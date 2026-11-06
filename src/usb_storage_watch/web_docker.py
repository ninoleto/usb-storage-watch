# SPDX-License-Identifier: MIT
"""Container-first restart choices. Docker storage metadata is advisory only."""
from contextlib import ExitStack, contextmanager
import copy
import hashlib
import http.client
import json
import os
import re
import time


def records(fleet):
    result = []
    for identifier, config, error in fleet.records():
        if error: raise ValueError(error)
        result.append((identifier, config))
    return result


def revision(items):
    return hashlib.sha256(json.dumps(dict(items), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def client(b, items):
    # A private client avoids changing another drive broker's engine globals.
    module = b.common.module('apps')
    config = copy.deepcopy(items[0][1]['docker'] if items else b.s.DEFAULT['docker'])
    module.configure(config)
    connection = module.LocalConnection('localhost', timeout=3)
    try:
        connection.request('GET', '/version')
        response = connection.getresponse(); body = response.read(65537)
        if response.status != 200 or len(body) > 65536: raise ValueError('Docker version unavailable.')
        value = json.loads(body)
        high, low = value.get('ApiVersion', ''), value.get('MinAPIVersion', '1.24')
        if not all(isinstance(v, str) and re.fullmatch(r'1\.\d{2}', v) for v in (low, high)):
            raise ValueError('Docker API version unavailable.')
        preferred = config['api'][1:]
        config['api'] = 'v' + (preferred if int(low[2:]) <= int(preferred[2:]) <= int(high[2:]) else high)
    finally: connection.close()
    module.configure(config)
    return module.Docker(), config['api']


def discover(b, items):
    docker, api = client(b, items)
    result = []; seen = set(); deadline = time.monotonic() + 18
    available = docker.request('GET', '/containers/json?all=1')
    if not isinstance(available, list) or len(available) > 512: raise ValueError('Docker returned too many containers.')
    for raw in available:
        if time.monotonic() >= deadline: raise ValueError('Container discovery timed out. Refresh again.')
        identity = raw.get('Id', '')
        if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{64}', identity): raise ValueError('Docker inventory returned an invalid identity.')
        if identity in seen: raise ValueError('Docker inventory returned a duplicate identity.')
        seen.add(identity)
        current = docker.inspect(identity)
        if current.get('id') != identity or not isinstance(current.get('name'), str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', current['name']): raise ValueError('Docker inventory changed during discovery.')
        state = ('dead' if current['dead'] else 'paused' if current['paused'] else
                 'restarting' if current['restarting'] else 'running' if current['running'] else 'stopped')
        detected = []
        for drive, c in items:
            mounts = [m.get('Source') for m in current.get('mounts', []) if isinstance(m.get('Source'), str)]
            path = c['disk']['mountpoint']
            if any(source == path or b.s.below(path, source) for source in mounts):
                detected.append(dict(drive_id=drive, drive_name=c['disk']['label']))
            for image in b.s.storage_images(c, False):
                if any(source == image['mountpoint'] or b.s.below(image['mountpoint'], source) for source in mounts):
                    detected.append(dict(drive_id=drive, drive_name=c['disk']['label'],
                                         image_uuid=image['uuid'], image_name=image['name']))
        setup = b.common.module('docker_setup').summary(b, docker, identity, current['name'])
        result.append(dict(id=identity, name=current['name'], state=state, health=current.get('health'),
                           discovered=True, detected_storage=detected, warnings=[], setup=setup))
    return result, api


def selections(items, containers):
    by_name = {row['name']: row for row in containers if row.get('discovered')}
    grouped = {}
    for drive, c in items:
        for spec in c['docker']['containers']:
            identity = spec.get('container_id') or by_name.get(spec['name'], {}).get('id') or 'saved:' + spec['name']
            key = (identity, spec['name'])
            grouped.setdefault(key, {})[drive] = dict(id=drive, enabled=c['docker']['enabled'], images=list(spec.get('images', [])))
    for row in containers: grouped.setdefault((row['id'], row['name']), {})
    return [dict(id=identity, name=name, drives=[choices.get(drive, dict(id=drive, enabled=False, images=[])) for drive, _ in items])
            for (identity, name), choices in sorted(grouped.items(), key=lambda item: item[0][1])]


def payload(b, items, containers, error=''):
    settings = selections(items, containers)
    seen = {row['id'] for row in containers}
    rows = list(containers)
    for choice in settings:
        if choice['id'] not in seen:
            rows.append(dict(id=choice['id'], name=choice['name'], state='unknown' if error else 'missing',
                             health=None, discovered=False, detected_storage=[], warnings=[
                                 'Docker is unavailable; saved selections are retained.' if error else
                                 'This saved container was not detected. Its recovery choices can be turned off.']))
    drives = []
    for drive, c in items:
        metadata = {}
        try: metadata = json.loads((b.s.STATE_DIR if drive == 'legacy' else b.s.STATE_ROOT/'drives'/drive).joinpath('drive-identity.json').read_text())
        except (OSError, ValueError): pass
        drives.append(dict(id=drive, name=c['disk']['label'], model=c['disk']['label'], size=metadata.get('size'), mountpoint=c['disk']['mountpoint'], automatic_mount=c['recovery']['mount'],
                           images=[dict(uuid=item['uuid'], name=item['name'], enabled=item['enabled'], mountpoint=item['mountpoint'])
                                   for item in b.s.storage_images(c, False)]))
    return dict(revision=revision(items), containers=sorted(rows, key=lambda row: (row['name'].lower(), row['id'])),
                drives=drives, settings=settings, observed_at=b.w.timestamp(), error=error, inventory_ok=not bool(error),
                boot=b.common.module('boot_start').public(b))


def overview(fleet):
    b = fleet.context()
    with fleet.mutex, b.cli.drives.configuration_lock(b.s):
        recover_transaction(fleet)
        items = records(fleet)
    try: containers, _ = discover(b, items); error = ''
    except Exception:
        containers = []; error = 'Docker discovery is unavailable. Saved recovery settings are retained.'
    # The private Docker module has its own exception class; all discovery errors
    # become a bounded unavailable result without leaking daemon response bodies.
    with fleet.mutex, b.cli.drives.configuration_lock(b.s):
        recover_transaction(fleet); items = records(fleet)
        result = payload(b, items, containers, error)
        try:
            result['applications'] = b.common.module('app_settings').snapshot(b, items, containers)
            for saved in result['applications']['settings']:
                if not any(row['id'] == saved['id'] for row in result['containers']):
                    result['containers'].append(dict(id=saved['id'], name=saved['name'], state='unknown' if error else 'missing', discovered=False))
        except (ValueError, OSError):
            result['applications'] = dict(revision=None, settings=[], error='App settings could not be read safely. Refresh or review the saved configuration.')
    restrictions = b.common.module('app_control').restrictions(b, items)
    for row in result['containers']:
        row['control_block'] = restrictions.get(row['id'], '')
    for drive in result['drives']:
        try:
            child, _ = fleet.get(drive['id'])
            service = child.service_state()
            drive['monitoring'] = service.get('ActiveState') == 'active'
            drive['monitor_enabled'] = service.get('UnitFileState') in ('enabled', 'enabled-runtime')
        except Exception:
            drive['monitoring'] = None; drive['monitor_enabled'] = None
    return result


@contextmanager
def request_lock(instance):
    if not instance.request_lock.acquire(timeout=.5): raise ValueError('A drive setting is being saved. Try saving again.')
    try: yield
    finally: instance.request_lock.release()


def journal_path(b):
    return b.cli.drives.roots(b.s)[1]/'docker-settings-transaction.json'


def finish_transaction(path):
    path.unlink()
    fd=os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try: os.fsync(fd)
    finally: os.close(fd)


def recover_transaction(fleet):
    """Undo a process-interrupted multi-profile save before exposing new choices."""
    b = fleet.context(); b.common.module('app_entries').recover(fleet)
    path = journal_path(b)
    if not path.exists(): return
    try:
        data = json.loads(path.read_text())
        if (set(data) != {'version', 'before', 'after'} or data['version'] != 1 or not isinstance(data['before'], dict)
                or not isinstance(data['after'], dict) or set(data['before']) != set(data['after'])): raise ValueError()
        active = dict(b.cli.drives.files(b.s))
        # Validate every path before restoring any: never overwrite a later unrelated edit.
        for identifier, old in data['before'].items():
            if identifier not in active: raise ValueError()
            current=b.cli.drives.read(b.s, active[identifier])
            if current not in (b.s.validate(old), b.s.validate(data['after'][identifier])): raise ValueError()
        for identifier, old in data['before'].items():
            b.cli.save(active[identifier], b.s.validate(old))
        finish_transaction(path)
    except (OSError, ValueError, TypeError):
        raise ValueError('An interrupted Docker settings save needs administrator review. Existing monitoring continues.') from None


def save(fleet, data, *, retained_specs=None):
    b = fleet.context()
    if set(data) != {'id', 'name', 'revision', 'drives'}: raise ValueError('Invalid container restart settings.')
    identity, name = data['id'], data['name']
    if not isinstance(name, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name): raise ValueError('Select a detected container.')
    if not isinstance(identity, str) or not (re.fullmatch('[0-9a-f]{64}', identity) or identity == 'saved:' + name): raise ValueError('Select a detected container identity.')
    if not isinstance(data['drives'], list): raise ValueError('Choose the disks for this container.')
    choices = {}
    for choice in data['drives']:
        if not isinstance(choice, dict) or set(choice) != {'id', 'enabled', 'images'}: raise ValueError('Invalid drive restart choice.')
        drive = choice['id']
        if not isinstance(drive, str) or drive in choices or type(choice['enabled']) is not bool: raise ValueError('Invalid drive restart choice.')
        if (not isinstance(choice['images'], list) or any(not isinstance(v, str) for v in choice['images'])
                or len(set(choice['images'])) != len(choice['images'])): raise ValueError('Choose valid virtual images.')
        if not choice['enabled'] and choice['images']: raise ValueError('An unselected disk cannot request image mounts.')
        choices[drive] = choice
    # Discovery can take seconds; never hold monitor/configuration locks while
    # waiting for Docker. The revision is checked again under locks before write.
    with fleet.mutex, b.cli.drives.configuration_lock(b.s):
        recover_transaction(fleet); initial = records(fleet)
        if revision(initial) != data['revision']: raise ValueError('Settings changed. Reload saved settings before saving this container.')
    enabled = any(choice['enabled'] for choice in choices.values())
    detected = []; api = None
    if enabled:
        try: detected, api = discover(b, initial)
        except Exception:
            raise ValueError('Docker discovery is unavailable. Refresh before enabling a restart choice.') from None
        if not any(row['id'] == identity and row['name'] == name for row in detected):
            raise ValueError('This container identity changed. Refresh and select the current container.')
    with fleet.mutex, ExitStack() as locks:
        first = records(fleet)
        for drive, _ in sorted(first):
            child, instance = fleet.get(drive); locks.enter_context(request_lock(instance))
        locks.enter_context(b.common.module('app_control').operation(fleet, identity))
        locks.enter_context(b.cli.drives.configuration_lock(b.s))
        recover_transaction(fleet); items = records(fleet)
        if revision(items) != data['revision']: raise ValueError('Settings changed. Reload saved settings before saving this container.')
        if set(choices) != {drive for drive, _ in items}: raise ValueError('The drive list changed. Refresh before saving.')
        updated = []
        for drive, old in items:
            choice = choices[drive]; c = copy.deepcopy(old)
            available = {image['uuid'] for image in b.s.storage_images(c, False)}
            if not set(choice['images']) <= available: raise ValueError('A selected virtual image no longer exists on this disk.')
            old_spec = next((item for item in c['docker']['containers'] if item['name'] == name), None)
            if old_spec and old_spec.get('container_id') and old_spec['container_id'] != identity and not choice['enabled']:
                # A stale missing card must not remove a replacement card's choices.
                updated.append((drive, c)); continue
            retained = [item for item in c['docker']['containers'] if item['name'] != name]
            if choice['enabled'] and retained and not c['docker']['enabled']:
                raise ValueError('Other apps have saved choices with drive-level Docker recovery off. Review those settings first; no selections changed.')
            if choice['enabled']:
                remembered = (retained_specs or {}).get(drive)
                if remembered and (remembered.get('container_id') != identity or remembered.get('name') != name):
                    raise ValueError('Retained app identity differs; no settings changed.')
                spec = dict(old_spec or remembered or dict(name=name, source='', destination='', grace=30))
                spec.update(container_id=identity, images=list(choice['images']))
                retained.append(spec)
            c['docker']['containers'] = retained; c['docker']['enabled'] = bool(retained) and (c['docker']['enabled'] or choice['enabled'])
            if api and choice['enabled']: c['docker']['api'] = api
            updated.append((drive, b.s.validate(c)))
        changed = [(drive, c) for drive, c in updated if c != dict(items)[drive]]
        if changed:
            path = journal_path(b)
            b.cli.save(path, dict(version=1, before={drive: dict(items)[drive] for drive, _ in changed}, after=dict(changed)))
            try:
                for drive, c in changed:
                    child, _ = fleet.get(drive)
                    b.cli.save(child.s.CONFIG, c)
                finish_transaction(path)
            except Exception:
                if path.exists():
                    recover_transaction(fleet)
                    raise ValueError('Container settings could not be saved; previous settings were restored.') from None
                raise ValueError('Settings were applied but confirmation could not complete. Refresh saved settings before making another change.') from None
            for drive, _ in changed: fleet.cache.pop(drive, None)
        result = payload(b, updated, detected)
        return dict(revision=result['revision'], settings=result['settings'], message='Container recovery settings saved.')


# Manual operations use Docker runtime identity only. Recovery settings and
# storage detection never decide whether these explicit controls can be used.
MANUAL_VERIFY_SECONDS = 8
MANUAL_GRACE_SECONDS = 30


def manual_snapshot(value, identity, name):
    if (not isinstance(value, dict) or value.get('id') != identity or value.get('name') != name
            or any(type(value.get(key)) is not bool for key in ('running', 'paused', 'restarting', 'dead'))
            or not isinstance(value.get('started_at'), str)):
        raise ValueError('This container identity or runtime state changed. Refresh containers before trying again.')
    state = ('dead' if value['dead'] else 'paused' if value['paused'] else
             'restarting' if value['restarting'] else 'running' if value['running'] else 'stopped')
    health = value.get('health')
    if health not in (None, 'none', 'starting', 'healthy', 'unhealthy'): health = None
    return dict(id=identity, name=name, state=state, health=health, discovered=True)


def manual_read(docker, identity, name):
    value = docker.inspect(identity)
    return value, manual_snapshot(value, identity, name)


def manual_storage(b, items, identity, name):
    """Union explicit saved choices, including retained choices with automation off.

    This never infers dependencies from Docker binds or assigns by app name.
    Remembered choices only restrict this manual request; they enable no recovery.
    """
    for _, config in items:
        for spec in config['docker']['containers']:
            if spec['name'] == name and not spec.get('container_id'):
                raise ValueError('Saved storage choices have no pinned container identity. Select this app explicitly in app settings; no Docker command was sent.')
            if spec.get('container_id') == identity and spec['name'] != name:
                raise ValueError('Saved container identity changed. Refresh app settings; no Docker command was sent.')
    try: saved = b.common.module('app_settings').snapshot(b, items, [dict(id=identity, name=name)])
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('Saved startup/recovery storage choices could not be verified. Review app settings; no Docker command was sent.') from None
    item = next(v for v in saved['settings'] if v['id'] == identity)
    if item['name'] != name:
        raise ValueError('Saved container identity changed. Refresh app settings; no Docker command was sent.')
    choices = {}
    for mode in ('boot', 'recovery'):
        for choice in item[mode]['drives']:
            choices.setdefault(choice['id'], set()).update(choice['images'])
    selection = dict(drives=[dict(id=drive, images=sorted(images)) for drive, images in sorted(choices.items())])
    boot = b.common.module('boot_start')
    try: boot.validate_storage(b, selection, items)
    except ValueError as exc:
        raise ValueError('Required storage selections need review. ' + str(exc) + ' No Docker command was sent.') from None
    configs = dict(items)
    return selection, {drive: configs[drive] for drive in choices}


def verify_manual_storage(contexts):
    """Use the boot/recovery verifier, never a directory-exists readiness check."""
    for choice, w in contexts:
        target = 'drive ' + w.SETTINGS['disk']['label']
        try:
            w.verify_main()
            images = {v['uuid']: v for v in w.settings.storage_images(w.SETTINGS, False)}
            for identity in choice['images']:
                image = images[identity]
                target = 'virtual image ' + image['name'] + ' on ' + w.SETTINGS['disk']['label']
                w.verify_dependent(image)
        except (OSError, ValueError, KeyError, w.Unsafe) as exc:
            if isinstance(exc, FileNotFoundError): detail = 'The required filesystem or device information is missing.'
            elif isinstance(exc, w.Unsafe): detail = str(exc)
            else: detail = 'Storage could not be verified (' + type(exc).__name__ + ').'
            raise ValueError('Cannot start or restart: required ' + target + ' is not ready. ' + detail +
                             ' Mount the correct storage and try again. No Docker command was sent.') from None


def manual_action(fleet, data):
    """One user-requested Start/Stop/Restart; no storage operations or retries."""
    if (set(data) != {'id', 'name', 'action', 'confirm'} or data.get('confirm') is not True
            or not isinstance(data.get('id'), str) or not re.fullmatch('[0-9a-f]{64}', data['id'])
            or not isinstance(data.get('name'), str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', data['name'])
            or data.get('action') not in ('start', 'stop', 'restart')):
        raise ValueError('Choose a detected container and explicitly confirm Start, Stop or Restart.')
    b = fleet.context(); identity, name, action = data['id'], data['name'], data['action']
    # Capture connection settings briefly. Do not hold settings, monitoring or
    # per-drive request locks while waiting for Docker.
    try:
        with fleet.mutex, b.cli.drives.configuration_lock(b.s):
            available = fleet.records()
            items = [(identifier, config) for identifier, config, error in available if not error]
            if available and not items:
                raise ValueError('Docker connection settings could not be read. No Docker command was sent.')
            if action != 'stop':
                if any(error for _, _, error in available):
                    raise ValueError('Required storage settings could not be read safely. Review drive settings; no Docker command was sent.')
                storage = manual_storage(b, items, identity, name)
    except BlockingIOError:
        raise ValueError('Settings are being saved. Wait briefly, then try this Docker action again. No Docker command was sent.') from None
    guard = b.common.module('app_control')
    guard.require_idle(b, items, identity)
    directory = b.cli.drives.roots(b.s)[1] / 'shared-locks'
    operation = ExitStack()
    try:
        contexts = []; fds = []
        if action != 'stop':
            # Same order as boot/recovery: sorted storage locks, then app lock.
            for choice in storage[0]['drives']:
                w = b.common.module('boot_start').engine(b, choice['id'], storage[1][choice['id']])
                fds.append(operation.enter_context(b.cli.drives.lock(w.STATE_DIR, 'recovery.lock')))
                contexts.append((choice, w))
        fds.append(operation.enter_context(b.cli.drives.lock(directory, 'docker-restart-' + identity + '.lock')))
        for _, w in contexts: w.WORKER_LOCK_FDS = tuple(fds)
    except BlockingIOError:
        operation.close()
        raise ValueError('Another operation is controlling this container or its required storage. Wait for its result, then try again. No additional Docker command was sent.') from None
    except Exception:
        operation.close()
        raise
    try:
        def recheck_storage_settings():
            with b.cli.drives.configuration_lock(b.s):
                current_items = records(fleet)
                if manual_storage(b, current_items, identity, name) != storage:
                    raise ValueError('Required storage settings changed. Refresh and try again; no Docker command was sent.')
            guard.require_idle(b, current_items, identity)
        if action != 'stop': recheck_storage_settings()
        guard.require_idle(b, items, identity)
        try:
            docker, _ = client(b, items)
            before, current = manual_read(docker, identity, name)
        except Exception:
            raise ValueError('This container could not be verified with Docker. Refresh containers before trying again. No Docker command was sent.') from None
        if current['state'] in ('paused', 'dead', 'restarting'):
            raise ValueError('This container is ' + current['state'] + '. Resolve that state in Docker, then refresh. No Docker command was sent.')
        if action != 'stop':
            verify_manual_storage(contexts)
            recheck_storage_settings()
        guard.require_idle(b, items, identity)
        if action == 'stop':
            b.common.module('boot_start').cancel(b, identity)
        if (action == 'start' and current['state'] == 'running') or (action == 'stop' and current['state'] == 'stopped'):
            if action == 'start': b.common.module('manual_intent').release(b, identity)
            return dict(ok=True, uncertain=False, changed=False, container=current,
                        message='Container is already ' + current['state'] + '. No Docker command was needed.')
        query = '?t=' + str(MANUAL_GRACE_SECONDS) if action in ('stop', 'restart') else ''
        try:
            docker.request('POST', '/containers/' + identity + '/' + action + query,
                           timeout=MANUAL_GRACE_SECONDS + 10 if action in ('stop', 'restart') else 10,
                           allowed_status=(304,) if action in ('start', 'stop') else ())
        except Exception as exc:
            # A timeout/daemon refusal can follow an accepted command. A read
            # updates the displayed state but cannot authorize a second POST.
            try: _, current = manual_read(docker, identity, name)
            except Exception: current = None
            suffix = (' Current state: ' + current['state'] + '.') if current else ''
            if getattr(exc, 'status', None) is not None:
                return dict(ok=False, uncertain=False, container=current, message=str(exc) + suffix)
            return dict(ok=False, uncertain=True, container=current,
                        message='Docker did not return a confirmed result for ' + action + '. The command was not sent again.' + suffix +
                        ' Refresh the container state before another action.')
        deadline = time.monotonic() + MANUAL_VERIFY_SECONDS
        while True:
            try: observed, current = manual_read(docker, identity, name)
            except Exception:
                return dict(ok=False, uncertain=True, container=None,
                            message='Docker accepted the ' + action + ' request, but its current state could not be verified. The command was not sent again. Refresh containers before another action.')
            expected = current['state'] == ('stopped' if action == 'stop' else 'running')
            restarted = action != 'restart' or (observed['started_at'] and observed['started_at'] != before['started_at'])
            if expected and restarted:
                if action != 'stop': b.common.module('manual_intent').release(b, identity)
                message = 'Container ' + ('restarted and is running.' if action == 'restart' else 'is stopped.' if action == 'stop' else 'is running.')
                if current['health'] in ('starting', 'unhealthy'):
                    message += ' Its health check reports ' + current['health'] + '.'
                if action != 'stop': message += ' Application file access has not been tested.'
                return dict(ok=True, uncertain=False, message=message, container=current)
            if time.monotonic() >= deadline:
                uncertain = expected and not restarted
                return dict(ok=False, uncertain=uncertain, container=current,
                            message='Docker accepted the ' + action + ' request, but ' +
                            ('a new container start was not verified.' if uncertain else 'the container is currently ' + current['state'] + '.') +
                            ' The command was not sent again. Refresh or check the application logs before another action.')
            time.sleep(.25)
    finally:
        operation.close()
