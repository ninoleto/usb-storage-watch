# SPDX-License-Identifier: MIT
"""Independent profiles, shared-resource refusal and upgrade regressions. No hardware I/O."""
import copy
import fcntl
import json
import os
from pathlib import Path
import threading
import time
import types
import unittest
from unittest.mock import Mock,patch
from gui_fixture import UUID,load
from multidrive_fixture import FleetMachine,SECOND


class MultiDriveTests(unittest.TestCase):
    def setUp(self):
        self.f=FleetMachine();self.addCleanup(self.f.close);self.m=self.f.main

    def test_add_second_while_first_running_preserves_every_legacy_file(self):
        for name in ('state.json','standby.json','manual-operation.json'):
            (self.m.state/name).write_text(json.dumps({'sentinel':name}))
        token=self.m.management_token()
        before={p:p.read_bytes() for p in self.m.root.rglob('*') if p.is_file()}
        profile=self.f.add();b=self.f.second.b
        self.assertTrue(self.m.active);self.assertFalse(self.f.second.active)
        self.assertEqual(b.configuration()['disk']['uuid'],SECOND)
        self.assertEqual(b.configuration()['disk']['mountpoint'],'/mnt/drive-b')
        self.assertEqual(b.s.SMTP,self.m.b.s.SMTP)
        self.assertEqual(b.cli.SERVICE,'usb-storage-watch@'+profile+'.service')
        for path,content in before.items():self.assertEqual(path.read_bytes(),content,str(path))
        self.assertEqual(self.f.request('add-drive',dict(uuid=SECOND))['data']['profile_id'],profile)
        self.assertEqual(len(self.f.main.broker.fleet.records()),2)
        self.assertTrue(token)

    def test_start_stop_and_settings_are_scoped(self):
        profile=self.f.add();child=self.f.second
        result=self.f.request('monitor',{'enabled':True},profile)
        self.assertEqual(result['status'],200,result);self.assertTrue(child.active);self.assertTrue(self.m.active)
        result=self.f.request('monitor',{'enabled':False},profile)
        self.assertEqual(result['status'],200,result);self.assertFalse(child.active);self.assertTrue(self.m.active)
        config=self.f.request('config',profile=profile)['data']
        self.assertEqual(config['config']['disk']['uuid'],SECOND)
        self.assertEqual(self.f.request('config')['data']['config']['disk']['uuid'],UUID)
        self.assertFalse(any(args[:2]==['/usr/bin/systemctl','stop'] for args in self.m.calls))

    def test_each_engine_worker_and_default_state_path_belongs_to_its_profile(self):
        profile=self.f.add();a,b=self.m.b.w,self.f.second.b.w
        self.assertEqual(b.CONFIG,self.f.second.config)
        self.assertEqual(b.Monitor.__init__.__defaults__[0],self.f.second.state/'state.json')
        self.assertEqual(b.Worker.__init__.__defaults__[0],self.f.second.state)
        self.assertEqual(b.settings.worker_environment()['USB_STORAGE_WATCH_DRIVE'],profile)
        self.assertEqual(a.settings.worker_environment()['USB_STORAGE_WATCH_DRIVE'],'legacy')
        a.configure(self.m.b.configuration());b.configure(self.f.second.b.configuration())
        self.assertEqual(a.DISK_UUID,UUID);self.assertEqual(b.DISK_UUID,SECOND)
        self.assertIsNot(a.usb,b.usb);self.assertIsNot(a.apps,b.apps)

    def test_real_worker_process_inherits_only_its_drive_identifier(self):
        profile=self.f.add();w=self.f.second.b.w
        code="import importlib.util,json; s=importlib.util.spec_from_file_location('settings',"+repr(str(Path(w.__file__).with_name('settings.py')))+");m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(json.dumps(dict(profile=m.PROFILE_ID,config=str(m.CONFIG))))"
        worker=w.Worker(['/usr/bin/python3','-I','-c',code],{},5,directory=self.f.second.state)
        try:
            while worker.poll() is None:time.sleep(0.01)
            result=w.worker_json(worker)
            self.assertEqual(result['profile'],profile)
            self.assertEqual(result['config'],'/etc/usb-storage-watch/drives/'+profile+'/config.json')
        finally:worker.cancel();worker.close()

    def test_busy_first_drive_does_not_block_second_or_fleet_observation(self):
        profile=self.f.add();entered=threading.Event();release=threading.Event()
        def operation():
            with self.m.broker.request_lock:entered.set();release.wait(5)
        thread=threading.Thread(target=operation);thread.start();self.addCleanup(release.set)
        try:
            self.assertTrue(entered.wait(2))
            result=self.f.request('status',profile=profile);self.assertEqual(result['status'],200,result)
            result=self.f.request('fleet-status');self.assertEqual(result['status'],200,result)
            rows={row['profile_id']:row for row in result['data']['drives']}
            self.assertTrue(rows['legacy']['busy']);self.assertEqual(rows['legacy']['monitoring'],'unknown')
            self.assertFalse(rows[profile]['busy']);self.assertTrue(rows[profile]['connected'])
        finally:release.set();thread.join(5)

    def test_disconnection_and_failed_recovery_are_not_shared(self):
        profile=self.f.add();self.f.second.active=True
        self.m.present=False;self.m.current=''
        failed=dict(phase='failed',reason='A did not return',id='incident-a')
        self.m.patch(self.m.b.w,'load_state',lambda *a:dict(incident=failed))
        result=self.f.request('fleet-status');self.assertEqual(result['status'],200,result)
        a,b=result['data']['drives'];self.assertFalse(a['connected']);self.assertTrue(b['connected']);self.assertTrue(b['mounted'])
        self.assertNotEqual(b['progress']['code'],'failed');self.assertEqual(b['monitoring'],'active')
        self.m.present=True;self.m.current='/mnt/drive-a';self.f.second.present=False;self.f.second.current=''
        a,b=self.f.request('fleet-status')['data']['drives'];self.assertTrue(a['connected']);self.assertFalse(b['connected'])

    def test_duplicate_uuid_mount_or_application_owner_is_refused(self):
        profile=self.f.add();child=self.f.second;c=child.b.configuration()
        changed=copy.deepcopy(c);changed['disk']['uuid']=UUID
        with self.assertRaisesRegex(ValueError,'UUID'):child.b.cli.save(child.config,changed)
        changed=copy.deepcopy(c);changed['disk']['mountpoint']='/mnt/drive-a/child'
        with self.assertRaisesRegex(ValueError,'overlap'):child.b.cli.save(child.config,changed)
        a=self.m.b.configuration();a['services'].update(units=['synthetic.service']);self.m.b.cli.save(self.m.config,a)
        changed=copy.deepcopy(c);changed['services'].update(units=['synthetic.service'])
        with self.assertRaisesRegex(ValueError,'recovery owner'):child.b.cli.save(child.config,changed)
        self.assertEqual(child.b.configuration(),c)

    def test_authorization_and_invalid_profile_fail_closed(self):
        profile=self.f.add()
        for action,write in [('fleet-status',False),('add-drive',True),('config',False),('monitor',True)]:
            request=dict(action=action,write=write,drive=profile,data={'enabled':False} if action=='monitor' else {})
            self.assertEqual(self.m.broker.handle(request)['status'],401)
        self.assertEqual(self.f.request('config',profile='../../etc')['status'],400)
        self.assertEqual(self.f.request('config',profile=str(__import__('uuid').uuid4()))['status'],400)
        self.assertEqual(self.m.broker.handle(dict(drive='legacy',action='add-drive',write=True,data={'uuid':SECOND},token=self.f.session['token']))['status'],401)
        self.assertTrue(self.m.active)

    def test_pending_confirmation_cannot_cross_profiles(self):
        profile=self.f.add();session=self.m.broker.sessions.sessions[self.f.session['token']]
        session['folder_access']={'token':'A-only'};session['image_plan']={'token':'A-only'};session['prepare_drive']={'token':'A-only'}
        child=self.f.second
        with patch.object(child.b.images,'permission_apply',side_effect=lambda b,chosen,data: {'chosen':chosen}), \
             patch.object(child.b.images,'apply',side_effect=lambda b,chosen,data:{'chosen':chosen}), \
             patch.object(child.broker,'start_preparation',side_effect=lambda chosen,data:{'chosen':chosen}):
            for action in ('folder-access-apply','image-apply'):
                result=self.f.request(action,{},profile);self.assertEqual(result['status'],200,result);self.assertIsNone(result['data']['chosen'])
        self.assertEqual(session['prepare_drive']['token'],'A-only')

    def test_cross_profile_formatting_is_refused_before_any_disk_access(self):
        self.f.add()
        with self.assertRaisesRegex(ValueError,'another drive profile'):
            self.m.b.preparation.other_owner(self.m.b.preparation_context(),{SECOND})

    def test_preparing_an_additional_disk_keeps_the_active_monitor_and_its_locks(self):
        b=self.m.b;self.m.patch(b.w,'assert_internal_state',Mock())
        with (self.m.state/'monitor.lock').open('a') as monitor,(self.m.state/'recovery.lock').open('a') as recovery:
            fcntl.flock(monitor,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(recovery,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with b.preparation.exclusive(b.preparation_context(),own_monitor=False):
                self.assertTrue(self.m.active)
            with self.assertRaises(ValueError):
                with b.preparation.exclusive(b.preparation_context(),own_monitor=True):pass
        self.assertTrue(self.m.active)

    def test_runtime_duplicate_uuid_and_changed_hardware_fail_closed(self):
        d=self.m.b.w.drives;root=self.m.root
        cache=root/'udev';sysfs=root/'sys';cache.mkdir();sysfs.mkdir();(sysfs/'240:2').touch()
        (cache/'b240:2').write_text('E:ID_FS_UUID='+UUID+'\n')
        with self.assertRaisesRegex(self.m.b.w.Unsafe,'Duplicate'):d.unique_uuid(self.m.b.w,'240:1',UUID,cache,sysfs)
        (sysfs/'240:2').unlink();d.unique_uuid(self.m.b.w,'240:1',UUID,cache,sysfs)
        self.m.b.w.configure(self.m.b.configuration());saved=dict(uuid=UUID,serial='original')
        (self.m.state/'drive-identity.json').write_text(json.dumps(saved))
        with patch.object(d,'hardware',return_value=dict(saved,serial='unrelated')):
            with self.assertRaisesRegex(self.m.b.w.Unsafe,'different hardware'):d.verify_hardware(self.m.b.w,'240:1',UUID)

    def test_same_port_is_exclusive_but_different_ports_are_independent(self):
        self.f.add();a=self.m.b.w;b=self.f.second.b.w
        with a.drives.port_lock(a.usb_context(),'/synthetic/controller/port1'):
            with self.assertRaises(BlockingIOError):
                with b.drives.port_lock(b.usb_context(),'/synthetic/controller/port1'):pass
            with b.drives.port_lock(b.usb_context(),'/synthetic/controller/port2'):pass
        (self.m.state/'usb-reset.json').write_text(json.dumps(dict(phase='enabling',port='/synthetic/controller/port1')))
        with self.assertRaisesRegex(b.Unsafe,'unresolved'):
            with b.drives.port_lock(b.usb_context(),'/synthetic/controller/port1'):pass
        with b.drives.port_lock(b.usb_context(),'/synthetic/controller/port10'):pass

    def test_upgrade_restarts_each_previously_active_profile_and_checks_cleanup(self):
        profile=self.f.add();m=load('maintenance');active={'usb-storage-watch.service','usb-storage-watch@'+profile+'.service'};calls=[]
        def call(*args,**kw):calls.append(args);return 0 if args[0]!='is-active' or args[-1] in active else 3
        with patch.object(m,'STATE',self.m.state),patch.object(m,'MARKER',self.m.state/'package-was-active'),patch.object(m,'call',call), \
             patch.object(m.os,'geteuid',return_value=0),patch.object(m.Path,'is_dir',return_value=True),patch.dict(os.environ,{},clear=True):
            m.main('prepare-upgrade');m.main('finish-upgrade')
            self.assertEqual({c[1] for c in calls if c[0]=='start'},active)
            (self.f.second.state/'usb-reset.json').write_text('{"phase":"disable-requested"}')
            with self.assertRaisesRegex(RuntimeError,'Unresolved'):m.main('prepare-upgrade')

    def test_simultaneous_incidents_have_independent_budgets_history_and_notification_queues(self):
        self.f.add();engines=[];monitors=[]
        for m in (self.m,self.f.second):
            w=m.b.common.module('engine',dict(id=m.b.s.PROFILE_ID,config_root=str(self.m.root/'config'),state_root=str(self.m.state)))
            c=m.b.configuration();c['notifications']['enabled']=True;w.configure(c);w.log=Mock()
            engines.append(w);monitors.append(w.Monitor(now=0,boot='synthetic-boot',application_tracking=False))
        def observed(ok):return dict(healthy=ok,detected=ok,dependent=ok,unsafe=False,detail='Isolated sample',dependent_detail='No extra images',mounts=[])
        for monitor in monitors:
            monitor.sample(observed(True),0);monitor.sample(observed(True),15)
            monitor.sample(observed(False),30);monitor.sample(observed(False),45)
            monitor.sample(dict(observed(False),detected=True,detail='Selected disk returned unmounted.'),60)
        a,b=monitors
        self.assertNotEqual(a.state['incident']['id'],b.state['incident']['id'])
        ar=a.work_request(True,105);br=b.work_request(True,105)
        outcome=dict(main=False,dependent=False,detected=False,actions=[],blocked=[],reason='A unavailable',dependent_reason='',mounts=[])
        a.work_result(ar,outcome,106)
        a_before=a.path.read_bytes()
        b.work_result(br,dict(outcome,main=True,dependent=True,detected=True,reason='B restored'),106)
        b.sample(observed(True),120);b.sample(observed(True),135)
        self.assertEqual(a.path.read_bytes(),a_before)
        self.assertIn('FAILED',a.state['incident']['outcome']);self.assertNotIn('FAILED',b.state['incident']['outcome'])
        self.assertEqual(len(a.state['incident']['attempts']),1);self.assertEqual(len(b.state['incident']['attempts']),1)
        self.assertIsNone(a.work_request(True,180));self.assertIsNone(b.work_request(True,180))
        self.assertNotEqual(a.state['pending'][0]['id'],b.state['pending'][0]['id'])
        self.assertEqual(a.state['pending'][0]['subject'].split(' ')[0],'ADATA')
        self.assertEqual(b.state['pending'][0]['subject'].split(' ')[0],'SanDisk')
        for w,monitor in zip(engines,monitors):
            restarted=w.Monitor(now=150,boot='synthetic-boot',application_tracking=False)
            self.assertEqual(restarted.state['incident']['id'],monitor.state['incident']['id'])
            self.assertEqual(restarted.state['pending'],monitor.state['pending'])

    def test_independent_monitor_and_operation_locks(self):
        self.f.add()
        for name in ('monitor.lock','recovery.lock'):
            with (self.m.state/name).open('a') as a,(self.f.second.state/name).open('a') as b:
                fcntl.flock(a,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(b,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with (self.m.state/name).open('a') as duplicate:
                    with self.assertRaises(BlockingIOError):fcntl.flock(duplicate,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def test_shared_container_and_storage_checks_refuse_unavailable_other_drive(self):
        self.f.add();b=self.f.second.b.w;c=self.m.b.configuration();c['disk']['mountpoint']='/mnt/drive-a'
        with patch.object(b,'device_number',side_effect=FileNotFoundError('A missing')) as probe:
            with self.assertRaises(FileNotFoundError):b.drives.verify_other_storage(b.usb_context(),['/mnt/drive-a/data'])
            probe.assert_called_once()
        with patch.object(b,'device_number') as probe:
            b.drives.verify_other_storage(b.usb_context(),['/mnt/drive-b/data']);probe.assert_not_called()

    def test_production_factory_retains_global_authority_and_private_profile_paths(self):
        identifier='33333333-3333-4333-8333-333333333333'
        child,broker=self.m.broker.fleet.create(identifier)
        self.assertIs(broker.sessions,self.m.broker.sessions);self.assertIs(child.auth,self.m.b.auth)
        self.assertIsNone(broker.fleet)
        self.assertEqual(child.s.CONFIG,self.m.config.parent/'drives'/identifier/'config.json')
        self.assertEqual(child.w.STATE_DIR,self.m.state/'drives'/identifier)
        self.assertEqual(child.s.SMTP,self.m.b.s.SMTP)
        self.assertEqual(child.s.STATE_DIR.stat().st_mode & 0o777,0o700)

    def test_duplicate_hardware_identity_is_refused_even_with_different_filesystem_uuid(self):
        original=self.m.broker.fleet.factory
        identity=dict(uuid=SECOND,serial='SAME-HARDWARE',wwn='',vendor='synthetic',product='flash',size=1024)
        (self.m.state/'drive-identity.json').write_text(json.dumps(dict(identity,uuid=UUID)))
        def factory(identifier):
            child,broker=original(identifier);self.f.second.patch(child.w.drives,'hardware',lambda *a:identity);return child,broker
        self.m.broker.fleet.factory=factory
        response=self.f.request('add-drive',dict(uuid=SECOND))
        self.assertEqual(response['status'],400,response);self.assertIn('physical USB disk',response['error'])
        self.assertFalse(self.f.second.config.exists());self.assertTrue(self.m.active)

    def test_distinct_cached_hardware_pins_do_not_replace_the_new_drive_configuration(self):
        original=self.m.broker.fleet.factory
        def factory(identifier):
            child,broker=original(identifier)
            self.f.second.patch(child.w.drives,'hardware',lambda w,dev,uuid:dict(uuid=uuid,serial='SERIAL-'+uuid,wwn='',vendor='fixture',product='flash',size=1024))
            return child,broker
        self.m.broker.fleet.factory=factory
        self.f.add();self.assertEqual(self.f.second.b.configuration()['disk']['uuid'],SECOND)
        pin=json.loads((self.f.second.state/'drive-identity.json').read_text());self.assertEqual(pin['uuid'],SECOND)

    def test_second_profile_identity_refusal_returns_specific_error_without_config_write(self):
        original=self.m.broker.fleet.factory
        def factory(identifier):
            child,broker=original(identifier)
            self.f.second.patch(child.w,'block_checks',Mock(side_effect=child.w.Unsafe('Duplicate filesystem UUID; operation refused.')))
            return child,broker
        self.m.broker.fleet.factory=factory
        response=self.f.request('add-drive',{'uuid':SECOND})
        self.assertEqual(response['status'],400,response);self.assertIn('Duplicate filesystem UUID',response['error'])
        self.assertFalse(self.f.second.config.exists());self.assertTrue(self.m.active)

    def test_three_profiles_keep_images_timings_and_standby_settings_separate(self):
        profile=self.f.add();child=self.f.second
        for m,number in ((self.m,1),(child,2)):
            c=m.b.configuration();mount=c['disk']['mountpoint']
            c['images']=[dict(name='Image '+str(index),uuid=f'{number}{index}abcdef-1111-4111-8111-111111111111',
                image=mount+'/volumes/'+str(index)+'.img',mountpoint=mount+'/spaces/'+str(index),
                enabled=True,fstab_options='loop,nofail,nodev,nosuid') for index in (1,2)]
            c['monitor']['interval']=number*20;c['standby']['idle_seconds']=number*600
            m.b.cli.save(m.config,m.b.s.validate(c))
        identifier='33333333-3333-4333-8333-333333333333'
        third,broker=self.m.broker.fleet.create(identifier);c=third.s.default()
        c['disk'].update(uuid=identifier,mountpoint='/mnt/drive-c',label='Third drive');third.cli.save(third.s.CONFIG,c)
        self.assertEqual(len(self.m.broker.fleet.records()),3)
        for m,number in ((self.m,1),(child,2)):
            result=self.f.request('config',profile=m.b.s.PROFILE_ID)['data']['config']
            self.assertEqual(len(result['images']),2);self.assertEqual(result['monitor']['interval'],number*20)
            self.assertEqual(result['standby']['idle_seconds'],number*600)
        self.assertEqual(self.m.b.configuration()['disk']['uuid'],UUID)


if __name__=='__main__':unittest.main()
