# SPDX-License-Identifier: MIT
"""Root broker: a bounded authenticated allowlist, never a recovery executor.

The engine remains the only owner of recovery, retry budgets and delivery queues.
The broker observes engine state and records a bounded presentation history.
"""
import copy
from contextlib import contextmanager
import errno
import datetime
import hashlib
import http.client
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import socket
import socketserver
import sqlite3
import ssl
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from types import SimpleNamespace
sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location('web_common', Path(__file__).with_name('web_common.py'))
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
auth = common.module('web_auth')
cli = common.module('cli', globals().get('PROFILE'))
migration = common.module('web_migration')
protection = common.module('web_protection')
preparation = common.module('web_prepare')
images = common.module('web_images')
drive_web = common.module('web_drives')
networking = common.module('web_network')
NETWORK_MANAGER = None
s, w, n = cli.s, cli.w, cli.n
WEB_SERVICE = 'usb-storage-watch-web.service'
LAN_SERVICE = 'usb-storage-watch-lan.service'
NETWORK_LOCK = threading.Lock()
READS = {'drive-activity', 'session', 'status', 'config', 'disks', 'docker', 'events', 'diagnostics', 'mount-plan', 'migration-plan', 'protection-plan', 'unmount-plan'}
READS.add('usb-status')
READS.add('application-status')
READS.add('network-state')
NETWORK_WRITES = {'network-stage','network-confirm','network-cancel','network-certificate','network-renew'}
READS.update(('global-config','recovery-plan'))
WRITES = {'logout', 'config', 'smtp', 'test-email', 'monitor', 'qualify', 'network', 'validate', 'prepare-mount', 'migrate-mount', 'rollback-mount', 'activate-protection', 'disk-operation', 'standby-settings', 'advanced-recovery', 'protection-settings'}
SMTP_FIELDS = ('host', 'port', 'security', 'username', 'sender', 'recipient')
READS.add('prepare-disks')
WRITES.update(('prepare-drive-plan', 'prepare-drive', 'prepare-drive-activate'))
WRITES.add('change-mount-location')
READS.update(('login-info','application-images','image-discover','local-accounts','lan-info','lan-status','prepare-progress'))
WRITES.update(('image-plan','image-apply','image-action','application-settings','timing-settings','lan-auto','folder-access-plan','folder-access-apply','management-token'))
WRITES.update(('recovery-settings','notification-settings'))
WRITES.add('application-check')
WRITES.update(NETWORK_WRITES)
FSTAB = Path('/etc/fstab')


def migration_context():
    return SimpleNamespace(**{name: globals()[name] for name in (
        's', 'cli', 'w', 'FSTAB', 'FieldError', 'configuration', 'target', 'inspect_mount',
        'mount_plan', 'fstab_entries', 'temporary_mount', 'command')})


def protection_context():
    return SimpleNamespace(**{name: globals()[name] for name in (
        's', 'w', 'n', 'cli', 'FSTAB', 'configuration', 'target', 'migration', 'migration_context',
        'fstab_entries', 'same_source', 'mount_plan', 'service_state', 'command', 'prepare_smtp')})


def preparation_context():
    return SimpleNamespace(**{name: globals()[name] for name in (
        's', 'w', 'cli', 'FSTAB', 'configuration', 'target', 'migration', 'migration_context',
        'fstab_entries', 'same_source', 'mount_plan', 'command', 'service_state', 'FieldError', 'media_kind')})


class FieldError(ValueError):
    def __init__(self, field, step, message):
        super().__init__(message)
        self.field, self.step = field, step


def virtualization():
    try:
        result = subprocess.run(['/usr/bin/systemd-detect-virt'], capture_output=True,
                                text=True, timeout=5, check=False)
        name = result.stdout.strip()
        if result.returncode == 0 and re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', name) and name != 'none':
            return dict(kind='virtual', name=name)
        if result.returncode == 1 and name == 'none':
            return dict(kind='physical', name='')
    except (OSError, subprocess.SubprocessError):
        pass
    return dict(kind='unknown', name='')


def service_state():
    value = command(['/usr/bin/systemctl', 'show', cli.SERVICE,
                     '--property=ActiveState,SubState,UnitFileState'])
    return dict(line.split('=', 1) for line in value.splitlines() if '=' in line)


def temporary_mount(path):
    return any(path == root or s.below(root, path) for root in ('/run', '/media'))


def fstab_entries():
    entries = []
    for line in FSTAB.read_text().splitlines():
        fields = line.split('#', 1)[0].split()
        if fields:
            if len(fields) < 4:
                raise ValueError('The permanent mount table contains an incomplete entry. Administrator review required; no entries were changed.')
            entries.append(fields)
    return entries


def same_source(source, row):
    if source.startswith('UUID=') and source[5:].strip('\"\'') == row['uuid']:
        return True
    device = row.get('device')
    if not device or source.startswith('UUID='):
        return False
    if source.startswith(('LABEL=', 'PARTUUID=', 'PARTLABEL=')):
        result = subprocess.run(['/usr/sbin/findfs', source], capture_output=True,
                                text=True, timeout=5, check=False)
        if result.returncode:
            # An unresolved alias could become this disk on reconnect.
            raise ValueError('An existing fstab device alias cannot be resolved. Administrator review is required; no entries were changed.')
        source = result.stdout.strip()
    return source.startswith('/dev/') and Path(source).resolve() == Path(device).resolve()


def proposed_mountpoint(old, row, recovery):
    transaction = migration.pending(migration_context())
    if transaction:
        if transaction['uuid'] != row['uuid']:
            raise ValueError('Complete or roll back the pending mount location change before selecting another disk.')
        return transaction['mountpoint']
    if old['disk']['uuid']:
        if old['disk']['uuid'] != row['uuid']:
            raise ValueError('Changing an established disk requires safe state archival by an administrator; existing history is preserved.')
        return old['disk']['mountpoint']
    if recovery:
        entries = [entry for entry in fstab_entries() if same_source(entry[0], row)]
        if entries:
            if len(entries) != 1 or entries[0][0] != 'UUID=' + row['uuid']:
                raise ValueError('Existing fstab entries for this disk conflict with UUID-based recovery. Administrator review required; entries are preserved.')
            return w.unescape_mount(entries[0][1])
        if not row['mountpoint'] or temporary_mount(row['mountpoint']):
            return '/mnt/usb-storage-watch-' + row['uuid']
    return row['mountpoint'] or '/mnt/usb-storage-watch-' + row['uuid']


def command(args, timeout=10):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise ValueError('System operation failed. Check the service journal in Advanced settings.')
    return result.stdout


def configuration():
    return s.read() if s.CONFIG.exists() else s.default()


def disks():
    raw = json.loads(command(['/usr/bin/lsblk', '--json', '--bytes', '--paths', '--output',
                              'NAME,TYPE,FSTYPE,UUID,LABEL,MOUNTPOINTS,SIZE,MODEL,TRAN,RO']))
    identities = [child.get('uuid') for disk in raw['blockdevices'] for child in cli.flatten([disk])
                  if child.get('type') in ('disk', 'part') and child.get('uuid')]
    rows = []
    for disk in raw['blockdevices']:
        if disk['type'] != 'disk':
            continue
        kind='unknown'
        if disk.get('tran')=='usb':
            try:
                dev=w.device_number(disk['name'])
                kind=media_kind(w.udev(dev),(Path('/sys/dev/block')/dev/'queue/rotational').read_text().strip())
            except (OSError,ValueError,w.Unsafe):pass
        children = list(cli.flatten([disk]))
        system = any(p in ('/', '/boot', '/boot/efi', '/usr', '/var', '/home', '[SWAP]')
                     for child in children for p in (child.get('mountpoints') or []))
        if system:
            continue
        for child in children:
            if child['type'] not in ('disk', 'part') or child.get('children'):
                continue
            points = [p for p in child.get('mountpoints', []) if p]
            reason = ('Only ext4 filesystems with a UUID are supported.' if child.get('fstype') != 'ext4'
                      or not child.get('uuid') else 'This device is read-only.' if child.get('ro')
                      else 'Multiple mountpoints require administrator review.' if len(points) > 1 else '')
            model = (child.get('model') or disk.get('model') or 'USB drive').strip()
            if child.get('label'):
                model = child['label'] + ' · ' + model
            rows.append(dict(device=child['name'], model=model,
                             size=int(child['size']), filesystem=child.get('fstype') or 'Unformatted',
                             uuid=child.get('uuid') or '', mountpoint=points[0] if points else '',
                             transport=disk.get('tran') or '', media_kind=kind, eligible=not reason, reason=reason))
    # Ambiguous duplicate filesystem identities are never selectable.
    for row in rows:
        if row['uuid'] and identities.count(row['uuid']) != 1:
            row.update(eligible=False, reason='Duplicate filesystem UUID. Administrator review required.')
    return rows


def target(uuid):
    if not isinstance(uuid, str):
        raise ValueError('Select a data disk.')
    rows = [row for row in disks() if row['eligible'] and row['uuid'] == uuid]
    if len(rows) != 1:
        raise ValueError('Selected disk is absent, ambiguous, unsupported, or belongs to the operating system.')
    return rows[0]


def smtp_public():
    if not s.SMTP.exists():
        return dict(host='', port=587, security='starttls', username='', sender='', recipient='', password_set=False)
    value = n.load_config()
    return {key: value[key] for key in SMTP_FIELDS} | {'password_set': bool(value['password'])}


def prepare_smtp(data):
    if not isinstance(data, dict) or set(data) - set(SMTP_FIELDS) - {'password'}:
        raise ValueError('Unexpected email settings.')
    value = {key: data.get(key) for key in SMTP_FIELDS}
    value.update(version=1, password=data.get('password', ''))
    if not value['password'] and s.SMTP.exists():
        value['password'] = n.load_config()['password']
    # Never include a submitted value in a validation error.
    try:
        if any(isinstance(v, str) and len(v) > 4096 for v in value.values()):
            raise ValueError()
        n.validate_config(value)
    except (ValueError, TypeError):
        raise ValueError('Check the SMTP server, port, TLS mode, login, password and email addresses.') from None
    return value


def mount_plan(c, row, confirmed, transition=False, allow_desktop=False):
    """Return a proposed fstab append; never replace an existing entry."""
    path = c['disk']['mountpoint']
    s.absolute(path, 'Mountpoint')
    if row['mountpoint'] and row['mountpoint'] != path and not transition:
        raise ValueError('Mountpoint: the disk is still mounted at ' + row['mountpoint'] +
                         '. Close files and safely unmount/eject it in the desktop file manager. If ejected, reconnect it, then click Check mountpoint again. Never unplug a busy disk.')
    entries = [entry for entry in fstab_entries()
               if same_source(entry[0], row) or w.unescape_mount(entry[1]) == path]
    if entries:
        if len(entries) != 1 or entries[0][0] != 'UUID=' + row['uuid'] or entries[0][1] != path or entries[0][2] != 'ext4':
            raise ValueError('An existing fstab entry conflicts with this disk. Administrator review required.')
        c['disk']['fstab_options'] = entries[0][3]
        s.options(c['disk']['fstab_options'])
        return None
    if temporary_mount(path) and not (allow_desktop and w.desktop_target(path)):
        raise ValueError('Mountpoint: this session location has no valid permanent UUID entry. Leave automatic remounting off until a stable location is configured.')
    if 'fstab' not in confirmed:
        raise ValueError('Confirm adding a permanent UUID-based mount entry before enabling remounting.')
    c['disk']['fstab_options'] = 'defaults,nofail,nodev,nosuid,x-systemd.device-timeout=10s'
    return f'\n# USB Storage Watch: explicitly approved in setup\nUUID={row["uuid"]} {path} ext4 {c["disk"]["fstab_options"]} 0 0\n'


def inspect_mount(uuid):
    """Read-only proposal, recomputed before consent is acted upon."""
    try:
        row = target(uuid)
        c = configuration()
        transaction = migration.pending(migration_context())
        path = proposed_mountpoint(c, row, True)
        c['disk'].update(uuid=uuid, mountpoint=path)
        c['recovery']['mount'] = True
        addition = mount_plan(c, row, ['fstab'], transition=True)
        s.validate(c)
        p = cli.root_path('/', path)
        if p.exists() and not p.is_dir():
            raise ValueError('Mountpoint must be a directory; the existing file is preserved.')
        # A normal mount may hide underlying files; preserve them. Reject active mounts.
        if row['mountpoint'] != path:
            if any(w.covers(path, mount['target']) for mount in w.read_rows()):
                raise ValueError('Proposed mountpoint is already used by another mount. Administrator review required.')
        return dict(uuid=uuid, current=row['mountpoint'], mountpoint=path,
                    temporary=temporary_mount(row['mountpoint']), needs_entry=bool(addition),
                    can_migrate=not transaction and not addition and temporary_mount(path),
                    migration=migration.public(migration_context()),
                    transition=bool(row['mountpoint'] and row['mountpoint'] != path),
                    entry=f'UUID={uuid} {path} ext4 {c["disk"]["fstab_options"]} 0 0',
                    token=s.digest(dict(fstab=FSTAB.read_text(), disk=c['disk'], current=row['mountpoint'])))
    except (ValueError, w.Unsafe) as exc:
        raise FieldError('mountpoint', 2, str(exc)) from None


def prepare_mount(data):
    cli.stopped()
    old = configuration()
    if data.get('revision') != s.digest(old):
        raise FieldError('mountpoint', 2, 'Settings changed in another session. Reload setup before preparing the mountpoint.')
    plan = inspect_mount(data.get('uuid'))
    if data.get('plan_token') != plan['token']:
        raise FieldError('mountpoint', 2, 'Mountpoint or permanent entries changed. Check mountpoint again and review the new proposal.')
    if data.get('confirm') is not True:
        raise FieldError('confirm-fstab', 2, 'Confirm the permanent mount entry before creating it.')
    if not plan['needs_entry']:
        return {'message': 'The existing permanent entry is preserved.', 'plan': plan}
    original = FSTAB.read_text()
    p = cli.root_path('/', plan['mountpoint'])
    p.mkdir(mode=0o755, parents=True, exist_ok=True)
    cli.save(s.STATE_DIR / 'fstab-before-web.json', {'content': original})
    # Recheck after backup/directory creation and immediately before the append.
    if inspect_mount(data['uuid'])['token'] != plan['token'] or FSTAB.read_text() != original:
        raise FieldError('mountpoint', 2, 'Mount settings changed. Check mountpoint again; no entry was added.')
    addition = '\n# USB Storage Watch: explicitly approved in setup\n' + plan['entry'] + '\n'
    w.atomic_write(FSTAB, original + addition, mode=0o644)
    try:
        command(['/usr/bin/systemctl', 'daemon-reload'])
    except Exception:
        if FSTAB.read_text() == original + addition:
            w.atomic_write(FSTAB, original, mode=0o644)
            try:
                command(['/usr/bin/systemctl', 'daemon-reload'])
            except (ValueError, OSError, subprocess.SubprocessError):
                pass  # Preserve the original failure; the on-disk table is restored.
        raise
    return {'message': 'Permanent mount entry created. No disk was unmounted or moved. The entry remains if you leave setup.',
            'plan': inspect_mount(data['uuid'])}


def docker_api(c):
    """Negotiate only a version; reuse the engine's local Unix connection."""
    w.apps.configure(c['docker'])
    connection = w.apps.LocalConnection('localhost', timeout=3)
    try:
        connection.request('GET', '/version')
        response = connection.getresponse()
        body = response.read(65537)
        if response.status != 200 or len(body) > 65536:
            raise ValueError('Docker version discovery failed.')
        value = json.loads(body)
        high, low = value.get('ApiVersion', ''), value.get('MinAPIVersion', '1.24')
        if not all(isinstance(v, str) and re.fullmatch(r'1\.\d{2}', v) for v in (low, high)):
            raise ValueError('Unsupported Docker API version.')
        preferred = c['docker']['api'][1:]
        c['docker']['api'] = 'v' + (preferred if int(low[2:]) <= int(preferred[2:]) <= int(high[2:]) else high)
    finally:
        connection.close()


def container_rows(c):
    """Legacy discovery route: bindings are metadata, never an eligibility gate."""
    docker_api(c)
    probe=copy.deepcopy(c);probe['recovery']['mount']=False;probe['usb']['enabled']=False;probe['docker']['enabled']=False
    w.configure(probe);docker=w.apps.Docker();rows=[];deadline=time.monotonic()+18
    for raw in docker.request('GET','/containers/json?all=1'):
        if time.monotonic()>deadline:raise ValueError('Docker discovery exceeded its deadline.')
        identity=raw.get('Id','')
        if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity):continue
        current=docker.inspect(identity)
        binds=[dict(source=m.get('Source') or '',destination=m.get('Destination') or '',eligible=True,reason='')
               for m in current.get('mounts',[]) if m.get('Type')=='bind']
        rows.append(dict(id=identity,name=current['name'],running=current['running'],paused=current['paused'],
                         restarting=current['restarting'],dead=current['dead'],health=current['health'],
                         binds=binds,required_storage=w.apps.required_storage_labels(w,current),eligible=True,reason=''))
    return rows


def selected_containers(c, selections):
    if not isinstance(selections,list):raise ValueError('Select containers from the discovered list.')
    available=container_rows(c);result=[]
    for choice in selections:
        if not isinstance(choice,dict) or set(choice)-{'id','destination','images'} or 'id' not in choice:
            raise ValueError('Invalid container selection.')
        row=next((v for v in available if v['id']==choice['id']),None)
        if row is None:raise ValueError('Container identity changed. Refresh the container list.')
        hint=next((v for v in row['binds'] if v['destination']==choice.get('destination')), {})
        previous=next((v for v in c['docker']['containers'] if v['name']==row['name']),{})
        result.append(dict(name=row['name'],source=hint.get('source',''),destination=hint.get('destination',''),
                           grace=previous.get('grace',30),container_id=row['id'],images=choice.get('images',previous.get('images',[]))))
    return result


def save_configuration(data, validate_only=False):
    if validate_only: return _save_configuration(data, validate_only=True)
    guard = common.module('app_control')
    with guard.drive_settings(SimpleNamespace(s=s, cli=cli, common=common, w=w), configuration(), guard.requested_identities(data)) as recheck:
        return _save_configuration(data, recheck=recheck)


def _save_configuration(data, validate_only=False, *, recheck=None):
    try:
        cli.stopped()
    except ValueError as exc:
        raise FieldError('setup-service', 0, str(exc)) from None
    old = configuration()
    if data.get('revision') != s.digest(old):
        raise ValueError('Settings changed in another session. Reload before saving.')
    if set(data) - {'revision', 'uuid', 'label', 'notifications', 'mount', 'usb', 'docker', 'containers', 'confirmations', 'advanced', 'mount_token'}:
        raise ValueError('Unknown configuration fields.')
    transaction = migration.pending(migration_context())
    if transaction and not data.get('mount', old['recovery']['mount']):
        raise FieldError('mountpoint', 2, 'Complete the pending mount location change with automatic remounting, or use Roll back location change before saving other settings.')
    try:
        row = target(data.get('uuid'))
    except ValueError as exc:
        raise FieldError('disk-choice', 0, str(exc)) from None
    c = copy.deepcopy(old)
    try:
        mountpoint = proposed_mountpoint(old, row, data.get('mount', old['recovery']['mount']))
    except ValueError as exc:
        raise FieldError('mountpoint', 2, str(exc)) from None
    c['disk'].update(uuid=row['uuid'], mountpoint=mountpoint, label=data.get('label', 'USB storage'))
    confirmations = data.get('confirmations', [])
    if not isinstance(confirmations, list) or any(type(v) is not str for v in confirmations):
        raise ValueError('Invalid confirmations.')
    for key, group, field in [('mount', 'recovery', 'mount'), ('usb', 'usb', 'enabled'), ('docker', 'docker', 'enabled')]:
        enabled = data.get(key, old[group][field])
        s.boolean(enabled, key)
        if enabled and not old[group][field] and key not in confirmations:
            raise FieldError('confirm-' + key, 2, 'Explicit confirmation is required to enable ' + key + ' recovery. Select its authorization checkbox in Recovery.')
        c[group][field] = enabled
    c['notifications']['enabled'] = data.get('notifications', old['notifications']['enabled'])
    if c['notifications']['enabled']:
        if not s.SMTP.exists():
            raise FieldError('email-enabled', 1, 'Email: save or test your email settings before enabling notifications, or turn email off.')
        n.load_config()
    if 'containers' in data:
        try:
            c['docker']['containers'] = selected_containers(c, data['containers']) if data['containers'] else []
        except (ValueError, w.Unsafe, w.apps.AppError) as exc:
            raise FieldError('apps-message', 3, str(exc)) from None
    allowed = {'monitor': ('interval', 'observations', 'boot_grace'),
               'recovery': ('wait', 'attempts', 'worker_timeout', 'return_timeout_minutes'),
               'usb': ('enumeration_seconds', 'disable_seconds'),
               'docker': ('health_timeout', 'worker_timeout')}
    advanced = data.get('advanced', {})
    if not isinstance(advanced, dict):
        raise ValueError('Invalid advanced settings.')
    for group, values in advanced.items():
        if group not in allowed or not isinstance(values, dict) or set(values) - set(allowed[group]):
            raise ValueError('Unsupported advanced setting.')
        c[group].update(values)
    try:
        addition = mount_plan(c, row, confirmations) if c['recovery']['mount'] else None
        if c['recovery']['mount']:
            plan = inspect_mount(row['uuid'])
            if addition and data.get('mount_token') != plan['token']:
                raise FieldError('confirm-fstab', 2, 'Permanent mount proposal changed. Check mountpoint again and review the entry before consenting.')
    except FieldError:
        raise
    except (ValueError, w.Unsafe) as exc:
        field = 'confirm-fstab' if 'Confirm adding' in str(exc) else 'mountpoint'
        raise FieldError(field, 2, str(exc)) from None
    if not c['recovery']['mount']:
        c['disk']['fstab_options'] = ''
    try:
        s.validate(c)
    except ValueError as exc:
        message = str(exc)
        field, page = ('disk-label', 0) if 'disk.label' in message else ('recover-usb', 2) if 'USB' in message or 'usb.' in message else ('apps-message', 3) if 'container' in message.lower() or 'docker' in message.lower() else ('mountpoint', 2)
        raise FieldError(field, page, message) from None
    # Validate mountpoint traversal before any filesystem/configuration mutation.
    p = cli.root_path('/', mountpoint)
    if p.exists() and not p.is_dir():
        raise ValueError('Mountpoint must be a directory.')
    if recheck: recheck()  # Still holding the exact-ID locks after slow discovery.
    if transaction:
        try:
            migration.commit(migration_context(), c, validate_only=validate_only)
        except ValueError as exc:
            raise FieldError('mountpoint', 2, str(exc)) from None
        return {'message': 'Location change and settings saved. The private backup is retained.',
                'revision': s.digest(c), 'mountpoint': mountpoint}
    if validate_only:
        return {'message': 'Setup prerequisites checked.', 'mountpoint': mountpoint}
    original = FSTAB.read_text()
    try:
        if addition:
            p.mkdir(mode=0o755, parents=True, exist_ok=True)
            cli.save(s.STATE_DIR / 'fstab-before-web.json', {'content': original})
            if inspect_mount(row['uuid'])['token'] != plan['token'] or FSTAB.read_text() != original:
                raise FieldError('mountpoint', 2, 'Mount settings changed before saving. Check mountpoint again; no entry was added.')
            w.atomic_write(FSTAB, original + addition, mode=0o644)
            command(['/usr/bin/systemctl', 'daemon-reload'])
        w.configure(c)
        if c['recovery']['mount']:
            w.fstab_check(w.MOUNT)
            if s.storage_images(c):
                for image in s.storage_images(c): w.fstab_check(image['mountpoint'])
        cli.save(s.CONFIG, c)
    except Exception:
        if addition:
            if FSTAB.read_text() == original + addition:
                w.atomic_write(FSTAB, original, mode=0o644)
                try:
                    command(['/usr/bin/systemctl', 'daemon-reload'])
                except (ValueError, OSError, subprocess.SubprocessError):
                    pass
        raise
    return {'message': 'Settings saved. Monitoring can now be enabled.', 'revision': s.digest(c)}


def sleep_operation(c):
    """A standby request never changes the monitoring service or its settings."""
    worker = None
    try:
        worker = w.Worker(['/usr/bin/python3', '-I', str(Path(__file__).with_name('engine.py')), '_manual'],
                          dict(action='sleep', config_digest=s.digest(c)),
                          c['recovery']['worker_timeout'] + 30, directory=s.STATE_DIR)
        done = worker.poll()
        while done is None:
            time.sleep(0.1)
            done = worker.poll()
        if not done:
            raise ValueError('Sleep worker did not complete.')
        result = w.worker_json(worker)
        if (not isinstance(result, dict) or type(result.get('ok')) is not bool
                or not isinstance(result.get('message'), str)):
            raise ValueError('Invalid sleep result.')
    except (OSError, ValueError, subprocess.SubprocessError):
        result = dict(ok=False, result='uncertain',
                      message='Sleep request failed or timed out; HDD power state is unverified. No automatic retry was sent.')
    finally:
        if worker is not None:
            worker.cancel()
            worker.close()
    try:
        result['service'] = service_state()
        state = result['service'].get('ActiveState')
        status = {'active': 'on', 'inactive': 'off', 'failed': 'failed'}.get(state, state or 'unknown')
        result['message'] += ' Monitoring is ' + status + '; the sleep request did not change it.'
    except (OSError, ValueError, subprocess.SubprocessError):
        result['service'] = {'ActiveState': 'unknown'}
        result['message'] += ' Monitoring was not changed; its current status could not be read.'
    result['last_operation'] = dict(uuid=c['disk']['uuid'], action='sleep',
                                   message=result['message'], ok=result['ok'], time=w.timestamp())
    try:
        w.atomic_write(s.STATE_DIR / 'manual-operation.json', json.dumps(result['last_operation']) + '\n')
    except OSError:
        result['history_warning'] = 'The last operation could not be saved; review the result shown here before retrying.'
    return result


def disk_operation(data, *, reviewed=False, lock_fds=()):
    if set(data) != {'action', 'uuid'} or data['action'] not in ('mount', 'unmount', 'reconnect', 'sleep'):
        raise ValueError('Choose a disk operation.')
    if data['action'] == 'unmount' and not reviewed:
        raise ValueError('Use Unmount safely in Storage Watch to review dependent apps before unmounting.')
    c = configuration()
    if not c['disk']['uuid'] or data['uuid'] != c['disk']['uuid']:
        raise ValueError('Selected disk changed. Refresh before operating it.')
    if data['action'] == 'sleep':
        return sleep_operation(c)
    if data['action'] == 'reconnect':
        try:
            w.configure(c)
            w.manual_usb.unmounted(w, w.manual_usb.capabilities(w))
        except (OSError, ValueError, w.Unsafe) as exc:
            # A refusal is an operation result, so both the drive page and
            # history retain it. No stop, unmount, or port write has occurred.
            message = str(exc) if isinstance(exc, (ValueError, w.Unsafe)) else 'Current USB connection could not be verified.'
            message += ' No reconnect was sent. Mounts and monitoring were left unchanged.'
            result = dict(ok=False, result=getattr(exc, 'standby_result', 'refused'), storage_unchanged=True, message=message,
                          service=service_state())
            result['last_operation'] = dict(uuid=c['disk']['uuid'],action='reconnect',message=message,ok=False,time=w.timestamp())
            w.atomic_write(s.STATE_DIR/'manual-operation.json',json.dumps(result['last_operation'])+'\n')
            return result
    active = service_state().get('ActiveState') == 'active'
    if data['action'] != 'reconnect':
        command(['/usr/bin/systemctl', 'stop', cli.SERVICE], 35)
    # The worker owns recovery.lock; mount actions also own monitor.lock.
    worker = w.Worker(['/usr/bin/python3', '-I', str(Path(__file__).with_name('engine.py')), '_manual'],
                      dict(action=data['action'], config_digest=s.digest(c), manual_lock_fds=list(lock_fds)),
                      c['recovery']['worker_timeout'] + 30, directory=s.STATE_DIR, **(dict(lock_fds=lock_fds) if lock_fds else {}))
    try:
        done = worker.poll()
        while done is None:
            time.sleep(0.1)
            done = worker.poll()
        if not done:
            state = 'Monitoring was left unchanged.' if data['action'] == 'reconnect' else 'Monitoring remains stopped.'
            raise ValueError('Disk operation failed or timed out; result is uncertain. ' + state + ' Operation locks prevent overlapping work.')
        result = w.worker_json(worker)
        if data['action'] == 'unmount' and result['ok']:
            command(['/usr/bin/systemctl', 'disable', cli.SERVICE])
        elif data['action'] != 'reconnect' and active and (result['ok'] or result.get('storage_unchanged') is True):
            command(['/usr/bin/systemctl', 'start', cli.SERVICE], 30)
        result['service'] = service_state()
        if data['action'] == 'reconnect':
            result['message'] += ' Monitoring was left unchanged.'
        elif not result['ok'] and result.get('storage_unchanged') is True:
            result['message'] += ' Mounts were left unchanged. Monitoring returned to its previous state.'
        elif not result['ok']:
            result['message'] += ' Monitoring is ' + ('on.' if result['service'].get('ActiveState') == 'active' else 'paused.')
        result['last_operation'] = dict(uuid=c['disk']['uuid'],action=data['action'],message=result['message'],ok=result['ok'],time=w.timestamp())
        w.atomic_write(s.STATE_DIR/'manual-operation.json',json.dumps(result['last_operation'])+'\n')
        return result
    finally:
        worker.cancel()
        worker.close()


def require_notification_settings():
    # This boundary only reads local SMTP configuration. Do not translate later
    # monitor/service failures into a missing-email error, or expose file contents.
    try:
        return n.load_config()
    except FileNotFoundError:
        raise ValueError('Email is not configured. Open Email & Notifications, save your SMTP settings and send a test email, then enable notifications for this drive.') from None
    except OSError:
        raise ValueError('Saved email settings cannot be read safely. Open Email & Notifications to review them; an administrator may need to check configuration ownership and permissions. Drive settings and monitoring were not changed.') from None
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Saved email settings are invalid. Open Email & Notifications, correct and save your SMTP settings, then test email before enabling drive notifications.') from None


def update_options(action, data):
    c = configuration()
    if data.get('revision') != s.digest(c):
        raise ValueError('Settings changed; refresh before saving.')
    if action == 'notification-settings':
        if set(data) != {'revision','enabled'} or type(data['enabled']) is not bool:
            raise ValueError('Choose the notification preference for this drive.')
        c['notifications']['enabled']=data['enabled']
        if data['enabled']: require_notification_settings()
    elif action == 'protection-settings':
        if set(data) != {'revision', 'automatic', 'notifications'}:
            raise ValueError('Invalid monitoring settings.')
        c['recovery']['mount'] = data['automatic']
        c['notifications']['enabled'] = data['notifications']
        c['usb']['enabled'] = data['automatic']
        if data['automatic'] and not c['disk']['fstab_options']:
            raise ValueError('Open Manage Drive to review this disk’s recovery settings first.')
        if data['notifications']:
            require_notification_settings()
    elif action == 'standby-settings':
        if set(data) != {'revision', 'enabled', 'idle_seconds'}:
            raise ValueError('Invalid standby settings.')
        c['standby'] = dict(enabled=data['enabled'], idle_seconds=data['idle_seconds'])
    else:
        if set(data) != {'revision', 'dependent', 'services'}:
            raise ValueError('Invalid advanced recovery settings.')
        c['dependent'], c['services'] = data['dependent'], data['services']
    c = s.validate(c)
    active = service_state().get('ActiveState') == 'active'
    command(['/usr/bin/systemctl', 'stop', cli.SERVICE], 35)
    try:
        cli.stopped()
        with migration.exclusive(migration_context()):
            cli.save(s.CONFIG, c)
    finally:
        if active:
            command(['/usr/bin/systemctl', 'start', cli.SERVICE], 30)
    return dict(message='Settings saved.', revision=s.digest(c))


class History:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, at TEXT, title TEXT, detail TEXT)')
            # Derived presentation metadata; retain the original event time and
            # all incident/receipt evidence, including on an older UI rollback.
            db.execute('CREATE TABLE IF NOT EXISTS event_times (id TEXT PRIMARY KEY, outcome_at TEXT, outage_started TEXT)')

    @staticmethod
    def valid_time(value):
        try:
            parsed = datetime.datetime.fromisoformat(value)
            return value if parsed.tzinfo is not None else None
        except (TypeError, ValueError): return None

    @staticmethod
    def sort_key(value):
        stamp = History.valid_time(value)
        return (datetime.datetime.fromisoformat(stamp).timestamp() if stamp else float('-inf'), value or '')

    ORDER = 'COALESCE(julianday(COALESCE(t.outcome_at,e.at)),0) DESC, COALESCE(t.outcome_at,e.at) DESC, e.id DESC'

    @contextmanager
    def connect(self):
        # sqlite's context manager ends a transaction; it does not close the
        # connection. Explicit ownership must not depend on cyclic GC timing.
        db = sqlite3.connect(self.path, timeout=0.25)
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(self, key, at, title, lines, *, outcome_at=None, outage_started=None):
        with self.connect() as db:
            if outcome_at is not None or outage_started is not None:
                db.execute('INSERT OR REPLACE INTO event_times VALUES (?,?,?)',
                           (key, self.valid_time(outcome_at), self.valid_time(outage_started)))
            db.execute('INSERT OR REPLACE INTO events VALUES (?,?,?,?)', (key, at, title[:200], '\n'.join(lines)[:6000]))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT e.id FROM events e LEFT JOIN event_times t ON t.id=e.id ORDER BY '+self.ORDER+' LIMIT 200)')
            db.execute('DELETE FROM event_times WHERE id NOT IN (SELECT id FROM events)')

    def capture_times(self, incident):
        """Backfill known archived rows without replacing their stored evidence."""
        values = [(incident['id'], incident.get('completed_at'), incident.get('first_failure'))]
        deadline = incident.get('return_deadline') or {}
        if deadline.get('reported_at'):
            values.append((incident['id'] + '-return-timeout', deadline['reported_at'], incident.get('first_failure')))
        with self.connect() as db:
            for key, outcome, started in values:
                db.execute('INSERT OR REPLACE INTO event_times VALUES (?,?,?)',
                           (key, self.valid_time(outcome), self.valid_time(started)))

    def capture(self):
        # Completed incidents are archived by the engine before replacement, so
        # broker downtime cannot erase a reconnect's prior failure/success.
        with self.connect() as db:
            known = dict(db.execute('SELECT id,title FROM events'))
            dated = dict(db.execute('SELECT id,outcome_at FROM event_times'))
        archived = sorted((s.STATE_DIR / 'incidents').glob('*.json'), key=lambda p: p.stat().st_mtime)[-200:]
        for path in archived:
            if path.stem not in known:
                self.capture_incident(json.loads(path.read_text()))
            elif not dated.get(path.stem):
                incident = json.loads(path.read_text())
                if incident.get('outcome') and known[path.stem] != incident['outcome']:
                    self.capture_incident(incident)  # Completion missed while broker was offline.
                else:
                    self.capture_times(incident)
        # Older cache rows can outlive their archived source. Use only an exact
        # stored outcome timestamp, never guess from title or observation time.
        with self.connect() as db:
            for key, at, detail in db.execute('SELECT e.id,e.at,e.detail FROM events e LEFT JOIN event_times t ON t.id=e.id WHERE t.id IS NULL').fetchall():
                found = re.search(r'^Outcome recorded: ([^\n]+)$', detail or '', re.M)
                outcome = self.valid_time(found[1]) if found else None
                if outcome:
                    db.execute('INSERT INTO event_times VALUES (?,?,?)', (key, outcome, self.valid_time(at)))
        path = s.STATE_DIR / 'state.json'
        if not path.exists():
            return
        state = json.loads(path.read_text())
        incident = state.get('incident')
        if not incident:
            return
        self.capture_incident(incident)

    def capture_incident(self, incident):
        lines = [incident.get('first_detail', ''), 'Phase: ' + str(incident.get('phase', 'unknown'))]
        deadline = incident.get('return_deadline') or {}
        if deadline.get('reported_at'):
            self.record(incident['id'] + '-return-timeout', deadline['reported_at'],
                        deadline['outcome'], ['Confirmed outage: ' + incident.get('confirmed_at', ''),
                        'Drive return timeout recorded: ' + deadline['reported_at'],
                        'Notification: ' + deadline.get('notification', 'unknown'),
                        'Recovery may continue on a later verified return; existing action budgets are retained.'],
                        outcome_at=deadline['reported_at'], outage_started=incident.get('first_failure'))
            lines.append('Drive return timeout recorded: ' + deadline['reported_at'])
        if incident.get('completed_at'):
            lines.append('Outcome recorded: ' + incident['completed_at'])
        for attempt in incident.get('attempts', []):
            lines.append(f'Attempt {attempt.get("number")}: {attempt.get("status", "pending")} — {attempt.get("reason", "")}')
            for image in attempt.get('images', []):
                lines.append(f'  Image {image.get("name", image.get("uuid", "unknown"))}: {"mounted" if image.get("healthy") else "warning"} — {image.get("detail", "")}')
            for action in attempt.get('actions', []):
                lines.append(f'  {action.get("target", "Action")}: {action.get("stage", "")} {action.get("detail", "")}')
        if incident.get('usb'):
            lines.append(str(incident['usb']))
        stopped = incident.get('stop') or {}
        if stopped:
            lines.append('Container stop stage: ' + str(stopped.get('phase', 'pending')))
            for name, result in (stopped.get('result') or {}).get('containers', {}).items():
                lines.append(f'  {name}: {result.get("status", "unknown")} — {result.get("reason", "")}')
        app = incident.get('applications') or {}
        if app:
            lines.append('Container start stage: ' + str(app.get('phase', app.get('status', 'see recovery journal'))))
            for identity, image in (app.get('result') or {}).get('images', {}).items():
                lines.append(f'  Image {image.get("name", identity)}: {image.get("status", "unknown")} — {image.get("detail", "")}')
            for name, result in (app.get('result') or {}).get('containers', {}).items():
                lines.append(f'  {name}: {result.get("status", "unknown")} — {result.get("reason", "")} (actions: {result.get("action_count", 0)})')
                for warning in result.get('warnings', []):
                    lines.append(f'    Warning: {warning}')
            for unit, result in (app.get('result') or {}).get('services', {}).items():
                lines.append(f"  {unit}: {result.get('status', 'unknown')} — {result.get('reason', '')}")
        self.record(incident['id'], incident.get('first_failure', ''),
                    incident.get('outcome') or 'Storage outage', lines,
                    outcome_at=incident.get('completed_at'), outage_started=incident.get('first_failure'))

    def events(self, limit=40):
        self.capture()
        rows, size = [], 0
        with self.connect() as db:
            for row in db.execute('SELECT COALESCE(t.outcome_at,e.at),e.title,e.detail,t.outage_started FROM events e LEFT JOIN event_times t ON t.id=e.id ORDER BY '+self.ORDER+' LIMIT ?', (min(200,max(1,limit)),)):
                value = dict(time=row[0], title=row[1], detail=row[2])
                if row[3]: value['outage_started'] = row[3]
                size += len(json.dumps(value).encode()) + 2
                if size > 90000:
                    break
                rows.append(value)
        return rows


def recovery_progress(c, state, probe, service, now=None):
    """Presentation only. All scheduling, budgets and actions belong to engine."""
    now = w.clock_now() if now is None else now
    i = state.get('incident') or {}
    phase = i.get('phase')
    active = service.get('ActiveState') == 'active'
    base = dict(phase=phase, incident=i.get('id'), attempt=len(i.get('attempts', [])),
                last_outcome=i.get('outcome'), completed_at=i.get('completed_at'), wait_seconds=None)
    deadline = common.module('return_deadline').status(i, now, w.boot_id())
    base['drive_return'] = deadline
    def result(code, title, detail):
        if (active and deadline and not deadline['expired'] and probe.get('detected') is False
                and phase not in ('done', 'legacy')):
            detail += ' ' + common.module('return_deadline').message(i, now, w.boot_id())
        return base | dict(code=code, title=title, detail=detail)
    if not c['disk']['uuid']:
        return result('unconfigured', 'Set up monitoring', 'Add your USB drive from Overview.')
    if service.get('ActiveState') not in ('active','inactive','failed'):
        return result('unknown','Monitoring state unknown','The service is changing state or its status is unavailable. Refresh before changing settings.')
    if not active:
        return result('disabled', 'Monitoring disabled', 'No automatic recovery is running. Disk status is a live read-only check.')
    if (state.get('sample_boot') != w.boot_id() or state.get('sample_at') is None
            or now - state['sample_at'] > max(30, c['monitor']['interval'] * 2 + 5)):
        return result('starting', 'Waiting for monitor update', 'The service is active; waiting for a fresh observation.')
    if state.get('status') == 'down' and phase in ('wait1', 'wait2', 'return_failed', 'running', 'verify', 'applications'):
        stopped = i.get('stop') or {}
        if stopped and (stopped.get('phase') != 'done' or
                        (stopped.get('result') or {}).get('all_stopped') is not True):
            failed = [row.get('reason', '') for row in
                      (stopped.get('result') or {}).get('containers', {}).values()
                      if row.get('status') in ('failed', 'uncertain')]
            if failed or (stopped.get('result') or {}).get('error'):
                return result('waiting_stop', 'Waiting for containers to stop',
                              ' '.join(failed) or stopped['result']['error'])
            return result('stopping', 'Stopping selected containers',
                          'Disk recovery will begin after Docker confirms the selected containers have stopped.')
        failed_mount = bool(probe.get('detached_shutdown_mount') and
                            (probe.get('stale_conflict_only') is True or
                             (not probe.get('detected') and not probe.get('unsafe'))))
        if phase == 'running' and failed_mount:
            return result('running', 'Releasing failed mounts',
                          'Confirming containers are stopped, then normally unmounting failed images and the disk before recovery. '
                          'The app performs these steps automatically.')
        if phase in ('wait1', 'wait2', 'return_failed'):
            if probe.get('detected') is False and deadline and deadline['expired']:
                return result('return_failed', 'Drive return timeout', common.module('return_deadline').failure_message(i))
            if failed_mount and c['recovery']['mount']:
                base['wait_seconds'] = max(0, int(i['due'] - now + .999)) if i.get('boot') == w.boot_id() else None
                return result('waiting', 'Automatic mount recovery scheduled',
                              'The app will verify that selected containers have stopped, unmount the failed images and disk, '
                              'recover and mount the disk, mount selected images, then start the containers. '
                              'No manual unmount command is needed.')
            if i.get('legacy_mount_wait') and not probe.get('healthy') and probe.get('detected'):
                if not c['recovery']['mount']:
                    return result('waiting_manual', 'Automatic recovery is off',
                                  'Selected containers stay stopped. Enable Automatic recovery to allow the app to release failed mounts and recover this disk.')
                return result('waiting', 'Waiting for the mount conflict to be resolved',
                              (probe.get('mount_detail') or probe.get('detail') or 'The configured mount cannot be verified.') +
                              ' An unrelated or unverified mount will not be detached automatically.')
            if stopped and not c['recovery']['mount'] and not probe.get('healthy'):
                return result('waiting_manual', 'Waiting for the disk to be mounted',
                              'Automatic disk mounting is off. Selected containers stay stopped until the disk is mounted; then selected images and containers can be restored.')
            if not probe.get('detected') and c['recovery']['mount']:
                return result('waiting_return', 'Waiting for the disk to return',
                              'Selected containers stay stopped. Recovery will continue when the same disk is detected, including on a different USB port.')
            base['wait_seconds'] = max(0, int(i['due'] - now + .999)) if i.get('boot') == w.boot_id() else None
            return result('waiting', 'Recovery scheduled', 'One recovery sequence is pending. ' +
                          ('Automatic mounting is enabled.' if c['recovery']['mount'] else 'Automatic mounting is disabled; verification only.'))
        application = (i.get('applications') or {}).get('result') or {}
        if phase == 'applications' and application.get('waiting_storage'):
            reasons = [row.get('reason', '') for row in application.get('containers', {}).values()
                       if row.get('status') == 'waiting_storage' and row.get('reason')]
            return result('waiting', 'Waiting for selected storage', ' '.join(reasons) or
                          'Another selected disk or image is unavailable. The container stays stopped until it is mounted.')
        return result(phase, {'running': 'Recovering storage', 'verify': 'Verifying recovery',
                              'applications': 'Mounting selected images and starting containers'}[phase],
                      ('Selected disks and images must be mounted before their containers start. The final email is queued afterward if notifications are enabled.'
                       if phase == 'applications' else 'Recovery is in progress. Success is reported only after storage verification finishes.'))
    if not probe.get('healthy'):
        if state.get('reconnect_pending'):
            return result('confirming', 'New USB connection detected', 'The monitor is confirming this connection before starting a separate recovery incident.')
        if state.get('status') == 'down' and phase in ('done', 'legacy'):
            reason = (i.get('attempts') or [{}])[-1].get('reason', 'Recovery budget is exhausted.')
            return result('failed', 'Recovery failed — attention needed', reason +
                          ' No recovery is running. A new verified attachment may allow another attempt; uncertain storage actions are never repeated automatically.')
        return result('confirming', 'Confirming storage outage', 'Storage is unavailable now; the monitor is checking for a new incident.')
    if state.get('status') != 'up':
        return result('verifying', 'Verifying returned storage', 'Storage is mounted now; the monitor must verify it before re-arming.')
    if (i.get('result', {}).get('main') and phase == 'done' and i.get('connection')
            and i.get('connection') == probe.get('connection')):
        if probe.get('dependent') is False:
            return result('partial', 'Storage recovered; dependent filesystem needs attention',
                          probe.get('dependent_detail') or 'The configured dependent filesystem is unavailable.')
        app = i.get('applications')
        if app and not app.get('result', {}).get('all_verified'):
            return result('partial', 'Storage recovered; applications need attention',
                          'The current filesystem is healthy, but the configured application restart checks did not all complete. '
                          'No further automatic application actions are scheduled for this incident. See its history for details.')
        return result('recovered', 'Recovery successful', 'The current filesystem is healthy and monitoring is armed for the next outage.')
    return result('healthy', 'Storage healthy', 'The current filesystem is healthy and monitoring is armed for the next outage.')


def media_kind(props, rotational=None):
    """Classify from cached hardware evidence; nonrotational alone is ambiguous."""
    if any(v=='1' and (k.startswith('ID_DRIVE_FLASH') or k=='ID_DRIVE_THUMB') for k,v in props.items()):
        return 'flash'
    rpm=props.get('ID_ATA_ROTATION_RATE_RPM','')
    if rpm.isdigit() and int(rpm)>1 and rotational=='1': return 'hdd'
    if (rotational=='1' and not rpm and props.get('ID_ATA')=='1'
            and props.get('ID_WWN') and props.get('ID_SERIAL')):
        return 'hdd'
    if rotational=='0' and (props.get('ID_ATA')=='1' or props.get('ID_NVME')=='1'):
        return 'ssd'
    return 'unknown'


def drive_metadata(c):
    """Passive display metadata; cached values never authorize a disk operation."""
    path=s.STATE_DIR/'drive-display.json'
    try:
        saved=json.loads(path.read_text())
        if saved.get('uuid')!=c['disk']['uuid']: saved={}
    except (OSError,ValueError,AttributeError): saved={}
    try:
        dev=w.device_number('/dev/disk/by-uuid/'+c['disk']['uuid'])
        props=w.udev(dev)
        block=(Path('/sys/dev/block')/dev).resolve(strict=True)
        whole=block.parent if (block/'partition').exists() else block
        hardware=w.udev((whole/'dev').read_text().strip())
        value=dict(uuid=c['disk']['uuid'],model=hardware.get('ID_MODEL',props.get('ID_MODEL',c['disk']['label'])).replace('_',' '),
                   manufacturer=hardware.get('ID_VENDOR',props.get('ID_VENDOR','')).replace('_',' '),
                   label=props.get('ID_FS_LABEL',''),filesystem=props.get('ID_FS_TYPE',''),size=int((whole/'size').read_text())*512)
        try: rotational=(whole/'queue/rotational').read_text().strip()
        except OSError: rotational=None
        value['media_kind']=media_kind(props|hardware,rotational)
        if value!=saved: w.atomic_write(path,json.dumps(value)+'\n')
        return value|dict(cached=False)
    except (OSError,ValueError,w.Unsafe):
        return saved|dict(cached=True) if saved else None


def status():
    c = configuration()
    if c['disk']['uuid']:
        w.configure(c)
    service = service_state()
    state = w.load_state() if c['disk']['uuid'] else {}
    last = None
    if state.get('sample_boot') == w.boot_id() and isinstance(state.get('sample_at'), (int, float)):
        last = datetime.datetime.fromtimestamp(time.time() - (w.clock_now() - state['sample_at']), datetime.timezone.utc).isoformat()
    probe = w.snapshot() if c['disk']['uuid'] else dict(healthy=False, detected=False, detail='Add your USB drive from Overview.', mounts=[])
    disk = None
    locations = []
    if c['disk']['uuid']:
        try:
            dev = w.device_number('/dev/disk/by-uuid/' + c['disk']['uuid'])
            locations = [r['target'] for r in w.read_rows() if r['dev'] == dev]
        except (OSError, ValueError, w.Unsafe):
            pass
    disk=drive_metadata(c) if c['disk']['uuid'] else None
    last_operation=None
    try:
        saved=json.loads((s.STATE_DIR/'manual-operation.json').read_text())
        if saved.get('uuid')==c['disk']['uuid']: last_operation=saved
    except (OSError,ValueError,AttributeError): pass
    return dict(profile_id=s.PROFILE_ID,observed_at=w.timestamp(),last_operation=last_operation,version=s.VERSION, configured=bool(c['disk']['uuid']), disk=c['disk'], discovered=disk,
                deliberate_stopped_apps=common.module('manual_intent').ready_apps(SimpleNamespace(**globals()), c, probe),
                health={k: probe.get(k) for k in ('healthy', 'detected', 'detail', 'dependent', 'dependent_detail')},
                mounted=bool(locations), mounted_expected=c['disk']['mountpoint'] in locations, mount_locations=locations,
                mount_state=probe.get('mount_state', 'unavailable'), mount_detail=probe.get('mount_detail', ''),
                mount_target_occupied=probe.get('mount_target_occupied'),
                usb=w.usb.connection_details(w.usb_context()) if c['disk']['uuid'] else {},
                service=service, last_check=last, queue=len(state.get('pending', [])),
                recovery=c['recovery'] | {'attempts': 1, 'usb': c['usb']['enabled'], 'docker': c['docker']['enabled']},
                images=probe.get('images', []),
                standby=c['standby'] | (w.standby.status(w.usb_context()) if c['disk']['uuid'] else {}),
                monitor=c['monitor'], notifications=c['notifications']['enabled'],
                progress=recovery_progress(c, state, probe, service))


def image_context(owner=None):
    return SimpleNamespace(**vars(preparation_context()),preparation=preparation,owner=owner)


def application_settings(data):
    guard = common.module('app_control')
    with guard.drive_settings(SimpleNamespace(s=s, cli=cli, common=common, w=w), configuration(), guard.requested_identities(data)) as recheck:
        return _application_settings(data, recheck=recheck)


def _application_settings(data, *, recheck):
    if set(data) - {'revision', 'containers', 'enabled', 'services'}:
        raise ValueError('Unknown application setting.')
    if 'enabled' in data and type(data['enabled']) is not bool:
        raise ValueError('Choose whether containers should restart after drive recovery.')
    c=configuration()
    if data.get('revision')!=s.digest(c): raise ValueError('Settings changed. Refresh before saving.')
    selected=None
    if 'containers' in data:
        if not isinstance(data['containers'], list): raise ValueError('Select containers from the discovered list.')
        selected=selected_containers(c,data['containers']) if data['containers'] else []
    with cli.drives.configuration_lock(s):
        recheck()
        if 'containers' in data:
            c['docker']['containers']=selected
            c['docker']['enabled']=bool(c['docker']['containers'])
        if 'enabled' in data: c['docker']['enabled']=data['enabled']
        if 'services' in data: c['services']={'units':data['services']}
        c=s.validate(c)
        if s.digest(configuration())!=data['revision']: raise ValueError('Settings changed during discovery. Refresh before saving.')
        cli.save(s.STATE_DIR/'application-backups'/(str(time.time_ns())+'.json'),configuration())
        cli.save(s.CONFIG,c)
    return dict(message='Container recovery settings saved.',revision=s.digest(c))


def application_status():
    """Container metadata only. Polling never executes commands inside containers."""
    deadline = time.monotonic() + 18
    c = configuration()
    w.configure(c)
    state = w.load_state()
    incident = state.get('incident') or {}
    outcome = (incident.get('applications') or {}).get('result') or {}
    result = dict(enabled=c['docker']['enabled'], containers=[], observed_at=w.timestamp(), service=service_state())
    unavailable = ''
    if c['docker']['containers']:
        try:
            docker_api(c)
            w.apps.configure(c['docker'])
        except (OSError, ValueError, w.apps.AppError, http.client.HTTPException):
            unavailable = 'Docker is unavailable. Last restart results are historical.'
    docker = w.apps.Docker()
    for spec in c['docker']['containers']:
        row = dict(name=spec['name'], source=spec['source'], destination=spec['destination'], state='unknown')
        previous = outcome.get('containers', {}).get(spec['name'], {})
        row['recovery'] = {k: previous[k] for k in ('status', 'reason', 'action', 'action_count', 'attempted_at', 'finished_at') if k in previous}
        row['recovery_time'] = previous.get('finished_at') or outcome.get('finished_at') or incident.get('finished_at')
        try:
            if unavailable or time.monotonic() > deadline:
                raise w.apps.AppError(unavailable or 'Container status deadline reached. Refresh to check again.')
            current = docker.inspect(spec['name'])
            w.apps.validate_container(spec['name'], current)
            row.update(state='dead' if current['dead'] else 'paused' if current['paused'] else
                       'restarting' if current['restarting'] else 'running' if current['running'] else 'stopped',
                       health=current['health'], bind_matches=True)
            row['required_storage'] = w.apps.required_storage_labels(w, current)
        except (OSError, ValueError, KeyError, TypeError, w.apps.AppError) as exc:
            row.update(error=w.apps.safe_error(exc), bind_matches=False)
        result['containers'].append(row)
    return result


def application_check(data):
    """Explicit, bounded read-only preflight. No container lifecycle actions."""
    c = configuration()
    if set(data) != {'revision'} or data['revision'] != s.digest(c):
        raise ValueError('Settings changed. Refresh before checking storage access.')
    if not c['docker']['containers']:
        raise ValueError('Save at least one Docker container before checking storage access.')
    worker = None
    try:
        worker = w.Worker(['/usr/bin/python3', '-I', str(Path(__file__).with_name('engine.py')), '_verify-apps'],
                          {}, 30, directory=s.STATE_DIR)
        done = worker.poll()
        while done is None:
            time.sleep(.1)
            done = worker.poll()
        if worker.timed_out: raise ValueError('Storage access check timed out. No restart was requested.')
        value = w.worker_json(worker)
        if not isinstance(value, dict): raise ValueError('Invalid storage check result.')
        if not done or 'error' in value: raise ValueError(str(value.get('error', 'Storage access could not be verified.'))[:500])
        if set(value) != {v['name'] for v in c['docker']['containers']}:
            raise ValueError('Container selection changed during the storage check. Run it again.')
        if s.digest(configuration()) != data['revision']:
            raise ValueError('Settings changed during the storage check. Run it again.')
        rows = []
        for spec in c['docker']['containers']:
            item = value[spec['name']]
            if (not isinstance(item, dict) or type(item.get('running')) is not bool
                    or item.get('source') != spec['source'] or item.get('destination') != spec['destination']):
                raise ValueError('Invalid container storage check result.')
            verified = isinstance(item.get('verification'), dict) and item['verification'].get('inside_access') is True
            if item['running'] and not verified: raise ValueError('Inside-container storage access was not verified.')
            rows.append(dict(name=spec['name'], verified=verified,
                             message='Storage access verified.' if verified else 'Stopped container preserved; access was not tested.'))
        return dict(containers=rows, observed_at=w.timestamp(), message='Storage access check finished. No containers were restarted.')
    finally:
        if worker is not None:
            worker.cancel()
            worker.close()


def timing_settings(data):
    c=configuration()
    if data.get('revision')!=s.digest(c): raise ValueError('Settings changed. Refresh before saving.')
    allowed={'monitor':('interval','observations','boot_grace'),'recovery':('wait','worker_timeout','return_timeout_minutes'),
             'usb':('enumeration_seconds','disable_seconds'),'docker':('health_timeout','worker_timeout')}
    for group,values in data.get('timings',{}).items():
        if group not in allowed or not isinstance(values,dict) or set(values)-set(allowed[group]): raise ValueError('Unknown timing setting.')
        c[group].update(values)
    c=s.validate(c)
    with migration.exclusive(migration_context()): cli.save(s.CONFIG,c)
    return dict(message='Timing settings saved.',revision=s.digest(c))


def network_configuration():
    try:
        value=json.loads(common.WEB_CONFIG.read_text())
        return common.network_config(value)
    except (OSError,ValueError):return dict(common.DEFAULT)


def network_manager():
    global NETWORK_MANAGER
    if NETWORK_MANAGER is None:
        NETWORK_MANAGER = networking.Manager(networking.Context(SimpleNamespace(**globals())))
    return NETWORK_MANAGER


def network_state():
    manager = network_manager()
    c = manager.c.config()
    addresses = manager.c.addresses()
    listener = manager.follower.public(c, addresses)
    return dict(config=c, url=listener.get('url'), listener=listener,
                local_url=networking.url(c, True), addresses=addresses,
                transaction=manager.status(), certificate=manager.c.certificate_info(),
                recovery_error=getattr(manager, 'recovery_error', ''))


def network_action(action, data, request):
    manager = network_manager()
    if getattr(manager, 'recovery_error', ''):
        raise ValueError(manager.recovery_error)
    if not manager.lock.acquire(blocking=False):
        raise ValueError('A network listener is still being checked. Wait for its status before changing settings.')
    try:
        if action == 'network-stage':
            return manager.stage(data)
        if action == 'network-certificate':
            if data: raise ValueError('Certificate preparation accepts no parameters.')
            manager.ensure_idle()
            return manager.c.prepare_certificate()
        if action == 'network-renew':
            if data: raise ValueError('Certificate renewal accepts no parameters.')
            return manager.renew()
        if set(data) != {'operation'} or not isinstance(data['operation'], str):
            raise ValueError('Choose the current network test.')
        if action == 'network-confirm':
            return manager.confirm(data['operation'], request.get('origin'))
        return manager.cancel(data['operation'])
    finally:
        manager.lock.release()


private_network_address=common.private_network_address


def network_url(value):
    return value.get('scheme','https')+'://'+value['hostname']+':'+str(value['port']) if value['lan'] else 'http://localhost:8765'


def lan_info():
    state=network_state();result=state['addresses'];configured=state['config'];scheme=configured['scheme']
    cert=common.WEB_DIR/'local-network-ca.pem'
    available=bool(state['url'])
    certificate=cert.read_text() if cert.exists() else '';fingerprint=''
    if certificate:
        try:
            digest=hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate)).hexdigest().upper()
            fingerprint='SHA256 Fingerprint='+':'.join(digest[i:i+2] for i in range(0,len(digest),2))
        except ValueError:certificate=''
    return dict(addresses=result,certificate=certificate,fingerprint=fingerprint,enabled=configured.get('lan') is True,
                available=available,scheme=scheme,address=configured['address'],url=state['url'],
                message=state['listener']['message'],operation=lan_status())


def lan_auto(data):
    if data.get('confirm') is not True: raise ValueError('Confirm local network access first.')
    if data.get('enabled') is False: return network(dict(enabled=False,confirm=True))
    available=lan_info()['addresses'];address=data.get('address')
    if address not in [item['address'] for item in available]: raise ValueError('Choose one of this computer’s current local network addresses.')
    scheme=data.get('scheme','https')
    if scheme=='http':
        return network(dict(enabled=True,confirm=True,address=address,hostname=address,scheme='http',acknowledge_http=data.get('acknowledge_http')))
    if scheme!='https':raise ValueError('Choose HTTP or HTTPS in Technical network settings.')
    current=network_configuration()
    if current.get('address')==address and (common.WEB_DIR/'certificate.pem').exists() and (common.WEB_DIR/'key.pem').exists():
        return network(dict(enabled=True,confirm=True,address=address,hostname=current['hostname'],scheme='https',
            certificate=(common.WEB_DIR/'certificate.pem').read_text(),key=(common.WEB_DIR/'key.pem').read_text(),
            local_ca=(common.WEB_DIR/'local-network-ca.pem').read_text() if (common.WEB_DIR/'local-network-ca.pem').exists() else None))
    with tempfile.TemporaryDirectory(prefix='usw-lan-',dir=s.STATE_DIR) as directory:
        root=Path(directory);ca=root/'ca.pem';key=root/'ca-key.pem';cert=root/'server.pem';private=root/'server-key.pem';csr=root/'server.csr'
        # A dedicated local CA allows another device to trust this HTTPS listener.
        # CA and server private keys never leave the administrator-owned directory.
        command(['/usr/bin/openssl','req','-x509','-newkey','rsa:3072','-nodes','-days','3650','-subj','/CN=USB Storage Watch Local Network',
                 '-keyout',str(key),'-out',str(ca),'-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign'],30)
        command(['/usr/bin/openssl','req','-new','-newkey','rsa:3072','-nodes','-subj','/CN='+address,'-keyout',str(private),'-out',str(csr)],30)
        extensions=root/'extensions';extensions.write_text('subjectAltName=IP:'+address+'\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
        command(['/usr/bin/openssl','x509','-req','-in',str(csr),'-CA',str(ca),'-CAkey',str(key),'-CAcreateserial','-days','365','-sha256',
                 '-extfile',str(extensions),'-out',str(cert)],30)
        fingerprint=command(['/usr/bin/openssl','x509','-in',str(ca),'-noout','-fingerprint','-sha256']).strip()
        result=network(dict(enabled=True,confirm=True,address=address,hostname=address,certificate=cert.read_text()+ca.read_text(),key=private.read_text(),local_ca=ca.read_text()))
        return result|dict(certificate=ca.read_text(),fingerprint=fingerprint)


def network(data):
    if data.get('confirm') is not True:
        raise ValueError('Explicit confirmation is required to change network access.')
    if data.get('enabled') is False:
        value = dict(network_configuration(),lan=False)
        if 'scheme' in data:
            if data['scheme'] not in ('http','https'):raise ValueError('Choose HTTP or HTTPS.')
            value['scheme']=data['scheme']
    elif data.get('enabled') is True:
        scheme=data.get('scheme','https')
        if scheme not in ('http','https'):raise ValueError('Choose HTTP or HTTPS.')
        address, hostname = data.get('address', ''), data.get('hostname', '')
        try:
            ip = ipaddress.IPv4Address(address)
        except (ValueError, TypeError):
            raise ValueError('Choose an assigned private IPv4 address.') from None
        if not private_network_address(str(ip)):
            raise ValueError('LAN access requires a private IPv4 address, never a wildcard or public address.')
        if not isinstance(hostname, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}', hostname):
            raise ValueError('Enter a valid local connection hostname.')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((address, 0))  # Requires this address to belong to this machine.
        if scheme=='http':
            if data.get('acknowledge_http') is not True:raise ValueError('Acknowledge that LAN HTTP exposes login tokens and commands before enabling it.')
            if not auth.management_configured((s.CONFIG if s.PROFILE_ID=='legacy' else s.CONFIG_ROOT/'config.json').with_name('management-token.json'),s.STATE_DIR if s.PROFILE_ID=='legacy' else s.STATE_ROOT):raise ValueError('Create your application management token before enabling LAN HTTP.')
            value=dict(common.DEFAULT,lan=True,address=address,hostname=address,scheme='http')
            return queue_network(value,{'config.json':json.dumps(value)+'\n'})
        certificate, key = data.get('certificate', ''), data.get('key', '')
        if not all(isinstance(v, str) and 0 < len(v) < 20000 for v in (certificate, key)):
            raise ValueError('Upload a PEM certificate chain and unencrypted private key.')
        with tempfile.TemporaryDirectory(prefix='usw-tls-', dir=s.STATE_DIR) as directory:
            cert, private = Path(directory) / 'certificate.pem', Path(directory) / 'key.pem'
            cert.write_text(certificate); private.write_text(key)
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(cert, private, password=lambda: '')
                check = '-checkip' if re.fullmatch(r'[0-9.]+', hostname) else '-checkhost'
                matched = command(['/usr/bin/openssl', 'x509', '-in', str(cert), check, hostname, '-noout'])
                # OpenSSL x509 exits zero even when -checkhost reports a mismatch.
                if not matched.strip().endswith(' does match certificate'):
                    raise ValueError('Certificate hostname mismatch')
                command(['/usr/bin/openssl', 'x509', '-in', str(cert), '-checkend', '86400', '-noout'])
                dates = command(['/usr/bin/openssl', 'x509', '-in', str(cert), '-startdate', '-noout'])
                if ssl.cert_time_to_seconds(dates.strip().removeprefix('notBefore=')) > time.time():
                    raise ValueError('Certificate is not yet valid')
            except (OSError, ssl.SSLError, ValueError):
                raise ValueError('TLS certificate/key invalid, mismatched, expiring, or missing the requested hostname.') from None
        value = dict(common.DEFAULT, lan=True, address=address, hostname=hostname,scheme='https')
    else:
        raise ValueError('Choose whether to enable LAN access.')
    files={'config.json':json.dumps(value)+'\n'}
    if value['lan'] and value.get('scheme','https')=='https':
        files.update({'certificate.pem':certificate,'key.pem':key,'local-network-ca.pem':data.get('local_ca')})
    return queue_network(value,files)


def lan_status():
    try:
        value=json.loads((s.STATE_DIR/'lan-operation.json').read_text())
        if value.get('phase')=='applying' and not NETWORK_LOCK.locked():
            return value|dict(phase='failed',message='The LAN change was interrupted. Check LAN settings from http://localhost:8765; local HTTP remains available.')
        return value
    except (OSError,ValueError): return dict(phase='idle',message='No LAN change is in progress.')


def lan_ready(value,certificate=None):
    """Verify the listener response; HTTPS additionally verifies its exact certificate."""
    if value['address'] != '127.0.0.1' and value['address'] not in [v['address'] for v in common.module('network_addresses').discover(command)]:
        raise ValueError('The listener address is not assigned locally; no connection probe was sent.')
    def response(connection):
        connection.sendall(('GET / HTTP/1.1\r\nHost: '+value['hostname']+':'+str(value['port'])+'\r\nConnection: close\r\n\r\n').encode())
        reply=http.client.HTTPResponse(connection)
        try:
            reply.begin()
            expected=value.get('scheme','https')+'://'+value['address']+':'+str(value['port'])
            if reply.status!=200 or reply.getheader('X-USW-Listener')!=expected:
                raise ValueError('The expected Storage Watch listener did not respond successfully.')
        except http.client.HTTPException:
            raise ValueError('The network listener returned an invalid HTTP response.') from None
        finally: reply.close()
    if value.get('scheme','https')=='http':
        with socket.create_connection((value['address'],value['port']),timeout=2) as connection:
            response(connection)
        return
    context=ssl.create_default_context()
    context.load_verify_locations(cadata=certificate)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    expected=ssl.PEM_cert_to_DER_cert(certificate.split('-----END CERTIFICATE-----')[0]+'-----END CERTIFICATE-----')
    with socket.create_connection((value['address'],value['port']),timeout=2) as connection:
        with context.wrap_socket(connection,server_hostname=value['hostname']) as secure:
            if secure.getpeercert(binary_form=True)!=expected: raise ValueError('Unexpected LAN listener certificate.')
            response(secure)


def apply_network(value,files,operation):
    paths=[common.WEB_DIR/name for name in ('config.json','certificate.pem','key.pem','local-network-ca.pem')]
    before={};gid=None
    def record(phase,message):
        w.atomic_write(s.STATE_DIR/'lan-operation.json',json.dumps(dict(operation=operation,phase=phase,message=message,url=network_url(value),enabled=value['lan'],scheme=value.get('scheme','https'),time=w.timestamp()))+'\n')
    def restore():
        for path,saved in before.items():
            if saved is None: path.unlink(missing_ok=True)
            else:
                w.atomic_write(path,saved[0].decode(),mode=saved[1]);os.chown(path,0,gid)
    try:
        gid=pwd.getpwnam('usb-storage-watch-web').pw_gid
        before={path:(path.read_bytes(),path.stat().st_mode & 0o777) if path.exists() else None for path in paths}
        for name,content in files.items():
            path=common.WEB_DIR/name
            if content is None: path.unlink(missing_ok=True)
            else: w.atomic_write(path,content,mode=0o640);os.chown(path,0,gid)
        if value['lan']:
            command(['/usr/bin/systemctl','restart',LAN_SERVICE],35)
            deadline=time.monotonic()+8
            while True:
                try: lan_ready(value,files.get('certificate.pem'));break
                except (OSError,ValueError):
                    if time.monotonic()>=deadline: raise ValueError('The LAN listener did not become ready with the selected protocol and verified settings.') from None
                    time.sleep(.2)
            command(['/usr/bin/systemctl','enable',LAN_SERVICE])
        else:
            command(['/usr/bin/systemctl','disable','--now',LAN_SERVICE],35)
            stopped = dict(line.split('=',1) for line in command(['/usr/bin/systemctl','show',LAN_SERVICE,'--property=ActiveState,MainPID']).splitlines() if '=' in line)
            if stopped.get('ActiveState') not in ('inactive','failed') or stopped.get('MainPID') != '0':
                raise ValueError('LAN listener did not stop.')
        record('complete','LAN '+value.get('scheme','https').upper()+' enabled and verified. Local HTTP remains available.' if value['lan'] else 'LAN access disabled. Local HTTP remains available.')
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:
        rollback='Previous LAN configuration restored.'
        try:
            if before:
                restore()
                try: previous=json.loads(before[common.WEB_CONFIG][0]) if before[common.WEB_CONFIG] else common.DEFAULT
                except ValueError: previous=common.DEFAULT
                command(['/usr/bin/systemctl','enable' if previous.get('lan') else 'disable',LAN_SERVICE])
                command(['/usr/bin/systemctl','restart' if previous.get('lan') else 'stop',LAN_SERVICE],35)
        except (OSError,ValueError,subprocess.SubprocessError): rollback='LAN could not be restored; review it from localhost.'
        record('failed',str(exc)+' '+rollback+' Local HTTP was not changed.')
    finally: NETWORK_LOCK.release()


def queue_network(value,files):
    if not NETWORK_LOCK.acquire(blocking=False): raise ValueError('A LAN change is already running. Wait for its result.')
    operation=__import__('secrets').token_hex(16)
    try:
        w.atomic_write(s.STATE_DIR/'lan-operation.json',json.dumps(dict(operation=operation,phase='applying',enabled=value['lan'],scheme=value.get('scheme','https'),message='Applying LAN settings. Local HTTP remains available.'))+'\n')
        # Give even a request over the old LAN connection time to receive its receipt.
        timer=threading.Timer(.5,apply_network,args=(value,files,operation));timer.daemon=True;timer.start()
    except Exception:
        NETWORK_LOCK.release();raise
    return dict(operation=operation,pending=True,message='Applying LAN settings. Local HTTP remains available.',
                url=network_url(value))


def monitor_control(data):
    if data.get('enabled') is True:
        if migration.pending(migration_context()):
            raise FieldError('mountpoint', 2, 'A mount location change is unfinished. Continue it in Change mount location or use Roll back location change before enabling monitoring.')
        c = s.read()
        row = next((r for r in disks() if r['uuid'] == c['disk']['uuid'] and r['eligible']), None)
        if c['recovery']['mount'] and row is not None:
            try:
                mount_plan(c, row, [])
            except ValueError as exc:
                raise FieldError('mountpoint', 2, 'Settings are saved, but monitoring was not enabled. ' + str(exc)) from None
        if c['notifications']['enabled']:
            n.load_config()
        w.configure(c)
        if c['recovery']['mount']:
            w.fstab_check(w.MOUNT)
        command(['/usr/bin/systemctl', 'enable', '--now', cli.SERVICE], 30)
    elif data.get('enabled') is False:
        command(['/usr/bin/systemctl', 'disable', '--now', cli.SERVICE], 35)
    else:
        raise ValueError('Choose whether to enable monitoring.')
    observed = service_state()
    if data['enabled'] and observed.get('ActiveState') != 'active':
        raise ValueError('Settings are saved, but monitoring is not active. Check the service journal in Advanced settings and try Enable monitoring again.')
    return {'message': 'Monitoring enabled at startup.' if data['enabled'] else 'Monitoring stopped and disabled at startup.',
            'service': observed}


class Broker:
    def __init__(self, history, sessions=None):
        self.prepare_worker=None
        self.request_lock=threading.RLock()
        self.fleet=drive_web.Fleet(lambda:SimpleNamespace(**globals()),self) if s.PROFILE_ID=='legacy' else None
        self.history = history
        self.sessions = sessions or auth.Sessions()

    def record_manual(self,label,outcome,detail):
        """Record meaningful user-initiated operations, not polling and routine checks.

        An audit failure must not turn a completed disk operation into a claimed
        failure; callers receive a separate warning when history is unavailable.
        """
        name=('Manual '+label+' — '+outcome).strip()[:190]
        try:
            self.history.record('manual:'+uuid.uuid4().hex,w.timestamp(),name,[str(detail or '')[:1000]])
            return None
        except (sqlite3.Error,OSError,ValueError):
            return 'The operation result could not be saved to event history.'

    def manual_action(self,label,callback):
        try:
            result=callback()
        except (ValueError,w.Unsafe,w.apps.AppError) as exc:
            self.record_manual(label,'Refused',str(exc))
            raise
        except (OSError,subprocess.SubprocessError):
            self.record_manual(label,'Failed','The host operation could not complete safely.')
            raise
        if not isinstance(result,dict):return result
        ok=result.get('ok') is not False
        warning=self.record_manual(label,'Successful' if ok else 'Failed',result.get('message',''))
        if warning:return result|dict(history_warning=warning)
        return result

    def start_preparation(self,chosen,data):
        preparation.confirm(chosen,data)
        self.prepare_progress()
        if self.prepare_worker is not None: raise ValueError('Formatting is already in progress.')
        chosen=dict(chosen,operation=__import__('secrets').token_hex(16))
        initial=dict(operation=chosen['operation'],device=chosen['disk']['device'],name=chosen.get('name',''),
                     phase='preparing',message='Stopping monitoring and rechecking the selected disk.')
        preparation.record(preparation_context(),initial)
        try:
            self.prepare_worker=w.Worker(['/usr/bin/python3','-I',str(Path(__file__).with_name('web_prepare.py')),'_prepare'],
                                         dict(chosen=chosen,data=data),300,directory=s.STATE_DIR)
        except Exception:
            preparation.record(preparation_context(),initial|dict(phase='failed',message='The formatting worker could not start. No formatting command was sent.'))
            raise
        return dict(operation=chosen['operation'],pending=True,message='Preparing the selected disk.')

    def prepare_progress(self):
        worker=self.prepare_worker
        if worker is not None:
            done=worker.poll()
            if done is not None:
                try:
                    try: result=w.worker_json(worker) if done else dict(ok=False,error='Formatting worker stopped or timed out. Review the drive; do not automatically retry.')
                    except (OSError,ValueError):result=dict(ok=False,error='The formatting worker returned no valid result. Review the drive before proceeding.')
                    if not result.get('ok'):
                        old=preparation.status(preparation_context()) or {}
                        preparation.record(preparation_context(),old|dict(phase='failed',message=result.get('error','Formatting did not complete.')))
                finally:
                    worker.cancel();worker.close();self.prepare_worker=None
        value=preparation.status(preparation_context()) or dict(phase='idle',message='No formatting operation is in progress.')
        if self.prepare_worker is None and value['phase'] in ('preparing','formatting','mounting','verifying','erasing','formatted'):
            value=value|dict(phase='failed',message='The previous operation was interrupted. Review the disk before proceeding; no automatic retry will run.')
        return value

    def dispatch(self, request):
        action, write, data = request.get('action'), request.get('write'), request.get('data', {})
        if not isinstance(data, dict) or type(write) is not bool:
            raise ValueError('Invalid request.')
        retired=s.CONFIG.with_name('removed-drive.json').exists()
        if action=='login-info' and not write:
            return dict(token_configured=auth.management_configured((s.CONFIG if s.PROFILE_ID=='legacy' else s.CONFIG_ROOT/'config.json').with_name('management-token.json'),s.STATE_DIR if s.PROFILE_ID=='legacy' else s.STATE_ROOT),bootstrap=request.get('local') is True)
        if action == 'login' and write:
            if set(data)=={'management_token'}:
                return self.sessions.token_login(data['management_token'],lambda value:auth.verify_management_token((s.CONFIG if s.PROFILE_ID=='legacy' else s.CONFIG_ROOT/'config.json').with_name('management-token.json'),value,s.STATE_DIR))
            if request.get('local') is not True:
                raise auth.Denied('Use localhost to set up or recover your application management token.')
            return self.sessions.login(data.get('username'), data.get('password'))
        if action not in (WRITES if write else READS):
            raise ValueError('Unknown or disallowed operation.')
        session = self.sessions.check(request.get('token'), request.get('csrf'), write)
        if retired and action not in drive_web.GLOBAL:
            raise ValueError('This drive was removed from Storage Watch. Refresh the overview.')
        if action == 'session':
            return {key: session[key] for key in ('username', 'csrf')} | dict(token_configured=auth.management_configured((s.CONFIG if s.PROFILE_ID=='legacy' else s.CONFIG_ROOT/'config.json').with_name('management-token.json'),s.STATE_DIR if s.PROFILE_ID=='legacy' else s.STATE_ROOT))
        if action == 'network-state': return network_state()
        if action in NETWORK_WRITES: return network_action(action, data, request)
        if action in ('network', 'lan-auto'):
            raise ValueError('Reload the dashboard and use Apply network settings to test and confirm the new connection.')
        if write and self.prepare_worker is not None and action not in ('logout','smtp','test-email'):
            self.prepare_progress()
            if self.prepare_worker is not None: raise ValueError('Formatting is in progress. Wait until verification finishes.')
        if action == 'logout':
            self.sessions.logout(request['token']); return {'message': 'Signed out.'}
        if action=='management-token':
            if data!={'confirm':True}:raise ValueError('Confirm creating or replacing the management token.')
            try:token=auth.rotate_management_token(s.STATE_DIR,session['username'])
            finally:
                # A durable replace may succeed before a later fsync/marker error.
                # Explicit rotation always retires sessions, even on that failure.
                self.sessions.sessions.clear()
            return dict(management_token=token,message='Management token replaced. Retrieve it with sudo cat /var/lib/usb-storage-watch/management.token. Previous management tokens, including DEV6 credentials, and all sessions are revoked. Connect again with the new token.')
        if action=='local-accounts':return images.local_accounts()
        if action == 'image-discover':
            return images.discover(image_context())
        if action == 'application-images':
            account=pwd.getpwnam(session['username'])
            return dict(images=images.entries(image_context((account.pw_uid,account.pw_gid))))
        if action == 'folder-access-plan':
            c=configuration();w.configure(c)
            item=next((v for v in s.storage_images(c,False) if v['uuid']==data.get('uuid')),None)
            if item is None and data.get('uuid')!=c['disk']['uuid']:raise ValueError('Select the configured storage folder.')
            account=pwd.getpwnam(session['username']);owner=(account.pw_uid,account.pw_gid)
            policy=images.access_policy(data.get('permissions'),owner)
            chosen=images.permission_plan(image_context(owner),item,owner,policy);session['folder_access'+('' if s.PROFILE_ID=='legacy' else ':'+s.PROFILE_ID)]=chosen
            return dict(token=chosen['token'],path=chosen['path'],changes=[dict(path=v['path'],rights=v['rights']) for v in chosen['targets']])
        if action == 'folder-access-apply':
            return images.permission_apply(image_context(),session.pop('folder_access'+('' if s.PROFILE_ID=='legacy' else ':'+s.PROFILE_ID),None),data)
        if action == 'image-plan':
            session.pop('image_plan'+('' if s.PROFILE_ID=='legacy' else ':'+s.PROFILE_ID),None)
            chosen=images.plan(image_context(),data)
            account=pwd.getpwnam(session['username']);chosen['owner']=(account.pw_uid,account.pw_gid)
            chosen['permissions']=images.access_policy(data.get('permissions'),chosen['owner'])
            session['image_plan'+('' if s.PROFILE_ID=='legacy' else ':'+s.PROFILE_ID)]=chosen
            return images.public(chosen)
        if action == 'image-apply':
            return self.manual_action('virtual disk image registration',lambda:images.apply(image_context(),session.pop('image_plan'+('' if s.PROFILE_ID=='legacy' else ':'+s.PROFILE_ID),None),data))
        if action == 'image-action':
            verb={'mount':'virtual disk mount','unmount':'virtual disk unmount','remove':'virtual disk registration removal','set-recovery':'virtual disk automatic mount preference'}.get(data.get('action'),'virtual disk operation')
            return self.manual_action(verb,lambda:images.manage(image_context(),data))
        if action == 'application-settings': return application_settings(data)
        if action == 'application-status': return application_status()
        if action == 'application-check': return application_check(data)
        if action == 'timing-settings': return timing_settings(data)
        if action == 'lan-info': return lan_info()
        if action == 'lan-status': return lan_status()
        if action == 'lan-auto':
            return lan_auto(data)
        if action == 'prepare-progress': return self.prepare_progress()
        if action == 'prepare-disks':
            return dict(disks=preparation.inventory(preparation_context()),
                        previous=self.prepare_progress())
        if action == 'prepare-drive-plan':
            session.pop('prepare_drive'+('' if s.PROFILE_ID=='legacy' else ':'+s.PROFILE_ID), None)
            chosen = preparation.plan(preparation_context(), data)
            account = pwd.getpwnam(session['username'])
            chosen['owner'] = (account.pw_uid, account.pw_gid)
            session['prepare_drive'+('' if s.PROFILE_ID=='legacy' else ':'+s.PROFILE_ID)] = chosen
            return preparation.public_plan(chosen)
        if action == 'prepare-drive':
            # Consume consent before touching storage, including failed attempts.
            chosen = session.pop('prepare_drive'+('' if s.PROFILE_ID=='legacy' else ':'+s.PROFILE_ID), None)
            return self.start_preparation(chosen,data)
        if action == 'prepare-drive-activate':
            return preparation.activate(preparation_context(), data)
        if action == 'unmount-plan':
            return common.module('manual_unmount').review(SimpleNamespace(**globals()), data, session)
        if action == 'disk-operation':
            if data.get('action') == 'unmount':
                return self.manual_action('drive unmount', lambda: common.module('manual_unmount').apply(
                    SimpleNamespace(**globals()), data, session,
                    lambda fds: disk_operation(dict(action='unmount', uuid=data['uuid']), reviewed=True, lock_fds=fds)))
            verb={'mount':'drive mount','unmount':'drive unmount','reconnect':'USB port reconnect','sleep':'HDD standby request'}.get(data.get('action'),'drive operation')
            return self.manual_action(verb,lambda:disk_operation(data))
        if action in ('standby-settings', 'advanced-recovery', 'protection-settings','notification-settings'):
            labels={'standby-settings':'automatic HDD standby settings','notification-settings':'email notification preference','protection-settings':'automatic recovery setting','advanced-recovery':'advanced recovery settings'}
            return self.manual_action(labels[action],lambda:update_options(action, data))
        if action == 'recovery-plan':
            return protection.recovery_plan(protection_context(),data)
        if action == 'recovery-settings':
            return self.manual_action('automatic recovery setting',lambda:protection.recovery_settings(protection_context(),data))
        if action == 'drive-activity':
            c=configuration();w.configure(c)
            if not c['disk']['uuid']: raise ValueError('Select a configured drive first.')
            return w.standby.io.observe(w.usb_context())
        if action == 'status':
            return status()
        if action == 'usb-status':
            c = configuration()
            if not c['disk']['uuid']:
                return dict(message='Select a drive to inspect its USB connection.')
            w.configure(c)
            return w.usb.connection_details(w.usb_context())
        if action == 'global-config':
            return dict(smtp=smtp_public(),network=network_configuration(),
                        management_transition=auth.management_transition(s.CONFIG.with_name('management-token.json'),s.STATE_DIR),
                        management_token=auth.management_configured(s.CONFIG.with_name('management-token.json'),s.STATE_DIR))
        if action == 'config':
            if write:
                return save_configuration(data)
            c = configuration()
            return dict(config=c, revision=s.digest(c), smtp=smtp_public(),management_transition=auth.management_transition((s.CONFIG if s.PROFILE_ID=='legacy' else s.CONFIG_ROOT/'config.json').with_name('management-token.json'),s.STATE_DIR if s.PROFILE_ID=='legacy' else s.STATE_ROOT),management_token=auth.management_configured((s.CONFIG if s.PROFILE_ID=='legacy' else s.CONFIG_ROOT/'config.json').with_name('management-token.json'),s.STATE_DIR if s.PROFILE_ID=='legacy' else s.STATE_ROOT), network=network_configuration(),
                        defaults={group:{key:value for key,value in s.DEFAULT[group].items() if type(value) in (int,float)} for group in ('monitor','recovery','usb','docker','standby')},
                        environment=virtualization(), service=service_state(), migration=migration.public(migration_context()))
        if action == 'mount-plan':
            return inspect_mount(data.get('uuid'))
        if action == 'protection-plan':
            if data.get('automatic') not in ('true', 'false'):
                raise ValueError('Choose whether to reconnect automatically.')
            return protection.plan(protection_context(), data.get('uuid'), data['automatic'] == 'true')
        if action == 'activate-protection':
            return protection.activate(protection_context(), data)
        if action == 'prepare-mount':
            return prepare_mount(data)
        if action in ('migration-plan', 'migrate-mount', 'rollback-mount'):
            try:
                context = migration_context()
                if action == 'migration-plan':
                    proposal = migration.plan(context, data.get('uuid'), data.get('mountpoint'))
                    return {key: value for key, value in proposal.items() if key != 'replacement'}
                if action == 'migrate-mount':
                    return migration.prepare(context, data)
                return migration.rollback(context, data)
            except ValueError as exc:
                raise FieldError('mountpoint', 2, str(exc)) from None
        if action == 'change-mount-location':
            c = configuration()
            if data.get('uuid') != c['disk']['uuid'] or not data.get('mountpoint'):
                raise ValueError('Selected drive changed. Refresh before changing its mount location.')
            cli.stopped()
            row = target(c['disk']['uuid'])
            if row['mountpoint']:
                raise ValueError('Use Unmount safely before changing the mount location.')
            w.configure(c)
            dev = w.device_number('/dev/disk/by-uuid/' + c['disk']['uuid'])
            w.mount_available(w.read_rows(), w.MOUNT, dev)
            context = migration_context()
            migration.prepare(context, data)
            c['disk']['mountpoint'] = data['mountpoint']
            migration.commit(context, s.validate(c))
            result = disk_operation(dict(action='mount', uuid=c['disk']['uuid']))
            return self.manual_action('mount location change',lambda:result | dict(message='Mount location saved. ' + result['message']))
        if action == 'validate':
            return save_configuration(data, validate_only=True)
        if action == 'disks':
            return {'disks': disks()}
        if action == 'docker':
            c = configuration()
            if data.get('uuid'):
                row = target(data['uuid'])
                c['disk'].update(uuid=row['uuid'], mountpoint=row['mountpoint'] or '/mnt/usb-storage-watch')
            return {'containers': container_rows(c)}
        if action == 'smtp':
            cli.save(s.SMTP, prepare_smtp(data))
            return {'message': 'Email settings saved. The password is stored privately.'}
        if action == 'test-email':
            n.load_config()
            ok, detail = n.bounded_send(n.test_payload())
            return dict(accepted=ok, message=detail)
        if action == 'monitor':return self.manual_action('monitoring '+('started' if data.get('enabled') else 'stopped'),lambda:monitor_control(data))
        if action == 'events':
            return {'events': self.history.events()}
        if action == 'diagnostics':
            c = configuration()
            lines = command(['/usr/bin/journalctl', '-u', cli.SERVICE, '--no-pager', '-n', '80', '-o', 'cat'])
            return dict(version=s.VERSION, journal=lines[-18000:], qualified=bool(c['usb']['profile'] and c['usb']['profile']['qualified']),
                        usb_explanation='Software reconnect requires a verified isolated direct root port. Discovery is read-only; electrical power cycling is not verified.',
                        dependent=c['dependent'], images=len(s.storage_images(c)), docker_api=c['docker']['api'])
        if action == 'qualify':
            cli.stopped()
            environment = virtualization()
            if environment['kind'] == 'virtual':
                raise ValueError('Virtualization detected (' + environment['name'] + '). Physical USB port safety cannot be established here. Leave port resetting off; normal automatic remounting remains available.')
            if not configuration()['disk']['uuid']:
                raise ValueError('No disk configuration has been saved. Finish Setup with USB port resetting off, then check hardware support for that disk in Advanced settings. Normal automatic remounting does not need USB qualification.')
            profile = cli.bounded_candidate()
            if data.get('attestation') != 'QUALIFIED':
                if data:
                    raise ValueError('Type QUALIFIED only after completing independent offline qualification.')
                return {'supported': True, 'message': 'Topology supports a candidate. Complete independent offline qualification before attesting.'}
            c = s.read()
            profile.update(qualified=True, qualification=dict(date=data.get('date'), evidence=data.get('evidence'),
                           isolated_port=True, reenable_verified=True, expected_disk_returned=True))
            c['usb']['profile'] = profile
            s.validate(c); cli.save(s.CONFIG, c)
            return {'supported': True, 'message': 'Qualification saved. Enable USB recovery separately in Setup.'}
        if action == 'network':
            return network(data)
        raise ValueError('Unsupported operation.')

    def handle(self, request):
        try:
            if self.fleet:
                result=self.fleet.route(request)
                if result is not None:return result
            return self.exclusive_handle(request)
        except auth.Denied as exc:return {'status':401,'error':str(exc)}
        except (ValueError,w.Unsafe) as exc:return {'status':400,'error':str(exc)}
        except (OSError,KeyError,TypeError):return {'status':503,'error':'Drive operation unavailable. Other monitors continue independently.'}

    def exclusive_handle(self, request):
        # Do not accumulate web threads behind a long drive operation. The
        # caller gets a definite refusal; mutations are never queued/retried.
        if not self.request_lock.acquire(timeout=0.5):
            return {'status': 409, 'error': 'An operation is already running for this drive. Wait for it to finish.'}
        try:
            return self.local_handle(request)
        finally:
            self.request_lock.release()

    def local_handle(self, request):
        try:
            value=self.dispatch(request)
            return {'status':200,'data':value}
        except auth.Denied as exc:
            return {'status': 401, 'error': str(exc)}
        except protection.Problem as exc:
            return {'status': 400, 'error': str(exc), 'field': exc.field, 'action': exc.action}
        except FieldError as exc:
            return {'status': 400, 'error': str(exc)[:1000], 'field': exc.field, 'step': exc.step}
        except (ValueError, w.Unsafe, w.apps.AppError) as exc:
            # SMTP input validation and daemon bodies are sanitized at source.
            return {'status': 400, 'error': str(exc)[:500]}
        except (OSError, subprocess.SubprocessError, KeyError, TypeError, sqlite3.Error):
            return {'status': 503, 'error': 'Operation could not complete safely. Check configuration and service availability.'}


class BrokerServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Keep accepting requests even while background history is unavailable."""
    daemon_threads = True
    block_on_close = False
    request_queue_size = 32

    def __init__(self, *args, broker, history, **kwargs):
        self.broker, self.history = broker, history
        self.next_observation = self.next_capture = 0
        self.observer = None
        self.warning_times = {}
        self.request_slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def warn(self, operation, error):
        now = time.monotonic()
        if now < self.warning_times.get(operation, 0):
            return
        self.warning_times[operation] = now + 30
        # Error types and errno aid diagnostics without printing paths, request
        # bodies, tokens, credentials or database content.
        code = getattr(error, 'errno', None)
        print(f'Administration {operation} unavailable ({type(error).__name__}, errno={code}); '
              'drive monitoring continues independently.', flush=True)

    def get_request(self):
        try:
            return super().get_request()
        except OSError as exc:
            self.warn('accept', exc)
            if exc.errno in (errno.EMFILE, errno.ENFILE, errno.ENOBUFS, errno.ENOMEM):
                # A readable listening socket plus EMFILE otherwise causes
                # socketserver to spin, starving cleanup and flooding logs.
                time.sleep(0.25)
            raise

    def process_request(self, request, client_address):
        if not self.request_slots.acquire(blocking=False):
            try:
                request.settimeout(0.1)
                request.sendall(b'{"status":503,"error":"Administration busy. Try again shortly."}\n')
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.request_slots.release()

    def observe(self):
        try:
            if self.broker.request_lock.acquire(blocking=False):
                try:
                    self.broker.prepare_progress()
                finally:
                    self.broker.request_lock.release()
            if self.broker.fleet:
                self.broker.fleet.observe()
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            self.warn('background observation', exc)
        now = time.monotonic()
        if now >= self.next_capture:
            self.next_capture = now + 5
            try:
                self.history.capture()
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                self.warn('history', exc)

    def service_actions(self):
        now = time.monotonic()
        if now < self.next_observation or (self.observer and self.observer.is_alive()):
            return
        self.next_observation = now + 1
        # Never read SQLite or drive files in the socket accept loop; at most
        # one observer exists, regardless of request rate or slow storage.
        self.observer = threading.Thread(target=self.observe, daemon=True, name='usw-observer')
        self.observer.start()


def main():
    if os.geteuid() != 0:
        raise SystemExit('The administration broker requires root.')
    os.umask(0o077)
    account = pwd.getpwnam('usb-storage-watch-web')
    history = History(s.STATE_DIR / 'web-history.sqlite3')
    broker = Broker(history)
    try:
        network_manager().recover()
        network_manager().c.publish_port(network_manager().c.config())
    except (OSError, ValueError, subprocess.SubprocessError):
        network_manager().recovery_error = 'An interrupted network test needs local administrator review. Drive monitoring continues.'
        print(network_manager().recovery_error, flush=True)
    network_manager().follower.start()
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(5)
            _pid, uid, _gid = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != account.pw_uid:
                return
            try:
                result = broker.handle(common.receive(self.rfile))
                encoded = json.dumps(result).encode() + b'\n'
                if len(encoded) > common.MAX_MESSAGE:
                    encoded = b'{"status":503,"error":"Response exceeded its size limit."}\n'
                self.wfile.write(encoded)
            except (OSError, ValueError):
                pass  # Never log request bodies or authentication material.
    socket_path = Path(common.SOCKET)
    socket_path.unlink(missing_ok=True)
    with BrokerServer(common.SOCKET, Handler, broker=broker, history=history) as server:
        os.chown(common.SOCKET, 0, account.pw_gid)
        os.chmod(common.SOCKET, 0o660)
        server.serve_forever(poll_interval=1)


if __name__ == '__main__':
    main()
