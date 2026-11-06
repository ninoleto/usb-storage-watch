# SPDX-License-Identifier: MIT
"""Consent-bound location change of one UUID fstab entry. Never performs disk I/O.

The durable journal and immutable private backup precede mutations. Interrupted
transactions block GUI monitoring and can be resumed or rolled back. Runtime
state changes only its target path, retaining all budgets, events and history.
"""
from contextlib import contextmanager
import fcntl
import json
import re
import secrets


OPEN_PHASES = ('prepared', 'applied', 'committing', 'rolling_back')


def text(path):
    return path.read_text() if path.exists() else None


def journal(b):
    path = b.s.STATE_DIR / 'mount-migration.json'
    if not path.exists() and not path.is_symlink():
        return None
    path = b.cli.root_path('/', path)
    value = json.loads(path.read_text())
    if (value.get('version') != 1 or value.get('phase') not in (*OPEN_PHASES, 'committed', 'rolled_back')
            or not re.fullmatch('[0-9a-f]{32}', value.get('id', ''))):
        raise ValueError('Mount location change journal is invalid. Its protected backup is retained; no changes are allowed.')
    return value


def backup(b, record):
    path = b.cli.root_path('/', b.s.STATE_DIR / 'mount-migrations' / record['id'] / 'backup.json')
    return json.loads(path.read_text())


def store(b, record):
    b.cli.save(b.s.STATE_DIR / 'mount-migration.json', record)


def public(b):
    record = journal(b)
    if not record or record['phase'] == 'rolled_back':
        return None
    return {key: record[key] for key in ('id', 'uuid', 'old_mountpoint', 'mountpoint', 'phase')} | {
        'backup': str(b.s.STATE_DIR / 'mount-migrations' / record['id'] / 'backup.json')}


def pending(b):
    record = journal(b)
    return record if record and record['phase'] in OPEN_PHASES else None


@contextmanager
def exclusive(b):
    with b.cli.drives.configuration_lock(b.s):
        with drive_exclusive(b):yield


@contextmanager
def drive_exclusive(b):
    path = b.cli.root_path('/', b.s.STATE_DIR / 'monitor.lock')
    with path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise b.FieldError('setup-service', 0, 'A monitor or recovery worker is still running. Stop monitoring and wait for it to finish before changing the location.') from None
        b.cli.stopped()
        yield


def entry(b, content, uuid):
    lines = content.splitlines(keepends=True)
    found = [(i, line.split('#', 1)[0].split()) for i, line in enumerate(lines)
             if line.split('#', 1)[0].split() and line.split('#', 1)[0].split()[0] == 'UUID=' + uuid]
    if len(found) != 1 or len(found[0][1]) != 6 or found[0][1][2] != 'ext4':
        raise ValueError('Location change requires exactly one complete UUID-based ext4 entry. Existing entries were preserved.')
    i, fields = found[0]
    if fields[4] != '0' or fields[5] not in ('0', '1', '2'):
        raise ValueError('The existing dump/check fields require review; keep the existing entry until reviewed.')
    b.s.options(fields[3])
    return lines, i, fields


def state_for_path(b, original, uuid, old, new):
    if original is None:
        return None
    value = json.loads(original)
    if value.get('target') not in (None, [uuid, old], [uuid, new]):
        raise ValueError('Recovery state belongs to a different disk or mountpoint. Keep the existing entry; state was preserved.')
    incident = value.get('incident')
    if incident and incident.get('phase') not in ('done', 'legacy'):
        raise ValueError('An unfinished recovery incident must finish before location change. State and retry budgets were preserved.')
    value['target'] = [uuid, new]
    return json.dumps(value, indent=2) + '\n'


def plan(b, uuid, destination=None):
    if pending(b):
        raise ValueError('A location change is already pending. Continue it in Recovery or use Roll back location change.')
    row = b.target(uuid)
    c = b.configuration()
    if c['disk']['uuid'] and c['disk']['uuid'] != uuid:
        raise ValueError('This configuration belongs to another disk; no location change is allowed.')
    original = b.FSTAB.read_bytes().decode('utf-8')
    lines, index, fields = entry(b, original, uuid)
    old = b.w.unescape_mount(fields[1])
    if destination is None and not b.temporary_mount(old):
        raise ValueError('This UUID entry already uses a stable location. Keep the existing mountpoint; location change is unnecessary.')
    if c['disk']['uuid'] and c['disk']['mountpoint'] != old:
        raise ValueError('Saved configuration and existing entry disagree. Keep the existing configuration; no entry was changed.')
    if b.s.storage_images(c,False):
        raise ValueError('Saved virtual image paths use this location. Remove their registrations before changing the mountpoint; image files are kept.')
    # Validate the existing entry and all aliases/conflicts through the normal path.
    check = b.inspect_mount(uuid)
    if check['mountpoint'] != old:
        raise ValueError('Existing mountpoint changed. Refresh before reviewing location change.')
    new = destination or '/mnt/usb-storage-watch-' + uuid
    b.s.absolute(new, 'Mount location')
    if not new.startswith('/mnt/') or new == old:
        raise ValueError('Choose a different folder inside /mnt, for example /mnt/usb-storage.')
    for existing in b.fstab_entries():
        if b.w.unescape_mount(existing[1]) == new:
            raise ValueError('The proposed stable mountpoint already has a permanent entry. Keep the existing entry; no changes were made.')
    b.s.absolute(new, 'Mountpoint')
    path = b.cli.root_path('/', new)
    if path.exists() and (not path.is_dir() or next(path.iterdir(), None) is not None):
        raise ValueError('The proposed stable mountpoint contains an existing file or directory contents. Keep the existing entry; those contents are preserved.')
    if any(b.w.covers(new, mount['target']) for mount in b.w.read_rows()):
        raise ValueError('The proposed stable mountpoint is occupied. Keep the existing entry; no mount is moved.')
    changed = re.sub(r'^(\s*\S+[ \t]+)\S+', lambda match: match[1] + new, lines[index], count=1)
    replacement = list(lines); replacement[index] = changed
    state = text(b.s.STATE_DIR / 'state.json')
    state_for_path(b, state, uuid, old, new)
    return dict(uuid=uuid, old_mountpoint=old, mountpoint=new, current=row['mountpoint'],
                old_entry=lines[index].rstrip('\r\n'), entry=changed.rstrip('\r\n'),
                token=b.s.digest(dict(fstab=original, config=b.s.digest(c), state=state, current=row['mountpoint'], destination=new)),
                replacement=''.join(replacement))


def prepare(b, data):
    with exclusive(b):
        proposal = plan(b, data.get('uuid'), data.get('mountpoint'))
        if data.get('token') != proposal['token'] or data.get('revision') != b.s.digest(b.configuration()):
            raise ValueError('Location change proposal changed. Review the location change again before consenting.')
        if data.get('confirm') is not True:
            raise ValueError('Select the location change consent checkbox before moving the permanent entry.')
        record = dict(version=1, id=secrets.token_hex(16), phase='prepared',
                      uuid=proposal['uuid'], old_mountpoint=proposal['old_mountpoint'], mountpoint=proposal['mountpoint'])
        saved = dict(fstab=b.FSTAB.read_bytes().decode('utf-8'), fstab_after=proposal['replacement'],
                     config=text(b.s.CONFIG), state=text(b.s.STATE_DIR / 'state.json'))
        b.cli.save(b.s.STATE_DIR / 'mount-migrations' / record['id'] / 'backup.json', saved)
        path = b.cli.root_path('/', record['mountpoint']); path.mkdir(mode=0o755, parents=True, exist_ok=True)
        if plan(b, data['uuid'], data.get('mountpoint'))['token'] != proposal['token']:
            raise ValueError('Mount or configuration changed before location change. No entry was changed; review again.')
        store(b, record)  # Durable intent before replacing the selected entry.
        try:
            b.w.atomic_write(b.FSTAB, saved['fstab_after'], mode=0o644)
            b.command(['/usr/bin/systemctl', 'daemon-reload'])
            record['phase'] = 'applied'; store(b, record)
        except Exception:
            try:
                _rollback(b, record)
            except Exception:
                raise ValueError('Location change was interrupted. Its private backup is retained. Use Roll back location change before enabling monitoring.') from None
            raise ValueError('Location change failed and was rolled back. The original entry and configuration were restored; no disk was unmounted.') from None
    return dict(message='Permanent entry moved to the stable path; the mounted filesystem was not moved. Safely release it in the file manager, reconnect if ejected, then Check mountpoint again. Rollback is available.',
                migration=public(b), plan=b.inspect_mount(record['uuid']))


def commit(b, c, validate_only=False):
    record = pending(b)
    if not record or record['phase'] not in ('applied', 'committing'):
        raise ValueError('Location change needs rollback before settings can be saved.')
    saved = backup(b, record)
    if c['disk']['uuid'] != record['uuid'] or c['disk']['mountpoint'] != record['mountpoint']:
        raise ValueError('Complete the pending location change at its stable mountpoint or roll it back before saving other settings.')
    if text(b.s.CONFIG) not in (saved['config'], record.get('config_after', saved['config'])):
        raise ValueError('Configuration changed during location change. No settings were overwritten; review the protected backup.')
    if text(b.s.STATE_DIR / 'state.json') not in (saved['state'], record.get('state_after', saved['state'])):
        raise ValueError('Recovery state changed during location change. Stop monitoring; state and queued events were preserved.')
    row = b.target(record['uuid'])
    b.mount_plan(c, row, [])
    if row['mountpoint'] and row['mountpoint'] != record['mountpoint']:
        raise ValueError('The filesystem is still at the old location. Safely release it in the file manager, then Check mountpoint again.')
    if validate_only:
        return
    with exclusive(b):
        commit(b, c, validate_only=True)
        record.update(phase='committing', config_after=json.dumps(c, indent=2) + '\n',
                      state_after=state_for_path(b, saved['state'], record['uuid'], record['old_mountpoint'], record['mountpoint']))
        store(b, record)
        b.w.configure(c); b.w.fstab_check(c['disk']['mountpoint'])
        if record['state_after'] is not None:
            b.w.atomic_write(b.s.STATE_DIR / 'state.json', record['state_after'])
        b.cli.save(b.s.CONFIG, c)
        record['phase'] = 'committed'; store(b, record)


def _rollback(b, record):
    saved = backup(b, record)
    # Never restore stale snapshots over new configuration, incidents or mail.
    for path, name in ((b.s.CONFIG, 'config'), (b.s.STATE_DIR / 'state.json', 'state')):
        if text(path) not in (saved[name], record.get(name + '_after', saved[name])):
            raise ValueError('Rollback cannot overwrite newer ' + name + '. The protected backup is retained; current settings and recovery history were preserved.')
    current = b.FSTAB.read_bytes().decode('utf-8')
    old_lines, old_index, _ = entry(b, saved['fstab'], record['uuid'])
    after_lines, after_index, _ = entry(b, saved['fstab_after'], record['uuid'])
    lines, index, fields = entry(b, current, record['uuid'])
    if lines[index] not in (old_lines[old_index], after_lines[after_index]):
        raise ValueError('The updated entry was edited elsewhere. Rollback will not overwrite it; the protected original is retained.')
    for i, line in enumerate(lines):
        parts = line.split('#', 1)[0].split()
        if i != index and len(parts) >= 2 and b.w.unescape_mount(parts[1]) == record['old_mountpoint']:
            raise ValueError('Another entry now uses the old mountpoint. Rollback will not overwrite it; the backup is retained.')
    lines[index] = old_lines[old_index]
    record['phase'] = 'rolling_back'; store(b, record)
    if current != ''.join(lines):
        b.w.atomic_write(b.FSTAB, ''.join(lines), mode=0o644)
    for path, name in ((b.s.STATE_DIR / 'state.json', 'state'), (b.s.CONFIG, 'config')):
        if saved[name] is None:
            b.cli.root_path('/', path).unlink(missing_ok=True)
        elif text(path) != saved[name]:
            b.w.atomic_write(path, saved[name])
    b.command(['/usr/bin/systemctl', 'daemon-reload'])
    record['phase'] = 'rolled_back'; store(b, record)


def rollback(b, data):
    with exclusive(b):
        record = journal(b)
        if not record or record['id'] != data.get('id') or data.get('confirm') is not True:
            raise ValueError('Select rollback consent for the displayed location change before restoring it.')
        _rollback(b, record)
    return dict(message='Original mount entry and configuration restored. No disk was unmounted. If it is mounted at the newer path, safely release it in the file manager before using the restored path.', revision=b.s.digest(b.configuration()))
