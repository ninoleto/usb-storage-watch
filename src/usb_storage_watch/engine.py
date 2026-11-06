# SPDX-License-Identifier: MIT
#!/usr/bin/python3 -I
"""USB Storage Watch: persistent, bounded recovery and outcome delivery."""
import argparse
import copy
from contextlib import ExitStack
import datetime as dt
import errno
import fcntl
import json
import importlib.util
import types
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile
import threading
import time
import uuid as uuidlib

_settings_spec = importlib.util.spec_from_file_location('usw_settings', Path(__file__).with_name('settings.py'))
settings = importlib.util.module_from_spec(_settings_spec)
if globals().get('PROFILE') is not None:settings.PROFILE = dict(PROFILE)
_settings_spec.loader.exec_module(settings)


VERSION = settings.VERSION
LABEL = 'USB storage'
OBSERVATIONS = 2
SETTINGS = {}
CONFIG_DIGEST = ''
STORAGE_CONFIG_DIGEST = ''
DISK_UUID = ''
MOUNT = '/mnt/storage'
STATE_DIR = settings.STATE_DIR
STATE = STATE_DIR / 'state.json'
NOTIFY = str(Path(__file__).with_name('notify.py'))
INTERVAL = 15
BOOT_GRACE = 90
RETRY_DELAY = 60
SEND_TIMEOUT = 20


def timestamp():
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')


def usb_context(directory=None):
    context = types.SimpleNamespace(**globals())
    if directory is not None:
        context.STATE_DIR = directory
    return context


def log(message):
    print(f'{timestamp()} {message}', flush=True)


def unescape_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)


def parse_mounts(text):
    rows = []
    for line in text.splitlines():
        left, right = line.split(' - ', 1)
        a, b = left.split(), right.split()
        rows.append({'id': a[0], 'parent': a[1], 'dev': a[2],
                     'root': unescape_mount(a[3]), 'target': unescape_mount(a[4]),
                     'vfs': set(a[5].split(',')), 'fs': b[0],
                     'source': unescape_mount(b[1]), 'super': set(b[2].split(','))})
    return rows


def top_mount(rows, target):
    matches = [r for r in rows if r['target'] == target]
    parents = {r['parent'] for r in matches if r['parent'] != r['id']}
    tops = [r for r in matches if r['id'] not in parents]
    return tops[0] if len(tops) == 1 else None


def covers(mountpoint, path):
    return path == mountpoint or path.startswith(mountpoint.rstrip('/') + '/')


def visible_mount(rows, target):
    """Follow mount parent IDs, including ancestor overmounts, without stat(target)."""
    current = top_mount(rows, '/')
    seen = set()
    while current is not None and current['id'] not in seen:
        seen.add(current['id'])
        children = [r for r in rows if r['parent'] == current['id']
                    and r['id'] != current['id'] and covers(r['target'], target)]
        if not children:
            return current
        # An ancestor mount can hide a deeper mount attached to the old parent.
        nearest = min(len(r['target']) for r in children)
        candidates = [r for r in children if len(r['target']) == nearest]
        if len(candidates) != 1:
            return None
        current = candidates[0]
    return None


def observe(mountinfo='/proc/self/mountinfo', dev_dir='/dev/disk/by-uuid',
            sys_dir='/sys/dev/block'):
    """Metadata only: never open/stat MOUNT, filesystem contents, or a block device."""
    try:
        rows = parse_mounts(Path(mountinfo).read_text())
        mounted = visible_mount(rows, MOUNT)
        try:
            device = os.stat(str(Path(dev_dir) / DISK_UUID))
        except FileNotFoundError:
            return False, 'The expected Storage UUID device is absent.'
        if not stat.S_ISBLK(device.st_mode):
            return False, 'The expected UUID does not resolve to a block device.'
        dev_id = f'{os.major(device.st_rdev)}:{os.minor(device.st_rdev)}'
        if not (Path(sys_dir) / dev_id).is_dir():
            return False, 'The Storage block device is absent from sysfs.'
        if mounted is None or mounted['target'] != MOUNT:
            return False, f'The expected mount at {MOUNT} is absent, hidden, or ambiguous.'
        if mounted['dev'] != dev_id or mounted['root'] != '/' or mounted['fs'] != 'ext4':
            return False, f'{MOUNT} is not the expected complete Storage ext4 filesystem.'
        if any({'shutdown', 'emergency_ro'} & opts for opts in (mounted['vfs'], mounted['super'])):
            return False, f'The Storage filesystem at {MOUNT} is shut down or in emergency read-only mode.'
        if any('ro' in opts or 'rw' not in opts for opts in (mounted['vfs'], mounted['super'])):
            return False, f'The Storage mount at {MOUNT} is not read/write.'
        return True, f'Expected Storage ext4 mount is present and read/write ({dev_id}).'
    except (OSError, ValueError, IndexError) as exc:
        return False, f'Mount/device check could not complete ({type(exc).__name__}).'


def atomic_write(path, data, mode=0o600):
    fd, temp = tempfile.mkstemp(prefix='.usb-storage-watch-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


CONFIG = settings.CONFIG
DEPENDENCIES = []
DEPENDENT_ENABLED = False
DEPENDENT = None
IMAGE = None
DEPENDENT_UUID = ''
RECOVERY_DELAY = 60
MAX_ATTEMPTS = 1
MAX_USB_RESETS = 1

_usb_spec = importlib.util.spec_from_file_location('storage_usb', Path(__file__).with_name('usb.py'))
usb = importlib.util.module_from_spec(_usb_spec)
_usb_spec.loader.exec_module(usb)
_apps_spec = importlib.util.spec_from_file_location('storage_apps', Path(__file__).with_name('apps.py'))
apps = importlib.util.module_from_spec(_apps_spec)
_apps_spec.loader.exec_module(apps)
USB_REASON = usb.REASON
for _name in ('standby', 'controls', 'drives', 'manual_usb', 'manual_intent', 'return_deadline'):
    _spec = importlib.util.spec_from_file_location(_name, Path(__file__).with_name(_name + '.py'))
    globals()[_name] = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(globals()[_name])
MANUAL_MOUNT = False
ACTION_TIMEOUT = 80
SCRIPT = Path(__file__).resolve()
WORKER_LOCK_FDS = ()
FSTAB_MAIN_OPTIONS = ''
FSTAB_DEP_OPTIONS = ''


class Unsafe(RuntimeError):
    """A specific, non-secret reason requiring manual intervention."""


class MountFailure(Unsafe):
    """A normal mount failed; allow retry only after clean-state proof."""


class UnmountFailure(Unsafe):
    """An ordinary umount returned a failure; its command is no longer pending."""


class MetadataPending(Unsafe):
    """Required udev identity fields have not appeared; never proof of health."""


def storage_config_digest(value):
    """Docker preferences are independently editable while disk monitoring runs."""
    protected = copy.deepcopy(value)
    protected['docker'] = copy.deepcopy(settings.DEFAULT['docker'])
    # Additive timing preference must not invalidate an existing guarded
    # incident's physical-storage digest or grant it new action budgets.
    protected['recovery'].pop('return_timeout_minutes', None)
    return settings.digest(protected)


def runtime_configuration():
    """Read a consistent selection while the UI saves several drive profiles."""
    deadline = time.monotonic() + 2
    while True:
        try:
            with drives.configuration_lock(settings):
                value = settings.read(CONFIG)
                journal = drives.roots(settings)[1] / 'docker-settings-transaction.json'
                if journal.exists():
                    try:
                        pending = json.loads(journal.read_text())
                        previous = pending['before']
                        if not isinstance(previous, dict) or pending.get('version') != 1:
                            raise ValueError('Invalid pending Docker settings.')
                        if settings.PROFILE_ID not in previous:
                            return value  # This drive is not part of the transaction.
                        before = settings.validate(previous[settings.PROFILE_ID])
                        if storage_config_digest(before) != storage_config_digest(value):
                            raise ValueError('Pending settings do not match the drive.')
                        # The save is not committed yet: every monitor continues
                        # using its previous Docker preferences, including after a crash.
                        value['docker'] = before['docker']
                    except (OSError, ValueError, KeyError, TypeError):
                        value['docker']['enabled'] = False
                        value['docker']['containers'] = []
                return value
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise Unsafe('Settings are being saved; this operation can resume after the save.') from None
            time.sleep(.05)


def refresh_docker_settings():
    """Hot-load only Docker choices; never alter drive/USB recovery mid-flight."""
    global CONFIG_DIGEST
    value = runtime_configuration()
    if storage_config_digest(value) != STORAGE_CONFIG_DIGEST:
        raise Unsafe('Storage configuration changed; a controlled service restart is required.')
    if value['docker'] != SETTINGS['docker']:
        SETTINGS['docker'] = copy.deepcopy(value['docker'])
        CONFIG_DIGEST = settings.digest(SETTINGS)
        apps.configure(SETTINGS['docker'], config_load)
    return value


def configure(value):
    global SETTINGS, CONFIG_DIGEST, STORAGE_CONFIG_DIGEST, DISK_UUID, MOUNT, LABEL, INTERVAL, OBSERVATIONS
    global BOOT_GRACE, RECOVERY_DELAY, MAX_ATTEMPTS, ACTION_TIMEOUT
    global DEPENDENCIES, DEPENDENT_ENABLED, DEPENDENT, IMAGE, DEPENDENT_UUID
    global FSTAB_MAIN_OPTIONS, FSTAB_DEP_OPTIONS, USB_REASON
    SETTINGS = settings.validate(value)
    CONFIG_DIGEST = settings.digest(SETTINGS)
    STORAGE_CONFIG_DIGEST = storage_config_digest(SETTINGS)
    d, m, r, dep = (SETTINGS[k] for k in ('disk','monitor','recovery','dependent'))
    DISK_UUID, MOUNT, LABEL = d['uuid'], d['mountpoint'], d['label']
    INTERVAL, OBSERVATIONS, BOOT_GRACE = m['interval'], m['observations'], m['boot_grace']
    RECOVERY_DELAY, MAX_ATTEMPTS, ACTION_TIMEOUT = r['wait'], 1, r['worker_timeout']
    DEPENDENCIES = settings.storage_images(SETTINGS)
    DEPENDENT_ENABLED = bool(DEPENDENCIES)
    dep = DEPENDENCIES[0] if DEPENDENCIES else dep
    DEPENDENT, IMAGE, DEPENDENT_UUID = dep['mountpoint'], dep['image'], dep['uuid']
    FSTAB_MAIN_OPTIONS, FSTAB_DEP_OPTIONS = d['fstab_options'], dep['fstab_options']
    usb.configure(SETTINGS['usb']['profile'])
    usb.DISABLE_SECONDS = SETTINGS['usb']['disable_seconds']
    usb.ENUM_SECONDS = SETTINGS['usb']['enumeration_seconds']
    USB_REASON = usb.REASON
    apps.configure(SETTINGS['docker'], config_load)
    apps.BASELINE_MAX_AGE = INTERVAL * OBSERVATIONS


def config_load():
    try:
        value = runtime_configuration()
        if storage_config_digest(value) != STORAGE_CONFIG_DIGEST:
            raise Unsafe('Storage configuration changed: actions disabled until a controlled service restart.')
        return {'version': 1, 'automatic_recovery': value['recovery']['mount'],
                'usb_reset_enabled': value['usb']['enabled'], 'docker_enabled': value['docker']['enabled'],
                'docker_containers': value['docker']['containers']}
    except (OSError, ValueError) as exc:
        raise Unsafe('Configuration unreadable/invalid; actions disabled.') from exc


def require_configuration(request):
    expected = request.get('storage_config_digest')
    if ((expected is not None and expected != STORAGE_CONFIG_DIGEST) or
            (expected is None and request.get('config_digest') != CONFIG_DIGEST)):
        raise Unsafe('Worker storage configuration differs from the incident request; no action allowed.')
    config_load()


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def clock_now():
    # BOOTTIME includes suspend and is immune to wall-clock/NTP changes.
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def finite(value):
    return type(value) in (float, int) and 0 <= value < float('inf')


def fresh_state():
    return {'version': 2, 'target': [DISK_UUID, MOUNT], 'status': 'unknown', 'pending': [], 'changed_at': None,
            'incident': None, 'candidate': None, 'count': 0, 'first_bad': None,
            'sample_boot': None, 'sample_at': None}


def load_state(path=STATE):
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        return fresh_state()
    if (not isinstance(state, dict) or state.get('version') not in (1, 2)
            or state.get('status') not in ('unknown', 'up', 'down')
            or not isinstance(state.get('pending'), list)):
        raise ValueError('Saved state invalid; retained for repair')
    for event in state['pending']:
        if (not isinstance(event, dict) or event.get('kind') not in ('failure', 'restored', 'outcome')
                or any(not isinstance(event.get(k), str) for k in ('id', 'time', 'host', 'detail'))
                or type(event.get('attempts', 0)) is not int or event.get('attempts', 0) < 0
                or not finite(event.get('retry_at', 0))
                or (event['kind'] == 'outcome' and not isinstance(event.get('subject'), str))):
            raise ValueError('Queued event invalid; retained for repair')
        uuidlib.UUID(event['id'])
    if state.get('target') and state['target'] != [DISK_UUID, MOUNT]:
        raise ValueError('State belongs to another filesystem; archive it only after safe shutdown')
    if state['version'] == 1:
        # Preserve every legacy event ID, retry and history field. Existing down
        # incidents never acquire a fresh action budget merely through upgrading.
        migrated = fresh_state()
        migrated.update(state)
        migrated.update(version=2, incident=None)
        if state['status'] == 'down':
            migrated['incident'] = new_incident(state.get('changed_at') or timestamp(),
                                               'Legacy outage imported; recovery budget disabled.',
                                               clock_now(), boot_id())
            migrated['incident']['phase'] = 'legacy'
        state = migrated
    incident = state.get('incident')
    for connection in (state.get('candidate_connection'), state.get('last_connection'),
                       incident.get('connection') if isinstance(incident, dict) else None):
        if connection is not None and (not isinstance(connection, dict)
                or set(connection) != {'boot', 'diskseq'}
                or not isinstance(connection['boot'], str) or not connection['boot']
                or type(connection['diskseq']) is not int or not 0 < connection['diskseq'] < 2**64):
            raise ValueError('Invalid saved USB connection identity; recovery budget retained')
    if (state.get('candidate') not in (None, True, False)
            or ('reconnect_pending' in state and type(state['reconnect_pending']) is not bool)
            or type(state.get('count')) is not int or not 0 <= state['count'] <= OBSERVATIONS
            or (state.get('sample_at') is not None and not finite(state['sample_at']))):
        raise ValueError('Invalid observation state')
    if incident is not None:
        if (not isinstance(incident, dict)
                or incident.get('phase') not in ('wait1', 'wait2', 'return_failed', 'running', 'verify', 'applications', 'done', 'legacy')
                or not isinstance(incident.get('attempts'), list)
                or len(incident['attempts']) > 2
                or type(incident.get('usb_resets')) is not int
                or not 0 <= incident['usb_resets'] <= MAX_USB_RESETS
                or not finite(incident.get('due'))
                or type(incident.get('notified')) is not bool
                or any(not isinstance(incident.get(k), str) for k in
                       ('id', 'first_failure', 'first_detail', 'boot', 'usb'))
                or not isinstance(incident.get('blocked'), list)
                or any(x not in ('main', 'dependent') for x in incident['blocked'])):
            raise ValueError('Invalid recovery state; retained for repair')
        uuidlib.UUID(incident['id'])
        if 'return_deadline' in incident: return_deadline.validate(incident['return_deadline'])
        for n, attempt in enumerate(incident['attempts'], 1):
            if (attempt.get('number') != n or not isinstance(attempt.get('time'), str)
                    or not isinstance(attempt.get('reason'), str)
                    or attempt.get('status') not in ('running', 'failed', 'recovered', 'interrupted')):
                raise ValueError('Invalid recovery attempt')
        if incident['phase'] == 'running' and not incident['attempts']:
            raise ValueError('Running recovery has no reserved attempt')
        if incident['phase'] == 'wait2' and len(incident['attempts']) != 1:
            raise ValueError('Second wait has invalid attempt count')
        if incident['phase'] == 'verify' and not isinstance(incident.get('result'), dict):
            raise ValueError('Recovery verification result missing')
        if incident['notified'] and incident['phase'] != 'done':
            raise ValueError('Outcome already queued but recovery remains active')
        stop = incident.get('stop')
        if stop is not None and (not isinstance(stop, dict)
                or stop.get('phase') not in ('pending', 'running', 'done')
                or not finite(stop.get('next_due', 0))
                or (stop.get('result') is not None and not isinstance(stop['result'], dict))
                or (stop['phase'] == 'done' and (not isinstance(stop.get('result'), dict)
                    or type(stop['result'].get('all_stopped')) is not bool))):
            raise ValueError('Invalid container-stop progress; retained for review')
        app = incident.get('applications')
        if app is not None and (not isinstance(app, dict)
                or app.get('phase') not in ('waiting', 'ready', 'running', 'done')
                or app.get('capture_phase') not in ('pending', 'running', 'done')):
            raise ValueError('Invalid application recovery progress; retained for review')
        if incident['phase'] == 'applications' and (not app or not isinstance(incident.get('result'), dict)):
            raise ValueError('Application phase missing saved storage result')
    elif state['status'] == 'down':
        raise ValueError('Down state missing incident; refusing a fresh recovery budget')
    return state


def new_incident(first, detail, now, boot):
    return {'id': str(uuidlib.uuid4()), 'config_digest': CONFIG_DIGEST,
            'storage_config_digest': STORAGE_CONFIG_DIGEST, 'first_failure': first, 'first_detail': detail,
            'confirmed_at': timestamp(), 'phase': 'wait1', 'boot': boot,
            'due': now + RECOVERY_DELAY, 'attempts': [], 'usb_resets': 0,
            'usb': USB_REASON, 'notified': False, 'blocked': [], 'rebooted': False,
            'recovery_generation': 24,
            'control_ids': sorted({v['container_id'] for v in SETTINGS['docker']['containers']
                                   if SETTINGS['docker']['enabled'] and v.get('container_id')})}


def storage_actions_settled(attempts):
    """A new attachment can retry completed work, never an uncertain write."""
    for attempt in attempts:
        if attempt.get('status') in ('running', 'interrupted'):
            return False
        pending = {}
        for action in attempt.get('actions', []):
            target, stage = action.get('target'), action.get('stage', '')
            if target == 'usb' and stage == 'returned':
                continue  # Separate USB ledger proves completion.
            if stage == 'intent' or stage.endswith('-intent'):
                family = stage[:-7] if stage.endswith('-intent') else 'mount'
                key = (target, family)
                pending[key] = pending.get(key, 0) + 1
            elif stage == 'returned' or stage.endswith('-returned'):
                family = stage[:-9] if stage.endswith('-returned') else 'mount'
                key = (target, family)
                pending[key] = max(0, pending.get(key, 0) - 1)
            else:
                return False
        if any(pending.values()):
            return False
    return True


def make_event(kind, detail, subject=None):
    event = {'id': str(uuidlib.uuid4()), 'kind': kind, 'detail': detail,
             'time': timestamp(), 'host': socket.gethostname(), 'attempts': 0, 'retry_at': 0}
    if subject is not None:
        event['subject'] = subject
    return event


def event_payload(event, latest):
    label = event.get('subject') or ('Storage mount ALERT' if event['kind'] == 'failure'
                                      else 'Storage mount restored')
    body = (f"Event recorded: {event['time']}\nHost: {event['host']}\n"
            f"Mount: {MOUNT}\nFilesystem UUID: {DISK_UUID}\n\n{event['detail']}\n"
            f'\nLatest monitor observation before sending: {latest}\n'
            '\nMount verification does not establish file integrity or application health.\n'
            f"\nEvent ID: {event['id']}\nDelivery attempt: {event['attempts']}\n")
    return {'id': event['id'], 'subject': label, 'body': body}


def read_rows():
    return parse_mounts(Path('/proc/self/mountinfo').read_text())


def udev(dev):
    return dict(line[2:].split('=', 1) for line in
                Path('/run/udev/data/b' + dev).read_text().splitlines()
                if line.startswith('E:') and '=' in line)


def device_number(path):
    info = os.stat(path)
    if not stat.S_ISBLK(info.st_mode):
        raise Unsafe('Expected UUID does not resolve to a block device.')
    return f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}'


def block_checks(dev, expected_uuid):
    sysdev = Path('/sys/dev/block') / dev
    if not sysdev.is_dir():
        raise Unsafe('Block device missing from live sysfs.')
    identity = udev(dev)
    if (identity.get('ID_FS_UUID') not in (None, '', expected_uuid)
            or identity.get('ID_FS_TYPE') not in (None, '', 'ext4')):
        raise Unsafe('Live device UUID/type metadata disagrees with expected ext4 identity.')
    if not identity.get('ID_FS_UUID') or not identity.get('ID_FS_TYPE'):
        raise MetadataPending('Live device UUID/type metadata is not available yet.')
    if (sysdev / 'ro').read_text().strip() != '0':
        raise Unsafe('Block device is read-only; manual intervention required.')
    drives.unique_uuid(usb_context(),dev,expected_uuid)
    drives.verify_hardware(usb_context(),dev,expected_uuid)
    return sysdev.resolve().name


def mount_text(value, limit=160):
    """Bound mount-table values before displaying them; no filesystem probing."""
    return ' '.join(str(value).split())[:limit]


def mount_observation(rows, target, dev):
    """Describe occupancy separately from the expected drive's health.

    A returned UUID can have a different device number while the old target
    remains mounted. That is a conflict to explain, never proof that the old
    mount is safe to detach. This function performs no I/O or recovery action.
    """
    exact = [row for row in rows if row['target'] == target]
    children = [row for row in rows if row['target'] != target and covers(target, row['target'])]
    occupied = bool(exact or children)
    label = mount_text(target)
    detail = ''
    if exact:
        visible = visible_mount(rows, target)
        if len(exact) != 1 or visible != exact[0]:
            detail = f'{label} has stacked, hidden or ambiguous mounts. No mount was replaced or detached.'
        else:
            row = exact[0]
            actual = mount_text(row['dev'], 40)
            if dev is None:
                detail = (f'A mount remains at {label} (device {actual}), but the expected UUID device is unavailable. '
                          'Its identity cannot be verified; no mount was replaced or detached.')
            elif row['dev'] != dev:
                detail = (f'{label} is occupied by device {actual}; the expected UUID currently resolves to device '
                          f'{mount_text(dev, 40)}. This may be a retained mount after disconnection or another filesystem. '
                          'No mount was replaced or detached.')
            elif row['root'] != '/' or row['fs'] != 'ext4':
                detail = (f'{label} is mounted as {mount_text(row["fs"], 40)} with filesystem root '
                          f'{mount_text(row["root"])}; the expected mount is the complete ext4 filesystem (root /). '
                          'No mount was replaced or detached.')
            elif any({'shutdown', 'emergency_ro'} & opts for opts in (row['vfs'], row['super'])):
                detail = (f'The filesystem mounted at {label} is shut down or in emergency read-only mode. '
                          'It is not usable even if its mount options still include rw. No mount was replaced or detached.')
            else:
                return dict(mount_state='mounted', mount_detail=f'The expected device {actual} is mounted at {label}.',
                            mount_target_occupied=True)
    elif children:
        detail = (f'{label} has no main mount, but another mount remains below it at '
                  f'{mount_text(children[0]["target"])}. This blocks mounting the drive; no mount was detached.')
    if detail:
        return dict(mount_state='conflict', mount_detail=detail, mount_target_occupied=occupied)
    elsewhere = next((row for row in rows if dev is not None and row['dev'] == dev), None)
    if elsewhere:
        return dict(mount_state='mounted_elsewhere',
                    mount_detail=f'The expected device is mounted at {mount_text(elsewhere["target"])}, not at {label}.',
                    mount_target_occupied=False)
    return dict(mount_state='unmounted' if dev is not None else 'unavailable',
                mount_detail=(f'No mount occupies {label} or its subfolders.' if dev is not None else
                              f'The expected UUID device is unavailable; no mount occupies {label} or its subfolders.'),
                mount_target_occupied=False)


def mounted_checks(rows, target, dev, expected_uuid):
    mounts = [r for r in rows if r['target'] == target]
    m = visible_mount(rows, target)
    if not mounts:
        raise Unsafe('Expected mount is missing.')
    if len(mounts) != 1 or m != mounts[0]:
        raise Unsafe(mount_observation(rows, target, dev)['mount_detail'])
    if m['dev'] != dev or m['root'] != '/' or m['fs'] != 'ext4':
        raise Unsafe(mount_observation(rows, target, dev)['mount_detail'])
    if any({'shutdown', 'emergency_ro'} & opts for opts in (m['vfs'], m['super'])):
        raise Unsafe('The mounted ext4 filesystem is shut down or in emergency read-only mode; it is not usable.')
    if any('ro' in opts or 'rw' not in opts for opts in (m['vfs'], m['super'])):
        raise Unsafe('Mount-level or filesystem-level read-only state; no rw remount allowed.')
    name = block_checks(dev, expected_uuid)
    errors = Path('/sys/fs/ext4') / name / 'errors_count'
    if int(errors.read_text()) != 0:
        raise Unsafe('ext4 reports filesystem errors/possible aborted journal; manual intervention required.')
    return m


def dependent_metadata(rows, item=None):
    if not DEPENDENT_ENABLED and item is None:
        return None
    item = item or dict(mountpoint=DEPENDENT, uuid=DEPENDENT_UUID, image=IMAGE)
    target, expected_uuid, image = item['mountpoint'], item['uuid'], item['image']
    m = visible_mount(rows, target)
    if m is None or m['target'] != target:
        raise Unsafe('Dependent loop mount is absent or hidden.')
    mounted_checks(rows, target, m['dev'], expected_uuid)
    loop = Path('/sys/dev/block') / m['dev'] / 'loop'
    if ((loop / 'backing_file').read_text().strip() != image
            or (loop / 'offset').read_text().strip() != '0'
            or (loop / 'sizelimit').read_text().strip() != '0'):
        raise Unsafe('Dependent loop backing image/offset/size is unexpected.')
    return m


def dependent_status(rows):
    result = []
    for item in DEPENDENCIES:
        try:
            dependent_metadata(rows, item)
            result.append(dict(uuid=item['uuid'],name=item['name'],mountpoint=item['mountpoint'],healthy=True,detail='Mounted read/write'))
        except (OSError, ValueError, Unsafe) as exc:
            result.append(dict(uuid=item['uuid'],name=item['name'],mountpoint=item['mountpoint'],healthy=False,detail=str(exc)))
    return result


def connection_identity(dev):
    """Read-only identity of a USB disk attachment, not a reusable /dev name.

    Old kernels or incomplete metadata leave reconnect re-arming unavailable;
    ordinary recovery and confirmed-healthy re-arming remain supported.
    """
    try:
        identity = udev(dev)
        if identity.get('ID_FS_UUID') != DISK_UUID or identity.get('ID_FS_TYPE') != 'ext4':
            return None
        path = (Path('/sys/dev/block') / dev).resolve(strict=True)
        if not usb.is_verified_usb_block(path, identity):
            return None
        disk = path.parent if (path / 'partition').exists() else path
        sequence = int((disk / 'diskseq').read_text())
        if not 0 < sequence < 2**64:
            return None
        return {'boot': boot_id(), 'diskseq': sequence}
    except (OSError, ValueError):
        return None


def snapshot():
    result = {'healthy': False, 'detected': False, 'detail': '',
              'dependent': False, 'dependent_detail': 'Main filesystem not verified healthy.',
              'mounts': [], 'unsafe': False, 'mount_state': 'unavailable',
              'mount_detail': 'Mount status could not be read.', 'mount_target_occupied': None}
    try:
        rows = read_rows()
        result.update(mount_observation(rows, MOUNT, None))
        detached = detached_shutdown_mount(rows)
        if detached is not None:
            result['detached_shutdown_mount'] = dict(boot=boot_id(), mount=mount_record(detached))
        result['mounts'] = [{k: r[k] for k in ('target', 'source', 'dev', 'fs')}
                            | {'vfs': sorted(r['vfs']), 'super': sorted(r['super'])}
                            for r in rows if covers(MOUNT, r['target'])]
        dev = device_number('/dev/disk/by-uuid/' + DISK_UUID)
        result.update(mount_observation(rows, MOUNT, dev))
        result['detected'] = True
        result['connection'] = connection_identity(dev)
        result['usb_binding_verified'] = False
        try:
            result['usb_binding'] = usb.bind_current(usb_context(), dev)
            result['usb_binding_verified'] = True
            result['usb_sources'] = result['usb_binding']['sources']
        except (OSError, ValueError, Unsafe) as exc:
            result['usb_binding_reason'] = str(exc) if isinstance(exc, Unsafe) else type(exc).__name__
        if not any(r['target'] == MOUNT for r in rows):
            result['detail'] = (result['mount_detail'] if result['mount_state'] == 'conflict' else
                                'Expected device exists; Storage is not mounted.')
            return result
        # Only this exact detached shutdown mismatch may avoid a new unsafe
        # latch. Other failures (for example a non-block UUID link) stay hard
        # failures even if an old detached mount is also visible.
        if detached is not None:
            result['stale_conflict_only'] = True
        main = mounted_checks(rows, MOUNT, dev, DISK_UUID)
        try:drives.enroll(usb_context(),dev)
        except (OSError,ValueError):pass  # No active probing to acquire missing hardware metadata.
        result.update(healthy=True, detail=f'Expected Storage ext4 mount read/write ({dev}); no reported ext4 errors.')
        if result.get('connection'):
            result['main_mount_proof'] = dict(version=1, uuid=DISK_UUID, target=MOUNT,
                boot=result['connection']['boot'], connection=result['connection'], mount=mount_record(main))
        try:
            result['images'] = dependent_status(rows)
            if any(not v['healthy'] for v in result['images']):
                raise Unsafe('; '.join(v['name'] + ': ' + v['detail'] for v in result['images'] if not v['healthy']))
            result.update(dependent=True, dependent_detail=('Dependent loop ext4 mount read/write.' if DEPENDENT_ENABLED else 'No dependent filesystem configured.'))
        except (OSError, ValueError, Unsafe) as exc:
            result['dependent_detail'] = str(exc) if isinstance(exc, Unsafe) else type(exc).__name__
    except FileNotFoundError:
        result['detail'] = 'Expected device or required live metadata is absent.'
    except (OSError, ValueError, Unsafe) as exc:
        result.update(unsafe=True, detail=str(exc) if isinstance(exc, Unsafe) else type(exc).__name__)
    return result


def command(argv, timeout=8):
    # Used only inside a separately supervised worker. No shell, no repair tools.
    if argv[0] == '/usr/bin/mount' and not config_load()['automatic_recovery'] and not MANUAL_MOUNT:
        raise Unsafe('Mount recovery disabled before the mount command; no action allowed.')
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, timeout=timeout, cwd='/', close_fds=True,
                           pass_fds=WORKER_LOCK_FDS)
    except subprocess.TimeoutExpired:
        raise Unsafe(f'{Path(argv[0]).name} exceeded its {timeout}s deadline; result uncertain.') from None
    if p.returncode:
        # Only fixed disk commands use this helper; no SMTP configuration/output.
        detail = ' '.join(p.stderr.split())[:600]
        error = (MountFailure if argv[0] == '/usr/bin/mount' else
                 UnmountFailure if argv[0] == '/usr/bin/umount' else Unsafe)
        raise error(f'{Path(argv[0]).name} exited {p.returncode}: {detail}')
    return p.stdout


def superblock(data, expected_uuid, unmounted):
    if len(data) != 1024 or struct.unpack_from('<H', data, 0x38)[0] != 0xef53:
        raise Unsafe('Invalid ext filesystem superblock.')
    if str(uuidlib.UUID(bytes=data[0x68:0x78])) != expected_uuid:
        raise Unsafe('Actual on-disk filesystem UUID is incorrect.')
    state = struct.unpack_from('<H', data, 0x3a)[0]
    incompat = struct.unpack_from('<I', data, 0x60)[0]
    errors = struct.unpack_from('<I', data, 0x194)[0]
    if state & ~1 or errors:
        raise Unsafe('Filesystem error/orphan state or recorded ext4 errors; manual intervention required.')
    # RECOVER is expected after an interrupted journaled mount. Let ext4 replay
    # its journal normally; it is not evidence of corruption or active use.
    # An unclean filesystem without a journal to replay still requires review.
    compat = struct.unpack_from('<I', data, 0x5c)[0]
    if incompat & 0x4 and not compat & 0x4:
        raise Unsafe('Journal recovery requested without an ext4 journal.')
    if unmounted and state != 1 and not (incompat & 0x4 and compat & 0x4):
        raise Unsafe('Unclean filesystem without journal recovery; manual intervention required.')


def disk_proof(path, expected_uuid, unmounted=False, regular=False):
    # Open read-only; pin the object while probing. This executes in a worker
    # with a hard parent deadline, never in the 15-second observation loop.
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    # Linux block-device exclusive open detects active filesystems even in
    # another namespace or retained only by a lazy-unmounted bind/open handle.
    # Never apply O_EXCL without O_CREAT to a regular loop backing file.
    if unmounted and not regular:
        flags |= os.O_EXCL
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.EBUSY:
            raise Unsafe('Returned block device is still in use (possibly a retained container mount); manual intervention required.') from None
        raise
    try:
        info = os.fstat(fd)
        if not (stat.S_ISREG(info.st_mode) if regular else stat.S_ISBLK(info.st_mode)):
            raise Unsafe('Unexpected backing object type.')
        fields = dict(line.split('=', 1) for line in command(
            ['/usr/sbin/blkid', '-p', '-o', 'export', str(path)]).splitlines() if '=' in line)
        if fields.get('UUID') != expected_uuid or fields.get('TYPE') != 'ext4':
            raise Unsafe('Direct probe found an incorrect filesystem UUID/type.')
        superblock(os.pread(fd, 1024, 1024), expected_uuid, unmounted)
        return info
    finally:
        os.close(fd)


def fstab_check(target):
    image = next((v for v in settings.storage_images(SETTINGS, enabled=False) if v['mountpoint'] == target), None)
    expected = ('UUID=' + DISK_UUID, FSTAB_MAIN_OPTIONS) if target == MOUNT else ((image['image'], image['fstab_options']) if image else (IMAGE, FSTAB_DEP_OPTIONS))
    entries = []
    for line in Path('/etc/fstab').read_text().splitlines():
        fields = line.split('#', 1)[0].split()
        if len(fields) >= 4 and unescape_mount(fields[1]) == target:
            entries.append(fields)
    if (len(entries) != 1 or entries[0][0] != expected[0] or entries[0][2] != 'ext4'
            or set(entries[0][3].split(',')) != set(expected[1].split(','))):
        raise Unsafe('Existing fstab identity/options changed or are ambiguous; refusing mount.')


def safe_path(path, parent_dev, directory=True):
    # Refuse symlinks at every component, including the configured mountpoint.
    p = Path(path)
    for component in [*reversed(p.parents), p]:
        if component.is_symlink():
            raise Unsafe('Symlink in mount/image path; manual intervention required.')
    info = p.stat()
    if info.st_dev != parent_dev or (directory and not stat.S_ISDIR(info.st_mode)):
        raise Unsafe('Path is on the wrong backing filesystem or is not a directory.')
    # A normal mount hides existing directory entries without altering them.
    # Do not enumerate, delete, move or otherwise touch those underlying files.
    return info


def desktop_target(path):
    return path.startswith(('/run/media/', '/media/'))


def recovery_backing(rows, target, dev, mounted=False):
    """Only system-root storage or the host /run tmpfs may back a target.

    Ignore the selected live mount only after the caller verifies its identity.
    Nested/stacked mounts and other backing filesystems remain unsupported.
    """
    beneath = [r for r in rows if not (mounted and r['target'] == target)]
    root = visible_mount(beneath, '/')
    parent = visible_mount(beneath, target)
    runtime = (desktop_target(target) and target.startswith('/run/media/')
               and parent is not None and parent['target'] == '/run'
               and parent.get('fs') == 'tmpfs' and parent.get('root') == '/'
               and len([r for r in beneath if r['target'] == '/run']) == 1)
    if (root is None or parent is None or (parent != root and not runtime)
            or parent['dev'] == dev or 'rw' not in parent['vfs'] or 'rw' not in parent['super']
            or any(r['target'] != target and covers(target, r['target']) for r in rows)):
        raise Unsafe('Recovery directory is not on protected writable system storage, or contains another mount.')
    return parent


def walk_mount_directory(fd, parts, backing_dev, create=False):
    """Walk from an owned descriptor; never follow links or writable parents.

    The caller owns fd. A missing suffix is acceptable during read-only planning.
    No existing directory, contents, ownership or permissions are changed.
    """
    current = os.dup(fd)
    try:
        for part in parts:
            info = os.fstat(current)
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise Unsafe('Recovery directory has a parent writable by another account.')
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    return
                # Creation is permitted only once the verified backing filesystem
                # has been reached. Never create through another mounted device.
                if info.st_dev != backing_dev:
                    raise Unsafe('Recovery directory backing changed before creation.')
                try:
                    os.mkdir(part, mode=0o755, dir_fd=current)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        info = os.fstat(current)
        if info.st_dev != backing_dev or info.st_uid != 0 or info.st_mode & 0o022:
            raise Unsafe('Recovery directory ownership, permissions or backing changed.')
    finally:
        os.close(current)


def protected_mount_directory(target, backing, mounted=False, create=False):
    parts = Path(target).parts[1:]
    if not parts or any(part in ('.', '..') for part in parts):
        raise Unsafe('Invalid recovery directory.')
    # Never inspect or chmod the live filesystem's contents/root ownership.
    if mounted:
        parts = parts[:-1]
    major, minor = map(int, backing['dev'].split(':'))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk_mount_directory(fd, parts, os.makedev(major, minor), create=create)
    finally:
        os.close(fd)


def process_exited(proc):
    """Kernel proof for an unreaped process; never infer exit from missing files."""
    if proc.parent != Path('/proc'):
        return False
    try:
        fd = os.pidfd_open(int(proc.name), 0)  # Process, not PIDFD_THREAD.
    except ProcessLookupError:
        return True
    except (OSError, AttributeError, ValueError):
        return False
    try:
        poll = select.poll()
        poll.register(fd, select.POLLIN)
        return any(event & (select.POLLIN | select.POLLHUP) for _, event in poll.poll(0))
    except OSError:
        return False
    finally:
        os.close(fd)


def namespace_available(dev, proc_root=Path('/proc'), allowed_mounts=()):
    # Inspect without entering namespaces. A disappearing process is harmless;
    # unreadable metadata for a surviving process must fail closed.
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():
            continue
        rows = []
        for attempt in range(3):
            try:
                rows = parse_mounts((proc / 'mountinfo').read_text())
                break
            except OSError as exc:
                # procfs can return EINVAL after task->nsproxy is released but
                # before the PID is reaped. Concurrent workers exposed this race.
                # Skip only a process proven exited; a surviving unreadable namespace
                # still fails closed after a bounded metadata recheck.
                if exc.errno in (errno.ENOENT, errno.ESRCH, errno.EINVAL):
                    try: proc.stat()
                    except (FileNotFoundError, ProcessLookupError): break
                    except OSError: pass
                    else:
                        if process_exited(proc):
                            break
                        if attempt < 2:
                            time.sleep(0.01)
                            continue
                raise Unsafe('Cannot verify process mount namespaces; refusing mount.') from None
            except (ValueError, IndexError):
                raise Unsafe('Cannot verify process mount namespaces; refusing mount.') from None
        conflict = next((row for row in rows if row['dev'] == dev and not any(
            all(row[key] == known[key] for key in MOUNT_IDENTITY_FIELDS) for known in allowed_mounts)), None)
        if conflict is not None:
            raise Unsafe('Device ' + mount_text(dev, 40) + ' is already mounted in process namespace for PID ' +
                         mount_text(proc.name, 30) + ' at ' + mount_text(conflict['target']) +
                         '; retained namespace mounts must be released before mounting this device or detaching its loop.')


def mount_available(rows, target, dev):
    if any(covers(target, r['target']) or r['dev'] == dev for r in rows):
        detail = mount_observation(rows, target, dev)['mount_detail']
        raise Unsafe('Mount refused. ' + detail + ' No additional mount was attempted.')
    namespace_available(dev)
    for holder in (Path('/sys/dev/block') / dev / 'holders').iterdir():
        raise Unsafe('Expected block device has active holders.')
    if any(line.split()[0] == str(Path('/dev/block') / dev) for line in
           Path('/proc/swaps').read_text().splitlines()[1:]):
        raise Unsafe('Expected device is in use as swap.')
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        source = unescape_mount(line.split()[0])
        if source.startswith('/dev/') and device_number(source) == dev:
            raise Unsafe('Expected device is in use as swap.')


def verify_main():
    rows = read_rows()
    device = Path('/dev/disk/by-uuid') / DISK_UUID
    dev = device_number(device)
    mounted_checks(rows, MOUNT, dev, DISK_UUID)
    real = device.resolve(strict=True)
    proof = disk_proof(real, DISK_UUID)
    if f'{os.major(proof.st_rdev)}:{os.minor(proof.st_rdev)}' != dev:
        raise Unsafe('Device identity changed while verifying.')
    mounted_checks(read_rows(), MOUNT, dev, DISK_UUID)
    return dev


def verify_dependent(item=None):
    if not DEPENDENT_ENABLED and item is None:
        return
    if item is None and len(DEPENDENCIES) > 1:
        for dependency in DEPENDENCIES: verify_dependent(dependency)
        return
    item = item or dict(mountpoint=DEPENDENT, uuid=DEPENDENT_UUID, image=IMAGE)
    image_path, expected_uuid = item['image'], item['uuid']
    m = dependent_metadata(read_rows(), item)
    proof = disk_proof((Path('/dev/block') / m['dev']).resolve(strict=True), expected_uuid)
    if f'{os.major(proof.st_rdev)}:{os.minor(proof.st_rdev)}' != m['dev']:
        raise Unsafe('Dependent device identity changed while verifying.')
    image = Path(image_path).stat()
    loop = json.loads(command(['/usr/sbin/losetup', '--json', '--list', '--output',
                               'NAME,BACK-FILE,BACK-INO,BACK-MAJ:MIN,OFFSET,SIZELIMIT']))['loopdevices']
    expected_name = str((Path('/dev/block') / m['dev']).resolve())
    entries = [r for r in loop if r['name'] == expected_name]
    if (len(entries) != 1 or entries[0]['back-file'] != image_path
            or int(entries[0]['back-ino']) != image.st_ino
            or entries[0]['back-maj:min'] != f'{os.major(image.st_dev)}:{os.minor(image.st_dev)}'):
        raise Unsafe('Loop device does not reference the current expected backing image inode.')
    dependent_metadata(read_rows(), item)


def write_receipt(path, receipt):
    atomic_write(path, json.dumps(receipt, indent=2) + '\n')


def verify_access():
    with os.scandir(MOUNT) as entries:
        next(entries, None)


MOUNT_IDENTITY_FIELDS = ('id', 'parent', 'dev', 'root', 'target', 'fs', 'source')


def mount_record(row):
    return {key: row[key] for key in MOUNT_IDENTITY_FIELDS} | {
        'vfs': sorted(row['vfs']), 'super': sorted(row['super'])}


def detached_shutdown_mount(rows):
    """Find a retained shutdown mount; ownership is verified separately.

    Configured loop mounts can survive unplugging their parent.  Their presence
    must not hide the parent recovery case; the worker proves every loop before
    removing it normally, from the leaves toward the physical drive.
    """
    exact = [row for row in rows if row['target'] == MOUNT]
    if len(exact) != 1 or visible_mount(rows, MOUNT) != exact[0]:
        return None
    row = exact[0]
    images = {item['mountpoint']: item for item in settings.storage_images(SETTINGS, enabled=False)}
    children = [other for other in rows if other != row and covers(MOUNT, other['target'])]
    if (row['fs'] != 'ext4' or row['root'] != '/' or 'shutdown' not in row['super']
            or any('rw' not in opts or 'ro' in opts or 'emergency_ro' in opts
                   for opts in (row['vfs'], row['super']))
            or any(other != row and other['dev'] == row['dev'] for other in rows)
            or any(child['target'] not in images or child['fs'] != 'ext4' or child['root'] != '/'
                   or not child['dev'].startswith('7:') or visible_mount(rows, child['target']) != child
                   or sum(other['target'] == child['target'] for other in rows) != 1
                   or any(other != child and other['dev'] == child['dev'] for other in rows)
                   for child in children)):
        return None
    try:
        (Path('/sys/dev/block') / row['dev']).lstat()
    except FileNotFoundError:
        return row
    except OSError:
        pass  # Unreadable metadata is not proof that the old device is gone.
    return None


def automatic_cleanup_eligible(current, boot=None):
    """A fresh detached configured shutdown mount may enter guarded cleanup.

    This is scheduling eligibility, not an unmount authorization. The worker
    re-captures the complete tree and proves its configured loops under the
    stopped-container guard. No past healthy observation is manufactured.
    """
    candidate = current.get('detached_shutdown_mount')
    if not isinstance(candidate, dict) or current.get('healthy'):
        return False
    if current.get('unsafe') and current.get('stale_conflict_only') is not True:
        return False
    row = candidate.get('mount', {})
    return (candidate.get('boot') == (boot or boot_id()) and row.get('target') == MOUNT
            and row.get('fs') == 'ext4' and row.get('root') == '/'
            and 'shutdown' in row.get('super', [])
            and all('rw' in row.get(key, []) and not {'ro', 'emergency_ro'} & set(row.get(key, []))
                    for key in ('vfs', 'super')))


def loop_inventory():
    return json.loads(command(['/usr/sbin/losetup', '--json', '--list', '--output',
                               'NAME,BACK-FILE,BACK-INO,BACK-MAJ:MIN,OFFSET,SIZELIMIT']))['loopdevices']


def retained_image_loops(rows, main):
    """Prove managed child loops against live kernel metadata, without files I/O."""
    children = [row for row in rows if row != main and covers(MOUNT, row['target'])]
    if not children:
        return []
    configured = {item['mountpoint']: item for item in settings.storage_images(SETTINGS, enabled=False)}
    entries = loop_inventory()
    proven = []
    for row in children:
        item = configured.get(row['target'])
        if (not item or row['fs'] != 'ext4' or row['root'] != '/' or not row['dev'].startswith('7:')
                or visible_mount(rows, row['target']) != row
                or sum(other['target'] == row['target'] for other in rows) != 1
                or any(other != row and other['dev'] == row['dev'] for other in rows)):
            raise Unsafe('An unrecognized or shared child mount prevents automatic recovery.')
        backing = visible_mount(rows, item['image'])
        if not backing or backing not in [main, *children] or covers(row['target'], item['image']):
            raise Unsafe('A managed image has an unexpected backing mount; no mount was detached.')
        metadata = udev(row['dev'])
        if metadata.get('ID_FS_UUID') != item['uuid'] or metadata.get('ID_FS_TYPE') != 'ext4':
            raise Unsafe('A retained image UUID does not match its configuration; no mount was detached.')
        name = str((Path('/dev/block') / row['dev']).resolve(strict=True))
        matches = [entry for entry in entries if entry.get('name') == name]
        if (len(matches) != 1 or matches[0].get('back-file') != item['image']
                or matches[0].get('back-maj:min') != backing['dev']
                or int(matches[0].get('back-ino', -1)) <= 0
                or int(matches[0].get('offset', -1)) != 0 or int(matches[0].get('sizelimit', -1)) != 0):
            raise Unsafe('A retained loop does not belong to the configured image on this disk; no mount was detached.')
        proven.append(dict(mount=mount_record(row), name=name, image=item['image'],
                           backing=backing['dev'], back_inode=int(matches[0]['back-ino'])))
    return sorted(proven, key=lambda item: len(item['mount']['target']), reverse=True)


def valid_storage_mount_proof(proof):
    try:
        if (not isinstance(proof, dict) or set(proof) != {'version', 'uuid', 'target', 'boot', 'connection', 'mount'}
                or type(proof['version']) is not int or proof['version'] != 1
                or not isinstance(proof['uuid'], str) or str(uuidlib.UUID(proof['uuid'])) != proof['uuid']
                or not isinstance(proof['boot'], str) or not 0 < len(proof['boot']) <= 128
                or not isinstance(proof['target'], str) or not proof['target'].startswith('/')
                or proof['target'] == '/' or len(proof['target']) > 4096):
            return False
        connection, row = proof['connection'], proof['mount']
        if (not isinstance(connection, dict) or set(connection) != {'boot', 'diskseq'}
                or connection['boot'] != proof['boot'] or type(connection['diskseq']) is not int
                or not 0 < connection['diskseq'] < 2**64
                or not isinstance(row, dict) or set(row) != set(MOUNT_IDENTITY_FIELDS) | {'vfs', 'super'}
                or any(not isinstance(row[key], str) or not row[key] or len(row[key]) > 4096
                       for key in MOUNT_IDENTITY_FIELDS)
                or not re.fullmatch(r'[0-9]+', row['id']) or not re.fullmatch(r'[0-9]+', row['parent'])
                or not re.fullmatch(r'[0-9]+:[0-9]+', row['dev'])
                or row['target'] != proof['target'] or row['fs'] != 'ext4' or row['root'] != '/'):
            return False
        return all(isinstance(row[key], list) and all(isinstance(value, str) for value in row[key])
                   and 'rw' in row[key] and not {'ro', 'shutdown', 'emergency_ro'} & set(row[key])
                   for key in ('vfs', 'super'))
    except (KeyError, TypeError, ValueError):
        return False


def known_detached_mount(current, proof):
    """Match this exact host mount to a healthy observation from this boot.

    UI18 records lack mount IDs and cannot authorize cleanup. A future healthy
    UI19 observation establishes the required baseline; upgrades never invent it.
    """
    candidate = current.get('detached_shutdown_mount')
    if not valid_storage_mount_proof(proof) or not isinstance(candidate, dict):
        return False
    try:
        old, row, connection = proof['mount'], candidate['mount'], proof['connection']
        return (proof['version'] == 1 and proof['uuid'] == DISK_UUID and proof['target'] == MOUNT
                and proof['boot'] == candidate['boot'] == connection['boot']
                and isinstance(proof['boot'], str) and bool(proof['boot'])
                and type(connection['diskseq']) is int and connection['diskseq'] > 0
                and all(old[key] == row[key] for key in MOUNT_IDENTITY_FIELDS)
                and old['root'] == '/' and old['fs'] == 'ext4' and old['target'] == MOUNT
                and all('rw' in old[key] and not {'ro', 'shutdown', 'emergency_ro'} & set(old[key])
                        for key in ('vfs', 'super'))
                and set(row['vfs']) == set(old['vfs'])
                and set(row['super']) - {'shutdown'} == set(old['super']))
    except (KeyError, TypeError):
        return False


def cleanup_detached_main(request, note):
    """One ordinary unmount of a previously verified, now detached host mount.

    Only configured child images proven against live loop metadata may be
    removed first. There is no force/lazy unmount or filesystem repair.
    """
    if request.get('check_only') or not request.get('allow_mount') or 'main' in request.get('blocked', []):
        raise Unsafe('Detached mount cleanup is not permitted for this request.')
    proof = request.get('known_storage')
    rows = read_rows()
    row = detached_shutdown_mount(rows)
    current = dict(detached_shutdown_mount=dict(boot=boot_id(), mount=mount_record(row))) if row else {}
    if not known_detached_mount(current, proof):
        raise Unsafe('The occupied mount cannot be matched to a healthy mount recorded by this version in the same boot. No mount was detached.')
    loops = retained_image_loops(rows, row)
    tree = [row, *[item for item in rows if item != row and covers(MOUNT, item['target'])]]
    for item in tree:
        namespace_available(item['dev'], allowed_mounts=tree)
    marker_path = STATE_DIR / 'stale-mount-cleanup.json'
    try:
        previous = json.loads(marker_path.read_text())
    except FileNotFoundError:
        previous = None
    except (OSError, ValueError):
        raise Unsafe('Previous detached-mount cleanup record is unreadable; no cleanup was repeated.') from None
    if previous is not None:
        if (not isinstance(previous, dict) or type(previous.get('version')) is not int
                or previous.get('version') != 1 or not valid_storage_mount_proof(previous.get('proof'))
                or previous.get('phase') not in ('intent', 'returned')
                or not isinstance(previous.get('incident'), str) or not previous['incident']
                or not isinstance(previous.get('time'), str) or not previous['time']
                or (previous.get('phase') == 'returned' and
                    (not isinstance(previous.get('finished_at'), str) or not previous['finished_at']))):
            raise Unsafe('Previous detached-mount cleanup record is invalid; no cleanup was repeated.')
        if previous.get('proof') == proof:
            raise Unsafe('Cleanup of this detached mount was already attempted. It will not be repeated automatically; resolve the retained mount manually.')
    device = Path('/dev/disk/by-uuid') / DISK_UUID
    dev = device_number(device)
    connection = connection_identity(dev)
    if (dev == row['dev'] or not connection or connection['boot'] != proof['boot']
            or connection['diskseq'] == proof['connection']['diskseq']):
        raise Unsafe('A separate returned attachment of the expected drive could not be verified; no mount was detached.')
    # The old mount must not obscure another active use of the returned device.
    mount_available([item for item in rows if item not in tree], MOUNT, dev)
    block_checks(dev, DISK_UUID)
    if not MANUAL_MOUNT or FSTAB_MAIN_OPTIONS:
        fstab_check(MOUNT)
    backing = recovery_backing([item for item in rows if item not in tree or item is row],
                               MOUNT, row['dev'], mounted=True)
    protected_mount_directory(MOUNT, backing, mounted=True)
    direct = disk_proof(device.resolve(strict=True), DISK_UUID, unmounted=True)
    if f'{os.major(direct.st_rdev)}:{os.minor(direct.st_rdev)}' != dev:
        raise Unsafe('Returned drive identity changed before cleanup; no mount was detached.')
    captured = mount_record(row)
    def recheck():
        latest_rows = read_rows()
        latest = detached_shutdown_mount(latest_rows)
        if (latest is None or mount_record(latest) != captured
                or device_number(device) != dev or connection_identity(dev) != connection):
            raise Unsafe('Mount or returned drive changed before cleanup; no mount was detached.')
        block_checks(dev, DISK_UUID)
        current_tree = [item for item in latest_rows if covers(MOUNT, item['target'])]
        expected_tree = [mount_record(item) for item in tree]
        if any(mount_record(item) not in expected_tree for item in current_tree):
            raise Unsafe('A mount changed during retained-mount cleanup; further actions stopped.')
        mount_available([item for item in latest_rows if item not in current_tree], MOUNT, dev)
        if not MANUAL_MOUNT and not config_load()['automatic_recovery']:
            raise Unsafe('Automatic recovery was disabled before cleanup; no mount was detached.')
        # Manual operations also recheck configuration identity immediately.
        if MANUAL_MOUNT:
            config_load()
    recheck()
    marker = dict(version=1, proof=proof, incident=request['incident'], phase='intent', time=timestamp())
    write_receipt(marker_path, marker)
    note('main', 'stale-unmount-intent', 'Normal unmount of the previously verified detached shutdown mount.')
    recheck()
    for loop in loops:
        target = loop['mount']['target']
        current_rows = read_rows()
        current = visible_mount(current_rows, target)
        if current is None or mount_record(current) != loop['mount']:
            raise Unsafe('A retained image mount changed before cleanup; further actions stopped.')
        current_proofs = retained_image_loops(current_rows, visible_mount(current_rows, MOUNT))
        if loop not in current_proofs:
            raise Unsafe('A retained image loop changed before cleanup; further actions stopped.')
        namespace_available(current['dev'], allowed_mounts=current_rows)
        note('dependent', 'stale-unmount-intent', target)
        command(['/usr/bin/umount', '--internal-only', '--no-canonicalize', '--', target], timeout=15)
        if any(item['id'] == current['id'] or covers(target, item['target']) for item in read_rows()):
            raise Unsafe('A retained image is still mounted; further actions stopped.')
        note('dependent', 'stale-unmount-returned', target)
        # util-linux loop mounts normally use autoclear. An explicitly created
        # managed loop may remain attached after its mount is gone; detach only
        # the same proven loop once all namespace references have disappeared.
        backing_file = Path('/sys/dev/block') / current['dev'] / 'loop/backing_file'
        try:
            backing_path = backing_file.read_text().strip()
        except FileNotFoundError:
            backing_path = None
        if backing_path is not None:
            namespace_available(current['dev'])
            retained = [entry for entry in loop_inventory() if entry.get('name') == loop['name']]
            if (backing_path != loop['image'] or len(retained) != 1
                    or retained[0].get('back-file') != loop['image']
                    or retained[0].get('back-maj:min') != loop['backing']
                    or int(retained[0].get('back-ino', -1)) != loop['back_inode']
                    or int(retained[0].get('offset', -1)) != 0
                    or int(retained[0].get('sizelimit', -1)) != 0):
                raise Unsafe('Retained loop backing changed after unmount; detach refused.')
            recheck()
            note('dependent', 'loop-detach-intent', target)
            command(['/usr/sbin/losetup', '--detach', '--', loop['name']], timeout=8)
            note('dependent', 'loop-detach-returned', target)
        recheck()
    try:
        command(['/usr/bin/umount', '--internal-only', '--no-canonicalize', '--', MOUNT], timeout=15)
    except (OSError, Unsafe) as exc:
        note('main', 'stale-unmount-failed', str(exc))
        raise Unsafe('Detached mount cleanup did not complete. No mount or retry was attempted. ' + str(exc)) from exc
    after = read_rows()
    if any(item['id'] == row['id'] or covers(MOUNT, item['target']) for item in after):
        raise Unsafe('Cleanup returned but the old mount or another mount still occupies the target. No new mount was attempted.')
    marker.update(phase='returned', finished_at=timestamp())
    write_receipt(marker_path, marker)
    note('main', 'stale-unmount-returned', 'The detached shutdown mount was removed by normal unmount.')


def valid_settled_cleanup_receipt(value):
    """Validate old receipts before any incident-scoped history is bypassed.

    UI22/23 may contain settled commands from earlier captures. Validate those
    records independently; membership in the latest capture is not required.
    """
    def text_field(item, limit=4096):
        return isinstance(item, str) and 0 < len(item) <= limit and '\x00' not in item
    def absolute(item):
        return text_field(item) and item.startswith('/') and item != '/' and '..' not in Path(item).parts
    def device(item):
        return isinstance(item, str) and re.fullmatch(r'[0-9]+:[0-9]+', item) is not None
    def mount(row, target):
        return (isinstance(row, dict) and set(row) == set(MOUNT_IDENTITY_FIELDS) | {'vfs', 'super'}
            and all(text_field(row[key]) for key in MOUNT_IDENTITY_FIELDS)
            and re.fullmatch(r'[0-9]+', row['id']) is not None
            and re.fullmatch(r'[0-9]+', row['parent']) is not None and device(row['dev'])
            and absolute(row['target']) and covers(target, row['target'])
            and row['root'] == '/' and row['fs'] == 'ext4'
            and all(isinstance(row[key], list) and row[key] and
                    all(text_field(item) for item in row[key]) for key in ('vfs', 'super')))
    try:
        if (not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 2
                or not text_field(value.get('incident'), 128) or value.get('phase') != 'returned'
                or not text_field(value.get('time'), 128)
                or ('finished_at' in value and not text_field(value['finished_at'], 128))
                or ('complete' in value and type(value['complete']) is not bool)):
            return False
        capture, commands = value['capture'], value['commands']
        if (not isinstance(capture, dict) or type(capture.get('version')) is not int or capture['version'] != 2
                or not text_field(capture.get('boot'), 128) or not absolute(capture.get('target'))
                or not isinstance(capture.get('uuid'), str) or str(uuidlib.UUID(capture['uuid'])) != capture['uuid']):
            return False
        target, tree, loops = capture['target'], capture['tree'], capture['loops']
        if (not isinstance(tree, list) or not tree or not all(mount(row, target) for row in tree)
                or len({row['id'] for row in tree}) != len(tree)
                or len({row['target'] for row in tree}) != len(tree)
                or sum(row['target'] == target for row in tree) != 1 or not isinstance(loops, list)):
            return False
        for loop in loops:
            if (not isinstance(loop, dict) or not mount(loop.get('mount'), target)
                    or loop['mount']['target'] == target or not loop['mount']['dev'].startswith('7:')
                    or not isinstance(loop.get('name'), str) or re.fullmatch(r'/dev/loop[0-9]+', loop['name']) is None
                    or not absolute(loop.get('image')) or not covers(target, loop['image'])
                    or covers(loop['mount']['target'], loop['image']) or not device(loop.get('backing'))
                    or type(loop.get('back_inode')) is not int or loop['back_inode'] <= 0):
                return False
        remaining = value['remaining']
        if (not isinstance(remaining, list) or not all(mount(row, target) for row in remaining)
                or (value.get('complete') is True and remaining)
                or not isinstance(commands, list) or not commands):
            return False
        for action in commands:
            if (not isinstance(action, dict) or action.get('phase') != 'returned'
                    or not text_field(action.get('finished_at'), 128)
                    or ('sent' in action and type(action['sent']) is not bool)
                    or ('removed' in action and type(action['removed']) is not bool)
                    or (action.get('sent') is False and action.get('removed') is True)):
                return False
            if action.get('action') == 'loop-detach':
                if (not isinstance(action.get('target'), str)
                        or re.fullmatch(r'/dev/loop[0-9]+', action['target']) is None or 'mount' in action):
                    return False
            elif ('action' in action or not mount(action.get('mount'), target)
                    or action.get('target') != action['mount']['target']
                    or type(action.get('attempt')) is not int or action['attempt'] not in (1, 2)
                    or not text_field(action.get('time'), 128)
                    or (action.get('sent') is not False and type(action.get('removed')) is not bool)):
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def cleanup_failed_main(request, note, stop_check=lambda: None):
    """Release the presently verified failed tree after confirmed Docker stops.

    The caller holds storage_recovery_guard through this operation. Only normal
    unmounts are used, leaves first; a timed-out command remains a durable intent.
    A completed busy unmount may retry once after exact-tree reconciliation.
    """
    if (MANUAL_MOUNT or request.get('check_only') or not request.get('allow_mount')
            or 'main' in request.get('blocked', []) or request.get('boot') != boot_id()):
        raise Unsafe('Automatic failed-mount cleanup is not permitted for this request.')
    rows = read_rows()
    main = detached_shutdown_mount(rows)
    if main is None:
        raise Unsafe('The configured mount is not a detached shutdown filesystem; no mount was detached.')
    loops = retained_image_loops(rows, main)
    tree = [mount_record(row) for row in rows if covers(MOUNT, row['target'])]
    captured = dict(version=2, boot=boot_id(), uuid=DISK_UUID, target=MOUNT, tree=tree, loops=loops)
    remaining = copy.deepcopy(tree)
    backing = recovery_backing([row for row in rows if not covers(MOUNT, row['target']) or row == main],
                               MOUNT, main['dev'], mounted=True)
    protected_mount_directory(MOUNT, backing, mounted=True)
    marker_path = STATE_DIR / 'retained-mount-cleanup.json'
    prior_commands = []
    # Do not erase uncertainty left by either cleanup implementation.
    for path in (STATE_DIR / 'stale-mount-cleanup.json', marker_path):
        try:
            raw = path.read_text()
            previous = json.loads(raw)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            raise Unsafe('Previous mount cleanup record is unreadable; cleanup was not repeated.') from None
        if (not isinstance(previous, dict) or type(previous.get('version')) is not int
                or previous.get('phase') not in ('intent', 'returned')
                or previous.get('version') not in (1, 2)):
            raise Unsafe('Previous mount cleanup record is invalid; cleanup was not repeated.')
        if previous['phase'] == 'intent':
            raise Unsafe('A previous mount cleanup command is uncertain; cleanup was not repeated.')
        if previous['version'] == 1:
            if (not valid_storage_mount_proof(previous.get('proof'))
                    or any(not isinstance(previous.get(key), str) or not 0 < len(previous[key]) <= 128
                           for key in ('incident', 'time', 'finished_at'))):
                raise Unsafe('Previous mount cleanup record is invalid; cleanup was not repeated.')
        else:
            if not valid_settled_cleanup_receipt(previous):
                raise Unsafe('Previous mount cleanup record is invalid or uncertain; cleanup was not repeated.')
            old_capture, commands = previous['capture'], previous['commands']
            same_incident = previous['incident'] == request['incident']
            same_scope = all(old_capture[key] == captured[key] for key in ('boot', 'uuid', 'target'))
            if same_incident and not same_scope:
                raise Unsafe('The cleanup incident boot or storage configuration changed; previous work was not repeated.')
            if not same_incident:
                # Mount IDs/device numbers may be reused after a successful
                # recovery. Settled history from another incident is evidence,
                # not this outage's command budget or pending-loop authority.
                history = STATE_DIR / 'cleanup-history'
                history.mkdir(mode=0o700, exist_ok=True)
                atomic_write(history / (uuidlib.uuid5(uuidlib.NAMESPACE_URL, raw).hex + '.json'), raw)
            else:
                if previous.get('complete') is True:
                    raise Unsafe('Cleanup already completed for this incident; it was not repeated.')
                prior_commands.extend(commands)
                if any(item.get('removed') is True and item.get('mount') in tree for item in prior_commands):
                    raise Unsafe('A previously removed mount identity appeared again; cleanup stopped.')
                if mount_record(main) in old_capture['tree']:
                    # A stop recheck can pause after child unmount and before
                    # detaching its non-autoclear loop. Keep the exact original
                    # backing proof; a live inventory must still match below.
                    for loop in old_capture.get('loops', []):
                        if (isinstance(loop, dict) and loop.get('mount') not in tree
                                and any(item.get('mount') == loop.get('mount') and item.get('removed') is True
                                        for item in commands)
                                and not any(item.get('action') == 'loop-detach' and item.get('target') == loop.get('name')
                                            and item.get('sent') is not False for item in commands)
                                and loop not in loops):
                            loops.append(loop)
    loops.sort(key=lambda item: len(item['mount']['target']), reverse=True)
    marker = dict(version=2, capture=captured, incident=request['incident'], phase='returned',
                  time=timestamp(), commands=copy.deepcopy(prior_commands), remaining=remaining)

    def recheck():
        stop_check()
        if request.get('boot') != boot_id() or not config_load()['automatic_recovery']:
            raise Unsafe('Boot or automatic recovery configuration changed before cleanup.')
        latest = read_rows()
        current = detached_shutdown_mount(latest)
        actual = [mount_record(row) for row in latest if covers(MOUNT, row['target'])]
        if (current is None or mount_record(current) != mount_record(main)
                or sorted(actual, key=lambda row: row['id']) != sorted(remaining, key=lambda row: row['id'])):
            raise Unsafe('The failed mount tree changed; further cleanup stopped.')
        proofs = retained_image_loops(latest, current)
        if any(proof not in loops for proof in proofs):
            raise Unsafe('A configured image backing changed; further cleanup stopped.')
        # Mount IDs belong to one namespace. Other namespaces may retain a
        # cloned tree or old bind; neither changes the exact local target of
        # this ordinary unmount. Namespace exclusion remains mandatory before
        # global loop detach and before mounting the returned live device.
        return latest

    def unmount(row, target_kind):
        used = sum(item.get('mount') == row and item.get('sent') is not False
                   for item in prior_commands)
        if used >= 2:
            raise Unsafe('The bounded ordinary-unmount attempts for this exact mount were already completed.')
        for attempt in range(used, 2):
            recheck()
            action = dict(target=row['target'], mount=row, phase='intent', time=timestamp(), attempt=attempt + 1)
            marker['commands'].append(action)
            marker.update(phase='intent', remaining=copy.deepcopy(remaining))
            write_receipt(marker_path, marker)
            try:
                note(target_kind, 'stale-unmount-intent', row['target'])
                recheck()
            except (apps.AppError, Unsafe, OSError, ValueError) as exc:
                # These checks precede dispatch. Persist that no command was
                # sent, so a fresh verified stop may safely resume the work.
                action.update(phase='returned', sent=False, finished_at=timestamp(), reason=str(exc))
                marker.update(phase='returned', finished_at=timestamp())
                write_receipt(marker_path, marker)
                note(target_kind, 'stale-unmount-returned', row['target'] + ': command not sent')
                raise
            failure = ''
            try:
                command(['/usr/bin/umount', '--internal-only', '--no-canonicalize', '--', row['target']], timeout=15)
            except UnmountFailure as exc:
                failure = str(exc)  # Returned failure, not an unknown timeout.
            latest = read_rows()
            actual = [mount_record(item) for item in latest if covers(MOUNT, item['target'])]
            after = [item for item in remaining if item != row]
            removed = sorted(actual, key=lambda item: item['id']) == sorted(after, key=lambda item: item['id'])
            unchanged = sorted(actual, key=lambda item: item['id']) == sorted(remaining, key=lambda item: item['id'])
            action.update(phase='returned', finished_at=timestamp(), removed=removed, reason=failure)
            marker.update(phase='returned', finished_at=timestamp(), remaining=actual)
            write_receipt(marker_path, marker)
            note(target_kind, 'stale-unmount-returned', row['target'] + (': removed' if removed else ': still mounted'))
            if removed:
                remaining[:] = after
                return
            if not unchanged:
                raise Unsafe('The mount tree changed after ordinary unmount; further cleanup stopped.')
            if attempt:
                raise Unsafe('Ordinary unmount did not release the configured mount after two completed attempts. ' + failure)
            time.sleep(0.5)

    recheck()
    for loop in loops:
        row = loop['mount']
        if row in remaining:
            unmount(row, 'dependent')
        # Autoclear is usual; otherwise detach only the same fully unmounted
        # configured loop, after namespace and exact backing checks.
        try:
            backing_path = (Path('/sys/dev/block') / row['dev'] / 'loop/backing_file').read_text().strip()
        except FileNotFoundError:
            backing_path = None
        if backing_path is not None:
            namespace_available(row['dev'])
            configured = next((item for item in settings.storage_images(SETTINGS, enabled=False)
                               if item['mountpoint'] == row['target']), None)
            metadata = udev(row['dev'])
            if (not configured or configured['image'] != loop['image'] or not row['dev'].startswith('7:')
                    or row['fs'] != 'ext4' or row['root'] != '/'
                    or metadata.get('ID_FS_UUID') != configured['uuid'] or metadata.get('ID_FS_TYPE') != 'ext4'
                    or str((Path('/dev/block') / row['dev']).resolve(strict=True)) != loop['name']):
                raise Unsafe('The unmounted loop no longer matches its configured image; detach refused.')
            matches = [entry for entry in loop_inventory() if entry.get('name') == loop['name']]
            if (backing_path != loop['image'] or len(matches) != 1
                    or matches[0].get('back-file') != loop['image']
                    or matches[0].get('back-maj:min') != loop['backing']
                    or int(matches[0].get('back-ino', -1)) != loop['back_inode']
                    or int(matches[0].get('offset', -1)) != 0 or int(matches[0].get('sizelimit', -1)) != 0):
                raise Unsafe('Retained loop backing changed after unmount; detach refused.')
            recheck()
            marker['commands'].append(dict(target=loop['name'], phase='intent', action='loop-detach'))
            marker['phase'] = 'intent'
            write_receipt(marker_path, marker)
            try:
                note('dependent', 'loop-detach-intent', row['target'])
                recheck()
            except (apps.AppError, Unsafe, OSError, ValueError) as exc:
                marker['commands'][-1].update(phase='returned', sent=False, finished_at=timestamp(), reason=str(exc))
                marker.update(phase='returned', finished_at=timestamp())
                write_receipt(marker_path, marker)
                note('dependent', 'loop-detach-returned', row['target'] + ': command not sent')
                raise
            command(['/usr/sbin/losetup', '--detach', '--', loop['name']], timeout=8)
            marker['commands'][-1].update(phase='returned', finished_at=timestamp())
            marker['phase'] = 'returned'
            write_receipt(marker_path, marker)
            note('dependent', 'loop-detach-returned', row['target'])
    unmount(mount_record(main), 'main')
    marker.update(phase='returned', finished_at=timestamp(), complete=True, remaining=[])
    write_receipt(marker_path, marker)


def mount_main(note):
    """One normal mount, using the established identity and filesystem guards."""
    if snapshot()['healthy']:
        return
    device = Path('/dev/disk/by-uuid') / DISK_UUID
    rows = read_rows()
    dev = device_number(device)
    mount_available(rows, MOUNT, dev)
    block_checks(dev, DISK_UUID)
    if not MANUAL_MOUNT or FSTAB_MAIN_OPTIONS:
        fstab_check(MOUNT)
    backing = recovery_backing(rows, MOUNT, dev)
    protected_mount_directory(MOUNT, backing, create=True)
    real = device.resolve(strict=True)
    proof = disk_proof(real, DISK_UUID, unmounted=True)
    if f'{os.major(proof.st_rdev)}:{os.minor(proof.st_rdev)}' != dev:
        raise Unsafe('Device identity changed before mounting.')
    mount_available(read_rows(), MOUNT, dev)
    note('main', 'intent')
    try:
        argv = (['/usr/bin/mount', '--', MOUNT] if FSTAB_MAIN_OPTIONS else
                ['/usr/bin/mount', '-t', 'ext4', '-o', 'rw,nodev,nosuid', '--', str(device), MOUNT])
        command(argv, timeout=12)
    except Unsafe as exc:
        note('main', 'failed', str(exc))
        raise
    note('main', 'returned')


def recovery_work(request, receipt_path):
    if not MANUAL_MOUNT and not request.get('check_only') and request.get('allow_mount'):
        with ExitStack() as locks:
            try:
                stop_check = locks.enter_context(apps.storage_recovery_guard(usb_context(), request))
            except apps.AppError as exc:
                current = snapshot()
                return dict(main=False, dependent=False, actions=[], blocked=[], waiting_stop=True,
                            reason='Waiting for selected containers to be confirmed stopped: ' + str(exc),
                            dependent_reason='Storage recovery is waiting for confirmed container stops.',
                            detected=current['detected'], mounts=current['mounts'], usb=USB_REASON)
            return guarded_recovery_work(request, receipt_path, stop_check or (lambda: None))
    return guarded_recovery_work(request, receipt_path)


def guarded_recovery_work(request, receipt_path, stop_check=lambda: None):
    result = {'main': False, 'dependent': False, 'actions': [], 'blocked': [],
              'reason': '', 'dependent_reason': 'Main Storage filesystem unavailable.',
              'detected': False, 'usb': USB_REASON, 'mounts': []}
    def note(action, stage, detail=''):
        if stage == 'intent' or stage.endswith('-intent'):
            stop_check()
        result['actions'].append({'target': action, 'stage': stage, 'time': timestamp(), 'detail': detail})
        # Intent is durable BEFORE invoking mount; a crash never repeats it.
        write_receipt(receipt_path, {'incident': request['incident'], 'number': request['number'], 'result': result, 'complete': False})
    try:
        initial = snapshot()
        result['detected'] = initial['detected']
        result['mounts'] = initial['mounts']
        if not initial['healthy']:
            if 'main' in request['blocked']:
                reason = (initial['detail'] if initial.get('unsafe') or initial.get('mount_state') == 'conflict' else
                          request.get('blocked_reason') or 'A previous unsafe or uncertain storage state blocked this incident.')
                raise Unsafe('Recovery stopped: ' + mount_text(reason, 700))
            if not request['allow_mount']:
                raise Unsafe('Automatic main mount is disabled for this incident.')
            if initial.get('detached_shutdown_mount'):
                if MANUAL_MOUNT:
                    cleanup_detached_main(request, note)
                elif automatic_cleanup_eligible(initial, request.get('boot')):
                    cleanup_failed_main(request, note, stop_check)
                else:
                    raise Unsafe('The occupied target is not eligible for automatic failed-mount cleanup.')
                result['cleanup_complete'] = True
                result['mounts'] = snapshot()['mounts']
            device = Path('/dev/disk/by-uuid') / DISK_UUID
            first_failure = None
            present = device.exists()
            if not present and not request.get('allow_usb'):
                result.update(waiting_device=True, reason='Waiting for the selected disk to reconnect.')
                return result
            if present:
                try:
                    mount_main(note)
                except MountFailure as exc:
                    first_failure = None if snapshot()['healthy'] else str(exc)
            if not present or first_failure:
                # Exactly one qualified port cycle, then one final normal mount.
                # A missing disk uses the saved, same-boot verified port binding.
                stop_check()
                reset = usb.cycle(usb_context(), request | {'allow_present': bool(first_failure)})
                result['usb'] = reset['reason']
                if reset.get('ready'):
                    note('usb', 'returned', reset['reason'])
                    if not snapshot()['healthy']:
                        mount_main(note)
                elif not reset.get('cycled') and not first_failure and device.exists():
                    # Natural return raced a safely skipped reset; normal guards still apply.
                    mount_main(note)
                else:
                    if not first_failure and not snapshot()['detected']:
                        result.update(waiting_device=True, reason='Waiting for the selected disk to reconnect. '
                                      + reset['reason'], blocked=[])
                        return result
                    raise Unsafe((first_failure + '. ' if first_failure else 'Expected device absent. ') + reset['reason'])
        verify_main()
        # Only recovery workers touch filesystem contents; routine checks use
        # mount/udev/sysfs metadata so an idle, mounted HDD stays asleep.
        verify_access()
        result.update(main=True, detected=True, reason='Main ext4 UUID/type and both rw flags independently verified.')
    except (OSError, ValueError, KeyError, Unsafe, apps.AppError) as exc:
        result['reason'] = str(exc) if isinstance(exc, Unsafe) else f'Main verification: {type(exc).__name__}'
        if isinstance(exc, apps.AppError):
            result['reason'] = 'Container stop verification changed: ' + str(exc)
            if storage_actions_settled([dict(status='failed', actions=result['actions'])]):
                result.update(waiting_stop=True, blocked=[])
                return result
        if isinstance(exc, FileNotFoundError) and not result['actions'] and not snapshot()['detected']:
            result.update(waiting_device=True, reason='Waiting for the selected disk to reconnect.')
            return result
        result['blocked'].append('main')
        result['mounts'] = snapshot()['mounts']
        return result
    if not DEPENDENT_ENABLED:
        result.update(dependent=True, dependent_reason='No dependent filesystem configured.')
        return result
    result['images'] = []
    for item in DEPENDENCIES:
        try:
            recover_image(item, request, note)
            result['images'].append(dict(uuid=item['uuid'],name=item['name'],healthy=True,detail='Storage verified read/write.'))
        except apps.AppError as exc:
            result.update(main=False, reason='Container stop verification changed: ' + str(exc),
                          waiting_stop=True, blocked=[])
            if not storage_actions_settled([dict(status='failed', actions=result['actions'])]):
                result.update(waiting_stop=False, blocked=['main', 'dependent'])
            return result
        except (OSError, ValueError, KeyError, TypeError, Unsafe) as exc:
            result['images'].append(dict(uuid=item['uuid'],name=item['name'],healthy=False,detail=str(exc)))
    if len(DEPENDENCIES)>1:
        for item,outcome in zip(DEPENDENCIES,result['images']):
            if outcome['healthy']:
                try: verify_dependent(item)
                except (OSError,ValueError,Unsafe) as exc:
                    outcome.update(healthy=False,detail='Final storage check: '+str(exc))
    result['dependent'] = all(item['healthy'] for item in result['images'])
    result['dependent_reason'] = '; '.join(item['name'] + ': ' + item['detail'] for item in result['images'])
    if not result['dependent']: result['blocked'].append('dependent')
    current = snapshot()
    result['mounts'] = current['mounts']
    if not current['healthy']:
        result.update(main=False, reason='Main filesystem lost health during application storage verification: ' + current['detail'])
    return result


def recover_image(item, request, note):
    # Never substitute files underneath a missing required parent image mount.
    registered = settings.storage_images(SETTINGS, enabled=False)
    for parent in registered:
        if parent != item and any(covers(parent['mountpoint'],item[key]) for key in ('image','mountpoint')):
            verify_dependent(parent)
    rows = read_rows()
    if not any(covers(item['mountpoint'], r['target']) for r in rows):
        if not request['allow_mount'] or 'dependent' in request['blocked']:
            raise Unsafe('Automatic dependent mount is disabled for this incident.')
        verify_main()
        allowed = {MOUNT} | {v['mountpoint'] for v in registered if v != item}
        for path in (item['image'], item['mountpoint']):
            parent = visible_mount(rows, path)
            if not parent or parent['target'] not in allowed:
                raise Unsafe('Image/target is covered by an unexpected mount.')
            if parent['target'] != MOUNT:
                verify_dependent(next(v for v in registered if v['mountpoint'] == parent['target']))
        safe_path(item['mountpoint'], os.stat(visible_mount(rows,item['mountpoint'])['target']).st_dev)
        info = safe_path(item['image'], os.stat(visible_mount(rows,item['image'])['target']).st_dev, directory=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Unsafe('Backing image is not a single regular file.')
        # Do not reuse an active, stale, attached or differently mounted loop image.
        for loop in Path('/sys/class/block').glob('loop*/loop/backing_file'):
            if loop.read_text().strip() == item['image']:
                raise Unsafe('Backing image is already attached to a loop device; manual intervention required.')
        fstab_check(item['mountpoint'])
        disk_proof(Path(item['image']), item['uuid'], unmounted=True, regular=True)
        verify_main()
        if any(covers(item['mountpoint'], r['target']) for r in read_rows()):
            raise Unsafe('Dependent target became active before mounting.')
        note('dependent', 'intent', item['name'])
        command(['/usr/bin/mount', '--', item['mountpoint']], timeout=12)
        note('dependent', 'returned', item['name'])
    metadata_deadline = time.monotonic() + 3
    while True:
        try:
            verify_dependent(item)
            break
        except (FileNotFoundError, MetadataPending):
            # A new loop can have a udev record before its filesystem fields
            # arrive. Known mismatches still fail immediately; this only
            # retries incomplete read-only proof within the existing bound.
            if time.monotonic() >= metadata_deadline:
                raise
            time.sleep(0.2)
    verify_main()



class Monitor:
    def __init__(self, path=STATE, now=None, boot=None, application_tracking=True):
        self.application_tracking = application_tracking
        self.path = path
        self.state = load_state(path)
        self.boot = boot or boot_id()
        now = clock_now() if now is None else now
        s = copy.deepcopy(self.state)
        incident = s['incident']
        if incident and incident['phase'] not in ('done', 'legacy'):
            return_deadline.advance(incident, SETTINGS.get('recovery', {}).get('return_timeout_minutes', 5),
                                    now, self.boot, return_deadline.epoch(timestamp()))
        if incident:
            self.sync_usb(incident)
            app = incident.get('applications')
            if app and incident['phase'] not in ('done', 'legacy'):
                incident.setdefault('stop', dict(phase='pending'))
                if incident['stop']['phase'] == 'running':
                    # apps.stop_selected resumes by inspecting its durable
                    # intent; it never repeats an uncertain stop command.
                    incident['stop']['phase'] = 'pending'
            if app and app['capture_phase'] == 'running':
                app.update(capture_phase='done', capture_error='Incident-time capture interrupted; not repeated.')
            if incident['phase'] == 'applications':
                # Resume from the separate durable per-container ledger; never
                # resend an intent already reserved before the service stopped.
                app['phase'] = 'ready'
                s.update(candidate=None, count=0, sample_at=None)
        if incident and incident['boot'] != self.boot:
            incident.update(boot=self.boot, rebooted=True, due=now + RECOVERY_DELAY, proof_due=now)
            if incident.get('stop') and incident['phase'] not in ('done', 'legacy'):
                incident['stop'].update(phase='pending', next_due=now)
            if incident['phase'] in ('verify', 'applications') and incident.get('result'):
                incident['result']['main'] = False  # Re-prove after reboot.
            s.update(candidate=None, count=0, sample_at=None, first_bad=None)
        if incident and incident['phase'] == 'running':
            record = None
            try:
                record = json.loads((path.parent / 'recovery-receipt.json').read_text())
                if (record.get('complete') and record['incident'] == incident['id']
                        and record.get('number') == len(incident['attempts'])):
                    self.commit(s)
                    self.work_result({'incident': incident['id'], 'check_only': False},
                                     record['result'], now)
                    return
            except (OSError, ValueError, KeyError):
                pass
            # Reserved work is consumed, never replayed after an uncertain crash.
            attempt = incident['attempts'][-1]
            attempt.update(status='interrupted', reason='Monitor restarted during reserved recovery; action result uncertain.')
            mount_uncertain = not (
                record and record.get('incident') == incident['id']
                and record.get('number') == len(incident['attempts'])
                and not any(a.get('target') in ('main', 'dependent') for a in record.get('result', {}).get('actions', [])))
            if mount_uncertain:
                incident['blocked'] = ['main', 'dependent']
            incident['phase'] = 'wait2' if len(incident['attempts']) < MAX_ATTEMPTS else 'verify'
            incident['due'] = now + RECOVERY_DELAY
            incident['result'] = {'main': False, 'dependent': False, 'actions': [],
                                  'reason': attempt['reason'], 'dependent_reason': 'Not verified.',
                                  'detected': None, 'mounts': [], 'blocked': list(incident['blocked'])}
        if incident and incident['phase'] in ('wait2', 'verify') and len(incident['attempts']) >= MAX_ATTEMPTS and not incident.get('result', {}).get('main'):
            self.finalize(s, incident.get('result') or failed_result('Previous recovery sequence was interrupted; automatic attempts stopped.'))
        # Persist migration/restart handling before any action or delivery.
        if s != self.state or not path.exists():
            self.commit(s)

    def commit(self, state):
        atomic_write(self.path, json.dumps(state, indent=2, allow_nan=False) + '\n')
        self.state = state

    def sync_usb(self, incident):
        record = usb.incident_record(usb_context(self.path.parent), incident['id'])
        if record:
            incident['usb_resets'] = max(incident['usb_resets'], record['reset_count'])
            incident['usb'] = record['reason']
            incident['usb_record'] = record

    def sample(self, current, now=None, wall=None):
        now = clock_now() if now is None else now
        wall = timestamp() if wall is None else wall
        s = copy.deepcopy(self.state)
        okay = current['healthy']
        connection = current.get('connection')
        consecutive = (s['sample_boot'] == self.boot and s['sample_at'] is not None
                       and max(1, INTERVAL - 1) <= now - s['sample_at'] <= INTERVAL * 2
                       and s.get('candidate_connection') == connection)
        s['count'] = min(s['count'] + 1, OBSERVATIONS) if consecutive and s['candidate'] == okay else 1
        s.update(candidate=okay, candidate_connection=connection, sample_at=now, sample_boot=self.boot)
        if okay:
            s['first_bad'] = None
            s['last_healthy'] = current
        elif s['count'] == 1:
            s['first_bad'] = {'time': wall, 'at': now, 'boot': self.boot, 'detail': current['detail'], 'state': current}
        i = s['incident']
        legacy_resume = None
        # UI18-21 may have exhausted a no-proof recovery or retained an active
        # legacy mount wait. UI22/23 may have refused namespace references or
        # an older cleanup receipt before any storage command. Re-capture eligible settled work once;
        # never migrate an uncertain write or manufacture healthy proof.
        cleanup_ready = automatic_cleanup_eligible(current, self.boot)
        migration_ready = cleanup_ready or (not current.get('unsafe') and
            current.get('mount_state') in ('unmounted', 'unavailable') and
            not current.get('mount_target_occupied'))
        if (i and not okay and i['phase'] != 'done' and i.get('legacy_mount_wait')
                and not i['attempts'] and i.get('recovery_generation', 0) < 22 and migration_ready
                and storage_actions_settled(i.get('cleanup_attempts', []) + i.get('paused_attempts', []))):
            # An active wait still owns the original running-state and verified
            # stop evidence. Archive it, then re-evaluate that same incident
            # under today's configuration; the guard rechecks every selection.
            archive = self.path.parent / 'incidents'
            archive.mkdir(mode=0o700, exist_ok=True)
            atomic_write(archive / (i['id'] + '-before-ui22.json'), json.dumps(i, indent=2) + '\n')
            i.update(recovery_generation=24, legacy_wait_migrated=True, blocked=[],
                     config_digest=CONFIG_DIGEST, storage_config_digest=STORAGE_CONFIG_DIGEST,
                     first_state=current)
            i.pop('legacy_mount_wait', None)
            i.pop('legacy_no_write_resume', None)
            i.pop('blocked_reason', None)
        no_write_previous = bool(i and i.get('recovery_generation') in (22, 23) and cleanup_ready
            and not any(attempt.get('actions') for attempt in
                        i['attempts'] + i.get('cleanup_attempts', []) + i.get('paused_attempts', [])))
        if (i and not okay and i['phase'] == 'done'
                and (i.get('recovery_generation', 0) < 22 or no_write_previous) and migration_ready
                and not i.get('result', {}).get('main')
                and storage_actions_settled(i['attempts'] + i.get('cleanup_attempts', []) + i.get('paused_attempts', []))):
            legacy_resume = copy.deepcopy(i)
            s['status'] = 'unknown'
        # A distinct attachment can recover after the previous device vanished.
        # Never replay an uncertain storage write or erase its audit history.
        prior = i.get('connection') if i else None
        if i and not okay and i['phase'] == 'done' and connection and current.get('detected'):
            proof = i.get('known_state', {}).get('main_mount_proof')
            own_stale = cleanup_ready
            changed = bool(prior and prior['boot'] == self.boot and prior != connection)
            legacy_stale = bool(i.get('recovery_generation', 0) < 22 and own_stale)
            settled = storage_actions_settled(i['attempts'] + i.get('cleanup_attempts', []) + i.get('paused_attempts', []))
            safe_return = not current.get('unsafe') or own_stale
            if (changed or legacy_stale) and settled and safe_return and s['count'] >= OBSERVATIONS:
                s['status'] = 'unknown'
        s['reconnect_pending'] = False
        if i and connection and (i['phase'] not in ('done', 'legacy') or not prior
                                  or prior['boot'] != self.boot):
            i['connection'] = connection
        if (s['count'] == OBSERVATIONS or self.application_tracking) and not okay and s['status'] != 'down':
            if i:
                archive = self.path.parent / 'incidents'
                archive.mkdir(mode=0o700, exist_ok=True)
                atomic_write(archive / (i['id'] + '.json'), json.dumps(i, indent=2) + '\n')
            s.update(status='down', changed_at=wall)
            first = s['first_bad']
            if legacy_resume:
                # A user may have already released the obsolete mount before
                # upgrading. Do not re-latch its historic unsafe observation.
                first = dict(time=wall, at=now, boot=self.boot, detail=current['detail'], state=current)
                s['first_bad'] = first
            i = new_incident(first['time'], first['detail'], now, self.boot)
            i['connection'] = connection or s.get('last_connection')
            i['first_state'] = first['state']
            i['known_state'] = s.get('last_healthy', {})
            if legacy_resume:
                i['legacy_recovery_resume'] = legacy_resume['id']
                i['legacy_no_write_resume'] = not any(attempt.get('actions') for attempt in legacy_resume['attempts'])
                # Upgrading does not grant another USB reset for this outage.
                i['usb_resets'] = legacy_resume['usb_resets']
                i['usb'] = legacy_resume['usb']
                if legacy_resume.get('usb_record'):
                    i['usb_record'] = legacy_resume['usb_record']
                previous_known = legacy_resume.get('known_state', {})
                if (not known_detached_mount(current, i['known_state'].get('main_mount_proof'))
                        and known_detached_mount(current, previous_known.get('main_mount_proof'))):
                    i['known_state'] = previous_known
            if self.application_tracking:
                i['applications'] = apps.incident_state(s.get('last_apps'), now, self.boot, first_bad=first, interval=INTERVAL)
                i['applications'].update(capture_deadline=now + INTERVAL, capture_boot=self.boot)
                i['stop'] = dict(phase='pending')
            if first['state'].get('unsafe') and not automatic_cleanup_eligible(first['state'], self.boot):
                i['blocked'].append('main')
                i['blocked_reason'] = mount_text(first['state']['detail'], 700)
            s['incident'] = i
            log('Storage failure detected; selected containers will stop before recovery. Incident ' + i['id'])
        if i and s['status'] == 'down':
            i['latest'] = current
            if i['phase'] not in ('done', 'legacy'):
                deadline = return_deadline.advance(i, SETTINGS.get('recovery', {}).get('return_timeout_minutes', 5),
                                                   now, self.boot, return_deadline.epoch(wall))
                # Only a fresh explicit absence can report a no-return failure.
                # A return observed on the boundary wins. Never interrupt a
                # running worker or spend/reset its existing action budget.
                if (current.get('detected') is False and deadline['remaining'] <= 0
                        and not deadline.get('reported_at')):
                    result = dict(main=False, dependent=False, detected=False, actions=[], mounts=current.get('mounts', []),
                                  reason=return_deadline.failure_message(i), dependent_reason='Required drive is absent.')
                    self.finalize(s, result, timed_out=True)
            # Keep old unknown/foreign conflicts waiting, but a freshly
            # classified failed configured mount can proceed automatically.
            if (i.get('legacy_no_write_resume') and not i['attempts']
                    and (current.get('unsafe') or current.get('detached_shutdown_mount')
                         or current.get('mount_state') in ('conflict', 'mounted_elsewhere'))
                    and not cleanup_ready):
                i['legacy_mount_wait'] = True
            if i.get('legacy_mount_wait'):
                connection_ready = (connection and connection.get('boot') == self.boot
                                    and current.get('detected') is True)
                safe_mount_state = (not current.get('unsafe') and
                                    (current.get('mount_state') == 'unmounted' or current.get('healthy') is True))
                if cleanup_ready or (connection_ready and safe_mount_state):
                    # This flag is set only for an inherited no-write conflict.
                    # Once that conflict is gone, re-evaluate normal guards in
                    # the same incident; its verified stop must not be repeated.
                    i.pop('legacy_mount_wait')
                    i['blocked'] = [item for item in i['blocked'] if item != 'main']
                    i.pop('blocked_reason', None)
            hard_unsafe = current.get('unsafe') and not cleanup_ready
            if hard_unsafe and 'main' not in i['blocked']:
                i['blocked'].append('main')
            if hard_unsafe:
                i['blocked_reason'] = mount_text(current['detail'], 700)
            # Re-arm only after two healthy samples AND independent direct proof.
            if okay and s['count'] == OBSERVATIONS and i.get('result', {}).get('main') and i['phase'] == 'verify':
                if not current['dependent']:
                    i['result'].update(dependent=False, dependent_reason=current['dependent_detail'])
                if self.finalize(s, i['result']):
                    s.update(status='up', changed_at=wall)
            elif not okay and i['phase'] == 'verify':
                i['result']['main'] = False
                i['result']['reason'] = 'Health was not sustained after action: ' + current['detail']
                if len(i['attempts']) < MAX_ATTEMPTS:
                    i.update(phase='wait2', due=now + RECOVERY_DELAY)
                else:
                    self.finalize(s, i['result'])
        if okay and s['count'] == OBSERVATIONS and s['status'] == 'unknown':
            s.update(status='up', changed_at=wall)
        if connection:
            s['last_connection'] = connection
        self.commit(s)

    def stop_request(self, now=None):
        now = clock_now() if now is None else now
        s = copy.deepcopy(self.state)
        i = s['incident']
        if (not i or i.get('stop', {}).get('phase') != 'pending'
                or now < i['stop'].get('next_due', 0)):
            return None
        i['stop']['phase'] = 'running'
        request = {'incident': i['id'], 'boot': self.boot,
                   'config_digest': i.get('config_digest', CONFIG_DIGEST)}
        if i.get('storage_config_digest'):
            request['storage_config_digest'] = i['storage_config_digest']
        self.commit(s)
        return request

    def stop_result(self, result):
        s = copy.deepcopy(self.state)
        i = s['incident']
        i['stop'] = dict(phase='done', result=result)
        if result.get('all_stopped') is not True:
            # Re-read a late stop result without resending its durable intent.
            # Temporary Docker unavailability must not permanently strand the
            # disk recovery state machine.
            i['stop'].update(phase='pending', next_due=clock_now() + INTERVAL)
        self.commit(s)

    def capture_request(self, now=None):
        now = clock_now() if now is None else now
        s = copy.deepcopy(self.state)
        i = s['incident']
        app = i.get('applications') if i else None
        if app and app['capture_phase'] == 'pending':
            if app['capture_boot'] != self.boot or now > app['capture_deadline']:
                app.update(capture_phase='done', capture_error='Incident-time inspection deadline missed; late state not substituted.')
                self.commit(s)
                return None
            app['capture_phase'] = 'running'
            self.commit(s)
            return {'incident': i['id'], 'boot': self.boot}
        if self.application_tracking and s['candidate'] is True and s['status'] != 'down':
            return {'incident': None, 'boot': self.boot}
        return None

    def capture_result(self, request, result):
        s = copy.deepcopy(self.state)
        if request['incident'] is None:
            if s['candidate'] is True and s['status'] != 'down' and result.get('boot') == self.boot:
                s['last_apps'] = result
        else:
            i = s['incident']
            if i and i['id'] == request['incident']:
                i['applications'].update(capture_phase='done', detected=result)
        self.commit(s)

    def app_request(self):
        s = copy.deepcopy(self.state)
        i = s['incident']
        if (not i or i['phase'] != 'applications' or i['applications']['phase'] != 'ready'
                or s['candidate'] is not True or s['count'] < OBSERVATIONS
                or clock_now() < i['applications'].get('next_due', 0)
                or (i.get('stop') and (i['stop']['phase'] != 'done'
                    or i['stop'].get('result', {}).get('all_stopped') is not True))):
            return None
        i['applications']['phase'] = 'running'
        request = {'incident': i['id'], 'boot': self.boot, 'plan': apps.plan(i['applications']),
                   'config_digest': i.get('config_digest', CONFIG_DIGEST),
                   'stop': i.get('stop', {}).get('result')}
        if i.get('storage_config_digest'):
            request['storage_config_digest'] = i['storage_config_digest']
        self.commit(s)
        return request

    def app_result(self, result):
        s = copy.deepcopy(self.state)
        i = s['incident']
        if result.get('waiting_storage'):
            i['applications'].update(phase='ready', result=result, next_due=clock_now() + INTERVAL)
            self.commit(s)
            return
        i['applications'].update(phase='done', result=result)
        if result.get('interrupted') or s['candidate'] is not True:
            i['result'].update(main=False, reason='Storage became unavailable/unsafe during the application restart stage.')
        elif result.get('storage_verified'):
            i['result']['main'] = True
        if not i.get('latest', {}).get('dependent', False):
            i['result'].update(dependent=False, dependent_reason=i.get('latest', {}).get('dependent_detail', 'dependent loop unavailable.'))
        self.finalize(s, i['result'])
        if i['result']['main']:
            s.update(status='up', changed_at=timestamp())
        elif result.get('interrupted') or s['candidate'] is False:
            # Storage was proved restored before the application stage. If it
            # fails again after a start was accepted, this is a new outage:
            # reserve a new stop ledger instead of trusting the earlier stop.
            archive = self.path.parent / 'incidents'
            archive.mkdir(mode=0o700, exist_ok=True)
            atomic_write(archive / (i['id'] + '.json'), json.dumps(i, indent=2) + '\n')
            now = clock_now()
            current = dict(i.get('latest', {}), healthy=False)
            fresh = new_incident(timestamp(), current.get('detail', 'Storage failed during container startup.'), now, self.boot)
            fresh.update(connection=current.get('connection') or i.get('connection'),
                         first_state=current, latest=current, known_state=s.get('last_healthy', {}),
                         stop=dict(phase='pending'))
            fresh['applications'] = apps.incident_state(s.get('last_apps'), now, self.boot)
            fresh['applications'].update(capture_deadline=now + INTERVAL, capture_boot=self.boot)
            if current.get('unsafe') and not automatic_cleanup_eligible(current, self.boot):
                fresh['blocked'] = ['main']
                fresh['blocked_reason'] = mount_text(current.get('detail', ''), 700)
            s['incident'] = fresh
            s.update(status='down', candidate=False, count=0, sample_at=None)
        self.commit(s)

    def work_request(self, enabled, now=None, usb_enabled=False):
        now = clock_now() if now is None else now
        s = copy.deepcopy(self.state)
        i = s['incident']
        if not i or s['status'] != 'down':
            return None
        if i.get('stop') and (i['stop']['phase'] != 'done'
                or i['stop'].get('result', {}).get('all_stopped') is not True):
            return None
        cleanup_ready = automatic_cleanup_eligible(i.get('latest', {}), self.boot)
        if i.get('legacy_mount_wait') and not cleanup_ready:
            return None  # No ownership proof: wait without consuming a mount attempt.
        # After a final outcome, only read-only proof may re-arm a new incident.
        check_only = (i['phase'] in ('done', 'legacy') or (i['phase'] == 'verify'
                      and not i.get('result', {}).get('main'))) and s['candidate'] is True and s['count'] >= OBSERVATIONS
        if check_only and now < i.get('proof_due', 0):
            return None
        if not check_only and (i['phase'] not in ('wait1', 'wait2', 'return_failed') or now < i['due']):
            return None
        if not check_only and not enabled and i.get('stop') and not i.get('latest', {}).get('healthy'):
            return None  # Selected containers wait for a manual/natural mount.
        if (not check_only and enabled and not i.get('latest', {}).get('detected')
                and not cleanup_ready
                and (not usb_enabled or i.get('return_wait') or i['usb_resets'] >= MAX_USB_RESETS)):
            return None  # Absence is waiting, not a spent mount attempt.
        if not check_only:
            if len(i['attempts']) >= MAX_ATTEMPTS:
                return None
            i['attempts'].append({'number': len(i['attempts']) + 1, 'time': timestamp(), 'boot': self.boot,
                                  'status': 'running', 'reason': 'Reserved durably before worker launch.'})
            i['phase'] = 'running'
        else:
            i['proof_due'] = now + RECOVERY_DELAY
        request = {'incident': i['id'], 'boot': self.boot, 'stop': i.get('stop', {}).get('result'),
                   'allow_mount': bool(enabled and not check_only),
                   'blocked': list(i['blocked']), 'check_only': check_only,
                   'number': len(i['attempts']), 'usb_resets': i['usb_resets'], 'config_digest': i.get('config_digest', CONFIG_DIGEST),
                   'allow_usb': bool(enabled and usb_enabled and not check_only),
                   'known_devs': [m['dev'] for m in i.get('known_state', {}).get('mounts', []) if 'dev' in m]
                       if i.get('known_state', {}).get('usb_binding_verified') else [],
                   'known_sources': i.get('known_state', {}).get('usb_sources', []),
                   'known_binding': i.get('known_state', {}).get('usb_binding'),
                   'known_storage': i.get('known_state', {}).get('main_mount_proof')}
        if 'main' in i['blocked']:
            prior = i.get('latest') if i.get('latest', {}).get('unsafe') else i.get('first_state', {})
            reason = i.get('blocked_reason') or (prior.get('detail') if prior.get('unsafe') else None)
            if reason:
                request['blocked_reason'] = mount_text(reason, 700)
        if i.get('storage_config_digest'):
            request['storage_config_digest'] = i['storage_config_digest']
        self.commit(s)
        return request

    def work_result(self, request, result, now=None):
        now = clock_now() if now is None else now
        s = copy.deepcopy(self.state)
        i = s['incident']
        if i['id'] != request['incident']:
            raise ValueError('Recovery result incident mismatch')
        i['usb'] = result.get('usb', i['usb'])
        self.sync_usb(i)
        if request['check_only']:
            if result['main'] and s['candidate'] is True and s['count'] >= OBSERVATIONS:
                if not i['notified']:
                    # Legacy ALERT may already have been delivered; retain its
                    # restoration semantics without initiating recovery actions.
                    result['actions'] = []
                    if not self.finalize(s, result):
                        self.commit(s)
                        return
                s.update(status='up', changed_at=timestamp())
                i['phase'] = 'done'
                log('Verified healthy; a separate future outage may start recovery.')
            self.commit(s)
            return
        a = i['attempts'][-1]
        if (result.get('waiting_stop') and
                storage_actions_settled([dict(status='failed', actions=result.get('actions', []))])):
            previous = i['attempts'].pop()
            if result.get('actions'):
                previous.update(status='failed', reason=result['reason'], finished_at=timestamp(),
                                actions=result['actions'], detected=result['detected'])
                i.setdefault('paused_attempts', []).append(previous)
            i.update(phase='wait1' if not i['attempts'] else 'wait2', due=now + INTERVAL, result=result)
            i.setdefault('stop', {})
            i['stop'].update(phase='pending', next_due=now)
            self.commit(s)
            return
        if (result.get('waiting_device') and result.get('cleanup_complete')
                and storage_actions_settled([dict(status='failed', actions=result.get('actions', []))])):
            # Cleaning an absent disk's failed tree is completed protective
            # work. Preserve its audit separately while keeping the single
            # actual remount attempt for the returned device.
            a.update(status='failed', reason=result['reason'], finished_at=timestamp(),
                     actions=result['actions'], detected=result['detected'])
            i.setdefault('cleanup_attempts', []).append(i['attempts'].pop())
            i.update(phase='return_failed' if i.get('return_deadline', {}).get('reported_at') else ('wait1' if not i['attempts'] else 'wait2'), due=now + INTERVAL,
                     return_wait=True, result=result)
            self.commit(s)
            return
        if result.get('waiting_device') and not result.get('actions'):
            i['attempts'].pop()
            i.update(phase='return_failed' if i.get('return_deadline', {}).get('reported_at') else ('wait1' if not i['attempts'] else 'wait2'), due=now + INTERVAL,
                     return_wait=True, result=result)
            self.commit(s)
            return
        if result.get('connection'):
            # A worker may itself have re-enumerated qualified hardware before
            # the next sample. Consume that attachment in this same budget.
            i['connection'] = result['connection']
        a.update(status='recovered' if result['main'] else 'failed',
                 reason=result['reason'], finished_at=timestamp(), detected=result['detected'],
                 actions=result['actions'], dependent=result['dependent'],
                 dependent_reason=result['dependent_reason'])
        i['blocked'] = sorted(set(i['blocked'] + result.get('blocked', [])))
        i['result'] = result
        if result['main']:
            # Require two subsequent 15-second samples before the final outcome.
            i['phase'] = 'verify'
            s.update(candidate=None, count=0, sample_at=None)
        elif len(i['attempts']) < MAX_ATTEMPTS:
            i.update(phase='wait2', due=now + RECOVERY_DELAY)
        else:
            self.finalize(s, result)
        self.commit(s)

    def finalize(self, state, result, *, timed_out=False):
        i = state['incident']
        if timed_out and i.get('return_deadline', {}).get('reported_at'): return True
        if i['notified']:
            i['phase'] = 'done'
            return True
        app = i.get('applications')
        if not timed_out and app and app['phase'] != 'done':
            if result['main']:
                i['result'] = result
                i['phase'] = 'applications'
                app['phase'] = 'ready'
                return False  # Keep the ONE final email until applications finish.
            app.update(phase='done', result=apps.no_actions(app,
                'Application restart not attempted because required storage remains unavailable.'))
        if not result['main']:
            subject = 'Storage RECOVERY FAILED — Manual intervention required'
        elif not result['dependent']:
            subject = 'Storage PARTIALLY RECOVERED — dependent loop mount unavailable'
        else:
            actions = [(a['number'], x) for a in (i['attempts'] + i.get('cleanup_attempts', []) + i.get('paused_attempts', []))
                       for x in a.get('actions', [])
                       if x['stage'] == 'returned' and a.get('boot') == self.boot]
            usb_record = i.get('usb_record', {})
            if (usb_record.get('boot') == self.boot and usb_record.get('enumeration_ready') is True
                    and usb_record.get('disable_confirmed_at') and usb_record.get('phase') == 'enabled'):
                # Preserve attribution if the worker died after USB/UUID proof
                # but before copying the successful action into its mount receipt.
                actions.append((1, {'target': 'usb', 'stage': 'returned'}))
            subject = (f'Storage AUTO-RECOVERED — Attempt {max(a[0] for a in actions)}' if actions
                       else ('Storage mount restored after reboot' if i.get('rebooted')
                             else 'Storage mount restored naturally'))
        if timed_out: subject += ' — Drive return timeout'
        if result['main'] and app and not app.get('result', {}).get('all_verified'):
            subject += ' — Applications require attention'
        current = i.get('latest', {})
        mounts = current.get('mounts', []) if result['main'] else result.get('mounts', [])
        detail = (f"First failure: {i['first_failure']}\nFirst observation: {i['first_detail']}\n"
                  f"Confirmed: {i['confirmed_at']}\nIncident: {i['id']}\n"
                  f"USB resets: {i['usb_resets']} budget reservation(s) (maximum {MAX_USB_RESETS}); {i['usb']}\n"
                  f"USB reset/enable record: {json.dumps(i.get('usb_record'))}\n"
                  f"Reboot observed during incident: {i.get('rebooted', False)}\n"
                  f"Recovery attempts:\n{json.dumps(i['attempts'], indent=2)}\n"
                  f"Completed cleanup before disk return:\n{json.dumps(i.get('cleanup_attempts', []), indent=2)}\n"
                  f"Completed actions before stop re-verification:\n{json.dumps(i.get('paused_attempts', []), indent=2)}\n"
                  f"Storage detected: {result.get('detected')}\nMain result: {result['reason']}\n"
                  f"dependent loop available: {result['dependent']}\ndependent loop result: {result['dependent_reason']}\n"
                  f"Current mounts: {json.dumps(mounts)}\n"
                  f"Latest observation: {current.get('detail', 'Unavailable')}\n")
        if i.get('stop'):
            detail += '\nContainer stop results:\n' + json.dumps(i['stop'], indent=2) + '\n'
        detail += ('\nApplication restart results:\n' + json.dumps(app, indent=2) + '\n' if app else
                   '\nApplication restart not attempted: disabled or no incident-time tracking.\n')
        subject = subject.replace('Storage', LABEL, 1)
        if i.get('return_deadline'):
            detail += '\nDrive return deadline: ' + json.dumps(i['return_deadline']) + '\n'
        event = None
        # A later failed attempt must not duplicate this incident's timeout
        # alert. A later verified recovery may send its normal success outcome.
        if (SETTINGS.get('notifications', {}).get('enabled', False) and
                (timed_out or result['main'] or not i.get('return_deadline', {}).get('reported_at'))):
            event = make_event('outcome', detail, subject)
            state['pending'].append(event)
        if timed_out:
            i['return_deadline'].update(reported_at=timestamp(), outcome=subject,
                                       event_id=event['id'] if event else None,
                                       notification='queued' if event else 'disabled')
            if i['phase'] in ('wait1', 'wait2'): i['phase'] = 'return_failed'
            log(subject + '; timeout recorded for incident ' + i['id'])
            return True
        i.update(notified=True, phase='done', outcome=subject, completed_at=timestamp())
        log(subject + '; final outcome recorded for incident ' + i['id'])
        return True

    def ready(self, now):
        if not self.state['pending']:
            return False
        retry = self.state['pending'][0].get('retry_at', 0)
        if retry > now + RETRY_DELAY + SEND_TIMEOUT:
            s = copy.deepcopy(self.state)
            s['pending'][0]['retry_at'] = now + RETRY_DELAY
            self.commit(s)
            return False
        return now >= retry

    def begin_attempt(self, now):
        s = copy.deepcopy(self.state)
        event = s['pending'][0]
        event['attempts'] = event.get('attempts', 0) + 1
        event['retry_at'] = now + SEND_TIMEOUT + RETRY_DELAY
        self.commit(s)
        return dict(event)

    def finish_attempt(self, event_id, accepted, now):
        s = copy.deepcopy(self.state)
        if s['pending'][0]['id'] != event_id:
            raise ValueError('Delivery result does not match queue head')
        if accepted:
            s['pending'].pop(0)
        else:
            s['pending'][0]['retry_at'] = now + RETRY_DELAY
        deadline = (s.get('incident') or {}).get('return_deadline') or {}
        if deadline.get('event_id') == event_id:
            deadline['notification'] = 'sent' if accepted else 'retry'
        self.commit(s)
        log(('SMTP accepted' if accepted else 'Delivery failed; retained for retry') + f' event {event_id}.')


class Worker:
    """Polling deadline; never wait indefinitely for an uninterruptible child."""
    def __init__(self, argv, payload, timeout, directory=STATE_DIR, lock_fd=None, lock_fds=()):
        self.deadline = time.monotonic() + timeout
        self.timed_out = False
        self.output = tempfile.TemporaryFile(dir=directory)
        with tempfile.TemporaryFile(dir=directory) as message:
            message.write(json.dumps(payload).encode())
            message.seek(0)
            self.proc = subprocess.Popen(argv, stdin=message, stdout=self.output,
                                         stderr=subprocess.DEVNULL, cwd='/', close_fds=True,
                                         start_new_session=True, env=settings.worker_environment(),
                                         pass_fds=tuple(lock_fds) + (() if lock_fd is None else (lock_fd,)))

    def cancel(self):
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def poll(self):
        code = self.proc.poll()
        if code is not None:
            return code == 0 and not self.timed_out
        if time.monotonic() >= self.deadline:
            self.timed_out = True
            self.cancel()
            return False
        return None

    def close(self):
        self.output.close()


class Delivery(Worker):
    def __init__(self, payload, command=None, timeout=SEND_TIMEOUT, input_dir=STATE_DIR):
        self.event_id = payload['id']
        super().__init__(command or ['/usr/bin/python3', '-I', NOTIFY, '_worker'],
                         payload, timeout, input_dir)


def failed_result(reason):
    current = snapshot()
    return {'main': False, 'dependent': current['dependent'], 'actions': [],
            'blocked': ['main', 'dependent'], 'reason': reason,
            'dependent_reason': current['dependent_detail'], 'detected': current['detected'],
            'mounts': current['mounts'], 'connection': current.get('connection')}


def worker_json(worker):
    worker.output.seek(0)
    data = worker.output.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError('Worker result too large')
    return json.loads(data)


def monitor_loop(stop, lock_fd):
    monitor = Monitor(application_tracking=bool(SETTINGS['docker']['enabled'] or SETTINGS['services']['units']))
    idle = standby.Idle()
    sleep_worker = None
    uptime = clock_now()
    log(f'Started {VERSION}: {INTERVAL}s samples, {OBSERVATIONS} observations, {RECOVERY_DELAY}s waits, {MAX_ATTEMPTS} attempts; USB qualification={usb.HOST_VERIFIED}')
    if stop.wait(max(0, BOOT_GRACE - uptime)):
        return
    next_sample, latest = 0.0, 'No observation yet.'
    delivery = recovery = request = None
    app_capture = capture_request = app_worker = stop_worker = None
    next_capture = 0.0
    usb_cleanup = None
    next_usb_cleanup = 0.0
    receipt = STATE_DIR / 'recovery-receipt.json'
    retired = []
    config_bad = False
    try:
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_sample:
                if recovery is None and app_worker is None and stop_worker is None and not retired:
                    try:
                        refresh_docker_settings()
                        monitor.application_tracking = bool(SETTINGS['docker']['enabled'] or SETTINGS['services']['units'])
                    except (OSError, ValueError, Unsafe):
                        pass  # Existing configuration guard reports/blocks storage changes below.
                current = snapshot()
                if stop.is_set():
                    break
                monitor.sample(current)
                i = monitor.state['incident']
                if i and i['phase'] == 'applications' and not current['healthy']:
                    if app_worker:
                        app_worker.cancel()
                        retired.append(app_worker)
                        app_worker = None
                    monitor.app_result(apps.interrupted(usb_context(), i['id'], i['applications'],
                        'Storage became unavailable during applications; further actions stopped. An accepted Docker request may still finish.'))
                latest = timestamp() + ': ' + current['detail']
                next_sample = now + INTERVAL
                deadline = (monitor.state.get('incident') or {}).get('return_deadline') or {}
                if (current.get('detected') is False and deadline.get('remaining', 0) > 0
                        and not deadline.get('reported_at') and i.get('phase') not in ('done', 'legacy')):
                    # Even a long configured polling interval must inspect the
                    # actual device at the earlier no-return deadline.
                    next_sample = min(next_sample, time.monotonic() + deadline['remaining'])
            # Retain killed-but-not-exited children; do not launch overlapping
            # work. An inherited monitor lock also protects across restarts.
            alive = []
            for worker in retired:
                if worker.proc.poll() is None:
                    alive.append(worker)
                else:
                    worker.close()
            retired = alive
            if stop_worker is not None:
                done = stop_worker.poll()
                if done is not None:
                    stopped = dict(complete=True, all_stopped=False, containers={},
                                   error='Container stop worker failed or timed out; no storage recovery was started.')
                    try:
                        if done:
                            stopped = worker_json(stop_worker)
                    except (OSError, ValueError):
                        pass
                    monitor.stop_result(stopped)
                    retired.append(stop_worker)
                    stop_worker = None
            if app_capture is not None:
                done = app_capture.poll()
                if done is not None:
                    captured = {'boot': monitor.boot, 'at': clock_now(), 'time': timestamp(),
                                'containers': {}, 'error': 'Docker inspection failed or timed out.'}
                    try:
                        if done:
                            captured = worker_json(app_capture)
                    except (OSError, ValueError):
                        pass
                    monitor.capture_result(capture_request, captured)
                    retired.append(app_capture)
                    app_capture = capture_request = None
            if app_worker is not None:
                done = app_worker.poll()
                if done is not None:
                    i = monitor.state['incident']
                    try:
                        if not done:
                            raise ValueError('Worker interrupted')
                        app_result = worker_json(app_worker)
                    except (OSError, ValueError):
                        app_result = apps.interrupted(usb_context(), i['id'], i['applications'],
                            'Application worker failed/timed out; reserved actions are not repeated.')
                        # An application/API failure alone must not say storage failed.
                        app_result['interrupted'] = not snapshot()['healthy']
                    monitor.app_result(app_result)
                    retired.append(app_worker)
                    app_worker = None
            if usb_cleanup is not None:
                done = usb_cleanup.poll()
                if done is not None:
                    if not done:
                        log('USB enable-only cleanup failed; pending obligation retained for retry in 15s.')
                    next_usb_cleanup = time.monotonic() + INTERVAL
                    retired.append(usb_cleanup)
                    usb_cleanup = None
            if recovery is not None:
                done = recovery.poll()
                if done is not None:
                    result = failed_result('Recovery worker failed or timed out; actions uncertain; no further mounts for this incident.')
                    try:
                        record = json.loads(receipt.read_text())
                        if record['incident'] == request['incident'] and record.get('number') == request['number']:
                            if done and record.get('complete'):
                                result = record['result']
                            else:
                                result['actions'] = record['result'].get('actions', [])
                    except (OSError, ValueError, KeyError):
                        pass
                    monitor.work_result(request, result)
                    retired.append(recovery)
                    recovery = request = None
            if delivery is not None:
                done = delivery.poll()
                if done is not None:
                    monitor.finish_attempt(delivery.event_id, done, time.time())
                    retired.append(delivery)
                    delivery = None
            if sleep_worker is not None and sleep_worker.poll() is not None:
                retired.append(sleep_worker)
                sleep_worker = None
            if (not stop.is_set() and recovery is None and usb_cleanup is None and app_worker is None and stop_worker is None
                    and sleep_worker is None and now >= next_usb_cleanup and not retired):
                usb_record = usb.load(usb_context())
                if usb_record and usb_record['phase'] != 'enabled':
                    try:
                        usb_cleanup = Worker(['/usr/bin/python3', '-I', str(SCRIPT), '_usb-cleanup'],
                                             {}, 8, lock_fd=lock_fd)
                    except OSError:
                        next_usb_cleanup = now + INTERVAL
                        log('Could not launch USB enable cleanup; obligation retained for retry in 15s.')
            if not stop.is_set() and recovery is None and usb_cleanup is None and app_worker is None and stop_worker is None and sleep_worker is None and not retired:
                stop_request = monitor.stop_request()
                if stop_request is not None:
                    stop_request['lock_fd'] = lock_fd
                    try:
                        stop_worker = Worker(['/usr/bin/python3', '-I', str(SCRIPT), '_apps-stop'],
                                             stop_request, apps.WORK_TIMEOUT, lock_fd=lock_fd)
                    except OSError:
                        monitor.stop_result(dict(complete=True, all_stopped=False, containers={},
                                                 error='Container stop worker could not start.'))
            if not stop.is_set() and recovery is None and usb_cleanup is None and app_worker is None and stop_worker is None and sleep_worker is None and not retired:
                try:
                    refresh_docker_settings()
                    monitor.application_tracking = bool(SETTINGS['docker']['enabled'] or SETTINGS['services']['units'])
                    config = config_load()
                    enabled = config['automatic_recovery']
                    usb_enabled = config.get('usb_reset_enabled', False)
                    config_bad = False
                except (OSError, ValueError, Unsafe):
                    enabled = usb_enabled = False
                    if not config_bad:
                        log('Recovery configuration invalid/unreadable: actions disabled, notifications continue.')
                    config_bad = True
                request = monitor.work_request(enabled, usb_enabled=usb_enabled)
                if request is not None:
                    request['lock_fd'] = lock_fd
                    write_receipt(receipt, {'incident': request['incident'], 'number': request['number'], 'complete': False,
                                            'result': {'actions': []}})
                    try:
                        recovery = Worker(['/usr/bin/python3', '-I', str(SCRIPT), '_recover'],
                                          request, ACTION_TIMEOUT, lock_fd=lock_fd)
                    except OSError:
                        monitor.work_result(request, failed_result('Could not start recovery worker.'))
                        request = None
                if recovery is None:
                    app_request = monitor.app_request()
                    if app_request is not None:
                        app_request['lock_fd'] = lock_fd
                        try:
                            app_worker = Worker(['/usr/bin/python3', '-I', str(SCRIPT), '_apps-recover'],
                                                app_request, apps.WORK_TIMEOUT, lock_fd=lock_fd)
                        except OSError:
                            i = monitor.state['incident']
                            monitor.app_result(apps.no_actions(i['applications'], 'Application worker could not start; no retry.'))
            if (not stop.is_set() and recovery is None and app_worker is None and stop_worker is None and usb_cleanup is None
                    and sleep_worker is None and not retired and monitor.state['status'] == 'up'
                    and idle.due(usb_context())):
                sleep_worker = Worker(['/usr/bin/python3', '-I', str(SCRIPT), '_standby'], {}, 45, lock_fd=lock_fd)
            # Snapshot inspection can overlap the bounded stop stage; it never
            # authorizes starts or substitutes a late state for the outage.
            i = monitor.state['incident']
            capture_due = i and i.get('applications', {}).get('capture_phase') == 'pending'
            if not stop.is_set() and app_capture is None and (capture_due or now >= next_capture):
                capture_request = monitor.capture_request()
                next_capture = now + INTERVAL
                if capture_request is not None:
                    try:
                        app_capture = Worker(['/usr/bin/python3', '-I', str(SCRIPT), '_apps-capture'],
                                             {}, apps.CAPTURE_TIMEOUT, lock_fd=lock_fd)
                    except OSError:
                        monitor.capture_result(capture_request, {'containers': {}, 'error': 'Inspection worker could not start.'})
                        capture_request = None
            if (not stop.is_set() and delivery is None
                    and not any(isinstance(worker, Delivery) for worker in retired)
                    and SETTINGS['notifications']['enabled'] and monitor.ready(time.time())):
                event = monitor.begin_attempt(time.time())
                try:
                    delivery = Delivery(event_payload(event, latest))
                except OSError:
                    monitor.finish_attempt(event['id'], False, time.time())
            stop.wait(max(0, min(0.5, next_sample - time.monotonic())))
    finally:
        for worker in (app_capture, app_worker, stop_worker, sleep_worker):
            if worker:
                worker.cancel()
                retired.append(worker)
        if usb_cleanup:
            usb_cleanup.cancel()
            retired.append(usb_cleanup)
        if recovery:
            recovery.cancel()  # Saved running intent is consumed on the next start.
            retired.append(recovery)
        if delivery:
            end = time.monotonic() + SEND_TIMEOUT
            result = delivery.poll()
            while result is None and time.monotonic() < end:
                time.sleep(0.1)
                result = delivery.poll()
            if result is None:
                delivery.cancel()
                result = False
            monitor.finish_attempt(delivery.event_id, result, time.time())
            retired.append(delivery)
        for worker in retired:
            worker.cancel()
            worker.close()
        log('Stopped; durable recovery progress and email FIFO retained.')


def assert_internal_state():
    if STATE_DIR.exists():
        info = STATE_DIR.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise Unsafe('State directory must be root-owned mode 0700.')
    rows = read_rows()
    root = visible_mount(rows, '/')
    target = visible_mount(rows, str(STATE_DIR))
    if (root is None or target is None or root['dev'] != target['dev']
            or 'rw' not in target['vfs'] or 'rw' not in target['super']
            or STATE_DIR.is_symlink() or str(STATE_DIR.resolve()).startswith(MOUNT + '/')):
        raise Unsafe('State must be on the internal writable root filesystem.')


def run_monitor():
    assert_internal_state()
    STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    with (STATE_DIR / 'monitor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monitor_loop(stop, lock.fileno())


def execute_recovery(request):
    require_configuration(request)
    global WORKER_LOCK_FDS
    monitor_fd = request['lock_fd']
    fcntl.fcntl(monitor_fd, fcntl.F_GETFD)
    # A separate lock also blocks this same monitor from overlapping a surviving
    # nested mount command after its Python supervisor was killed on timeout.
    with (STATE_DIR / 'recovery.lock').open('a') as operation_lock:
        fcntl.flock(operation_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        WORKER_LOCK_FDS = (monitor_fd, operation_lock.fileno())
        try:
            receipt = STATE_DIR / 'recovery-receipt.json'
            if usb.ensure_enabled(usb_context()):
                result = recovery_work(request, receipt)
            else:
                result = failed_result('USB re-enable remains unverified; no recovery operation allowed.')
            result['connection'] = snapshot().get('connection')
            write_receipt(receipt, {'incident': request['incident'], 'number': request['number'],
                                    'result': result, 'complete': True})
        finally:
            WORKER_LOCK_FDS = ()


def execute_applications(request):
    global WORKER_LOCK_FDS
    require_configuration(request)
    assert_internal_state()
    fcntl.fcntl(request['lock_fd'], fcntl.F_GETFD)
    with (STATE_DIR / 'recovery.lock').open('a') as operation_lock:
        fcntl.flock(operation_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        WORKER_LOCK_FDS = (request['lock_fd'], operation_lock.fileno())
        try:
            if not usb.ensure_enabled(usb_context()):
                raise Unsafe('Pending USB enable prevents application actions.')
            result = apps.recover(usb_context(), request) if SETTINGS['docker']['enabled'] else {'complete': True, 'interrupted': False, 'all_verified': True, 'containers': {}}
            result['services'] = apps.recover_services(usb_context(), request)
            result['all_verified'] &= all(v['status'] == 'verified' for v in result['services'].values())
            print(json.dumps(result))
        finally:
            WORKER_LOCK_FDS = ()


def execute_stops(request):
    """Stop selected containers before touching failed storage."""
    global WORKER_LOCK_FDS
    require_configuration(request)
    assert_internal_state()
    fcntl.fcntl(request['lock_fd'], fcntl.F_GETFD)
    with (STATE_DIR / 'recovery.lock').open('a') as operation_lock:
        fcntl.flock(operation_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        WORKER_LOCK_FDS = (request['lock_fd'], operation_lock.fileno())
        try:
            result = apps.stop_selected(usb_context(), request) if SETTINGS['docker']['enabled'] else dict(
                complete=True, all_stopped=True, containers={})
            print(json.dumps(result))
        finally:
            WORKER_LOCK_FDS = ()


def main():
    global WORKER_LOCK_FDS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'status', 'test', 'run', '_recover', '_verify', '_verify-usb', '_usb-io', '_usb-guard', '_usb-cleanup', '_apps-capture', '_apps-stop', '_apps-recover', '_verify-apps', '_manual', '_standby'))
    args = parser.parse_args()
    os.chdir('/')
    io_request = json.loads(sys.stdin.read(65536)) if args.command == '_usb-io' else None
    cleanup = args.command in ('_usb-cleanup', '_usb-guard') or (io_request and io_request.get('action') == 'enable')
    if not cleanup:
        try:
            configure(runtime_configuration())
        except FileNotFoundError:
            if args.command == 'run' and not CONFIG.exists():
                log('No configuration: run setup before starting monitoring. Pending USB cleanup remains independent.')
                return 0
            raise
    if args.command == 'check':
        current = snapshot()
        print(json.dumps(current, indent=2))
        return 0 if current['healthy'] and current['dependent'] else 2
    if os.geteuid() != 0:
        parser.error('Use sudo for status, test, or run.')
    os.umask(0o077)
    if args.command == '_manual':
        request = json.loads(sys.stdin.read(65536))
        require_configuration(request)
        WORKER_LOCK_FDS = tuple(request.get('manual_lock_fds', ()))
        for fd in WORKER_LOCK_FDS: fcntl.fcntl(fd, fcntl.F_GETFD)
        try:
            message = controls.perform(sys.modules[__name__], request['action'])
            print(json.dumps({'ok': True, 'result': 'success', 'message': message, 'health': snapshot()}))
        except (OSError, ValueError, Unsafe, subprocess.SubprocessError) as exc:
            message = ('The selected drive or required device information is unavailable.' if isinstance(exc, FileNotFoundError) else str(exc))
            print(json.dumps({'ok': False, 'result': standby.error_result(exc), 'message': message,
                              'storage_unchanged': getattr(exc, 'storage_unchanged', False), 'health': snapshot()}))
    elif args.command == '_standby':
        with (STATE_DIR / 'recovery.lock').open('a') as operation:
            fcntl.flock(operation, fcntl.LOCK_EX | fcntl.LOCK_NB)
            WORKER_LOCK_FDS = (operation.fileno(),)
            try:
                print(standby.sleep(usb_context()))
            except (OSError, ValueError, Unsafe, subprocess.SubprocessError) as exc:
                standby.save(usb_context(), standby.identity(usb_context()), str(exc), suppressed='bridge' in str(exc))
    elif args.command == '_apps-capture':
        print(json.dumps(apps.capture(usb_context()) if SETTINGS['docker']['enabled'] else
                         dict(boot=boot_id(), at=clock_now(), time=timestamp(), containers={})))
    elif args.command == '_apps-recover':
        execute_applications(json.loads(sys.stdin.read(65536)))
    elif args.command == '_apps-stop':
        execute_stops(json.loads(sys.stdin.read(65536)))
    elif args.command == '_verify-apps':
        try:
            print(json.dumps(apps.preflight(usb_context())))
        except apps.AppError as exc:
            print(json.dumps({'error': str(exc)}))
            return 1
    elif args.command == '_usb-io':
        request = io_request
        try:
            usb.io_worker(usb_context(), request)
        except (OSError, ValueError, Unsafe) as error:
            try:
                record = usb.load(usb_context())
                if record and record['incident'] == request['incident']:
                    reason = str(error) or type(error).__name__
                    usb.update(usb_context(), io_error=request['action'] + ': ' + reason,
                               io_error_at=timestamp())
            except (OSError, ValueError, Unsafe):
                pass
            raise
    elif args.command == '_usb-guard':
        usb.guard_worker(usb_context(), json.loads(sys.stdin.read(65536)))
    elif args.command == '_usb-cleanup':
        assert_internal_state()
        return 0 if usb.ensure_enabled(usb_context()) else 1
    elif args.command == '_recover':
        request = json.loads(sys.stdin.read(65536))
        execute_recovery(request)
    elif args.command == '_verify':
        verify_main()
        verify_dependent()
        print('Both expected ext4 filesystems verified read/write.')
    elif args.command == '_verify-usb':
        dev = verify_main()
        print(json.dumps(usb.healthy_binding(usb_context(), dev), sort_keys=True))
    elif args.command == 'test':
        return subprocess.call(['/usr/bin/python3', '-I', NOTIFY, 'test'], timeout=25)
    elif args.command == 'status':
        state = load_state()
        application_ledger, application_warning = None, None
        try:
            application_ledger = apps.read_ledger(usb_context(), (state.get('incident') or {}).get('id'))
        except apps.AppError as error:
            # Read-only diagnostics must remain available when a historical
            # selection differs. Recovery keeps the same strict ledger guard.
            application_warning = str(error)
        print(json.dumps({'version': VERSION, 'monitor_interval': INTERVAL,
                          'recovery_delay': RECOVERY_DELAY, 'max_attempts': MAX_ATTEMPTS,
                          'max_usb_resets': MAX_USB_RESETS, 'usb_reset_enabled': config_load()['usb_reset_enabled'],
                          'usb_host_verified': usb.HOST_VERIFIED, 'usb_enumeration_seconds': usb.ENUM_SECONDS,
                          'usb_ledger': usb.load(usb_context()),
                          'usb_reason': USB_REASON, 'config': config_load(),
                          'application_recovery_enabled': apps.enabled(),
                          'application_ledger': application_ledger,
                          'application_ledger_warning': application_warning,
                          'state': state}, indent=2))
    else:
        run_monitor()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        log(f'Monitor error ({type(error).__name__}); saved state retained.')
        raise SystemExit(1)
