# SPDX-License-Identifier: MIT
"""Reviewed manual unmount with real locks/receipts; Docker/storage are isolated."""
import copy
import fcntl
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from gui_fixture import load
from multidrive_fixture import FleetMachine
import test_ui25_boot as boot_fixture
import test_ui20_lifecycle as lifecycle

ID='a'*64
OTHER='b'*64
IMAGE='33333333-3333-4333-8333-333333333333'

class Unmount(unittest.TestCase):
    def setUp(self):
        self.f=FleetMachine();self.addCleanup(self.f.close);self.second=self.f.add()
        self.b=self.f.main.b;self.events=[];self.fail_stop=False;self.busy=False;self.hook=lambda:None
        # Match engine.main's private umask when our simulated worker opens it.
        (self.b.s.STATE_DIR/'recovery.lock').touch(mode=0o600)
        c=self.b.configuration();mount=c['disk']['mountpoint']
        c['images']=[dict(name='files',uuid=IMAGE,enabled=True,image=mount+'/volumes/files.img',mountpoint=mount+'/volumes/files',fstab_options='loop,nofail,nodev,nosuid')]
        c['docker'].update(enabled=True,containers=[dict(name='test-app',container_id=ID,source='',destination='',grace=10,images=[IMAGE])])
        self.b.cli.save(self.b.s.CONFIG,c)
        self.original=[m.config.read_bytes() for m in (self.f.main,self.f.second)]
        self.boot=load('boot_start');self.b.cli.save(self.boot.paths(self.b)[0],dict(version=1,containers=[dict(id=ID,name='test-app',enabled=True,drives=[dict(id='legacy',images=[IMAGE])])]))
        self.boot_config=self.boot.paths(self.b)[0].read_bytes()
        self.runtime={i:dict(id=i,name=n,running=True,paused=False,restarting=False,dead=False,started_at='original',health=None,mounts=[]) for i,n in [(ID,'test-app'),(OTHER,'unrelated')]}
        self.docker=SimpleNamespace(inspect=self.inspect,request=self.post)
        web=load('web_docker');self.f.main.patch(web,'client',lambda *_:(self.docker,'v1.47'))
        original=self.b.common.module
        self.f.main.patch(self.b.common,'module',lambda name,*args:web if name=='web_docker' else original(name,*args))
        self.rows=[dict(id='10',dev='240:1',root='/',target=mount,source='/dev/synthetic',fs='ext4'),dict(id='11',dev='7:1',root='/',target=mount+'/volumes/files',source='/dev/loop1',fs='ext4')]
        self.f.main.patch(self.b.w,'read_rows',lambda:copy.deepcopy(self.rows))
        self.f.main.patch(self.b.w,'mounted_checks',lambda rows,target,*_:next(v for v in rows if v['target']==target))
        self.f.main.patch(self.b.w.standby,'identity',lambda *_:{})
        self.f.main.patch(self.b.w.standby,'users',self.users)
        self.f.main.patch(self.b.w,'verify_dependent',lambda *_:self.events.append('verify:image'))
        self.f.main.patch(self.b.w,'command',self.command)
        self.f.main.patch(self.b.w,'assert_internal_state',lambda:None)
        self.f.main.patch(self.b.w.usb,'ensure_enabled',lambda *_:True)
        self.worker_payload=None;self.result=None
        parent=self
        class Worker:
            def __init__(self,argv,payload,*args,**kwargs):
                parent.worker_payload=payload
                assert tuple(payload['manual_lock_fds'])==kwargs['lock_fds']
                for fd in kwargs['lock_fds']:fcntl.fcntl(fd,fcntl.F_GETFD)
                previous=parent.b.w.WORKER_LOCK_FDS;parent.b.w.WORKER_LOCK_FDS=tuple(kwargs['lock_fds'])
                try:
                    message=parent.b.w.controls.perform(parent.b.w,'unmount')
                    parent.result=dict(ok=True,message=message)
                except parent.b.w.Unsafe as exc:parent.result=dict(ok=False,message=str(exc))
                finally:parent.b.w.WORKER_LOCK_FDS=previous
            def poll(self):return True
            def cancel(self):pass
            def close(self):pass
        self.f.main.patch(self.b.w,'Worker',Worker)
        self.f.main.patch(self.b.w,'worker_json',lambda _:self.result)

    def inspect(self,identity):return copy.deepcopy(self.runtime[identity])
    def post(self,method,path,**kwargs):
        self.assertEqual(method,'POST');identity=path.split('/')[2]
        if '/stop?' in path:
            self.events.append('stop:'+identity);self.hook()
            if self.fail_stop:raise self.b.w.apps.daemon_refusal(403,b'{"message":"permission denied secret"}')
            self.runtime[identity]['running']=False
        else:self.runtime[identity]['running']=True;self.events.append('start:'+identity)
    def users(self,*_):
        self.events.append('users');self.assertFalse(self.runtime[ID]['running'])
        self.assertTrue(self.runtime[OTHER]['running'])
        if self.busy:raise self.b.w.Unsafe('An unrelated process holds this disk open.')
    def command(self,argv,**kwargs):
        if argv[0]=='/usr/bin/umount':
            image=argv[-1].endswith('/files');self.events.append('unmount:image' if image else 'unmount:disk')
            self.rows[:]=[r for r in self.rows if r['target']!=argv[-1]]
        else:self.events.append('sync')
    def review(self):
        result=self.f.main.broker.handle(dict(action='unmount-plan',write=False,data=dict(uuid=self.f.main.uuid),drive='legacy',token=self.f.session['token'],csrf=self.f.session['csrf']))
        self.assertEqual(result['status'],200,result)
        return dict(action='unmount',uuid=self.f.main.uuid,token=result['data']['token'],confirm=True),result['data']
    def apply(self,data):return self.f.request('disk-operation',data)
    def receipt(self):return json.loads((self.b.s.STATE_DIR/'manual-unmount.json').read_text())
    def unchanged(self):
        self.assertEqual(self.original,[m.config.read_bytes() for m in (self.f.main,self.f.second)])
        self.assertEqual(self.boot_config,self.boot.paths(self.b)[0].read_bytes())
        self.assertTrue(self.runtime[OTHER]['running'])

    def test_order_and_exact_review_with_images_and_private_intent(self):
        data,review=self.review();self.assertEqual(review['apps'][0]['images'],['files']);self.assertEqual(self.events,[])
        result=self.apply(data);self.assertTrue(result['data']['ok'],result)
        self.assertEqual(self.events,['stop:'+ID,'users','verify:image','unmount:image','sync','unmount:disk'])
        self.assertFalse(self.f.main.active);self.assertFalse(self.runtime[ID]['running']);self.assertEqual(self.rows,[])
        self.assertEqual(self.receipt()['phase'],'complete');self.assertEqual(self.boot.state(self.b,ID)['phase'],'cancelled')
        self.assertTrue(self.b.w.manual_intent.stopped(self.b.w,ID));self.unchanged()
        self.assertEqual((self.b.s.STATE_DIR/'manual-unmount.json').stat().st_mode&0o777,0o600)
        self.assertEqual(self.apply(data)['status'],400)

    def test_stop_failure_aborts_before_monitoring_or_storage_and_identifies_blocker(self):
        data,_=self.review();self.fail_stop=True;result=self.apply(data)
        self.assertEqual(result['status'],400,result);self.assertIn('test-app',result['error']);self.assertIn('HTTP 403',result['error']);self.assertNotIn('secret',result['error'])
        self.assertEqual(self.events,['stop:'+ID]);self.assertTrue(self.f.main.active);self.assertEqual(len(self.rows),2)
        self.assertEqual(self.receipt()['phase'],'failed');self.unchanged()

    def test_already_stopped_apps_never_send_stop(self):
        self.runtime[ID]['running']=False;data,review=self.review();self.assertFalse(review['apps'][0]['running'])
        self.assertTrue(self.apply(data)['data']['ok']);self.assertFalse(any(e.startswith('stop:') for e in self.events));self.unchanged()

    def test_busy_unrelated_storage_is_not_bypassed_after_stop(self):
        self.busy=True;data,_=self.review();result=self.apply(data)
        self.assertFalse(result['data']['ok']);self.assertIn('unrelated process',result['data']['message']);self.assertEqual(len(self.rows),2)
        self.assertEqual(self.events,['stop:'+ID,'users']);self.unchanged()

    def test_stale_identity_execution_mount_and_selections_refuse_before_side_effects(self):
        for change in ('id','start','mount','selection','boot'):
            with self.subTest(change=change):
                data,_=self.review();saved=copy.deepcopy(self.runtime[ID]);rows=copy.deepcopy(self.rows);config=self.b.configuration();startup=self.boot.read(self.b)
                if change=='id':self.runtime[ID]['id']='c'*64
                elif change=='start':self.runtime[ID]['started_at']='new-execution'
                elif change=='mount':self.rows[0]['id']='20'
                elif change=='selection':self.b.cli.save(self.b.s.CONFIG,config|{'docker':config['docker']|{'enabled':False}})
                else:self.b.cli.save(self.boot.paths(self.b)[0],dict(version=1,containers=[]))
                result=self.apply(data);self.assertEqual(result['status'],400,result);self.assertEqual(self.events,[]);self.assertTrue(self.f.main.active)
                self.runtime[ID]=saved;self.rows=rows;self.b.cli.save(self.b.s.CONFIG,config);self.b.cli.save(self.boot.paths(self.b)[0],startup)

    def test_confirmation_required_and_session_bound(self):
        self.assertEqual(self.apply(dict(action='unmount',uuid=self.f.main.uuid))['status'],400)
        data,_=self.review();other=self.f.main.broker.sessions.login('admin','synthetic')
        result=self.f.main.broker.handle(dict(action='disk-operation',write=True,data=data,drive='legacy',token=other['token'],csrf=other['csrf']))
        self.assertEqual(result['status'],400);self.assertEqual(self.events,[])
        with self.assertRaisesRegex(ValueError,'review dependent apps'):self.b.disk_operation(dict(action='unmount',uuid=self.f.main.uuid))

    def test_real_concurrent_container_lock_refuses_without_queue(self):
        data,_=self.review();directory=self.b.s.STATE_DIR/'shared-locks';directory.mkdir(exist_ok=True,mode=0o700)
        with (directory/('docker-restart-'+ID+'.lock')).open('w') as lock:
            lock.fileno();__import__('os').fchmod(lock.fileno(),0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=self.apply(data)
        self.assertEqual(result['status'],400);self.assertIn('Nothing was queued',result['error']);self.assertEqual(self.events,[])

    def test_card_guard_all_paths_and_unrelated_action_during_stop(self):
        results=[]
        def probe():
            def run():
                b=self.b;guard=b.common.module('app_control');items=[(i,c) for i,c,e in self.f.main.broker.fleet.records() if not e]
                results.append(guard.restrictions(b,items)[ID])
                results.append(self.f.request('docker-container-action',dict(id=ID,name='test-app',action='start',confirm=True),profile=None)['status'])
                results.append(self.f.request('docker-container-action',dict(id=OTHER,name='unrelated',action='start',confirm=True),profile=None)['data']['ok'])
                with self.assertRaises((ValueError,BlockingIOError)):
                    with guard.drive_settings(b,b.configuration()):pass
            thread=threading.Thread(target=run);thread.start();thread.join(3);self.assertFalse(thread.is_alive())
        self.hook=probe;data,_=self.review();self.assertTrue(self.apply(data)['data']['ok'])
        self.assertEqual(results,['Safe unmount in progress. Controls are temporarily unavailable.',400,True]);self.unchanged()

    def test_shared_dependency_remains_held_until_explicit_manual_start(self):
        c=self.f.second.b.configuration();c['docker'].update(enabled=True,containers=[dict(name='test-app',container_id=ID,source='',destination='',grace=10,images=[])])
        self.b.cli.save(self.f.second.config,c);data,_=self.review();self.assertTrue(self.apply(data)['data']['ok'])
        self.assertTrue(self.b.w.manual_intent.stopped(self.b.w,ID))
        # Readbacks and a manual mount cannot clear the durable app intent.
        self.assertEqual(self.b.common.module('app_control').restrictions(self.b,[(i,c) for i,c,e in self.f.main.broker.fleet.records() if not e]),{})
        result=self.f.request('docker-container-action',dict(id=ID,name='test-app',action='start',confirm=True),profile=None)
        self.assertEqual(result['status'],400,result)
        self.assertTrue(self.b.w.manual_intent.stopped(self.b.w,ID))
        # Both configured drives and the selected image have now been remounted.
        verified=[]; original=self.b.common.module
        def engine(b,drive,config):
            return SimpleNamespace(STATE_DIR=self.b.s.STATE_DIR if drive=='legacy' else self.f.second.state,
                SETTINGS=config,settings=self.b.s,Unsafe=self.b.w.Unsafe,
                verify_main=lambda:verified.append(drive),verify_dependent=lambda image:verified.append(image['uuid']))
        with patch.object(self.boot,'engine',side_effect=engine), patch.object(self.b.common,'module',side_effect=lambda name,*args:self.boot if name=='boot_start' else original(name,*args)):
            result=self.f.request('docker-container-action',dict(id=ID,name='test-app',action='start',confirm=True),profile=None)
        self.assertEqual(result['status'],200,result)
        self.assertTrue(result['data']['ok'],result);self.assertFalse(self.b.w.manual_intent.stopped(self.b.w,ID))
        self.assertEqual(set(verified),{'legacy',self.second,IMAGE})

    def test_inactive_retained_selection_does_not_authorize_stopping(self):
        c=self.b.configuration();c['docker']['enabled']=False;self.b.cli.save(self.b.s.CONFIG,c)
        data,review=self.review();self.assertEqual(review['apps'],[])
        self.b.w.standby.users=lambda *_:(_ for _ in ()).throw(self.b.w.Unsafe('Running app still uses disk.'))
        result=self.apply(data);self.assertFalse(result['data']['ok']);self.assertTrue(self.runtime[ID]['running']);self.assertEqual(self.events,[])

    def test_changed_selection_during_docker_read_aborts_before_stop(self):
        data,_=self.review();original=self.inspect;calls=[]
        def inspect(identity):
            calls.append(identity)
            if len(calls)==2:
                c=self.b.configuration();c['docker']['containers'][0]['grace']=15;self.b.cli.save(self.b.s.CONFIG,c)
            return original(identity)
        self.docker.inspect=inspect
        result=self.apply(data)
        self.assertEqual(result['status'],400,result);self.assertEqual(self.events,[])

    def test_ordinary_folders_need_no_images(self):
        c=self.b.configuration();c['images']=[];c['docker']['containers'][0]['images']=[];self.b.cli.save(self.b.s.CONFIG,c)
        self.rows=self.rows[:1];boot=self.boot.read(self.b);boot['containers'][0]['drives'][0]['images']=[];self.b.cli.save(self.boot.paths(self.b)[0],boot)
        data,review=self.review();self.assertEqual(review['apps'][0]['images'],[])
        self.assertTrue(self.apply(data)['data']['ok']);self.assertEqual(self.events,['stop:'+ID,'users','sync','unmount:disk'])

    def test_partial_stop_failure_reports_completed_stops(self):
        c=self.b.configuration();c['docker']['containers'].append(dict(name='unrelated',container_id=OTHER,source='',destination='',grace=10,images=[]));self.b.cli.save(self.b.s.CONFIG,c)
        original=self.post
        def post(method,path,**kwargs):
            if OTHER in path:raise self.b.w.apps.daemon_refusal(403,b'{}')
            return original(method,path,**kwargs)
        self.docker.request=post;data,_=self.review();result=self.apply(data)
        self.assertEqual(result['status'],400,result);self.assertIn('already confirmed stopped: test-app',result['error']);self.assertIn('Cannot confirm unrelated',result['error'])
        self.assertFalse(self.runtime[ID]['running']);self.assertTrue(self.runtime[OTHER]['running']);self.assertEqual(len(self.rows),2);self.assertTrue(self.f.main.active)

    def test_lost_stop_acknowledgement_is_verified_without_repeating(self):
        original=self.post
        def post(*args,**kwargs):
            original(*args,**kwargs)
            raise TimeoutError('private transport body')
        self.docker.request=post;data,_=self.review();result=self.apply(data)
        self.assertTrue(result['data']['ok'],result);self.assertEqual(self.events.count('stop:'+ID),1)
        self.assertNotIn('private transport',result['data']['message'])

    def test_inherited_worker_locks_survive_parent_close(self):
        import sys
        root=self.b.s.STATE_DIR
        worker=None
        try:
            with self.b.cli.drives.lock(root,'inherited-test.lock') as fd:
                worker=self.b.w.__dict__.get('Worker')
                # Use the production worker, not this fixture's storage adapter.
                real=load('engine').Worker
                worker=real([sys.executable,'-I','-c','import time; time.sleep(5)'],{},10,directory=root,lock_fds=(fd,))
            with (root/'inherited-test.lock').open('rb') as probe:
                with self.assertRaises(BlockingIOError):fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)
        finally:
            if hasattr(worker,'proc'):worker.cancel();worker.proc.wait(timeout=3);worker.close()

    def test_orphaned_receipt_releases_controls_but_keeps_automatic_start_hold(self):
        self.b.cli.save(self.b.s.STATE_DIR/'manual-unmount.json',dict(boot=self.b.w.boot_id(),phase='active',control_ids=[ID],held_ids=[ID]))
        guard=self.b.common.module('app_control');items=[('legacy',self.b.configuration())]
        self.assertEqual(guard.restrictions(self.b,items),{})
        self.assertTrue(self.b.w.manual_intent.stopped(self.b.w,ID))


class BootIntent(unittest.TestCase):
    setUp=boot_fixture.BootStartup.setUp
    request=boot_fixture.BootStartup.request
    verify=boot_fixture.BootStartup.verify
    mount=boot_fixture.BootStartup.mount
    run_boot=boot_fixture.BootStartup.run_boot
    receipt=boot_fixture.BootStartup.receipt
    def test_pending_boot_including_new_app_cannot_remount_after_manual_unmount(self):
        self.b.cli.save(self.b.s.STATE_DIR/'manual-unmount.json',dict(boot=self.boot,phase='complete',control_ids=[],held_ids=[]))
        self.run_boot();self.run_boot();self.assertEqual(self.events,[]);self.assertEqual(self.receipt()['phase'],'cancelled')
        self.boot='next-boot';self.run_boot();self.assertEqual(self.events,['mount','start'])

class RecoveryIntent(unittest.TestCase):
    def test_deliberate_stop_survives_shared_recovery_and_manual_remount(self):
        m=lifecycle.Machine(self);m.establish();m.disconnect(m.now+15);m.returned(m.now+60)
        self.assertTrue(m.recover()['main'])
        m.patch(m.w.drives,'files',lambda _:[('legacy',m.w.CONFIG)])
        m.w.atomic_write(m.directory/'manual-unmount.json',json.dumps(dict(boot=m.w.boot_id(),phase='complete',control_ids=[ID],held_ids=[ID])))
        result=m.finish();self.assertTrue(result['all_verified'],result)
        self.assertNotIn('docker:start',m.events);self.assertFalse(m.docker.containers['selected_app']['running'])
        self.assertEqual(result['containers']['selected_app']['status'],'preserved_stopped')

    def test_manual_hold_preserves_an_existing_uncertain_start_budget(self):
        m=lifecycle.Machine(self);m.establish();m.disconnect(m.now+15);m.returned(m.now+60);self.assertTrue(m.recover()['main'])
        m.patch(m.w.drives,'files',lambda _:[('legacy',m.w.CONFIG)])
        m.w.atomic_write(m.directory/'manual-unmount.json',json.dumps(dict(boot=m.w.boot_id(),phase='complete',control_ids=[ID],held_ids=[ID])))
        entry=dict(status='intent',action_count=1,container_id=ID,before=dict(id=ID,known=True,running=True),before_started_at='initial')
        ledger=dict(version=1,incident=m.monitor.state['incident']['id'],boot=m.w.boot_id(),complete=False,interrupted=False,containers={'selected_app':entry})
        m.w.apps.save(m.w,ledger);result=m.finish()
        self.assertEqual(result['containers']['selected_app']['action_count'],1)
        self.assertNotIn('docker:start',m.events);self.assertFalse(result['all_verified'])

    def test_running_app_is_not_falsely_reported_as_preserved_stopped(self):
        m=lifecycle.Machine(self);m.establish();m.disconnect(m.now+15);m.returned(m.now+60);self.assertTrue(m.recover()['main'])
        m.patch(m.w.drives,'files',lambda _:[('legacy',m.w.CONFIG)])
        m.w.atomic_write(m.directory/'manual-unmount.json',json.dumps(dict(boot=m.w.boot_id(),phase='complete',control_ids=[ID],held_ids=[ID])))
        m.docker.containers['selected_app']['running']=True
        result=m.finish();self.assertNotEqual(result['containers']['selected_app']['status'],'preserved_stopped')
        self.assertNotIn('docker:start',m.events);self.assertFalse(result['all_verified'])


import test_ui28_apps as editor

class StaleSettings(unittest.TestCase):
    setUp=editor.AppSettings.setUp
    current=editor.AppSettings.current
    desired=editor.AppSettings.desired
    review=editor.AppSettings.review
    commit=editor.AppSettings.commit
    def test_stale_settings_and_policy_confirmations_refused_during_manual_unmount(self):
        desired=self.desired();desired['boot']['drives'][0]['images']=[]
        plan=self.review(desired)
        policy=self.m.plan(self.fleet,dict(id=editor.IDENTITY,name='folder-app'),self.session)
        self.b.cli.save(self.b.s.STATE_DIR/'manual-unmount.json',dict(boot=self.b.w.boot_id(),phase='active',control_ids=[editor.IDENTITY],held_ids=[editor.IDENTITY]))
        original=self.current()
        with self.b.cli.drives.lock(self.b.s.STATE_DIR,'manual-unmount.lock'):
            with self.assertRaisesRegex(ValueError,'Safe unmount in progress'):self.commit(plan)
            with self.assertRaisesRegex(ValueError,'Safe unmount in progress'):
                self.m.apply(self.fleet,dict(id=editor.IDENTITY,name='folder-app',token=policy['token'],confirm=True),self.session)
            with self.assertRaisesRegex(ValueError,'Safe unmount in progress'):
                self.boot.update(self.fleet,dict(revision=self.boot.public(self.b)['revision'],container=dict(id=editor.IDENTITY,name='folder-app',enabled=False,drives=[])))
            self.assertTrue(self.web.overview(self.fleet)['inventory_ok'])
        self.assertEqual(original,self.current());self.assertEqual(self.docker.updates,[])


if __name__=='__main__':unittest.main()
