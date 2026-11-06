# SPDX-License-Identifier: MIT
"""Explicit, backed-up removal/reconnection of a confirmed unavailable identity.

Only configuration references are edited. Recovery receipts, policy records and
history are never moved/deleted. Reconnected choices are retained with automatic
options off, so identity housekeeping cannot start a different app.
"""
from contextlib import ExitStack
import copy
import json
import secrets
import time


def paths(b):
    config, state = b.cli.drives.roots(b.s)
    return dict(boot=config/'boot-start.json', choices=config/'application-choices.json') | {
        'drive:'+i:p for i,p in b.cli.drives.files(b.s)}


def journal(b):
    return b.cli.drives.roots(b.s)[1]/'app-entry-transaction.json'


def file_value(path):
    if path.is_symlink(): raise ValueError('App settings must not be symlinks.')
    try: return json.loads(path.read_text())
    except FileNotFoundError: return None


def write_value(b, path, value):
    if value is None:
        path.unlink(missing_ok=True)
    else: b.cli.save(path, value)


def recover(fleet):
    """Reconcile only our exact interrupted writes, never a later user's edit."""
    b=fleet.context(); path=journal(b)
    if not path.exists(): return
    try:
        value=json.loads(path.read_text()); catalog=paths(b)
        if (set(value)!={'version','before','after'} or value['version']!=1
                or not isinstance(value['before'],dict) or not isinstance(value['after'],dict)
                or set(value['before'])!=set(value['after']) or not set(value['before'])<=set(catalog)):
            raise ValueError()
        for key, old in value['before'].items():
            if file_value(catalog[key]) not in (old,value['after'][key]): raise ValueError()
        for key, old in value['before'].items(): write_value(b,catalog[key],old)
        b.common.module('web_docker').finish_transaction(path)
        fleet.cache.clear()
    except (OSError,ValueError,TypeError):
        raise ValueError('An interrupted saved-entry change needs administrator review. No later settings were overwritten.') from None


def inventory(b, items):
    try: rows,_=b.common.module('web_docker').discover(b,items)
    except Exception:
        raise ValueError('Docker inventory is unavailable. No saved entry can be removed or reconnected; refresh when Docker is available.') from None
    return rows


def documents(b):
    # Validate existing public schemas before proposing any edits.
    b.common.module('boot_start').read(b)
    b.common.module('app_settings').preferences(b)
    return {key:file_value(path) for key,path in paths(b).items()}


def saved_ids(values):
    return ({v['id'] for v in (values.get('boot') or {}).get('containers',[])} |
            set(values.get('choices') or {}) |
            {v['container_id'] for k,c in values.items() if k.startswith('drive:')
             for v in c['docker']['containers'] if v.get('container_id')})


def projection(b, before, source, target):
    identity=source['id']; after=copy.deepcopy(before)
    boot=after.get('boot'); choices=after.get('choices')
    old_boot=next((v for v in (boot or {}).get('containers',[]) if v['id']==identity),None)
    old_choices=(choices or {}).get(identity)
    specs=copy.deepcopy((old_choices or {}).get('specs',{})); selected=[]
    if boot: boot['containers']=[v for v in boot['containers'] if v['id']!=identity]
    if choices is not None: choices.pop(identity,None)
    for key,c in after.items():
        if not key.startswith('drive:'): continue
        removed=[v for v in c['docker']['containers'] if v.get('container_id')==identity]
        for spec in removed:
            specs[key[6:]]=copy.deepcopy(spec);selected.append(dict(id=key[6:],images=list(spec.get('images',[]))))
        if removed:
            c['docker']['containers']=[v for v in c['docker']['containers'] if v.get('container_id')!=identity]
            if not c['docker']['containers']: c['docker']['enabled']=False
            b.s.validate(c)
    if target:
        # Explicit identity transfer, never name matching or overwriting a target.
        if target['id'] in saved_ids(before):
            raise ValueError('The selected container already has saved Storage Watch settings. Choose another identity or remove the obsolete entry to keep the existing app unchanged. Settings will not be merged.')
        if old_boot:
            item=copy.deepcopy(old_boot);item.update(target);item['enabled']=False
            after['boot']['containers'].append(item)
        if selected or old_choices:
            selected=selected or copy.deepcopy(old_choices['drives'])
            for spec in specs.values(): spec.update(container_id=target['id'],name=target['name'])
            if after['choices'] is None: after['choices']={}
            after['choices'][target['id']]=dict(**target,enabled=False,drives=selected,specs=specs)
    return after


def validate_inventory(rows, source, target):
    if any(v['id']==source['id'] for v in rows):
        raise ValueError('This container is present in Docker. Refresh; only confirmed unavailable entries can be changed here.')
    if target and not any(v['id']==target['id'] and v['name']==target['name'] for v in rows):
        raise ValueError('The explicitly selected destination identity changed or disappeared. Review again.')


def plan(fleet, data, session):
    if set(data)!={'id','name','revision','operation','target'} or data['operation'] not in ('remove','reconnect'):
        raise ValueError('Review the saved-entry change first.')
    b=fleet.context(); web=b.common.module('web_docker'); editor=b.common.module('app_settings')
    source={k:data[k] for k in ('id','name')};target=data['target']
    b.common.module('docker_setup').validate_target(source)
    if data['operation']=='remove':
        if target is not None: raise ValueError('Removing an entry cannot select another container.')
    else: b.common.module('docker_setup').validate_target(target)
    with fleet.mutex, b.cli.drives.configuration_lock(b.s):
        web.recover_transaction(fleet);items=web.records(fleet);before=documents(b)
        snapshot=editor.snapshot(b,items,[])
        if data['revision']!=snapshot['revision']: raise ValueError('Saved settings changed. Refresh and review again.')
        saved=next((v for v in snapshot['settings'] if v['id']==source['id'] and v['name']==source['name']),None)
        if not saved: raise ValueError('This saved identity no longer exists. Refresh the app list.')
        rows=inventory(b,items);validate_inventory(rows,source,target)
        for target_item in (source, target):
            if target_item: b.common.module('app_control').require_idle(b, items, target_item['id'])
        after=projection(b,before,source,target)
    token=secrets.token_hex(24)
    session['app_entry_plan']=dict(token=token,expires=time.monotonic()+300,source=source,target=target,
        before=before,after=after,operation=data['operation'])
    return dict(token=token,source=source,target=target,operation=data['operation'],settings=saved,
        message=('Remove only this identity’s Storage Watch startup, recovery and retained inactive settings. Docker containers, application files and historical recovery records are untouched.' if not target else
                 'Move this saved entry’s drive and image choices to the explicitly selected identity. Automatic startup and drive recovery will be OFF; review and enable them on its app card afterward. Existing Docker settings, running apps and historical records are untouched.'))


def _apply(fleet, data, session):
    if set(data)!={'token','confirm'} or data['confirm'] is not True:
        raise ValueError('Explicitly confirm the reviewed saved-entry change.')
    value=session.get('app_entry_plan')
    if not value or data['token']!=value['token'] or time.monotonic()>value['expires']:
        raise ValueError('The saved-entry review expired. Refresh and review again.')
    if session.pop('app_entry_plan',None) is not value: raise ValueError('This review was already used. Refresh the app list.')
    b=fleet.context();web=b.common.module('web_docker');_,state=b.cli.drives.roots(b.s)
    with fleet.mutex, ExitStack() as held:
        items=web.records(fleet)
        # Same storage-before-container ordering as boot/recovery; refuse a busy
        # operation rather than stopping a service or changing recovery receipts.
        for drive,_ in sorted(items):
            child,instance=fleet.get(drive)
            held.enter_context(web.request_lock(instance))
            held.enter_context(b.cli.drives.lock(child.s.STATE_DIR,'recovery.lock'))
        for identity in sorted({v['id'] for v in (value['source'],value['target']) if v}):
            held.enter_context(b.cli.drives.lock(state/'shared-locks','docker-restart-'+identity+'.lock'))
        held.enter_context(b.cli.drives.configuration_lock(b.s))
        web.recover_transaction(fleet)
        if documents(b)!=value['before']: raise ValueError('Settings changed after review; nothing was removed or reconnected.')
        for target_item in (value['source'], value['target']):
            if target_item: b.common.module('app_control').require_idle(b, web.records(fleet), target_item['id'])
        rows=inventory(b,web.records(fleet));validate_inventory(rows,value['source'],value['target'])
        # Preview supplied no file paths. The only writable paths come from the
        # fixed boot/preferences files and currently configured drive profiles.
        catalog=paths(b);changed=[k for k in value['before'] if value['before'][k]!=value['after'][k]]
        receipt=dict(version=1,before={k:value['before'][k] for k in changed},after={k:value['after'][k] for k in changed})
        backup=state/'app-entry-backups'/('entry-'+secrets.token_hex(16)+'.json')
        b.cli.save(backup,receipt)
        b.cli.save(journal(b),receipt)
        try:
            for key in changed: write_value(b,catalog[key],value['after'][key])
            if documents(b)!=value['after']: raise ValueError('Saved-entry readback differs.')
            web.finish_transaction(journal(b));fleet.cache.clear()
        except Exception:
            if journal(b).exists():
                recover(fleet)
                raise ValueError('Saved-entry change failed; previous settings were restored from the private transaction.') from None
            raise ValueError('The change may have completed, but confirmation failed. Refresh before another action.') from None
    return dict(ok=True,message=('Saved entry removed. Only Storage Watch configuration changed; Docker and historical records are unchanged.' if not value['target'] else
        'Saved entry reconnected to the selected identity. Automatic options are off; review its app card before enabling them. Docker and historical records are unchanged.'))


def apply(fleet, data, session):
    try: return _apply(fleet, data, session)
    except BlockingIOError:
        raise ValueError('Another storage or app operation is busy. No saved entry was changed; review again when it finishes.') from None
