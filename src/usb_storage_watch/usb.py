# SPDX-License-Identifier: MIT
"""Isolated sysfs USB recovery helper for the EXISTING Storage monitor.

No daemon, SMTP or service management. Software reconnect is not proof of power loss.
Only the pinned port's disable attribute can be written; cleanup only enables.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import select
import stat
import subprocess
import sys
import tempfile
import time

PROFILE = None
HOST_VERIFIED = False
REASON = 'Software USB reconnect is unavailable until an isolated direct root port is verified.'
CONTROLLER = ROOT_HUB = PORT = DEVICE = Path('/nonexistent-usw-unqualified')
CONTROLLER_REAL = CANONICAL = DEVICE_REAL = FIRMWARE = ''
CONTROLLER_IDS = ROOT_HUB_IDS = {}
VID = PID = DISK_SERIAL = ''
USB_DEVICES = Path('/sys/bus/usb/devices')
SYS_DEV_BLOCK = Path('/sys/dev/block')
SYS_BLOCK = Path('/sys/class/block')
PROC = Path('/proc')
UUID_DIR = Path('/dev/disk/by-uuid')
POWER_CACHE = {}


def peer_diagnostic(port):
    """Read-only assessment, never a qualification or permission to reset.

    Linux USB2/USB3 peers can be the two interfaces of one connector. The
    existing executor/cleanup ledger owns only one logical port; it cannot
    safely execute or recover an interrupted two-interface operation.
    """
    port = Path(port)
    link = port / 'peer'
    if not link.exists() and not link.is_symlink():
        return None
    prefix = 'USB2/USB3 peer link detected. A peer can represent the same physical connector; it does not prove isolation is impossible. '
    try:
        primary, peer = port.resolve(strict=True), link.resolve(strict=True)
        def root(p):
            match = re.fullmatch(r'usb(\d+)-port([1-9]\d*)', p.name)
            if not match or p.parent.name != match[1] + '-0:1.0' or p.parent.parent.name != 'usb' + match[1]:
                raise ValueError('The peer is not a direct root port; shared hubs are not supported.')
            return p.parent.parent
        first, second = root(primary), root(peer)
        if primary == peer or (peer / 'peer').resolve(strict=True) != primary:
            raise ValueError('The peer mapping is not reciprocal; independent connector control is unverified.')
        if first.parent != second.parent or not re.fullmatch(r'[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]', first.parent.name):
            raise ValueError('The peer ports do not resolve to the same PCI controller; connector identity is unverified.')
        speeds = [float((hub / 'speed').read_text().strip()) for hub in (first, second)]
        if not ((speeds[0] <= 480 and speeds[1] >= 5000) or (speeds[1] <= 480 and speeds[0] >= 5000)):
            raise ValueError('The mapping is not a verified USB2/USB3 root-port pair.')
        for member in (primary, peer):
            if (member / 'disable').is_symlink() or not (member / 'disable').is_file():
                raise ValueError('Both interfaces must expose their own port disable control; one is missing or replaced.')
        if (peer / 'device').exists() or (peer / 'device').is_symlink():
            child = (peer / 'device').resolve(strict=True)
            def read_label(name):
                try: return (child / name).read_text().strip()[:100]
                except OSError: return ''
            label = ' '.join(filter(None, (read_label('manufacturer'), read_label('product')))) or child.name
            raise ValueError('Selected port '+primary.name+' is paired with '+peer.name+
                             ', which reports an attached device: '+label+' ('+child.name+'). '
                             'Its association with this disk is unproven; it must not be disconnected.')
        message = ('USB2/USB3 companion ports identified; the companion is empty. '
                   'Only the selected software port is reconnected. Electrical power cycling is not verified.')
        return dict(kind='paired-software', paired=True, supported=True, message=message,
                    ports=[str(primary), str(peer)])
    except (OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else 'Peer identity or controls are unreadable/dangling; independent control cannot be established.'
        return dict(kind='peer-unverified', paired=False, supported=False,
                    message=prefix + reason + ' Keep resets off; ordinary filesystem remounting remains available.')


def configure(profile):
    global PROFILE, HOST_VERIFIED, CONTROLLER, CONTROLLER_REAL, CONTROLLER_IDS
    global ROOT_HUB, ROOT_HUB_IDS, PORT, CANONICAL, DEVICE, DEVICE_REAL, FIRMWARE, VID, PID, DISK_SERIAL
    PROFILE = profile
    HOST_VERIFIED = bool(profile and (profile['qualified'] or profile.get('mode') == 'software'))
    if profile:
        CONTROLLER, ROOT_HUB, PORT, DEVICE = (Path(profile[k]) for k in ('controller','root_hub','port','device'))
        CONTROLLER_REAL, CANONICAL, DEVICE_REAL, FIRMWARE = (profile[k] for k in ('controller_real','canonical','device_real','firmware'))
        CONTROLLER_IDS, ROOT_HUB_IDS = profile['controller_ids'], profile['root_hub_ids']
        VID, PID, DISK_SERIAL = profile['vid'], profile['pid'], profile['disk_serial']

DISABLE_SECONDS = 1.0
ENUM_SECONDS = 20.0
POLL_SECONDS = 0.25
IO_TIMEOUT = 3.0
CHECK_TIMEOUT = 15.0
GUARD_READY_TIMEOUT = 2.0
GUARD_SECONDS = CHECK_TIMEOUT + IO_TIMEOUT + DISABLE_SECONDS + 4.0
CLEANUP_TIMEOUT = 12.0


def ledger_path(w):
    return w.STATE_DIR / 'usb-reset.json'


def load(w):
    try:
        record = json.loads(ledger_path(w).read_text())
    except FileNotFoundError:
        return None
    if not isinstance(record, dict):
        raise w.Unsafe('Invalid USB ledger')
    profile = w.settings.usb_profile(record.get('profile'), qualified=True)
    if (not isinstance(record, dict) or record.get('version') != 1
            or record.get('port') != profile['canonical'] or record.get('firmware') != profile['firmware']
            or record.get('number') != 1 or record.get('reset_count') != 1
            or record.get('phase') not in ('armed', 'disabling', 'enabling', 'enabled', 'enable_failed')
            or type(record.get('disable_issued')) is not bool
            or type(record.get('guard_ready')) is not bool
            or not isinstance(record.get('incident'), str)
            or not isinstance(record.get('attempted_at'), str)):
        raise w.Unsafe('USB reset ledger is invalid; no disable or arbitrary-path cleanup permitted.')
    return record


def update(w, unless_enabled=False, **values):
    with (w.STATE_DIR / 'usb-ledger.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = load(w)
        if record is None:
            raise w.Unsafe('USB reset ledger missing.')
        if unless_enabled and record['phase'] == 'enabled':
            return record
        record.update(values)
        w.atomic_write(ledger_path(w), json.dumps(record, indent=2) + '\n')
        return record


def attachment_token():
    """Kernel USB enumeration identity, not a power-status bit or a /dev name."""
    try:
        value={key:(DEVICE/key).read_text().strip() for key in ('busnum','devnum')}
        if not all(re.fullmatch(r'[1-9][0-9]*',v) for v in value.values()):raise ValueError('USB enumeration identity is unreadable; reconnect was not started.')
        return value
    except FileNotFoundError:return None


def reserve(w, request):
    # The recovery operation lock serializes reservations across workers.
    previous = load(w)
    if previous and (previous['incident'] == request['incident'] or previous['phase'] != 'enabled'):
        raise w.Unsafe('USB reset already consumed or an earlier port enable remains unresolved.')
    if request['number'] != 1 or request.get('usb_resets', 0):
        raise w.Unsafe('USB reset is forbidden after attempt 1 or a consumed reset budget.')
    before=attachment_token()
    if DEVICE.exists() and before is None:
        raise w.Unsafe('The connected USB device has no verifiable enumeration identity; reconnect was not started.')
    record = {'version': 1, 'incident': request['incident'], 'number': 1, 'reset_count': 1,
              'port': CANONICAL, 'firmware': FIRMWARE, 'phase': 'armed', 'profile': PROFILE,
              'attempted_at': w.timestamp(), 'boot': w.boot_id(),
              'disable_issued': False, 'guard_ready': False,
              'known_devs': request['known_devs'], 'known_sources': request.get('known_sources', []),
              'known_binding': request.get('known_binding'),
              'allow_present': request.get('allow_present', False),
              'manual': request.get('manual', False),
              'config_digest': request.get('config_digest'),
              'reason': 'Reset budget consumed before any port write.',
              'attachment_before':before, 'disconnect_observed':False,
              'return_ports': (peer_diagnostic(PORT) or {}).get('ports', [CANONICAL])}
    w.atomic_write(ledger_path(w), json.dumps(record, indent=2) + '\n')
    return record


def controller_identity(w):
    if not HOST_VERIFIED:
        raise w.Unsafe('No verified software USB port binding is available.')
    if (str(CONTROLLER.resolve(strict=True)) != CONTROLLER_REAL
            or str((CONTROLLER / 'driver').resolve(strict=True)) != '/sys/bus/pci/drivers/xhci_hcd'
            or str(ROOT_HUB.resolve(strict=True)) != CONTROLLER_REAL + '/' + ROOT_HUB.name
            or any((CONTROLLER / k).read_text().strip() != v for k, v in CONTROLLER_IDS.items())
            or any((ROOT_HUB / k).read_text().strip() != v for k, v in ROOT_HUB_IDS.items())):
        raise w.Unsafe('USB controller/root-hub identity differs from the qualified hardware.')


def port_identity(w, enabling=False):
    controller_identity(w)
    if str(PORT.resolve(strict=True)) != CANONICAL:
        raise w.Unsafe('USB port path no longer resolves to the pinned controller and port.')
    firmware = PORT / 'firmware_node'
    if (str(firmware.resolve(strict=True)) if firmware.exists() else CANONICAL) != FIRMWARE:
        raise w.Unsafe('USB port firmware identity changed.')
    if (PORT / 'disable').is_symlink() or not (PORT / 'disable').is_file():
        raise w.Unsafe('Pinned port disable attribute is missing or replaced.')
    if not (PORT / 'disable').stat().st_mode & 0o200:
        raise w.Unsafe('This USB port does not expose a writable software reconnect control.')
    if not enabling:
        peer = peer_diagnostic(PORT)
        if peer and not peer['supported']:
            raise w.Unsafe(peer['message'])


def hub_power(root):
    """Query only the root hub, once per attachment identity; never the HDD."""
    try:
        key = (str(root), (root / 'busnum').read_text().strip(), (root / 'devnum').read_text().strip())
        if key not in POWER_CACHE:
            result = subprocess.run(['/usr/bin/lsusb', '-v', '-s', key[1] + ':' + key[2]],
                                    capture_output=True, text=True, timeout=3, check=False,
                                    env=dict(os.environ, LC_ALL='C'))
            match = re.search(r'wHubCharacteristic[s]?\s+0x([0-9a-f]+)', result.stdout, re.I)
            POWER_CACHE[key] = {0:'ganged', 1:'individual', 2:'none', 3:'none'}.get(int(match[1], 16) & 3, 'unknown') if match else 'unknown'
        return POWER_CACHE[key]
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def physical_usb_device(block_sys):
    """Read the physical USB device from kernel sysfs, not udev ID_BUS.

    SATA disks behind USB-to-SATA adapters may correctly report ID_BUS=ata.
    No USB device is accepted without a real USB ancestor and root hub.
    """
    path = Path(block_sys).resolve(strict=True)
    for ancestor in (path, *path.parents):
        if not re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*(?:\.[1-9][0-9]*)*', ancestor.name):
            continue
        bus = ancestor.name.split('-', 1)[0]
        if not ((ancestor / 'idVendor').is_file() and (ancestor / 'idProduct').is_file()):
            continue
        if any(root.name == 'usb' + bus and (root / 'idVendor').is_file()
               and (root / 'idProduct').is_file() for root in ancestor.parents):
            return ancestor
    return None


def is_verified_usb_block(block_sys, props):
    """Require physical USB sysfs ancestry and positive disk serial metadata."""
    if not isinstance(props, dict) or not props.get('ID_SERIAL'):
        return False
    try:
        return physical_usb_device(block_sys) is not None
    except (OSError, ValueError):
        return False


def discover(w, dev):
    w.block_checks(dev, w.DISK_UUID)
    props = w.udev(dev)
    real = (SYS_DEV_BLOCK / dev).resolve(strict=True)
    device = physical_usb_device(real)
    if device is None or not props.get('ID_SERIAL'):
        raise w.Unsafe('The disk is not verified as USB-attached hardware with a stable serial number.')
    if not re.fullmatch(r'\d+-\d+', device.name):
        raise w.Unsafe('An intermediate USB hub is connected. Connect this drive directly to a motherboard USB port for complete recovery.')
    bus, number = device.name.split('-')
    root = USB_DEVICES / ('usb' + bus)
    controller = device.parent.parent
    port = USB_DEVICES / f'{bus}-0:1.0/usb{bus}-port{number}'
    def values(path, keys): return {key:(path / key).read_text().strip() for key in keys}
    profile = dict(controller='/sys/bus/pci/devices/' + controller.name, controller_real=str(controller),
                   controller_ids=values(controller, ('vendor','device','subsystem_vendor','subsystem_device','class','revision')),
                   root_hub=str(root), root_hub_ids=values(root, ('idVendor','idProduct','serial')),
                   port=str(port), canonical=str(port.resolve(strict=True)), device=str(USB_DEVICES / device.name),
                   device_real=str(device), firmware=str((port / 'firmware_node').resolve(strict=True)) if (port / 'firmware_node').exists() else str(port.resolve(strict=True)),
                   vid=(device / 'idVendor').read_text().strip(), pid=(device / 'idProduct').read_text().strip(),
                   disk_serial=props['ID_SERIAL'], qualified=False, qualification=None, mode='software')
    w.settings.usb_profile(profile, qualified=True)
    if hub_power(root) == 'ganged':
        raise w.Unsafe('This hub reports shared power switching; reconnecting one port could affect other devices. Software port reconnect is unavailable here.')
    return profile


def current_record(w):
    try:
        value = json.loads((w.STATE_DIR / 'usb-binding.json').read_text())
        if not isinstance(value, dict):
            raise ValueError('USB connection record is invalid.')
        return value if value.get('uuid') == w.DISK_UUID else None
    except FileNotFoundError:
        return None


def bind_current(w, dev):
    """Rebind the same UUID/hardware to its live root port, including unmounted disks."""
    previous = current_record(w)
    configured = w.SETTINGS['usb']['profile']
    expected = (configured or {}).get('disk_serial') or (previous or {}).get('serial')
    if not expected:
        props = w.udev(dev)
        if props.get('ID_FS_UUID') == w.DISK_UUID and props.get('ID_FS_TYPE') == 'ext4':
            expected = props.get('ID_SERIAL')
    try:
        profile = discover(w, dev)
        if expected and profile['disk_serial'] != expected:
            raise w.Unsafe('The UUID is now on different USB hardware; software reconnect refused.')
        configure(profile)
        binding = healthy_binding(w, dev)
        value = dict(uuid=w.DISK_UUID, boot=w.boot_id(), serial=profile['disk_serial'],
                     profile=profile, binding=binding)
        if previous and previous.get('binding'):
            old = dict(previous['binding']); old.pop('observed_at', None)
            new = dict(binding); new.pop('observed_at', None)
            if old == new and previous.get('profile') == profile:
                return previous['binding']
    except (OSError, ValueError, w.Unsafe) as exc:
        # Observing a moved/unsupported connection revokes the previous port.
        value = dict(uuid=w.DISK_UUID, boot=w.boot_id(), serial=expected, profile=None,
                     reason=str(exc) if isinstance(exc, w.Unsafe) else 'Current USB connection could not be verified.')
        configure(None)
        if w.STATE_DIR.exists() and previous != value:
            w.atomic_write(w.STATE_DIR / 'usb-binding.json', json.dumps(value) + '\n')
        raise
    if w.STATE_DIR.exists():
        w.atomic_write(w.STATE_DIR / 'usb-binding.json', json.dumps(value) + '\n')
    return binding


def select_current(w, request):
    try:
        dev = w.device_number(UUID_DIR / w.DISK_UUID)
    except FileNotFoundError:
        saved = current_record(w)
        if saved is None:
            return request  # Legacy same-boot known binding remains guarded below.
        if saved.get('boot') != w.boot_id() or not saved.get('profile'):
            raise w.Unsafe((saved or {}).get('reason', 'No verified USB port binding for this boot.'))
        configure(w.settings.usb_profile(saved['profile'], qualified=True))
        binding = saved['binding']
    else:
        binding = bind_current(w, dev)
    return request | dict(known_binding=binding, known_sources=binding['sources'],
                          known_devs=sorted(set(request.get('known_devs', []) + [binding['main_dev']])))


def port_connection_details(w):
    def read(path):
        try: return Path(path).read_text().strip()
        except OSError: return 'Unknown'
    result = dict(board_vendor=read('/sys/class/dmi/id/board_vendor'), board_model=read('/sys/class/dmi/id/board_name'),
                  software_reconnect=False, power_switching='unknown', electrical_verified=False, direct=None,
                  power_cycle_available=False,
                  power_message='Electrical power removal is not verified. This build provides software reconnect only. '
                                'USB control cannot switch off a separate disk power supply.')
    try:
        try:
            dev = w.device_number(UUID_DIR / w.DISK_UUID)
        except FileNotFoundError:
            saved = current_record(w)
            if not saved or saved.get('boot') != w.boot_id() or not saved.get('profile'):
                raise w.Unsafe('Drive disconnected. No verified port binding is available for this boot.') from None
            request = select_current(w, dict(known_devs=[]))
            port_identity(w)
            validate_saved_binding(w, request)
            return result | dict(software_reconnect=True, direct=True, controller=PROFILE['controller'],
                                 controller_ids=PROFILE['controller_ids'], port=PROFILE['port'],
                                 usb_ids=VID + ':' + PID, peer=peer_diagnostic(PORT), power_switching=hub_power(ROOT_HUB),
                                 message='Drive disconnected. Its last verified port is retained; live isolation checks run before reconnecting.')
        real = (SYS_DEV_BLOCK / dev).resolve(strict=True)
        device = next((p for p in real.parents if (p / 'idVendor').is_file()), None)
        root = next((p for p in real.parents if re.fullmatch(r'usb\d+', p.name)), None)
        if device and root:
            bus = root.name[3:]
            number = device.name.split('-')[1].split('.')[0]
            port = root / f'{bus}-0:1.0/usb{bus}-port{number}'
            result.update(direct='.' not in device.name, controller=str(root.parent),
                          controller_ids={k:read(root.parent / k) for k in ('vendor','device','subsystem_vendor','subsystem_device')},
                          port=str(port), usb_ids=read(device / 'idVendor') + ':' + read(device / 'idProduct'),
                          peer=peer_diagnostic(port), power_switching=hub_power(root))
        bind_current(w, dev)
        # Availability is a current topology assessment, not merely a saved
        # binding. A peer can become occupied between binding and this reply.
        port_identity(w)
        result.update(software_reconnect=True, direct=True, controller=PROFILE['controller'],
                      controller_ids=PROFILE['controller_ids'], port=PROFILE['port'], serial=DISK_SERIAL,
                      usb_ids=VID + ':' + PID, peer=peer_diagnostic(PORT), power_switching=hub_power(ROOT_HUB),
                      message='Software USB port reconnect is available. Electrical power cycling is not independently verified.')
    except (OSError, ValueError, w.Unsafe) as exc:
        message = str(exc) if isinstance(exc, w.Unsafe) else 'Connect the selected drive to inspect its USB connection.'
        result.update(message=message)
    return result


def connection_details(w):
    result = port_connection_details(w)
    result['last_known'] = not (UUID_DIR / w.DISK_UUID).exists()
    result['manual_reset_available'] = False
    try:
        dev = w.device_number(UUID_DIR / w.DISK_UUID)
        device = physical_usb_device(SYS_DEV_BLOCK / dev)
        if device:
            result.update(topology=device.name, port=str((device / 'port').resolve()),
                          bus_address=f"{int((device / 'busnum').read_text()):03d}/{int((device / 'devnum').read_text()):03d}",
                          usb_ids=(device / 'idVendor').read_text().strip()+':'+(device / 'idProduct').read_text().strip(),
                          serial=(device / 'serial').read_text().strip() if (device / 'serial').exists() else None)
        if hasattr(w, 'manual_usb'):
            value = w.manual_usb.capabilities(w)
            result['reset_method'] = 'port-reconnect' if result['software_reconnect'] else 'device-reset'
            result['reset_status'] = 'blocked'
            w.manual_usb.unmounted(w, value)
            result.update(manual_reset_available=True, reset_status='available',
                          message=('Guarded software port reconnect' if result['software_reconnect'] else 'Guarded software device reset') + ' available; the disk will remain unmounted.')
    except (OSError, ValueError, w.Unsafe) as exc:
        result.setdefault('reset_status', 'unsupported' if getattr(exc, 'standby_result', None) == 'unsupported' else 'unavailable')
        if not result['last_known']:
            result['message'] = str(exc) if isinstance(exc, w.Unsafe) else 'USB capability inspection failed; refresh the connection.'
    return result


def binding_signature(w):
    return {'controller': CONTROLLER_REAL, 'controller_ids': dict(CONTROLLER_IDS),
            'root_hub_ids': dict(ROOT_HUB_IDS), 'port': CANONICAL, 'firmware': FIRMWARE,
            'usb_device': DEVICE_REAL, 'vid': VID, 'pid': PID,
            'disk_serial': DISK_SERIAL, 'uuid': w.DISK_UUID, 'fs': 'ext4', 'boot': w.boot_id()}


def healthy_binding(w, dev):
    """Capture the exact live filesystem/serial/port, mounted or unmounted."""
    port_identity(w)
    identity = w.udev(dev)
    sysdev = Path('/sys/dev/block') / dev
    if ((DEVICE / 'idVendor').read_text().strip() != VID
            or (DEVICE / 'idProduct').read_text().strip() != PID
            or str(DEVICE.resolve(strict=True)) != DEVICE_REAL
            or str((DEVICE / 'port').resolve(strict=True)) != CANONICAL
            or str((PORT / 'device').resolve(strict=True)) != DEVICE_REAL
            or (PORT / 'disable').read_text().strip() != '0'
            or (PORT / 'state').read_text().strip() != 'configured'
            or not str(sysdev.resolve(strict=True)).startswith(DEVICE_REAL + '/')
            or identity.get('ID_SERIAL') != DISK_SERIAL
            or identity.get('ID_FS_UUID') != w.DISK_UUID or identity.get('ID_FS_TYPE') != 'ext4'):
        raise w.Unsafe('Healthy filesystem is not bound to the qualified Storage USB port/disk.')
    sources = ['/dev/' + sysdev.resolve(strict=True).name]
    if (sysdev / 'partition').exists():
        sources.append('/dev/' + sysdev.resolve(strict=True).parent.name)
    return binding_signature(w) | {'main_dev': dev, 'sources': sources, 'observed_at': w.timestamp()}


def validate_saved_binding(w, request):
    saved = request.get('known_binding')
    if (not isinstance(saved, dict)
            or any(saved.get(k) != v for k, v in binding_signature(w).items())
            or saved.get('main_dev') not in request.get('known_devs', [])
            or not saved.get('sources') or saved['sources'] != request.get('known_sources')
            or not isinstance(saved.get('observed_at'), str)):
        raise w.Unsafe('Prior healthy Storage identity/UUID/port for this boot is missing or changed; USB reset skipped.')


def usb_present(w):
    # Even an unexpected device on the target port prevents disabling it.
    if DEVICE.exists() or (PORT / 'device').exists() or (PORT / 'device').is_symlink():
        return True
    for path in USB_DEVICES.iterdir():
        try:
            if ((path / 'idVendor').read_text().strip() == VID
                    and (path / 'idProduct').read_text().strip() == PID):
                return True  # Generic bridge serial is not unique; fail conservatively.
        except FileNotFoundError:
            continue
    return False


def kernel_only_fd_target(target):
    """Positive identification of kernel-only fds; they cannot reference a USB mount.

    This is NOT an exception for unreadable ordinary descriptors. Unknown handles
    must still pass the original stat/mount identity checks or fail closed.
    """
    return bool(re.fullmatch(r'(?:socket:\[[0-9]+\]|pipe:\[[0-9]+\]|anon_inode:\[[A-Za-z0-9_.+/-]+\]|anon_inode:inotify|memfd:[^\r\n]+)',target))


def descriptor_identity(proc, number):
    """Kernel mount/inode identity, not a pathname-based ownership guess."""
    value = {}
    for line in (proc / 'fdinfo' / number).read_text().splitlines():
        key, separator, text = line.partition(':')
        if separator and key in ('mnt_id', 'ino'):
            if key in value or not re.fullmatch(r'[1-9][0-9]*', text.strip()):
                raise ValueError('Ambiguous descriptor identity')
            value[key] = text.strip()
    if set(value) != {'mnt_id', 'ino'}:
        raise ValueError('Incomplete descriptor identity')
    return value


def verify_unrelated_descriptor(w, proc, fd, target, known, rows):
    """Alternative proof when procfs cannot stat a live descriptor directly.

    Resolve only its already reported path in that process's root, and require
    the inode and device to match fdinfo/mountinfo. Recheck all three identities
    before accepting the result. Missing, deleted, moved and unreadable files
    remain unverified. fdinfo alone cannot rule out an open raw block device.
    """
    if not target.startswith('/') or target.endswith(' (deleted)'):
        return False
    try:
        before = descriptor_identity(proc, fd.name)
        mounts = [row for row in rows if row['id'] == before['mnt_id']]
        if len(mounts) != 1 or mounts[0]['dev'] in known:
            return False
        row = mounts[0]
        info = Path(str(proc / 'root') + target).stat()
        if (str(info.st_ino) != before['ino'] or
                f'{os.major(info.st_dev)}:{os.minor(info.st_dev)}' != row['dev']):
            return False
        if (stat.S_ISBLK(info.st_mode) and
                f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}' in known):
            raise w.Unsafe('An open block-device handle still references Storage; reset skipped.')
        after_rows = w.parse_mounts((proc / 'mountinfo').read_text())
        after_mounts = [item for item in after_rows if item['id'] == before['mnt_id']]
        return (after_mounts == mounts and descriptor_identity(proc, fd.name) == before
                and os.readlink(fd) == target)
    except (OSError, ValueError, KeyError, IndexError):
        return False


def require_absent_and_isolated(w, request, progress=None):
    port_identity(w)
    if not request.get('known_devs'):
        raise w.Unsafe('No prior healthy device identity recorded for this outage; USB reset skipped.')
    validate_saved_binding(w, request)
    present = usb_present(w)
    if present:
        if not request.get('allow_present'):
            raise w.Unsafe('A USB device/Storage bridge is still detected; USB reset skipped.')
        dev = w.device_number(UUID_DIR / w.DISK_UUID)
        healthy_binding(w, dev)  # Exact live serial/UUID/port, even when unmounted.
        w.mount_available(w.read_rows(), w.MOUNT, dev)
    else:
        if (UUID_DIR / w.DISK_UUID).exists():
            raise w.Unsafe('Expected device is present on a different port; reset skipped.')
        if (PORT / 'state').read_text().strip() != 'not attached':
            raise w.Unsafe('USB port does not report entirely absent; reset skipped.')
    if (PORT / 'disable').read_text().strip() != '0':
        raise w.Unsafe('Port is already disabled or its enabled state is unknown; no new reset.')
    for block in SYS_BLOCK.iterdir():
        if str(block.resolve()).startswith(DEVICE_REAL + '/'):
            if not present or '/dev/' + block.resolve().name not in request.get('known_sources', []):
                raise w.Unsafe('Unverified block device beneath Storage port; reset skipped.')
            w.namespace_available((block / 'dev').read_text().strip())
        backing = block / 'loop/backing_file'
        try:
            if w.covers(w.MOUNT, backing.read_text().strip()):
                raise w.Unsafe('Loop image on Storage remains attached; USB reset skipped.')
        except FileNotFoundError:
            pass
    require_process_isolation(w, request, progress)


def require_process_isolation(w, request, progress=None):
    """Shared fail-closed holder checks for both port reconnect and device reset."""
    # Check other mount namespaces, including containers, without entering them.
    # Inability to inspect any surviving namespace fails closed.
    known = set(request['known_devs'])
    for proc in PROC.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if progress: progress('process ' + proc.name + ' mount namespaces')
            rows = w.parse_mounts((proc / 'mountinfo').read_text())
            if any(r['dev'] in known or w.covers(w.MOUNT, r['target']) for r in rows):
                raise w.Unsafe('Storage/dependent loop is still mounted in a process namespace; reset skipped.')
            if progress: progress('process ' + proc.name + ' open handles')
            for fd in (proc / 'fd').iterdir():
                try:
                    raw_target = os.readlink(fd)
                    target = raw_target.removesuffix(' (deleted)')
                    if target in request.get('known_sources', []) or w.covers(w.MOUNT, target):
                        raise w.Unsafe('A recorded Storage device has an open handle; reset skipped.')
                    # /proc/<pid>/fd magic links to sockets, pipes and anonymous
                    # kernel fds can reject stat() despite readlink() proving their
                    # type. Do not treat such an EPERM as a USB storage holder.
                    # Unknown and normal filesystem fds MUST still be inspected.
                    if kernel_only_fd_target(target):
                        continue
                    try:
                        info = fd.stat()
                    except PermissionError as exc:
                        if w.process_exited(proc):
                            continue  # Kernel-confirmed process exit, no live descriptor.
                        if verify_unrelated_descriptor(w, proc, fd, raw_target, known, rows):
                            continue
                        raise w.Unsafe('Cannot inspect a live process file descriptor safely; USB port reconnect refused. '
                                       'Process ' + proc.name + ', descriptor ' + fd.name +
                                       ' could not be verified by descriptor or mount/inode identity. '
                                       'Target ' + repr(raw_target[:240]) + ', errno ' + str(exc.errno) + '. '
                                       'No USB port change was authorized.') from exc
                    if (f'{os.major(info.st_dev)}:{os.minor(info.st_dev)}' in known
                            or (stat.S_ISBLK(info.st_mode) and
                                f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}' in known)):
                        raise w.Unsafe('An open file/device still references Storage; reset skipped.')
                except FileNotFoundError:
                    continue
            if progress: progress('process ' + proc.name + ' working paths')
            for name in ('cwd', 'root', 'exe'):
                link = proc / name
                try:
                    if w.covers(w.MOUNT, os.readlink(link).removesuffix(' (deleted)')):
                        raise w.Unsafe('A process still references Storage; reset skipped.')
                    info = link.stat()
                    if f'{os.major(info.st_dev)}:{os.minor(info.st_dev)}' in known:
                        raise w.Unsafe('A process still uses the Storage filesystem; reset skipped.')
                except FileNotFoundError:
                    continue
            # mmap can outlive the descriptor and a lazy unmount.
            if progress: progress('process ' + proc.name + ' memory mappings')
            for line in (proc / 'maps').read_text().splitlines():
                fields = line.split(None, 5)
                major, minor = (int(n, 16) for n in fields[3].split(':'))
                if (f'{major}:{minor}' in known
                        or (len(fields) == 6 and w.covers(w.MOUNT, fields[5]))):
                    raise w.Unsafe('Mapped memory still references Storage; reset skipped.')
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as exc:
            # procfs may return EINVAL for mountinfo after process exit.
            # Require kernel pidfd exit proof; live/unknown failures still block.
            if exc.errno == 22 and w.process_exited(proc):
                continue
            raise
    for line in (PROC / 'swaps').read_text().splitlines()[1:]:
        source = w.unescape_mount(line.split()[0])
        if w.covers(w.MOUNT, source) or source in request.get('known_sources', []):
            raise w.Unsafe('Storage swap use remains active; reset skipped.')


def ready(w):
    try:
        # A companion may enumerate before its UUID exists. Wait while the old
        # device is absent; no operation or successful return is authorized here.
        if not DEVICE.exists():
            return False
        port_identity(w)
        if ((DEVICE / 'idVendor').read_text().strip() != VID
                or (DEVICE / 'idProduct').read_text().strip() != PID
                or str((DEVICE / 'port').resolve(strict=True)) != CANONICAL
                or str((PORT / 'device').resolve(strict=True)) != DEVICE_REAL):
            raise w.Unsafe('Unexpected USB device/port identity during enumeration.')
        dev = w.device_number('/dev/disk/by-uuid/' + w.DISK_UUID)
        identity = w.udev(dev)
        if not identity.get('ID_FS_UUID') or not identity.get('ID_FS_TYPE'):
            return False  # udev has not completed filesystem identification yet.
        w.block_checks(dev, w.DISK_UUID)
        if (not str((Path('/sys/dev/block') / dev).resolve()).startswith(DEVICE_REAL + '/')
                or identity.get('ID_SERIAL') != DISK_SERIAL):
            raise w.Unsafe('Returned filesystem is not the expected physical Storage disk.')
    except FileNotFoundError:
        return False  # USB attributes/links can appear before the UUID node.
    return True


def poll_ready(w, probe=None, clock=None, sleep=None):
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    probe = probe or (lambda: ready(w))
    start = clock()
    deadline = start + ENUM_SECONDS
    while True:
        now = clock()
        if now > deadline:
            return False, now - start
        detected = probe()
        now = clock()
        if detected and now <= deadline:
            return True, now - start
        remaining = deadline - now
        if remaining <= 0:
            return False, now - start
        sleep(min(POLL_SECONDS, remaining))


def io_worker(w, request):
    """Called ONLY in a supervised process; never from the observation loop."""
    action = request['action']
    if action not in ('disable', 'enable'):
        raise w.Unsafe('Unknown USB operation.')
    with (w.STATE_DIR / 'usb-io.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = load(w)
        if record is None or record['incident'] != request['incident']:
            raise w.Unsafe('USB operation has no matching durable intent.')
        update(w, io_stage=action + ' identity checks')
        def isolation(stage):
            update(w, io_stage=stage)
            last = time.monotonic()
            def progress(detail):
                nonlocal last
                now = time.monotonic()
                if now - last >= .5:
                    update(w, io_stage=stage + ': ' + detail)
                    last = now
            require_absent_and_isolated(w, record, progress=progress)
        if action == 'enable':
            configure(record['profile'])  # Owned pending enable survives config replacement/removal.
        else:
            select_current(w, record)
            if record['profile'] != PROFILE:
                raise w.Unsafe('USB connection changed after reservation; no disable allowed.')
        port_identity(w, enabling=action == 'enable')
        if action == 'disable':
            manual = record.get('manual') is True and record.get('config_digest') == w.CONFIG_DIGEST
            if not w.config_load().get('usb_reset_enabled', False) and not manual:
                raise w.Unsafe('USB recovery disabled before the port write; no disable allowed.')
            if (not HOST_VERIFIED or record['phase'] != 'armed' or record['disable_issued']
                    or not record['guard_ready']):
                raise w.Unsafe('USB disable is unqualified, unguarded or already consumed.')
            isolation('initial isolation checks')
            if (PORT / 'disable').read_text().strip() != '0':
                raise w.Unsafe('Port was already disabled; refusing a new reset.')
            update(w, phase='disabling', disable_issued=True, disable_started_at=w.timestamp())
            # Repeat after the durable write: a natural return while fsync was
            # running must not be disconnected. There is no kernel atomic
            # "disable only if absent" operation, so also check immediately below.
            isolation('isolation checks after durable intent')
        else:
            # Ignore recovery-off setting during cleanup: a pending enable is an
            # obligation, not a new reset. Never write "1" in cleanup.
            if record['phase'] == 'enabled':
                return
            update(w, phase='enabling', enable_started_at=w.timestamp())
        fd = os.open(PORT / 'disable', os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            if action == 'disable':
                if not record.get('allow_present') and (usb_present(w)
                        or (PORT / 'state').read_text().strip() != 'not attached'):
                    raise w.Unsafe('USB device returned before port write; disable cancelled.')
                isolation('final isolation checks before USB write')
            update(w, **{action+'_write_started_at':w.timestamp(), 'io_stage':action+' sysfs write'})
            os.write(fd, b'1\n' if action == 'disable' else b'0\n')
        finally:
            os.close(fd)
        update(w, **{action+'_written_at':w.timestamp(), 'io_stage':action+' readback'})
        expected = '1' if action == 'disable' else '0'
        if (PORT / 'disable').read_text().strip() != expected:
            if action == 'enable':
                raise w.Unsafe('USB port state did not confirm enable; manual intervention required.')
            # Linux disable_show reads the hub POWER bit, not logical attachment.
            # A completed disable_store disconnects the child even on hardware
            # that does not report switched power. Verify return after enabling.
            update(w, disable_written_at=w.timestamp(), power_off_reported=False,
                   io_warning='Software disconnect requested; hardware did not report power off.')
            return
        if action == 'disable':
            update(w, disable_written_at=w.timestamp(), disable_confirmed_at=w.timestamp(), power_off_reported=True)
        if action == 'enable':
            update(w, phase='enabled', enabled_at=w.timestamp(), reason='Port enabled and read back as 0.')


def bounded_io(w, action, incident):
    # Private input file avoids blocked stdin; no external shell or arbitrary path.
    with tempfile.TemporaryFile(dir=w.STATE_DIR) as data:
        data.write(json.dumps({'action': action, 'incident': incident}).encode())
        data.seek(0)
        child = subprocess.Popen([sys.executable, '-I', str(w.SCRIPT), '_usb-io'],
                                 stdin=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 pass_fds=w.WORKER_LOCK_FDS, close_fds=True)
    started = time.monotonic()
    deadline = started + (CHECK_TIMEOUT if action == 'disable' else IO_TIMEOUT)
    write_deadline = None
    while child.poll() is None and time.monotonic() < deadline:
        record=load(w)
        if action == 'disable' and record.get('disable_write_started_at') and write_deadline is None:
            # Safety inspection has its own bounded budget. A sysfs write still
            # gets at most IO_TIMEOUT; a changing stage cannot extend it again.
            write_deadline = min(started + CHECK_TIMEOUT + IO_TIMEOUT, time.monotonic() + IO_TIMEOUT)
            deadline = write_deadline
        if action=='disable' and record.get('attachment_before') and not record.get('disconnect_observed') and not DEVICE.exists():
            update(w,disconnect_observed=True,disconnect_observed_at=w.timestamp())
        time.sleep(0.05)
    if child.poll() is None:
        child.kill()  # Do not wait indefinitely for a kernel-uninterruptible write.
        # The kernel may have disconnected the child before its synchronous
        # sysfs write returns. SIGKILL can lose the post-write receipt. Retain
        # intent and evidence; enable cleanup waits for that writer's lock.
        try: child.wait(timeout=.1)
        except subprocess.TimeoutExpired: pass
        record=load(w) or {}
        update(w,io_timeout=action,io_timeout_at=w.timestamp())
        stage = record.get('io_stage', 'identity and isolation checks')
        if action == 'disable' and not record.get('disable_write_started_at'):
            raise w.Unsafe('Safety checks timed out during ' + stage + '. No USB disconnect write was started.')
        raise w.Unsafe('USB '+action+' worker timed out during '+stage+'. USB write completion is uncertain; cleanup and disk identity checks determine the outcome.')
    if child.returncode:
        reason = (load(w) or {}).get('io_error', 'Port state could not be verified.')
        raise w.Unsafe('USB ' + action + ' failed: ' + reason)


def ensure_enabled(w):
    record = load(w)
    if record is None or record['phase'] == 'enabled':return True
    last = ''
    deadline=time.monotonic()+CLEANUP_TIMEOUT
    # A killed kernel write can still hold usb-io.lock. Do not spend both enable
    # attempts immediately on EAGAIN, or race a late disable with an enable.
    for _ in range(2):  # Enable-only retries; never another disable.
        with (w.STATE_DIR/'usb-io.lock').open('a') as lock:
            while True:
                if (load(w) or {}).get('phase')=='enabled':return True
                try:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    fcntl.flock(lock,fcntl.LOCK_UN);break
                except BlockingIOError:
                    if time.monotonic()>=deadline:
                        last='USB writer is still busy; enable cleanup remains pending. No new disable or mount is allowed.';break
                    time.sleep(.05)
        if last.startswith('USB writer is still busy'):break
        try:
            bounded_io(w, 'enable', record['incident'])
            if load(w)['phase'] == 'enabled':return True
            last = 'Enable returned without a durable enabled-state verification.'
        except (OSError, ValueError, w.Unsafe) as exc:last = str(exc)
        if load(w)['phase'] == 'enabled':return True
    latest = update(w, unless_enabled=True, phase='enable_failed', reason=last, enable_failed_at=w.timestamp())
    if latest['phase'] == 'enabled':return True
    w.log('USB RE-ENABLE FAILED: ' + last + ' Pending enable retained; all recovery actions blocked.')
    return False


class Guardian:
    """Short-lived child of the existing service; survives recovery-worker killpg."""
    def __init__(self, w, incident):
        read_fd, self.write_fd = os.pipe()
        try:
            with tempfile.TemporaryFile(dir=w.STATE_DIR) as data:
                data.write(json.dumps({'incident': incident, 'lifeline': read_fd}).encode())
                data.seek(0)
                self.proc = subprocess.Popen([sys.executable, '-I', str(w.SCRIPT), '_usb-guard'],
                    stdin=data, stdout=subprocess.DEVNULL, stderr=None, close_fds=True,
                    start_new_session=True, pass_fds=(read_fd,*w.WORKER_LOCK_FDS))
        except BaseException:
            os.close(self.write_fd)
            raise
        finally:
            os.close(read_fd)
        deadline = time.monotonic() + GUARD_READY_TIMEOUT
        while time.monotonic() < deadline:
            if load(w)['guard_ready']:
                return
            if self.proc.poll() is not None:
                break
            time.sleep(0.05)
        self.close()
        raise w.Unsafe('USB enable guardian did not arm; no disable permitted.')

    def close(self):
        if self.write_fd is not None:
            os.close(self.write_fd)
            self.write_fd = None


def guard_worker(w, request):
    record = load(w)
    if record is None or record['incident'] != request['incident']:
        raise w.Unsafe('Enable guardian incident mismatch.')
    update(w, guard_ready=True)
    end = time.monotonic() + GUARD_SECONDS
    try:
        while time.monotonic() < end:
            if load(w)['phase'] == 'enabled':
                return
            reads, _, _ = select.select([request['lifeline']], [], [], max(0, min(0.1, end-time.monotonic())))
            if reads and not os.read(request['lifeline'], 1):
                break  # Parent exited, including SIGKILL or unexpected crash.
    finally:
        os.close(request['lifeline'])
        if not ensure_enabled(w):
            raise w.Unsafe('USB guardian could not re-enable the port; cleanup remains pending.')


def cycle(w, request):
    if request['number'] != 1 or request.get('usb_resets', 0):
        return {'reset_count': request.get('usb_resets', 0), 'reason': 'USB reset budget unavailable.', 'ready': False}
    if not request.get('allow_usb'):
        return {'reset_count': 0, 'reason': 'USB reset disabled by recovery configuration.', 'ready': False}
    try:
        request = select_current(w, request)
    except (OSError, ValueError, w.Unsafe) as exc:
        return {'reset_count': 0, 'reason': 'USB reconnect safely skipped: ' + str(exc), 'ready': False}
    if not HOST_VERIFIED:
        return {'reset_count': 0, 'reason': REASON, 'ready': False}
    try:
        require_absent_and_isolated(w, request)
    except (OSError, ValueError, w.Unsafe) as exc:
        return {'reset_count': 0, 'reason': 'USB reset safely skipped: ' + str(exc), 'ready': False}
    coordination=getattr(w,'drives',None)
    if coordination is None:return cycle_write(w,request)  # Explicit isolated test contexts.
    try:
        with coordination.port_lock(w,CANONICAL):
            require_absent_and_isolated(w,request)  # Recheck under the shared physical-port lock.
            return cycle_write(w,request)
    except BlockingIOError:
        return {'reset_count':0,'reason':'This USB port is already being recovered by another drive. No disable was sent.','ready':False}


def returned_binding(w, record):
    """Accept a return on a previously verified companion, without resetting it.

    The old port must already be enabled. UUID, disk serial, VID:PID, controller
    and the captured reciprocal port pair all remain mandatory.
    """
    try:
        dev = w.device_number(UUID_DIR / w.DISK_UUID)
        device = physical_usb_device(SYS_DEV_BLOCK / dev)
        if device is None or str(device) == DEVICE_REAL:
            return
        candidate = discover(w, dev)
        original = record['profile']
        if (candidate['canonical'] not in record.get('return_ports', [original['canonical']])
                or any(candidate[k] != original[k] for k in
                       ('controller_real', 'controller_ids', 'disk_serial', 'vid', 'pid'))
                or (Path(original['port']) / 'disable').read_text().strip() != '0'):
            raise w.Unsafe('Returned disk is outside the verified USB connector or its identity changed.')
        old = PROFILE
        try:
            configure(candidate)
            healthy_binding(w, dev)
        except BaseException:
            configure(old)
            raise
        bind_current(w, dev)
    except FileNotFoundError:
        return  # Wait for USB/udev enumeration to complete.


def cycle_write(w,request):
    reserve(w, request)
    guardian = None
    failure = None
    try:
        guardian = Guardian(w, request['incident'])
        bounded_io(w, 'disable', request['incident'])
        time.sleep(DISABLE_SECONDS)
    except BaseException as exc:
        failure = exc
    finally:
        try:
            enabled = ensure_enabled(w)
        finally:
            if guardian is not None:
                guardian.close()
    if not enabled:
        raise w.Unsafe('USB port re-enable failed; no mount will be attempted. '+(load(w) or {}).get('reason','Enable could not be independently verified; manual review is required.'))
    if failure is not None:
        detail = str(failure) or 'Operation interrupted before it completed.'
        # A completed write may be followed by a bookkeeping/readback error.
        # Cleanup must succeed before testing the actual returned drive.
        if not any((load(w) or {}).get(key) for key in ('disable_written_at','disable_write_started_at')):
            raise w.Unsafe('USB reconnect was not performed. No USB disconnect write was started. '
                           'Port enabled state verified. ' + detail) from failure
        if not isinstance(failure, Exception):
            raise w.Unsafe('USB reconnect was interrupted after a disconnect write started. '
                           'Port enabled state verified; disk return was not verified. ' + detail) from failure
    record=load(w)
    def returned():
        returned_binding(w, record)
        if not ready(w):return False
        # For a connected disk, require a new kernel enumeration or an observed
        # disconnect. An unchanged UUID alone is not evidence of reconnection.
        before=record.get('attachment_before')
        after=attachment_token()
        return before is None or record.get('disconnect_observed') or (after is not None and after!=before)
    detected, elapsed = poll_ready(w,probe=returned)
    update(w, enumeration_finished_at=w.timestamp(), enumeration_seconds=elapsed,
           enumeration_ready=detected)
    detail = (f'Expected USB device and UUID ready after {elapsed:.2f}s.' if detected
              else f'No verified USB reconnection after {elapsed:.2f}s: the expected disk did not return with a new attachment identity.')
    if failure is not None:
        detail += ' Reconnect warning: ' + str(failure)
    if (load(w) or {}).get('io_warning'):
        detail += ' ' + load(w)['io_warning']
    return {'reset_count': 1, 'reason': 'Port re-enablement verified. ' + detail + ' Electrical power removal is not verified.',
            'port_enabled':True, 'device_returned':detected, 'mount_verified':False,
            'operation':'software_reconnect', 'electrical_power_cut_verified':False,
            'cycled': True, 'ready': detected, 'enumeration_seconds': elapsed}


def incident_record(w, incident):
    record = load(w)
    return record if record and record['incident'] == incident else None
