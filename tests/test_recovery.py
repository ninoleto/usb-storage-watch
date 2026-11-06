# SPDX-License-Identifier: MIT
#!/usr/bin/python3
"""Simulated recovery only. No real mounts, USB operations, SMTP or service changes."""
import ast
import copy
from contextlib import nullcontext
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import time
import types
import unittest
import uuid
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('recovery_watch', HERE.parent / 'src/usb_storage_watch/engine.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
_fs = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('fixtures.py'))
fixture = importlib.util.module_from_spec(_fs)
_fs.loader.exec_module(fixture)
fixture.configure(w)

ROOT = '1 0 240:2 / / rw,relatime - ext4 /dev/sda2 rw\n'
STORAGE = '2 1 240:17 / /mnt/storage rw,relatime - ext4 /dev/sdb1 rw\n'
DEP = '3 2 7:8 / /mnt/storage/_loop/files rw,nosuid,nodev,noexec - ext4 /dev/loop8 rw\n'


def observation(healthy=False, detected=True, dependent=False, unsafe=False):
    return {'healthy': healthy, 'detected': detected, 'dependent': dependent,
            'detail': 'Simulated healthy' if healthy else 'Simulated disk failure',
            'dependent_detail': 'Simulated dependent status', 'unsafe': unsafe,
            'mounts': [{'target': w.MOUNT, 'source': '/dev/simulated'}] if healthy else []}


def outcome(main=False, dependent=False, actions=None, reason='Simulated result', blocked=None):
    return {'main': main, 'dependent': dependent, 'detected': main, 'actions': actions or [],
            'reason': reason, 'dependent_reason': 'Simulated dependent loop result', 'blocked': blocked or [],
            'mounts': []}


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp', prefix='storage-recovery-test-')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        patch = mock.patch.object(w, 'log')
        patch.start()
        self.addCleanup(patch.stop)
        self.monitor = w.Monitor(self.path, now=0, boot='test-boot', application_tracking=False)

    def down(self, start=0):
        self.monitor.sample(observation(), start, 'first-failure')
        self.monitor.sample(observation(), start + 15, 'confirmed-failure')

    def up(self, start=100):
        self.monitor.sample(observation(True, True, True), start)
        self.monitor.sample(observation(True, True, True), start + 15)

    def restart(self, now=30, boot='test-boot'):
        self.monitor = w.Monitor(self.path, now=now, boot=boot, application_tracking=False)

    def attempt(self, now=75, main=False, dependent=False, actions=None, blocked=None):
        req = self.monitor.work_request(True, now)
        self.assertIsNotNone(req)
        self.monitor.work_result(req, outcome(main, dependent, actions, blocked=blocked), now + 1)
        return req


class RecoveryStateTests(Temp):
    def test_two_bad_samples_and_first_timestamp(self):
        self.monitor.sample(observation(), 0, 'first')
        self.assertIsNone(self.monitor.state['incident'])
        self.monitor.sample(observation(), 15, 'second')
        i = self.monitor.state['incident']
        self.assertEqual(i['first_failure'], 'first')
        self.assertEqual(i['due'], 75)
        self.assertFalse(self.monitor.state['pending'])

    def test_transient_failure_and_nonconsecutive_samples_do_not_trigger(self):
        for snap, now in [(observation(), 0), (observation(True), 15), (observation(), 30), (observation(), 100)]:
            self.monitor.sample(snap, now)
        self.assertIsNone(self.monitor.state['incident'])

    def test_healthy_startup_does_not_mail(self):
        self.up(0)
        self.assertEqual(self.monitor.state['status'], 'up')
        self.assertEqual(self.monitor.state['pending'], [])

    def test_confirmation_wait_and_one_sequence_without_overlap(self):
        self.down()
        self.assertIsNone(self.monitor.work_request(True, 74.99))
        req = self.monitor.work_request(True, 75)
        self.assertIsNone(self.monitor.work_request(True, 100))
        self.monitor.work_result(req, outcome(), 80)
        self.assertIsNone(self.monitor.work_request(True, 140))
        self.assertEqual(len(self.monitor.state['incident']['attempts']), 1)

    def test_failure_stops_after_sequence_and_sends_one_detailed_outcome(self):
        self.down()
        self.attempt(75)
        self.assertIsNone(self.monitor.work_request(True, 136))
        for now in range(150, 600, 15):
            self.monitor.sample(observation(), now)
            self.assertIsNone(self.monitor.work_request(True, now))
        events = self.monitor.state['pending']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['subject'], 'Storage RECOVERY FAILED — Manual intervention required')
        for text in ['first-failure', 'Recovery attempts', 'Storage detected', 'Current mounts', 'dependent loop available', 'USB resets: 0']:
            self.assertIn(text, events[0]['detail'])
        self.restart(900)
        self.assertIsNone(self.monitor.work_request(True, 900))
        self.assertEqual(len(self.monitor.state['pending']), 1)

    def test_natural_return_no_auto_claim(self):
        self.down()
        self.up(30)
        self.assertIsNone(self.monitor.work_request(True, 60))
        self.attempt(75, True, True)
        self.up(90)
        self.assertEqual(self.monitor.state['pending'][0]['subject'], 'Storage mount restored naturally')

    def test_successful_first_mount(self):
        self.down()
        self.attempt(75, True, True, [{'target': 'main', 'stage': 'returned'}])
        self.assertEqual(self.monitor.state['pending'], [])
        self.up(90)
        self.assertEqual(self.monitor.state['pending'][0]['subject'], 'Storage AUTO-RECOVERED — Attempt 1')

    def test_usb_and_final_mount_success_in_one_sequence(self):
        self.down()
        self.attempt(75, True, True, [{'target': 'main', 'stage': 'failed'},
            {'target': 'usb', 'stage': 'returned'}, {'target': 'main', 'stage': 'returned'}])
        self.up(150)
        self.assertEqual(self.monitor.state['pending'][0]['subject'], 'Storage AUTO-RECOVERED — Attempt 1')

    def test_partial_recovery(self):
        self.down()
        self.attempt(75, True, False, [{'target': 'main', 'stage': 'returned'}])
        self.up(90)
        self.assertEqual(self.monitor.state['pending'][0]['subject'], 'Storage PARTIALLY RECOVERED — dependent loop mount unavailable')

    def test_mount_intent_without_success_never_claims_auto(self):
        self.down()
        self.attempt(75, True, True, [{'target': 'main', 'stage': 'intent'}])
        self.up(90)
        self.assertIn('naturally', self.monitor.state['pending'][0]['subject'])

    def test_rearm_requires_healthy_samples_and_independent_proof(self):
        self.down()
        self.attempt(75)
        self.assertIsNone(self.monitor.work_request(True, 136))
        self.up(150)
        self.assertEqual(self.monitor.state['status'], 'down')
        req = self.monitor.work_request(True, 170)
        self.assertTrue(req['check_only'])
        self.assertFalse(req['allow_mount'])
        self.monitor.work_result(req, outcome(True, True), 171)
        self.assertEqual(self.monitor.state['status'], 'up')
        self.assertEqual(len(self.monitor.state['pending']), 1)
        old = self.monitor.state['incident']['id']
        self.down(180)
        self.assertNotEqual(self.monitor.state['incident']['id'], old)
        self.assertEqual(self.monitor.state['incident']['attempts'], [])

    def test_restart_preserves_wait_and_debounce(self):
        self.monitor.sample(observation(), 0, 'first')
        self.restart(10)
        self.monitor.sample(observation(), 15)
        self.restart(50)
        self.assertIsNone(self.monitor.work_request(True, 74))
        self.assertIsNotNone(self.monitor.work_request(True, 75))

    def test_restart_running_consumes_attempt_and_blocks_uncertain_actions(self):
        self.down()
        self.monitor.work_request(True, 75)
        self.restart(80)
        i = self.monitor.state['incident']
        self.assertEqual(i['attempts'][0]['status'], 'interrupted')
        self.assertEqual(i['blocked'], ['main', 'dependent'])
        self.assertIsNone(self.monitor.work_request(True, 140))
        self.assertEqual(i['phase'], 'done')
        self.assertEqual(len(self.monitor.state['pending']), 1)

    def test_restart_after_completed_durable_receipt_keeps_action_attribution(self):
        self.down()
        req = self.monitor.work_request(True, 75)
        receipt = {'incident': req['incident'], 'number': 1, 'complete': True,
                   'result': outcome(True, True, [{'target': 'main', 'stage': 'returned'}])}
        (self.path.parent / 'recovery-receipt.json').write_text(json.dumps(receipt))
        self.restart(80)
        self.up(90)
        self.assertEqual(self.monitor.state['pending'][0]['subject'], 'Storage AUTO-RECOVERED — Attempt 1')

    def test_stale_receipt_cannot_credit_current_sequence(self):
        self.down()
        req = self.monitor.work_request(True, 75)
        (self.path.parent / 'recovery-receipt.json').write_text(json.dumps(
            {'incident': str(uuid.uuid4()), 'number': 1, 'complete': True, 'result': outcome(True, True)}))
        self.restart(80)
        self.assertFalse(self.monitor.state['incident']['result']['main'])
        self.assertIsNone(self.monitor.work_request(True, 140))
        self.assertIn('FAILED', self.monitor.state['pending'][0]['subject'])

    def test_reboot_has_new_wait_and_distinct_restoration(self):
        self.down()
        self.restart(5, 'new-boot')
        self.assertIsNone(self.monitor.work_request(True, 64))
        self.attempt(65, True, True)
        self.up(80)
        self.assertEqual(self.monitor.state['pending'][0]['subject'], 'Storage mount restored after reboot')

    def test_disabling_recovery_keeps_outcome_notifications(self):
        self.down()
        req = self.monitor.work_request(False, 75)
        self.assertFalse(req['allow_mount'])
        self.monitor.work_result(req, outcome(), 76)
        self.assertIsNone(self.monitor.work_request(False, 136))
        self.assertEqual(len(self.monitor.state['pending']), 1)

    def test_unsafe_observation_latches_no_mount_for_incident(self):
        self.down()
        self.monitor.sample(observation(unsafe=True), 30)
        req = self.monitor.work_request(True, 75)
        self.assertIn('main', req['blocked'])

    def test_usb_absolute_ceiling_across_restart_qualified_host(self):
        self.down()
        self.monitor.state['incident']['usb_resets'] = 1
        self.monitor.commit(self.monitor.state)
        self.attempt(75)
        self.restart(90)
        self.assertIsNone(self.monitor.work_request(True, 136))
        self.assertEqual(self.monitor.state['incident']['usb_resets'], 1)
        source = (HERE.parent / 'src/usb_storage_watch/engine.py').read_text()
        self.assertNotIn('uhubctl', source)
        self.assertTrue(w.usb.HOST_VERIFIED)
        self.assertEqual(w.MAX_USB_RESETS, 1)

    def test_corrupt_or_overbudget_state_never_resets(self):
        for mutate in [lambda s: s.update(version=99),
                       lambda s: s['incident'].update(usb_resets=2),
                       lambda s: s['incident'].update(attempts=[{}, {}, {}]),
                       lambda s: s['incident'].update(due=float('nan'))]:
            self.down()
            s = copy.deepcopy(self.monitor.state)
            mutate(s)
            raw = json.dumps(s)
            self.path.write_text(raw)
            with self.assertRaises(ValueError):
                w.load_state(self.path)
            self.assertEqual(self.path.read_text(), raw)
            self.monitor.commit(self.monitor.state)

    def test_failed_persistence_prevents_action_reservation(self):
        self.down()
        with mock.patch.object(w, 'atomic_write', side_effect=OSError('simulated')):
            with self.assertRaises(OSError):
                self.monitor.work_request(True, 75)
        self.assertEqual(self.monitor.state['incident']['attempts'], [])

    def test_legacy_state_preserves_queue_and_disables_new_action_budget(self):
        event = w.make_event('failure', 'legacy queued failure')
        old = {'version': 1, 'status': 'down', 'pending': [event], 'changed_at': 'legacy time'}
        self.path.write_text(json.dumps(old))
        self.restart(0)
        self.assertEqual(self.monitor.state['pending'][0], event)
        self.assertIsNone(self.monitor.work_request(True, 999))
        self.up(1000)
        req = self.monitor.work_request(True, 1020)
        self.assertFalse(req['allow_mount'])
        self.monitor.work_result(req, outcome(True, True), 1021)
        self.assertEqual(len(self.monitor.state['pending']), 2)

    def test_health_lost_after_mount_does_not_queue_success(self):
        self.down()
        self.attempt(75, True, True, [{'target': 'main', 'stage': 'returned'}])
        self.monitor.sample(observation(), 90)
        self.assertEqual(self.monitor.state['incident']['phase'], 'done')
        self.assertIn('FAILED', self.monitor.state['pending'][0]['subject'])


class QueueTests(Temp):
    def queued(self):
        self.down()
        self.attempt(75)
        self.assertIsNone(self.monitor.work_request(True, 136))

    def test_fifo_retry_stable_id_and_restart_suppression(self):
        self.queued()
        e = self.monitor.begin_attempt(1000)
        self.restart(200)
        self.assertFalse(self.monitor.ready(1001))
        self.assertTrue(self.monitor.ready(1080))
        retry = self.monitor.begin_attempt(1080)
        self.assertEqual(e['id'], retry['id'])
        self.assertEqual(retry['attempts'], 2)
        self.monitor.finish_attempt(e['id'], False, 1081)
        self.assertFalse(self.monitor.ready(1140))
        self.assertTrue(self.monitor.ready(1141))
        self.monitor.finish_attempt(e['id'], True, 1141)
        self.restart(300)
        self.assertEqual(self.monitor.state['pending'], [])
        self.assertIsNone(self.monitor.work_request(True, 9999))

    def test_backwards_wallclock_only_clamps_email_retry(self):
        self.queued()
        self.monitor.begin_attempt(10000)
        self.assertFalse(self.monitor.ready(1))
        self.assertTrue(self.monitor.ready(61))

    def test_corrupt_queue_and_payload(self):
        self.queued()
        event = self.monitor.begin_attempt(1000)
        payload = w.event_payload(event, 'Latest simulated observation')
        self.assertIn('Latest simulated observation', payload['body'])
        self.assertIn(w.DISK_UUID, payload['body'])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        s = copy.deepcopy(self.monitor.state)
        s['pending'][0]['retry_at'] = float('nan')
        self.path.write_text(json.dumps(s))
        with self.assertRaises(ValueError):
            w.load_state(self.path)


class ConnectionRearmTests(Temp):
    def observation(self, sequence=1, healthy=False, boot='test-boot'):
        return observation(healthy, True, healthy) | {'connection': {'boot': boot, 'diskseq': sequence}}

    def exhaust(self):
        self.monitor.sample(self.observation(), 0)
        self.monitor.sample(self.observation(), 15)
        self.attempt(75)
        self.assertIsNone(self.monitor.work_request(True, 136))
        return self.monitor.state['incident']['id']

    def test_late_new_connection_rearms_a_refused_no_write_outage(self):
        self.exhaust()
        old = self.monitor.state['incident']['id']
        for now in (150,165): self.monitor.sample(self.observation(2), now)
        self.assertNotEqual(self.monitor.state['incident']['id'], old)
        self.assertIsNotNone(self.monitor.work_request(True, 225))
        self.assertFalse(self.monitor.state['reconnect_pending'])

    def test_restart_and_same_device_disappearance_do_not_renew_budget(self):
        old = self.exhaust()
        for snap, now in [(observation(),150),(self.observation(),165),(self.observation(),180)]:
            self.monitor.sample(snap,now)
        self.restart(200)
        self.monitor.sample(self.observation(),210)
        self.assertEqual(self.monitor.state['incident']['id'],old)
        self.assertEqual(len(self.monitor.state['incident']['attempts']),1)
        self.assertIsNone(self.monitor.work_request(True,300))

    def test_legacy_identity_and_reboot_only_anchor_without_retry(self):
        old=self.exhaust()
        del self.monitor.state['incident']['connection']
        self.monitor.commit(self.monitor.state)
        for now in (150,165):self.monitor.sample(self.observation(2),now)
        self.assertEqual(self.monitor.state['incident']['id'],old)
        self.restart(170,boot='new-boot')
        for now in (180,195):self.monitor.sample(self.observation(3,boot='new-boot'),now)
        self.assertEqual(self.monitor.state['incident']['id'],old)
        self.assertIsNone(self.monitor.work_request(True,300))

    def test_absent_attempts_preserve_last_attachment_for_late_reconnect(self):
        self.monitor.sample(self.observation(1,True),0)
        self.monitor.sample(self.observation(1,True),15)
        self.down(30)
        self.attempt(105)
        old=self.monitor.state['incident']['id']
        for now in (180,195):self.monitor.sample(self.observation(2),now)
        self.assertNotEqual(self.monitor.state['incident']['id'],old)
        self.assertIsNotNone(self.monitor.work_request(True,300))

    def test_each_distinct_attachment_gets_one_attempt_without_replaying_same_attachment(self):
        self.exhaust()
        old=self.monitor.state['incident']['id']
        for sequence in range(2,10):
            for now in (sequence*60+150,sequence*60+165): self.monitor.sample(self.observation(sequence),now)
            request = self.monitor.work_request(True,sequence*60+225)
            self.assertIsNotNone(request)
            self.monitor.work_result(request, outcome(),sequence*60+226)
            self.assertIsNone(self.monitor.work_request(True,sequence*60+240))
        self.assertNotEqual(self.monitor.state['incident']['id'],old)
        self.assertEqual(len(self.monitor.state['pending']),9)

    def test_worker_returned_attachment_does_not_create_another_budget(self):
        self.down()
        req = self.monitor.work_request(True, 75)
        self.monitor.work_result(req, outcome() | {'connection':{'boot':'test-boot','diskseq':2}}, 76)
        old = self.monitor.state['incident']['id']
        self.monitor.sample(self.observation(2), 150)
        self.monitor.sample(self.observation(2), 165)
        self.assertEqual(self.monitor.state['incident']['id'], old)
        self.assertIsNone(self.monitor.work_request(True, 200))

    def test_new_attachment_does_not_bypass_an_unsafe_observation(self):
        self.exhaust()
        for now in (150,165):self.monitor.sample(self.observation(2) | {'unsafe':True},now)
        self.assertIsNone(self.monitor.work_request(True,225))


class SafetyTests(unittest.TestCase):
    def test_attachment_identity_requires_expected_usb_metadata_and_disk_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            disk=Path(directory);part=disk/'partition-node';part.mkdir();(part/'partition').write_text('1')
            (disk/'diskseq').write_text('42')
            identity={'ID_FS_UUID':w.DISK_UUID,'ID_FS_TYPE':'ext4','ID_BUS':'usb','ID_SERIAL':'SYNTHETIC-DEVICE'}
            with mock.patch.object(w,'udev',return_value=identity),mock.patch.object(Path,'resolve',return_value=part),mock.patch.object(w,'boot_id',return_value='test-boot'),mock.patch.object(w.usb,'is_verified_usb_block',return_value=True) as usb_guard:
                self.assertEqual(w.connection_identity('240:17'),{'boot':'test-boot','diskseq':42})
                identity['ID_BUS']='ata'  # The physical sysfs USB guard is authoritative, not ID_BUS.
                self.assertEqual(w.connection_identity('240:17'),{'boot':'test-boot','diskseq':42})
                usb_guard.return_value=False
                self.assertIsNone(w.connection_identity('240:17')) # Direct SATA/unproven attachment.
                usb_guard.return_value=True
                identity['ID_FS_UUID']='wrong';self.assertIsNone(w.connection_identity('240:17'))
                identity['ID_FS_UUID']=w.DISK_UUID;(disk/'diskseq').unlink();self.assertIsNone(w.connection_identity('240:17'))

    def super_data(self, uuid_value=w.DISK_UUID, state=1, incompat=0x40, errors=0, compat=0x4):
        b = bytearray(1024)
        struct.pack_into('<H', b, 0x38, 0xef53)
        struct.pack_into('<H', b, 0x3a, state)
        struct.pack_into('<I', b, 0x60, incompat)
        struct.pack_into('<I', b, 0x5c, compat)
        struct.pack_into('<I', b, 0x194, errors)
        b[0x68:0x78] = uuid.UUID(uuid_value).bytes
        return bytes(b)

    def test_correct_clean_superblock(self):
        w.superblock(self.super_data(), w.DISK_UUID, True)

    def test_wrong_actual_uuid_rejected(self):
        with self.assertRaisesRegex(w.Unsafe, 'UUID'):
            w.superblock(self.super_data(uuid_value=str(uuid.uuid4())), w.DISK_UUID, True)

    def test_error_aborted_journal_unclean_and_recorded_errors_rejected(self):
        for kwargs in [dict(state=2), dict(state=0), dict(incompat=0x44, compat=0),
                       dict(errors=1), dict(state=5), dict(state=2, incompat=0x44)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(w.Unsafe):
                w.superblock(self.super_data(**kwargs), w.DISK_UUID, True)

    def test_active_journal_not_mistaken_for_unmounted_corruption(self):
        w.superblock(self.super_data(state=0, incompat=0x44), w.DISK_UUID, False)

    def test_normal_journal_replay_allowed_without_recorded_errors(self):
        for state in (0, 1):
            w.superblock(self.super_data(state=state, incompat=0x44), w.DISK_UUID, True)

    def test_mount_namespace_checks_reject_active_device_and_unreadable_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc / '10').mkdir()
            (proc / '10/mountinfo').write_text(ROOT)
            w.namespace_available('240:17', proc)
            (proc / '10/mountinfo').write_text(ROOT + STORAGE.replace('/mnt/storage', '/data'))
            with self.assertRaisesRegex(w.Unsafe, 'namespace'):
                w.namespace_available('240:17', proc)
            (proc / '10/mountinfo').write_text('malformed')
            with self.assertRaisesRegex(w.Unsafe, 'namespaces'):
                w.namespace_available('240:17', proc)
            with mock.patch.object(Path, 'read_text', side_effect=PermissionError):
                with self.assertRaisesRegex(w.Unsafe, 'namespaces'):
                    w.namespace_available('240:17', proc)

    def test_busy_block_device_fails_closed_before_direct_probe(self):
        import errno
        with mock.patch.object(os, 'open', side_effect=OSError(errno.EBUSY, 'busy')) as opened, \
                mock.patch.object(w, 'command') as command:
            with self.assertRaisesRegex(w.Unsafe, 'still in use'):
                w.disk_proof(Path('/dev/synthetic'), w.DISK_UUID, unmounted=True)
            self.assertTrue(opened.call_args.args[1] & os.O_EXCL)
            command.assert_not_called()

    def test_namespace_einval_for_exiting_process_is_rechecked_not_ignored(self):
        import errno
        with tempfile.TemporaryDirectory() as directory:
            proc=Path(directory);(proc/'10').mkdir()
            error=OSError(errno.EINVAL,'Exiting process')
            with mock.patch.object(Path,'read_text',side_effect=[error,ROOT]) as read, mock.patch.object(w.time,'sleep'):
                w.namespace_available('240:17',proc)
                self.assertEqual(read.call_count,2)
            with mock.patch.object(Path,'read_text',side_effect=[error,ROOT+STORAGE]), mock.patch.object(w.time,'sleep'):
                with self.assertRaisesRegex(w.Unsafe,'already mounted'):w.namespace_available('240:17',proc)

    def test_namespace_persistent_einval_fails_closed_with_bounded_checks(self):
        import errno
        with tempfile.TemporaryDirectory() as directory:
            proc=Path(directory);(proc/'10').mkdir()
            with mock.patch.object(Path,'read_text',side_effect=OSError(errno.EINVAL,'Invalid argument')) as read, mock.patch.object(w.time,'sleep'):
                with self.assertRaisesRegex(w.Unsafe,'namespaces'):w.namespace_available('240:17',proc)
                self.assertEqual(read.call_count,3)

    def test_namespace_exiting_process_skipped_only_after_pid_disappears(self):
        import errno
        with tempfile.TemporaryDirectory() as directory:
            proc=Path(directory);(proc/'10').mkdir()
            def exiting(path,**kwargs):
                (proc/'10').rmdir()
                raise OSError(errno.EINVAL,'Exiting process')
            with mock.patch.object(Path,'read_text',exiting):w.namespace_available('240:17',proc)

    def test_real_unreaped_process_exit_is_kernel_verified_without_skipping_live_processes(self):
        # Some executors expose the host's procfs while fork/getpid use a
        # different PID namespace. /proc/<child pid> then names an unrelated
        # host process (or no process), so this kernel integration check cannot
        # establish anything there. Keep the real assertions on normal Linux.
        if Path('/proc/self').resolve() != Path('/proc') / str(os.getpid()):
            self.skipTest('procfs PID namespace differs from getpid/fork; requires matching Linux procfs')
        self.assertFalse(w.process_exited(Path('/proc')/str(os.getpid())))
        pid=os.fork()
        if pid==0:os._exit(0)
        try:
            os.waitid(os.P_PID,pid,os.WEXITED|os.WNOWAIT)
            proc=Path('/proc')/str(pid)
            self.assertTrue(proc.exists())  # Deliberately not reaped yet.
            self.assertTrue(w.process_exited(proc))
            self.assertFalse(w.process_exited(Path('/proc')/str(os.getpid())))
            with mock.patch.object(Path,'iterdir',return_value=iter([proc])):
                w.namespace_available('240:17')
        finally:os.waitpid(pid,0)

    def test_unavailable_exit_proof_fails_closed(self):
        with mock.patch.object(os,'pidfd_open',side_effect=PermissionError):
            self.assertFalse(w.process_exited(Path('/proc')/str(os.getpid())))

    def test_both_rw_levels_wrong_type_uuid_and_stacks(self):
        for text in [ROOT+STORAGE.replace('rw,relatime', 'ro,relatime'),
                     ROOT+STORAGE.replace('/dev/sdb1 rw', '/dev/sdb1 ro'),
                     ROOT+STORAGE.replace('240:17', '8:33'),
                     ROOT+STORAGE.replace('ext4', 'xfs'),
                     ROOT+STORAGE+STORAGE.replace('2 1', '3 2')]:
            with self.subTest(text=text), self.assertRaises(w.Unsafe):
                w.mounted_checks(w.parse_mounts(text), w.MOUNT, '240:17', w.DISK_UUID)

    def test_unexpected_live_mount_and_submount_block_mount(self):
        for text in [ROOT+STORAGE, ROOT+DEP, ROOT+STORAGE.replace('/mnt/storage', '/elsewhere')]:
            with self.assertRaises(w.Unsafe):
                w.mount_available(w.parse_mounts(text), w.MOUNT, '240:17')

    def test_fstab_exact_identity_and_options(self):
        good = f'UUID={w.DISK_UUID} {w.MOUNT} ext4 {w.FSTAB_MAIN_OPTIONS} 0 2\n'
        with mock.patch.object(Path, 'read_text', return_value=good):
            w.fstab_check(w.MOUNT)
        for bad in [good.replace(w.DISK_UUID, str(uuid.uuid4())), good + good,
                    good.replace('defaults,', 'ro,'), good.replace('ext4', 'xfs')]:
            with mock.patch.object(Path, 'read_text', return_value=bad), self.assertRaises(w.Unsafe):
                w.fstab_check(w.MOUNT)

    def test_usb_cannot_be_enabled_without_hardware_qualification(self):
        for value in [True, 1, 'true']:
            with mock.patch.object(w.usb, 'HOST_VERIFIED', False), mock.patch.object(Path, 'read_text', return_value=json.dumps(
                    {'version': 1, 'automatic_recovery': True, 'usb_reset_enabled': value})):
                with self.assertRaises(w.Unsafe):
                    w.config_load()

    def test_nonempty_target_preserved_and_symlink_refused(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as d:
            path = Path(d) / 'target'
            path.mkdir()
            w.safe_path(path, path.stat().st_dev)
            (path / 'file').write_text('simulated')
            w.safe_path(path, path.stat().st_dev)
            self.assertEqual((path / 'file').read_text(), 'simulated')
            link = Path(d) / 'link'
            link.symlink_to(path)
            with self.assertRaises(w.Unsafe):
                w.safe_path(link, path.stat().st_dev)

    def test_no_forbidden_external_commands(self):
        tree = ast.parse((HERE.parent / 'src/usb_storage_watch/engine.py').read_text())
        strings = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        for forbidden in ['fsck', 'e2fsck', 'reboot', 'uhubctl', 'usbreset']:
            self.assertFalse(any(x == forbidden or x.endswith('/' + forbidden) for x in strings))
        # 'shutdown' is now an ext4 metadata flag, never a system command.
        self.assertFalse(any(x.endswith('/shutdown') for x in strings))
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
                self.assertFalse(isinstance(node.elts[0], ast.Constant) and node.elts[0].value == 'shutdown')
        # All cleanup commands stay within the two guarded implementations;
        # every unmount is ordinary, explicit-target, bounded, and non-recursive.
        unmounts = [node.elts[0] for node in ast.walk(tree)
                    if isinstance(node, (ast.List, ast.Tuple)) and node.elts
                    and isinstance(node.elts[0], ast.Constant) and isinstance(node.elts[0].value, str)
                    and (node.elts[0].value == 'umount' or node.elts[0].value.endswith('/umount'))]
        checked = []
        for cleanup in (node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name in ('cleanup_detached_main', 'cleanup_failed_main')):
            calls = [node for node in ast.walk(cleanup) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == 'command']
            self.assertTrue(calls)
            for call in calls:
                argv = call.args[0]
                self.assertIsInstance(argv, ast.List)
                prefix = [item.value for item in argv.elts[:-1]]
                if prefix[0] == '/usr/bin/umount':
                    self.assertEqual(prefix, ['/usr/bin/umount', '--internal-only', '--no-canonicalize', '--'])
                    self.assertIn(ast.unparse(argv.elts[-1]), ('MOUNT', 'target', "row['target']"))
                    checked.append(argv.elts[0])
                    self.assertEqual([(item.arg, item.value.value) for item in call.keywords], [('timeout', 15)])
                else:
                    self.assertEqual(prefix, ['/usr/sbin/losetup', '--detach', '--'])
                    self.assertEqual([(item.arg, item.value.value) for item in call.keywords], [('timeout', 8)])
        self.assertTrue(checked)
        self.assertCountEqual(checked, unmounts)
        self.assertNotIn('remount,rw', strings)


class RecoveryWorkerTests(Temp):
    def setUp(self):
        super().setUp()
        # Storage-unit boundary only. Full lifecycle tests exercise the actual
        # persisted Docker stop ledger and live storage guard together.
        patch = mock.patch.object(w.apps, 'storage_recovery_guard', side_effect=lambda *_: nullcontext())
        patch.start()
        self.addCleanup(patch.stop)

    def work(self, healthy=False, present=True, mount_failure=None, proof_failure=None, dep_failure=None, allow=True, natural_return=False, mount_rows=None, directory_failure=None):
        req = {'incident': 'test', 'number': 1, 'allow_mount': allow, 'blocked': []}
        state = {'mounted': healthy, 'dependent': True, 'reads': 0}
        def snap():
            state['reads'] += 1
            if natural_return and state['reads'] >= 2:
                state['mounted'] = True
            return observation(state['mounted'], present, state['dependent'])
        def cmd(argv, **kw):
            if argv[0] == '/usr/bin/mount':
                if mount_failure:
                    raise mount_failure
                state['mounted'] = True
            return ''
        proof = types.SimpleNamespace(st_rdev=os.makedev(240, 17))
        rows = w.parse_mounts(mount_rows or ROOT)
        with mock.patch.object(w, 'snapshot', side_effect=snap), \
                mock.patch.object(w, 'read_rows', return_value=rows), \
                mock.patch.object(w, 'device_number', return_value='240:17'), \
                mock.patch.object(w, 'mount_available'), mock.patch.object(w, 'block_checks'), \
                mock.patch.object(w, 'safe_path'), mock.patch.object(w, 'fstab_check'), \
                mock.patch.object(w, 'protected_mount_directory', side_effect=directory_failure), \
                mock.patch.object(Path, 'exists', return_value=present), \
                mock.patch.object(Path, 'resolve', return_value=Path('/dev/simulated')), \
                mock.patch.object(w, 'disk_proof', return_value=proof, side_effect=proof_failure), \
                mock.patch.object(w, 'verify_main'), mock.patch.object(w, 'verify_access'), \
                mock.patch.object(w, 'verify_dependent', side_effect=dep_failure), \
                mock.patch.object(w, 'command', side_effect=cmd) as command, \
                mock.patch.object(w, 'covers', side_effect=lambda a,b: a == w.DEPENDENT or b == a or b.startswith(a.rstrip('/') + '/')):
            # Treat dependent as already mounted to isolate main recovery actions.
            result = w.recovery_work(req, self.path.parent / 'receipt.json')
        return result, command

    def test_desktop_tmpfs_recovery_uses_only_normal_guarded_mount(self):
        rows = ROOT + '2 1 0:17 / /run rw - tmpfs tmpfs rw\n'
        with mock.patch.object(w, 'MOUNT', '/run/media/test/USW_TEST'):
            result, command = self.work(mount_rows=rows)
            command.assert_called_once_with(['/usr/bin/mount', '--', w.MOUNT], timeout=12)
        self.assertTrue(result['main'])

    def test_desktop_directory_failure_never_mounts_or_resets(self):
        rows = ROOT + '2 1 0:17 / /run rw - tmpfs tmpfs rw\n'
        with mock.patch.object(w, 'MOUNT', '/run/media/test/USW_TEST'):
            result, command = self.work(mount_rows=rows, directory_failure=w.Unsafe('unsafe parent'))
        command.assert_not_called(); self.assertFalse(result['main'])
        self.assertIn('main', result['blocked'])

    def test_absent_device_skips_usb(self):
        result, command = self.work(present=False)
        self.assertFalse(result['main'])
        self.assertTrue(result['waiting_device'])
        self.assertIn('Waiting', result['reason'])
        self.assertFalse(result['blocked'])
        command.assert_not_called()

    def test_already_healthy_no_mount(self):
        result, command = self.work(healthy=True)
        self.assertTrue(result['main'])
        self.assertTrue(result['dependent'])
        self.assertEqual(result['actions'], [])
        command.assert_not_called()

    def test_natural_remount_during_recheck_does_not_issue_another_mount(self):
        recovered, command = self.work(natural_return=True)
        self.assertTrue(recovered['main'])
        self.assertEqual(recovered['actions'], [])
        command.assert_not_called()

    def test_timed_out_enumeration_stops_without_mounting_late_device(self):
        req = {'incident': 'simulated', 'number': 1, 'allow_mount': True, 'allow_usb': True, 'blocked': []}
        with mock.patch.object(w, 'snapshot', return_value=observation(detected=False)), \
                mock.patch.object(Path, 'exists', side_effect=[False, True]) as exists, \
                mock.patch.object(w.usb, 'cycle', return_value={'cycled': True, 'ready': False,
                    'reset_count': 1, 'reason': 'No expected device in 20 seconds.'}), \
                mock.patch.object(w, 'command') as command:
            recovered = w.recovery_work(req, self.path.parent/'receipt.json')
        self.assertFalse(recovered['main'])
        self.assertTrue(recovered['waiting_device'])
        self.assertIn('20 seconds', recovered['reason'])
        self.assertEqual(exists.call_count, 1)
        command.assert_not_called()

    def test_normal_mount_and_durable_intent(self):
        result, command = self.work()
        self.assertTrue(result['main'])
        command.assert_called_once_with(['/usr/bin/mount', '--', w.MOUNT], timeout=12)
        self.assertEqual([a['stage'] for a in result['actions']], ['intent', 'returned'])
        receipt = json.loads((self.path.parent / 'receipt.json').read_text())
        self.assertFalse(receipt['complete'])
        self.assertEqual(receipt['number'], 1)

    def test_mount_failure_stops_when_usb_cycle_is_unavailable(self):
        result, command = self.work(mount_failure=w.MountFailure('mount exited 32: temporarily busy'))
        self.assertFalse(result['main'])
        self.assertEqual(result['blocked'], ['main'])
        self.assertIn('temporarily busy', result['reason'])

    def test_bad_uuid_or_readonly_never_mount(self):
        for reason in ['Actual on-disk filesystem UUID is incorrect.', 'Filesystem is read-only']:
            result, command = self.work(proof_failure=w.Unsafe(reason))
            self.assertFalse(result['main'])
            self.assertIn('main', result['blocked'])
            command.assert_not_called()

    def test_mount_filesystem_error_blocks_retry(self):
        result, _ = self.work(mount_failure=w.MountFailure('mount exited 32: aborted journal I/O error'))
        self.assertIn('main', result['blocked'])

    def test_dependent_failure_reports_partial(self):
        result, _ = self.work(healthy=True, dep_failure=w.Unsafe('dependent loop loop UUID wrong'))
        self.assertTrue(result['main'])
        self.assertFalse(result['dependent'])
        self.assertIn('UUID wrong', result['dependent_reason'])

    def test_disabled_recovery_never_mounts(self):
        result, command = self.work(allow=False)
        self.assertFalse(result['main'])
        command.assert_not_called()


class WorkerDeadlineTests(Temp):
    def test_hung_command_deadline_and_lock_inheritance(self):
        with (self.path.parent / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            worker = w.Worker([sys.executable, '-I', '-c', 'import time; time.sleep(30)'],
                              {}, 0.05, self.path.parent, lock.fileno())
            start = time.monotonic()
            while worker.poll() is None:
                time.sleep(0.01)
            self.assertTrue(worker.timed_out)
            self.assertLess(time.monotonic() - start, 1)
            worker.proc.wait(timeout=2)
            worker.close()

    def test_poll_never_waits_for_unkillable_child(self):
        worker = object.__new__(w.Worker)
        worker.proc = mock.Mock(pid=123456)
        worker.proc.poll.return_value = None
        worker.deadline = 0
        worker.timed_out = False
        with mock.patch.object(w.os, 'killpg') as kill:
            self.assertFalse(worker.poll())
        kill.assert_called_once()
        worker.proc.wait.assert_not_called()

    def test_nonreading_mail_worker_and_large_payload_do_not_block(self):
        payload = {'id': str(uuid.uuid4()), 'subject': 'simulated', 'body': 'x' * 65536}
        start = time.monotonic()
        worker = w.Delivery(payload, [sys.executable, '-I', '-c', 'import time; time.sleep(30)'],
                            timeout=0.05, input_dir=self.path.parent)
        while worker.poll() is None:
            time.sleep(0.01)
        worker.proc.wait(timeout=2)
        worker.close()
        self.assertLess(time.monotonic() - start, 1)



class DependentMountTests(Temp):
    def setUp(self):
        super().setUp()
        # Storage-unit boundary only. Full lifecycle tests exercise the actual
        # persisted Docker stop ledger and live storage guard together.
        patch = mock.patch.object(w.apps, 'storage_recovery_guard', side_effect=lambda *_: nullcontext())
        patch.start()
        self.addCleanup(patch.stop)

    def dependent(self, failure=None, parent_failure=None):
        request = {'incident': 'test', 'number': 1, 'allow_mount': True, 'blocked': []}
        rows = w.parse_mounts(ROOT + STORAGE)
        info = types.SimpleNamespace(st_dev=os.makedev(240, 17), st_ino=1234,
                                     st_mode=stat.S_IFREG | 0o600, st_nlink=1)
        snap = observation(True, True, False)
        with mock.patch.object(w, 'snapshot', return_value=snap), \
                mock.patch.object(w, 'read_rows', return_value=rows), \
                mock.patch.object(w, 'verify_main', side_effect=parent_failure), mock.patch.object(w, 'verify_access'), \
                mock.patch.object(w, 'verify_dependent', side_effect=failure), \
                mock.patch.object(w.os, 'stat', return_value=info), \
                mock.patch.object(w, 'safe_path', return_value=info), \
                mock.patch.object(w, 'fstab_check'), mock.patch.object(w, 'disk_proof'), \
                mock.patch.object(Path, 'glob', return_value=[]), \
                mock.patch.object(w, 'write_receipt'), mock.patch.object(w, 'command') as command:
            result = w.recovery_work(request, self.path.parent / 'receipt')
        return result, command

    def test_missing_loopfs_uses_only_existing_mount_configuration(self):
        result, command = self.dependent()
        command.assert_called_once_with(['/usr/bin/mount', '--', w.DEPENDENT], timeout=12)
        self.assertTrue(result['main'])
        self.assertTrue(result['dependent'])
        self.assertEqual(result['actions'][0]['target'], 'dependent')

    def test_dependent_postmount_failure_is_partial(self):
        result, command = self.dependent(failure=w.Unsafe('Incorrect dependent UUID'))
        self.assertTrue(result['main'])
        self.assertFalse(result['dependent'])
        self.assertIn('Incorrect', result['dependent_reason'])

    def test_incomplete_new_loop_metadata_is_retried_without_remount(self):
        with mock.patch.object(w.time, 'sleep') as sleep:
            result, command = self.dependent(failure=[w.MetadataPending('Pending UUID'), None])
        self.assertTrue(result['dependent'])
        command.assert_called_once_with(['/usr/bin/mount', '--', w.DEPENDENT], timeout=12)
        sleep.assert_called_once_with(0.2)

    def test_pending_loop_metadata_has_a_bounded_deadline(self):
        with mock.patch.object(w.time, 'monotonic', side_effect=[0, 3]), mock.patch.object(w.time, 'sleep') as sleep:
            result, command = self.dependent(failure=w.MetadataPending('Pending UUID'))
        self.assertFalse(result['dependent'])
        self.assertIn('dependent', result['blocked'])
        command.assert_called_once()
        sleep.assert_not_called()

    def test_known_loop_mismatch_is_not_retried(self):
        with mock.patch.object(w.time, 'sleep') as sleep:
            result, _ = self.dependent(failure=[w.Unsafe('UUID mismatch'), None])
        self.assertFalse(result['dependent'])
        sleep.assert_not_called()

    def test_no_dependent_operation_before_verified_parent(self):
        result, command = self.dependent(parent_failure=w.Unsafe('Main UUID incorrect'))
        command.assert_not_called()
        self.assertFalse(result['main'])


class RuntimeTests(Temp):
    def runtime(self, stop_at=240, stop_in_observation=False):
        clock = types.SimpleNamespace(now=0, stopped=False)
        class Stop:
            def is_set(self):
                return clock.stopped or clock.now >= stop_at
            def wait(self, duration):
                clock.now += max(duration, 0)
                return self.is_set()
        samples = []
        jobs = []
        sends = []
        def observe():
            samples.append(clock.now)
            if stop_in_observation:
                clock.stopped = True
            return observation()
        class Job:
            def __init__(self, argv, payload, timeout, **kw):
                self.start = clock.now
                self.proc = types.SimpleNamespace(poll=lambda: 0)
                jobs.append(self.start)
            def poll(self):
                return False if clock.now - self.start >= 35 else None
            def cancel(self): pass
            def close(self): pass
        class Mail(Job):
            def __init__(self, payload):
                self.event_id = payload['id']
                self.start = clock.now
                self.proc = types.SimpleNamespace(poll=lambda: 0)
                sends.append(self.start)
            def poll(self):
                return True if clock.now - self.start >= 20 else None
        with mock.patch.object(w, 'Monitor', return_value=self.monitor), \
                mock.patch.object(w, 'snapshot', side_effect=observe), \
                mock.patch.object(w, 'config_load', return_value={'automatic_recovery': True}), \
                mock.patch.object(w, 'clock_now', side_effect=lambda: clock.now), \
                mock.patch.object(w.time, 'monotonic', side_effect=lambda: clock.now), \
                mock.patch.object(w.time, 'time', side_effect=lambda: 1000 + clock.now), \
                mock.patch.object(w.time, 'sleep', side_effect=lambda t: setattr(clock, 'now', clock.now+t)), \
                mock.patch.object(w, 'STATE_DIR', self.path.parent), mock.patch.object(w, 'BOOT_GRACE', 0), \
                mock.patch.object(w, 'Worker', Job), mock.patch.object(w, 'Delivery', Mail):
            w.monitor_loop(Stop(), 42)
        return samples, jobs, sends

    def test_15_second_checks_continue_during_slow_recovery_and_smtp(self):
        samples, jobs, sends = self.runtime()
        # failed_result also obtains an immediate snapshot when the worker ends.
        for t in range(0, 240, 15):
            self.assertIn(t, samples)
        self.assertEqual(jobs, [75])
        self.assertEqual(sends, [110])
        self.assertEqual(self.monitor.state['pending'], [])

    def test_shutdown_during_observation_cannot_create_failure(self):
        samples, jobs, sends = self.runtime(stop_in_observation=True)
        self.assertEqual(samples, [0])
        self.assertEqual(jobs, [])
        self.assertEqual(sends, [])
        self.assertIsNone(self.monitor.state['incident'])

    def test_shutdown_retains_reserved_recovery_for_restart(self):
        self.runtime(stop_at=80)
        self.assertEqual(self.monitor.state['incident']['phase'], 'running')
        self.restart(now=90)
        self.assertEqual(len(self.monitor.state['incident']['attempts']), 1)
        # The durable receipt proves no mount intent was issued before shutdown.
        self.assertNotIn('main', self.monitor.state['incident']['blocked'])





class AdditionalOutcomeTests(Temp):
    def test_rearm_proof_cannot_override_an_intervening_unhealthy_sample(self):
        self.down()
        self.attempt(75)
        self.assertIsNone(self.monitor.work_request(True, 136))
        self.up(150)
        request = self.monitor.work_request(True, 170)
        self.monitor.sample(observation(), 180)
        self.monitor.work_result(request, outcome(True, True), 181)
        self.assertEqual(self.monitor.state['status'], 'down')
        self.assertEqual(len(self.monitor.state['incident']['attempts']), 1)

    def test_loopfs_loss_during_confirmation_cannot_report_complete_success(self):
        self.down()
        self.attempt(75, True, True, [{'target': 'main', 'stage': 'returned'}])
        self.monitor.sample(observation(True, True, False), 90)
        self.monitor.sample(observation(True, True, False), 105)
        self.assertIn('PARTIALLY', self.monitor.state['pending'][0]['subject'])

    def test_after_final_outcome_readonly_proofs_are_rate_limited(self):
        self.down()
        self.attempt(75)
        self.assertIsNone(self.monitor.work_request(True, 136))
        self.up(150)
        req = self.monitor.work_request(True, 170)
        self.monitor.work_result(req, outcome(), 171)
        self.assertIsNone(self.monitor.work_request(True, 172))
        self.assertIsNotNone(self.monitor.work_request(True, 230))

    def test_recovery_action_after_reboot_is_still_auto_not_natural(self):
        self.down()
        self.restart(5, 'new-boot')
        self.attempt(65, True, True, [{'target': 'main', 'stage': 'returned'}])
        self.up(80)
        self.assertEqual(self.monitor.state['pending'][0]['subject'], 'Storage AUTO-RECOVERED — Attempt 1')



class LiveMetadataSimulationTests(unittest.TestCase):
    def test_missing_udev_filesystem_fields_are_pending(self):
        for identity in ({}, {'ID_FS_UUID': w.DISK_UUID}, {'ID_FS_TYPE': 'ext4'}):
            with self.subTest(identity=identity), mock.patch.object(Path, 'is_dir', return_value=True), \
                    mock.patch.object(w, 'udev', return_value=identity), self.assertRaises(w.MetadataPending):
                w.block_checks('240:17', w.DISK_UUID)

    def test_known_wrong_udev_field_is_not_transient(self):
        for identity in ({'ID_FS_UUID': 'wrong'}, {'ID_FS_TYPE': 'xfs'}):
            with self.subTest(identity=identity), mock.patch.object(Path, 'is_dir', return_value=True), \
                    mock.patch.object(w, 'udev', return_value=identity):
                with self.assertRaises(w.Unsafe) as caught:
                    w.block_checks('240:17', w.DISK_UUID)
                self.assertNotIsInstance(caught.exception, w.MetadataPending)

    def test_runtime_snapshot_exact_mount_identity_and_errors(self):
        for rows, errors, healthy, unsafe in [
                (ROOT+STORAGE+DEP, '0', True, False),
                (ROOT+STORAGE+DEP, '1', False, True),
                (ROOT+STORAGE.replace('/dev/sdb1 rw', '/dev/sdb1 ro'), '0', False, True),
                (ROOT+STORAGE.replace('240:17', '8:33'), '0', False, True)]:
            with mock.patch.object(w, 'read_rows', return_value=w.parse_mounts(rows)), \
                    mock.patch.object(w, 'device_number', return_value='240:17'), \
                    mock.patch.object(w, 'block_checks', return_value='sdb1'), \
                    mock.patch.object(Path, 'read_text', return_value=errors), \
                    mock.patch.object(w, 'dependent_metadata'):
                result = w.snapshot()
            self.assertEqual(result['healthy'], healthy)
            self.assertEqual(result['unsafe'], unsafe)

    def test_block_uuid_filesystem_type_and_readonly_are_independent_guards(self):
        for identity, ro in [({'ID_FS_UUID': 'wrong', 'ID_FS_TYPE': 'ext4'}, '0'),
                             ({'ID_FS_UUID': w.DISK_UUID, 'ID_FS_TYPE': 'xfs'}, '0'),
                             ({'ID_FS_UUID': w.DISK_UUID, 'ID_FS_TYPE': 'ext4'}, '1')]:
            with mock.patch.object(Path, 'is_dir', return_value=True), \
                    mock.patch.object(w, 'udev', return_value=identity), \
                    mock.patch.object(Path, 'read_text', return_value=ro), self.assertRaises(w.Unsafe):
                w.block_checks('240:17', w.DISK_UUID)

    def test_dependent_image_inode_is_verified(self):
        main_dev = os.makedev(240, 17)
        device = types.SimpleNamespace(st_rdev=os.makedev(7, 8))
        image = types.SimpleNamespace(st_dev=main_dev, st_ino=100)
        for inode, succeeds in [(100, True), (101, False)]:
            loop = {'loopdevices': [{'name': '/dev/loop8', 'back-file': w.IMAGE,
                                     'back-ino': inode, 'back-maj:min': '240:17'}]}
            with mock.patch.object(w, 'read_rows', return_value=[]), \
                    mock.patch.object(w, 'dependent_metadata', return_value={'dev': '7:8'}), \
                    mock.patch.object(w, 'disk_proof', return_value=device), \
                    mock.patch.object(Path, 'resolve', return_value=Path('/dev/loop8')), \
                    mock.patch.object(Path, 'stat', return_value=image), \
                    mock.patch.object(w, 'command', return_value=json.dumps(loop)):
                if succeeds:
                    w.verify_dependent()
                else:
                    with self.assertRaisesRegex(w.Unsafe, 'inode'):
                        w.verify_dependent()


class LockTests(Temp):
    def test_surviving_operation_lock_blocks_new_recovery_worker(self):
        with (self.path.parent / 'monitor.lock').open('a') as monitor_lock, \
                (self.path.parent / 'recovery.lock').open('a') as operation_lock:
            fcntl.flock(operation_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with mock.patch.object(w, 'STATE_DIR', self.path.parent), \
                    mock.patch.object(w, 'recovery_work') as recover:
                with self.assertRaises(BlockingIOError), mock.patch.object(w, 'require_configuration'):
                    w.execute_recovery({'lock_fd': monitor_lock.fileno()})
            recover.assert_not_called()

    def test_both_locks_are_inherited_by_nested_commands(self):
        with mock.patch.object(w, 'WORKER_LOCK_FDS', (40, 41)), mock.patch.object(w, 'config_load', return_value={'automatic_recovery': True}), \
                mock.patch.object(w.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout='')) as run:
            w.command(['/usr/bin/mount', '--', w.MOUNT])
        self.assertEqual(run.call_args.kwargs['pass_fds'], (40, 41))

    def test_child_retains_singleton_lock_after_parent_closes_it(self):
        name = self.path.parent / 'monitor.lock'
        lock = name.open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        worker = w.Worker([sys.executable, '-I', '-c', 'import time; time.sleep(30)'],
                          {}, 2, self.path.parent, lock.fileno())
        try:
            lock.close()
            with name.open('a') as other:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            worker.cancel()
            worker.proc.wait(timeout=2)
            worker.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
