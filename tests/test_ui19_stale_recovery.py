# SPDX-License-Identifier: MIT
"""Detached shutdown recovery with synthetic mount tables; no real storage I/O."""
import copy
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location('ui19_stale_' + name, ROOT/'src/usb_storage_watch'/(name+'.py'))
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
w = load('engine'); controls = load('controls')
spec = importlib.util.spec_from_file_location('ui19_stale_fixture', Path(__file__).with_name('fixtures.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture);fixture.configure(w)
BASE='1 0 240:2 / / rw - ext4 /dev/root rw\n'
HEALTHY='2 1 240:17 / /mnt/storage rw,nosuid,nodev - ext4 /dev/sdc1 rw\n'
SHUTDOWN=HEALTHY.replace('/dev/sdc1 rw','/dev/sdc1 rw,shutdown')
OLD='240:17';NEW='240:33';BOOT='test-boot'

class DetachedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.folder=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.rows=w.parse_mounts(BASE+SHUTDOWN)
        self.prior_connection=dict(boot=BOOT,diskseq=10)
        self.connection=dict(boot=BOOT,diskseq=11)
        self.proof=dict(version=1,uuid=w.DISK_UUID,target=w.MOUNT,boot=BOOT,
                        connection=self.prior_connection,mount=w.mount_record(w.parse_mounts(BASE+HEALTHY)[-1]))
        self.request=dict(incident='synthetic-incident',number=1,allow_mount=True,blocked=[],check_only=False,
                          known_storage=self.proof)
        self.calls=[];self.notes=[]
        def patch(name,**kwargs):return self.stack.enter_context(mock.patch.object(w,name,**kwargs))
        patch('STATE_DIR',new=self.folder);patch('MANUAL_MOUNT',new=False)
        patch('boot_id',return_value=BOOT);patch('read_rows',side_effect=lambda:copy.deepcopy(self.rows))
        patch('device_number',return_value=NEW)
        self.connection_mock=patch('connection_identity',side_effect=lambda dev:dict(self.connection))
        self.block=patch('block_checks',return_value='synthetic-returned')
        self.mount_available=patch('mount_available')
        self.fstab=patch('fstab_check');self.directory=patch('protected_mount_directory')
        self.disk=patch('disk_proof',return_value=types.SimpleNamespace(st_rdev=os.makedev(240,33)))
        self.config=patch('config_load',return_value={'automatic_recovery':True})
        self.command=patch('command',side_effect=self.execute)
        original_lstat=Path.lstat
        def lstat(path,*args,**kwargs):
            if str(path)=='/sys/dev/block/'+OLD:raise FileNotFoundError(path)
            return original_lstat(path,*args,**kwargs)
        self.stack.enter_context(mock.patch.object(Path,'lstat',lstat))
        original_resolve=Path.resolve
        def resolve(path,*args,**kwargs):
            if str(path)=='/dev/disk/by-uuid/'+w.DISK_UUID:return Path('/dev/synthetic-returned')
            return original_resolve(path,*args,**kwargs)
        self.stack.enter_context(mock.patch.object(Path,'resolve',resolve))

    def execute(self,argv,**kwargs):
        self.calls.append(argv)
        self.assertEqual(argv,['/usr/bin/umount','--internal-only','--no-canonicalize','--',w.MOUNT])
        marker=json.loads((self.folder/'stale-mount-cleanup.json').read_text())
        self.assertEqual(marker['phase'],'intent')
        receipt=self.folder/'receipt.json'
        self.assertTrue(any(note[1]=='stale-unmount-intent' for note in self.notes)
                        or (receipt.exists() and any(item['stage']=='stale-unmount-intent'
                            for item in json.loads(receipt.read_text())['result']['actions'])))
        self.rows=w.parse_mounts(BASE)
        return ''

    def note(self,*args):self.notes.append(args)
    def candidate(self):
        row=w.detached_shutdown_mount(self.rows)
        return dict(detached_shutdown_mount=dict(boot=BOOT,mount=w.mount_record(row))) if row else {}

    def test_exact_detached_mount_is_normally_unmounted_once_with_durable_intent(self):
        w.cleanup_detached_main(self.request,self.note)
        self.assertEqual(len(self.calls),1)
        self.assertEqual([row[1] for row in self.notes],['stale-unmount-intent','stale-unmount-returned'])
        self.assertEqual(json.loads((self.folder/'stale-mount-cleanup.json').read_text())['phase'],'returned')
        self.disk.assert_called_once_with(Path('/dev/synthetic-returned'),w.DISK_UUID,unmounted=True)
        self.directory.assert_called_once()
        for call in self.mount_available.call_args_list:
            self.assertFalse(any(row['dev']==OLD for row in call.args[0]))

    def test_legacy_crossboot_wrong_id_or_wrong_uuid_proof_cannot_authorize_cleanup(self):
        variants=[None,{},dict(self.proof,version=0),dict(self.proof,boot='previous-boot'),dict(self.proof,uuid='bad')]
        changed=copy.deepcopy(self.proof);changed['mount']['id']='999';variants.append(changed)
        for proof in variants:
            with self.subTest(proof=proof),self.assertRaises(w.Unsafe):
                w.cleanup_detached_main(dict(self.request,known_storage=proof),self.note)
        self.command.assert_not_called()

    def test_live_old_device_or_unreadable_sysfs_is_not_detached(self):
        for side_effect in (lambda path:types.SimpleNamespace(),lambda path:(_ for _ in ()).throw(PermissionError())):
            with mock.patch.object(Path,'lstat',side_effect),self.assertRaises(w.Unsafe):
                w.cleanup_detached_main(self.request,self.note)
        self.command.assert_not_called()

    def test_wrong_mount_type_root_children_stack_hidden_and_flags_refuse(self):
        variants=[
            SHUTDOWN.replace(' - ext4 ',' - xfs '),SHUTDOWN.replace('240:17 / ','240:17 /subdir '),
            HEALTHY,SHUTDOWN.replace('rw,shutdown','ro,shutdown'),SHUTDOWN.replace('rw,shutdown','rw,shutdown,emergency_ro'),
            SHUTDOWN+'3 2 7:8 / /mnt/storage/image rw - ext4 /dev/loop8 rw\n',
            SHUTDOWN+'3 2 240:49 / /mnt/storage rw - ext4 /dev/other rw\n',
            SHUTDOWN+'3 1 240:49 / /mnt rw - ext4 /dev/other rw\n',
            SHUTDOWN+'3 1 240:17 / /elsewhere rw - ext4 /dev/sdc1 rw,shutdown\n',
        ]
        for variant in variants:
            self.rows=w.parse_mounts(BASE+variant)
            with self.subTest(variant=variant),self.assertRaises(w.Unsafe):
                w.cleanup_detached_main(self.request,self.note)
        self.command.assert_not_called()

    def test_same_or_unknown_returned_attachment_refuses(self):
        for connection in (None,self.prior_connection,dict(boot='other-boot',diskseq=11)):
            self.connection_mock.side_effect=None;self.connection_mock.return_value=connection
            with self.subTest(connection=connection),self.assertRaises(w.Unsafe):
                w.cleanup_detached_main(self.request,self.note)
        self.command.assert_not_called()

    def test_returned_device_checks_fail_before_unmount(self):
        for target in (self.block,self.disk,self.fstab,self.mount_available,self.directory):
            target.side_effect=w.Unsafe('Synthetic returned identity/access refusal')
            with self.subTest(target=target),self.assertRaises(w.Unsafe):
                w.cleanup_detached_main(self.request,self.note)
            target.side_effect=None
        self.command.assert_not_called()
        self.assertFalse((self.folder/'stale-mount-cleanup.json').exists())

    def test_changed_returned_device_number_refuses(self):
        self.disk.return_value=types.SimpleNamespace(st_rdev=os.makedev(240,49))
        with self.assertRaises(w.Unsafe):w.cleanup_detached_main(self.request,self.note)
        self.command.assert_not_called()

    def test_readonly_check_only_disabled_and_preblocked_requests_do_not_unmount(self):
        for values in ({'check_only':True},{'allow_mount':False},{'blocked':['main']}):
            with self.subTest(values=values),self.assertRaises(w.Unsafe):
                w.cleanup_detached_main(self.request|values,self.note)
        self.config.return_value={'automatic_recovery':False}
        with self.assertRaises(w.Unsafe):w.cleanup_detached_main(self.request,self.note)
        self.command.assert_not_called()

    def test_configuration_or_mount_race_after_intent_refuses_without_command(self):
        def changed(*args):
            self.note(*args)
            self.rows[-1]['id']='999'
        with self.assertRaises(w.Unsafe):w.cleanup_detached_main(self.request,changed)
        self.command.assert_not_called()
        self.rows[-1]['id']='2'
        with self.assertRaisesRegex(w.Unsafe,'already attempted'):
            w.cleanup_detached_main(self.request,self.note)
        self.command.assert_not_called()

    def test_disable_recovery_after_intent_refuses(self):
        def disabled(*args):
            self.note(*args);self.config.return_value={'automatic_recovery':False}
        with self.assertRaises(w.Unsafe):w.cleanup_detached_main(self.request,disabled)
        self.command.assert_not_called()

    def test_unmount_failure_or_timeout_is_not_replayed(self):
        for message in ('umount exited 32: target is busy','umount exceeded its 15s deadline; result uncertain.'):
            marker=self.folder/'stale-mount-cleanup.json'
            if marker.exists():marker.unlink()
            self.command.reset_mock();self.command.side_effect=w.Unsafe(message)
            with self.subTest(message=message),self.assertRaises(w.Unsafe):
                w.cleanup_detached_main(self.request,self.note)
            with self.assertRaisesRegex(w.Unsafe,'already attempted'):
                w.cleanup_detached_main(self.request,self.note)
            self.assertEqual(self.command.call_count,1)

    def test_malformed_existing_cleanup_marker_is_never_overwritten(self):
        complete=dict(version=1,proof=self.proof,incident='previous',phase='intent',time='recorded')
        records=[{'version':1},dict(complete,proof={}),dict(complete,phase='invalid'),
                 dict(complete,incident=None),dict(complete,time=3),dict(complete,phase='returned')]
        for record in records:
            path=self.folder/'stale-mount-cleanup.json';path.write_text(json.dumps(record))
            with self.subTest(record=record),self.assertRaisesRegex(w.Unsafe,'record is invalid'):
                w.cleanup_detached_main(self.request,self.note)
            self.assertEqual(json.loads(path.read_text()),record)
        self.command.assert_not_called()

    def test_success_receipt_with_retained_target_does_not_allow_remount_or_repeat(self):
        self.command.side_effect=lambda *args,**kwargs:''
        with self.assertRaisesRegex(w.Unsafe,'still occupies'):
            w.cleanup_detached_main(self.request,self.note)
        with self.assertRaisesRegex(w.Unsafe,'already attempted'):
            w.cleanup_detached_main(self.request,self.note)
        self.assertEqual(self.command.call_count,1)

    def test_manual_mount_captures_original_storage_proof_separate_from_usb_binding(self):
        ctx=types.SimpleNamespace(STATE_DIR=self.folder,DISK_UUID=w.DISK_UUID,CONFIG_DIGEST='test',Unsafe=w.Unsafe,
            load_state=lambda path:dict(last_healthy=dict(main_mount_proof=self.proof)),
            device_number=lambda path:NEW,usb_context=lambda:None,
            usb=types.SimpleNamespace(bind_current=lambda context,dev:dict(sources=['returned-device'])))
        result=controls.request(ctx)
        self.assertEqual(result['known_storage'],self.proof);self.assertEqual(result['known_devs'],[NEW])

    @mock.patch.object(w, 'MANUAL_MOUNT', True)
    def test_manual_cleanup_continues_existing_mount_image_pipeline(self):
        state={'mounted':False}
        initial=dict(self.candidate(),healthy=False,detected=True,mounts=[],unsafe=True,detail='Detached shutdown')
        def snapshot():
            return dict(initial,healthy=state['mounted'],dependent=state['mounted'])
        def mounted(note):
            self.assertEqual(len(self.calls),1);self.assertEqual(self.rows,w.parse_mounts(BASE))
            state['mounted']=True;note('main','returned','existing guarded mount path')
        with mock.patch.object(w,'snapshot',side_effect=snapshot),mock.patch.object(w,'mount_main',side_effect=mounted) as mount, \
             mock.patch.object(w,'verify_main'),mock.patch.object(w,'verify_access'),mock.patch.object(w,'recover_image') as images, \
             mock.patch.object(Path,'exists',return_value=True),mock.patch.object(w.usb,'cycle') as reset:
            result=w.recovery_work(self.request,self.folder/'receipt.json')
        self.assertTrue(result['main']);self.assertTrue(result['dependent']);mount.assert_called_once()
        self.assertEqual(images.call_count,len(w.DEPENDENCIES));reset.assert_not_called()

    @mock.patch.object(w, 'MANUAL_MOUNT', True)
    def test_manual_cleanup_failure_never_calls_mount_or_images(self):
        current=dict(self.candidate(),healthy=False,detected=True,mounts=[],unsafe=True,detail='Detached shutdown')
        self.command.side_effect=w.Unsafe('target is busy')
        with mock.patch.object(w,'snapshot',return_value=current),mock.patch.object(w,'mount_main') as mount, \
             mock.patch.object(w,'recover_image') as images,mock.patch.object(w.usb,'cycle') as reset:
            result=w.recovery_work(self.request,self.folder/'receipt.json')
        self.assertFalse(result['main']);mount.assert_not_called();images.assert_not_called();reset.assert_not_called()

    def test_shutdown_and_emergency_readonly_are_never_healthy_even_with_rw(self):
        for option in ('shutdown','emergency_ro'):
            rows=w.parse_mounts(BASE+HEALTHY.replace('/dev/sdc1 rw','/dev/sdc1 rw,'+option))
            with self.subTest(option=option),self.assertRaisesRegex(w.Unsafe,'shut down|emergency'):
                w.mounted_checks(rows,w.MOUNT,OLD,w.DISK_UUID)
            self.assertEqual(w.mount_observation(rows,w.MOUNT,OLD)['mount_state'],'conflict')
        self.block.assert_not_called()

    def test_shutdown_observe_is_unhealthy_and_healthy_snapshot_captures_exact_proof(self):
        mountinfo=self.folder/'mountinfo';mountinfo.write_text(BASE+SHUTDOWN)
        sysroot=self.folder/'sys';(sysroot/OLD).mkdir(parents=True)
        original_stat=os.stat
        def info(path,*args,**kwargs):
            if str(path)=='/synthetic-uuid/'+w.DISK_UUID:
                return types.SimpleNamespace(st_mode=stat.S_IFBLK,st_rdev=os.makedev(240,17))
            return original_stat(path,*args,**kwargs)
        with mock.patch.object(os,'stat',info):
            okay,detail=w.observe(str(mountinfo),'/synthetic-uuid',str(sysroot))
        self.assertFalse(okay);self.assertIn('shut down',detail)
        self.rows=w.parse_mounts(BASE+HEALTHY)
        original_read=Path.read_text
        def read(path,*args,**kwargs):
            if str(path).endswith('/errors_count'):return '0'
            return original_read(path,*args,**kwargs)
        with mock.patch.object(w,'device_number',return_value=OLD), \
             mock.patch.object(w,'connection_identity',return_value=self.prior_connection), \
             mock.patch.object(w.usb,'bind_current',side_effect=w.Unsafe('Reset qualification unavailable')), \
             mock.patch.object(w.drives,'enroll'),mock.patch.object(w,'dependent_status',return_value=[]), \
             mock.patch.object(Path,'read_text',read):
            result=w.snapshot()
        self.assertTrue(result['healthy']);self.assertEqual(result['main_mount_proof'],self.proof)

    @mock.patch.object(w, 'MANUAL_MOUNT', True)
    def test_manual_absent_returned_drive_releases_retained_mount_then_waits(self):
        current=dict(self.candidate(),healthy=False,detected=False,mounts=[],unsafe=False,detail='Absent')
        original_exists = Path.exists
        def exists(path):
            return False if str(path) == '/dev/disk/by-uuid/' + w.DISK_UUID else original_exists(path)
        with mock.patch.object(w,'snapshot',return_value=current),mock.patch.object(Path,'exists',exists), \
             mock.patch.object(w.usb,'cycle') as reset,mock.patch.object(w,'mount_main') as mount:
            result=w.recovery_work(self.request,self.folder/'receipt.json')
        self.assertFalse(result['main']);self.assertTrue(result['waiting_device'])
        self.assertIn('Waiting',result['reason']);self.assertEqual(result['blocked'],[])
        self.command.assert_called_once();reset.assert_not_called();mount.assert_not_called()
        self.assertTrue(result['cleanup_complete'])

    def test_new_exact_stale_incident_does_not_latch_but_prior_hard_block_stays(self):
        with mock.patch.object(w,'log'):
            monitor=w.Monitor(self.folder/'state.json',now=0,boot=BOOT,application_tracking=False)
            healthy=dict(healthy=True,detected=True,dependent=True,unsafe=False,detail='Healthy',mounts=[],
                         main_mount_proof=self.proof,connection=self.prior_connection)
            stale=dict(self.candidate(),healthy=False,detected=True,dependent=False,unsafe=True,detail='Detached shutdown',
                       mounts=[],connection=self.connection,stale_conflict_only=True)
            monitor.sample(healthy,0);monitor.sample(healthy,15)
            # A dead old mount can be observed before the new UUID appears.
            waiting=dict(stale,detected=False,connection=None,unsafe=False)
            monitor.sample(waiting,30);monitor.sample(waiting,45)
            self.assertNotIn('main',monitor.state['incident']['blocked'])
            monitor.sample(stale,60);monitor.sample(stale,75)
            request=monitor.work_request(True,105)
            self.assertNotIn('main',request['blocked']);self.assertEqual(request['known_storage'],self.proof)
            monitor.state['incident']['blocked']=['main'];monitor.state['incident']['blocked_reason']='Earlier unsafe mount'
            monitor.sample(stale,120)
            self.assertIn('main',monitor.state['incident']['blocked'])

    def test_legacy_proof_cannot_suppress_unsafe_latch(self):
        with mock.patch.object(w,'log'):
            monitor=w.Monitor(self.folder/'state.json',now=0,boot=BOOT,application_tracking=False)
            current=dict(self.candidate(),healthy=False,detected=True,dependent=False,unsafe=True,detail='Conflict',mounts=[])
            monitor.sample(current,0);monitor.sample(current,15)
            self.assertIn('main',monitor.state['incident']['blocked'])

    def test_unrelated_unsafe_cause_is_not_suppressed_by_visible_detached_mount(self):
        with mock.patch.object(w,'log'):
            monitor=w.Monitor(self.folder/'state.json',now=0,boot=BOOT,application_tracking=False)
            healthy=dict(healthy=True,detected=True,dependent=True,unsafe=False,detail='Healthy',mounts=[],main_mount_proof=self.proof)
            monitor.sample(healthy,0);monitor.sample(healthy,15)
            current=dict(self.candidate(),healthy=False,detected=True,dependent=False,unsafe=True,
                         detail='UUID path is not a block device',mounts=[])
            monitor.sample(current,30);monitor.sample(current,45)
            self.assertIn('main',monitor.state['incident']['blocked'])

if __name__=='__main__':unittest.main()
