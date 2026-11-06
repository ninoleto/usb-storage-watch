# SPDX-License-Identifier: MIT
"""Review/save adapter for independent startup and recovery settings.

The recovery engine remains authoritative. This file only remembers selections
removed by an explicit off switch; remembered choices never authorize recovery.
"""
import copy
import json
import secrets
import time


def preferences_path(b):
    return b.cli.drives.roots(b.s)[0] / 'application-choices.json'


def preferences(b):
    try: value = json.loads(preferences_path(b).read_text())
    except FileNotFoundError: return {}
    if not isinstance(value, dict): raise ValueError('Saved app choices need administrator review.')
    boot = b.common.module('boot_start')
    for identity, item in value.items():
        if not isinstance(item, dict) or set(item) != {'id', 'name', 'enabled', 'drives', 'specs'} or item['id'] != identity or item['enabled']:
            raise ValueError('Saved app choices need administrator review.')
        boot.validate_item(b, item)
        if not isinstance(item['specs'], dict): raise ValueError('Invalid retained app settings.')
        for drive, spec in item['specs'].items():
            b.cli.drives.profile_id(drive)
            if not isinstance(spec, dict) or spec.get('container_id') != identity or spec.get('name') != item['name']:
                raise ValueError('Invalid retained app identity.')
    return value


def normalize(value):
    return dict(enabled=value['enabled'], drives=sorted(
        [dict(id=d['id'], images=sorted(d['images'])) for d in value['drives']], key=lambda d:d['id']))


def snapshot(b, items, containers):
    boot = b.common.module('boot_start').read(b); remembered = preferences(b)
    # Include missing pinned IDs and disabled choices without assigning by name.
    names = {v['id']:v['name'] for v in containers}
    names.update({v['id']:v['name'] for v in boot['containers']})
    names.update({v['id']:v['name'] for v in remembered.values()})
    for _, c in items:
        for spec in c['docker']['containers']:
            if spec.get('container_id'): names[spec['container_id']] = spec['name']
    saved_ids = {v['id'] for v in boot['containers']} | set(remembered) | {v['container_id'] for _, c in items for v in c['docker']['containers'] if v.get('container_id')}
    settings = []
    for identity, name in names.items():
        startup = next((v for v in boot['containers'] if v['id'] == identity), dict(enabled=False, drives=[]))
        choices = []; enabled = False
        for drive, c in items:
            spec = next((v for v in c['docker']['containers'] if v.get('container_id') == identity and v['name'] == name), None)
            if spec:
                choices.append(dict(id=drive, images=list(spec.get('images', []))))
                enabled |= c['docker']['enabled']
        recovery = dict(enabled=enabled, drives=choices) if choices else remembered.get(identity, dict(enabled=False, drives=[]))
        settings.append(dict(id=identity, name=name, boot=normalize(startup), recovery=normalize(recovery)))
    return dict(revision=b.s.digest([items, boot, remembered]), settings=settings, saved_ids=sorted(saved_ids))


def validate(b, desired, items, changed):
    if not isinstance(desired, dict) or set(desired) != {'id', 'name', 'boot', 'recovery'}:
        raise ValueError('Review the app settings before saving.')
    b.common.module('docker_setup').validate_target({k:desired[k] for k in ('id', 'name')})
    boot = b.common.module('boot_start')
    for key in ('boot', 'recovery'):
        value = desired[key]
        if not isinstance(value, dict) or set(value) != {'enabled', 'drives'}:
            raise ValueError('Invalid app storage choices.')
        item = dict(id=desired['id'], name=desired['name'], **value)
        boot.validate_item(b, item)
        if key in changed and value['enabled']: boot.validate_storage(b, item, items)
    # Do not implicitly activate or discard another app stored under a global
    # disabled drive setting. Such legacy settings need a separate drive review.
    for drive, c in items:
        if not c['docker']['enabled'] and any(v['name'] != desired['name'] for v in c['docker']['containers']):
            if 'recovery' in changed and any(v['id'] == drive for v in desired['recovery']['drives']) and desired['recovery']['enabled']:
                raise ValueError('This drive has other saved apps with drive-level Docker recovery off. Review its existing recovery settings before enabling this app; no other selections were changed.')


def plan(fleet, data, session):
    if set(data) != {'revision', 'settings'}: raise ValueError('Review current app settings first.')
    b = fleet.context(); web = b.common.module('web_docker')
    with fleet.mutex, b.cli.drives.configuration_lock(b.s):
        web.recover_transaction(fleet); items = web.records(fleet)
        validate(b, data['settings'], items, [])
        b.common.module('app_control').require_idle(b, items, data['settings']['id'])
        desired = copy.deepcopy(data['settings'])
        for key in ('boot', 'recovery'): desired[key] = normalize(desired[key])
        current = snapshot(b, items, [desired])
        if data['revision'] != current['revision']: raise ValueError('Settings changed. Reload saved settings, then review again.')
        old = next(v for v in current['settings'] if v['id'] == desired['id'])
        if old['name'] != desired['name']:
            raise ValueError('Saved container identity changed. Refresh before reviewing.')
        changed = [key for key in ('boot', 'recovery') if old[key] != desired[key]]
        if not changed: raise ValueError('No settings changed; nothing to save.')
        validate(b, desired, items, changed)
        boot_revision = b.common.module('boot_start').public(b)['revision']
    policy = None
    if any(desired[key]['enabled'] for key in changed):
        policy = b.common.module('docker_setup').plan(fleet, {k:desired[k] for k in ('id', 'name')}, session)
    token = secrets.token_hex(24)
    session['application_plan'] = dict(token=token, expires=time.monotonic()+300,
        desired=desired, revision=current['revision'], drive_revision=web.revision(items),
        boot_revision=boot_revision, changed=changed, policy=policy)
    return dict(token=token, settings=desired, changed=changed, policy=policy,
                allowed=not policy or policy['allowed'])


def save(fleet, data, session):
    if set(data) != {'token', 'confirm'} or data['confirm'] is not True:
        raise ValueError('Confirm the reviewed settings before saving.')
    value = session.get('application_plan')
    if not value or data['token'] != value['token'] or time.monotonic() > value['expires']:
        raise ValueError('The review expired. Review changes again.')
    if value['policy'] and not value['policy']['allowed']:
        raise ValueError('Follow the deployment instructions before enabling these settings.')
    if session.pop('application_plan', None) is not value:
        raise ValueError('This review was already used. Refresh saved settings.')
    b = fleet.context(); web = b.common.module('web_docker'); desired = value['desired']
    applied = []; stage = 'Docker startup policy'; message = ''; ok = False
    # Serialize this broker's multi-stage save. Existing per-drive, config and
    # container locks plus revisions still guard each underlying operation.
    with fleet.mutex, b.common.module('app_control').operation(fleet, desired['id']):
        with b.cli.drives.configuration_lock(b.s):
            items = web.records(fleet)
            if snapshot(b, items, [desired])['revision'] != value['revision']:
                raise ValueError('Settings changed after review. Reload saved settings; nothing was applied.')
            validate(b, desired, items, value['changed'])
        try:
            if value['policy']:
                p = value['policy']
                result = b.common.module('docker_setup').apply(fleet,
                    dict(id=desired['id'], name=desired['name'], token=p['token'], confirm=True), session)
                if not result['ok']:
                    return dict(ok=False, applied=[], message=result['message']+' App settings were not saved.')
                applied.append('Docker startup policy verified' + ('; Compose source verified' if p['compose'] else '; external source unverified'))
            if 'recovery' in value['changed']:
                stage = 'Drive recovery'
                recovery = desired['recovery']; selected = {d['id']:d['images'] for d in recovery['drives']}
                # Save retained choices BEFORE removing engine selections. A crash
                # cannot lose the disabled selections. Active engine choices win.
                with b.cli.drives.configuration_lock(b.s):
                    remembered = preferences(b); previous = copy.deepcopy(remembered)
                    specs = copy.deepcopy(remembered.get(desired['id'], {}).get('specs', {}))
                    for drive, c in items:
                        for spec in c['docker']['containers']:
                            if spec.get('container_id') == desired['id'] and spec['name'] == desired['name']:
                                specs[drive] = copy.deepcopy(spec)
                    remembered[desired['id']] = dict(id=desired['id'], name=desired['name'], enabled=False,
                                                      drives=copy.deepcopy(recovery['drives']), specs=specs)
                    b.cli.save(preferences_path(b), remembered)
                try:
                    web.save(fleet, dict(id=desired['id'], name=desired['name'], revision=value['drive_revision'], drives=[
                        dict(id=i, enabled=recovery['enabled'] and i in selected,
                             images=selected.get(i, []) if recovery['enabled'] else []) for i, _ in items]), retained_specs=specs)
                except Exception:
                    with b.cli.drives.configuration_lock(b.s):
                        # Undo only our private preference write when the engine
                        # settings are proven unchanged. Never overwrite a later edit.
                        if web.revision(web.records(fleet)) == value['drive_revision'] and preferences(b) == remembered:
                            b.cli.save(preferences_path(b), previous)
                    raise
                applied.append('Drive recovery saved')
            if 'boot' in value['changed']:
                stage = 'Computer startup'
                b.common.module('boot_start').update(fleet, dict(revision=value['boot_revision'],
                    container=dict(id=desired['id'], name=desired['name'], **desired['boot'])))
                applied.append('Computer startup saved')
            with b.cli.drives.configuration_lock(b.s):
                actual = snapshot(b, web.records(fleet), [desired])
                if next(v for v in actual['settings'] if v['id'] == desired['id']) != desired:
                    raise ValueError('Readback differs from the reviewed choices. Refresh and review the remaining changes.')
            ok = True
            message = 'Settings saved and verified.'
        except Exception as exc:
            # Do not echo arbitrary Docker/OS output. Stage outcomes remain
            # explicit, including policy changes preceding a failed storage save.
            detail = str(exc) if isinstance(exc, ValueError) else 'The operation could not be confirmed. Refresh before reviewing again.'
            message = stage + ' was not confirmed. ' + detail
    return dict(ok=ok, applied=applied, message=message)
