# SPDX-License-Identifier: MIT
"""Legacy incident migration with real engine and Docker ledger transitions.

The device and Docker boundaries are simulated by the existing lifecycle
fixture; these tests do not claim physical hotplug or kernel mount coverage.
"""
import copy
import json
import unittest

from test_ui20_lifecycle import Machine, MAIN, IMAGE_MOUNT, BOOT


class LegacyRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.machine = Machine(self)

    def legacy(self, actions=None, usb_resets=0, keep_proof=False):
        m = self.machine
        m.establish()
        m.rows = [row for row in m.rows if row['target'] != IMAGE_MOUNT]
        m.loop_attached = False
        for row in m.rows:
            if row['target'] == MAIN:
                row['super'].add('shutdown')
        m.dev = '240:33'
        m.diskseq = 11
        current = m.w.snapshot()
        state = copy.deepcopy(m.monitor.state)
        previous = copy.deepcopy(state['last_healthy'])
        if not keep_proof:
            state['last_healthy'].pop('main_mount_proof', None)
            previous.pop('main_mount_proof', None)
        incident = m.w.new_incident('old failure', 'old conflict', 0, BOOT)
        incident.update(recovery_generation=18, phase='done', notified=True,
                        blocked=['main'], blocked_reason=current['detail'],
                        connection=current['connection'], known_state=previous,
                        usb_resets=usb_resets,
                        result=m.w.failed_result('Automatic main mount is disabled for this incident.'))
        incident['attempts'] = [dict(number=1, time='old time', boot=BOOT, status='failed',
                                    reason='Automatic main mount is disabled for this incident.',
                                    actions=actions or [])]
        state.update(status='down', incident=incident, first_bad=dict(time='old failure',
            at=30, boot=BOOT, detail=current['detail'], state=current),
            candidate=False, candidate_connection=current['connection'], count=2,
            sample_at=30, sample_boot=BOOT)
        m.monitor.commit(state)
        return incident['id']

    def stop(self):
        m = self.machine
        request = m.monitor.stop_request(m.now)
        self.assertIsNotNone(request)
        result = m.w.apps.stop_selected(m.w, request, m.docker)
        self.assertTrue(result['all_stopped'], result)
        m.monitor.stop_result(result)

    def test_supplied_legacy_failure_stops_and_recovers_without_manual_unmount(self):
        m = self.machine
        old_id = self.legacy()
        m.sample(45)
        incident = m.monitor.state['incident']
        new_id = incident['id']
        self.assertNotEqual(new_id, old_id)
        self.assertEqual(incident['legacy_recovery_resume'], old_id)
        archived = json.loads((m.directory/'incidents'/f'{old_id}.json').read_text())
        self.assertEqual(archived['attempts'][0]['actions'], [])
        self.assertIsNone(archived.get('stop'))
        self.assertIsNone(incident['known_state'].get('main_mount_proof'))
        self.stop()
        for when in (60, 75, 90):
            m.sample(when)
            self.assertIsNone(m.monitor.work_request(True, when))
            self.assertIsNone(m.monitor.stop_request(when))
        self.assertEqual(m.events, ['docker:stop'])
        self.assertEqual(m.monitor.state['incident']['attempts'], [])
        self.assertEqual(m.monitor.state['pending'], [])
        m.sample(120)
        self.assertEqual(m.monitor.state['incident']['id'], new_id)
        self.assertNotIn('legacy_mount_wait', m.monitor.state['incident'])
        result = m.recover()
        self.assertTrue(result['main'], result)
        self.assertTrue(result['dependent'], result)
        result = m.finish()
        self.assertTrue(result['all_verified'], result)
        self.assertEqual(m.events, ['docker:stop', 'unmount:disk', 'mount:disk', 'mount:image', 'docker:start'])
        self.assertEqual(len(m.monitor.state['pending']), 1)

    def test_service_restart_does_not_repeat_migration_or_container_stop(self):
        m = self.machine
        old_id = self.legacy()
        m.sample(45)
        self.stop()
        new_id = m.monitor.state['incident']['id']
        m.monitor = m.w.Monitor(m.directory/'state.json', now=60, boot=BOOT)
        m.sample(60)
        self.assertEqual(m.monitor.state['incident']['id'], new_id)
        self.assertEqual(len(list((m.directory/'incidents').glob('*.json'))), 1)
        self.assertTrue((m.directory/'incidents'/f'{old_id}.json').exists())
        self.assertIsNone(m.monitor.stop_request(60))
        m.sample(150)
        self.assertTrue(m.recover()['main'])
        self.assertTrue(m.finish()['all_verified'])
        self.assertEqual(m.events.count('docker:stop'), 1)

    def test_prior_usb_reset_budget_is_retained(self):
        m = self.machine
        self.legacy(usb_resets=1)
        m.sample(45)
        self.stop()
        m.sample(120)
        request = m.monitor.work_request(True, m.now, usb_enabled=True)
        self.assertEqual(request['usb_resets'], 1)
        self.assertEqual(m.monitor.state['incident']['usb_resets'], 1)

    def test_uncertain_prior_write_is_not_migrated(self):
        m = self.machine
        old_id = self.legacy(actions=[dict(target='main', stage='intent')])
        m.sample(45)
        self.assertEqual(m.monitor.state['incident']['id'], old_id)
        self.assertIsNone(m.monitor.stop_request(45))
        self.assertIsNone(m.monitor.work_request(True, 150))
        self.assertEqual(m.events, [])

    def test_automatic_mount_off_keeps_container_stopped_without_unmount(self):
        m = self.machine
        self.legacy()
        m.sample(45)
        self.stop()
        m.sample(120)
        self.assertIsNone(m.monitor.work_request(False, m.now))
        self.assertEqual(m.monitor.state['incident']['attempts'], [])
        self.assertEqual(m.events, ['docker:stop'])

    def test_unclassified_mount_conflict_does_not_authorize_cleanup(self):
        m = self.machine
        self.legacy()
        m.sample(45)
        self.stop()
        snapshot = m.w.snapshot()
        m.monitor.sample(snapshot | dict(unsafe=True, mount_state='conflict',
                                        detached_shutdown_mount=None,
                                        stale_conflict_only=False), now=120)
        request = m.monitor.work_request(True, 120)
        if request:
            result = m.w.recovery_work(request, m.directory/'recovery-receipt.json')
            self.assertFalse(result['main'], result)
        self.assertEqual(m.events, ['docker:stop'])

    def test_existing_valid_healthy_proof_can_use_normal_known_cleanup(self):
        m = self.machine
        self.legacy(keep_proof=True)
        m.sample(45)
        self.stop()
        self.assertNotIn('legacy_mount_wait', m.monitor.state['incident'])
        m.sample(120)
        result = m.recover()
        self.assertTrue(result['main'], result)
        self.assertEqual(m.events[:3], ['docker:stop', 'unmount:disk', 'mount:disk'])

    def test_incident_proof_is_used_if_last_healthy_lacks_it(self):
        m = self.machine
        self.legacy(keep_proof=True)
        state = copy.deepcopy(m.monitor.state)
        state['last_healthy'].pop('main_mount_proof')
        m.monitor.commit(state)
        m.sample(45)
        self.assertNotIn('legacy_mount_wait', m.monitor.state['incident'])
        self.assertTrue(m.monitor.state['incident']['known_state']['main_mount_proof'])

    def test_upgrade_while_absent_cleans_then_waits_for_return_and_completes(self):
        m = self.machine
        self.legacy()
        m.present = False
        m.sample(45)
        self.stop()
        new_id = m.monitor.state['incident']['id']
        m.sample(120)
        result = m.recover()
        self.assertTrue(result['waiting_device'], result)
        self.assertTrue(result['cleanup_complete'], result)
        self.assertEqual(m.events, ['docker:stop', 'unmount:disk'])
        m.present = True
        m.sample(150)
        self.assertEqual(m.monitor.state['incident']['id'], new_id)
        self.assertTrue(m.recover()['main'])
        self.assertTrue(m.finish()['all_verified'])
        self.assertEqual(m.events.count('docker:stop'), 1)
        self.assertEqual(m.events.count('docker:start'), 1)

    def test_fresh_classification_of_occupied_mount_resumes_without_external_release(self):
        m = self.machine
        self.legacy()
        current = m.w.snapshot()
        current.pop('detached_shutdown_mount', None)
        current.pop('stale_conflict_only', None)
        m.now = 45
        m.monitor.sample(current, now=45)
        self.assertIsNone(m.monitor.stop_request(m.now))
        self.assertIsNone(m.monitor.work_request(True, 150))
        self.assertEqual(m.events, [])
        # A subsequent complete observation identifies the configured failed
        # mount. The worker now cleans it automatically after the verified stop.
        m.sample(165)
        self.stop()
        m.sample(225)
        self.assertTrue(m.recover()['main'])
        self.assertTrue(m.finish()['all_verified'])

    def test_old_mount_released_before_upgrade_uses_fresh_safe_observation(self):
        m = self.machine
        self.legacy()
        m.rows = [row for row in m.rows if row['target'] != MAIN]
        m.sample(45)
        self.stop()
        self.assertNotIn('main', m.monitor.state['incident']['blocked'])
        self.assertNotIn('legacy_mount_wait', m.monitor.state['incident'])
        m.sample(120)
        self.assertTrue(m.recover()['main'])
        self.assertTrue(m.finish()['all_verified'])


if __name__ == '__main__':
    unittest.main()
