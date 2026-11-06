# SPDX-License-Identifier: MIT
"""Boot coordinator simulations: real receipts/locks, simulated Docker/storage."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gui_fixture import load
from multidrive_fixture import FleetMachine

IDENTITY = 'a' * 64


class BootStartup(unittest.TestCase):
    def setUp(self):
        self.f = FleetMachine(); self.addCleanup(self.f.close)
        self.second = self.f.add()
        self.b = self.f.main.b
        self.m = load('boot_start')
        self.events = []
        self.boot = 'test-boot'
        self.f.main.patch(self.b.w, 'boot_id', lambda:self.boot)
        self.records = [(i,c) for i,c,error in self.f.main.broker.fleet.records() if not error]
        self.item = dict(id=IDENTITY,name='test-app',enabled=True,drives=[dict(id='legacy',images=[])])
        self.b.cli.save(self.m.paths(self.b)[0],dict(version=1,containers=[self.item]))
        self.original = [machine.config.read_bytes() for machine in (self.f.main,self.f.second)]
        self.current = dict(id=IDENTITY,name='test-app',running=False,paused=False,dead=False,restarting=False,healthcheck=False,health=None)
        self.docker = SimpleNamespace(inspect=lambda _:copy.deepcopy(self.current),request=self.request)
        self.mounted = False
        config=dict(self.records)['legacy']
        self.w=SimpleNamespace(STATE_DIR=self.b.s.STATE_DIR,DISK_UUID=config['disk']['uuid'],
            Unsafe=self.b.w.Unsafe,SETTINGS=config,CONFIG_DIGEST=self.b.s.digest(config),settings=self.b.s,
            runtime_configuration=lambda:copy.deepcopy(config),verify_main=self.verify,mount_main=self.mount)
        self.w.SETTINGS['notifications']['enabled']=False
        self.w.CONFIG_DIGEST=self.b.s.digest(config)
        self.engines=Mock(return_value=self.w)
        self.f.main.patch(self.m,'engine',self.engines)

    def request(self,method,path,**kwargs):
        if method=='GET':return {'HostConfig':{'RestartPolicy':{'Name':'no'}}}
        self.assertTrue(self.mounted)
        self.events.append('start');self.current['running']=True

    def verify(self):
        if not self.mounted:raise self.w.Unsafe('Storage absent')

    def mount(self,note):
        note('main','intent');self.events.append('mount');self.mounted=True

    def run_boot(self):self.m.run_container(self.b,self.item,self.records,self.docker)

    def receipt(self):return self.m.state(self.b,IDENTITY)

    def test_mount_before_start_once_per_boot_without_recovery_changes(self):
        self.run_boot();self.run_boot()
        self.assertEqual(self.events,['mount','start'])
        self.assertEqual(self.receipt()['phase'],'verified')
        self.assertEqual(self.original,[machine.config.read_bytes() for machine in (self.f.main,self.f.second)])
        self.assertEqual([c.args[1] for c in self.engines.call_args_list],['legacy','legacy'])

    def test_later_manual_stop_is_respected(self):
        self.run_boot();self.current['running']=False;self.run_boot()
        self.assertEqual(self.events.count('start'),1)

    def test_pending_manual_stop_cancels_current_boot(self):
        self.m.cancel(self.b,IDENTITY);self.run_boot()
        self.assertEqual(self.events,[]);self.assertEqual(self.receipt()['phase'],'cancelled')

    def test_next_boot_is_a_new_start(self):
        self.run_boot();self.current['running']=False;self.boot='next-boot';self.run_boot()
        self.assertEqual(self.events.count('start'),2)

    def test_missing_disk_waits_without_start(self):
        self.w.mount_main=lambda note:(_ for _ in ()).throw(FileNotFoundError())
        self.run_boot();self.assertEqual(self.events,[]);self.assertEqual(self.receipt()['phase'],'waiting')

    def test_uncertain_mount_is_reconciled_not_replayed(self):
        def failed(note):note('main','intent');raise TimeoutError()
        self.w.mount_main=failed;self.run_boot();self.run_boot()
        self.assertEqual(self.events,[]);self.assertEqual(self.receipt()['phase'],'failed')

    def test_mount_completed_before_crash_is_read_back(self):
        value=self.receipt();value['mounts'][self.w.DISK_UUID]='intent';self.m.save_state(self.b,IDENTITY,value)
        self.mounted=True;self.run_boot();self.assertEqual(self.events,['start'])

    def test_uncertain_start_is_never_repeated_when_stopped(self):
        self.mounted=True;value=self.receipt();value['phase']='intent';self.m.save_state(self.b,IDENTITY,value)
        self.run_boot();self.assertEqual(self.events,[]);self.assertEqual(self.receipt()['phase'],'failed')

    def test_uncertain_start_running_is_verified_without_post(self):
        self.mounted=True;self.current['running']=True
        value=self.receipt();value['phase']='intent';self.m.save_state(self.b,IDENTITY,value)
        self.run_boot();self.assertEqual(self.events,[]);self.assertEqual(self.receipt()['phase'],'verified')

    def test_docker_refusal_retains_safe_reason_and_is_not_retried(self):
        apps=load('apps');original=self.docker.request
        def request(method,path,**kwargs):
            if method=='GET':return original(method,path,**kwargs)
            self.events.append('refused')
            raise apps.daemon_refusal(500,b'{"message":"cannot assign requested address"}')
        self.docker.request=request
        self.run_boot();self.run_boot()
        self.assertEqual(self.events,['mount','refused'])
        self.assertEqual(self.receipt()['phase'],'failed')
        self.assertIn('host IP address',self.receipt()['message'])

    def test_uncertain_start_error_survives_reconciliation(self):
        original=self.docker.request
        def request(method,path,**kwargs):
            if method=='GET':return original(method,path,**kwargs)
            raise TimeoutError()
        self.docker.request=request
        self.run_boot();self.run_boot()
        self.assertEqual(self.receipt()['phase'],'failed')
        self.assertIn('TimeoutError',self.receipt()['message'])

    def test_disabled_or_changed_selection_does_not_start(self):
        self.b.cli.save(self.m.paths(self.b)[0],dict(version=1,containers=[self.item|{'enabled':False}]))
        self.run_boot();self.assertEqual(self.events,[])

    def test_already_running_with_missing_storage_is_not_mounted_underneath(self):
        self.current['running']=True;self.run_boot();self.assertEqual(self.events,[])

    def test_competing_container_operation_blocks_boot(self):
        root=self.b.cli.drives.roots(self.b.s)[1]
        # A separately opened flock models a different process (same-thread lock helpers reenter).
        import fcntl
        directory=root/'shared-locks';directory.mkdir(exist_ok=True,mode=0o700)
        with (directory/('docker-restart-'+IDENTITY+'.lock')).open('w') as held:
            held_path=Path(held.name);held_path.chmod(0o600);fcntl.flock(held,fcntl.LOCK_EX)
            with self.assertRaises(BlockingIOError):self.run_boot()
        self.assertEqual(self.events,[])

    def test_no_implicit_images_from_recovery_preferences(self):
        self.w.settings=SimpleNamespace(**vars(self.b.s))
        self.w.settings.storage_images=lambda *args:[dict(uuid='11111111-1111-4111-8111-111111111111',enabled=True)]
        self.w.verify_dependent=Mock(side_effect=AssertionError('Unselected image must not gate boot'))
        self.run_boot();self.w.verify_dependent.assert_not_called()
        self.assertEqual(self.events,['mount','start'])

    def test_explicit_image_mount_precedes_container_start(self):
        image=dict(uuid='33333333-3333-4333-8333-333333333333',name='data',enabled=False,
                   mountpoint='/mnt/drive-a/data',image='/mnt/drive-a/data.img',fstab_options='loop,noauto,nodev,nosuid')
        self.w.SETTINGS['images']=[image];self.w.CONFIG_DIGEST=self.b.s.digest(self.w.SETTINGS)
        self.item['drives'][0]['images']=[image['uuid']]
        self.b.cli.save(self.m.paths(self.b)[0],dict(version=1,containers=[self.item]))
        ready=[False]
        def verify(_):
            if not ready[0]:raise self.w.Unsafe('Image absent')
        def mount(item,request,note):
            self.assertTrue(self.mounted);note('dependent','intent');self.events.append('image');ready[0]=True
        self.w.verify_dependent=verify;self.w.recover_image=mount
        self.run_boot();self.assertEqual(self.events,['mount','image','start'])

    def test_selected_second_disk_is_required_even_with_monitoring_off(self):
        self.item['drives'].append(dict(id=self.second,images=[]))
        self.b.cli.save(self.m.paths(self.b)[0],dict(version=1,containers=[self.item]))
        second=SimpleNamespace(**vars(self.w));second.STATE_DIR=self.f.second.b.s.STATE_DIR
        second.DISK_UUID=dict(self.records)[self.second]['disk']['uuid']
        second.verify_main=lambda:(_ for _ in ()).throw(FileNotFoundError())
        second.mount_main=lambda _:(_ for _ in ()).throw(FileNotFoundError())
        self.engines.side_effect=lambda b,identifier,c:self.w if identifier=='legacy' else second
        self.f.main.active=False;self.f.second.active=False
        self.run_boot();self.assertNotIn('start',self.events)

    def test_boot_with_monitoring_off_does_not_toggle_services(self):
        self.f.main.active=False;self.f.second.active=False
        self.f.main.calls.clear();self.f.second.calls.clear()
        self.run_boot();self.assertEqual(self.events,['mount','start'])
        self.assertFalse(self.f.main.active);self.assertFalse(self.f.second.active)
        self.assertEqual(self.f.main.calls,[]);self.assertEqual(self.f.second.calls,[])

    def test_boot_api_saves_independently_and_requires_authentication(self):
        docker_module=SimpleNamespace(client=lambda *_:(self.docker,'v1.47'))
        original=self.b.common.module
        with patch.object(self.b.common,'module',side_effect=lambda name,*args:docker_module if name=='web_docker' else original(name,*args)):
            data=dict(revision=self.m.public(self.b)['revision'],container=self.item)
            result=self.f.request('docker-boot-settings',data,profile=None)
            self.assertEqual(result['status'],200,result)
            self.assertEqual(result['data']['settings'],[self.item])
            self.assertEqual(self.original,[m.config.read_bytes() for m in (self.f.main,self.f.second)])
            result=self.f.main.broker.handle(dict(action='docker-boot-settings',write=True,data=data))
            self.assertEqual(result['status'],401)


if __name__=='__main__':unittest.main()
