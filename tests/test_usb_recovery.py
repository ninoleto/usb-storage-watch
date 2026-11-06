# SPDX-License-Identifier: MIT
#!/usr/bin/python3
"""Offline sysfs recovery simulations. All port writes use fake I/O or /tmp files."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
import uuid
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('usb_test_watch', HERE.parent / 'src/usb_storage_watch/engine.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
_fs = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('fixtures.py'))
fixture = importlib.util.module_from_spec(_fs)
_fs.loader.exec_module(fixture)
fixture.configure(w)

u = w.usb


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []
    def read(self):
        return self.now
    def sleep(self, value):
        self.sleeps.append(value)
        self.now += value


def observation(healthy=False):
    return {'healthy': healthy, 'detected': healthy, 'dependent': healthy, 'unsafe': False,
            'detail': 'Simulated health', 'dependent_detail': 'Simulated dependent loop',
            'usb_binding_verified': healthy, 'usb_sources': ['/dev/sdb', '/dev/sdb1'],
            'usb_binding': binding(),
            'mounts': [{'target': w.MOUNT, 'dev': '240:17', 'source': '/dev/sdb1'}] if healthy else []}


def binding():
    ctx = w.usb_context()
    ctx.boot_id = lambda: 'simulated-boot'
    return u.binding_signature(ctx) | {'main_dev': '240:17', 'sources': ['/dev/sdb', '/dev/sdb1'],
                                      'observed_at': '2000-01-01T00:00:00+00:00'}


def result(main=False):
    return {'main': main, 'dependent': main, 'detected': main, 'actions': [], 'blocked': [],
            'reason': 'Simulated outcome', 'dependent_reason': 'Simulated dependent loop', 'mounts': []}


class Temp(unittest.TestCase):
    def setUp(self):
        fixture.configure(w)
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp', prefix='usb-test-')
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.ctx = w.usb_context(self.directory)
        self.ctx.config_load = lambda: {'usb_reset_enabled': True}
        self.ctx.log = mock.Mock()
        self.ctx.boot_id = lambda: 'simulated-boot'
        self.ctx.timestamp = lambda: '2000-01-01T00:00:00+00:00'
        self.clock = Clock()
        self.request = {'incident': str(uuid.uuid4()), 'number': 1, 'allow_usb': True, 'usb_resets': 0,
                        'known_devs': ['240:17'], 'known_sources': ['/dev/sdb', '/dev/sdb1'],
                        'known_binding': binding()}
        self.actions = []
        self.value = '0'
        self.enable_failures = 0
        self.disable_failure = None

    def fake_io(self, ctx, action, incident):
        record = u.load(ctx)
        self.assertEqual(record['incident'], incident)
        self.assertEqual(record['reset_count'], 1)
        self.assertEqual(record['port'], u.CANONICAL)
        self.actions.append(action)
        if action == 'disable':
            self.assertTrue(record['guard_ready'])
            self.assertFalse(record['disable_issued'])
            u.update(ctx, disable_issued=True, phase='disabling', disable_started_at=ctx.timestamp())
            self.value = '1'
            u.update(ctx, disable_confirmed_at=ctx.timestamp())
            if self.disable_failure:
                raise self.disable_failure
        else:
            if self.enable_failures:
                self.enable_failures -= 1
                raise w.Unsafe('Simulated enable failure')
            self.value = '0'
            u.update(ctx, phase='enabled', enabled_at=ctx.timestamp(), reason='Enabled and verified.')

    @contextlib.contextmanager
    def simulation(self, appear_after=0, guardian_error=None):
        parent = self
        class Guard:
            def __init__(self, ctx, incident):
                self.ctx = ctx
                if guardian_error:
                    raise guardian_error
                u.update(ctx, guard_ready=True)
            def close(self):
                parent.guard_closed = True
        self.guard_closed = False
        start_probe = None
        def probe(ctx):
            nonlocal start_probe
            if start_probe is None:
                start_probe = parent.clock.now
            return appear_after is not None and parent.clock.now - start_probe >= appear_after
        with mock.patch.object(u, 'select_current', side_effect=lambda ctx, req: req), \
                mock.patch.object(u, 'HOST_VERIFIED', True), \
                mock.patch.object(u, 'require_absent_and_isolated') as isolation, \
                mock.patch.object(u, 'Guardian', Guard), \
                mock.patch.object(u, 'bounded_io', side_effect=self.fake_io), \
                mock.patch.object(u, 'ready', side_effect=probe), \
                mock.patch.object(u.time, 'monotonic', side_effect=self.clock.read), \
                mock.patch.object(u.time, 'sleep', side_effect=self.clock.sleep):
            yield isolation


class EnumerationTests(Temp):
    def test_immediate_detection_does_not_sleep_twenty_seconds(self):
        with self.simulation(0):
            answer = u.cycle(self.ctx, self.request)
        self.assertTrue(answer['ready'])
        self.assertEqual(answer['enumeration_seconds'], 0)
        self.assertEqual(self.clock.now, 1)
        self.assertEqual(self.actions, ['disable', 'enable'])
        self.assertEqual(self.value, '0')

    def test_successful_early_detection_polls_every_quarter_second(self):
        with self.simulation(2.25):
            answer = u.cycle(self.ctx, self.request)
        self.assertTrue(answer['ready'])
        self.assertEqual(answer['enumeration_seconds'], 2.25)
        self.assertEqual(self.clock.now, 3.25)
        self.assertEqual(self.clock.sleeps, [1.0]+[0.25]*9)

    def test_full_twenty_second_timeout_does_not_extend(self):
        with self.simulation(None):
            answer = u.cycle(self.ctx, self.request)
        self.assertFalse(answer['ready'])
        self.assertEqual(answer['enumeration_seconds'], 20)
        self.assertEqual(self.clock.now, 21)
        self.assertEqual(u.load(self.ctx)['enumeration_seconds'], 20)
        self.assertEqual(u.load(self.ctx)['phase'], 'enabled')

    def test_device_at_deadline_detected_but_after_deadline_not_waited_for(self):
        for appears, expected in [(20, True), (20.25, False)]:
            clock = Clock()
            okay, elapsed = u.poll_ready(self.ctx, probe=lambda: clock.now >= appears,
                                         clock=clock.read, sleep=clock.sleep)
            self.assertEqual(okay, expected)
            self.assertEqual(elapsed, 20)

    def test_poll_does_not_probe_again_after_scheduling_overshoots_deadline(self):
        clock = Clock()
        probe = mock.Mock(return_value=False)
        def delayed_sleep(value):
            clock.now = 21
        detected, elapsed = u.poll_ready(self.ctx, probe=probe, clock=clock.read, sleep=delayed_sleep)
        self.assertFalse(detected)
        self.assertEqual(elapsed, 21)
        probe.assert_called_once()

    def test_unsafe_return_stops_polling_immediately(self):
        def bad():
            raise w.Unsafe('Wrong filesystem/USB identity')
        with self.assertRaises(w.Unsafe):
            u.poll_ready(self.ctx, probe=bad, clock=self.clock.read, sleep=self.clock.sleep)
        self.assertEqual(self.clock.sleeps, [])


class ResetSafetyTests(Temp):
    def test_qualified_policy_default_can_be_disabled_by_operator(self):
        self.assertTrue(u.HOST_VERIFIED)
        self.assertFalse(w.settings.default()['usb']['enabled'])
        self.request['allow_usb'] = False
        with mock.patch.object(u, 'bounded_io') as io:
            answer = u.cycle(self.ctx, self.request)
        self.assertIn('disabled by recovery configuration', answer['reason'])
        self.assertIsNone(u.load(self.ctx))
        io.assert_not_called()

    def test_unqualified_host_cannot_write_or_reserve(self):
        with mock.patch.object(u, 'HOST_VERIFIED', False), mock.patch.object(u, 'bounded_io') as io:
            answer = u.cycle(self.ctx, self.request)
        self.assertFalse(answer['ready'])
        self.assertEqual(answer['reset_count'], 0)
        io.assert_not_called()
        self.assertIsNone(u.load(self.ctx))

    def test_isolation_failure_skips_reset(self):
        with self.simulation() as isolation:
            isolation.side_effect = w.Unsafe('Other device active')
            answer = u.cycle(self.ctx, self.request)
        self.assertIn('safely skipped', answer['reason'])
        self.assertIn('Other device', answer['reason'])
        self.assertEqual(self.actions, [])
        self.assertIsNone(u.load(self.ctx))

    def test_ledger_fsync_failure_prevents_any_write(self):
        with self.simulation(), mock.patch.object(self.ctx, 'atomic_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                u.cycle(self.ctx, self.request)
        self.assertEqual(self.actions, [])

    def test_duplicate_reset_same_outage_refused_even_after_success(self):
        with self.simulation():
            u.cycle(self.ctx, self.request)
            with self.assertRaises(w.Unsafe):
                u.cycle(self.ctx, self.request)
        self.assertEqual(self.actions.count('disable'), 1)
        self.assertEqual(u.load(self.ctx)['reset_count'], 1)

    def test_second_attempt_never_resets(self):
        self.request['number'] = 2
        with self.simulation():
            answer = u.cycle(self.ctx, self.request)
        self.assertIn('budget', answer['reason'])
        self.assertEqual(self.actions, [])

    def test_preconsumed_reset_never_resets(self):
        self.request['usb_resets'] = 1
        with self.simulation():
            u.cycle(self.ctx, self.request)
        self.assertEqual(self.actions, [])

    def test_failed_disable_still_attempts_enable(self):
        self.disable_failure = w.Unsafe('Simulated disable error')
        with self.simulation(), self.assertRaises(w.Unsafe):
            u.cycle(self.ctx, self.request)
        self.assertEqual(self.actions, ['disable', 'enable'])
        self.assertEqual(self.value, '0')
        self.assertTrue(self.guard_closed)

    def test_failure_preserves_specific_reason_without_generic_unsafe(self):
        self.disable_failure=w.Unsafe('Selected device changed before the write')
        with self.simulation(),self.assertRaisesRegex(w.Unsafe,'Selected device changed before the write') as raised:
            u.cycle(self.ctx,self.request)
        self.assertNotIn('Unsafe',str(raised.exception))

    def test_completed_write_readback_error_verifies_return_after_enable(self):
        original=self.fake_io
        def io(ctx,action,incident):
            original(ctx,action,incident)
            if action=='disable':
                u.update(ctx,disable_written_at=ctx.timestamp())
                raise OSError('readback temporarily unavailable')
        with self.simulation(),mock.patch.object(u,'bounded_io',side_effect=io):
            result=u.cycle(self.ctx,self.request)
        self.assertTrue(result['ready']);self.assertEqual(self.actions,['disable','enable'])
        self.assertIn('readback temporarily unavailable',result['reason'])

    def test_timeout_still_attempts_enable(self):
        self.disable_failure = TimeoutError('Simulated hung disable')
        with self.simulation(), self.assertRaises(w.Unsafe):
            u.cycle(self.ctx, self.request)
        self.assertEqual(self.value, '0')
        self.assertEqual(self.actions.count('disable'), 1)

    def test_signal_style_interruption_still_enables(self):
        self.disable_failure = KeyboardInterrupt()
        with self.simulation(), self.assertRaises(w.Unsafe):
            u.cycle(self.ctx, self.request)
        self.assertEqual(self.value, '0')

    def test_failed_reenable_retains_obligation_and_does_not_poll_or_mount(self):
        self.enable_failures = 2
        with self.simulation(), mock.patch.object(u, 'poll_ready') as poll:
            with self.assertRaisesRegex(w.Unsafe, 're-enable failed'):
                u.cycle(self.ctx, self.request)
        self.assertEqual(self.actions, ['disable', 'enable', 'enable'])
        self.assertEqual(self.value, '1')
        self.assertEqual(u.load(self.ctx)['phase'], 'enable_failed')
        poll.assert_not_called()
        # A subsequent cleanup may retry enable, never disable.
        with mock.patch.object(u, 'bounded_io', side_effect=self.fake_io):
            self.assertTrue(u.ensure_enabled(self.ctx))
        self.assertEqual(self.actions.count('disable'), 1)
        self.assertEqual(self.value, '0')

    def test_guard_failure_never_disables_but_performs_enable_cleanup(self):
        with self.simulation(guardian_error=w.Unsafe('Guardian failed')), self.assertRaises(w.Unsafe):
            u.cycle(self.ctx, self.request)
        self.assertEqual(self.actions, ['enable'])
        self.assertEqual(u.load(self.ctx)['phase'], 'enabled')

    def test_cleanup_without_owned_intent_never_writes(self):
        with mock.patch.object(u, 'bounded_io') as io:
            self.assertTrue(u.ensure_enabled(self.ctx))
        io.assert_not_called()

    def test_corrupt_or_wrong_port_ledger_never_writes(self):
        u.reserve(self.ctx, self.request)
        record = u.load(self.ctx)
        record['port'] = '/sys/bus/usb/devices/usb8/authorized'
        u.ledger_path(self.ctx).write_text(json.dumps(record))
        with mock.patch.object(u, 'bounded_io') as io, self.assertRaises(w.Unsafe):
            u.ensure_enabled(self.ctx)
        io.assert_not_called()


class RestartTests(Temp):
    def monitor_down(self):
        path = self.directory / 'state.json'
        monitor = w.Monitor(path, now=0, boot='simulated-boot', application_tracking=False)
        monitor.sample(observation(True), 0)
        monitor.sample(observation(True), 15)
        monitor.sample(observation(False), 30)
        monitor.sample(observation(False), 45)
        req = monitor.work_request(True, 105, usb_enabled=True)
        self.request.update(req)
        return monitor, path

    def test_restart_during_reset_enables_and_never_repeats_sequence(self):
        monitor, path = self.monitor_down()
        u.reserve(self.ctx, self.request)
        u.update(self.ctx, phase='disabling', disable_issued=True, guard_ready=True)
        self.value = '1'
        (self.directory / 'recovery-receipt.json').write_text(json.dumps(
            {'incident': self.request['incident'], 'number': 1, 'complete': False, 'result': {'actions': []}}))
        with mock.patch.object(u, 'bounded_io', side_effect=self.fake_io):
            self.assertTrue(u.ensure_enabled(self.ctx))  # ExecStartPre / watchdog cleanup.
        restarted = w.Monitor(path, now=110, boot='simulated-boot', application_tracking=False)
        self.assertEqual(restarted.state['incident']['usb_resets'], 1)
        self.assertIsNone(restarted.work_request(True, 169, usb_enabled=True))
        req2 = restarted.work_request(True, 170, usb_enabled=True)
        self.assertIsNone(req2)
        self.assertEqual(self.actions, ['enable'])
        self.assertEqual(self.value, '0')

    def test_completed_usb_proof_survives_restart_before_mount_receipt(self):
        monitor, path = self.monitor_down()
        with self.simulation(0):
            u.cycle(self.ctx, self.request)
        (self.directory / 'recovery-receipt.json').write_text(json.dumps(
            {'incident': self.request['incident'], 'number': 1, 'complete': False, 'result': {'actions': []}}))
        restarted = w.Monitor(path, now=110, boot='simulated-boot', application_tracking=False)
        self.assertIsNone(restarted.work_request(True, 170, usb_enabled=True))
        self.assertIn('FAILED', restarted.state['pending'][0]['subject'])
        self.assertEqual(restarted.state['incident']['usb_resets'], 1)
        self.assertEqual(self.actions.count('disable'), 1)

    def test_uncertain_mount_intent_after_usb_still_blocks_mount_replay(self):
        monitor, path = self.monitor_down()
        u.reserve(self.ctx, self.request)
        (self.directory / 'recovery-receipt.json').write_text(json.dumps(
            {'incident': self.request['incident'], 'number': 1, 'complete': False,
             'result': {'actions': [{'target': 'main', 'stage': 'intent'}]}}))
        restarted = w.Monitor(path, now=110, boot='simulated-boot', application_tracking=False)
        self.assertIn('main', restarted.state['incident']['blocked'])
        self.assertEqual(restarted.state['incident']['usb_resets'], 1)

    def test_late_return_after_final_failure_only_rearms_with_readonly_proof(self):
        monitor, path = self.monitor_down()
        with self.simulation(None):
            u.cycle(self.ctx, self.request)
        monitor.work_result(self.request, result(), now=126)
        self.assertEqual(monitor.state['incident']['phase'], 'done')
        monitor.sample(observation(True), 145)
        monitor.sample(observation(True), 160)
        proof = monitor.work_request(True, 186, usb_enabled=True)
        self.assertTrue(proof['check_only'])
        self.assertFalse(proof['allow_mount'])
        self.assertFalse(proof['allow_usb'])
        monitor.work_result(proof, result(True), now=187)
        self.assertEqual(len(monitor.state['pending']), 1)
        self.assertIn('FAILED', monitor.state['pending'][0]['subject'])
        self.assertEqual(self.actions.count('disable'), 1)

    def test_failed_sequence_includes_reset_and_enable_state_in_one_email(self):
        monitor, path = self.monitor_down()
        with self.simulation(None):
            u.cycle(self.ctx, self.request)
        monitor.work_result(self.request, result(), now=126)
        req2 = monitor.work_request(True, 186)
        self.assertIsNone(req2)
        event = monitor.state['pending'][0]
        self.assertIn('RECOVERY FAILED', event['subject'])
        self.assertIn('USB resets: 1', event['detail'])
        self.assertIn('enabled_at', event['detail'])
        for now in (300, 600, 900):
            self.assertIsNone(monitor.work_request(True, now, usb_enabled=True))
        self.assertEqual(len(monitor.state['pending']), 1)


class GuardianTests(Temp):
    def test_parent_death_lifeline_eof_triggers_enable(self):
        u.reserve(self.ctx, self.request)
        read_fd, write_fd = os.pipe()
        os.close(write_fd)  # Simulates SIGKILL/exit of the parent worker.
        with mock.patch.object(u, 'ensure_enabled', return_value=True) as enable:
            u.guard_worker(self.ctx, {'incident': self.request['incident'], 'lifeline': read_fd})
        enable.assert_called_once_with(self.ctx)
        self.assertTrue(u.load(self.ctx)['guard_ready'])

    def test_guard_deadline_triggers_enable_without_parent_cooperation(self):
        u.reserve(self.ctx, self.request)
        read_fd, write_fd = os.pipe()
        def select_step(*args):
            self.clock.sleep(args[3])
            return [], [], []
        try:
            with mock.patch.object(u.time, 'monotonic', side_effect=self.clock.read), \
                    mock.patch.object(u.select, 'select', side_effect=select_step), \
                    mock.patch.object(u, 'ensure_enabled', return_value=True) as enable:
                u.guard_worker(self.ctx, {'incident': self.request['incident'], 'lifeline': read_fd})
            enable.assert_called_once_with(self.ctx)
            self.assertAlmostEqual(self.clock.now, u.GUARD_SECONDS)
        finally:
            os.close(write_fd)

    def test_cleanup_hooks_are_enable_only_on_existing_service(self):
        source = (HERE.parent / 'packaging/usb-storage-watch.service').read_text()
        self.assertIn('ExecStartPre=-/usr/bin/python3 -I /usr/lib/usb-storage-watch/engine.py _usb-cleanup', source)
        self.assertIn('ExecStopPost=-/usr/bin/python3 -I /usr/lib/usb-storage-watch/engine.py _usb-cleanup', source)
        self.assertIn('KillMode=mixed', source)
        self.assertNotIn('uhubctl', source)


class RawPortSimulationTests(Temp):
    def setUp(self):
        super().setUp()
        self.port = self.directory / 'simulated-port'
        self.port.mkdir()
        (self.port / 'disable').write_text('0\n')
        (self.port / 'state').write_text('not attached\n')
        u.reserve(self.ctx, self.request)
        u.update(self.ctx, guard_ready=True)

    @contextlib.contextmanager
    def raw_simulation(self):
        with mock.patch.object(u, 'PORT', self.port), mock.patch.object(u, 'HOST_VERIFIED', True), \
                mock.patch.object(u, 'port_identity'), mock.patch.object(u, 'usb_present', return_value=False), \
                mock.patch.object(u, 'require_absent_and_isolated'), mock.patch.object(u, 'configure'):
            yield

    def test_single_write_one_then_zero_with_readback_and_duplicate_refused(self):
        with self.raw_simulation():
            u.io_worker(self.ctx, {'action': 'disable', 'incident': self.request['incident']})
            self.assertEqual((self.port/'disable').read_text(), '1\n')
            with self.assertRaises(w.Unsafe):
                u.io_worker(self.ctx, {'action': 'disable', 'incident': self.request['incident']})
            u.io_worker(self.ctx, {'action': 'enable', 'incident': self.request['incident']})
        self.assertEqual((self.port/'disable').read_text(), '0\n')
        self.assertEqual(u.load(self.ctx)['phase'], 'enabled')

    def test_logical_disable_with_unchanged_power_bit_is_not_failure(self):
        original=Path.read_text
        def read(path,*args,**kwargs):
            return '0\n' if path==self.port/'disable' else original(path,*args,**kwargs)
        with self.raw_simulation(),mock.patch.object(Path,'read_text',read):
            u.io_worker(self.ctx,dict(action='disable',incident=self.request['incident']))
            self.assertTrue(u.load(self.ctx)['disable_written_at'])
            self.assertFalse(u.load(self.ctx)['power_off_reported'])
            u.io_worker(self.ctx,dict(action='enable',incident=self.request['incident']))
        self.assertEqual(u.load(self.ctx)['phase'],'enabled')

    def test_cleanup_after_arm_prevents_late_disable(self):
        with self.raw_simulation():
            u.io_worker(self.ctx, {'action': 'enable', 'incident': self.request['incident']})
            with self.assertRaises(w.Unsafe):
                u.io_worker(self.ctx, {'action': 'disable', 'incident': self.request['incident']})
        self.assertEqual((self.port/'disable').read_text(), '0\n')

    def test_overlapping_sysfs_writers_are_refused(self):
        import fcntl
        with (self.directory/'usb-io.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.raw_simulation(), self.assertRaises(BlockingIOError):
                u.io_worker(self.ctx, {'action': 'disable', 'incident': self.request['incident']})
        self.assertEqual((self.port/'disable').read_text(), '0\n')

    def test_guard_not_ready_prevents_raw_disable(self):
        u.update(self.ctx, guard_ready=False)
        with self.raw_simulation(), self.assertRaises(w.Unsafe):
            u.io_worker(self.ctx, {'action': 'disable', 'incident': self.request['incident']})
        self.assertEqual((self.port/'disable').read_text(), '0\n')

    def test_failed_enable_readback_does_not_mark_enabled(self):
        u.update(self.ctx, phase='disabling', disable_issued=True)
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path == self.port/'disable':
                return '1\n'  # Simulate hardware ignoring enable.
            return original(path, *args, **kwargs)
        with self.raw_simulation(), mock.patch.object(Path, 'read_text', read), self.assertRaises(w.Unsafe):
            u.io_worker(self.ctx, {'action': 'enable', 'incident': self.request['incident']})
        self.assertNotEqual(u.load(self.ctx)['phase'], 'enabled')

    def test_device_return_during_durable_intent_cancels_disable(self):
        with self.raw_simulation(), mock.patch.object(u, 'require_absent_and_isolated',
                side_effect=[None, w.Unsafe('Device returned during fsync')]):
            with self.assertRaisesRegex(w.Unsafe, 'returned'):
                u.io_worker(self.ctx, {'action': 'disable', 'incident': self.request['incident']})
        self.assertEqual((self.port/'disable').read_text(), '0\n')
        self.assertTrue(u.load(self.ctx)['disable_issued'])  # Budget remains consumed.

    def test_device_return_immediately_before_write_cancels_disable(self):
        with self.raw_simulation(), mock.patch.object(u, 'usb_present', return_value=True):
            with self.assertRaisesRegex(w.Unsafe, 'returned before'):
                u.io_worker(self.ctx, {'action': 'disable', 'incident': self.request['incident']})
        self.assertEqual((self.port/'disable').read_text(), '0\n')



class IsolationTests(Temp):
    def setUp(self):
        super().setUp()
        for name in ('port', 'devices', 'block', 'proc', 'uuid'):
            (self.directory/name).mkdir()
        (self.directory/'port/state').write_text('not attached\n')
        (self.directory/'port/disable').write_text('0\n')
        (self.directory/'proc/swaps').write_text('Filename Type Size Used Priority\n')
        proc = self.directory/'proc/10'
        proc.mkdir()
        (proc/'fd').mkdir()
        (proc/'mountinfo').write_text('1 0 240:2 / / rw - ext4 /dev/sda2 rw\n')
        (proc/'maps').write_text('')
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for attr, path in [('PORT','port'), ('DEVICE','absent-device'), ('USB_DEVICES','devices'),
                           ('SYS_BLOCK','block'), ('PROC','proc'), ('UUID_DIR','uuid')]:
            self.stack.enter_context(mock.patch.object(u, attr, self.directory/path))
        self.stack.enter_context(mock.patch.object(u, 'port_identity'))

    def test_present_expected_unmounted_disk_requires_live_binding(self):
        self.request['allow_present'] = True
        self.ctx.device_number = lambda _: '240:17'
        self.ctx.read_rows = lambda: []
        self.ctx.mount_available = mock.Mock()
        with mock.patch.object(u, 'usb_present', return_value=True), \
                mock.patch.object(u, 'healthy_binding', return_value=binding()) as live:
            u.require_absent_and_isolated(self.ctx, self.request)
        live.assert_called_once_with(self.ctx, '240:17')
        self.ctx.mount_available.assert_called_once()

    def test_present_wrong_disk_never_qualifies_for_cycle(self):
        self.request['allow_present'] = True
        self.ctx.device_number = lambda _: '240:17'
        with mock.patch.object(u, 'discover', return_value=w.SETTINGS['usb']['profile']), \
                mock.patch.object(u, 'usb_present', return_value=True), \
                mock.patch.object(u, 'healthy_binding', side_effect=w.Unsafe('wrong serial')):
            answer = u.cycle(self.ctx, self.request)
        self.assertIn('wrong serial', answer['reason'])
        self.assertIsNone(u.load(self.ctx))

    def test_absent_unmounted_port_passes_runtime_checks(self):
        u.require_absent_and_isolated(self.ctx, self.request)

    def test_qualified_host_cycle_requires_complete_runtime_absence_proof(self):
        self.assertTrue(u.HOST_VERIFIED)
        check = u.require_absent_and_isolated
        with self.simulation(7) as isolation:
            isolation.side_effect = check
            answer = u.cycle(self.ctx, self.request)
        self.assertTrue(answer['ready'])
        self.assertEqual(answer['enumeration_seconds'], 7)
        self.assertEqual(self.actions, ['disable', 'enable'])

    def test_incomplete_or_wrong_saved_identity_skips_qualified_reset(self):
        original = dict(self.request['known_binding'])
        for key, bad in [('uuid', 'wrong'), ('fs', 'xfs'), ('disk_serial', 'wrong'),
                         ('port', '/sys/bus/usb/devices/8-0:1.0/usb8-port1'),
                         ('controller', 'other'), ('firmware', 'other'), ('vid', 'fffe'),
                         ('pid', '0063'), ('main_dev', '8:99'), ('boot', 'previous-boot')]:
            with self.subTest(key=key):
                self.request['known_binding'] = original | {key: bad}
                answer = u.cycle(self.ctx, self.request)
                self.assertIn('safely skipped', answer['reason'])
                self.assertIsNone(u.load(self.ctx))
        self.request['known_binding'] = None
        with self.assertRaisesRegex(w.Unsafe, 'Prior healthy'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_present_or_unrecognized_port_state_never_resets(self):
        for state in ('configured', 'suspended', 'reconnecting', 'not-attached', 'UNKNOWN'):
            (self.directory/'port/state').write_text(state)
            with self.subTest(state=state), self.assertRaisesRegex(w.Unsafe, 'entirely absent'):
                u.require_absent_and_isolated(self.ctx, self.request)

    def test_preexisting_disabled_port_does_not_acquire_cleanup_obligation(self):
        (self.directory/'port/disable').write_text('1\n')
        answer = u.cycle(self.ctx, self.request)
        self.assertIn('already disabled', answer['reason'])
        self.assertIsNone(u.load(self.ctx))

    def test_matching_generic_bridge_elsewhere_blocks_reset(self):
        other = self.directory/'devices/2-7'
        other.mkdir()
        (other/'idVendor').write_text(u.VID)
        (other/'idProduct').write_text(u.PID)
        with self.assertRaisesRegex(w.Unsafe, 'still detected'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_uuid_present_even_without_usb_link_blocks_reset(self):
        (self.directory/'uuid'/w.DISK_UUID).write_text('simulated node')
        with self.assertRaisesRegex(w.Unsafe, 'different port'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_lazy_unmounted_file_handle_blocks_reset(self):
        (self.directory/'proc/10/fd/3').symlink_to(w.MOUNT+'/open-file (deleted)')
        with self.assertRaisesRegex(w.Unsafe, 'open handle'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_open_file_through_alias_is_detected_by_device_number(self):
        regular = self.directory/'file'
        regular.write_text('simulated')
        fd = self.directory/'proc/10/fd/3'
        fd.symlink_to(regular)
        original = Path.stat
        def info(path, *args, **kwargs):
            if path == fd:
                return types.SimpleNamespace(st_dev=os.makedev(240,17), st_mode=stat.S_IFREG)
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'stat', info), self.assertRaisesRegex(w.Unsafe, 'open file/device'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_process_cwd_on_lazy_unmounted_storage_blocks_reset(self):
        (self.directory/'proc/10/cwd').symlink_to(w.MOUNT+'/folder')
        with self.assertRaisesRegex(w.Unsafe, 'process still references'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_mmap_without_descriptor_blocks_reset(self):
        (self.directory/'proc/10/maps').write_text('1-2 r--p 00000000 f0:11 1 /alias/image\n')
        with self.assertRaisesRegex(w.Unsafe, 'Mapped memory'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_present_usb_never_reset_even_without_uuid(self):
        (self.directory/'absent-device').mkdir()
        with self.assertRaisesRegex(w.Unsafe, 'still detected'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_other_device_at_target_port_is_protected(self):
        other = self.directory/'foreign-device'
        other.mkdir()
        (self.directory/'port/device').symlink_to(other)
        with self.assertRaises(w.Unsafe):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_active_mount_in_another_namespace_blocks_reset(self):
        (self.directory/'proc/10/mountinfo').write_text('1 0 240:17 / /elsewhere rw - ext4 /dev/sdb1 rw\n')
        with self.assertRaisesRegex(w.Unsafe, 'still mounted'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_stale_mount_or_loop_image_prevents_reset(self):
        loop = self.directory/'block/loop8/loop'
        loop.mkdir(parents=True)
        (loop/'backing_file').write_text(w.IMAGE+'\n')
        with self.assertRaisesRegex(w.Unsafe, 'Loop image'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_open_raw_device_handle_blocks_reset(self):
        (self.directory/'proc/10/fd/3').symlink_to('/dev/sdb (deleted)')
        with self.assertRaisesRegex(w.Unsafe, 'open handle'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_inability_to_inspect_namespace_fails_closed(self):
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path.name == 'mountinfo':
                raise PermissionError('Simulated namespace permission denial')
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'read_text', read), self.assertRaises(PermissionError):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_no_prior_known_identity_blocks_reset(self):
        self.request['known_devs'] = []
        with self.assertRaisesRegex(w.Unsafe, 'No prior'):
            u.require_absent_and_isolated(self.ctx, self.request)



class ReturnedIdentityTests(Temp):
    def setUp(self):
        super().setUp()
        self.port = self.directory/'port'
        self.device = self.directory/'device'
        self.port.mkdir()
        self.device.mkdir()
        (self.device/'idVendor').write_text(u.VID)
        (self.device/'idProduct').write_text(u.PID)
        (self.device/'port').symlink_to(self.port)
        (self.port/'device').symlink_to(self.device)
        (self.port/'disable').write_text('0\n')
        (self.port/'state').write_text('configured\n')
        self.ctx.device_number = lambda path: '240:17'
        self.ctx.block_checks = mock.Mock()
        self.ctx.udev = lambda dev: {'ID_FS_UUID': w.DISK_UUID, 'ID_FS_TYPE': 'ext4', 'ID_SERIAL': u.DISK_SERIAL}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in [('PORT', self.port), ('DEVICE', self.device),
                            ('CANONICAL', str(self.port)), ('DEVICE_REAL', str(self.device))]:
            self.stack.enter_context(mock.patch.object(u, name, value))
        original = Path.resolve
        device = self.device
        def resolve(path, *args, **kwargs):
            return device/'block/sdb/sdb1' if str(path) == '/sys/dev/block/240:17' else original(path, *args, **kwargs)
        self.stack.enter_context(mock.patch.object(Path, 'resolve', resolve))
        self.stack.enter_context(mock.patch.object(u, 'port_identity'))

    def test_usb_present_but_attributes_still_appearing_keeps_polling(self):
        (self.device/'idVendor').unlink()
        self.assertFalse(u.ready(self.ctx))

    def test_usb_present_but_uuid_udev_metadata_pending_keeps_polling(self):
        self.ctx.udev = lambda dev: {}
        self.assertFalse(u.ready(self.ctx))
        self.ctx.block_checks.assert_not_called()

    def test_full_expected_usb_uuid_and_serial_are_ready(self):
        self.assertTrue(u.ready(self.ctx))
        self.ctx.block_checks.assert_called_once_with('240:17', w.DISK_UUID)

    def test_wrong_usb_device_is_rejected(self):
        (self.device/'idVendor').write_text('fffe')
        with self.assertRaises(w.Unsafe):
            u.ready(self.ctx)

    def test_wrong_disk_serial_is_rejected(self):
        self.ctx.udev = lambda dev: {'ID_FS_UUID': w.DISK_UUID, 'ID_FS_TYPE': 'ext4', 'ID_SERIAL': 'wrong'}
        with self.assertRaises(w.Unsafe):
            u.ready(self.ctx)

    def test_healthy_binding_records_full_identity_for_this_boot(self):
        saved = u.healthy_binding(self.ctx, '240:17')
        self.assertEqual(saved['boot'], 'simulated-boot')
        self.assertEqual(saved['main_dev'], '240:17')
        self.assertEqual(saved['uuid'], w.DISK_UUID)
        self.assertEqual(saved['controller_ids'], u.CONTROLLER_IDS)
        self.assertEqual(saved['disk_serial'], u.DISK_SERIAL)

    def test_healthy_binding_refuses_wrong_uuid_even_if_mount_is_rw(self):
        self.ctx.udev = lambda dev: {'ID_FS_UUID': 'wrong', 'ID_FS_TYPE': 'ext4', 'ID_SERIAL': u.DISK_SERIAL}
        with self.assertRaises(w.Unsafe):
            u.healthy_binding(self.ctx, '240:17')

    def test_reciprocal_port_mapping_is_required_for_healthy_binding(self):
        (self.port/'device').unlink()
        (self.port/'device').symlink_to(self.directory/'another-device')
        with self.assertRaises((w.Unsafe, OSError)):
            u.healthy_binding(self.ctx, '240:17')


class ControllerIdentityTests(Temp):
    def setUp(self):
        super().setUp()
        self.pci = self.directory/'pci'
        self.pci.mkdir()
        self.hub = self.pci/'usb9'
        self.hub.mkdir()
        for name, value in u.CONTROLLER_IDS.items():
            (self.pci/name).write_text(value+'\n')
        for name, value in u.ROOT_HUB_IDS.items():
            (self.hub/name).write_text(value+'\n')
        # Keep the entire synthetic controller independent of host hardware.
        # A real /sys driver symlink made these tests fail on non-xHCI hosts.
        self.drivers = self.directory/'drivers'
        (self.drivers/'xhci_hcd').mkdir(parents=True)
        (self.pci/'driver').symlink_to(self.drivers/'xhci_hcd')
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        resolve = Path.resolve
        def synthetic_driver(path, *args, **kwargs):
            resolved = resolve(path, *args, **kwargs)
            if resolved.is_relative_to(self.drivers):
                return Path('/sys/bus/pci/drivers')/resolved.relative_to(self.drivers)
            return resolved
        self.stack.enter_context(mock.patch.object(Path, 'resolve', synthetic_driver))
        for name, value in [('CONTROLLER', self.pci), ('ROOT_HUB', self.hub),
                            ('CONTROLLER_REAL', str(self.pci))]:
            self.stack.enter_context(mock.patch.object(u, name, value))

    def test_pinned_pci_controller_and_root_hub_match(self):
        u.controller_identity(self.ctx)

    def test_other_controller_driver_rejected(self):
        (self.drivers/'ehci-pci').mkdir()
        (self.pci/'driver').unlink()
        (self.pci/'driver').symlink_to(self.drivers/'ehci-pci')
        with self.assertRaises(w.Unsafe):
            u.controller_identity(self.ctx)

    def test_changed_controller_ids_block_policy(self):
        for key, original in u.CONTROLLER_IDS.items():
            (self.pci/key).write_text('wrong')
            with self.subTest(key=key), self.assertRaises(w.Unsafe):
                u.controller_identity(self.ctx)
            (self.pci/key).write_text(original)

    def test_bus_reassignment_to_different_controller_is_rejected(self):
        (self.hub/'serial').write_text('0000:00:1e.0')
        with self.assertRaises(w.Unsafe):
            u.controller_identity(self.ctx)


class PinnedPortTests(Temp):
    def setUp(self):
        super().setUp()
        self.port = self.directory/'root-interface/port2'
        self.port.mkdir(parents=True)
        (self.port/'disable').write_text('0\n')
        self.firmware = self.directory/'firmware'
        self.firmware.mkdir()
        (self.port/'firmware_node').symlink_to(self.firmware)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(u, 'PORT', self.port))
        self.stack.enter_context(mock.patch.object(u, 'CANONICAL', str(self.port)))
        self.stack.enter_context(mock.patch.object(u, 'FIRMWARE', str(self.firmware)))
        self.stack.enter_context(mock.patch.object(u, 'controller_identity'))

    def test_exact_port_and_firmware_match(self):
        u.port_identity(self.ctx)

    def test_controller_or_root_hub_path_cannot_substitute_for_port(self):
        with mock.patch.object(u, 'PORT', self.port.parent), self.assertRaises(w.Unsafe):
            u.port_identity(self.ctx)

    def test_different_firmware_or_peer_requires_review(self):
        with mock.patch.object(u, 'FIRMWARE', 'wrong'), self.assertRaises(w.Unsafe):
            u.port_identity(self.ctx)
        (self.port/'peer').symlink_to(self.directory/'other-port')
        with self.assertRaises(w.Unsafe):
            u.port_identity(self.ctx)

    def test_disable_attribute_cannot_be_a_symlink_to_another_control(self):
        (self.port/'disable').unlink()
        other = self.directory/'other-control'
        other.write_text('0\n')
        (self.port/'disable').symlink_to(other)
        with self.assertRaises(w.Unsafe):
            u.port_identity(self.ctx)


class DEV5ReconnectTests(Temp):
    def run_attachment_cycle(self,changed=True,ready=True,timeout=False,power_off=False):
        before={'busnum':'4','devnum':'2'};after=dict(before,devnum='3') if changed else before
        token=dict(before);original=self.fake_io
        def io(ctx,action,incident):
            original(ctx,action,incident)
            if action=='disable':
                u.update(ctx,disable_write_started_at=ctx.timestamp(),power_off_reported=power_off,
                         io_warning='' if power_off else 'Hardware did not report electrical power off.')
                token.update(after)
                if timeout:raise w.Unsafe('USB disable worker timed out during disable sysfs write')
        with self.simulation(0 if ready else None),mock.patch.object(u,'attachment_token',side_effect=lambda:dict(token)),mock.patch.object(u,'bounded_io',side_effect=io):
            return u.cycle(self.ctx,self.request)

    def test_timeout_lost_postwrite_receipt_new_attachment_verifies_success(self):
        result=self.run_attachment_cycle(timeout=True)
        self.assertTrue(result['ready']);self.assertTrue(result['port_enabled']);self.assertTrue(result['device_returned'])
        self.assertFalse(result['mount_verified']);self.assertNotIn('disable_written_at',u.load(self.ctx))
        self.assertIn('warning',result['reason']);self.assertEqual(self.actions,['disable','enable'])

    def test_ambiguous_power_readback_with_new_attachment_is_success(self):
        result=self.run_attachment_cycle();self.assertTrue(result['ready']);self.assertFalse(u.load(self.ctx)['power_off_reported'])

    def test_zero_exit_and_unchanged_disk_is_not_reconnect_success(self):
        result=self.run_attachment_cycle(changed=False);self.assertFalse(result['ready']);self.assertEqual(result['enumeration_seconds'],20)
        self.assertIn('No verified USB reconnection',result['reason'])

    def test_timed_out_disable_without_return_stays_failed_even_after_enable(self):
        result=self.run_attachment_cycle(timeout=True,ready=False);self.assertFalse(result['ready']);self.assertTrue(result['port_enabled'])
        self.assertEqual(self.actions,['disable','enable'])

    def test_changed_enumeration_does_not_override_wrong_uuid_or_hardware(self):
        with self.simulation(),mock.patch.object(u,'ready',side_effect=w.Unsafe('Returned USB serial or UUID differs')):
            with self.assertRaisesRegex(w.Unsafe,'serial or UUID'):u.cycle(self.ctx,self.request)
        self.assertEqual(u.load(self.ctx)['phase'],'enabled')

    def test_delayed_disable_writer_lock_is_waited_for_before_enable(self):
        import fcntl
        u.reserve(self.ctx,self.request);lock=(self.directory/'usb-io.lock').open('a');self.addCleanup(lock.close)
        fcntl.flock(lock,fcntl.LOCK_EX)
        def sleep(seconds):
            self.clock.sleep(seconds)
            if self.clock.now>=.2:fcntl.flock(lock,fcntl.LOCK_UN)
        with mock.patch.object(u.time,'monotonic',side_effect=self.clock.read),mock.patch.object(u.time,'sleep',side_effect=sleep),mock.patch.object(u,'bounded_io',side_effect=self.fake_io):
            self.assertTrue(u.ensure_enabled(self.ctx))
        self.assertGreaterEqual(self.clock.now,.2);self.assertEqual(self.actions,['enable'])

    def test_permanently_blocked_writer_cleanup_is_bounded_and_keeps_obligation(self):
        import fcntl
        u.reserve(self.ctx,self.request)
        with (self.directory/'usb-io.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            with mock.patch.object(u.time,'monotonic',side_effect=self.clock.read),mock.patch.object(u.time,'sleep',side_effect=self.clock.sleep),mock.patch.object(u,'bounded_io') as io:
                self.assertFalse(u.ensure_enabled(self.ctx));io.assert_not_called()
        self.assertLess(self.clock.now,u.CLEANUP_TIMEOUT+.1);self.assertEqual(u.load(self.ctx)['phase'],'enable_failed')
        self.assertIn('still busy',u.load(self.ctx)['reason'])

    def test_missing_enumeration_identity_on_present_disk_blocks_before_write(self):
        device=self.directory/'device';device.mkdir()
        with mock.patch.object(u,'DEVICE',device),self.assertRaisesRegex(w.Unsafe,'enumeration identity'):u.reserve(self.ctx,self.request)
        self.assertIsNone(u.load(self.ctx))

    def test_bounded_worker_timeout_preserves_stage_and_does_not_wait_unbounded(self):
        u.reserve(self.ctx,self.request);u.update(self.ctx,io_stage='disable sysfs write',disable_write_started_at=self.ctx.timestamp())
        child=mock.Mock();child.poll.return_value=None;child.wait.side_effect=u.subprocess.TimeoutExpired('fake-worker',.1)
        with mock.patch.object(u.subprocess,'Popen',return_value=child),mock.patch.object(u.time,'monotonic',side_effect=self.clock.read),mock.patch.object(u.time,'sleep',side_effect=self.clock.sleep):
            with self.assertRaisesRegex(w.Unsafe,'disable sysfs write'):u.bounded_io(self.ctx,'disable',self.request['incident'])
        child.kill.assert_called_once();child.wait.assert_called_once_with(timeout=.1)
        self.assertLess(self.clock.now,u.IO_TIMEOUT+.1);self.assertEqual(u.load(self.ctx)['io_timeout'],'disable')

if __name__ == '__main__':
    unittest.main()
