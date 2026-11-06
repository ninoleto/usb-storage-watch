# SPDX-License-Identifier: MIT
"""Opt-in boot startup, independent of drive monitors and outage selections."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True


def paths(b):
    config, state = b.cli.drives.roots(b.s)
    return config / 'boot-start.json', state / 'boot-start'


def read(b):
    path, _ = paths(b)
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return dict(version=1, containers=[])
    if set(value) != {'version', 'containers'} or value['version'] != 1 or not isinstance(value['containers'], list):
        raise ValueError('Boot startup settings are invalid; no start is permitted.')
    ids = set()
    for item in value['containers']:
        if (set(item) != {'id', 'name', 'enabled', 'drives'} or type(item['enabled']) is not bool
                or not isinstance(item['id'], str) or not re.fullmatch('[0-9a-f]{64}', item['id'])
                or item['id'] in ids or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', item['name'])
                or not isinstance(item['drives'], list)):
            raise ValueError('Invalid boot container selection.')
        validate_item(b, item)
        ids.add(item['id'])
        selected = set()
        for drive in item['drives']:
            if set(drive) != {'id', 'images'} or not isinstance(drive['images'], list):
                raise ValueError('Invalid boot storage selection.')
            b.cli.drives.profile_id(drive['id'])
            if drive['id'] in selected or len(set(drive['images'])) != len(drive['images']):
                raise ValueError('Duplicate boot storage selection.')
            selected.add(drive['id'])
            for image in drive['images']:
                if str(uuid.UUID(image)) != image: raise ValueError('Invalid boot image identity.')
    return value


def state(b, identity):
    _, directory = paths(b)
    try:
        value = json.loads((directory / (identity + '.json')).read_text())
    except FileNotFoundError:
        value = {}
    if value.get('boot') != b.w.boot_id():
        return dict(boot=b.w.boot_id(), phase='waiting', mounts={}, message='Waiting for boot startup prerequisites.')
    if (value.get('phase') not in ('waiting', 'intent', 'verified', 'failed', 'cancelled')
            or not isinstance(value.get('mounts'), dict)
            or any(not isinstance(key, str) or status not in ('intent', 'uncertain', 'verified')
                   for key, status in value['mounts'].items())):
        raise ValueError('Boot startup receipt is invalid; no action was repeated.')
    return value


def save_state(b, identity, value):
    _, directory = paths(b)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    b.w.atomic_write(directory / (identity + '.json'), json.dumps(value) + '\n')


def public(b):
    try: value = read(b)
    except (OSError, ValueError, TypeError, KeyError):
        return dict(revision=None, settings=[], results={}, error='Boot settings could not be read safely. Recovery settings and manual controls remain available.')
    results = {}
    for item in value['containers']:
        try: results[item['id']] = state(b, item['id'])
        except (ValueError, OSError): results[item['id']] = dict(phase='failed', message='Boot receipt needs review; no start will be repeated.')
    return dict(revision=b.s.digest(value), settings=value['containers'],
                results=results)


def recovery_idle(b, records, name):
    _, root = b.cli.drives.roots(b.s)
    for drive, c in records:
        if not c['docker']['enabled'] or not any(v['name'] == name for v in c['docker']['containers']): continue
        directory = root if drive == 'legacy' else root / 'drives' / drive
        try: incident = json.loads((directory / 'state.json').read_text()).get('incident') or {}
        except FileNotFoundError: incident = {}
        if incident.get('boot') == b.w.boot_id() and incident.get('phase') != 'done':
            raise ValueError('Waiting for the selected container’s active recovery incident.')


def validate_storage(b, item, records):
    configs = dict(records)
    for choice in item['drives']:
        if choice['id'] not in configs:
            raise ValueError('A selected boot drive is no longer configured.')
        c = configs[choice['id']]
        images = b.s.storage_images(c, False)
        selected = set(choice['images'])
        if not selected <= {i['uuid'] for i in images}:
            raise ValueError('A selected boot image is no longer configured.')
        for image in images:
            if image['uuid'] not in selected: continue
            for parent in images:
                if parent != image and any(b.s.below(parent['mountpoint'], image[key]) for key in ('image', 'mountpoint')):
                    if parent['uuid'] not in selected:
                        raise ValueError('Explicitly select the parent image required by ' + image['name'] + '.')


def update(fleet, data):
    b = fleet.context()
    if set(data) != {'revision', 'container'}:
        raise ValueError('Review boot startup settings before saving.')
    item = data['container']
    if not isinstance(item, dict) or set(item) != {'id','name','enabled','drives'}:
        raise ValueError('Invalid boot startup selection.')
    validate_item(b, item)
    with fleet.mutex, b.common.module('app_control').operation(fleet, item['id']), b.cli.drives.configuration_lock(b.s):
        old = read(b)
        if data['revision'] != b.s.digest(old):
            raise ValueError('Boot settings changed. Refresh before saving.')
        records = [(i, c) for i, c, error in fleet.records() if not error]
        if item['enabled']:
            validate_storage(b, item, records)
            if not item['drives']:
                raise ValueError('Select at least one boot disk; images are optional.')
            docker_module = b.common.module('web_docker')
            docker, _ = docker_module.client(b, records)
            current = docker.inspect(item['id'])
            if current['id'] != item['id'] or current['name'] != item['name']:
                raise ValueError('Container identity changed; refresh before saving.')
            policy = docker.request('GET', '/containers/' + item['id'] + '/json')['HostConfig']['RestartPolicy']['Name']
            if policy not in ('', 'no'):
                raise ValueError('Set this container’s Docker restart policy to no before enabling Storage Watch boot startup.')
        new = dict(version=1, containers=[v for v in old['containers'] if v['id'] != item['id']] + [item])
        b.cli.save(paths(b)[0], new)
        return public(b) | dict(message='Boot startup settings saved. Enabled containers are scheduled once this boot when their selected storage is ready.')


def validate_item(b, item):
    if (type(item['enabled']) is not bool or not isinstance(item['id'], str)
            or not re.fullmatch('[0-9a-f]{64}', item['id']) or not isinstance(item['name'], str)
            or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', item['name'])
            or not isinstance(item['drives'], list)):
        raise ValueError('Invalid boot container selection.')
    if item['enabled'] and not item['drives']:
        raise ValueError('Select at least one boot disk; images are optional.')
    seen = set()
    for choice in item['drives']:
        if not isinstance(choice, dict) or set(choice) != {'id', 'images'} or not isinstance(choice['images'], list):
            raise ValueError('Invalid boot disk selection.')
        b.cli.drives.profile_id(choice['id'])
        if choice['id'] in seen or len(set(choice['images'])) != len(choice['images']):
            raise ValueError('Duplicate boot selection.')
        seen.add(choice['id'])
        for image in choice['images']:
            if not isinstance(image, str) or str(uuid.UUID(image)) != image:
                raise ValueError('Invalid boot image selection.')


def cancel(b, identity):
    """Called while the manual container action lock is held, even if already stopped."""
    if any(v['id'] == identity and v['enabled'] for v in read(b)['containers']):
        value = state(b, identity)
        value.update(phase='cancelled', message='Manual stop cancelled boot startup for this boot.')
        save_state(b, identity, value)


def engine(b, identifier, c):
    config, root = b.cli.drives.roots(b.s)
    w = b.common.module('engine', dict(id=identifier, config_root=str(config), state_root=str(root)))
    w.configure(c)
    return w


def mount_once(b, w, identity, value, key, verify, mount):
    try:
        verify()
        value['mounts'][key] = 'verified'
        save_state(b, identity, value)
        return
    except (OSError, ValueError, w.Unsafe):
        if value['mounts'].get(key) in ('intent', 'uncertain'):
            value['phase'] = 'failed'
            raise ValueError('An earlier boot mount has an uncertain outcome; it was not replayed.') from None
    def note(*args):
        if len(args) > 1 and args[1] == 'intent':
            value['mounts'][key] = 'intent'
            save_state(b, identity, value)
    mount(note)
    verify()
    value['mounts'][key] = 'verified'
    save_state(b, identity, value)


def run_container(b, item, records, docker):
    identity = item['id']
    validate_storage(b, item, records)
    configs = dict(records)
    contexts = [(choice, engine(b, choice['id'], configs[choice['id']])) for choice in sorted(item['drives'], key=lambda v:v['id'])]
    _, root = b.cli.drives.roots(b.s)
    with ExitStack() as held:
        # Match recovery's storage-before-container lock order; no monitor stop.
        fds = [held.enter_context(b.cli.drives.lock(w.STATE_DIR, 'recovery.lock')) for _, w in contexts]
        fds.append(held.enter_context(b.cli.drives.lock(root / 'shared-locks', 'docker-restart-' + identity + '.lock')))
        value = state(b, identity)
        if value['phase'] in ('verified', 'cancelled', 'failed'): return
        if item not in read(b)['containers']: return
        intent = b.common.module('manual_intent')
        if any(intent.read(root, choice['id'], b.w.boot_id()) for choice in item['drives']):
            value.update(phase='cancelled', message='Safe unmount cancelled startup for this computer session. Mounting storage does not start apps.')
            save_state(b, identity, value)
            return
        recovery_idle(b, records, item['name'])
        current = docker.inspect(identity)
        if current['id'] != identity or current['name'] != item['name']:
            raise ValueError('Container identity changed; no start was sent.')
        if current['paused'] or current['dead'] or current['restarting']:
            raise ValueError('Container runtime state is not ready for boot startup.')
        policy = docker.request('GET', '/containers/' + identity + '/json')['HostConfig']['RestartPolicy']['Name']
        if policy not in ('', 'no'): raise ValueError('Waiting: Docker restart policy must be no for a single boot startup owner.')
        try:
            for choice, w in contexts:
                w.WORKER_LOCK_FDS = tuple(fds)
                w.MANUAL_MOUNT = True
                # Never mount beneath an already running container or replay an uncertain start.
                if current['running'] or value['phase'] == 'intent':
                    w.verify_main()
                else:
                    mount_once(b, w, identity, value, w.DISK_UUID, w.verify_main, w.mount_main)
                for image in w.settings.storage_images(w.SETTINGS, False):
                    if image['uuid'] not in choice['images']: continue
                    if current['running'] or value['phase'] == 'intent':
                        w.verify_dependent(image)
                    else:
                        mount_once(b, w, identity, value, image['uuid'], lambda i=image:w.verify_dependent(i),
                                   lambda note,i=image:w.recover_image(i, dict(allow_mount=True, blocked=[]), note))
            def verify_storage():
                if item not in read(b)['containers']: raise ValueError('Boot startup was disabled or changed.')
                recovery_idle(b, records, item['name'])
                for choice, w in contexts:
                    if w.settings.digest(w.runtime_configuration()) != w.CONFIG_DIGEST:
                        raise ValueError('Storage settings changed during boot startup.')
                    w.verify_main()
                    for image in w.settings.storage_images(w.SETTINGS, False):
                        if image['uuid'] in choice['images']: w.verify_dependent(image)
            verify_storage()
            if value['phase'] == 'intent' and not current['running']:
                reason = 'Previous start outcome is uncertain or the container was stopped; no start was repeated.'
                value.update(phase='failed', message=reason + (' Previous error: ' + value['error'] if value.get('error') else ''))
                save_state(b, identity, value)
                return
            if not current['running']:
                value.update(phase='intent', message='Starting after verified boot storage.', started_at=b.w.timestamp())
                save_state(b, identity, value)  # Durable before the only POST.
                docker.request('POST', '/containers/' + identity + '/start', timeout=10, allowed_status=(304,))
            deadline = time.monotonic() + 120
            while True:
                verify_storage()
                current = docker.inspect(identity)
                if current['id'] != identity or current['name'] != item['name']: raise ValueError('Container identity changed during verification.')
                if (current['running'] and not any(current[k] for k in ('paused','dead','restarting'))
                        and (not current['healthcheck'] or current['health'] == 'healthy')): break
                if time.monotonic() >= deadline: raise ValueError('Container startup verification timed out; the start was not repeated.')
                time.sleep(1)
            value.update(phase='verified', message='Boot startup verified; later manual stops are respected.',
                         verified_at=b.w.timestamp(), health=current['health'] if current['healthcheck'] else 'no healthcheck')
            save_state(b, identity, value)
            if any(w.SETTINGS['notifications']['enabled'] for _, w in contexts):
                value['notification'] = 'intent'
                value['notification_attempted_at'] = b.w.timestamp()
                value['notification_id'] = str(uuid.uuid4())
                save_state(b, identity, value)
                payload = dict(id=value['notification_id'], subject='[Storage Watch] Boot startup verified',
                               body=item['name'] + ': selected boot disks/images and running state verified.\nHealth: ' + value['health'])
                try:
                    result = subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('notify.py')),'send','--json'],
                                            input=json.dumps(payload),text=True,capture_output=True,timeout=25)
                    value['notification'] = 'accepted' if result.returncode == 0 else 'failed'
                    value['notification_exit_status'] = result.returncode
                    if result.returncode:
                        value['notification_error'] = b.common.module('notify').delivery_diagnostic(result)
                except subprocess.SubprocessError:
                    value.update(notification='uncertain', notification_error='Notification process timed out or was interrupted; SMTP acceptance is unknown.')
                except OSError:
                    value.update(notification='failed', notification_error='Notification process could not be launched; check the installed worker and permissions.')
                save_state(b, identity, value)
        except Exception as exc:
            if value['phase'] != 'failed' and (value['phase'] == 'intent' or any(v == 'intent' for v in value['mounts'].values())):
                value['phase'] = 'intent' if value['phase'] == 'intent' else 'waiting'
            # DockerHTTPError already translates daemon responses to safe, useful
            # messages. Keep the original failure through later reconciliation.
            refusal = type(exc).__name__ == 'DockerHTTPError' and isinstance(getattr(exc, 'status', None), int)
            value['error'] = str(exc) if refusal or isinstance(exc, (ValueError, *(w.Unsafe for _,w in contexts))) else type(exc).__name__
            value['message'] = value['error']
            if refusal: value['phase'] = 'failed'
            save_state(b, identity, value)


def tick(b):
    _, root = b.cli.drives.roots(b.s)
    with b.cli.drives.lock(root / 'shared-locks', 'boot-start.lock'):
        with b.cli.drives.configuration_lock(b.s):
            value = read(b)
            records = [(i,b.cli.drives.read(b.s,p)) for i,p in b.cli.drives.files(b.s)]
        selected = [v for v in value['containers'] if v['enabled'] and state(b,v['id'])['phase'] not in ('verified','cancelled','failed')]
        if not selected: return
        docker, _ = b.common.module('web_docker').client(b, records)
        for item in selected:
            try: run_container(b,item,records,docker)
            except Exception as exc:
                # Waiting conditions do not consume a start. Never expose Docker bodies.
                receipt = state(b,item['id'])
                receipt['message'] = str(exc) if isinstance(exc,ValueError) else 'Waiting for Docker, storage or operation ownership: ' + type(exc).__name__
                save_state(b,item['id'],receipt)


if __name__ == '__main__':
    import importlib.util
    spec=importlib.util.spec_from_file_location('boot_common',Path(__file__).with_name('web_common.py'))
    common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
    b=common.module('web_broker')
    try: tick(b)
    except Exception as exc: print('Boot startup waiting: '+type(exc).__name__,flush=True)
