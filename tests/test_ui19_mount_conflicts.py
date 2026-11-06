# SPDX-License-Identifier: MIT
"""Read-only mount classification; synthetic devices, no mount/unmount commands."""
import importlib.util
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location('ui19_' + name, ROOT/'src/usb_storage_watch'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

w = load('engine')
spec = importlib.util.spec_from_file_location('ui19_fixture', Path(__file__).with_name('fixtures.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
fixture.configure(w)
broker = load('web_broker')
web_drives = load('web_drives')
BASE = '1 0 240:2 / / rw - ext4 /dev/sda2 rw\n'
MAIN = '2 1 240:17 / /mnt/storage rw - ext4 /dev/sdb1 rw\n'
IMAGE = '3 2 7:8 / /mnt/storage/_loop/files rw - ext4 /dev/loop8 rw\n'
CURRENT = '240:33'

class MountConflictTests(unittest.TestCase):
    def test_returned_uuid_new_device_does_not_erase_old_target_occupancy(self):
        rows = w.parse_mounts(BASE+MAIN+IMAGE)
        result = w.mount_observation(rows, w.MOUNT, CURRENT)
        self.assertEqual(result['mount_state'], 'conflict')
        self.assertTrue(result['mount_target_occupied'])
        self.assertIn('240:17', result['mount_detail']); self.assertIn(CURRENT, result['mount_detail'])
        self.assertIn('may be', result['mount_detail'])  # Do not diagnose stale ownership as established fact.
        with mock.patch.object(w, 'block_checks') as proof, self.assertRaises(w.Unsafe):
            w.mounted_checks(rows, w.MOUNT, CURRENT, w.DISK_UUID)
        proof.assert_not_called()

    def test_wrong_root_filesystem_stacked_and_hidden_mounts_remain_conflicts(self):
        fixtures = (
            MAIN.replace('240:17 / ', '240:17 /uploads '),
            MAIN.replace(' - ext4 ', ' - xfs '),
            MAIN+'3 2 240:18 / /mnt/storage rw - ext4 /dev/sdc1 rw\n',
            MAIN+'3 1 240:18 / /mnt rw - ext4 /dev/sdc1 rw\n',
        )
        for value in fixtures:
            rows = w.parse_mounts(BASE+value)
            with self.subTest(value=value):
                self.assertEqual(w.mount_observation(rows,w.MOUNT,'240:17')['mount_state'],'conflict')
                with self.assertRaises(w.Unsafe):w.mounted_checks(rows,w.MOUNT,'240:17',w.DISK_UUID)

    def test_child_mount_without_main_is_not_plain_unmounted(self):
        rows = w.parse_mounts(BASE+IMAGE.replace('3 2 ', '3 1 '))
        result = w.mount_observation(rows, w.MOUNT, CURRENT)
        self.assertEqual(result['mount_state'],'conflict');self.assertTrue(result['mount_target_occupied'])
        self.assertIn('/mnt/storage/_loop/files',result['mount_detail'])
        with mock.patch.object(w,'namespace_available') as namespace, self.assertRaises(w.Unsafe):
            w.mount_available(rows,w.MOUNT,CURRENT)
        namespace.assert_not_called()

    def test_missing_uuid_with_retained_target_is_still_occupied(self):
        result = w.mount_observation(w.parse_mounts(BASE+MAIN),w.MOUNT,None)
        self.assertEqual(result['mount_state'],'conflict');self.assertTrue(result['mount_target_occupied'])
        self.assertIn('unavailable',result['mount_detail'])
        self.assertEqual(w.mount_observation(w.parse_mounts(BASE),w.MOUNT,None)['mount_state'],'unavailable')

    def test_healthy_mount_unmounted_and_elsewhere_are_distinct_from_conflict(self):
        for rows,dev,state,occupied in (
            (BASE+MAIN,'240:17','mounted',True),
            (BASE,CURRENT,'unmounted',False),
            (BASE+MAIN.replace('/mnt/storage','/media/external'),'240:17','mounted_elsewhere',False),
        ):
            with self.subTest(state=state):
                result=w.mount_observation(w.parse_mounts(rows),w.MOUNT,dev)
                self.assertEqual(result['mount_state'],state);self.assertEqual(result['mount_target_occupied'],occupied)

    def test_snapshot_reports_conflict_and_manual_mount_still_sends_no_command(self):
        rows=w.parse_mounts(BASE+MAIN+IMAGE)
        with mock.patch.object(w,'read_rows',return_value=rows), mock.patch.object(w,'device_number',return_value=CURRENT), \
             mock.patch.object(w,'connection_identity',return_value=None), \
             mock.patch.object(w.usb,'bind_current',side_effect=w.Unsafe('No reset binding')):
            value=w.snapshot()
            self.assertFalse(value['healthy']);self.assertTrue(value['detected']);self.assertTrue(value['unsafe'])
            self.assertEqual(value['mount_state'],'conflict')
            with mock.patch.object(w,'command') as command, self.assertRaises(w.Unsafe) as error:
                w.mount_main(lambda *args:None)
            command.assert_not_called()
            self.assertIn('240:17',str(error.exception));self.assertIn(CURRENT,str(error.exception))

    def test_blocked_incident_retains_unsafe_reason_after_later_plain_absence(self):
        unsafe=dict(healthy=False,detected=True,dependent=False,unsafe=True,
                    detail='Old mount device 240:17 conflicts with returned device 240:33.',mounts=[])
        absent=dict(unsafe,unsafe=False,detected=False,detail='Expected device absent.')
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(w,'log'):
            monitor=w.Monitor(Path(folder)/'state.json',now=0,boot='test-boot',application_tracking=False)
            monitor.sample(unsafe,0,'first');monitor.sample(unsafe,15,'confirmed');monitor.sample(absent,30,'later')
            self.assertIsNone(monitor.work_request(True,60))
            # A qualified reset may be scheduled while absent, but the earlier
            # unsafe identity reason must still prevent every storage write.
            request=monitor.work_request(True,75,usb_enabled=True)
            self.assertIn('main',request['blocked']);self.assertEqual(request['blocked_reason'],unsafe['detail'])
            with mock.patch.object(w,'snapshot',return_value=absent),mock.patch.object(w,'command') as command:
                # Storage blocker scope; actual stop guard is covered by UI22 lifecycle tests.
                result=w.guarded_recovery_work(request,Path(folder)/'receipt.json')
            command.assert_not_called();self.assertFalse(result['main'])
            self.assertIn(unsafe['detail'],result['reason']);self.assertNotIn('Automatic main mount is disabled',result['reason'])

    def test_detail_is_bounded_without_control_characters(self):
        rows=w.parse_mounts(BASE+MAIN)
        rows[-1]['root']='x'*4000+'\n\r\tunsafe'
        result=w.mount_observation(rows,w.MOUNT,'240:17')
        self.assertLess(len(result['mount_detail']),700)
        self.assertNotIn('\n',result['mount_detail'])

    def test_status_and_fleet_propagate_conflict_without_changing_mounted_flags(self):
        c=broker.s.default();c['disk'].update(uuid=fixture.DISK_UUID if hasattr(fixture,'DISK_UUID') else '11111111-1111-4111-8111-111111111111',mountpoint=w.MOUNT)
        rows=w.parse_mounts(BASE+MAIN+IMAGE)
        probe=dict(w.mount_observation(rows,w.MOUNT,CURRENT),healthy=False,detected=True,detail='Conflict',mounts=[])
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(broker,'configuration',return_value=c), \
             mock.patch.object(broker,'service_state',return_value={'ActiveState':'inactive'}), \
             mock.patch.object(broker,'drive_metadata',return_value=None),mock.patch.object(broker,'recovery_progress',return_value={}), \
             mock.patch.object(broker.s,'STATE_DIR',Path(folder)),mock.patch.object(broker.w,'configure'), \
             mock.patch.object(broker.w,'load_state',return_value={}),mock.patch.object(broker.w,'snapshot',return_value=probe), \
             mock.patch.object(broker.w,'device_number',return_value=CURRENT),mock.patch.object(broker.w,'read_rows',return_value=rows), \
             mock.patch.object(broker.w.usb,'connection_details',return_value={}),mock.patch.object(broker.w.standby,'status',return_value={}):
            value=broker.status()
        self.assertFalse(value['mounted']);self.assertFalse(value['mounted_expected'])
        self.assertEqual(value['mount_state'],'conflict');self.assertTrue(value['mount_target_occupied'])
        instance=types.SimpleNamespace(request_lock=threading.Lock(),local_handle=lambda request:dict(status=200,data=value))
        fleet=types.SimpleNamespace(cache={},context=lambda:types.SimpleNamespace(disks=lambda:[],w=types.SimpleNamespace(timestamp=lambda:'now')),
                                    records=lambda:[('legacy',c,None)],get=lambda identifier:(None,instance))
        row=web_drives.Fleet.overview(fleet,{})['drives'][0]
        self.assertEqual(row['mount_state'],'conflict');self.assertEqual(row['mount_detail'],probe['mount_detail'])
        self.assertTrue(row['mount_target_occupied']);self.assertFalse(row['mounted'])

if __name__=='__main__':unittest.main()
