# SPDX-License-Identifier: MIT
"""Authenticated routing to isolated instances of the existing drive broker."""
import copy
import json
import sqlite3
import threading
import time
import uuid

GLOBAL = {'login','login-info','logout','session','management-token','smtp','test-email',
          'network','lan-auto','lan-info','lan-status','local-accounts','global-config',
          'network-state','network-stage','network-confirm','network-cancel','network-certificate','network-renew'}
FLEET = {'docker-overview','docker-container-settings','docker-container-action','docker-boot-settings','docker-setup-plan','docker-setup-apply','docker-permission-plan','docker-permission-apply','docker-app-plan','docker-app-save','docker-entry-plan','docker-entry-apply','fleet-status','add-drive','fleet-events','notification-preferences',
         'remove-drive-plan','remove-drive',
         'drive-rebind-candidates','drive-rebind-plan','drive-rebind-apply',
         'prepare-disks','prepare-drive-plan','prepare-drive','prepare-progress'}


class Fleet:
    def __init__(self, context, broker):
        self.context=context;self.broker=broker;self.children={};self.mutex=threading.RLock();self.cache={}
        self.factory=self.create

    def create(self,identifier):
        b=self.context();config,state=b.cli.drives.roots(b.s)
        profile=dict(id=identifier,config_root=str(config),state_root=str(state))
        child=b.common.module('web_broker',profile)
        for path in (child.s.CONFIG.parent,child.s.STATE_DIR):
            if path.resolve()!=path:raise ValueError('Drive paths must not contain symlinks.')
            path.mkdir(parents=True,mode=0o700,exist_ok=True)
        child.auth=b.auth  # One global session authority, no duplicated credentials.
        instance=child.Broker(child.History(child.s.STATE_DIR/'web-history.sqlite3'),self.broker.sessions)
        return child,instance

    def get(self,identifier,create=False):
        b=self.context();b.cli.drives.profile_id(identifier)
        if identifier=='legacy':return b,self.broker
        with self.mutex:
            if not create and identifier not in dict(b.cli.drives.files(b.s)):
                raise ValueError('This drive profile no longer exists. Refresh the drive list.')
            if identifier not in self.children:self.children[identifier]=self.factory(identifier)
            return self.children[identifier]

    def records(self):
        b=self.context();result=[]
        for identifier,path in b.cli.drives.files(b.s):
            try:c=b.cli.drives.read(b.s,path);result.append((identifier,c,None))
            except (OSError,ValueError):result.append((identifier,None,'Drive settings could not be read safely.'))
        return result

    def add(self,data):
        b=self.context()
        if set(data)!={'uuid'}:raise ValueError('Choose a supported USB filesystem.')
        row=b.target(data['uuid'])
        if row['transport']!='usb':raise ValueError('Choose a USB drive.')
        with self.mutex:
            records=self.records()
            for identifier,c,error in records:
                if error:raise ValueError(error)
                if c['disk']['uuid']==row['uuid']:return dict(profile_id=identifier,message='Drive is already configured.')
            if len(records)>=64:raise ValueError('This installation supports up to 64 drive profiles.')
            # A retired legacy profile keeps its history/cleanup ledgers. A new
            # registration must not inherit those files or its old API tokens.
            identifier='legacy' if not records and not b.s.CONFIG.with_name('removed-drive.json').exists() else str(uuid.uuid4())
            child,instance=self.get(identifier,create=True)
            with instance.request_lock,child.cli.drives.configuration_lock(child.s):
                row=b.target(data['uuid'])  # Recheck identity after acquiring shared configuration ownership.
                c=child.s.default()
                entries=[entry for entry in b.fstab_entries() if b.same_source(entry[0],row)]
                if len(entries)>1:raise ValueError('Conflicting persistent mounts need review before adding this drive.')
                mount=b.w.unescape_mount(entries[0][1]) if entries else row['mountpoint'] or '/mnt/usb-storage-watch-'+row['uuid']
                c['disk'].update(uuid=row['uuid'],label=row['model'][:40],mountpoint=mount)
                if entries:
                    if entries[0][0]!='UUID='+row['uuid'] or entries[0][2]!='ext4':raise ValueError('Use an unambiguous persistent UUID mount for this drive.')
                    c['disk']['fstab_options']=entries[0][3]
                c['notifications']=copy.deepcopy(b.configuration()['notifications'])
                child.s.validate(c);child.cli.drives.validate_shared(child.s,c)
                child.w.configure(c)
                try:
                    dev=child.w.device_number('/dev/disk/by-uuid/'+row['uuid'])
                    child.w.block_checks(dev,row['uuid'])
                except child.w.Unsafe as exc:raise ValueError(str(exc)) from None
                try:
                    identity=child.w.drives.hardware(child.w.usb_context(),dev,row['uuid'])
                    root=child.s.STATE_DIR if identifier=='legacy' else child.s.STATE_ROOT
                    for active_id, _, _ in records:
                        pin=(root if active_id=='legacy' else root/'drives'/active_id)/'drive-identity.json'
                        if pin.parent==child.s.STATE_DIR or not pin.exists():continue
                        prior=json.loads(pin.read_text())
                        if (identity.get('serial') and prior.get('serial')==identity['serial'] and prior.get('vendor')==identity['vendor'] and prior.get('product')==identity['product']) or (identity.get('wwn') and prior.get('wwn')==identity['wwn']):
                            raise ValueError('Another profile already uses this physical USB disk or an ambiguous hardware serial.')
                    # Legacy profiles may not yet have a pin. A second partition
                    # on the same connected disk is not an independent USB port.
                    for existing,other_config,error in records:
                        try:
                            otherdev=b.w.device_number('/dev/disk/by-uuid/'+other_config['disk']['uuid'])
                            other=child.w.drives.hardware(child.w.usb_context(),otherdev,other_config['disk']['uuid'])
                        except FileNotFoundError:continue
                        if (identity.get('serial') and identity['serial']==other['serial'] and identity['vendor']==other['vendor'] and identity['product']==other['product']) or (identity.get('wwn') and identity['wwn']==other['wwn']):
                            raise ValueError('Another drive profile uses this physical disk or an ambiguous hardware identity.')
                except FileNotFoundError:
                    identity=None  # Missing cached hardware metadata does not authorize a port reset.
                child.cli.save(child.s.CONFIG,c)
                if identity and (identity['serial'] or identity['wwn']):child.w.atomic_write(child.s.STATE_DIR/'drive-identity.json',json.dumps(identity)+'\n')
            return dict(profile_id=identifier,message='Drive added. Configure monitoring and automatic recovery in Manage Drive.')

    def overview(self,request):
        b=self.context();rows=b.disks();result=[];configured=set()
        for identifier,c,error in self.records():
            if error:
                result.append(dict(profile_id=identifier,configured=True,name='Drive settings unavailable',error=error,monitoring='unknown'));continue
            configured.add(c['disk']['uuid']);child,instance=self.get(identifier)
            cached=self.cache.get(identifier);busy=not instance.request_lock.acquire(blocking=False)
            try:
                if not busy:
                    response=instance.local_handle(dict(request,action='status',data={},write=False))
                    if response['status']==200:
                        cached=response['data'];self.cache[identifier]=cached
                    else:error=response.get('error','Status unavailable')
            finally:
                if not busy:instance.request_lock.release()
            value=cached or {};metadata=value.get('discovered') or {};service=value.get('service',{});health=value.get('health',{})
            row=next((v for v in rows if v['uuid']==c['disk']['uuid']),{})
            name=c['disk']['label'] if c['disk']['label']!='USB storage' else metadata.get('model') or row.get('model') or 'Configured USB drive'
            result.append(dict(profile_id=identifier,configured=True,uuid=c['disk']['uuid'],name=name,
                size=metadata.get('size') or row.get('size'),media_kind=metadata.get('media_kind','unknown'),
                mountpoint=c['disk']['mountpoint'],mount_locations=value.get('mount_locations',[]),mounted_expected=value.get('mounted_expected'),
                connected=health.get('detected'),mounted=value.get('mounted'),busy=busy,error=error,
                mount_state=value.get('mount_state', 'unavailable'), mount_detail=value.get('mount_detail', ''),
                mount_target_occupied=value.get('mount_target_occupied'),
                deliberate_stopped_apps=value.get('deliberate_stopped_apps', []),
                hub=(value.get('usb') or {}).get('direct') is False,
                reconnect_available=((value.get('usb') or {}).get('direct') is True and
                                     (value.get('usb') or {}).get('software_reconnect') is True),
                monitoring='unknown' if busy or error else service.get('ActiveState','unknown'),
                recovery_enabled=c['recovery']['mount'],standby=value.get('standby'),progress=value.get('progress',{}),stale=busy or bool(error),observed_at=value.get('observed_at')))
        for row in rows:
            if row['uuid'] in configured or row['transport']!='usb':continue
            result.append(dict(profile_id=None,configured=False,uuid=row['uuid'],name=row['model'],size=row['size'],
                media_kind=row.get('media_kind','unknown'),
                connected=True,mounted=bool(row['mountpoint']),mountpoint=row['mountpoint'],monitoring='inactive',
                recovery_enabled=False,eligible=row['eligible'],error=row['reason']))
        return dict(drives=result,refreshed_at=b.w.timestamp())

    def history(self, data):
        selected=data.get('drive')
        if set(data)-{'drive'}:raise ValueError('Invalid history filter.')
        records=self.records()
        if selected and selected not in {i for i,c,e in records}:raise ValueError('Unknown history drive.')
        events=[];warnings=[];choices=[]
        for identifier,c,error in records:
            name=c['disk']['label'] if c else 'Unavailable drive'
            choices.append(dict(id=identifier,name=name))
            if selected and identifier!=selected:continue
            try:
                if error:raise ValueError(error)
                child,instance=self.get(identifier)
                # History reads atomic incident files and its own SQLite database;
                # it does not probe disks or acquire an operation lock.
                events.extend(row|dict(drive_id=identifier,drive_name=name) for row in instance.history.events(limit=200))
            except (OSError,ValueError,sqlite3.Error,KeyError,TypeError):
                warnings.append(name+': history temporarily unavailable.')
        bounded=[];size=0
        for row in sorted(events,key=lambda row:self.context().History.sort_key(row['time']),reverse=True)[:200]:
            size+=len(json.dumps(row).encode())+2
            if size>90000:break
            bounded.append(row)
        return dict(events=bounded,drives=choices,warnings=warnings)

    def preferences(self):
        b=self.context()
        return dict(drives=[dict(id=i,name=c['disk']['label'],enabled=c['notifications']['enabled'],revision=b.s.digest(c))
                            if c else dict(id=i,name='Unavailable drive',error=e) for i,c,e in self.records()])

    def preparation_target(self, data):
        """Resolve from verified physical identity, never dashboard selection."""
        b=self.context();disk=b.preparation.binding(b.preparation_context(),data.get('device'))
        observed=b.preparation.signatures(disk)
        uuids={item.get('UUID') for item in observed['filesystems']} - {None}
        owners=[]
        for identifier,c,error in self.records():
            if error:raise ValueError(error)
            if c['disk']['uuid'] in uuids:owners.append(identifier)
        if len(owners)>1:raise ValueError('This physical disk contains multiple configured drives. Administrator review is required; nothing was erased.')
        child,instance=self.get(owners[0] if owners else 'legacy')
        if owners:
            with instance.request_lock:
                config=child.configuration()
                row=b.target(config['disk']['uuid'])  # Reject duplicate UUIDs, including unselected disks.
                dev=child.w.device_number(row['device'])
                if dev not in disk['devs']:
                    raise ValueError('The configured filesystem is on a different physical disk. Nothing was erased.')
                child.w.configure(config)
                child.w.block_checks(dev,config['disk']['uuid'])  # Includes the saved hardware pin.
        return child,instance

    def preparations(self):
        result={}
        for identifier in dict.fromkeys(['legacy',*(i for i,c,e in self.records())]):
            child,instance=self.get(identifier)
            with instance.request_lock:value=instance.prepare_progress()
            if value.get('phase')!='idle':
                try:updated=(child.s.STATE_DIR/'prepare-drive.json').stat().st_mtime_ns
                except OSError:updated=0
                key=value.get('device') or identifier
                if key not in result or updated>=result[key][0]:
                    result[key]=(updated,{k:v for k,v in value.items() if k!='config'})
        return [value for updated,value in sorted(result.values(),key=lambda entry:entry[0])]

    def preparation(self,request,session):
        b=self.context();action=request['action'];data=request.get('data',{})
        if action in ('prepare-disks','prepare-progress'):
            if request['write']:raise ValueError('Preparation status is read-only.')
            progress=self.preparations()
            if action=='prepare-disks':return dict(disks=b.preparation.inventory(b.preparation_context()),operations=progress)
            operation=data.get('operation')
            if set(data)!={'operation'} or not isinstance(operation,str):raise ValueError('Select the preparation operation to inspect.')
            value=next((v for v in progress if v.get('operation')==operation),None)
            if value is None:raise ValueError('This preparation result is no longer available. Refresh drives before starting another operation.')
            return value
        if not request['write']:raise ValueError('Drive preparation requires explicit authorization.')
        with self.mutex:
            if action=='prepare-drive-plan':
                session.pop('physical_preparation',None)
                child,instance=self.preparation_target(data)
                with instance.request_lock:
                    chosen=child.preparation.plan(child.preparation_context(),data)
                    account=b.pwd.getpwnam(session['username']);chosen['owner']=(account.pw_uid,account.pw_gid)
                    session['physical_preparation']=(child.s.PROFILE_ID,chosen)
                    return child.preparation.public_plan(chosen)
            if any(v.get('phase') in ('preparing','formatting','mounting','verifying') for v in self.preparations()):
                raise ValueError('Formatting is already in progress. Wait for its result.')
            pending=session.pop('physical_preparation',None)
            if not pending:raise ValueError('Review the physical drive and confirm erasure again.')
            identifier,chosen=pending
            child,instance=self.get(identifier)
            child.preparation.confirm(chosen,data)
            with instance.request_lock:return instance.start_preparation(chosen,data)

    def route(self,request):
        b=self.context();action=request.get('action');identifier=request.get('drive')
        if not isinstance(request.get('data',{}),dict) or type(request.get('write')) is not bool:
            raise ValueError('Invalid request.')
        if action in GLOBAL:return None
        session=self.broker.sessions.check(request.get('token'),request.get('csrf'),request.get('write'))
        if action in ('docker-overview', 'docker-container-settings', 'docker-container-action', 'docker-boot-settings', 'docker-setup-plan', 'docker-setup-apply', 'docker-permission-plan', 'docker-permission-apply', 'docker-app-plan', 'docker-app-save', 'docker-entry-plan', 'docker-entry-apply'):
            if identifier is not None: raise ValueError('Docker settings are global; do not select a drive route.')
            module=b.common.module('web_docker')
            if action == 'docker-overview':
                if request['write'] or request.get('data', {}): raise ValueError('Container discovery is read-only.')
                return dict(status=200, data=module.overview(self))
            if not request['write']: raise ValueError('Saving container settings requires authorization.')
            if action in ('docker-entry-plan', 'docker-entry-apply'):
                editor=b.common.module('app_entries')
                return dict(status=200, data=(editor.plan if action=='docker-entry-plan' else editor.apply)(self, request.get('data', {}), session))
            if action in ('docker-app-plan', 'docker-app-save'):
                editor=b.common.module('app_settings')
                return dict(status=200, data=(editor.plan if action=='docker-app-plan' else editor.save)(self, request.get('data', {}), session))
            if action in ('docker-permission-plan', 'docker-permission-apply'):
                setup=b.common.module('docker_setup')
                return dict(status=200, data=(setup.permission_plan if action=='docker-permission-plan' else setup.permission_apply)(self, request.get('data', {}), session))
            if action in ('docker-setup-plan', 'docker-setup-apply'):
                setup=b.common.module('docker_setup')
                return dict(status=200, data=(setup.plan if action=='docker-setup-plan' else setup.apply)(self, request.get('data', {}), session))
            if action == 'docker-boot-settings':
                return dict(status=200, data=b.common.module('boot_start').update(self, request.get('data', {})))
            if action == 'docker-container-action':
                return dict(status=200, data=module.manual_action(self, request.get('data', {})))
            return dict(status=200, data=module.save(self, request.get('data', {})))
        if action in FLEET and action.startswith('prepare-'):
            return dict(status=200,data=self.preparation(request,session))
        if action in ('fleet-events','notification-preferences'):
            if request['write']:raise ValueError('This information is read-only.')
            return dict(status=200,data=self.history(request.get('data',{})) if action=='fleet-events' else self.preferences())
        if action=='fleet-status':
            if request.get('write'):raise ValueError('Drive overview is read-only.')
            return dict(status=200,data=self.overview(request))
        if action in ('remove-drive-plan','remove-drive'):
            if not identifier:raise ValueError('Select the drive to remove.')
            remover=b.common.module('web_remove');data=request.get('data',{})
            if action=='remove-drive-plan':
                if request['write'] or data:raise ValueError('Removal review is read-only.')
                review=remover.review(self,identifier)
                session['remove:'+identifier]=dict(uuid=review['uuid'],revision=review['revision'],expires=time.monotonic()+300)
                return dict(status=200,data=review)
            if not request['write'] or set(data)!={'uuid','revision','confirm'} or data['confirm'] is not True:
                raise ValueError('Review the selected drive and confirm its removal.')
            approval=session.pop('remove:'+identifier,None)
            if (not approval or time.monotonic()>approval['expires'] or
                    approval['uuid']!=data['uuid'] or approval['revision']!=data['revision']):
                raise ValueError('The removal review expired or changed. Open Remove from Storage Watch again.')
            return dict(status=200,data=remover.apply(self,identifier,data))
        if action in ('drive-rebind-candidates','drive-rebind-plan','drive-rebind-apply'):
            if not identifier:raise ValueError('Select the drive configuration to reconnect.')
            child,instance=self.get(identifier)
            rebinder=b.common.module('web_rebind')
            data=request.get('data',{})
            if action=='drive-rebind-candidates':
                if request['write'] or data:raise ValueError('Drive discovery is read-only.')
                rows=[]
                for row in b.disks():
                    if row.get('transport')!='usb' or not row.get('eligible') or not row.get('uuid'):continue
                    try:
                        record=rebinder.public(rebinder.inspect(self,identifier,row['uuid']))
                        rows.append(record)
                    except (OSError,ValueError,child.w.Unsafe):continue
                return dict(status=200,data=dict(drives=rows))
            if action=='drive-rebind-plan':
                if request['write'] or set(data)!={'uuid'}:raise ValueError('Select one detected replacement filesystem.')
                review=rebinder.inspect(self,identifier,data['uuid'])
                session['rebind:'+identifier]=dict(uuid=review['new_uuid'],revision=review['revision'],
                                                  expires=time.monotonic()+300)
                return dict(status=200,data=rebinder.public(review))
            if not request['write'] or set(data)!={'uuid','revision','confirm'} or data['confirm'] is not True:
                raise ValueError('Review the drive and explicitly confirm the configuration change.')
            approval=session.pop('rebind:'+identifier,None)
            if (not approval or time.monotonic()>approval['expires'] or
                    approval['uuid']!=data['uuid'] or approval['revision']!=data['revision']):
                raise ValueError('The drive review expired or changed. Review it again before reconnecting.')
            result=rebinder.apply(self,identifier,data['uuid'],data['revision'])
            self.cache.pop(identifier,None)
            return dict(status=200,data=result)
        if action=='add-drive':
            if not request.get('write'):raise ValueError('Adding a drive requires authorization.')
            return dict(status=200,data=self.add(request.get('data',{})))
        if identifier is None:raise ValueError('An explicit drive identifier is required. Open Manage Drive from Overview.')
        if identifier=='legacy':return None
        child,instance=self.get(identifier)
        return instance.exclusive_handle(request)

    def observe(self):
        for child,instance in list(self.children.values()):
            if instance.request_lock.acquire(blocking=False):
                try:instance.prepare_progress();instance.history.capture()
                except (OSError,ValueError,KeyError,TypeError,AttributeError,sqlite3.Error):
                    pass  # One unavailable history never blocks other drive observations.
                finally:instance.request_lock.release()
