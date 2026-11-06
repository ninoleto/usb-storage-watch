# SPDX-License-Identifier: MIT
"""Real broker routing/config writes; synthetic Docker and hardware boundaries."""
import copy
import json
import threading
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from gui_fixture import load
from multidrive_fixture import FleetMachine

ID='a'*64
IMAGE='33333333-3333-4333-8333-333333333333'


class ContainerSettings(unittest.TestCase):
    def setUp(self):
        self.f=FleetMachine();self.addCleanup(self.f.close);self.other=self.f.add()
        self.b=self.f.main.b;self.module=load('web_docker')
        self.rows=[dict(id=ID,name='erugo',state='running',health=None,discovered=True,warnings=[],detected_storage=[]),
                   dict(id='b'*64,name='unrelated-ssd-app',state='stopped',health=None,discovered=True,warnings=[],detected_storage=[])]
        self.discovery=Mock(side_effect=lambda *args:(copy.deepcopy(self.rows),'v1.47'))
        self.f.main.patch(self.module,'discover',self.discovery)
        original=self.b.common.module
        self.f.main.patch(self.b.common,'module',lambda name,*args:self.module if name=='web_docker' else original(name,*args))
        c=self.b.configuration();c['images']=[dict(name='backups',uuid=IMAGE,mountpoint='/mnt/drive-a/backups',
            image='/mnt/drive-a/backups.img',enabled=False,fstab_options='loop,nodev,nosuid,noexec')]
        self.b.cli.save(self.b.s.CONFIG,self.b.s.validate(c))
        self.f.second.active=True

    def get(self):
        return self.f.request('docker-overview',profile=None)

    def data(self,enabled=True):
        overview=self.get();self.assertEqual(overview['status'],200,overview)
        return dict(id=ID,name='erugo',revision=overview['data']['revision'],drives=[
            dict(id='legacy',enabled=enabled,images=[IMAGE] if enabled else []),
            dict(id=self.other,enabled=enabled,images=[])])

    def save(self,data):return self.f.request('docker-container-settings',data,profile=None)

    def test_all_containers_listed_without_storage_or_monitoring_eligibility(self):
        result=self.get();self.assertEqual(result['status'],200,result)
        self.assertEqual({r['name'] for r in result['data']['containers']},{'erugo','unrelated-ssd-app'})
        self.assertEqual(len(result['data']['drives']),2)
        self.assertTrue(self.f.main.active);self.assertTrue(self.f.second.active)
        self.assertTrue(all(call[:2]==['/usr/bin/systemctl','show'] for call in self.f.main.calls))

    def test_save_while_both_monitors_active_without_stopping_them(self):
        result=self.save(self.data());self.assertEqual(result['status'],200,result)
        for m in (self.f.main,self.f.second):
            self.assertTrue(m.active)
            config=m.b.configuration();self.assertTrue(config['docker']['enabled'])
            spec=config['docker']['containers'][0]
            self.assertEqual(spec['container_id'],ID);self.assertEqual(spec['source'],'')
            self.assertEqual(spec['images'],[IMAGE] if m is self.f.main else [])
            self.assertFalse(any(call[:2]==['/usr/bin/systemctl','stop'] for call in m.calls))
        self.b.cli.drives.validate_shared(self.b.s,self.b.configuration())

    def test_explicit_replacement_updates_only_ids_and_never_reassigns_by_name(self):
        self.assertEqual(self.save(self.data())['status'],200)
        self.f.second.active=False
        before=[m.b.configuration() for m in (self.f.main,self.f.second)]
        replacement='c'*64;self.rows[0]['id']=replacement
        view=self.get()['data']
        self.assertTrue(any(v['id']==ID for v in view['settings']))
        self.assertEqual(before,[m.b.configuration() for m in (self.f.main,self.f.second)])
        data=self.data()
        self.assertEqual(self.save(data)['status'],400)  # Stale explicit ID refused.
        self.assertEqual(before,[m.b.configuration() for m in (self.f.main,self.f.second)])
        data['id']=replacement
        self.assertEqual(self.save(data)['status'],200)
        for old,m in zip(before,(self.f.main,self.f.second)):
            expected=copy.deepcopy(old)
            expected['docker']['containers'][0]['container_id']=replacement
            actual=m.b.configuration();self.assertEqual(actual,expected)
            m.b.w.configure(actual)
            m.b.w.apps.validate_container('erugo',dict(id=replacement,name='erugo'))
            with self.assertRaises(m.b.w.apps.AppError):
                m.b.w.apps.validate_container('erugo',dict(id=ID,name='erugo'))
        self.assertTrue(self.f.main.active);self.assertFalse(self.f.second.active)
        self.rows[0]['id']='d'*64
        self.get()
        self.assertTrue(all(m.b.configuration()['docker']['containers'][0]['container_id']==replacement
                            for m in (self.f.main,self.f.second)))

    def test_slow_discovery_does_not_hold_monitor_configuration_lock(self):
        data=self.data();seen=[]
        def discovery(*args):
            def probe():
                try:
                    with self.b.cli.drives.configuration_lock(self.b.s):seen.append('available')
                except OSError:seen.append('blocked')
            worker=threading.Thread(target=probe);worker.start();worker.join(2)
            self.assertFalse(worker.is_alive())
            return copy.deepcopy(self.rows),'v1.47'
        self.discovery.side_effect=discovery
        self.assertEqual(self.save(data)['status'],200)
        self.assertEqual(seen,['available'])

    def test_selected_image_does_not_change_mount_on_recovery(self):
        self.assertEqual(self.save(self.data())['status'],200)
        self.assertFalse(self.b.configuration()['images'][0]['enabled'])

    def test_stale_revision_rejected_without_any_partial_changes(self):
        data=self.data();c=self.f.second.b.configuration();c['monitor']['interval']=45
        self.f.second.b.cli.save(self.f.second.config,c)
        before=[m.config.read_bytes() for m in (self.f.main,self.f.second)]
        self.assertEqual(self.save(data)['status'],400)
        self.assertEqual(before,[m.config.read_bytes() for m in (self.f.main,self.f.second)])

    def test_foreign_image_rejected_before_any_write(self):
        data=self.data();data['drives'][1]['images']=[IMAGE]
        before=[m.config.read_bytes() for m in (self.f.main,self.f.second)]
        self.assertEqual(self.save(data)['status'],400)
        self.assertEqual(before,[m.config.read_bytes() for m in (self.f.main,self.f.second)])

    def test_failed_second_write_rolls_back_first(self):
        data=self.data();before=[m.b.configuration() for m in (self.f.main,self.f.second)]
        original=self.b.cli.save;calls=0
        def fail_once(path,value):
            nonlocal calls
            if path==self.f.second.config:
                calls+=1
                if calls==1:raise OSError('synthetic write failure')
            return original(path,value)
        with patch.object(self.b.cli,'save',fail_once):
            result=self.save(data)
        self.assertEqual(result['status'],400,result)
        self.assertEqual(before,[m.b.configuration() for m in (self.f.main,self.f.second)])
        self.assertFalse(self.module.journal_path(self.b).exists())

    def test_interrupted_transaction_rolls_back_before_exposing_settings(self):
        before=self.b.configuration();after=copy.deepcopy(before);after['docker']['containers']=[dict(
            name='erugo',source='',destination='',grace=30,container_id=ID,images=[])];after['docker']['enabled']=True
        self.b.cli.save(self.module.journal_path(self.b),dict(version=1,before={'legacy':before},after={'legacy':after}))
        self.b.cli.save(self.b.s.CONFIG,after)
        self.assertEqual(self.get()['status'],200)
        self.assertEqual(self.b.configuration(),before)

    def test_interrupted_transaction_never_overwrites_later_unrelated_edit(self):
        before=self.b.configuration();after=copy.deepcopy(before);after['monitor']['interval']=30
        self.b.cli.save(self.module.journal_path(self.b),dict(version=1,before={'legacy':before},after={'legacy':after}))
        later=copy.deepcopy(after);later['disk']['label']='Later edit';self.b.cli.save(self.b.s.CONFIG,later)
        self.assertEqual(self.get()['status'],400)
        self.assertEqual(self.b.configuration(),later)

    def test_daemon_failure_keeps_saved_settings_and_allows_disabling(self):
        self.assertEqual(self.save(self.data())['status'],200)
        self.discovery.side_effect=RuntimeError('daemon response must not leak')
        view=self.get();self.assertEqual(view['status'],200,view)
        self.assertEqual(view['data']['containers'][0]['state'],'unknown')
        self.assertNotIn('response must not leak',json.dumps(view))
        data=dict(id=ID,name='erugo',revision=view['data']['revision'],drives=[
            dict(id=drive['id'],enabled=False,images=[]) for drive in view['data']['drives']])
        self.assertEqual(self.save(data)['status'],200)
        self.assertFalse(self.b.configuration()['docker']['enabled'])

    def test_legacy_bind_selection_migrates_without_inventing_image_choice(self):
        c=self.b.configuration();c['docker'].update(enabled=True,containers=[dict(name='erugo',source='/some/ssd/path',destination='/data',grace=30)])
        self.b.cli.save(self.b.s.CONFIG,c)
        spec=self.b.configuration()['docker']['containers'][0]
        self.assertEqual(spec['container_id'],'');self.assertEqual(spec['images'],[])
        view=self.get()['data'];choice=next(v for v in view['settings'] if v['id']==ID)
        self.assertTrue(choice['drives'][0]['enabled']);self.assertEqual(choice['drives'][0]['images'],[])

    def test_missing_saved_container_stays_visible_and_can_be_removed(self):
        self.assertEqual(self.save(self.data())['status'],200)
        self.rows=[];view=self.get()['data'];self.assertEqual(view['containers'][0]['state'],'missing')
        self.assertEqual(self.save(self.data(False))['status'],200)

    def test_no_auth_or_csrf_cannot_mutate_and_global_route_has_no_drive(self):
        data=self.data()
        result=self.broker_call('docker-container-settings',data,csrf='wrong')
        self.assertEqual(result['status'],401)
        self.assertEqual(self.f.request('docker-overview')['status'],400)

    def test_real_discovery_includes_ssd_readonly_and_image_bindings_as_advice(self):
        connection=Mock();connection.getresponse.return_value=Mock(status=200,read=lambda _:b'{"ApiVersion":"1.47","MinAPIVersion":"1.24"}')
        docker=Mock();docker.request.return_value=[dict(Id=ID),dict(Id='b'*64)]
        def inspect(identity):
            return dict(id=identity,name='erugo' if identity==ID else 'ssd-app',running=True,paused=False,
                        restarting=False,dead=False,health=None,mounts=[dict(Type='bind',
                        Source='/mnt/drive-a/backups/uploads' if identity==ID else '/srv/ssd/data',
                        Destination='/data',RW=False,Propagation='shared')])
        docker.inspect.side_effect=inspect
        module=SimpleNamespace(configure=Mock(),LocalConnection=Mock(return_value=connection),Docker=Mock(return_value=docker))
        real=load('web_docker')
        actual_module = self.b.common.module
        with patch.object(self.b.common,'module',side_effect=lambda name,*args: module if name=='apps' else actual_module(name,*args)):
            rows,_=real.discover(self.b,real.records(self.f.main.broker.fleet))
        self.assertEqual(len(rows),2)
        self.assertTrue(all(row['discovered'] for row in rows))
        self.assertEqual(rows[0]['detected_storage'][-1]['image_uuid'],IMAGE)
        self.assertEqual(rows[1]['detected_storage'],[])
        docker.change.assert_not_called();docker.access.assert_not_called()

    def test_event_history_reports_image_warning_separately_from_container_restart(self):
        history=self.b.History(self.f.main.state/'history-unit.sqlite3')
        history.record=Mock()
        history.capture_incident(dict(id='incident',applications=dict(phase='done',result=dict(
            images={IMAGE:dict(name='backups',status='warning',detail='Mount failed')},
            containers={'erugo':dict(status='verified',reason='Restart complete',action_count=1,warnings=['Uploads may fail'])}))))
        lines=history.record.call_args.args[-1]
        self.assertTrue(any('Image backups: warning' in line for line in lines))
        self.assertTrue(any('erugo: verified' in line for line in lines))
        self.assertTrue(any('Uploads may fail' in line for line in lines))

    def broker_call(self,action,data,csrf):
        return self.f.main.broker.handle(dict(action=action,data=data,write=True,token=self.f.session['token'],csrf=csrf))


if __name__=='__main__':unittest.main()
