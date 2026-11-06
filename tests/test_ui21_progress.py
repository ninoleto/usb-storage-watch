# SPDX-License-Identifier: MIT
"""Earlier legacy progress fixtures now display automatic failed-mount cleanup."""
import unittest
from unittest.mock import patch

from gui_fixture import load

b = load('web_broker')


class LegacyMountProgressTests(unittest.TestCase):
    def setUp(self):
        self.c = b.s.default()
        self.c['disk']['uuid'] = '11111111-1111-4111-8111-111111111111'
        self.c['recovery']['mount'] = True
        self.state = dict(status='down', sample_boot='boot', sample_at=100,
                          incident=dict(id='incident', phase='wait1', boot='boot', due=160,
                                        attempts=[], legacy_mount_wait=True,
                                        stop=dict(phase='done', result=dict(all_stopped=True))))
        self.probe = dict(healthy=False, detected=True, mount_state='conflict',
                          stale_conflict_only=True,
                          detached_shutdown_mount=dict(boot='boot', mount=dict(dev='8:33')))

    def progress(self, active='active'):
        with patch.object(b.w, 'boot_id', return_value='boot'):
            return b.recovery_progress(self.c, self.state, self.probe,
                                       dict(ActiveState=active), 100)

    def test_confirmed_stop_precedes_automatic_release_and_recovery_order(self):
        result = self.progress()
        self.assertEqual(result['code'], 'waiting')
        self.assertEqual(result['title'], 'Automatic mount recovery scheduled')
        self.assertIn('unmount the failed images and disk', result['detail'])
        self.assertIn('No manual unmount command is needed.', result['detail'])
        self.assertIn('recover and mount the disk, mount selected images, then start the containers', result['detail'])
        self.assertEqual(result['wait_seconds'], 60)

    def test_stop_still_pending_is_shown_instead_of_false_stopped_claim(self):
        self.state['incident']['stop'] = dict(phase='pending')
        result = self.progress()
        self.assertEqual(result['code'], 'stopping')
        self.assertNotIn('are stopped', result['detail'])

    def test_failed_stop_keeps_exact_reason_before_mount_release(self):
        self.state['incident']['stop'] = dict(phase='pending', result=dict(
            all_stopped=False, containers={'files': dict(status='uncertain', reason='Docker stop is unconfirmed.')}))
        result = self.progress()
        self.assertEqual(result['code'], 'waiting_stop')
        self.assertIn('Docker stop is unconfirmed.', result['detail'])

    def test_without_stop_receipt_does_not_claim_containers_stopped(self):
        self.state['incident'].pop('stop')
        result = self.progress()
        self.assertEqual(result['title'], 'Automatic mount recovery scheduled')
        self.assertNotIn('containers are stopped', result['detail'])

    def test_disabled_automatic_recovery_requires_enabling_it(self):
        self.c['recovery']['mount'] = False
        result = self.progress()
        self.assertEqual(result['title'], 'Automatic recovery is off')
        self.assertIn('Enable Automatic recovery', result['detail'])
        self.assertNotIn('normal unmount', result['detail'])

    def test_disconnected_disk_does_not_claim_it_has_returned(self):
        self.probe['detected'] = False
        result = self.progress()
        self.assertEqual(result['title'], 'Automatic mount recovery scheduled')
        self.assertNotIn('disk has returned', result['detail'])

    def test_cleared_wait_resumes_normal_recovery_progress(self):
        self.state['incident'].pop('legacy_mount_wait')
        self.probe['mount_state'] = 'unmounted'
        self.probe.pop('detached_shutdown_mount')
        result = self.progress()
        self.assertEqual(result['title'], 'Recovery scheduled')
        self.assertEqual(result['wait_seconds'], 60)

    def test_inactive_monitor_never_promises_automatic_recovery(self):
        result = self.progress('inactive')
        self.assertEqual(result['code'], 'disabled')
        self.assertIn('No automatic recovery is running.', result['detail'])

    def test_foreign_live_mount_has_no_unmount_instruction(self):
        self.probe.pop('detached_shutdown_mount')
        self.probe['stale_conflict_only'] = False
        self.probe['mount_detail'] = 'The configured folder is occupied by another live filesystem.'
        result = self.progress()
        self.assertEqual(result['title'], 'Waiting for the mount conflict to be resolved')
        self.assertIn(self.probe['mount_detail'], result['detail'])
        self.assertNotIn('normal unmount', result['detail'])
        self.assertNotIn('earlier version', result['detail'])

    def test_unknown_identity_has_no_unmount_instruction_even_with_stale_candidate(self):
        self.probe.pop('stale_conflict_only')
        self.probe['detail'] = 'The current device identity could not be verified.'
        result = self.progress()
        self.assertEqual(result['title'], 'Waiting for the mount conflict to be resolved')
        self.assertIn(self.probe['detail'], result['detail'])
        self.assertNotIn('normal unmount', result['detail'])
        self.assertNotIn('earlier version', result['detail'])

    def test_stale_flag_without_live_candidate_has_no_unmount_instruction(self):
        self.probe.pop('detached_shutdown_mount')
        result = self.progress()
        self.assertEqual(result['title'], 'Waiting for the mount conflict to be resolved')
        self.assertNotIn('normal unmount', result['detail'])

    def test_running_cleanup_has_local_automatic_progress(self):
        self.state['incident']['phase'] = 'running'
        result = self.progress()
        self.assertEqual(result['code'], 'running')
        self.assertEqual(result['title'], 'Releasing failed mounts')
        self.assertIn('automatically', result['detail'])

    def test_missing_disk_cleanup_does_not_wait_for_return_first(self):
        self.probe['detected'] = False
        self.probe.pop('stale_conflict_only')
        result = self.progress()
        self.assertEqual(result['title'], 'Automatic mount recovery scheduled')
        self.assertIn('unmount the failed images and disk', result['detail'])


if __name__ == '__main__':
    unittest.main()
