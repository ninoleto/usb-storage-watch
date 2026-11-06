# SPDX-License-Identifier: MIT
"""UI11 Docker configuration and read-only status/preflight boundaries."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from gui_fixture import Machine, UUID, load
from multidrive_fixture import FleetMachine


class ApplicationSettings(unittest.TestCase):
    def setUp(self):
        self.m=Machine();self.addCleanup(self.m.close);self.b=self.m.b
        self.c=self.b.s.default();self.c['disk'].update(uuid=UUID,mountpoint=self.m.current)
        self.spec=dict(name='test-app',source=self.m.current+'/app',destination='/data',grace=47)
        self.c['docker'].update(enabled=True,containers=[self.spec])
        self.b.cli.save(self.m.config,self.c)
        self.rows=[dict(id='a'*64,name='test-app',binds=[dict(source=self.spec['source'],destination='/data',eligible=True)])]
        self.b.container_rows.return_value=self.rows

    def data(self,**values):return dict(revision=self.b.s.digest(self.b.configuration()),**values)

    def test_save_rescans_identity_and_preserves_grace(self):
        self.b.application_settings(self.data(enabled=True,containers=[dict(id='a'*64,destination='/data')]))
        self.assertEqual(self.b.configuration()['docker']['containers'],[self.spec | dict(container_id='a'*64,images=[])])
        self.b.container_rows.assert_called_once()
        self.assertFalse(self.m.active)
        self.assertEqual(self.m.calls,[])

    def test_disable_offline_preserves_selection_and_clear_skips_daemon(self):
        self.b.container_rows.side_effect=ValueError('Daemon absent')
        self.b.application_settings(self.data(enabled=False))
        self.assertFalse(self.b.configuration()['docker']['enabled'])
        self.assertEqual(self.b.configuration()['docker']['containers'],[self.spec | dict(container_id='',images=[])])
        self.b.application_settings(self.data(enabled=False,containers=[]))
        self.assertEqual(self.b.configuration()['docker']['containers'],[])
        self.b.container_rows.assert_not_called()

    def test_stale_invalid_and_replaced_identity_refused_but_monitoring_and_binds_are_not_gates(self):
        before=self.m.config.read_bytes()
        with self.assertRaises(ValueError):self.b.application_settings(dict(revision='stale',enabled=False))
        for data in [dict(enabled='false'),dict(enabled=True,containers=[]),dict(enabled=True,containers=[dict(id='b'*64,destination='/data')]),dict(containers='bad'),dict(unknown=True)]:
            with self.assertRaises(ValueError):self.b.application_settings(self.data(**data))
        self.assertEqual(self.m.config.read_bytes(),before)
        self.m.active=True
        self.b.application_settings(self.data(enabled=False))
        self.assertTrue(self.m.active)
        self.rows[0]['binds'][0]['eligible']=False
        self.b.application_settings(self.data(containers=[dict(id='a'*64,destination='/data')]))
        self.assertTrue(self.b.configuration()['docker']['enabled'])
        self.assertEqual(self.m.calls,[])

    def test_current_status_is_metadata_only_and_historical_result_is_separate(self):
        docker=Mock();docker.inspect.return_value=dict(id='a'*64,name='test-app',running=False,paused=False,restarting=False,dead=False,health=None,mounts=[dict(Type='bind',Source=self.spec['source'],Destination='/data',RW=True,Propagation='rprivate')],Env=['SECRET=not-public'])
        self.m.patch(self.b.w.apps,'Docker',Mock(return_value=docker));self.m.patch(self.b,'docker_api',Mock())
        self.m.patch(self.b.w,'load_state',lambda:dict(incident=dict(finished_at='2026-01-01T00:00:00Z',applications=dict(result=dict(containers={'test-app':dict(status='verified',reason='Restart completed',action='restart',action_count=1,attempted_at='2026-01-01T00:00:01Z',finished_at='2026-01-01T00:00:02Z',secret='not-public')})))))
        result=self.b.application_status();row=result['containers'][0]
        self.assertEqual(row['state'],'stopped');self.assertEqual(row['recovery']['status'],'verified')
        self.assertEqual(row['recovery']['action'],'restart')
        self.assertEqual(row['recovery_time'],'2026-01-01T00:00:02Z')
        self.assertEqual(row['recovery']['attempted_at'],'2026-01-01T00:00:01Z')
        self.assertNotIn('not-public',json.dumps(result))
        docker.change.assert_not_called();docker.access.assert_not_called();docker.request.assert_not_called()
        docker.inspect.side_effect=self.b.w.apps.AppError('Docker unavailable')
        self.assertEqual(self.b.application_status()['containers'][0]['state'],'unknown')

    def test_explicit_check_uses_bounded_worker_and_no_restart(self):
        worker=Mock(timed_out=False);worker.poll.return_value=True
        data={'test-app':dict(self.spec,id='a'*64,running=True,verification=dict(inside_access=True,bind_identity_verified=True))}
        worker.output=io.BytesIO(json.dumps(data).encode())
        create=self.m.patch(self.b.w,'Worker',Mock(return_value=worker))
        result=self.b.application_check(self.data())
        self.assertTrue(result['containers'][0]['verified'])
        self.assertEqual(create.call_args.args[0][-1],'_verify-apps');self.assertEqual(create.call_args.args[2],30)
        worker.cancel.assert_called_once();worker.close.assert_called_once()
        self.assertEqual(self.m.calls,[])
        for timeout,done,body in [(True,False,{}),(False,False,dict(error='Access refused')),(False,True,{}),(False,True,{'test-app':dict(running=True)})]:
            worker.timed_out=timeout;worker.poll.return_value=done;worker.output=io.BytesIO(json.dumps(body).encode())
            with self.assertRaises(ValueError):self.b.application_check(self.data())

    def test_check_stopped_is_not_reported_as_access_verified(self):
        worker=Mock(timed_out=False);worker.poll.return_value=True
        worker.output=io.BytesIO(json.dumps({'test-app':dict(self.spec,running=False,verification='Stopped preserved')}).encode())
        self.m.patch(self.b.w,'Worker',Mock(return_value=worker))
        result=self.b.application_check(self.data())
        self.assertFalse(result['containers'][0]['verified']);self.assertIn('not tested',result['containers'][0]['message'])

    def test_authentication_and_csrf_protect_new_actions(self):
        for action,write in [('application-status',False),('application-check',True)]:
            result=self.m.broker.local_handle(dict(action=action,write=write,data={}))
            self.assertEqual(result['status'],401)
        session=self.m.broker.sessions.login('admin','synthetic')
        result=self.m.broker.local_handle(dict(action='application-check',write=True,data={},token=session['token']))
        self.assertEqual(result['status'],401)


class ApplicationDriveIsolation(unittest.TestCase):
    def test_same_container_can_be_selected_on_multiple_drives(self):
        f=FleetMachine();self.addCleanup(f.close);identifier=f.add();a=f.main;b=f.second
        a.active=b.active=False
        for m in (a,b):
            m.b.container_rows.return_value=[dict(id='a'*64,name='shared-app',binds=[dict(source=m.current+'/app',destination='/data',eligible=True)])]
        def save(profile,m):return f.request('application-settings',dict(revision=m.b.s.digest(m.b.configuration()),containers=[dict(id='a'*64,destination='/data')],enabled=True),profile=profile)
        self.assertEqual(save('legacy',a)['status'],200)
        result=save(identifier,b)
        self.assertEqual(result['status'],200,result)
        self.assertEqual(a.b.configuration()['docker']['containers'][0]['container_id'],b.b.configuration()['docker']['containers'][0]['container_id'])


class ApplicationDiscovery(unittest.TestCase):
    def test_image_detection_is_advisory_without_probing_storage(self):
        b=load('web_broker')
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);source=root/'image-mount'/'app';source.mkdir(parents=True)
            c=b.s.default();c['disk'].update(uuid=UUID,mountpoint=str(root))
            c['images']=[dict(name='image',enabled=True,uuid='22222222-2222-4222-8222-222222222222',image=str(root/'data.img'),mountpoint=str(root/'image-mount'),fstab_options='loop,nofail,nodev,nosuid,noexec')]
            dev=f'{os.major(source.stat().st_dev)}:{os.minor(source.stat().st_dev)}'
            docker=Mock();docker.request.return_value=[dict(Id='a'*64)]
            docker.inspect.return_value=dict(id='a'*64,name='test-app',running=True,paused=False,restarting=False,dead=False,health=None,mounts=[dict(Type='bind',Source=str(source),Destination='/data',RW=True,Propagation='rprivate')])
            def rows(target):return b.w.parse_mounts(f'1 0 240:0 / / rw - ext4 /dev/system rw\n2 1 {dev} / {target} rw - ext4 /dev/synthetic rw\n')
            with patch.object(b,'docker_api'),patch.object(b.w.apps,'Docker',return_value=docker),patch.object(b.w,'snapshot',return_value=dict(healthy=True)),patch.object(b.w,'dependent_metadata'),patch.object(b.w,'read_rows',return_value=rows(root)) as mounts:
                self.assertTrue(b.container_rows(copy.deepcopy(c))[0]['eligible'])
                mounts.return_value=rows(root/'image-mount')
                self.assertTrue(b.container_rows(copy.deepcopy(c))[0]['eligible'])
                c['images'][0]['enabled']=False
                self.assertTrue(b.container_rows(copy.deepcopy(c))[0]['eligible'])
                mounts.assert_not_called()
            docker.change.assert_not_called();docker.access.assert_not_called()


if __name__=='__main__':unittest.main()
