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
    # Product/image and access-control labels do not establish deployment ownership.
    # Portainer's own image carries io.portainer.server; accesscontrol.* is also
    # documented for resources deployed externally. Unknown hints stay unverified.
    hints = {k: v for k, v in labels.items() if k.startswith(('io.portainer.', 'com.portainer.'))
             and k not in ('io.portainer.server', 'io.portainer.agent') and not k.startswith('io.portainer.accesscontrol.')}
    if any(v and k in ('io.portainer.stack.id', 'io.portainer.stack.name', 'com.portainer.stack.id',
                      'com.portainer.stack.name', 'io.portainer.edge_stack_id') for k, v in hints.items()): return 'Portainer'
    if hints: return 'Unverified external management'
    directory = labels.get('com.docker.compose.project.working_dir', '')
    if re.fullmatch(r'/data/(?:compose|edge_stacks)/[0-9]+(?:/.*)?', directory):
        return 'Unverified external management'
    if any(k.startswith('com.docker.compose.') for k in labels): return 'Docker Compose'
    return 'Not identified'


def access_usage(docker, raw, items):
    """Read-only, complete Docker mount inventory; never infer native-service safety."""
    rows = docker.request('GET', '/containers/json?all=1'); deadline = time.monotonic() + 18
    if not isinstance(rows, list) or len(rows) > 512: raise ValueError('Docker mount inventory is unavailable or too large.')
    identities = [v.get('Id') for v in rows if isinstance(v, dict)]
    if (len(identities) != len(rows) or len(set(identities)) != len(rows) or raw['Id'] not in identities
            or any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v) for v in identities)):
        raise ValueError('Docker mount inventory is incomplete; refresh before reviewing access changes.')
    result = []
    for identity in sorted(identities):
        if time.monotonic() >= deadline: raise ValueError('Docker mount inventory timed out; review again.')
        value = docker.request('GET', '/containers/' + identity + '/json', timeout=max(1, deadline-time.monotonic()))
        if value.get('Id') != identity or not isinstance(value.get('Mounts'), list):
            raise ValueError('Docker mount identities could not be verified.')
        mounts = []
        for mount in value['Mounts']:
            source = mount.get('Source', '')
            if not source and mount.get('Type') == 'tmpfs': continue
            if not isinstance(source, str) or not Path(source).is_absolute() or '..' in Path(source).parts:
                raise ValueError('An application mount source cannot be verified safely.')
            mounts.append(dict(source=source, resolved=str(Path(source).resolve()), type=mount.get('Type'),
                               destination=mount.get('Destination'), writable=mount.get('RW')))
        result.append(dict(id=identity, name=value.get('Name', '').lstrip('/'), mounts=mounts))
    shared = sorted({str(p) for _, c in items for p in
                     [c['disk']['mountpoint']] + [im['mountpoint'] for im in c.get('images', [])]})
    return dict(apps=result, storage=shared)


def access_diagnostics(editor, diagnostics, usage):
    for issue in diagnostics:
        if not issue['adjustable']: continue
        path = Path(issue['path']); data = []
        for app in usage['apps']:
            for mount in app['mounts']:
                source = Path(mount['resolved'])
                if path == source or source in path.parents:
                    issue.update(adjustable=False, proposed_mode=None,
                                 limitation='This path is inside an application data mount used by '+app['name']+'. No access change is offered; separate deployment configuration from shared data.')
                elif issue['type'] == 'directory' and path in source.parents:
                    if not source.is_dir():
                        issue.update(adjustable=False, proposed_mode=None,
                                     limitation='A known application data folder below this project is missing or is not a directory. Its required access cannot be verified.')
                    else:
                        data.append(dict(app=app['name'], path=str(source), identity=editor.identity(source.stat())))
        if issue['type'] == 'directory':
            if any(path == Path(p) or Path(p) in path.parents for p in usage['storage']):
                issue.update(adjustable=False, proposed_mode=None, limitation='This project is on configured shared storage. Directory access needs separate owner review.')
            try: home = Path(editor.pwd.getpwuid(issue['_owner']).pw_dir)
            except (KeyError, OSError, AttributeError): home = None
            if home is None or not home.is_absolute():
                issue.update(adjustable=False, proposed_mode=None, limitation='The project owner’s home directory could not be verified. Resolve that account lookup before changing directory access.')
            elif path == home:
                issue.update(adjustable=False, proposed_mode=None, limitation='The project is the account home directory. Its shared access needs separate owner review.')
            issue['child_data'] = [dict(app=v['app'], path=v['path']) for v in data]
            issue['_child_data'] = data
    # Never offer a descendant through a directory that the full review refused.
    for issue in diagnostics:
        if issue['adjustable'] and any(not v['adjustable'] and Path(v['path']) in Path(issue['path']).parents for v in diagnostics):
            issue.update(adjustable=False, proposed_mode=None, limitation='A parent directory is not eligible for this access review. Resolve its stated limitation first.')


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
    compose = None; allowed = True; instructions = []; diagnostics = []; technical = []; usage = None
    if receipt.get('phase') in ('intent', 'uncertain'):
        allowed = False; instructions.append('Previous setup outcome is unresolved. Review ' + str(directory(b, identity)) + ' before another policy change.')
    if raw['HostConfig'].get('AutoRemove'):
        allowed = False; instructions.append('This container uses automatic removal; Docker cannot update its restart policy. Change that option in its deployment manager.')
    if owner in ('Docker Swarm', 'Kubernetes', 'Portainer', 'Unverified external management'):
        allowed = False
        instructions.append({
            'Docker Swarm': 'This is a Swarm task. Its service reconciler can recreate it independently of Docker restart policy. Storage Watch cannot take ownership of task startup: move the selected workload to a standalone container under an explicitly reviewed deployment change, or keep startup owned by Swarm. A live task update is not a completed setup.',
            'Kubernetes': 'This is a Kubernetes-managed container. Pod restartPolicy and its workload controller own startup/recreation. Storage Watch cannot take ownership of this container ID. Keep startup in Kubernetes or explicitly migrate the selected workload to a standalone Docker container before selecting it here.',
            'Unverified external management': 'Portainer-related deployment hints or a manager-private Compose location were found, but ownership cannot be established reliably. Review the source in its deployment manager; Storage Watch will not edit an unverified external source.',
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
            if diagnostics:
                try:
                    usage = access_usage(docker, raw, items)
                    access_diagnostics(editor, diagnostics, usage)
                except Exception:
                    for issue in diagnostics:
                        if issue['adjustable']:
                            issue.update(adjustable=False, proposed_mode=None,
                                         limitation='Current application mount usage could not be verified. Refresh Docker status and review again; no access change is offered.')
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
                 binding=digest(raw['Config'].get('Labels') or {}), diagnostics=diagnostics, access_usage=usage)
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
    # Old file-only clients may still select an index. They cannot approve a
    # directory change without the new multi-path effect review.
    if (not isinstance(data, dict) or set(data) not in ({'id','name','token'}, {'id','name','token','index'})
            or ('index' in data and type(data['index']) is not int)):
        raise ValueError('Select access changes from the current app review.')
    validate_target({k:data[k] for k in ('id', 'name')})
    old = session.get('docker_setup_plan')
    if (not old or any(old[k] != data[k] for k in ('id', 'name', 'token')) or time.monotonic() > old['expires']):
        raise ValueError('This review expired. Review app settings again.')
    targets = [v for v in old.get('diagnostics', []) if v['adjustable']]
    if 'index' in data:
        index = data['index']
        if not 0 <= index < len(old.get('diagnostics', [])):
            raise ValueError('Review the current access problems again.')
        target = old['diagnostics'][index]
        if target not in targets or target['type'] != 'file' or any(v['type']=='directory' for v in targets):
            raise ValueError('Use Review access changes to confirm the complete directory/file effects.')
        targets = [target]
    if not targets: raise ValueError('No safe access change is available. Review the specific limitations.')
    plan(fleet, {k:data[k] for k in ('id', 'name')}, session)
    current = session['docker_setup_plan']
    if current['access_usage'] != old['access_usage'] or any(v not in current['diagnostics'] for v in targets):
        raise ValueError('The paths or application mounts changed. Nothing was changed; review again.')
    token = secrets.token_hex(24)
    session['docker_permission_plan'] = dict(token=token, expires=time.monotonic()+300, setup=current, targets=targets, legacy='index' in data)
    paths = [fleet.context().common.module('compose_setup').public_diagnostic(v) for v in targets]
    remaining = [fleet.context().common.module('compose_setup').public_diagnostic(v) for v in current['diagnostics'] if v not in targets]
    return dict(token=token, id=data['id'], name=data['name'], paths=paths, path=paths[0], remaining=remaining,
                message='Remove only the listed write access from these exact paths. For a directory, affected accounts '
                        'will no longer be able to create, delete or rename entries directly inside it. Ownership, read/traverse '
                        'access and child permissions stay unchanged. Existing data subfolders keep their own permissions. '
                        'Native services and jobs are not fully inventoried: confirm only if those accounts do not need '
                        'to create or rename entries in this project or edit these configuration files. '
                        'This does not save app settings, change Docker policy or restart the app. Original modes are recorded privately. '
                        + ('Other setup problems listed below remain outside this adjustment.' if remaining else ''))


def permission_apply(fleet, data, session):
    if not isinstance(data, dict) or set(data) != {'id', 'name', 'token', 'confirm'} or data['confirm'] is not True:
        raise ValueError('Explicitly confirm the reviewed access changes.')
    validate_target({k:data[k] for k in ('id', 'name')})
    value = session.get('docker_permission_plan')
    if (not value or data['token'] != value['token'] or time.monotonic() > value['expires']
            or any(data[k] != value['setup'][k] for k in ('id', 'name'))):
        raise ValueError('The access review expired. Review again; nothing was changed.')
    if session.pop('docker_permission_plan', None) is not value:
        raise ValueError('This review was already used.')
    session.pop('application_plan', None)
    b = fleet.context(); web = b.common.module('web_docker'); targets = value['targets']; before = value['setup']
    with fleet.mutex, b.common.module('app_control').operation(fleet, data['id']):
        plan(fleet, {k:data[k] for k in ('id', 'name')}, session)
        current = session['docker_setup_plan']
        if (any(current[k] != before[k] for k in ('protected', 'runtime', 'before_policy', 'storage', 'binding', 'access_usage'))
                or any(v not in current['diagnostics'] for v in targets)):
            raise ValueError('Container, storage, mounts, identity or permissions changed; nothing was changed. Review again.')
        path = directory(b, data['id']) / ('permissions-' + secrets.token_hex(12) + '.json')
        record = dict(id=data['id'], name=data['name'], time=b.w.timestamp(), phase='intent', targets=targets)
        editor = b.common.module('compose_setup')
        def before_write():
            items = web.records(fleet); b.common.module('app_control').require_idle(b, items, data['id'])
            docker, _ = web.client(b, items); raw = inspect(docker, data['id'], data['name'])
            if (protected(raw) != before['protected'] or runtime(raw) != before['runtime']
                    or access_usage(docker, raw, items) != before['access_usage']):
                raise ValueError('Application identity or shared-data usage changed; review again.')
            if not path.exists():
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                b.w.atomic_write(path, json.dumps(record, indent=2)+'\n')
        def progress(outcomes):
            record['outcomes'] = outcomes
            b.w.atomic_write(path, json.dumps(record, indent=2)+'\n')
        try:
            if value.get('legacy'): editor.adjust_permission(targets[0], before_write)
            else: editor.adjust_access(targets, before_write, progress)
        except editor.AccessFailure as exc:
            record.update(phase='unconfirmed', outcomes=exc.outcomes)
            b.w.atomic_write(path, json.dumps(record, indent=2)+'\n')
            details = '; '.join(v['path']+': '+v['status'] for v in exc.outcomes)
            return dict(ok=False, settings_saved=False, outcomes=exc.outcomes,
                        message='Access changes did not complete. '+details+'. No app settings were saved or container actions requested. Review again.')
        except Exception as exc:
            if path.exists():
                record.update(phase='unconfirmed');b.w.atomic_write(path, json.dumps(record, indent=2)+'\n')
            message = str(exc) if isinstance(exc, editor.Unavailable) else 'Access change could not be confirmed. Review the exact paths before trying again.'
            raise ValueError(message) from None
        record.update(phase='verified', verified_at=b.w.timestamp())
        b.w.atomic_write(path, json.dumps(record, indent=2)+'\n')
        reviewed = plan(fleet, {k:data[k] for k in ('id', 'name')}, session)
        return dict(ok=True, settings_saved=False, review=reviewed,
                    message='Access changes updated and verified. ' +
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
