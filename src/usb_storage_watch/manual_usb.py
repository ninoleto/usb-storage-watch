# SPDX-License-Identifier: MIT
"""Manual, unmounted-only USB operations. Never mount or operate a shared hub."""
import errno
import fcntl
import json
import os
from pathlib import Path
import stat
import time


def unsupported(w, message):
    error = w.Unsafe('Unsupported: ' + message)
    error.standby_result = 'unsupported'  # Existing worker result protocol.
    return error


def identity(w):
    dev = w.device_number('/dev/disk/by-uuid/' + w.DISK_UUID)
    w.block_checks(dev, w.DISK_UUID)
    w.drives.verify_hardware(w, dev, w.DISK_UUID)
    device = w.usb.physical_usb_device(Path('/sys/dev/block') / dev)
    props = w.udev(dev)
    if device is None or not props.get('ID_SERIAL'):
        raise unsupported(w, 'the selected filesystem has no verifiable USB device identity.')
    if (device / 'bDeviceClass').read_text().strip() == '09':
        raise unsupported(w, 'a shared USB hub cannot be reset as a disk.')
    blocks = [p for p in Path('/sys/class/block').iterdir()
              if p.resolve().is_relative_to(device)]
    if len([p for p in blocks if not (p / 'partition').exists()]) != 1:
        raise unsupported(w, 'this USB device contains multiple disks; independent reset is unverified.')
    interfaces = list(device.glob(device.name + ':*'))
    if not interfaces or any((p / 'bInterfaceClass').read_text().strip() != '08' for p in interfaces):
        raise unsupported(w, 'resetting this USB device could affect a non-storage interface.')
    bus, address = (int((device / k).read_text()) for k in ('busnum', 'devnum'))
    return dict(uuid=w.DISK_UUID, serial=props['ID_SERIAL'], device=str(device),
                bus=bus, address=address, usb_ids=(device / 'idVendor').read_text().strip() + ':' +
                (device / 'idProduct').read_text().strip(),
                node=f'/dev/bus/usb/{bus:03d}/{address:03d}',
                known_devs=sorted((p / 'dev').read_text().strip() for p in blocks),
                known_sources=sorted('/dev/' + p.name for p in blocks))


def unmounted(w, value=None):
    value = value or identity(w)
    for row in w.read_rows():
        if row['dev'] in value['known_devs'] or w.covers(w.MOUNT, row['target']):
            raise w.Unsafe('Unmount this drive and its dependent storage before resetting USB.')
    for backing in Path('/sys/class/block').glob('loop*/loop/backing_file'):
        if w.covers(w.MOUNT, backing.read_text().strip()):
            raise w.Unsafe('A dependent image loop remains attached; USB reset refused.')
    # All namespaces, raw device aliases, ordinary FDs, working paths, mmap and swap.
    w.usb.require_process_isolation(w, value)
    return value


def capabilities(w):
    value = identity(w)
    node = Path(value['node']).stat()
    if not stat.S_ISCHR(node.st_mode) or os.major(node.st_rdev) != 189:
        raise unsupported(w, 'Linux USB device reset is unavailable on this connection.')
    return value


def reset(w):
    """Use the existing guarded port path where supported, otherwise a leaf ioctl.

    A failed operation is never followed by another reset method automatically.
    """
    value = unmounted(w, capabilities(w))
    receipt = w.STATE_DIR / 'manual-usb.json'
    if receipt.exists():
        previous = json.loads(receipt.read_text())
        if not isinstance(previous, dict) or previous.get('phase') not in ('intent', 'verified', 'unsupported'):
            raise w.Unsafe('The previous device-reset receipt is invalid; no reset was sent.')
        if previous.get('boot') == w.boot_id() and previous.get('phase') == 'intent':
            raise w.Unsafe('A previous device reset has an uncertain outcome; no reset was repeated. Review its recorded result first.')
    pending = w.usb.load(w.usb_context())
    if pending and pending['phase'] != 'enabled':
        raise w.Unsafe('A previous USB enable obligation is unresolved; no new reset was sent.')
    try:
        request = w.usb.select_current(w.usb_context(), w.controls.request(w))
        w.usb.port_identity(w.usb_context())
    except (OSError, ValueError, w.Unsafe):
        request = None  # Unsupported port control does not imply unsupported leaf reset.
    if request is not None:
        result = w.usb.cycle(w.usb_context(), request)
        if not result.get('ready'):
            raise w.Unsafe(result['reason'])
        unmounted(w)
        return 'Software USB reconnect verified. The disk remains unmounted. Electrical power removal is not verified.'
    with w.drives.port_lock(w, value['device']):
        if unmounted(w, capabilities(w)) != value:
            raise w.Unsafe('USB identity or address changed before reset; no reset was sent.')
        fd = os.open(value['node'], os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 189
                    or os.minor(info.st_rdev) != (value['bus'] - 1) * 128 + value['address'] - 1
                    or identity(w) != value):
                raise w.Unsafe('USB device node identity changed; reset refused.')
            w.atomic_write(w.STATE_DIR / 'manual-usb.json', json.dumps(dict(
                boot=w.boot_id(), uuid=w.DISK_UUID, method='device-reset', phase='intent', time=w.timestamp())) + '\n')
            try:
                fcntl.ioctl(fd, (ord('U') << 8) | 20, 0)  # Linux USBDEVFS_RESET.
            except OSError as exc:
                if exc.errno in (errno.ENOTTY, errno.EOPNOTSUPP, errno.ENOSYS):
                    w.atomic_write(receipt, json.dumps(dict(boot=w.boot_id(), uuid=w.DISK_UUID,
                        method='device-reset', phase='unsupported', time=w.timestamp())) + '\n')
                    raise unsupported(w, 'this kernel/device does not implement USB device reset.') from exc
                raise w.Unsafe('USB device reset failed (errno ' + str(exc.errno) + '); no other reset was attempted.') from exc
        finally:
            os.close(fd)
        deadline = time.monotonic() + w.SETTINGS['usb']['enumeration_seconds']
        while True:
            try:
                after = identity(w)
                if any(after[k] != value[k] for k in ('uuid', 'serial', 'device', 'usb_ids')):
                    raise w.Unsafe('Returned device identity changed; reset verification failed.')
                unmounted(w, after)
                break
            except FileNotFoundError:
                if time.monotonic() >= deadline:
                    raise w.Unsafe('USB reset was accepted but the expected disk did not return before the deadline.')
                time.sleep(.2)
        w.atomic_write(w.STATE_DIR / 'manual-usb.json', json.dumps(dict(
            boot=w.boot_id(), uuid=w.DISK_UUID, method='device-reset', phase='verified', time=w.timestamp())) + '\n')
        return 'Software USB device reset completed; disk identity verified and left unmounted. Electrical power removal is not verified.'
