# SPDX-License-Identifier: MIT
"""Manual controls share the engine guards and exclusive operation locks."""
from contextlib import contextmanager
import fcntl
from pathlib import Path
import uuid


def request(w):
    known = w.load_state(w.STATE_DIR / 'state.json').get('last_healthy', {})
    known_storage = known.get('main_mount_proof')
    try:
        dev = w.device_number('/dev/disk/by-uuid/' + w.DISK_UUID)
        binding = w.usb.bind_current(w.usb_context(), dev)
        known = dict(usb_binding=binding, usb_sources=binding['sources'], mounts=[dict(dev=dev)])
    except (OSError, ValueError, w.Unsafe):
        pass  # An absent disk may use the previously verified same-boot binding.
    return dict(incident=str(uuid.uuid4()), number=1, allow_mount=True, allow_usb=True,
                usb_resets=0, blocked=[], check_only=False, manual=True, allow_present=True,
                config_digest=w.CONFIG_DIGEST, known_binding=known.get('usb_binding'),
                known_sources=known.get('usb_sources', []),
                known_devs=[r['dev'] for r in known.get('mounts', []) if 'dev' in r],
                known_storage=known_storage)


def unmount(w):
    rows = w.read_rows()
    selected = [r for r in rows if r['target'] == w.MOUNT]
    if not selected:
        return 'Already unmounted. Files underneath the mountpoint were left untouched.'
    dev = w.device_number('/dev/disk/by-uuid/' + w.DISK_UUID)
    w.mounted_checks(rows, w.MOUNT, dev, w.DISK_UUID)
    binding = w.standby.identity(w)
    w.standby.users(w, binding)
    nested = [r for r in rows if r['target'] != w.MOUNT and w.covers(w.MOUNT, r['target'])]
    if nested:
        configured = w.settings.storage_images(w.SETTINGS, enabled=False)
        expected = {item['mountpoint'] for item in configured}
        if any(row['target'] not in expected for row in nested):
            raise w.Unsafe('Unconfigured dependent mounts are active; safe unmount refused.')
        for row in sorted(nested, key=lambda r:len(r['target']), reverse=True):
            w.verify_dependent(next(item for item in configured if item['mountpoint'] == row['target']))
            w.command(['/usr/bin/umount', '--', row['target']], timeout=15)
    w.command(['/usr/bin/sync', '-f', '--', w.MOUNT], timeout=15)
    w.mounted_checks(w.read_rows(), w.MOUNT, dev, w.DISK_UUID)
    w.command(['/usr/bin/umount', '--', w.MOUNT], timeout=15)
    w.mount_available(w.read_rows(), w.MOUNT, dev)
    return 'Filesystem safely unmounted. Monitoring is stopped until you start it again.'


def sleep_now(w):
    # Observation keeps running. Only storage-changing work must be exclusive,
    # just as for the monitor's automatic standby worker.
    with (w.STATE_DIR / 'recovery.lock').open('a') as operation:
        try:
            fcntl.flock(operation, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise w.standby.refusal(w, 'busy', 'Another storage operation is running; try Sleep again after it finishes.') from None
        previous = w.WORKER_LOCK_FDS
        w.WORKER_LOCK_FDS = (*previous, operation.fileno())
        try:
            pending = w.usb.load(w.usb_context())
            if pending and pending['phase'] != 'enabled':
                raise w.standby.refusal(w, 'busy', 'USB reconnection cleanup must finish before HDD standby.')
            return w.standby.sleep(w, manual=True)
        finally:
            w.WORKER_LOCK_FDS = previous


@contextmanager
def operation_ownership(w):
    with (w.STATE_DIR / 'monitor.lock').open('a') as monitor, (w.STATE_DIR / 'recovery.lock').open('a') as operation:
        fcntl.flock(monitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(operation, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = getattr(w, 'WORKER_LOCK_FDS', ())
        w.WORKER_LOCK_FDS = (*previous, monitor.fileno(), operation.fileno())
        try:
            yield
        finally:
            # A preflight refusal also exits here. Status reporting must never
            # inherit descriptor numbers whose lock files have been closed.
            w.WORKER_LOCK_FDS = previous


def perform(w, action):
    if action not in ('mount', 'unmount', 'reconnect', 'sleep'):
        raise w.Unsafe('Unknown disk operation.')
    w.assert_internal_state()
    if action == 'sleep':
        return sleep_now(w)
    if action == 'reconnect':
        # Monitoring is never stopped by a manual reset, including a refusal.
        w.manual_usb.unmounted(w)
        with (w.STATE_DIR / 'recovery.lock').open('a') as operation:
            fcntl.flock(operation, fcntl.LOCK_EX | fcntl.LOCK_NB)
            previous = w.WORKER_LOCK_FDS
            w.WORKER_LOCK_FDS = (operation.fileno(),)
            try:
                return w.manual_usb.reset(w)
            finally:
                w.WORKER_LOCK_FDS = previous
    with operation_ownership(w):
        if not w.usb.ensure_enabled(w.usb_context()):
            raise w.Unsafe('Pending USB enable must complete first.')
        if action == 'unmount':
            return unmount(w)
        if action == 'mount' and not (Path('/dev/disk/by-uuid') / w.DISK_UUID).exists():
            raise w.Unsafe('The selected drive is not connected. Reconnect it, then try Mount.')
        r = request(w)
        w.MANUAL_MOUNT = True
        try:
            # A Mount click only mounts. Reconnect has already spent its USB budget.
            r.update(allow_usb=False, usb_resets=0)
            result = w.recovery_work(r, w.STATE_DIR / 'manual-receipt.json')
            if not result['main'] or not result['dependent']:
                raise w.Unsafe(result['reason'] + ' ' + result['dependent_reason'])
            return 'Expected filesystem and configured dependent mounts verified read/write.'
        finally:
            w.MANUAL_MOUNT = False
