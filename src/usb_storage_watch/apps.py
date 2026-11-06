# SPDX-License-Identifier: MIT
"""Stop selected containers at drive failure, then start after storage recovery.

The Docker socket is local and explicitly configured. No Compose, daemon or unrelated-container
operations. API bodies/inspect environments and application output are never logged.
"""
import fcntl
from contextlib import ExitStack, contextmanager
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import time
from types import SimpleNamespace

APPS = {}
SOCKET = '/var/run/docker.sock'
API = '/v1.47'
CAPTURE_TIMEOUT = 10
WORK_TIMEOUT = 720
HEALTH_TIMEOUT = 120
BASELINE_MAX_AGE = 30
ENABLED = False
READER = None


def configure(value, reader=None):
    global APPS, SOCKET, API, WORK_TIMEOUT, HEALTH_TIMEOUT, ENABLED, READER, CAPTURE_TIMEOUT
    APPS = {v['name']: dict(source=v.get('source', ''), destination=v.get('destination', ''),
                            grace=v['grace'], container_id=v.get('container_id', ''),
                            images=list(v.get('images', []))) for v in value['containers']}
    SOCKET, API = value['socket'], '/' + value['api']
    WORK_TIMEOUT, HEALTH_TIMEOUT, ENABLED, READER = value['worker_timeout'], value['health_timeout'], value['enabled'], reader
    CAPTURE_TIMEOUT = max(10, len(APPS)*4)


ACCESS_SCRIPT = 'test -d "$1" && test -r "$1" && test -x "$1" && find "$1" -mindepth 1 -maxdepth 1 -print -quit >/dev/null'


class AppError(RuntimeError):
    pass


class StorageLost(AppError):
    pass


class DockerHTTPError(AppError):
    """A definite daemon refusal, with a bounded non-secret explanation."""
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def daemon_refusal(status, data):
    # Do not return arbitrary daemon output: it can contain host paths, command
    # arguments or credentials. Classify known failures and retain the status.
    try:
        raw = json.loads(data)
        message = raw.get('message', '') if isinstance(raw, dict) else ''
    except (ValueError, UnicodeError):
        message = ''
    text = message.lower() if isinstance(message, str) else ''
    if 'cannot assign requested address' in text:
        detail = 'The host IP address configured for this container is unavailable. Check its published port address in Docker.'
    elif 'port is already allocated' in text or 'address already in use' in text:
        detail = 'Another process or container is using this container’s published port. Free that port or change its Docker port setting.'
    elif 'bind source path does not exist' in text or 'mount source path' in text and ('not exist' in text or 'no such file' in text):
        detail = 'A host storage folder configured for this container is missing. Mount its disk and any required virtual image before starting it.'
    elif 'permission denied' in text or status in (401, 403):
        detail = 'Docker denied access. Check the Docker socket permissions and the container’s storage permissions.'
    elif 'paused' in text:
        detail = 'This container is paused. Unpause it in Docker before starting or stopping it here.'
    elif status == 404:
        detail = 'Docker could not find this container. Refresh the container list.'
    elif 'client version' in text or 'api version' in text:
        detail = 'The Docker API version is incompatible. Refresh containers to renegotiate the Docker connection.'
    elif 'device or resource busy' in text:
        detail = 'Docker cannot attach the configured storage because it is still busy. Check the disk and virtual-image mount state.'
    else:
        detail = 'Docker refused the operation. Check this container’s Docker error or logs for the exact cause.'
    return DockerHTTPError(status, 'Docker refused the operation (HTTP ' + str(status) + '). ' + detail)


class LocalConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


class Docker:
    def request(self, method, path, body=None, timeout=3, allowed_status=()):
        conn = LocalConnection('localhost', timeout=timeout)
        try:
            encoded = '' if body is None and method == 'POST' else None if body is None else json.dumps(body)
            conn.request(method, API + path, body=encoded,
                         headers={'Content-Type': 'application/json'} if body is not None else {})
            response = conn.getresponse()
            data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise AppError('Docker response exceeded the size limit; outcome requires verification.')
            if not (200 <= response.status < 300 or response.status in allowed_status):
                raise daemon_refusal(response.status, data)
            return json.loads(data) if data.strip() and response.status not in (204, 304) else None
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise AppError('Docker API unavailable/timeout/invalid response (' + type(exc).__name__ + ').') from None
        finally:
            conn.close()

    def inspect(self, name):
        if name not in APPS and not re.fullmatch('[0-9a-f]{64}', name):
            raise AppError('Unapproved container identity.')
        raw = self.request('GET', '/containers/' + name + '/json')
        state = raw['State']
        healthcheck = (raw.get('Config', {}).get('Healthcheck') or {}).get('Test', [])
        # Whitelist only non-secret identity, health and bind metadata.
        return {'id': raw['Id'], 'name': raw['Name'].removeprefix('/'),
                'running': state['Running'], 'paused': state['Paused'],
                'restarting': state['Restarting'], 'dead': state['Dead'],
                'started_at': state['StartedAt'], 'pid': state['Pid'],
                'healthcheck': bool(healthcheck and healthcheck != ['NONE']),
                'health': state.get('Health', {}).get('Status'),
                'mounts': [{k: m.get(k) for k in ('Type', 'Source', 'Destination', 'RW', 'Propagation')}
                           for m in raw.get('Mounts', [])]}

    def change(self, name, container_id, action):
        if name not in APPS or not re.fullmatch('[0-9a-f]{64}', container_id):
            raise AppError('Unapproved container identity.')
        if action not in ('restart', 'start', 'stop'):
            raise AppError('Unapproved Docker action.')
        grace = APPS[name]['grace']
        query = '?t=' + str(grace) if action in ('restart', 'stop') else ''
        self.request('POST', '/containers/' + container_id + '/' + action + query,
                     timeout=grace + 10, allowed_status=(304,) if action in ('start', 'stop') else ())

    def access(self, container_id, destination, check):
        # Read-only directory enumeration as the configured container user.
        # The command has an inside-container timeout as well as host deadlines.
        check()
        result = self.request('POST', '/containers/' + container_id + '/exec', {
            'AttachStdout': False, 'AttachStderr': False, 'Privileged': False,
            'Cmd': ['timeout', '8', 'sh', '-c', ACCESS_SCRIPT, 'storage-access', destination]})
        exec_id = result['Id']
        if not re.fullmatch('[0-9a-f]{64}', exec_id):
            raise AppError('Invalid Docker exec identity.')
        check()
        self.request('POST', '/exec/' + exec_id + '/start', {'Detach': True, 'Tty': False})
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            check()
            result = self.request('GET', '/exec/' + exec_id + '/json')
            if not result['Running']:
                if result['ExitCode'] != 0:
                    raise AppError('Inside-container access check failed (exit ' + str(result['ExitCode'])
                                   + '); timeout/sh/find and read/search access are required.')
                return
            time.sleep(0.25)
        raise AppError('Inside-container access verification timed out.')


def enabled():
    return READER()['docker_enabled'] if READER else ENABLED


def validate_container(name, value, container_id=None):
    """Only identity is mandatory; Docker storage locations never grant permission."""
    expected = APPS[name].get('container_id') or container_id
    if (value.get('name') != name or not re.fullmatch('[0-9a-f]{64}', value.get('id', ''))
            or (expected and value['id'] != expected)):
        raise AppError('Container was replaced/renamed or its identity is unknown; untouched.')


def selected_now(name, container_id=None):
    """Honor a saved deselection before sending any new Docker action."""
    if not enabled():
        return False
    if not READER:
        return True
    current = READER()
    rows = current.get('docker_containers')
    if rows is None:  # Compatibility for callers that only expose enabled state.
        return True
    selected = next((v for v in rows if v['name'] == name), None)
    expected = container_id or APPS[name].get('container_id')
    return bool(selected and (not selected.get('container_id') or not expected or
                             selected['container_id'] == expected))


def stop_ledger_path(w):
    return w.STATE_DIR / 'app-stop.json'


def read_stop_ledger(w, incident, archive=True):
    try:
        raw = stop_ledger_path(w).read_text()
        value = json.loads(raw)
    except FileNotFoundError:
        return None
    if (not isinstance(value, dict) or value.get('version') != 1
            or not isinstance(value.get('incident'), str)
            or not isinstance(value.get('containers'), dict)
            or type(value.get('complete')) is not bool):
        raise AppError('Invalid container-stop record; retained for review.')
    for name, entry in value['containers'].items():
        if (not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name)
                or not isinstance(entry, dict)
                or entry.get('status') not in ('pending', 'intent', 'stopped', 'already_stopped', 'skipped', 'failed', 'uncertain')
                or type(entry.get('action_count')) is not int or entry['action_count'] not in (0, 1)
                or (entry.get('container_id') is not None and not re.fullmatch('[0-9a-f]{64}', entry['container_id']))):
            raise AppError('Invalid container-stop action record; retained for review.')
    if value['incident'] != incident:
        if not value['complete']:
            raise AppError('An earlier container-stop operation is unresolved; retained for review.')
        if archive:
            history = w.STATE_DIR / 'application-history'
            history.mkdir(mode=0o700, exist_ok=True)
            w.atomic_write(history / ('stop-' + hashlib.sha256(raw.encode()).hexdigest() + '.json'), raw)
        return None
    return value


def save_stop(w, value):
    w.atomic_write(stop_ledger_path(w), json.dumps(value, indent=2, allow_nan=False) + '\n')


@contextmanager
def storage_recovery_guard(w, request, docker=None):
    """Keep selected containers stopped while their storage is recovered.

    The persisted stop receipt proves this incident's completed stop stage;
    fresh Docker inspection proves its current state. Shared container locks
    prevent this application's manual or other-drive start during recovery.
    This guard never sends a Docker mutation or replaces a stop receipt.
    Its yielded callback repeats live checks immediately before storage actions.
    """
    def selection():
        w.require_configuration(request)
        current = READER() if READER else None
        if not (current.get('docker_enabled') if current is not None else enabled()):
            return {}
        rows = current.get('docker_containers') if current is not None else None
        if rows is None:
            return {name: spec.get('container_id', '') for name, spec in APPS.items()}
        selected = {}
        for row in rows:
            name = row['name']
            if name not in APPS:
                raise AppError('Container recovery selection changed after the stop stage; storage recovery is waiting for a verified stop.')
            selected[name] = row.get('container_id') or APPS[name].get('container_id', '')
        return selected

    selected = selection()
    if not selected:
        observed_boot = w.boot_id()
        def recheck_empty_selection():
            if w.boot_id() != observed_boot:
                raise AppError('Host boot changed during storage recovery; stop verification must run again.')
            if selection() != selected:
                raise AppError('Container recovery selection changed before storage recovery; the new selection must be stopped first.')
        recheck_empty_selection()
        yield recheck_empty_selection
        return
    if request.get('boot') != w.boot_id():
        raise AppError('Storage recovery requires a container stop verified in the current host boot.')
    with (w.STATE_DIR / 'applications.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AppError('Another application operation is active; storage recovery is waiting for its stop verification.') from None
        value = read_stop_ledger(w, request['incident'], archive=False)
        if (not isinstance(value, dict) or value.get('boot') != request['boot']
                or value.get('complete') is not True or value.get('all_stopped') is not True):
            raise AppError('Selected containers have no completed stop receipt for this incident and host boot; storage recovery is waiting.')
        identities = {}
        for name, configured_id in selected.items():
            entry = value['containers'].get(name, {})
            identity = entry.get('container_id', '')
            if (entry.get('status') not in ('stopped', 'already_stopped')
                    or not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{64}', identity)
                    or (configured_id and configured_id != identity)):
                raise AppError('Selected container ' + name + ' has no matching verified stop; storage recovery is waiting.')
            identities[name] = identity
        with ExitStack() as locks:
            # Identical ordering avoids cycles when several drives share apps.
            for name, identity in sorted(identities.items(), key=lambda item: (item[1], item[0])):
                locks.enter_context(container_action(w, name, identity, request, healthy=False))
            docker = docker or Docker()
            def recheck_stopped():
                if request.get('boot') != w.boot_id():
                    raise AppError('Storage recovery requires a container stop verified in the current host boot.')
                if selection() != selected:
                    raise AppError('Container recovery selection changed while its locks were held; storage recovery needs a verified stop.')
                for name, identity in identities.items():
                    current = docker.inspect(name)
                    validate_container(name, current, identity)
                    if current.get('id') != identity:
                        raise AppError('Selected container ' + name + ' differs from its stop receipt; storage recovery is waiting.')
                    if any(current.get(key) is not False for key in ('running', 'paused', 'restarting')):
                        raise AppError('Selected container ' + name + ' is not confirmed stopped now; storage recovery is waiting for a verified stop.')
                if selection() != selected:
                    raise AppError('Container recovery selection changed during stop verification; storage recovery needs a verified stop.')
            recheck_stopped()
            yield recheck_stopped


def stop_selected(w, request, docker=None):
    """Stop once per incident before any disk recovery, without touching storage.

    A durable intent is written before sending Docker a command. On resumed
    work only a read-back is allowed for that intent in the same host boot.
    A verified host reboot ends the old command and permits a new stop epoch.
    The same lock serializes manual and recovery controls.
    """
    if request.get('boot') != w.boot_id():
        raise AppError('Container stop request belongs to another host boot; no command sent.')
    docker = docker or Docker()
    with (w.STATE_DIR / 'applications.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        value = read_stop_ledger(w, request['incident'])
        if value is None:
            value = dict(version=1, incident=request['incident'], boot=request['boot'],
                         complete=False, all_stopped=False, containers={})
        for entry in value['containers'].values():
            if entry['action_count']:
                entry.setdefault('action_boot', value.get('boot'))
        changed_boot = value.get('boot') != request['boot']
        if changed_boot:
            value['previous_boot'] = value.get('boot')
            value['boot'] = request['boot']
            for entry in value['containers'].values():
                # Boot changed: a restart policy may have started it again. A
                # historical success does not prove current stopped state.
                if entry['status'] in ('stopped', 'already_stopped'):
                    entry['verified_stopped_start'] = entry.get('before_started_at')
                    entry['status'] = 'intent' if entry['action_count'] else 'pending'
                    entry['needs_boot_verification'] = True
        for name in APPS:
            value['containers'].setdefault(name, dict(status='pending', action_count=0))
        save_stop(w, value)
        for name, entry in value['containers'].items():
            if entry['status'] == 'skipped':
                continue
            try:
                if name not in APPS or not selected_now(name):
                    entry.update(status='skipped', reason='Container recovery selection is off; no stop command sent.')
                    save_stop(w, value)
                    continue
                w.require_configuration(request)
                current = docker.inspect(name)
                validate_container(name, current, entry.get('container_id'))
                identity = entry['container_id'] = current['id']
                entry.setdefault('before_started_at', current['started_at'])
                with container_action(w, name, identity, request, healthy=False):
                    current = docker.inspect(name)
                    validate_container(name, current, identity)
                    new_host_boot = bool(entry['action_count'] and entry.get('action_boot')
                                         and entry['action_boot'] != request['boot'])
                    new_execution = bool(entry.get('verified_stopped_start')
                                         and current['started_at'] != entry['verified_stopped_start'])
                    if current['running'] and entry['action_count'] and (new_host_boot or new_execution):
                        # A verified host reboot terminates the old local Docker
                        # request, even if its acknowledgement was lost. Within
                        # one boot only a proven new execution after a VERIFIED
                        # stop grants another stop. Preserve every old receipt.
                        history = entry.setdefault('stop_history', [])
                        history.append({key: item for key, item in entry.items() if key != 'stop_history'})
                        entry.clear()
                        entry.update(status='pending', action_count=0, container_id=identity,
                                     before_started_at=current['started_at'], stop_history=history)
                    if current['running'] is False and current['paused'] is False and current['restarting'] is False:
                        entry.update(status='stopped' if entry['action_count'] else 'already_stopped',
                                     reason='Container is stopped.', verified_at=w.timestamp(),
                                     verified_stopped_start=current['started_at'])
                    elif entry['action_count']:
                        entry.update(status='uncertain', reason='The earlier stop request has not been verified. It was not repeated.')
                    else:
                        w.require_configuration(request)
                        if not selected_now(name, identity):
                            entry.update(status='skipped', reason='Container was deselected before stopping.')
                            save_stop(w, value)
                            continue
                        entry.update(status='intent', action='stop', action_count=1, action_boot=request['boot'], attempted_at=w.timestamp())
                        save_stop(w, value)
                        try:
                            docker.change(name, identity, 'stop')
                            entry['api_accepted_at'] = w.timestamp()
                        except AppError as exc:
                            entry['api_error'] = str(exc)
                        # Docker stop is synchronous; this authoritative read also
                        # covers a lost acknowledgement after a successful stop.
                        current = docker.inspect(name)
                        validate_container(name, current, identity)
                        if current['running'] is False and current['paused'] is False and current['restarting'] is False:
                            entry.update(status='stopped', reason='Container stopped before disk recovery.', verified_at=w.timestamp(),
                                         verified_stopped_start=current['started_at'])
                        else:
                            entry.update(status='failed', reason=entry.get('api_error') or 'Docker did not confirm that the container stopped. Disk recovery is waiting.')
            except (AppError, w.Unsafe, OSError, ValueError, KeyError, TypeError) as exc:
                entry.update(status='uncertain' if entry['action_count'] else 'failed', reason=safe_error(exc))
            save_stop(w, value)
        value.update(complete=True, finished_at=w.timestamp(), all_stopped=all(
            entry['status'] in ('stopped', 'already_stopped', 'skipped') for entry in value['containers'].values()))
        save_stop(w, value)
        return value


def capture(w, docker=None):
    docker = docker or Docker()
    result = {'boot': w.boot_id(), 'at': w.clock_now(), 'time': w.timestamp(), 'containers': {}}
    for name in APPS:
        try:
            current = docker.inspect(name)
            validate_container(name, current)
            result['containers'][name] = {'known': True, 'id': current['id'],
                'running': current['running'] and not current['paused'] and not current['dead'],
                'docker_running': current['running'],
                'paused': current['paused'], 'started_at': current['started_at']}
        except (AppError, OSError, ValueError, KeyError, TypeError) as exc:
            result['containers'][name] = {'known': False, 'error': safe_error(exc)}
    return result


def incident_state(baseline, now, boot, first_bad=None, interval=None):
    # The baseline precedes the FIRST failed observation. Confirmation can take
    # several polling intervals; measuring its age at confirmation loses valid
    # running-state evidence and mistakes an outage exit for an intentional stop.
    def finite(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    reference, maximum_age = now, BASELINE_MAX_AGE
    timing_valid = finite(now)
    if interval is not None:
        timing_valid = (timing_valid and type(interval) is int and 5 <= interval <= 3600
                        and isinstance(first_bad, dict) and first_bad.get('boot') == boot
                        and finite(first_bad.get('at')) and first_bad['at'] <= now)
        reference = first_bad['at'] if timing_valid else now
        maximum_age = interval + 5 if timing_valid else 0  # Bounded scheduler jitter.
    recent = (timing_valid and isinstance(baseline, dict) and baseline.get('boot') == boot
              and finite(baseline.get('at')) and 0 <= reference - baseline['at'] <= maximum_age)
    return {'phase': 'waiting', 'baseline': baseline if recent else None,
            'detected': None, 'capture_phase': 'pending'}


def plan(app):
    result = {}
    for name in APPS:
        # Prefer pre-outage evidence. Do not reinterpret an intentional stop as
        # an outage stop. Incident-time capture is the fallback for unknown history.
        value = (app.get('baseline') or {}).get('containers', {}).get(name)
        if not value or not value.get('known'):
            value = (app.get('detected') or {}).get('containers', {}).get(name, {})
        result[name] = value
    return result


def no_actions(app, reason):
    return {'complete': True, 'interrupted': False, 'all_verified': False,
            'reason': reason, 'containers': {n: {'status': 'not_attempted', 'reason': reason,
                'before': v, 'action_count': 0} for n, v in plan(app).items()}}


def safe_error(exc):
    return str(exc) if isinstance(exc, AppError) else type(exc).__name__


def quick_storage(w, request=None):
    current = w.snapshot()
    if not current['healthy']:
        raise StorageLost('Storage unavailable/unsafe: ' + current['detail'])
    if request is not None:
        try:
            w.require_configuration(request)
        except (w.Unsafe, OSError, ValueError):
            raise StorageLost('Configuration changed during recovery; further Docker actions stopped.') from None
        state = w.load_state(w.STATE_DIR / 'state.json')
        i = state['incident']
        if (not i or i['id'] != request['incident'] or i['phase'] != 'applications'
                or i['boot'] != request['boot'] or state['candidate'] is not True):
            raise StorageLost('Incident/boot/storage observation changed; further Docker actions stopped.')


def direct_storage(w, request=None):
    quick_storage(w, request)
    try:
        dev = w.verify_main()
        return dev
    except (w.Unsafe, OSError, ValueError) as exc:
        detail = str(exc) if isinstance(exc, w.Unsafe) else type(exc).__name__
        raise StorageLost('Storage direct verification failed: ' + detail) from None


def registered_images(w, configuration=None):
    c = configuration if configuration is not None else w.SETTINGS
    result = list(w.settings.storage_images(c, enabled=False))
    legacy = c.get('dependent', {})
    if not legacy.get('enabled') and legacy.get('uuid') and legacy.get('mountpoint') and legacy.get('image'):
        result.insert(0, dict(legacy, name=Path(legacy['image']).stem))
    return result


def required_images(w, paths, configuration=None):
    """Infer image dependencies from binds, including recursive submounts and parents."""
    images = registered_images(w, configuration)
    required = {item['mountpoint'] for item in images if any(
        w.covers(item['mountpoint'], path) or w.covers(path, item['mountpoint']) for path in paths)}
    while True:
        before = set(required)
        for item in images:
            if item['mountpoint'] in required:
                required.update(parent['mountpoint'] for parent in images if parent is not item and
                    (w.covers(parent['mountpoint'], item['image']) or w.covers(parent['mountpoint'], item['mountpoint'])))
        if before == required:
            return [item for item in images if item['mountpoint'] in required]


def source_proof(w, name, request=None):
    return path_proof(w, APPS[name]['source'], request)


def path_proof(w, path, request=None):
    dev = direct_storage(w, request)
    source = Path(path)
    if not w.covers(w.MOUNT, str(source)):
        raise AppError('Application source is outside the selected storage; untouched.')
    for p in [*reversed(source.parents), source]:
        if p.is_symlink():
            raise AppError('Symlink in application source; untouched.')
    dependencies = required_images(w, [str(source)])
    for item in dependencies:
        if not item['enabled']:
            raise AppError('Required image '+item['name']+' has Mount on recovery disabled; container left untouched.')
        try:
            w.verify_dependent(item)
        except (w.Unsafe, OSError, ValueError) as exc:
            detail = str(exc) if isinstance(exc, w.Unsafe) else type(exc).__name__
            raise AppError('Required image '+item['name']+' is not ready: '+detail) from None
    expected = max([w.MOUNT] + [item['mountpoint'] for item in dependencies if w.covers(item['mountpoint'], str(source))], key=len)
    mount = w.visible_mount(w.read_rows(), str(source))
    if mount and expected != w.MOUNT:
        dev = mount['dev']
    info = source.stat()
    if (mount is None or mount['target'] != expected or mount['dev'] != dev
            or not stat.S_ISDIR(info.st_mode)
            or f'{os.major(info.st_dev)}:{os.minor(info.st_dev)}' != dev):
        raise AppError('Application source is not a directory on the recovered Storage; untouched.')
    return dev, info.st_dev, info.st_ino


def namespace_proof(w, name, current, proof):
    return path_namespace_proof(w, APPS[name]['source'], APPS[name]['destination'], current, proof)


def path_namespace_proof(w, source, destination, current, proof, writable=True):
    pid = current['pid']
    if type(pid) is not int or pid <= 0:
        raise AppError('Container has no live PID.')
    rows = w.parse_mounts(Path(f'/proc/{pid}/mountinfo').read_text())
    mount = w.visible_mount(rows, destination)
    base = max([w.MOUNT] + [item['mountpoint'] for item in registered_images(w)
                           if w.covers(item['mountpoint'], source)], key=len)
    if (mount is None or mount['target'] != destination or mount['dev'] != proof[0]
            or mount['root'] != (source[len(base):] or '/') or mount['fs'] != 'ext4'
            or writable and any('ro' in opts or 'rw' not in opts for opts in (mount['vfs'], mount['super']))):
        raise AppError('Container namespace has a stale/wrong/read-only Storage mount.')
    info = Path(f'/proc/{pid}/root{destination}').stat()
    if (info.st_dev, info.st_ino) != proof[1:]:
        raise AppError('Inside-container bind inode/device differs from recovered source.')


def required_bindings(w, name, current, request=None, namespace=False):
    """Every mapped folder on this drive is checked, not just the chosen primary bind."""
    paths = [m['Source'] for m in current['mounts'] if m.get('Type') == 'bind']
    if getattr(w, 'drives', None):
        w.drives.verify_other_storage(w, paths)
    for mount in current['mounts']:
        source = mount.get('Source') or ''
        if source and source != w.MOUNT and w.covers(source, w.MOUNT):
            raise AppError('A mapped parent folder includes this drive. Map the specific storage folders before enabling container restart after drive recovery.')
        if mount.get('Type') != 'bind' and source and w.covers(w.MOUNT, source):
            raise AppError('Storage on this drive must use explicit bind folders for verified container restarts.')
        if mount.get('Type') != 'bind' or not w.covers(w.MOUNT, mount['Source']):
            continue
        if mount.get('Propagation') != 'rprivate' or type(mount.get('RW')) is not bool:
            raise AppError('Required storage needs a private, known bind mount; untouched.')
        primary = mount['Source'] == APPS[name]['source'] and mount['Destination'] == APPS[name]['destination']
        if not primary:
            proof = path_proof(w, mount['Source'], request)
            if namespace:
                path_namespace_proof(w, mount['Source'], mount['Destination'], current, proof, mount['RW'])
        if namespace:
            for image in required_images(w, [mount['Source']]):
                if image['mountpoint'] != mount['Source'] and w.covers(mount['Source'], image['mountpoint']):
                    destination = mount['Destination'].rstrip('/') + image['mountpoint'][len(mount['Source']):]
                    image_proof = path_proof(w, image['mountpoint'], request)
                    path_namespace_proof(w, image['mountpoint'], destination, current, image_proof, mount['RW'])


def required_storage_labels(w, current):
    paths = [m['Source'] for m in current['mounts'] if m.get('Type') == 'bind']
    configurations = [w.SETTINGS]
    if getattr(w, 'drives', None):
        configurations += [w.drives.read(w.settings, path) for _, path in w.drives.files(w.settings) if path != w.CONFIG]
    labels = []
    for c in configurations:
        if any(w.covers(c['disk']['mountpoint'], path) for path in paths):
            labels.append(c['disk'].get('label') or c['disk']['mountpoint'])
            labels.extend('image: '+item['name'] for item in required_images(w, paths, c))
    return labels


def storage_warnings(w, name, current):
    """Read-only advice. Every failure here is a warning, never a restart gate."""
    warnings = []
    try:
        paths = [m.get('Source', '') for m in current.get('mounts', []) if m.get('Source')]
        for item in required_images(w, paths):
            try:
                w.verify_dependent(item)
            except (w.Unsafe, OSError, ValueError, KeyError, TypeError) as exc:
                warnings.append('Docker storage uses image ' + item['name'] +
                                ', which is not verified mounted. Choose this image in the container settings if it must be mounted before startup.')
    except (w.Unsafe, OSError, ValueError, KeyError, TypeError, AppError):
        warnings.append('Docker storage advice is unavailable. Your explicit disk and image selections still control startup.')
    return warnings


def prepare_images(w, request, value):
    """Attempt explicitly selected images once, after ordinary recovery images.

    Only images explicitly selected by the user are start prerequisites.
    Docker bind detection stays advisory; unrelated recovery images do not gate.
    """
    latest = READER().get('docker_containers') if READER else None
    chosen = {identity for name, spec in APPS.items() if selected_now(name)
              for identity in spec.get('images', [])
              if latest is None or any(v['name'] == name and identity in v.get('images', []) for v in latest)}
    records = value.setdefault('images', {})
    state = w.load_state(w.STATE_DIR / 'state.json')
    incident = state.get('incident') or {}
    earlier = {item['uuid']: item for item in (incident.get('result') or {}).get('images', [])}
    registered = {item['uuid']: item for item in registered_images(w)}
    ordered = [identity for identity in registered if identity in chosen]
    ordered.extend(sorted(chosen - set(ordered)))
    for identity in ordered:
        if identity in records:
            if records[identity].get('status') == 'intent':
                records[identity].update(status='warning', detail='Previous image mount outcome is uncertain; not repeated.')
                save(w, value)
            continue
        item = registered.get(identity)
        if identity in earlier:
            previous = earlier[identity]
            records[identity] = dict(name=previous.get('name', identity),
                status='mounted' if previous.get('healthy') else 'warning',
                detail=previous.get('detail', ''), attempted_by='drive_recovery')
            save(w, value)
            continue
        if item is None:
            records[identity] = dict(name=identity, status='warning',
                detail='Selected image is no longer configured. Select an available image before automatic container start.')
            save(w, value)
            continue
        direct_storage(w, request)
        record = records[identity] = dict(name=item['name'], status='intent', attempted_at=w.timestamp())
        save(w, value)  # Mount reservation survives crashes, just like Docker intent.
        def note(target, stage, detail=''):
            record.setdefault('actions', []).append(dict(target=target, stage=stage, detail=detail, time=w.timestamp()))
            save(w, value)
        try:
            w.recover_image(item, request | {'allow_mount': True, 'blocked': []}, note)
            record.update(status='mounted', detail='Selected image mounted and verified.')
        except (w.Unsafe, OSError, ValueError, KeyError, TypeError) as exc:
            record.update(status='warning', detail=str(exc) + ' Containers requiring this selected image stay stopped.')
        record['finished_at'] = w.timestamp()
        save(w, value)
        direct_storage(w, request)


def verify_container(w, docker, name, entry, request=None, wait=True):
    """Verify restart/runtime results without executing or proving storage access."""
    deadline = time.monotonic() + (HEALTH_TIMEOUT if wait else 0)
    while True:
        quick_storage(w, request)
        current = docker.inspect(name)
        validate_container(name, current, entry.get('container_id') or entry['before'].get('id'))
        okay = (current['running'] and not current['paused'] and not current['restarting']
                and not current['dead'] and (not current['healthcheck'] or current['health'] == 'healthy')
                and (not entry.get('before_started_at') or current['started_at'] != entry['before_started_at']))
        if okay:
            return {'running': True, 'health': current['health'] if current['healthcheck'] else 'no healthcheck',
                    'storage_access_checked': False, 'started_at': current['started_at']}
        if time.monotonic() >= deadline:
            raise AppError('Restart was requested, but running/new start/health verification did not succeed within its deadline.')
        time.sleep(1)


def ledger_path(w):
    return w.STATE_DIR / 'app-recovery.json'


def read_ledger(w, incident, archive=False):
    try:
        raw = ledger_path(w).read_text()
        value = json.loads(raw)
    except FileNotFoundError:
        return None
    if (not isinstance(value, dict) or value.get('version') != 1
            or not isinstance(value.get('incident'), str) or not value['incident']
            or not isinstance(value.get('containers'), dict)
            or type(value.get('complete')) is not bool):
        raise AppError('Invalid application ledger; no Docker mutations permitted.')
    for name, item in value['containers'].items():
        if (not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name)
                or not isinstance(item, dict)
                or item.get('status') not in ('pending', 'waiting_storage', 'intent', 'verified', 'already_running', 'failed', 'not_attempted', 'preserved_stopped')
                or type(item.get('action_count')) is not int or item['action_count'] not in (0, 1)
                or (item['status'] in ('intent', 'verified') and item['action_count'] != 1)
                or (item['status'] in ('pending', 'waiting_storage', 'already_running', 'preserved_stopped') and item['action_count'] != 0)
                or (value['complete'] and item['status'] in ('pending', 'waiting_storage', 'intent'))):
            raise AppError('Invalid per-container action state; retained for manual review.')
    if value.get('incident') != incident:
        if not value['complete']:
            raise AppError('An older application recovery is unresolved; no new actions.')
        # Completed history belongs to its original selection. Only a current
        # incident must match today's selection. Preserve old evidence before
        # replacing it, under the application lock held by recover().
        if archive:
            directory = w.STATE_DIR / 'application-history'
            directory.mkdir(mode=0o700, exist_ok=True)
            name = hashlib.sha256(raw.encode()).hexdigest() + '.json'
            w.atomic_write(directory / name, raw)
        return None
    return value


def save(w, value):
    w.atomic_write(ledger_path(w), json.dumps(value, indent=2, allow_nan=False) + '\n')


@contextmanager
def container_action(w, name, identity, request, healthy=True):
    """Serialize the same container across independent watched-drive incidents."""
    if not re.fullmatch('[0-9a-f]{64}', identity):
        raise AppError('Container identity is invalid.')
    directory = w.drives.roots(w.settings)[1] / 'shared-locks'
    deadline = time.monotonic() + max(1, WORK_TIMEOUT - 15)
    while True:
        operation = w.drives.lock(directory, 'docker-restart-' + identity + '.lock')
        try:
            operation.__enter__()
            break
        except BlockingIOError:
            if healthy:
                quick_storage(w, request)
            else:
                w.require_configuration(request)
            if time.monotonic() >= deadline:
                raise AppError('Another operation controls this container; no overlapping command was sent.') from None
            time.sleep(.25)
    try:
        yield
    finally:
        operation.__exit__(None, None, None)


def selected_image_ids(name):
    identities = APPS[name].get('images', [])
    if READER:
        rows = READER().get('docker_containers')
        if rows is not None:
            latest = next((row for row in rows if row['name'] == name), {})
            identities = [identity for identity in identities if identity in latest.get('images', [])]
    return identities


def selected_images_ready(w, name, value):
    registered = {item['uuid']: item for item in registered_images(w)}
    for identity in selected_image_ids(name):
        item = registered.get(identity)
        if item is None:
            raise AppError('A selected virtual image is no longer configured. Container stays stopped.')
        record = value.get('images', {}).get(identity)
        if not record or record.get('status') != 'mounted':
            reason = (record or {}).get('detail') or 'Mount was not confirmed.'
            raise AppError('Selected virtual image ' + item['name'] + ' is not mounted. Container stays stopped. ' + reason)
        try:
            w.verify_dependent(item)
        except (w.Unsafe, OSError, ValueError) as exc:
            raise AppError('Selected virtual image ' + item['name'] + ' could not be verified. Container stays stopped. ' + str(exc)) from None


def other_selected_storage(w, name, identity):
    """Explicit user choices on other drives are prerequisites, never inferred binds."""
    if not getattr(w, 'drives', None):
        return
    _, state_root = w.drives.roots(w.settings)
    for identifier, path in w.drives.files(w.settings):
        if path == w.CONFIG:
            continue
        config = w.drives.read(w.settings, path)
        selected = next((item for item in config['docker']['containers'] if item['name'] == name
                         and (not item.get('container_id') or item['container_id'] == identity)), None)
        if not config['docker']['enabled'] or not selected:
            continue
        label = config['disk'].get('label') or config['disk']['mountpoint']
        try:
            rows = w.read_rows()
            dev = w.device_number('/dev/disk/by-uuid/' + config['disk']['uuid'])
            w.mounted_checks(rows, config['disk']['mountpoint'], dev, config['disk']['uuid'])
            directory = state_root if identifier == 'legacy' else state_root / 'drives' / identifier
            other = SimpleNamespace(**vars(w))
            other.DISK_UUID, other.SETTINGS, other.STATE_DIR = config['disk']['uuid'], config, directory
            w.drives.verify_hardware(other, dev, config['disk']['uuid'])
            registered = {item['uuid']: item for item in registered_images(w, config)}
            for image_id in selected.get('images', []):
                if image_id not in registered:
                    raise AppError('A selected virtual image is no longer configured.')
                w.verify_dependent(registered[image_id])
            directory = state_root if identifier == 'legacy' else state_root / 'drives' / identifier
            try:
                state = json.loads((directory / 'state.json').read_text())
            except FileNotFoundError:
                state = {}
            incident = state.get('incident') or {}
            stop = incident.get('stop') or incident.get('stop_state') or {}
            if incident and incident.get('phase') != 'done' and stop and (
                    stop.get('phase') != 'done' or not (stop.get('result') or {}).get('all_stopped')):
                raise AppError('Its container-stop stage has not completed.')
        except (w.Unsafe, AppError, OSError, ValueError, KeyError, TypeError) as exc:
            raise StorageWaiting('Waiting for selected drive ' + label + ' and its selected images. ' +
                                 (str(exc) if isinstance(exc, (w.Unsafe, AppError)) else type(exc).__name__)) from None


class StorageWaiting(AppError):
    pass


def recover(w, request, docker=None):
    docker = docker or Docker()
    with (w.STATE_DIR / 'applications.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        value = read_ledger(w, request['incident'], archive=True)
        previous_boot = None
        if value is not None and value.get('boot') and value['boot'] != request['boot']:
            # A start intent from an earlier host boot cannot still be executing.
            # A fresh verified stop in this boot gives this recovery a new start
            # epoch. Keep the old receipt before replacing any action budgets.
            stopped = read_stop_ledger(w, request['incident'])
            if (request['boot'] != w.boot_id() or not isinstance(stopped, dict)
                    or stopped.get('boot') != request['boot']
                    or stopped.get('complete') is not True or stopped.get('all_stopped') is not True):
                raise AppError('A previous-boot container start is unresolved. Confirm a fresh container stop in this boot before starting again.')
            previous_boot = value['boot']
            raw = ledger_path(w).read_text()
            history = w.STATE_DIR / 'application-history'
            history.mkdir(mode=0o700, exist_ok=True)
            w.atomic_write(history / ('start-epoch-' + hashlib.sha256(raw.encode()).hexdigest() + '.json'), raw)
            request = dict(request, stop=stopped)
            value = None
        if value is None:
            value = {'version': 1, 'incident': request['incident'], 'boot': request['boot'],
                     'complete': False, 'interrupted': False, 'containers': {}}
            if previous_boot:
                value['previous_boot'] = previous_boot
        # An existing incident ledger owns its action budgets even if selections
        # were edited. Removed selections are never replayed; new ones get one.
        if not value['complete']:
            for name in APPS:
                value['containers'].setdefault(name, dict(before=request.get('plan', {}).get(name, {}),
                                                         status='pending', action_count=0))
        save(w, value)
        value['storage_verified'] = False
        value['waiting_storage'] = False
        try:
            if 'stop' in request and not (isinstance(request['stop'], dict) and request['stop'].get('all_stopped') is True):
                raise StorageLost('Selected containers have not been confirmed stopped. Recovery cannot start them.')
            direct_storage(w, request)
            if not value['complete']:
                prepare_images(w, request, value)
            for name, entry in value['containers'].items():
                if entry['status'] not in ('pending', 'waiting_storage', 'intent'):
                    continue
                try:
                    if name not in APPS or not selected_now(name):
                        entry.update(status='not_attempted' if not entry['action_count'] else 'failed',
                                     reason='Container recovery selection was disabled; no new start was sent.')
                        save(w, value)
                        continue
                    direct_storage(w, request)
                    current = docker.inspect(name)
                    validate_container(name, current, entry.get('container_id') or entry['before'].get('id'))
                    entry['container_id'] = current['id']
                    entry['warnings'] = storage_warnings(w, name, current)
                    entry['warnings'] += [v['name'] + ': ' + v['detail'] for identity, v in value.get('images', {}).items()
                                          if identity in APPS[name].get('images', []) and v['status'] != 'mounted']
                    selected_images_ready(w, name, value)
                    with container_action(w, name, current['id'], request):
                        if getattr(w, 'manual_intent', None) and w.manual_intent.stopped(w, current['id']):
                            # A deliberate stop never erases an earlier uncertain
                            # start or substitutes intent for observed runtime.
                            if entry['action_count']:
                                raise AppError('Safe unmount withholds further startup. The earlier start attempt remains recorded; review its outcome.')
                            held_current = docker.inspect(name)
                            validate_container(name, held_current, current['id'])
                            if any(held_current.get(key) is not False for key in ('running', 'paused', 'restarting')):
                                raise AppError('Safe unmount withholds startup, but Docker does not report this app stopped. Check its current state; no new start was sent.')
                            entry.update(status='preserved_stopped', action='none', action_count=0,
                                         reason='Deliberate safe unmount keeps this app stopped. Mounting storage does not start it; use Start app explicitly.')
                            save(w, value)
                            continue
                        other_selected_storage(w, name, current['id'])
                        selected_images_ready(w, name, value)
                        current = docker.inspect(name)
                        validate_container(name, current, entry['container_id'])
                        stopped = (request.get('stop') or {}).get('containers', {}).get(name, {})
                        if 'stop' in request and not (stopped.get('container_id') == current['id']
                                and stopped.get('status') in ('stopped', 'already_stopped')):
                            raise AppError('This selected container has no verified stop for this outage. No start was sent.')
                        if (entry['status'] in ('pending', 'waiting_storage') and current['running']
                                and stopped.get('container_id') == current['id']
                                and stopped.get('status') in ('stopped', 'already_stopped')
                                and stopped.get('before_started_at')
                                and current['started_at'] != stopped['before_started_at']):
                            # A second selected drive (or the user) has already
                            # started it after this outage's verified stop.
                            entry.update(status='already_running', action='none', action_count=0,
                                         before_started_at=stopped['before_started_at'])
                            entry['verification'] = verify_container(w, docker, name, entry, request)
                            entry.update(finished_at=w.timestamp(), reason='Container is already running from a new start after the outage. No duplicate start was sent.')
                            save(w, value)
                            continue
                        if entry['status'] in ('pending', 'waiting_storage'):
                            # The incident stop stage completed before disk recovery.
                            # Start the selected container only after its prerequisites.
                            entry.update(status='intent', action='start', action_count=1,
                                         attempted_at=w.timestamp(), before_started_at=current['started_at'])
                            save(w, value)
                            direct_storage(w, request)
                            if not selected_now(name, current['id']):
                                raise AppError('Container was deselected before the restart request was sent.')
                            try:
                                docker.change(name, current['id'], 'start')
                                entry['api_accepted_at'] = w.timestamp()
                            except AppError as exc:
                                entry['api_error'] = str(exc)  # Unknown acceptance never permits a repeat.
                            save(w, value)
                        else:
                            entry['resumed_verification_only_at'] = w.timestamp()
                        entry['verification'] = verify_container(w, docker, name, entry, request)
                        entry.update(status='verified', finished_at=w.timestamp(), reason=
                            'Container started after drive and selected-image recovery. Running state and configured health check verified; application file access was not tested.')
                except StorageLost:
                    raise
                except StorageWaiting as exc:
                    entry.update(status='waiting_storage', reason=str(exc))
                    value['waiting_storage'] = True
                except (AppError, w.Unsafe, OSError, ValueError, KeyError, TypeError) as exc:
                    entry.update(status='failed', finished_at=w.timestamp(), reason=safe_error(exc))
                save(w, value)
            for name, entry in value['containers'].items():
                if entry['status'] in ('verified', 'already_running') and name in APPS:
                    try:
                        entry['verification'] = verify_container(w, docker, name, entry, request, wait=False)
                    except StorageLost:
                        raise
                    except (AppError, w.Unsafe, OSError, ValueError, KeyError, TypeError) as exc:
                        entry.update(status='failed', reason='Final verification: ' + safe_error(exc))
            direct_storage(w, request)
            value['storage_verified'] = True
        except StorageLost as exc:
            value.update(interrupted=True, waiting_storage=False, reason=str(exc))
            for entry in value['containers'].values():
                if entry['status'] in ('pending', 'waiting_storage', 'intent'):
                    entry.update(status='not_attempted' if not entry['action_count'] else 'failed',
                                 reason='Storage recovery interrupted; no further Docker actions.')
        value.update(complete=not value.get('waiting_storage', False), finished_at=w.timestamp(), all_verified=all(
            e['status'] in ('verified', 'already_running', 'preserved_stopped') for e in value['containers'].values()))
        save(w, value)
        return value


def preflight(w, docker=None):
    """Read-only identity/runtime check with storage advice; never starts a container."""
    docker = docker or Docker()
    result = {}
    for name in APPS:
        try:
            current = docker.inspect(name)
            validate_container(name, current)
            result[name] = {'id': current['id'], 'running': current['running'], **APPS[name],
                            'warnings': storage_warnings(w, name, current),
                            'verification': {'running': current['running'], 'health': current.get('health'),
                                             'storage_access_checked': False}}
        except (AppError, w.Unsafe, OSError, ValueError, KeyError, TypeError) as exc:
            raise AppError(name + ': ' + safe_error(exc)) from None
    return result


def interrupted(w, incident, app, reason):
    value = no_actions(app, reason)
    value['interrupted'] = True
    def close_record(record):
        for entry in record['containers'].values():
            if entry['status'] in ('pending', 'waiting_storage', 'intent'):
                entry.update(status='failed' if entry['action_count'] else 'not_attempted', reason=reason)
        record.update(complete=True, interrupted=True, all_verified=False, reason=reason)
        return record
    # Atomic ledger reads remain safe while a dying worker owns the lock. Include
    # its reserved action in the email even if we cannot yet close that ledger.
    try:
        old = read_ledger(w, incident)
        if old:
            value = close_record(old)
    except (OSError, ValueError, AppError):
        value['ledger_warning'] = 'Application progress unavailable; action results uncertain.'
    try:
        with (w.STATE_DIR / 'applications.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            old = read_ledger(w, incident)
            if old:
                value = close_record(old)
                save(w, value)
    except (OSError, ValueError, AppError):
        value['ledger_warning'] = 'Progress could not be closed; retained and never replayed blindly.'
    return value


def recover_services(w, request):
    """One durable restart intent per explicitly selected application service."""
    units = w.SETTINGS['services']['units']
    path = w.STATE_DIR / ('services-' + request['incident'] + '.json')
    value = json.loads(path.read_text()) if path.exists() else {}
    for unit in units:
        if unit in value:
            continue  # An uncertain restart is never repeated after a crash.
        try:
            quick_storage(w, request)
            w.verify_dependent()
            if not w.config_load()['automatic_recovery']:
                raise AppError('Automatic recovery is disabled.')
            value[unit] = dict(status='intent', time=w.timestamp())
            w.atomic_write(path, json.dumps(value) + '\n')
            w.command(['/usr/bin/systemctl', 'restart', '--', unit], timeout=20)
            w.command(['/usr/bin/systemctl', 'is-active', '--quiet', '--', unit], timeout=5)
            quick_storage(w, request)
            value[unit]['status'] = 'verified'
        except (OSError, ValueError, w.Unsafe, AppError) as exc:
            value[unit] = dict(status='failed', reason=str(exc))
        w.atomic_write(path, json.dumps(value) + '\n')
    return value
