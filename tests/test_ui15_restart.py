# SPDX-License-Identifier: MIT
"""Restart policy and polling-time evidence; isolated from real Docker/storage."""
from unittest.mock import patch
from test_apps import Temp, a, w, observation, storage_result
import test_ui12_applications as dependencies


class PollingEvidence(Temp):
    def long_outage(self, stopped_before=False):
        self.stack.enter_context(patch.object(w, 'INTERVAL', 900))
        self.stack.enter_context(patch.object(w, 'OBSERVATIONS', 3))
        for when in (0, 900, 1800):
            self.monitor.sample(observation(), when)
        self.clock.now = 1801
        self.docker.containers['app_one']['running'] = not stopped_before
        self.monitor.capture_result({'incident': None}, a.capture(self.ctx, self.docker))
        self.docker.containers['app_one']['running'] = False
        self.monitor.sample(observation(False), 2700)
        self.clock.now = 2700
        # UI20 captures and stops on the first failure; waiting until the old
        # third-observation confirmation would intentionally miss the deadline.
        request = self.monitor.capture_request(2700)
        self.assertIsNotNone(request)
        self.monitor.capture_result(request, a.capture(self.ctx, self.docker))
        stop = self.monitor.stop_request(2700)
        self.assertIsNotNone(stop)
        self.monitor.stop_result(a.stop_selected(self.ctx, stop, self.docker))
        self.docker.changes.clear()  # Assertions below concern the later start.
        for when in (3600, 4500):
            self.monitor.sample(observation(False), when)
        self.clock.now = 4500
        return self.monitor.state['incident']['applications']

    def finish_storage(self):
        returned = dict(observation(False), detected=True)
        self.monitor.sample(returned, 4560)
        request = self.monitor.work_request(True, 4560)
        self.assertIsNotNone(request)
        self.monitor.work_result(request, storage_result(), 4561)
        for when in (5400, 6300, 7200):
            self.monitor.sample(observation(), when)
        return self.monitor.app_request()

    def test_long_polling_keeps_pre_outage_running_evidence_through_confirmation(self):
        app = self.long_outage()
        self.assertTrue(a.plan(app)['app_one']['running'])
        self.assertFalse(app['detected']['containers']['app_one']['running'])
        result = a.recover(self.ctx, self.finish_storage())
        self.assertEqual(self.docker.changes[0][2], 'start')
        self.assertEqual(result['containers']['app_one']['status'], 'verified')
        self.assertIn('started after drive and selected-image recovery', result['containers']['app_one']['reason'])

    def test_selected_container_restarts_despite_stopped_baseline_with_long_polling(self):
        app = self.long_outage(stopped_before=True)
        self.assertFalse(a.plan(app)['app_one']['running'])
        result = a.recover(self.ctx, self.finish_storage())
        self.assertEqual(result['containers']['app_one']['status'], 'verified')
        self.assertIn('app_one', [row[0] for row in self.docker.changes])

    def test_baseline_timing_is_bounded_by_first_failure_not_confirmation(self):
        baseline = dict(boot='boot-test', at=1000, containers={})
        first = dict(boot='boot-test', at=1905)
        self.assertIsNotNone(a.incident_state(baseline, 5505, 'boot-test', first, 900)['baseline'])
        cases = [dict(first=dict(first, at=1906)), dict(first=dict(first, at=999)),
                 dict(first=dict(first, at=6000)), dict(first=dict(first, boot='previous')),
                 dict(first={}), dict(first=dict(first, at=float('nan'))),
                 dict(baseline=dict(baseline, at=float('inf'))),
                 dict(baseline=dict(baseline, at=True)),
                 dict(baseline=dict(baseline, boot='previous')), dict(interval=0)]
        for values in cases:
            with self.subTest(values=values):
                result = a.incident_state(values.get('baseline', baseline), 5505, 'boot-test',
                                          values.get('first', first), values.get('interval', 900))
                self.assertIsNone(result['baseline'])

    def test_recent_stopped_baseline_wins_over_running_incident_capture(self):
        baseline = a.capture(self.ctx, self.docker)
        baseline['containers']['app_one']['running'] = False
        app = a.incident_state(baseline, 1815, 'boot-test', dict(boot='boot-test', at=915), 900)
        app['detected'] = a.capture(self.ctx, self.docker)
        self.assertFalse(a.plan(app)['app_one']['running'])


class RestartStorageOrder(dependencies.StorageDependencies):

    def test_stopped_container_is_started_after_drive_proof_with_image_advice(self):
        self.image_ready = True
        trace = []
        self.ctx.verify_main.side_effect = lambda: trace.append('drive') or self.realdev
        self.ctx.verify_dependent.side_effect = lambda item: trace.append('image:' + item['name'])
        original = self.docker.change
        def change(name, identity, action):
            self.assertEqual(action, 'start')
            self.assertIn('drive', trace)
            trace.append('start:' + name)
            original(name, identity, action)
        self.docker.change = change
        result = a.recover(self.ctx, self.ready(), self.docker)
        self.assertEqual(result['containers']['app_two']['action'], 'start')
        self.assertIn('Container started after drive and selected-image recovery.', result['containers']['app_two']['reason'])
        self.assertTrue(result['all_verified'])

    def test_detected_image_loss_after_durable_intent_does_not_block_restart(self):
        self.image_ready = True
        original = a.save
        def save(ctx, value):
            original(ctx, value)
            if value['containers']['app_two']['status'] == 'intent':
                self.image_ready = False
        with patch.object(a, 'save', side_effect=save):
            result = a.recover(self.ctx, self.ready(), self.docker)
        self.assertIn('app_two', [row[0] for row in self.docker.changes])
        self.assertEqual(result['containers']['app_two']['status'], 'verified')
        self.assertEqual(result['containers']['app_two']['action_count'], 1)
        self.assertTrue(result['storage_verified'])
        self.assertEqual(result['containers']['app_three']['status'], 'verified')
