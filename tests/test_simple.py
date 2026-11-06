# SPDX-License-Identifier: MIT
"""Focused 2.0 sequence, manual-control and standby safety regressions."""
import contextlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('simple_engine', Path(__file__).parents[1] / 'src/usb_storage_watch/engine.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class SequenceTests(unittest.TestCase):
    def run_sequence(self, present=True, mount_errors=(), ready=True, blocked=False):
        actions = []
        mounted = False
        def mount(note):
            nonlocal mounted
            actions.append('mount')
            index = actions.count('mount') - 1
            if index < len(mount_errors) and mount_errors[index]:
                raise mount_errors[index]
            mounted = True
        def cycle(ctx, request):
            actions.append('cycle')
            self.assertEqual(request['known_binding'], {'saved': 'binding'})
            return dict(ready=ready, cycled=True, reason='enumeration timeout' if not ready else 'returned')
        request = dict(incident='test', number=1, allow_mount=True, allow_usb=True, usb_resets=0,
                       blocked=['main'] if blocked else [], known_binding={'saved': 'binding'})
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(w, 'snapshot', side_effect=lambda: dict(healthy=mounted, detected=present, mounts=[])))
            stack.enter_context(mock.patch.object(Path, 'exists', return_value=present))
            stack.enter_context(mock.patch.object(w, 'mount_main', side_effect=mount))
            stack.enter_context(mock.patch.object(w.usb, 'cycle', side_effect=cycle))
            stack.enter_context(mock.patch.object(w, 'verify_main'))
            stack.enter_context(mock.patch.object(w, 'verify_access'))
            stack.enter_context(mock.patch.object(w, 'DEPENDENT_ENABLED', False))
            # Storage-only unit scope; UI22 lifecycle tests cover the real Docker guard.
            result = w.guarded_recovery_work(request, Path(directory) / 'receipt')
        return actions, result

    def test_successful_first_mount_does_not_cycle(self):
        actions, result = self.run_sequence()
        self.assertEqual(actions, ['mount']); self.assertTrue(result['main'])

    def test_failed_mount_cycles_once_then_mounts_once(self):
        actions, result = self.run_sequence(mount_errors=[w.MountFailure('failed')])
        self.assertEqual(actions, ['mount', 'cycle', 'mount']); self.assertTrue(result['main'])

    def test_second_mount_failure_is_terminal(self):
        actions, result = self.run_sequence(mount_errors=[w.MountFailure('first'), w.MountFailure('second')])
        self.assertEqual(actions, ['mount', 'cycle', 'mount']); self.assertFalse(result['main'])

    def test_absent_device_uses_saved_binding(self):
        actions, result = self.run_sequence(present=False)
        self.assertEqual(actions, ['cycle', 'mount']); self.assertTrue(result['main'])

    def test_enumeration_timeout_never_mounts_again(self):
        actions, result = self.run_sequence(present=False, ready=False)
        self.assertEqual(actions, ['cycle']); self.assertFalse(result['main'])

    def test_unsafe_mount_never_cycles(self):
        actions, result = self.run_sequence(mount_errors=[w.Unsafe('wrong UUID')])
        self.assertEqual(actions, ['mount']); self.assertFalse(result['main'])

    def test_blocked_incident_does_not_mutate(self):
        actions, result = self.run_sequence(blocked=True)
        self.assertEqual(actions, []); self.assertFalse(result['main'])


class StandbyTests(unittest.TestCase):
    def test_activity_uses_kernel_stat_and_inflight_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'stat').write_text('1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17')
            counters, inflight = w.standby.activity({'sys':directory})
            self.assertEqual(inflight, 9)
            self.assertEqual(counters, list(range(1,9)) + list(range(12,18)))

    def test_idle_resets_on_io_and_attempts_once_until_new_activity(self):
        context = types.SimpleNamespace(SETTINGS={'standby':{'enabled':True, 'idle_seconds':60}},
            snapshot=lambda:{'healthy':True}, clock_now=mock.Mock(), Unsafe=w.Unsafe)
        idle = w.standby.Idle()
        with mock.patch.object(w.standby, 'identity', return_value={'serial':'one'}), \
                mock.patch.object(w.standby, 'activity', return_value=([1],0)) as activity, \
                mock.patch.object(w.standby, 'status', side_effect=[{'sleeping':False}, {'sleeping':True}, {'sleeping':False}]):
            for now, due in [(0,False),(59,False),(60,True),(120,False)]:
                context.clock_now.return_value=now
                self.assertEqual(idle.due(context), due)
            activity.return_value=([2],0)
            context.clock_now.return_value=121; self.assertFalse(idle.due(context))
            context.clock_now.return_value=181; self.assertTrue(idle.due(context))

    def test_unsupported_bridge_is_explicit(self):
        with mock.patch.object(w.standby.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1, stderr='Operation not supported')):
            with self.assertRaisesRegex(w.Unsafe, 'USB-SATA bridge') as failure:
                w.standby.power_command(w.usb_context(), '-y', '/dev/disk/by-id/synthetic')
            self.assertEqual(w.standby.error_result(failure.exception), 'unsupported')

    def test_ata_deep_sleep_is_never_allowed(self):
        with mock.patch.object(w.standby.subprocess, 'run') as run:
            with self.assertRaises(w.Unsafe):
                w.standby.power_command(w.usb_context(), '-Y', '/dev/synthetic')
            run.assert_not_called()

    def test_busy_hdd_is_not_flushed_or_stopped(self):
        context = w.usb_context()
        context.command = mock.Mock()
        with mock.patch.object(w.standby, 'identity', return_value={'sys':'/fake'}), \
                mock.patch.object(Path, 'read_text', return_value='1'), \
                mock.patch.object(context, 'snapshot', return_value={'healthy':True}), \
                mock.patch.object(w.standby, 'storage_kind', return_value='mechanical'), \
                mock.patch.object(w.standby, 'status', return_value={'sleeping':False}), \
                mock.patch.object(w.standby, 'users', side_effect=w.Unsafe('active users')), \
                mock.patch.object(w.standby, 'power_command') as power:
            with self.assertRaisesRegex(w.Unsafe, 'active users'):
                w.standby.sleep(context)
            context.command.assert_not_called(); power.assert_not_called()

    def sleep_case(self, counters, fuser_code=1, mounted=True, fuser_error=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'queue').mkdir()
            (root/'queue/rotational').write_text('1'); (root/'dev').write_text('8:0')
            (root/'node').touch()
            binding = dict(sys=directory, path=str(root/'node'))
            context = w.usb_context(); context.device_number = lambda _: '8:0'
            calls = []
            context.command = lambda argv, **kw: calls.append(argv)
            def command(argv, **kw):
                calls.append(argv)
                if argv[0] == '/usr/bin/fuser':
                    return types.SimpleNamespace(returncode=fuser_code, stdout='', stderr=fuser_error)
                return types.SimpleNamespace(returncode=0, stdout='drive state is: standby', stderr='')
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(w.standby, 'identity', return_value=binding))
                stack.enter_context(mock.patch.object(w.standby, 'storage_kind', return_value='mechanical'))
                stack.enter_context(mock.patch.object(w.standby, 'status', return_value={'sleeping':False}))
                stack.enter_context(mock.patch.object(w.standby, 'users'))
                stack.enter_context(mock.patch.object(w.standby, 'filesystems', return_value=([],[w.MOUNT])))
                stack.enter_context(mock.patch.object(context, 'snapshot', return_value={'healthy':mounted}))
                stack.enter_context(mock.patch.object(w.standby, 'activity', side_effect=counters))
                stack.enter_context(mock.patch.object(w.standby.subprocess, 'run', side_effect=command))
                stack.enter_context(mock.patch.object(w.standby.time, 'sleep', side_effect=lambda seconds:calls.append(['wait',seconds])))
                saved = stack.enter_context(mock.patch.object(w.standby, 'save'))
                try:
                    w.standby.sleep(context)
                    return 'success', calls, saved.called
                except w.Unsafe as exc:
                    return w.standby.error_result(exc), calls, saved.called

    def test_three_second_guard_then_sync_then_only_normal_standby(self):
        result, calls, saved = self.sleep_case([([0],0)] * 5)
        self.assertEqual(result, 'success'); self.assertTrue(saved)
        self.assertEqual(calls[:3], [['/usr/bin/fuser','-m','-M',w.MOUNT],
                                   ['wait',3], ['/usr/bin/sync','-f','--',w.MOUNT]])
        self.assertEqual([call[:2] for call in calls[3:]], [['/usr/sbin/hdparm','-y'], ['/usr/sbin/hdparm','-C']])
        self.assertTrue(calls[3][2].startswith('/proc/self/fd/'))

    def test_busy_users_or_three_second_io_change_never_flush_or_sleep(self):
        for counters, code in [([],0), ([([0],0),([1],0)],1)]:
            with self.subTest(fuser_code=code):
                result, calls, saved = self.sleep_case(counters, code)
                self.assertEqual(result, 'busy'); self.assertFalse(saved)
                self.assertFalse(any(c[0] in ('/usr/bin/sync','/usr/sbin/hdparm') for c in calls))

    def test_unmounted_or_failed_user_check_never_sleeps(self):
        for mounted, code, expected in [(False,1,'unavailable'), (True,2,'failed')]:
            result, calls, saved = self.sleep_case([],code,mounted)
            self.assertEqual(result,expected); self.assertFalse(saved)
            self.assertFalse(any(c[0] == '/usr/sbin/hdparm' for c in calls))

    def test_fuser_idle_exit_is_allowed_but_inspection_diagnostics_block_standby(self):
        result, calls, saved = self.sleep_case([], fuser_error='Cannot open /proc directory: Permission denied')
        self.assertEqual(result,'failed'); self.assertFalse(saved)
        self.assertFalse(any(call[0] in ('/usr/bin/sync','/usr/sbin/hdparm') for call in calls))

    def test_io_during_standby_never_claims_confirmed_sleep(self):
        result, _, saved = self.sleep_case([([0],0)]*4+[([1],0)])
        self.assertEqual(result,'busy'); self.assertFalse(saved)

    def test_automatic_sleep_settings_upgrade_preserves_old_configuration(self):
        old = w.settings.default(); old['disk']['uuid']='11111111-1111-4111-8111-111111111111'
        del old['standby']; del old['services']
        result = w.settings.validate(old)
        self.assertFalse(result['standby']['enabled']); self.assertEqual(result['services']['units'], [])
        self.assertNotIn('standby', old)


class ControlTests(unittest.TestCase):
    def test_already_unmounted_never_checks_underlying_files(self):
        context = w.usb_context()
        context.read_rows=lambda:[]
        with mock.patch.object(Path, 'iterdir', side_effect=AssertionError('Must not inspect contents')):
            self.assertIn('Already unmounted', w.controls.unmount(context))

    def test_wrong_mount_identity_never_unmounts(self):
        context=w.usb_context()
        context.read_rows=lambda:[{'target':w.MOUNT}]
        context.device_number=lambda _: '8:17'
        context.mounted_checks=mock.Mock(side_effect=w.Unsafe('wrong identity'))
        context.command=mock.Mock()
        with self.assertRaisesRegex(w.Unsafe, 'wrong identity'):
            w.controls.unmount(context)
        context.command.assert_not_called()


class ServiceTests(unittest.TestCase):
    def test_service_restart_intent_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            context = w.usb_context()
            context.STATE_DIR = Path(directory)
            context.SETTINGS = {'services':{'units':['synthetic-app.service']}}
            context.config_load = lambda: {'automatic_recovery':True}
            context.verify_dependent = mock.Mock()
            context.command = mock.Mock(return_value='')
            with mock.patch.object(w.apps, 'quick_storage'):
                first = w.apps.recover_services(context, {'incident':'synthetic'})
                second = w.apps.recover_services(context, {'incident':'synthetic'})
            self.assertEqual(first, second)
            self.assertEqual(first['synthetic-app.service']['status'], 'verified')
            self.assertEqual(context.command.call_count, 2)  # restart and is-active, once each

    def test_service_failure_does_not_retry_or_report_success(self):
        with tempfile.TemporaryDirectory() as directory:
            context = w.usb_context()
            context.STATE_DIR = Path(directory)
            context.SETTINGS = {'services':{'units':['synthetic-app.service']}}
            context.config_load = lambda: {'automatic_recovery':True}
            context.verify_dependent = mock.Mock()
            context.command = mock.Mock(side_effect=w.Unsafe('restart failed'))
            with mock.patch.object(w.apps, 'quick_storage'):
                w.apps.recover_services(context, {'incident':'synthetic'})
                second = w.apps.recover_services(context, {'incident':'synthetic'})
            self.assertEqual(second['synthetic-app.service']['status'], 'failed')
            self.assertEqual(context.command.call_count, 1)
