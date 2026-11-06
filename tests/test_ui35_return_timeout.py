# SPDX-License-Identifier: MIT
"""Real monitor/ledgers; simulated storage, Docker, clocks and SMTP acceptance."""
import copy
import json
import unittest
from unittest.mock import patch
from test_ui20_lifecycle import Machine, BOOT, CONTAINER
import test_ui30_controls as guards
from test_ui30_controls import incident, ID
from gui_fixture import load


class ReturnLifecycle(unittest.TestCase):
    def setUp(self):
        self.m = Machine(self)
        self.m.establish(); self.m.disconnect()

    def clean(self):
        self.m.sample(90)
        self.assertTrue(self.m.recover()['cleanup_complete'])

    def expire(self):
        self.m.sample(330)
        i = self.m.monitor.state['incident']
        self.assertEqual(i['phase'], 'return_failed')
        self.assertTrue(i['return_deadline']['reported_at'])
        return i

    def test_never_returns_records_one_failure_and_keeps_attempt_budget(self):
        self.clean(); before = copy.deepcopy(self.m.monitor.state['incident'])
        i = self.expire()
        self.assertEqual(i['attempts'], before['attempts'])
        self.assertEqual(i['cleanup_attempts'], before['cleanup_attempts'])
        self.assertEqual(i['usb_resets'], before['usb_resets'])
        for now in range(345, 600, 15):
            self.m.sample(now)
            self.assertIsNone(self.m.monitor.work_request(True, now))
            self.assertIsNone(self.m.monitor.stop_request(now))
            self.assertIsNone(self.m.monitor.app_request())
        queued = self.m.monitor.state['pending']
        self.assertEqual(len(queued), 1)
        self.assertIn('RECOVERY FAILED', queued[0]['subject'])
        self.assertIn('Drive return timeout', queued[0]['subject'])
        self.assertFalse(self.m.docker.containers['selected_app']['running'])
        self.assertTrue(self.m.docker.containers['unrelated_app']['running'])
        self.assertEqual(self.m.events.count('docker:stop'), 1)
        self.assertEqual(self.m.events.count('docker:start'), 0)

    def test_return_before_or_exactly_on_deadline_avoids_timeout(self):
        self.clean(); self.m.returned(330)
        self.assertFalse(self.m.monitor.state['incident']['return_deadline'].get('reported_at'))
        self.assertTrue(self.m.recover()['main']); self.assertTrue(self.m.finish()['all_verified'])
        self.assertEqual(len(self.m.monitor.state['pending']), 1)
        self.assertIn('AUTO-RECOVERED', self.m.monitor.state['pending'][0]['subject'])

    def test_return_after_failure_resumes_same_incident_once_with_history(self):
        self.clean(); i = self.expire(); identity = i['id']; failure = copy.deepcopy(i['return_deadline'])
        self.m.returned(390); self.assertTrue(self.m.recover()['main']); self.assertTrue(self.m.finish()['all_verified'])
        i = self.m.monitor.state['incident']
        self.assertEqual(i['id'], identity); self.assertEqual(i['return_deadline']['event_id'], failure['event_id'])
        self.assertEqual(len(self.m.monitor.state['pending']), 2)
        for now in range(435, 600, 15): self.m.sample(now)
        self.assertEqual(len(self.m.monitor.state['pending']), 2)
        self.assertEqual(self.m.events.count('docker:start'), 1); self.assertEqual(self.m.events.count('docker:stop'), 1)
        self.assertEqual(len(self.m.monitor.state['incident']['attempts']), 1)

    def test_service_restart_retains_deadline_and_expired_receipt(self):
        self.clean(); self.m.now = 180
        self.m.monitor = self.m.w.Monitor(self.m.directory/'state.json', now=180, boot=BOOT)
        self.assertEqual(self.m.monitor.state['incident']['return_deadline']['remaining'], 150)
        self.expire(); event = self.m.monitor.state['pending'][0]['id']; self.m.now = 400
        self.m.monitor = self.m.w.Monitor(self.m.directory/'state.json', now=400, boot=BOOT)
        self.m.sample(405)
        self.assertEqual([v['id'] for v in self.m.monitor.state['pending']], [event])

    def test_pre_ui35_saved_incident_uses_original_confirmation_not_upgrade_time(self):
        self.clean(); s = copy.deepcopy(self.m.monitor.state); s['incident'].pop('return_deadline')
        self.m.monitor.commit(s); self.m.now = 400
        self.m.monitor = self.m.w.Monitor(self.m.directory/'state.json', now=400, boot=BOOT)
        self.assertEqual(self.m.monitor.state['incident']['return_deadline']['remaining'], 0)
        self.m.sample(405)
        self.assertEqual(len(self.m.monitor.state['pending']), 1)
        self.assertEqual(self.m.monitor.state['incident']['phase'], 'return_failed')

    def test_reboot_does_not_reset_budget_or_notification(self):
        self.clean(); self.m.now = 400
        self.m.monitor = self.m.w.Monitor(self.m.directory/'state.json', now=20, boot='new-boot')
        self.assertEqual(self.m.monitor.state['incident']['return_deadline']['remaining'], 0)
        self.m.monitor.sample(self.m.w.snapshot(), now=25, wall='2026-01-01T00:06:45+00:00')
        self.assertEqual(len(self.m.monitor.state['pending']), 1)
        self.assertEqual(self.m.monitor.state['incident']['id'], self.m.monitor.state['pending'][0]['detail'].split('Incident: ')[1].split('\n')[0])
        self.assertEqual(self.m.monitor.state['incident']['attempts'], [])

    def test_disabled_notifications_record_once_without_later_retroactive_alert(self):
        self.clean(); self.m.w.SETTINGS['notifications']['enabled'] = False; self.expire()
        self.assertEqual(self.m.monitor.state['pending'], [])
        self.assertEqual(self.m.monitor.state['incident']['return_deadline']['notification'], 'disabled')
        self.m.w.SETTINGS['notifications']['enabled'] = True; self.m.sample(345)
        self.assertEqual(self.m.monitor.state['pending'], [])

    def test_delivery_failure_retries_same_logical_event(self):
        self.clean(); self.expire(); monitor = self.m.monitor
        event = monitor.begin_attempt(1000); monitor.finish_attempt(event['id'], False, 1001)
        self.m.sample(345)
        self.assertEqual(len(monitor.state['pending']), 1); self.assertFalse(monitor.ready(1060)); self.assertTrue(monitor.ready(1061))
        again = monitor.begin_attempt(1061); self.assertEqual(again['id'], event['id'])
        self.assertEqual(again['attempts'], 2); monitor.finish_attempt(event['id'], True, 1062)
        self.assertEqual(monitor.state['incident']['return_deadline']['notification'], 'sent')
        self.m.sample(360); self.assertEqual(monitor.state['pending'], [])

    def test_timeout_does_not_interrupt_reserved_worker_or_repeat_alert(self):
        self.m.sample(90); req = self.m.monitor.work_request(True, 90)
        self.m.sample(330); self.assertEqual(self.m.monitor.state['incident']['phase'], 'running')
        result = self.m.w.recovery_work(req, self.m.directory/'recovery-receipt.json')
        self.m.monitor.work_result(req, result, 331)
        self.assertEqual(self.m.monitor.state['incident']['phase'], 'return_failed')
        self.m.sample(345); self.assertEqual(len(self.m.monitor.state['pending']), 1)

    def test_later_failed_attempt_does_not_duplicate_timeout_notification(self):
        self.clean(); self.expire(); self.m.returned(390)
        request = self.m.monitor.work_request(True, 390)
        self.m.monitor.work_result(request, dict(main=False, dependent=False, actions=[], detected=True,
            reason='Synthetic guarded refusal', dependent_reason='Unavailable', blocked=[], mounts=[]), 391)
        self.assertEqual(len(self.m.monitor.state['pending']), 1)
        self.assertEqual(self.m.monitor.state['incident']['phase'], 'done')

    def test_stop_failure_is_not_described_as_stopped(self):
        s = copy.deepcopy(self.m.monitor.state); s['incident']['stop']['result']['all_stopped'] = False
        self.m.monitor.commit(s); self.expire()
        self.assertIn('could not all be confirmed stopped', self.m.monitor.state['pending'][0]['detail'])
        self.assertIsNone(self.m.monitor.work_request(True, 345))


class ClockAndSettings(unittest.TestCase):
    def setUp(self): self.clock = load('return_deadline')
    def fresh(self):
        i = dict(confirmed_at='2026-01-01T00:00:00+00:00')
        t = self.clock.epoch(i['confirmed_at']); self.clock.advance(i, 5, 100, 'boot', t)
        return i, t
    def test_monotonic_progress_wall_rollback_and_settings_do_not_extend(self):
        i,t = self.fresh(); self.clock.advance(i, 99, 160, 'boot', t-3600)
        self.assertEqual(i['return_deadline']['remaining'], 240)
        self.clock.advance(i, 99, 400, 'boot', t-3360)
        self.assertEqual(i['return_deadline']['remaining'], 0)
    def test_reboot_accounts_for_downtime_and_clock_uncertainty(self):
        i,t = self.fresh(); self.clock.advance(i, 5, 160, 'boot', t+60)
        self.clock.advance(i, 5, 10, 'new', t+240)
        self.assertEqual(i['return_deadline']['remaining'], 60)
        self.clock.advance(i, 5, 1, 'third', t-1)
        self.assertEqual(i['return_deadline']['remaining'], 0)
    def test_forward_jump_expires_and_read_only_projection_does_not_write(self):
        i,t = self.fresh(); before = copy.deepcopy(i)
        self.assertEqual(self.clock.status(i, 101, 'boot', t+10000)['remaining_seconds'], 0)
        self.assertEqual(i, before)
    def test_invalid_or_future_confirmation_never_grants_full_new_window(self):
        for value in ('invalid', '2030-01-01T00:00:00+00:00'):
            i = dict(confirmed_at=value); self.clock.advance(i, 5, 100, 'boot', 1767225600)
            self.assertEqual(i['return_deadline']['remaining'], 0)
    def test_additive_default_validated_range_and_storage_digest_compatibility(self):
        s = load('settings'); w = load('engine'); c = s.default(); c['recovery'].pop('return_timeout_minutes')
        old = w.storage_config_digest(c); result = s.validate(c, allow_unconfigured=True)
        self.assertEqual(result['recovery']['return_timeout_minutes'], 5); self.assertEqual(old, w.storage_config_digest(result))
        for invalid in (0,1441,True,1.5):
            result['recovery']['return_timeout_minutes'] = invalid
            with self.assertRaises(s.ConfigError):s.validate(result, allow_unconfigured=True)


class TimeoutAdmission(unittest.TestCase):
    setUp = guards.ManualGuard.setUp
    data = guards.ManualGuard.data
    run_action = guards.ManualGuard.run_action
    # Reuse real authenticated manual endpoint fixtures, without duplicating the
    # inherited suite in this class's run.
    def test_timeout_and_late_failed_attempt_deny_stale_manual_commands(self):
        clock=load('return_deadline'); i=dict(confirmed_at='2026-01-01T00:00:00+00:00')
        clock.advance(i,5,0,'synthetic-boot',1767225600)
        i['return_deadline'].update(reported_at='2026-01-01T00:05:00+00:00',remaining=0)
        for phase in ('return_failed','done'):
            incident(self.f.main,phase,[ID],return_deadline=i['return_deadline'],latest=dict(healthy=False,detected=False))
            for action in ('start','stop','restart'):
                reply=self.run_action(action);self.assertEqual(reply['status'],400)
                self.assertIn('Drive has not returned' if phase=='return_failed' else 'Required storage is unavailable',reply['error'])
        self.assertEqual(self.docker.posts,[])

    def test_terminal_timeout_still_verifies_selected_images_and_pinned_storage(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        b=self.b;guard=b.common.module('app_control');boot=b.common.module('boot_start')
        c=b.configuration();c['docker'].update(enabled=True,containers=[dict(container_id=ID,images=['image'])])
        w=SimpleNamespace(SETTINGS=c,verify_main=Mock(),verify_dependent=Mock(side_effect=ValueError('Image missing')),
                          settings=SimpleNamespace(storage_images=lambda *_:[dict(uuid='image')]))
        original=b.common.module
        with patch.object(boot,'engine',return_value=w),patch.object(b.common,'module',side_effect=lambda name,*args:boot if name=='boot_start' else original(name,*args)):
            self.assertFalse(guard.timeout_storage_ready(b,[('legacy',c)],ID))
            w.verify_dependent.side_effect=None
            self.assertTrue(guard.timeout_storage_ready(b,[('legacy',c)],ID))
            self.assertFalse(guard.timeout_storage_ready(b,[('legacy',c)],'b'*64))
            c['docker']['containers'][0]['images']=[];w.verify_dependent.reset_mock()
            self.assertTrue(guard.timeout_storage_ready(b,[('legacy',c)],ID))
            w.verify_dependent.assert_not_called()


class ProgressAndHistory(unittest.TestCase):
    def test_backend_remaining_and_timestamped_timeout_history(self):
        import tempfile
        from pathlib import Path
        b=load('web_broker');clock=b.common.module('return_deadline');c=b.s.default()
        c['disk']['uuid']='11111111-1111-4111-8111-111111111111';c['recovery']['mount']=True
        i=dict(id='incident',phase='wait1',boot='boot',due=115,attempts=[],confirmed_at='2026-01-01T00:00:00+00:00',first_failure='2026-01-01T00:00:00+00:00',stop=dict(phase='done',result=dict(all_stopped=True)))
        t=clock.epoch(i['confirmed_at']);clock.advance(i,5,100,'boot',t)
        state=dict(status='down',sample_boot='boot',sample_at=160,incident=i);probe=dict(healthy=False,detected=False)
        with patch.object(b.w,'boot_id',return_value='boot'),patch.object(clock.time,'time',return_value=t+60):
            p=b.recovery_progress(c,state,probe,dict(ActiveState='active'),160)
            self.assertEqual(p['drive_return']['remaining_seconds'],240);self.assertIn('4:00 remaining',p['detail'])
            i['phase']='return_failed';i['return_deadline'].update(remaining=0,reported_at='2026-01-01T00:05:00+00:00',outcome='Recovery failed — drive return timeout',notification='queued')
            p=b.recovery_progress(c,state,probe,dict(ActiveState='active'),160)
            self.assertEqual(p['code'],'return_failed');self.assertEqual(p['detail'],clock.MESSAGE)
        with tempfile.TemporaryDirectory() as directory:
            h=b.History(Path(directory)/'history.sqlite3');h.capture_incident(i);h.capture_incident(i)
            i.update(phase='done',outcome='Recovered later',completed_at='2026-01-01T00:08:00+00:00');h.capture_incident(i)
            with h.connect() as db:rows=db.execute('SELECT id,at,title FROM events ORDER BY id').fetchall()
            self.assertEqual(len(rows),2);self.assertEqual(rows[0][1],i['first_failure'])
            self.assertEqual(rows[1][1],'2026-01-01T00:05:00+00:00');self.assertIn('timeout',rows[1][2])

    def test_timing_save_uses_existing_authenticated_revision_and_preserves_other_values(self):
        from gui_fixture import Machine as GUI
        m=GUI();self.addCleanup(m.stack.close);b=m.b;config=b.s.default();config['disk']['uuid']=m.uuid;b.cli.save(m.config,config)
        before=b.configuration();data=dict(revision=b.s.digest(before),timings=dict(recovery=dict(return_timeout_minutes=7)))
        b.timing_settings(data);after=b.configuration();expected=copy.deepcopy(before);expected['recovery']['return_timeout_minutes']=7
        self.assertEqual(after,expected)
        with self.assertRaisesRegex(ValueError,'Settings changed'):b.timing_settings(data)

if __name__=='__main__':unittest.main()
