# SPDX-License-Identifier: MIT
"""Authenticated, explicitly confirmed ownership of one pinned container's policy."""
import copy
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

POLICIES = {'no', 'always', 'unless-stopped', 'on-failure'}
EXPLANATION = ('Storage Watch waits for your selected storage before computer-startup and disk-recovery starts. '
               'This sets Docker restart policy to no; it does not enable or change your storage selections. '
               'It does not provide a general application-crash restart watchdog.')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def policy(raw):
    value = raw.get('HostConfig', {}).get('RestartPolicy', {})
    name, count = value.get('Name') or 'no', value.get('MaximumRetryCount', 0)
    if name not in POLICIES or type(count) is not int or count < 0:
        raise ValueError('Docker restart policy could not be read safely.')
    return dict(Name=name, MaximumRetryCount=count)


def manager(raw):
    labels = raw.get('Config', {}).get('Labels') or {}
    if any(k.startswith('com.docker.swarm.') for k in labels): return 'Docker Swarm'
    if any(k.startswith('io.kubernetes.') for k in labels): return 'Kubernetes'
    if any(k.startswith(('io.portainer.', 'com.portainer.')) for k in labels): return 'Portainer'
    if any(k.startswith('com.docker.compose.') for k in labels): return 'Docker Compose'
    return 'Not identified'


def inspect(docker, identity, name):
    raw = docker.request('GET', '/containers/' + identity + '/json')
    if not isinstance(raw, dict) or raw.get('Id') != identity or raw.get('Name') != '/' + name:
        raise ValueError('Container identity changed; refresh and explicitly select it again.')
    policy(raw)
    return raw


def protected(raw):
    host = copy.deepcopy(raw['HostConfig']); host.pop('RestartPolicy', None)
    return digest(dict(id=raw['Id'], name=raw['Name'], image=raw.get('Image'), config=raw['Config'],
                       host=host, mounts=raw.get('Mounts'), networks=raw.get('NetworkSettings')))


def runtime(raw):
    state = raw['State']
    return dict(started=state['StartedAt'], running=state['Running'], paused=state['Paused'],
                restarting=state['Restarting'], dead=state['Dead'], count=raw.get('RestartCount'))


def directory(b, identity):
    return b.cli.drives.roots(b.s)[1] / 'docker-setup' / identity


def read(b, identity):
    try: value = json.loads((directory(b, identity) / 'record.json').read_text())
    except FileNotFoundError: return {}
    if (not isinstance(value, dict) or value.get('id') != identity
            or value.get('phase') not in ('intent', 'verified', 'rolled-back', 'uncertain')):
        raise ValueError('Previous Docker setup record needs review; no new update is allowed.')
    return value


def save(b, identity, value):
    path = directory(b, identity); path.mkdir(mode=0o700, parents=True, exist_ok=True)
    b.w.atomic_write(path / 'record.json', json.dumps(value, indent=2) + '\n')


def storage(b, items, identity, name):
    boot = b.common.module('boot_start').read(b)
    selected = next((v for v in boot['containers'] if v['id'] == identity and v['name'] == name), {})
    recovery = []
    for identifier, c in items:
        entry = next((v for v in c['docker']['containers'] if v['name'] == name and v.get('container_id') == identity), None)
        if c['docker']['enabled'] and entry: recovery.append(dict(id=identifier, images=entry.get('images', [])))
    return dict(boot=selected.get('drives', []) if selected.get('enabled') else [], recovery=recovery,
                revision=digest([items, boot]))


def summary(b, docker, identity, name):
    try:
        raw = inspect(docker, identity, name); current = policy(raw); owner = manager(raw)
        conflicts = []
        if current['Name'] != 'no': conflicts.append('Docker can restart this container independently of storage readiness.')
        receipt = read(b, identity)
        source_ok = False
        if receipt.get('phase') == 'verified' and receipt.get('binding') == digest(raw.get('Config', {}).get('Labels') or {}):
            source_ok = receipt.get('manager') == 'Docker Compose'
            if any(Path(path).exists() or Path(path).is_symlink() for path in receipt.get('absent', [])): source_ok = False
            for path, expected in receipt.get('inputs', {}).items():
                try:
                    actual = b.common.module('compose_setup').read_file(path, receipt['owner'])
                    if actual['sha256'] != expected: source_ok = False
                except Exception: source_ok = False
        if owner == 'Docker Compose' and not source_ok:
            conflicts.append('Compose source/overrides need review; recreation could restore a conflicting policy.')
        elif owner != 'Docker Compose':
            conflicts.append('Deployment manager policy is not verified. Check its authoritative startup/restart settings.')
        if receipt.get('phase') in ('intent', 'uncertain'):
            conflicts.append('A prior setup operation is unresolved. Its private record must be reviewed before another update.')
        return dict(policy=current, manager=owner, source_verified=source_ok, conflicts=conflicts,
                    original_policy=receipt.get('original_policy'), available=True,
                    compose_source=(raw.get('Config', {}).get('Labels') or {}).get('com.docker.compose.project.config_files', ''),
                    compose_service=(raw.get('Config', {}).get('Labels') or {}).get('com.docker.compose.service', ''))
    except Exception:
        return dict(policy=None, manager='Unavailable', conflicts=['Restart-policy information is unavailable; refresh before setup.'], available=False)


def validate_target(data):
    if (not isinstance(data, dict) or set(data) != {'id', 'name'}
            or not isinstance(data['id'], str) or not re.fullmatch('[0-9a-f]{64}', data['id'])
            or not isinstance(data['name'], str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', data['name'])):
        raise ValueError('Select an exact detected container ID and name.')


def plan(fleet, data, session):
    validate_target(data); b = fleet.context(); identity, name = data['id'], data['name']
    module = b.common.module('web_docker'); items = module.records(fleet)
    b.common.module('app_control').require_idle(b, items, identity)
    docker, _ = module.client(b, items); raw = inspect(docker, identity, name)
    receipt = read(b, identity); owner = manager(raw); current = policy(raw)
    dependencies = storage(b, items, identity, name)
    compose = None; allowed = True; instructions = []; diagnostics = []; technical = []
    if receipt.get('phase') in ('intent', 'uncertain'):
        allowed = False; instructions.append('Previous setup outcome is unresolved. Review ' + str(directory(b, identity)) + ' before another policy change.')
    if raw['HostConfig'].get('AutoRemove'):
        allowed = False; instructions.append('This container uses automatic removal; Docker cannot update its restart policy. Change that option in its deployment manager.')
    if owner in ('Docker Swarm', 'Kubernetes', 'Portainer'):
        allowed = False
        instructions.append({
            'Docker Swarm': 'This is a Swarm task. Its service reconciler can recreate it independently of Docker restart policy. Storage Watch cannot take ownership of task startup: move the selected workload to a standalone container under an explicitly reviewed deployment change, or keep startup owned by Swarm. A live task update is not a completed setup.',
            'Kubernetes': 'This is a Kubernetes-managed container. Pod restartPolicy and its workload controller own startup/recreation. Storage Watch cannot take ownership of this container ID. Keep startup in Kubernetes or explicitly migrate the selected workload to a standalone Docker container before selecting it here.',
            'Portainer': 'Use the authoritative Portainer stack editor or its linked Git source to set restart: "no" on only the selected service, including any override. Do not redeploy for this live change. Then use docker update --restart=no ' + identity + ' and verify the live policy. This app cannot certify Portainer’s external source; setup remains externally managed.'
        }[owner])
        if owner == 'Portainer':
            technical.extend(instructions[-1:])
            instructions[-1] = ('Portainer owns this app’s deployment. Review its selected service in the Portainer stack editor or linked source. '
                                'Storage Watch cannot verify that external source or complete automatic setup here; technical steps are available below.')
    elif owner == 'Docker Compose':
        editor = b.common.module('compose_setup')
        try: compose = editor.preview(raw['Config'].get('Labels') or {}, receipt)
        except Exception as exc:
            allowed = False
            safe = str(exc) if isinstance(exc, editor.Unavailable) else None
            diagnostics = copy.deepcopy(exc.diagnostics) if isinstance(exc, editor.Unavailable) else []
            # A configuration file also used as app data cannot safely lose its
            # writers. Docker mount inventory is evidence, never a guessed mapping.
            for issue in diagnostics:
                if issue['adjustable'] and any(m.get('Type') == 'bind' and m.get('Source') and
                        (Path(issue['path']) == Path(m['Source']) or Path(m['Source']) in Path(issue['path']).parents)
                        for m in raw.get('Mounts', [])):
                    issue.update(adjustable=False, proposed_mode=None,
                                 limitation='This file is inside a bind mount used by the app. Its write access needs review with the app owner; no permission change is offered.')
            instructions.append('Review the exact paths below. App settings have not been saved.' if diagnostics else
                                safe or 'Compose sources could not be verified. Check the recorded source location and project owner in Advanced details.')
            service = (raw['Config'].get('Labels') or {}).get('com.docker.compose.service', '')
            if not diagnostics and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*', service):
                technical.append('Authoritative service: services.' + service + '.restart. Validate with docker compose config using the original project, file order and environment. Review setup again after correcting the source; do not run compose up for this change.')
    else:
        instructions.append('No deployment manager is identifiable. The live policy can be verified, but external systemd scripts or another manager must also be configured not to start this container ahead of Storage Watch. External ownership remains unverified.')
    token = secrets.token_hex(24)
    value = dict(id=identity, name=name, token=token, expires=time.monotonic() + 300,
                 before_policy=current, protected=protected(raw), runtime=runtime(raw),
                 manager=owner, compose=compose, storage=dependencies, allowed=allowed,
                 binding=digest(raw['Config'].get('Labels') or {}), diagnostics=diagnostics)
    session['docker_setup_plan'] = value
    original = receipt.get('original_policy')
    return dict(id=identity, name=name, token=token, allowed=allowed, manager=owner,
                policy=current, target_policy=dict(Name='no', MaximumRetryCount=0),
                live_change=current != dict(Name='no', MaximumRetryCount=0),
                compose=compose['public'] if compose else None, storage=dependencies,
                explanation=EXPLANATION, instructions=instructions, original_policy=original,
                diagnostics=[b.common.module('compose_setup').public_diagnostic(v) for v in diagnostics], technical=technical,
                restoration=('Previous policy is saved privately. Disable Storage Watch boot/recovery choices before restoring it; Compose source backups are retained with the setup record.') if original else '')


def permission_plan(fleet, data, session):
    if not isinstance(data, dict) or set(data) != {'id', 'name', 'token', 'index'} or type(data['index']) is not int:
        raise ValueError('Select a permission problem from the current app review.')
    validate_target({k:data[k] for k in ('id', 'name')})
    old = session.get('docker_setup_plan')
    if (not old or any(old[k] != data[k] for k in ('id', 'name', 'token')) or time.monotonic() > old['expires']
            or not 0 <= data['index'] < len(old.get('diagnostics', []))):
        raise ValueError('This review expired. Review app settings again.')
    target = old['diagnostics'][data['index']]
    plan(fleet, {k:data[k] for k in ('id', 'name')}, session)
    current = session['docker_setup_plan']
    if target not in current['diagnostics'] or not target['adjustable']:
        raise ValueError('This path changed or cannot be adjusted here. Review the current diagnostics.')
    token = secrets.token_hex(24)
    session['docker_permission_plan'] = dict(token=token, expires=time.monotonic()+300, setup=current, target=target)
    return dict(token=token, id=data['id'], name=data['name'],
                path=fleet.context().common.module('compose_setup').public_diagnostic(target),
                message='Remove only the reviewed group/other write access from this one configuration file. '
                        'Read/execute permissions, ownership, parent directories and media folders stay unchanged. '
                        'This does not save startup/recovery settings, change Docker policy or restart the app. '
                        'The original mode is recorded privately. Compose validation will run again afterward.')


def permission_apply(fleet, data, session):
    if not isinstance(data, dict) or set(data) != {'id', 'name', 'token', 'confirm'} or data['confirm'] is not True:
        raise ValueError('Explicitly confirm the reviewed single-file permission change.')
    validate_target({k:data[k] for k in ('id', 'name')})
    value = session.get('docker_permission_plan')
    if (not value or data['token'] != value['token'] or time.monotonic() > value['expires']
            or any(data[k] != value['setup'][k] for k in ('id', 'name'))):
        raise ValueError('The permission review expired. Review again; nothing was changed.')
    if session.pop('docker_permission_plan', None) is not value:
        raise ValueError('This review was already used.')
    session.pop('application_plan', None)  # A permission confirmation never saves the app draft.
    b = fleet.context(); web = b.common.module('web_docker'); target = value['target']; before = value['setup']
    with fleet.mutex, b.common.module('app_control').operation(fleet, data['id']):
        plan(fleet, {k:data[k] for k in ('id', 'name')}, session)
        current = session['docker_setup_plan']
        if any(current[k] != before[k] for k in ('protected', 'runtime', 'before_policy', 'storage', 'binding')) or target not in current['diagnostics']:
            raise ValueError('Container, storage selections, path or permissions changed. Review again; nothing was changed.')
        path = directory(b, data['id']) / ('permissions-' + secrets.token_hex(12) + '.json')
        record = dict(id=data['id'], name=data['name'], time=b.w.timestamp(), phase='intent', target=target)
        def before_write():
            b.common.module('app_control').require_idle(b, web.records(fleet), data['id'])
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            b.w.atomic_write(path, json.dumps(record, indent=2)+'\n')
        try:
            b.common.module('compose_setup').adjust_permission(target, before_write)
        except Exception as exc:
            if path.exists():
                record.update(phase='unconfirmed');b.w.atomic_write(path, json.dumps(record, indent=2)+'\n')
            message = str(exc) if type(exc).__name__ == 'Unavailable' else 'Permission change could not be confirmed. Review the path before trying again.'
            raise ValueError(message) from None
        record.update(phase='verified', verified_at=b.w.timestamp())
        b.w.atomic_write(path, json.dumps(record, indent=2)+'\n')
        # Full normal validation runs again, including ordered overrides/hash.
        # A remaining source issue is not a failed chmod or a completed app setup.
        reviewed = plan(fleet, {k:data[k] for k in ('id', 'name')}, session)
        return dict(ok=True, settings_saved=False, review=reviewed,
                    message='File permissions updated and verified. ' +
                    ('Compose validation passed. Review and save app settings next.' if reviewed['allowed'] else
                     'App settings are not configured by this action. Review the remaining setup problem.'))


def apply(fleet, data, session):
    if (not isinstance(data, dict) or set(data) != {'id', 'name', 'token', 'confirm'} or data['confirm'] is not True):
        raise ValueError('Explicitly confirm the reviewed restart-policy change.')
    validate_target({k:data[k] for k in ('id','name')})
    value = session.get('docker_setup_plan')
    if (not value or any(data[k] != value[k] for k in ('id','name','token'))
            or time.monotonic() > value['expires'] or not value['allowed']):
        raise ValueError('This preview is expired, unavailable or belongs to another container. Review setup again.')
    if session.pop('docker_setup_plan', None) is not value:
        raise ValueError('This preview was already consumed. Review setup again.')
    b = fleet.context(); identity = value['id']; module = b.common.module('web_docker')
    with b.common.module('app_control').operation(fleet, identity):
        items = module.records(fleet); docker, _ = module.client(b, items)
        if storage(b, items, identity, value['name']) != value['storage']:
            raise ValueError('Storage selections changed after preview; review setup again.')
        raw = inspect(docker, identity, value['name'])
        if policy(raw) != value['before_policy'] or protected(raw) != value['protected'] or runtime(raw) != value['runtime']:
            raise ValueError('Container policy, configuration or execution changed after preview; no update was sent.')
        old_record = read(b, identity)
        if old_record.get('phase') in ('intent', 'uncertain'):
            raise ValueError('A previous setup operation must be reviewed before another update.')
        compose = value['compose']; editor = b.common.module('compose_setup')
        if compose:
            editor.unchanged(compose['context'])
            if editor.digest(editor.run(compose['context'], compose['context']['files'])) != compose['before_digest']:
                raise ValueError('Effective Compose configuration changed; review setup again.')
        b.common.module('app_control').require_idle(b, module.records(fleet), identity)
        record = dict(id=identity, name=value['name'], phase='intent', manager=value['manager'],
                      original_policy=old_record.get('original_policy', value['before_policy']),
                      binding=value['binding'], time=b.w.timestamp(), backups=old_record.get('backups', []))
        # Back up exact source privately before any mutation. Never return its contents.
        if compose and compose['public']['changes']:
            original = compose['context']['sources'][compose['index']]
            backup = directory(b, identity) / ('compose-' + secrets.token_hex(12) + '.backup')
            backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            b.w.atomic_write(backup, original['text'])
            record['backups'] = record['backups'] + [dict(source=original['path'], backup=str(backup), sha256=original['sha256'])]
        save(b, identity, record)
        changed_file = None; file_attempted = False; policy_attempted = False
        target = dict(Name='no', MaximumRetryCount=0)
        try:
            if compose:
                ctx = compose['context']
                if compose['public']['changes']:
                    file_attempted = True
                    changed_file = editor.replace(original, compose['text'])
                expected_inputs = copy.deepcopy(ctx)
                if changed_file: expected_inputs['sources'][compose['index']] = changed_file
                editor.unchanged(expected_inputs)
                effective = editor.run(ctx, ctx['files'])
                if editor.digest(effective) != compose['after_digest']:
                    raise ValueError('Effective Compose validation failed after the selected-service edit.')
                record.update(compose_hash=editor.run(ctx, ctx['files'], hash_service=True), owner=ctx['owner'], absent=ctx.get('absent', []))
                # Includes overrides and interpolation/env files; later drift must be visible.
                editor.unchanged(expected_inputs)
                record['inputs'] = editor.fingerprints(expected_inputs)
            if value['before_policy'] != target:
                policy_attempted = True
                try: docker.request('POST', '/containers/' + identity + '/update', {'RestartPolicy': target}, timeout=10)
                except Exception: pass  # A fresh read, not a second POST, resolves an uncertain acknowledgement.
            after = inspect(docker, identity, value['name'])
            if policy(after) != target:
                raise ValueError('Docker did not retain restart policy no; the update was not repeated.')
            if protected(after) != value['protected'] or runtime(after) != value['runtime']:
                raise ValueError('Container configuration or execution changed during setup; review the outcome. No restart was requested.')
            if compose: editor.unchanged(expected_inputs)
            record.update(phase='verified', verified_at=b.w.timestamp(), applied_policy=target)
            save(b, identity, record)
            return dict(ok=True, message='Restart policy verified as no. Container identity, execution and other settings are unchanged. ' +
                        ('Compose configuration and overrides verified.' if compose else 'External deployment manager remains unverified.'),
                        setup=summary(b, docker, identity, value['name']))
        except Exception:
            # Only undo our exact source edit when Docker is proven unchanged.
            try:
                current = inspect(docker, identity, value['name']) if policy_attempted else raw
                if policy(current) != value['before_policy'] or protected(current) != value['protected']:
                    raise ValueError('Uncertain live outcome')
                if file_attempted and changed_file is None and editor.read_file(original['path'], original['uid']) != original:
                    raise ValueError('Uncertain source outcome')
                if changed_file: editor.replace(changed_file, original['text'])
                record['phase'] = 'rolled-back'
                message = 'Setup failed. The previous live policy was verified and any confirmed Compose edit was rolled back. Review a new preview.'
            except Exception:
                record['phase'] = 'uncertain'
                message = 'Setup outcome is unresolved. No update was repeated and no uncertain file was overwritten. Review the private setup record and backup before continuing.'
            save(b, identity, record)
            return dict(ok=False, message=message, setup=summary(b, docker, identity, value['name']))
