# SPDX-License-Identifier: MIT
"""Manual sleep preserves monitoring and waits for flushed writes, no real disks."""
from contextlib import ExitStack
import fcntl
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from gui_fixture import load

w = load('engine')
b = load('web_broker')
UUID = '11111111-1111-4111-8111-111111111111'


class BrokerSleep(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        config = b.s.default()
        config['disk']['uuid'] = UUID
        self.stack.enter_context(mock.patch.object(b, 'configuration', return_value=config))
        self.stack.enter_context(mock.patch.object(b.s, 'STATE_DIR', self.root))
        self.stack.enter_context(mock.patch.object(b.time, 'sleep'))
        self.service = dict(ActiveState='active', SubState='running', UnitFileState='enabled')
        def command(argv, *args, **kwargs):
            # Fail on ANY service mutation, including a transient stop/start.
            self.assertEqual(argv, ['/usr/bin/systemctl', 'show', b.cli.SERVICE,
                                    '--property=ActiveState,SubState,UnitFileState'])
            return '\n'.join(k + '=' + v for k, v in self.service.items())
        self.command = self.stack.enter_context(mock.patch.object(b, 'command', side_effect=command))
        self.worker = mock.Mock()
        self.worker.poll.return_value = True
        self.worker.output = io.BytesIO()
        self.create = self.stack.enter_context(mock.patch.object(b.w, 'Worker', return_value=self.worker))

    def reply(self, payload):
        self.worker.output = io.BytesIO(json.dumps(payload).encode())
        result = b.disk_operation(dict(action='sleep', uuid=UUID))
        self.assertEqual(json.loads((self.root / 'manual-operation.json').read_text()), result['last_operation'])
        return result

    def test_success_busy_and_unsupported_keep_monitor_on_or_off_and_enabled_state(self):
        for state in ('active', 'inactive'):
            for enabled in ('enabled', 'disabled'):
                for outcome in ('success', 'busy', 'unsupported'):
                    with self.subTest(state=state, enabled=enabled, outcome=outcome):
                        self.service.update(ActiveState=state, UnitFileState=enabled)
                        result = self.reply(dict(ok=outcome == 'success', result=outcome, message=outcome))
                        self.assertEqual(result['service'], self.service)
                        self.assertEqual(result['result'], outcome)
                        self.assertEqual(result['ok'], outcome == 'success')
                        self.assertIn('sleep request did not change it', result['message'])
                        self.assertNotIn('paused', result['message'])
        self.assertEqual(self.create.call_count, 12)

    def test_polling_then_completion_sends_one_request(self):
        self.worker.poll.side_effect = [None, None, True]
        self.reply(dict(ok=True, message='HDD standby confirmed.'))
        self.create.assert_called_once()
        self.assertEqual(self.create.call_args.args[1]['action'], 'sleep')
        self.worker.cancel.assert_called_once()
        self.worker.close.assert_called_once()

    def test_timeout_reports_uncertainty_without_stopping_or_retrying(self):
        self.worker.poll.return_value = False
        result = self.reply({})
        self.assertFalse(result['ok'])
        self.assertEqual(result['result'], 'uncertain')
        self.assertEqual(result['service']['ActiveState'], 'active')
        self.create.assert_called_once()
        self.worker.cancel.assert_called_once()

    def test_worker_start_failure_keeps_monitor_and_records_result(self):
        self.create.side_effect = OSError('synthetic spawn failure')
        result = self.reply({})
        self.assertFalse(result['ok'])
        self.assertEqual(result['service']['ActiveState'], 'active')
        self.worker.cancel.assert_not_called()

    def test_unreadable_or_invalid_worker_result_keeps_monitor(self):
        for payload in (None, [], {}, {'ok': 'yes', 'message': 'standby'}):
            with self.subTest(payload=payload):
                result = self.reply(payload)
                self.assertEqual(result['result'], 'uncertain')
                self.assertFalse(result['ok'])
        self.worker.output = io.BytesIO(b'not json')
        result = b.disk_operation(dict(action='sleep', uuid=UUID))
        self.assertEqual(result['result'], 'uncertain')

    def test_status_read_failure_does_not_relabel_confirmed_standby(self):
        self.command.side_effect = OSError('systemctl show unavailable')
        result = self.reply(dict(ok=True, message='HDD standby confirmed.'))
        self.assertTrue(result['ok'])
        self.assertEqual(result['service']['ActiveState'], 'unknown')
        self.assertIn('current status could not be read', result['message'])

    def test_receipt_failure_returns_known_result_without_retry(self):
        with mock.patch.object(b.w, 'atomic_write', side_effect=OSError('full state disk')):
            self.worker.output = io.BytesIO(b'{"ok":true,"message":"HDD standby confirmed."}')
            result = b.disk_operation(dict(action='sleep', uuid=UUID))
        self.assertTrue(result['ok'])
        self.assertIn('could not be saved', result['history_warning'])
        self.create.assert_called_once()

    def test_wrong_uuid_never_starts_worker_or_touches_service(self):
        with self.assertRaisesRegex(ValueError, 'Selected disk changed'):
            b.disk_operation(dict(action='sleep', uuid='different'))
        self.create.assert_not_called()
        self.command.assert_not_called()


class SleepLocks(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.ctx = w.usb_context(self.root)
        self.ctx.assert_internal_state = mock.Mock()
        self.ctx.WORKER_LOCK_FDS = ()
        self.pending = self.stack.enter_context(mock.patch.object(w.usb, 'load', return_value=None))
        self.enable = self.stack.enter_context(mock.patch.object(w.usb, 'ensure_enabled'))
        self.sleep = self.stack.enter_context(mock.patch.object(w.standby, 'sleep', return_value='standby'))

    def test_live_monitor_lock_allows_sleep_but_storage_lock_stays_exclusive(self):
        def standby(ctx, *, manual):
            self.assertTrue(manual)
            self.assertEqual(len(ctx.WORKER_LOCK_FDS), 1)
            with (self.root / 'recovery.lock').open('a') as other:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return 'standby'
        self.sleep.side_effect = standby
        with (self.root / 'monitor.lock').open('a') as monitor:
            fcntl.flock(monitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(w.controls.perform(self.ctx, 'sleep'), 'standby')
            with (self.root / 'monitor.lock').open('a') as second:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(self.ctx.WORKER_LOCK_FDS, ())
        self.enable.assert_not_called()

    def test_recovery_in_progress_prevents_overlapping_sleep(self):
        with (self.root / 'recovery.lock').open('a') as operation:
            fcntl.flock(operation, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(w.Unsafe, 'Another storage operation') as error:
                w.controls.perform(self.ctx, 'sleep')
        self.assertEqual(w.standby.error_result(error.exception), 'busy')
        self.sleep.assert_not_called()

    def test_pending_usb_cleanup_refuses_without_attempting_reconnect(self):
        self.pending.return_value = {'phase': 'enabling'}
        with self.assertRaisesRegex(w.Unsafe, 'cleanup must finish'):
            w.controls.perform(self.ctx, 'sleep')
        self.sleep.assert_not_called()
        self.enable.assert_not_called()
        self.assertEqual(self.ctx.WORKER_LOCK_FDS, ())

    def test_refusal_releases_lock_and_restores_inherited_descriptors(self):
        self.ctx.WORKER_LOCK_FDS = (123,)
        self.sleep.side_effect = w.Unsafe('busy')
        with self.assertRaises(w.Unsafe):
            w.controls.perform(self.ctx, 'sleep')
        self.assertEqual(self.ctx.WORKER_LOCK_FDS, (123,))
        with (self.root / 'recovery.lock').open('a') as operation:
            fcntl.flock(operation, fcntl.LOCK_EX | fcntl.LOCK_NB)


class ManualStandby(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (root / 'dev').write_text('8:0')
        (root / 'node').touch()
        self.binding = dict(sys=str(root), path=str(root / 'node'))
        self.ctx = w.usb_context(root)
        self.ctx.WORKER_LOCK_FDS = ()
        self.ctx.device_number = lambda _: '8:0'
        self.ctx.snapshot = mock.Mock(return_value={'healthy': True})
        self.calls = []
        self.now = 0
        self.ctx.command = mock.Mock(side_effect=lambda argv, **kwargs: self.calls.append(argv))
        def advance(seconds):
            self.calls.append(['wait', seconds])
            self.now += seconds
        self.stack.enter_context(mock.patch.object(w.standby.time, 'monotonic', side_effect=lambda: self.now))
        self.stack.enter_context(mock.patch.object(w.standby.time, 'sleep', side_effect=advance))
        self.identity = self.stack.enter_context(mock.patch.object(w.standby, 'identity', return_value=self.binding))
        self.stack.enter_context(mock.patch.object(w.standby, 'status', return_value={'sleeping': False}))
        self.stack.enter_context(mock.patch.object(w.standby, 'storage_kind', return_value='mechanical'))
        self.users = self.stack.enter_context(mock.patch.object(w.standby, 'users'))
        self.topology = self.stack.enter_context(mock.patch.object(w.standby.io, 'topology', return_value=dict(targets=['/mnt/test/image','/mnt/test'],devices=[],loops={},mounts=[])))
        self.stack.enter_context(mock.patch.object(w.standby.io, 'swap_guard'))
        self.stack.enter_context(mock.patch.object(w.standby.io, 'capture', return_value={'containers':{},'available':False}))
        self.stack.enter_context(mock.patch.object(w.standby, 'filesystems', return_value=([], ['/mnt/test', '/mnt/test/image'])))
        self.fuser = self.stack.enter_context(mock.patch.object(w.standby.subprocess, 'run',
            return_value=SimpleNamespace(returncode=1, stdout='', stderr='')))
        self.activity = self.stack.enter_context(mock.patch.object(w.standby, 'activity', return_value=([0], 0)))
        self.power = self.stack.enter_context(mock.patch.object(w.standby, 'power_command', return_value='drive state is: standby'))
        self.save = self.stack.enter_context(mock.patch.object(w.standby, 'save'))

    def sleep_now(self):
        return w.standby.sleep(self.ctx, manual=True)

    def test_flushes_child_then_parent_before_quiet_window_and_normal_standby(self):
        self.assertIn('standby confirmed', self.sleep_now())
        self.assertEqual(self.calls[:2], [['/usr/bin/sync', '-f', '--', '/mnt/test/image'],
                                         ['/usr/bin/sync', '-f', '--', '/mnt/test']])
        self.assertEqual(self.now, 3)
        self.assertEqual([c.args[1] for c in self.power.call_args_list], ['-y', '-C'])
        self.assertTrue(self.save.call_args.kwargs['sleeping'])

    def test_background_writes_can_settle_without_refusing_request(self):
        self.activity.side_effect = lambda _: ([int(min(self.now, 2))], 0)
        self.sleep_now()
        self.assertEqual(self.now, 5)
        self.assertEqual(self.power.call_count, 2)
        self.save.assert_called_once()

    def test_inflight_io_can_finish_before_quiet_window(self):
        self.activity.side_effect = lambda _: ([1], int(self.now < 2))
        self.sleep_now()
        self.assertEqual(self.now, 5)

    def test_continuing_writes_are_bounded_and_never_send_standby(self):
        self.activity.side_effect = lambda _: ([int(self.now)], 0)
        with self.assertRaisesRegex(w.Unsafe, 'did not settle within 15 seconds') as error:
            self.sleep_now()
        self.assertEqual(w.standby.error_result(error.exception), 'busy')
        self.assertEqual(self.now, 15)
        self.power.assert_not_called()
        self.save.assert_not_called()

    def test_idle_handles_and_running_containers_do_not_block_standby(self):
        self.users.side_effect = AssertionError('Standby must not scan idle consumers')
        self.fuser.side_effect = AssertionError('Standby must not call fuser')
        self.sleep_now()
        self.users.assert_not_called()
        self.fuser.assert_not_called()
        self.power.assert_called()

    def test_flush_failure_never_sends_standby(self):
        self.ctx.command.side_effect = w.Unsafe('sync failed')
        with self.assertRaisesRegex(w.Unsafe, 'sync failed'):
            self.sleep_now()
        self.power.assert_not_called()

    def test_changed_disk_or_lost_mount_never_sends_standby(self):
        for changed in ('identity', 'mount'):
            with self.subTest(changed=changed):
                self.identity.side_effect = [self.binding, {}] if changed == 'identity' else None
                self.ctx.snapshot.side_effect = [{'healthy': True}, {'healthy': False}] if changed == 'mount' else None
                with self.assertRaises(w.Unsafe):
                    self.sleep_now()
                self.power.assert_not_called()

    def test_new_activity_during_power_command_does_not_claim_sleep(self):
        def power(ctx, flag, path):
            self.activity.return_value = ([1], 0)
            return 'drive state is: standby'
        self.power.side_effect = power
        with self.assertRaisesRegex(w.Unsafe, 'New disk activity'):
            self.sleep_now()
        self.save.assert_not_called()

    def test_bridge_must_confirm_standby(self):
        self.power.return_value = 'drive state is: active/idle'
        with self.assertRaisesRegex(w.Unsafe, 'did not confirm standby') as error:
            self.sleep_now()
        self.assertEqual(w.standby.error_result(error.exception), 'unverified')
        self.save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
