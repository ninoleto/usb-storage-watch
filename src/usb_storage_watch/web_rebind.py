# SPDX-License-Identifier: MIT
"""Explicit, hardware-verified reassociation after external reformatting.

This never formats, mounts, reconnects, or restarts storage. Destructive
filesystem changes cannot be undone by merely adopting their new UUID.
"""
import copy
import contextlib
import fcntl
import json
import os
from pathlib import Path
import secrets
import subprocess
import stat

DEFAULT_OPTIONS = 'defaults,nofail,nodev,nosuid,x-systemd.device-timeout=10s'


def hardware_match(old, new):
    """An authoritative hardware pin and every recorded stable attribute must match."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return False
    if not (old.get('serial') or old.get('wwn')):
        return False
    for key in ('serial', 'wwn', 'vendor', 'product', 'size'):
        recorded = old.get(key)
        if recorded not in ('', None) and (new.get(key) != recorded or type(new.get(key)) != type(recorded)):
            return False
    return bool((old.get('serial') and new.get('serial') == old['serial']) or
                (old.get('wwn') and new.get('wwn') == old['wwn']))


def fstab_plan(b, old_uuid, new_uuid, old_mount, new_row):
    original = b.FSTAB.read_text()
    lines = original.splitlines(keepends=True)
    old_indexes, new_indexes = [], []
    for i, line in enumerate(lines):
        fields = line.split('#', 1)[0].split()
        if fields and fields[0] == 'UUID=' + old_uuid:
            old_indexes.append(i)
        if fields and fields[0] == 'UUID=' + new_uuid:
            new_indexes.append(i)
    if len(old_indexes) > 1 or len(new_indexes) > 1:
        raise ValueError('Conflicting persistent mount entries require administrator review.')
    if old_indexes:
        fields = lines[old_indexes[0]].split()
        if len(fields) != 6 or fields[1] != old_mount or fields[2] != 'ext4':
            raise ValueError('The previous mount entry was modified; do not change this configuration.')
    if new_indexes:
        fields = lines[new_indexes[0]].split()
        if len(fields) != 6 or fields[2] != 'ext4':
            raise ValueError('The newly formatted filesystem has an unsupported mount entry.')
        new_mount, options = fields[1], fields[3]
        b.s.absolute(new_mount, 'Mount location')
        b.s.options(options)
    else:
        new_mount = '/mnt/usb-storage-watch-' + new_uuid
        options = DEFAULT_OPTIONS
    if not new_mount.startswith('/mnt/') or new_mount == old_mount:
        raise ValueError('The new filesystem needs a distinct safe mount location under /mnt.')
    for i, line in enumerate(lines):
        if i in (*old_indexes, *new_indexes):
            continue
        fields = line.split('#', 1)[0].split()
        if len(fields) >= 2 and b.w.unescape_mount(fields[1]) == new_mount:
            raise ValueError('The new mount location is already assigned to another filesystem.')
    if any(row['target'] == old_mount for row in b.w.read_rows()):
        raise ValueError('The previous mount location is still active. Safely unmount it before reconnecting the configuration.')
    path = b.cli.root_path('/', new_mount)
    current_mount = new_row.get('mountpoint')
    if current_mount:
        if current_mount != new_mount:
            raise ValueError('The reformatted drive is mounted at another location. Safely unmount it before reconnecting its configuration.')
        # The previous drive's hardware pin still names the old filesystem.
        # Do NOT use mounted_checks(), which deliberately rejects that pin.
        # Verify the actual new mount directly; inspect() independently checks
        # the full new USB hardware identity against the old authoritative pin.
        dev = b.w.device_number('/dev/disk/by-uuid/' + new_uuid)
        rows = b.w.read_rows()
        matches = [r for r in rows if r['target'] == new_mount]
        visible = b.w.visible_mount(rows, new_mount)
        if len(matches) != 1 or visible != matches[0]:
            raise ValueError('The newly formatted drive mount is ambiguous. Safely unmount it before re-identification.')
        mount = matches[0]
        if (mount['dev'] != dev or mount['root'] != '/' or mount['fs'] != 'ext4'
                or any('ro' in opts or 'rw' not in opts for opts in (mount['vfs'], mount['super']))):
            raise ValueError('The new filesystem is not mounted read/write with the verified identity.')
    elif path.exists() and (not path.is_dir() or path.is_symlink() or any(path.iterdir())):
        raise ValueError('New mount location contains existing data; nothing will be changed.')
    replacement = ''.join(line for i, line in enumerate(lines) if i not in old_indexes)
    if not new_indexes:
        replacement += ('\n' if replacement and not replacement.endswith('\n') else '')
        replacement += f'UUID={new_uuid} {new_mount} ext4 {options} 0 0\n'
    return dict(before=original, after=replacement, mountpoint=new_mount, options=options,
                old_entry=bool(old_indexes), new_entry=bool(new_indexes))


def inspect(fleet, identifier, uuid):
    """Read-only review. No trust in the browser's asserted physical identity."""
    child, instance = fleet.get(identifier)
    b = fleet.context()
    config = child.configuration()
    old_uuid = config['disk']['uuid']
    if old_uuid == uuid or not old_uuid:
        raise ValueError('This drive does not require filesystem re-identification.')
    if (config['dependent']['enabled'] or child.s.storage_images(config, False)
            or config['docker']['containers'] or config['services']['units']):
        raise ValueError('This drive has dependent storage or applications. Their paths must be reviewed before re-identification.')
    progress = child.s.STATE_DIR / 'prepare-drive.json'
    phase = json.loads(progress.read_text()).get('phase') if progress.exists() else 'idle'
    if (child.migration.pending(child.migration_context()) or
            phase in ('preparing', 'formatting', 'mounting', 'verifying')):
        raise ValueError('Finish pending drive operations before reconnecting this configuration.')
    for profile, other, error in fleet.records():
        if error:raise ValueError(error)
        if profile != identifier and other['disk']['uuid'] == uuid:
            raise ValueError('This new filesystem already belongs to another configured drive.')
    if os.path.exists('/dev/disk/by-uuid/' + old_uuid):
        raise ValueError('The original filesystem is still detected. Do not replace an active configuration.')
    row = b.target(uuid)
    if row['transport'] != 'usb' or row.get('filesystem', 'ext4') != 'ext4':
        raise ValueError('Only a verified ext4 filesystem on a USB disk can be re-associated.')
    pin_path = child.s.STATE_DIR / 'drive-identity.json'
    if not pin_path.is_file() or pin_path.is_symlink():
        raise ValueError('The old drive has no verified hardware identity. Automatic matching is unavailable.')
    saved_pin = json.loads(pin_path.read_text())
    if saved_pin.get('uuid') != old_uuid:
        raise ValueError('Previous hardware identity and drive configuration do not agree.')
    dev = child.w.device_number('/dev/disk/by-uuid/' + uuid)
    actual = child.w.drives.hardware(child.w.usb_context(), dev, uuid)
    if not hardware_match(saved_pin, actual):
        raise ValueError('The connected device does not match the previous hardware identity.')
    # Detect ambiguous USB bridges that expose a duplicated serial/WWN.
    matches = 0
    for other in b.disks():
        if other.get('transport') != 'usb' or not other.get('uuid'):
            continue
        try:
            otherdev = child.w.device_number('/dev/disk/by-uuid/' + other['uuid'])
            otherpin = child.w.drives.hardware(child.w.usb_context(), otherdev, other['uuid'])
        except (OSError, ValueError, child.w.Unsafe):
            continue
        if hardware_match(saved_pin, otherpin):
            matches += 1
    if matches != 1:
        raise ValueError('Hardware identity is ambiguous. No configuration was changed.')
    state_path = child.s.STATE_DIR / 'state.json'
    state_before = state_path.read_text() if state_path.exists() else None
    saved_state = json.loads(state_before) if state_before else {}
    if saved_state.get('target') not in (None, [old_uuid, config['disk']['mountpoint']]):
        raise ValueError('The previous recovery state belongs to a different drive.')
    if saved_state.get('pending'):
        raise ValueError('Pending email notifications must be delivered before changing the drive identity.')
    reset_path = child.s.STATE_DIR / 'usb-reset.json'
    reset_before = reset_path.read_text() if reset_path.exists() else None
    if reset_before and json.loads(reset_before).get('phase') != 'enabled':
        raise ValueError('USB port re-enable cleanup must finish before this configuration can change.')
    migration_path = child.s.STATE_DIR / 'mount-migration.json'
    migration_before = migration_path.read_text() if migration_path.exists() else None
    fst = fstab_plan(child, old_uuid, uuid, config['disk']['mountpoint'], row)
    updated = copy.deepcopy(config)
    updated['disk'].update(uuid=uuid, mountpoint=fst['mountpoint'], fstab_options=fst['options'])
    # Never carry USB port qualification across a filesystem replacement.
    updated['usb']['enabled'] = False
    updated['usb']['profile'] = None
    child.s.validate(updated)
    child.cli.drives.validate_shared(child.s, updated)
    blob = dict(config=child.s.CONFIG.read_text(),state=state_before,identity=pin_path.read_text(),
                usb_reset=reset_before,migration=migration_before,fstab=fst['before'])
    fingerprint = child.s.digest(dict(backup=blob,new_uuid=uuid,hardware=actual,mountpoint=fst['mountpoint']))
    return dict(profile_id=identifier,old_uuid=old_uuid,new_uuid=uuid,mountpoint=fst['mountpoint'],
                name=config['disk']['label'],revision=fingerprint,updated=updated,identity=actual,
                fstab=fst,backup=blob)


def public(review):
    return {k:review[k] for k in ('profile_id','old_uuid','new_uuid','mountpoint','name','revision')} | dict(
        message='This is the same verified USB hardware with a new ext4 filesystem. Update its existing configuration while preserving settings and history. Previously erased files cannot be recovered. USB port reconnect will need fresh qualification.')


def apply(fleet, identifier, uuid, revision):
    """Atomic intent and best-effort rollback; never changes actual filesystem bytes."""
    child, instance = fleet.get(identifier)
    with fleet.mutex, instance.request_lock, child.cli.drives.configuration_lock(child.s), contextlib.ExitStack() as locks:
        # The monitor can be stopped while a recovery, preparation or USB
        # cleanup worker still owns a separate lock. All must be idle.
        for name in ('monitor.lock', 'recovery.lock', 'preparation.lock', 'usb-io.lock', 'usb-ledger.lock'):
            lock_path = child.s.STATE_DIR / name
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            locks.callback(os.close, fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                raise ValueError('A drive operation lock is not safely owned. Repair requires administrator review.')
            try:fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another drive operation is still active. Stop it before reconnecting this configuration.') from None
            service = subprocess.run(['/usr/bin/systemctl','is-active','--quiet',child.s.SERVICE],timeout=8)
            if service.returncode not in (3,4):
                raise ValueError('Stop monitoring this drive before changing its filesystem identity.')
            review = inspect(fleet,identifier,uuid)
            if review['revision'] != revision:
                raise ValueError('Drive identity or configuration changed. Review the drive again.')
            backup = review['backup']
            record_id = secrets.token_hex(16)
            backup_path = child.s.STATE_DIR / 'rebind-backups' / record_id / 'backup.json'
            child.cli.save(backup_path,dict(version=1,old_uuid=review['old_uuid'],new_uuid=uuid,
                                            recorded_at=child.w.timestamp(),files=backup))
            pin_path=child.s.STATE_DIR/'drive-identity.json'
            state_path=child.s.STATE_DIR/'state.json'
            reset_path=child.s.STATE_DIR/'usb-reset.json'
            changed=[]
            def store(path,value,mode=0o600):
                child.w.atomic_write(path,value,mode=mode)
                changed.append(path)
            try:
                mount_path = child.cli.root_path('/',review['mountpoint'])
                if not mount_path.exists():
                    mount_path.mkdir(mode=0o755,parents=True)
                # Commit config and clean state before new fstab visibility.
                child.cli.save(child.s.CONFIG,review['updated']);changed.append(child.s.CONFIG)
                child.w.configure(review['updated'])
                store(state_path,json.dumps(child.w.fresh_state(),indent=2)+'\n')
                store(pin_path,json.dumps(review['identity'],indent=2)+'\n')
                if reset_path.exists():
                    reset_path.unlink();changed.append(reset_path)
                migration_path = child.s.STATE_DIR / 'mount-migration.json'
                if migration_path.exists() and json.loads(migration_path.read_text()).get('phase') in ('committed','rolled_back'):
                    migration_path.unlink()
                store(child.FSTAB,review['fstab']['after'],0o644)
                child.command(['/usr/bin/systemctl','daemon-reload'])
            except Exception as err:
                failed=[]
                for path,key,mode in ((child.FSTAB,'fstab',0o644),(child.s.CONFIG,'config',0o600),
                                      (state_path,'state',0o600),(pin_path,'identity',0o600),(reset_path,'usb_reset',0o600),
                                      (child.s.STATE_DIR/'mount-migration.json','migration',0o600)):
                    try:
                        if backup[key] is None:path.unlink(missing_ok=True)
                        else:child.w.atomic_write(path,backup[key],mode=mode)
                    except Exception:failed.append(str(path))
                try:child.command(['/usr/bin/systemctl','daemon-reload'])
                except Exception:failed.append('systemd reload')
                try:child.w.configure(json.loads(backup['config']))
                except Exception:failed.append('runtime configuration')
                if failed:
                    raise ValueError('Re-identification stopped. Automatic rollback was incomplete; manual review required. Private backup: '+str(backup_path)) from err
                raise ValueError('Re-identification failed and its previous settings were restored. No drive was formatted.') from err
            return dict(message='Drive configuration updated for its new filesystem. Previous history and settings are preserved; monitoring remains off until you start it.',
                        uuid=uuid, mountpoint=review['mountpoint'],backup=str(backup_path))
