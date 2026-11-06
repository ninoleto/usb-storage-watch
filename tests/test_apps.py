# SPDX-License-Identifier: MIT
#!/usr/bin/python3
"""Offline restart simulations. No real Docker, mounts, USB or email operations."""
import contextlib
import copy
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('apps_test_watch', HERE.parent/'src/usb_storage_watch/engine.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
_fs = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('fixtures.py'))
fixture = importlib.util.module_from_spec(_fs)
_fs.loader.exec_module(fixture)
fixture.configure(w)

a = w.apps


def observation(healthy=True, loopfs=True):
    return {'healthy': healthy, 'detected': healthy, 'dependent': loopfs and healthy,
        'unsafe': False, 'detail': 'simulated storage', 'dependent_detail': 'simulated dependent loop', 'mounts': []}


def storage_result(main=True, loopfs=True):
    return {'main': main, 'dependent': main and loopfs, 'detected': main, 'actions': [],
            'blocked': [], 'reason': 'simulated storage outcome', 'dependent_reason': 'simulated dependent loop', 'mounts': []}


class Clock:
    now = 15.0
    def sleep(self, duration): self.now += duration


class FakeDocker:
    def __init__(self):
        self.containers = {}
        self.changes = []
        self.accesses = []
        self.fail = set()
        self.inspect_fail = set()
        self.timeout_after_apply = set()
        self.access_fail = set()
        self.after_change = lambda name: None
        for n, (name, cfg) in enumerate(a.APPS.items(), 1):
            self.containers[name] = {'id': str(n)*64, 'name': name, 'running': True,
                'paused': False, 'restarting': False, 'dead': False, 'started_at': 'before',
                'pid': 100+n, 'healthcheck': name == 'app_three',
                'health': 'healthy' if name == 'app_three' else None,
                'mounts': [{'Type': 'bind', 'Source': cfg['source'], 'Destination': cfg['destination'],
                            'RW': True, 'Propagation': 'rprivate'}]}
    def inspect(self, name):
        if name in self.inspect_fail: raise a.AppError('Simulated inspect failure')
        return copy.deepcopy(self.containers[name])
    def change(self, name, identity, action):
        self.changes.append((name, identity, action))
        if name in self.fail: raise a.AppError('Simulated restart rejected')
        self.containers[name].update(running=action != 'stop', started_at=self.containers[name]['started_at'] if action == 'stop' else 'after-'+name)
        self.after_change(name)
        if name in self.timeout_after_apply: raise a.AppError('Simulated API acknowledgement timeout')
    def access(self, identity, destination, check):
        check()
        name = next(n for n,v in self.containers.items() if v['id'] == identity)
        self.accesses.append(name)
        if name in self.access_fail: raise a.AppError('Simulated access denied')


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp', prefix='apps-test-')
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.ctx = w.usb_context(self.directory)
        # This isolated legacy profile has no other configured drives.
        self.ctx.CONFIG = self.directory/'config.json'
        self.ctx.settings = types.SimpleNamespace(**vars(w.settings))
        self.ctx.settings.CONFIG = self.ctx.CONFIG
        self.ctx.settings.STATE_DIR = self.directory
        self.clock = Clock()
        self.ctx.boot_id = lambda: 'boot-test'
        self.ctx.clock_now = lambda: self.clock.now
        self.ctx.timestamp = lambda: 'simulated-time'
        self.ctx.config_load = lambda: {'automatic_recovery': True}
        self.ctx.require_configuration = lambda request: None
        self.healthy = True
        self.ctx.snapshot = lambda: observation(self.healthy)
        self.ctx.verify_main = mock.Mock(return_value='240:17')
        self.ctx.verify_dependent = mock.Mock()
        self.docker = FakeDocker()
        self.stack = __import__('contextlib').ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(a, 'Docker', return_value=self.docker))
        self.stack.enter_context(mock.patch.object(a, 'enabled', return_value=True))
        self.stack.enter_context(mock.patch.object(a, 'READER', None))
        self.stack.enter_context(mock.patch.object(w.drives, 'roots', return_value=(self.directory, self.directory)))
        self.stack.enter_context(mock.patch.object(a.time, 'monotonic', side_effect=lambda: self.clock.now))
        self.stack.enter_context(mock.patch.object(a.time, 'sleep', side_effect=self.clock.sleep))
        self.stack.enter_context(mock.patch.object(a, 'HEALTH_TIMEOUT', 3))
        self.namespace = self.stack.enter_context(mock.patch.object(a, 'namespace_proof'))
        self.real_source = a.source_proof
        def source(ctx, name, request=None):
            a.quick_storage(ctx, request)
            return '240:17', os.makedev(240,17), 123
        self.source = self.stack.enter_context(mock.patch.object(a, 'source_proof', side_effect=source))
        self.monitor = w.Monitor(self.directory/'state.json', now=0, boot='boot-test')

    def outage(self, baseline=True):
        self.monitor.sample(observation(), 0)
        self.monitor.sample(observation(), 15)
        if baseline:
            self.monitor.capture_result({'incident': None}, a.capture(self.ctx, self.docker))
        self.monitor.sample(observation(False), 30)
        self.monitor.sample(observation(False), 45)
        req = self.monitor.capture_request(45)
        self.monitor.capture_result(req, a.capture(self.ctx, self.docker))
        # These tests focus on the start stage. The stop protocol itself is
        # exercised through real durable receipts by test_ui20_lifecycle and
        # test_ui20_docker_protocol; establish that completed boundary here.
        stop_request = self.monitor.stop_request(45)
        if stop_request:
            stopped = {}
            for name, current in self.docker.containers.items():
                stopped[name] = dict(status='stopped', container_id=current['id'], action_count=1,
                                     before_started_at=current['started_at'])
                current['running'] = False
            self.monitor.stop_result(dict(complete=True, all_stopped=True, containers=stopped))
        returned = observation(False)
        returned['detected'] = True
        self.monitor.sample(returned, 60)

    def ready(self, loopfs=True):
        self.outage()
        self.recover_storage(loopfs)
        return self.monitor.app_request()

    def recover_storage(self, loopfs=True):
        req = self.monitor.work_request(True, 105)
        self.monitor.work_result(req, storage_result(loopfs=loopfs), 106)
        self.monitor.sample(observation(loopfs=loopfs), 120)
        self.monitor.sample(observation(loopfs=loopfs), 135)


class RecoveryTests(Temp):
    def test_three_individual_restarts_and_verified_outcome_once(self):
        request = self.ready()
        result = a.recover(self.ctx, request)
        self.assertEqual([x[0] for x in self.docker.changes], list(a.APPS))
        self.assertTrue(result['all_verified'])
        self.assertEqual(self.docker.accesses, [])  # Restart does not run commands inside containers.
        self.monitor.app_result(result)
        self.assertEqual(len(self.monitor.state['pending']), 1)
        detail = self.monitor.state['pending'][0]['detail']
        for name in a.APPS: self.assertIn(name, detail)
        self.assertIn('started_at', detail)
        self.assertEqual(self.monitor.state['status'], 'up')

    def test_storage_failure_never_calls_docker_change_or_application_worker(self):
        self.outage()
        first = self.monitor.work_request(True, 105)
        self.monitor.work_result(first, storage_result(False), 106)
        second = self.monitor.work_request(True, 166)
        self.assertIsNone(second)
        self.assertIsNone(self.monitor.app_request())
        self.assertEqual(self.docker.changes, [])
        event = self.monitor.state['pending'][0]
        self.assertEqual(event['subject'], 'Storage RECOVERY FAILED — Manual intervention required')
        self.assertIn('storage remains unavailable', event['detail'])

    def test_image_failure_enters_per_container_verification(self):
        request=self.ready(loopfs=False)
        self.assertIsNotNone(request)
        self.assertEqual(self.docker.changes, [])
        result=a.recover(self.ctx, request)
        self.monitor.app_result(result)
        self.assertIn('dependent loop mount unavailable', self.monitor.state['pending'][0]['subject'])

    def test_selected_stopped_container_is_restarted(self):
        self.docker.containers['app_two']['running'] = False
        result = a.recover(self.ctx, self.ready())
        self.assertEqual([x[0] for x in self.docker.changes], ['app_one', 'app_two', 'app_three'])
        self.assertEqual(result['containers']['app_two']['status'], 'verified')
        self.assertTrue(result['all_verified'])

    def test_container_that_exited_during_outage_uses_restart(self):
        self.outage()
        self.docker.containers['app_one']['running'] = False
        self.recover_storage()
        result = a.recover(self.ctx, self.monitor.app_request())
        self.assertEqual(self.docker.changes[0][2], 'start')
        self.assertTrue(result['all_verified'])

    def test_restart_rejected_no_retry_other_containers_continue(self):
        self.docker.fail.add('app_two')
        result = a.recover(self.ctx, self.ready())
        self.assertEqual([x[0] for x in self.docker.changes].count('app_two'), 1)
        self.assertEqual(result['containers']['app_two']['status'], 'failed')
        self.assertEqual(result['containers']['app_three']['status'], 'verified')
        self.monitor.app_result(result)
        self.assertIn('Applications require attention', self.monitor.state['pending'][0]['subject'])

    def test_api_timeout_after_success_is_verified_without_duplicate(self):
        self.docker.timeout_after_apply.add('app_one')
        result = a.recover(self.ctx, self.ready())
        self.assertTrue(result['all_verified'])
        self.assertIn('api_error', result['containers']['app_one'])
        self.assertEqual(len(self.docker.changes), 3)

    def test_unhealthy_healthcheck_never_reports_complete(self):
        self.docker.containers['app_three']['health'] = 'unhealthy'
        result = a.recover(self.ctx, self.ready())
        self.assertFalse(result['all_verified'])
        self.assertEqual(result['containers']['app_three']['status'], 'failed')

    def test_inside_container_access_does_not_gate_restart(self):
        self.docker.access_fail.add('app_one')
        result = a.recover(self.ctx, self.ready())
        self.assertTrue(result['all_verified'])
        self.assertEqual(self.docker.accesses, [])

    def test_storage_loss_between_containers_stops_remaining_actions(self):
        request = self.ready()
        self.docker.after_change = lambda name: setattr(self, 'healthy', False)
        result = a.recover(self.ctx, request)
        self.assertTrue(result['interrupted'])
        self.assertEqual(len(self.docker.changes), 1)
        self.monitor.app_result(result)
        self.assertIn('RECOVERY FAILED', self.monitor.state['pending'][0]['subject'])

    def test_unavailable_storage_before_application_stage_means_no_mutation(self):
        request = self.ready()
        self.healthy = False
        result = a.recover(self.ctx, request)
        self.assertTrue(result['interrupted'])
        self.assertEqual(self.docker.changes, [])

    def test_wrong_container_id_is_never_restarted(self):
        request = self.ready()
        self.docker.containers['app_one']['id'] = 'a'*64
        result = a.recover(self.ctx, request)
        self.assertNotIn('app_one', [x[0] for x in self.docker.changes])
        self.assertIn('replaced', result['containers']['app_one']['reason'])

    def test_changed_bind_mapping_does_not_block_selected_restart(self):
        request = self.ready()
        self.docker.containers['app_one']['mounts'][0]['Source'] = '/srv/test-user/underlying'
        result = a.recover(self.ctx, request)
        self.assertIn('app_one', [x[0] for x in self.docker.changes])
        self.assertEqual(result['containers']['app_one']['status'], 'verified')

    def test_selected_paused_container_receives_restart_but_unverified_state_is_reported(self):
        request = self.ready()
        self.docker.containers['app_one']['paused'] = True
        result = a.recover(self.ctx, request)
        self.assertIn('app_one', [x[0] for x in self.docker.changes])
        self.assertEqual(result['containers']['app_one']['status'], 'failed')

    def test_explicit_off_switch_preserves_containers_and_monitor(self):
        request = self.ready()
        with mock.patch.object(a, 'enabled', return_value=False):
            result = a.recover(self.ctx, request)
        self.assertEqual(self.docker.changes, [])
        self.monitor.app_result(result)
        self.assertEqual(self.monitor.state['status'], 'up')
        self.assertEqual(len(self.monitor.state['pending']), 1)

    def test_completed_ledger_prevents_duplicate_restart(self):
        request = self.ready()
        a.recover(self.ctx, request)
        a.recover(self.ctx, request)
        self.assertEqual(len(self.docker.changes), 3)

    def historical_ledger(self, incident='previous-incident', complete=True, status='verified', count=1):
        value = {'version': 1, 'incident': incident, 'complete': complete, 'containers': {
            'retired_container': {'status': status, 'action_count': count}}}
        raw = json.dumps(value, indent=2) + '\n'
        a.ledger_path(self.ctx).write_text(raw)
        return raw

    def test_completed_previous_selection_is_archived_and_new_incident_recovers(self):
        self.docker.containers['app_two']['running'] = False
        request = self.ready()
        raw = self.historical_ledger()
        self.assertIsNone(a.read_ledger(self.ctx, request['incident']))
        self.assertFalse((self.directory/'application-history').exists())  # Reads never mutate history.
        result = a.recover(self.ctx, request)
        self.assertTrue(result['all_verified'])
        self.assertEqual([x[0] for x in self.docker.changes], ['app_one', 'app_two', 'app_three'])
        self.assertEqual(result['containers']['app_two']['status'], 'verified')
        self.assertEqual([p.read_text() for p in (self.directory/'application-history').glob('*.json')], [raw])
        a.recover(self.ctx, request)
        self.assertEqual(len(self.docker.changes), 3)

    def test_unresolved_previous_selection_still_blocks_new_actions(self):
        request = self.ready();raw = self.historical_ledger(complete=False, status='intent')
        with self.assertRaisesRegex(a.AppError, 'older application recovery is unresolved'):
            a.recover(self.ctx, request)
        self.assertEqual(a.ledger_path(self.ctx).read_text(), raw)
        self.assertEqual(self.docker.changes, [])

    def test_completed_incident_changed_selection_does_not_gain_new_budget(self):
        request = self.ready()
        self.historical_ledger(incident=request['incident'])
        result = a.recover(self.ctx, request)
        self.assertEqual(set(result['containers']), {'retired_container'})
        self.assertEqual(self.docker.changes, [])

    def test_completed_flag_cannot_hide_unresolved_historical_intent(self):
        request = self.ready();raw = self.historical_ledger(status='intent')
        with self.assertRaises(a.AppError): a.recover(self.ctx, request)
        self.assertEqual(a.ledger_path(self.ctx).read_text(), raw)
        self.assertEqual(self.docker.changes, [])

    def test_history_write_failure_preserves_old_ledger_and_prevents_actions(self):
        request = self.ready();raw = self.historical_ledger()
        with mock.patch.object(self.ctx, 'atomic_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): a.recover(self.ctx, request)
        self.assertEqual(a.ledger_path(self.ctx).read_text(), raw)
        self.assertEqual(self.docker.changes, [])

    def test_status_reports_ledger_guard_without_losing_saved_state_or_acting(self):
        state = copy.deepcopy(self.monitor.state)
        output = io.StringIO()
        with mock.patch.object(w.drives, 'configuration_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(sys, 'argv', ['watch', 'status']), \
             mock.patch.object(w.settings, 'read', return_value=w.settings.validate(fixture.configuration(w))), \
             mock.patch.object(w.os, 'geteuid', return_value=0), \
             mock.patch.object(w.os, 'chdir'), mock.patch.object(w.os, 'umask'), \
             mock.patch.object(w, 'load_state', return_value=state), \
             mock.patch.object(w.usb, 'load', return_value=None), \
             mock.patch.object(a, 'read_ledger', side_effect=a.AppError('Application selection changed.')), \
             mock.patch.object(sys, 'stdout', output):
            self.assertEqual(w.main(), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['state'], state)
        self.assertEqual(result['application_ledger_warning'], 'Application selection changed.')
        self.assertIsNone(result['application_ledger'])
        self.assertEqual(self.docker.changes, [])

    def test_service_crash_after_docker_action_resumes_verification_only(self):
        request = self.ready()
        def crash(name): raise KeyboardInterrupt()
        self.docker.after_change = crash
        with self.assertRaises(KeyboardInterrupt): a.recover(self.ctx, request)
        ledger = a.read_ledger(self.ctx, request['incident'])
        self.assertEqual(ledger['containers']['app_one']['status'], 'intent')
        restarted = w.Monitor(self.directory/'state.json', now=140, boot='boot-test')
        self.assertIsNone(restarted.app_request())
        restarted.sample(observation(), 150)
        restarted.sample(observation(), 165)
        self.docker.after_change = lambda name: None
        result = a.recover(self.ctx, restarted.app_request())
        self.assertTrue(result['all_verified'])
        self.assertEqual([x[0] for x in self.docker.changes].count('app_one'), 1)
        restarted.app_result(result)
        self.assertEqual(len(restarted.state['pending']), 1)

    def test_crash_after_intent_before_request_consumes_budget(self):
        request = self.ready()
        original = self.ctx.atomic_write
        def write(path, data, **kw):
            result = original(path, data, **kw)
            if '"status": "intent"' in data:
                raise KeyboardInterrupt()
            return result
        self.ctx.atomic_write = write
        with self.assertRaises(KeyboardInterrupt): a.recover(self.ctx, request)
        self.assertEqual(self.docker.changes, [])
        self.ctx.atomic_write = original
        result = a.recover(self.ctx, request)
        self.assertNotIn('app_one', [x[0] for x in self.docker.changes])
        self.assertEqual(result['containers']['app_one']['status'], 'failed')

    def test_fsync_failure_before_intent_prevents_action(self):
        request = self.ready()
        original = self.ctx.atomic_write
        def write(path, data, **kw):
            if '"status": "intent"' in data: raise OSError('simulated disk full')
            return original(path, data, **kw)
        self.ctx.atomic_write = write
        result = a.recover(self.ctx, request)
        self.assertEqual(self.docker.changes, [])
        self.assertFalse(result['all_verified'])

    def test_overlapping_worker_is_rejected(self):
        request = self.ready()
        with (self.directory/'applications.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError): a.recover(self.ctx, request)
        self.assertEqual(self.docker.changes, [])

    def test_corrupt_or_reset_budget_ledger_never_replays(self):
        request = self.ready()
        a.ledger_path(self.ctx).write_text(json.dumps({'version': 1, 'complete': False, 'containers': {
            n: {'status': 'pending', 'action_count': 1} for n in a.APPS}}))
        with self.assertRaises(a.AppError): a.recover(self.ctx, request)
        self.assertEqual(self.docker.changes, [])

    def test_storage_loss_after_fsync_before_docker_request_cancels_action(self):
        request = self.ready()
        original = self.ctx.atomic_write
        def write(path, data, **kw):
            result = original(path, data, **kw)
            if '"status": "intent"' in data:
                self.healthy = False
            return result
        self.ctx.atomic_write = write
        result = a.recover(self.ctx, request)
        self.assertTrue(result['interrupted'])
        self.assertEqual(self.docker.changes, [])
        self.assertEqual(result['containers']['app_one']['action_count'], 1)

    def test_final_sweep_detects_earlier_app_losing_health(self):
        request = self.ready()
        def changed(name):
            if name == 'app_three': self.docker.containers['app_one']['running'] = False
        self.docker.after_change = changed
        result = a.recover(self.ctx, request)
        self.assertFalse(result['all_verified'])
        self.assertIn('Final verification', result['containers']['app_one']['reason'])
        self.assertEqual(len(self.docker.changes), 3)

    def test_inspect_failure_does_not_stop_other_app_recovery(self):
        request = self.ready()
        self.docker.inspect_fail.add('app_one')
        result = a.recover(self.ctx, request)
        self.assertEqual(result['containers']['app_one']['status'], 'failed')
        self.assertEqual([x[0] for x in self.docker.changes], ['app_two', 'app_three'])

    def test_replaced_container_after_restart_cannot_report_verified(self):
        request = self.ready()
        def changed(name):
            if name == 'app_one': self.docker.containers[name]['id'] = 'f'*64
        self.docker.after_change = changed
        result = a.recover(self.ctx, request)
        self.assertEqual(result['containers']['app_one']['status'], 'failed')

    def test_finished_ledger_reverified_after_service_restart_before_email(self):
        request = self.ready()
        a.recover(self.ctx, request)
        restarted = w.Monitor(self.directory/'state.json', now=140, boot='boot-test')
        restarted.sample(observation(), 150)
        restarted.sample(observation(), 165)
        self.docker.containers['app_one']['running'] = False
        result = a.recover(self.ctx, restarted.app_request())
        self.assertFalse(result['all_verified'])
        self.assertEqual(len(self.docker.changes), 3)
        restarted.app_result(result)
        self.assertIn('Applications require attention', restarted.state['pending'][0]['subject'])

    def test_known_unsafe_direct_storage_stops_even_when_metadata_looks_healthy(self):
        request = self.ready()
        self.ctx.verify_main.side_effect = w.Unsafe('Aborted ext4 journal')
        result = a.recover(self.ctx, request)
        self.assertTrue(result['interrupted'])
        self.assertIn('Aborted ext4 journal', result['reason'])
        self.assertEqual(self.docker.changes, [])

    def test_reboot_during_applications_requires_new_direct_storage_proof(self):
        self.ready()
        restarted = w.Monitor(self.directory/'state.json', now=0, boot='new-boot')
        self.assertFalse(restarted.state['incident']['result']['main'])
        self.ctx.boot_id = lambda: 'new-boot'
        stop = restarted.stop_request(0)
        self.assertIsNotNone(stop)
        restarted.stop_result(a.stop_selected(self.ctx, stop, self.docker))
        restarted.sample(observation(), 0)
        restarted.sample(observation(), 15)
        result = a.recover(self.ctx, restarted.app_request())
        self.assertTrue(result['storage_verified'])
        restarted.app_result(result)
        self.assertIn('restored after reboot', restarted.state['pending'][0]['subject'])

    def test_cancelled_worker_still_holding_lock_reports_reserved_action_accurately(self):
        request = self.ready()
        def crash(name): raise KeyboardInterrupt()
        self.docker.after_change = crash
        with self.assertRaises(KeyboardInterrupt): a.recover(self.ctx, request)
        with (self.directory/'applications.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result = a.interrupted(self.ctx,request['incident'],self.monitor.state['incident']['applications'],'Interrupted')
        self.assertEqual(result['containers']['app_one']['action_count'],1)
        self.assertEqual(result['containers']['app_one']['status'],'failed')
        self.assertIn('ledger_warning',result)


class TrackingTests(Temp):
    def test_healthy_startup_and_normal_boot_never_request_application_recovery(self):
        self.monitor.sample(observation(), 0)
        self.monitor.sample(observation(), 15)
        self.assertIsNone(self.monitor.app_request())
        self.assertIsNone(self.monitor.state['incident'])
        self.assertEqual(self.monitor.state['pending'], [])

    def test_detection_only_inspects_and_preserves_storage_wait(self):
        self.outage()
        self.assertEqual(self.monitor.state['incident']['due'], 90)
        self.assertEqual(self.docker.changes, [])
        self.assertIsNone(self.monitor.app_request())
        self.assertEqual(set(self.monitor.state['incident']['applications']['detected']['containers']), set(a.APPS))

    def test_snapshot_preceding_outage_retains_running_app_after_exit(self):
        self.monitor.sample(observation(), 0)
        self.monitor.sample(observation(), 15)
        self.monitor.capture_result({'incident': None}, a.capture(self.ctx, self.docker))
        self.docker.containers['app_one']['running'] = False
        self.monitor.sample(observation(False), 30)
        self.monitor.sample(observation(False), 45)
        request = self.monitor.capture_request(45)
        self.monitor.capture_result(request, a.capture(self.ctx, self.docker))
        app = self.monitor.state['incident']['applications']
        self.assertFalse(app['detected']['containers']['app_one']['running'])
        self.assertTrue(a.plan(app)['app_one']['running'])

    def test_stale_or_previous_boot_snapshot_is_not_used(self):
        captured = a.capture(self.ctx, self.docker)
        self.assertIsNone(a.incident_state(captured, 46, 'boot-test')['baseline'])
        self.assertIsNone(a.incident_state(captured, 20, 'different')['baseline'])

    def test_unavailable_live_identity_prevents_a_restart(self):
        self.docker.inspect_fail = set(a.APPS)
        result = a.recover(self.ctx, self.ready())
        self.assertEqual(self.docker.changes, [])
        self.assertFalse(result['all_verified'])

    def test_interrupted_incident_capture_is_not_repeated_later(self):
        self.monitor.sample(observation(False), 0)
        self.monitor.sample(observation(False), 15)
        self.assertIsNotNone(self.monitor.capture_request(15))
        restarted = w.Monitor(self.directory/'state.json', now=30, boot='boot-test')
        self.assertIsNone(restarted.capture_request(30))
        self.assertEqual(restarted.state['incident']['applications']['capture_phase'], 'done')

    def test_late_incident_capture_not_substituted_for_prior_state(self):
        self.monitor.sample(observation(False), 0)
        self.monitor.sample(observation(False), 15)
        self.assertIsNone(self.monitor.capture_request(31))
        self.assertIn('deadline', self.monitor.state['incident']['applications']['capture_error'])

    def test_single_email_waits_for_application_verification(self):
        request = self.ready()
        self.assertEqual(self.monitor.state['pending'], [])
        self.assertEqual(self.monitor.state['incident']['phase'], 'applications')
        result = a.recover(self.ctx, request)
        self.monitor.app_result(result)
        self.monitor.app_result(result)
        self.assertEqual(len(self.monitor.state['pending']), 1)

    def test_legacy_incident_does_not_acquire_new_application_actions(self):
        legacy = w.Monitor(self.directory/'legacy.json', now=0, boot='boot-test', application_tracking=False)
        legacy.sample(observation(False), 0)
        legacy.sample(observation(False), 15)
        upgraded = w.Monitor(self.directory/'legacy.json', now=30, boot='boot-test')
        self.assertNotIn('applications', upgraded.state['incident'])
        self.assertIsNone(upgraded.app_request())


class GuardTests(Temp):
    def test_internal_ssd_underlying_directory_rejected(self):
        with mock.patch.object(Path, 'is_symlink', return_value=False), \
             mock.patch.object(Path, 'stat', return_value=types.SimpleNamespace(st_mode=stat.S_IFDIR, st_dev=os.makedev(240,2), st_ino=1)), \
             mock.patch.object(self.ctx, 'read_rows', return_value=[]), \
             mock.patch.object(self.ctx, 'visible_mount', return_value={'target': '/', 'dev': '240:2'}):
            with self.assertRaises(a.AppError): self.real_source(self.ctx, 'app_one')

    def test_unsafe_direct_filesystem_proof_stops_all_actions(self):
        self.ctx.verify_main.side_effect = w.Unsafe('Aborted journal')
        with self.assertRaises(a.StorageLost): self.real_source(self.ctx, 'app_one')

    def test_source_symlink_is_rejected(self):
        with mock.patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaisesRegex(a.AppError, 'Symlink'): self.real_source(self.ctx, 'app_one')

    def test_container_identity_validation_is_independent_of_storage_mapping(self):
        for key, bad in [('RW',False), ('Propagation','rshared'), ('Type','volume'), ('Destination','/elsewhere')]:
            value = self.docker.inspect('app_one')
            value['mounts'][0][key] = bad
            with self.subTest(key=key): a.validate_container('app_one',value)

    def test_namespace_inode_mount_identity_and_rw_guards(self):
        # Use the real namespace verifier, isolated from this fixture's mock.
        spec = importlib.util.spec_from_file_location('namespace_only', HERE.parent/'src/usb_storage_watch/apps.py')
        real = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(real)
        real.configure(w.SETTINGS["docker"])
        root = '1 0 0:1 / / rw - overlay overlay rw\n'
        mount = '2 1 240:17 /app_one-uploads /var/www/html/storage/app/shares rw - ext4 /dev/sdb1 rw\n'
        current = self.docker.inspect('app_one')
        for text, ino, okay in [(root+mount,123,True), (root+mount,456,False),
              (root+mount.replace('240:17','240:2'),123,False),
              (root+mount.replace('/dev/sdb1 rw','/dev/sdb1 ro'),123,False)]:
            with mock.patch.object(Path,'read_text',return_value=text), \
                 mock.patch.object(Path,'stat',return_value=types.SimpleNamespace(st_dev=os.makedev(240,17),st_ino=ino)):
                if okay: real.namespace_proof(self.ctx,'app_one',current,('240:17',os.makedev(240,17),123))
                else:
                    with self.assertRaises(real.AppError): real.namespace_proof(self.ctx,'app_one',current,('240:17',os.makedev(240,17),123))

    def test_preflight_only_inspects_and_verifies_never_restarts(self):
        self.docker.containers['app_two']['running'] = False
        result = a.preflight(self.ctx, self.docker)
        self.assertEqual(self.docker.changes, [])
        self.assertEqual(set(result),set(a.APPS))
        self.assertNotIn('app_two',self.docker.accesses)

    def test_existing_recovery_lock_prevents_overlapping_app_worker(self):
        with (self.directory/'recovery.lock').open('a') as operation, (self.directory/'monitor.lock').open('a') as monitor:
            fcntl.flock(operation,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with mock.patch.object(w,'STATE_DIR',self.directory), mock.patch.object(w,'assert_internal_state'), \
                 mock.patch.object(a,'recover') as recover:
                with self.assertRaises(BlockingIOError), mock.patch.object(w,'require_configuration'): w.execute_applications({'lock_fd':monitor.fileno()})
            recover.assert_not_called()


class RuntimeTests(Temp):
    def run_loop(self, application=False, loss_at=None):
        if application:
            self.ready()
            self.monitor.state['incident']['applications']['phase'] = 'ready'
            self.monitor.commit(self.monitor.state)
        self.clock.now = 135 if application else 0
        start, end = self.clock.now, self.clock.now + 90
        samples, jobs, mails, cancellations = [], [], [], []
        parent = self
        class Stop:
            def is_set(self): return parent.clock.now >= end
            def wait(self, duration):
                parent.clock.sleep(max(0,duration))
                return self.is_set()
        def snapshot():
            samples.append(parent.clock.now)
            return observation(loss_at is None or parent.clock.now < loss_at)
        class Job:
            def __init__(self, argv, payload, timeout, **kw):
                self.kind = argv[-1]
                self.start = parent.clock.now
                jobs.append((self.kind,self.start,timeout))
                self.proc = types.SimpleNamespace(poll=lambda:0)
                if self.kind == '_apps-capture':
                    self.duration = 0.5
                    result = a.capture(parent.ctx,parent.docker)
                elif self.kind == '_apps-stop':
                    self.duration = .5
                    result = a.stop_selected(parent.ctx, payload, parent.docker)
                elif self.kind == '_apps-recover':
                    self.duration = 45
                    result = {'complete':True,'interrupted':False,'all_verified':True,'containers':{}}
                else:
                    raise AssertionError('Unexpected worker '+self.kind)
                self.output = io.BytesIO(json.dumps(result).encode())
            def poll(self): return True if parent.clock.now-self.start >= self.duration else None
            def cancel(self): cancellations.append(self.kind)
            def close(self): self.output.close()
        class Mail:
            def __init__(self,payload):
                self.event_id=payload['id']
                self.proc=types.SimpleNamespace(poll=lambda:0)
                mails.append(payload)
            def poll(self): return True
            def close(self): pass
            def cancel(self): pass
        with mock.patch.object(w,'Monitor',return_value=self.monitor), \
             mock.patch.object(w,'snapshot',side_effect=snapshot), \
             mock.patch.object(w,'STATE_DIR',self.directory), mock.patch.object(w,'BOOT_GRACE',0), \
             mock.patch.object(w,'clock_now',side_effect=lambda:self.clock.now), \
             mock.patch.object(w,'config_load',return_value={'automatic_recovery':True,'usb_reset_enabled':True}), \
             mock.patch.object(w,'refresh_docker_settings',return_value=w.SETTINGS), \
             mock.patch.object(w,'Worker',Job), mock.patch.object(w,'Delivery',Mail):
            w.monitor_loop(Stop(),42)
        return start,end,samples,jobs,mails,cancellations

    def test_15_second_monitoring_and_one_email_during_slow_application_worker(self):
        start,end,samples,jobs,mails,_=self.run_loop(application=True)
        for when in range(int(start),int(end),15): self.assertIn(when,samples)
        self.assertEqual(len([j for j in jobs if j[0]=='_apps-recover']),1)
        self.assertEqual(len(mails),1)
        self.assertEqual(self.monitor.state['pending'],[])

    def test_live_observation_loss_cancels_worker_and_no_later_docker_stage(self):
        _,_,_,jobs,mails,cancel=self.run_loop(application=True,loss_at=165)
        self.assertIn('_apps-recover',cancel)
        self.assertEqual(len([j for j in jobs if j[0]=='_apps-recover']),1)
        self.assertEqual(len(mails),1)
        self.assertIn('RECOVERY FAILED',mails[0]['subject'])

    def test_normal_healthy_boot_only_captures_never_recovers_or_mails(self):
        _,_,_,jobs,mails,_=self.run_loop()
        self.assertTrue(jobs)
        self.assertTrue(all(j[0]=='_apps-capture' for j in jobs))
        self.assertEqual(mails,[])


class ApiTests(unittest.TestCase):
    def test_restart_uses_only_pinned_ids_and_bounded_grace(self):
        client = a.Docker()
        with mock.patch.object(client,'request') as request:
            client.change('app_one','1'*64,'restart')
            self.assertEqual(request.call_args.args,('POST','/containers/'+'1'*64+'/restart?t=30'))
            self.assertEqual(request.call_args.kwargs['timeout'],40)
            client.change('app_three','3'*64,'restart')
            self.assertEqual(request.call_args.kwargs['timeout'],70)
            with self.assertRaises(a.AppError): client.change('unrelated','1'*64,'restart')
            client.change('app_one','1'*64,'stop')
            self.assertEqual(request.call_args.args,('POST','/containers/'+'1'*64+'/stop?t=30'))
            self.assertEqual(request.call_args.kwargs['allowed_status'],(304,))
            with self.assertRaises(a.AppError): client.change('app_one','1'*64,'kill')

    def test_local_socket_api_timeout_and_error_redaction(self):
        client = a.Docker()
        conn = mock.Mock()
        conn.request.side_effect = socket.timeout('secret-do-not-print')
        with mock.patch.object(a,'LocalConnection',return_value=conn):
            with self.assertRaises(a.AppError) as error: client.request('GET','/containers/app_one/json')
        self.assertNotIn('secret',str(error.exception))
        conn.close.assert_called_once()

    def test_inspect_discards_environment_and_health_output(self):
        raw = {'Id':'1'*64,'Name':'/app_one','Config':{'Env':['PASSWORD=secret'],'Healthcheck':None},
            'State':{'Running':True,'Paused':False,'Restarting':False,'Dead':False,'StartedAt':'x','Pid':1,
                     'Health':{'Status':'healthy','Log':['secret']}},'Mounts':[]}
        client = a.Docker()
        with mock.patch.object(client,'request',return_value=raw): result=client.inspect('app_one')
        self.assertNotIn('secret',json.dumps(result))

    def test_access_command_has_inside_container_timeout_and_no_output(self):
        client=a.Docker()
        with mock.patch.object(client,'request',side_effect=[{'Id':'a'*64},None,{'Running':False,'ExitCode':0}]) as request:
            client.access('1'*64,'/fixed/path',lambda:None)
        payload=request.call_args_list[0].args[2]
        self.assertEqual(payload['Cmd'][:3],['timeout','8','sh'])
        self.assertFalse(payload['AttachStdout'])
        self.assertFalse(payload['Privileged'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
