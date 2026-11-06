# SPDX-License-Identifier: MIT
"""Automatic stop/unmount/remount/start with real Monitor and durable ledgers.

Kernel mounts, device presence, Docker and SMTP acceptance are simulated. These
regressions do not claim physical USB, live Docker or delivered-email coverage.
"""
import copy
import json
import unittest

from test_ui20_lifecycle import Machine, MAIN, IMAGE_MOUNT, BOOT


class AutomaticCleanupTests(unittest.TestCase):
    def setUp(self):
        self.machine = Machine(self)

    def finish_and_deliver(self):
        m = self.machine
        self.assertEqual(m.monitor.state['pending'], [])
        result = m.finish()
        self.assertTrue(result['all_verified'], result)
        self.assertEqual(len(m.monitor.state['pending']), 1)
        event = m.monitor.begin_attempt(m.now)
        self.assertIn('AUTO-RECOVERED', event['subject'])
        self.assertIn('selected_app', event['detail'])
        self.assertTrue(m.docker.containers['selected_app']['running'])
        m.events.append('email:accepted')
        m.monitor.finish_attempt(event['id'], True, m.now)
        self.assertEqual(m.monitor.state['pending'], [])

    def test_ui21_waiting_incident_without_old_proof_finishes_without_external_unmount(self):
        m = self.machine
        m.establish()
        m.disconnect()
        state = copy.deepcopy(m.monitor.state)
        incident_id = state['incident']['id']
        state['last_healthy']['main_mount_proof'] = None
        state['incident']['known_state']['main_mount_proof'] = None
        state['incident'].update(recovery_generation=21, legacy_mount_wait=True,
                                 legacy_no_write_resume=True, blocked=['main'])
        m.monitor.commit(state)
        m.returned(90)
        self.assertIsNone(m.monitor.state['incident']['known_state'].get('main_mount_proof'))
        result = m.recover()
        self.assertTrue(result['main'], result)
        self.assertTrue(result['dependent'], result)
        self.assertEqual(m.monitor.state['incident']['id'], incident_id)
        self.finish_and_deliver()
        self.assertEqual(m.events, ['docker:stop', 'unmount:image', 'unmount:disk',
                                    'mount:disk', 'mount:image', 'docker:start', 'email:accepted'])
        self.assertTrue(m.docker.containers['unrelated_app']['running'])

    def test_absent_drive_is_cleaned_before_wait_then_return_completes_same_incident(self):
        m = self.machine
        m.establish()
        m.disconnect()
        incident_id = m.monitor.state['incident']['id']
        m.sample(90)
        result = m.recover()
        self.assertTrue(result['waiting_device'], result)
        self.assertTrue(result['cleanup_complete'], result)
        self.assertEqual(m.events, ['docker:stop', 'unmount:image', 'unmount:disk'])
        self.assertEqual(m.monitor.state['incident']['attempts'], [])
        self.assertTrue(m.monitor.state['incident']['cleanup_attempts'])
        self.assertEqual(m.monitor.state['pending'], [])
        m.sample(120)
        self.assertIsNone(m.monitor.work_request(True, m.now))
        m.returned(150)
        self.assertTrue(m.recover()['main'])
        self.assertEqual(m.monitor.state['incident']['id'], incident_id)
        self.finish_and_deliver()
        self.assertEqual(m.events.count('unmount:disk'), 1)
        self.assertEqual(m.events.count('docker:stop'), 1)

    def test_fresh_failure_without_healthy_storage_history_uses_current_verified_tree(self):
        m = self.machine
        m.present = False
        m.main_row['super'].add('shutdown')
        m.sample(30)
        self.assertFalse(m.monitor.state.get('last_healthy'))
        capture = m.monitor.capture_request(m.now)
        self.assertIsNotNone(capture)
        m.monitor.capture_result(capture, m.w.apps.capture(m.w, m.docker))
        request = m.monitor.stop_request(m.now)
        self.assertIsNotNone(request)
        m.monitor.stop_result(m.w.apps.stop_selected(m.w, request, m.docker))
        m.returned(90)
        self.assertTrue(m.recover()['main'])
        self.finish_and_deliver()
        self.assertEqual(m.events[:3], ['docker:stop', 'unmount:image', 'unmount:disk'])

    def test_busy_unmount_never_mounts_or_starts_and_is_not_blindly_repeated(self):
        m = self.machine
        m.establish()
        m.disconnect()
        m.returned(90)
        command = m.command
        def busy(argv, **kwargs):
            if argv[0] == '/usr/bin/umount' and argv[-1] == MAIN:
                m.events.append('unmount:disk:busy')
                raise m.w.UnmountFailure('Synthetic target is busy')
            return command(argv, **kwargs)
        m.patch(m.w, 'command', busy)
        result = m.recover()
        self.assertFalse(result['main'], result)
        self.assertEqual(m.events, ['docker:stop', 'unmount:image',
                                    'unmount:disk:busy', 'unmount:disk:busy'])
        self.assertNotIn('mount:disk', m.events)
        self.assertNotIn('docker:start', m.events)
        self.assertTrue(all('AUTO-RECOVERED' not in item['subject'] for item in m.monitor.state['pending']))
        m.sample(165)
        request = m.monitor.work_request(True, m.now)
        if request:
            result = m.w.recovery_work(request, m.directory/'retry-receipt.json')
            m.monitor.work_result(request, result, m.now+1)
        # A completed EBUSY may have one bounded retry; an unknown write may not.
        self.assertEqual(m.events.count('unmount:disk:busy'), 2)
        self.assertNotIn('docker:start', m.events)
        self.assertFalse(m.docker.containers['selected_app']['running'])
        self.assertTrue(all('AUTO-RECOVERED' not in item['subject'] for item in m.monitor.state['pending']))

    def test_interrupted_unmount_intent_survives_service_restart_without_replay(self):
        m = self.machine
        m.establish()
        m.disconnect()
        m.returned(90)
        command = m.command
        def interrupted(argv, **kwargs):
            if argv[0] == '/usr/bin/umount' and argv[-1] == MAIN:
                m.events.append('unmount:disk:unknown')
                raise KeyboardInterrupt('Synthetic worker termination after durable intent')
            return command(argv, **kwargs)
        m.patch(m.w, 'command', interrupted)
        request = m.monitor.work_request(True, m.now)
        self.assertIsNotNone(request)
        with self.assertRaises(KeyboardInterrupt):
            m.w.recovery_work(request, m.directory/'recovery-receipt.json')
        receipt = json.loads((m.directory/'recovery-receipt.json').read_text())
        self.assertFalse(receipt['complete'])
        m.monitor = m.w.Monitor(m.directory/'state.json', now=120, boot=BOOT)
        m.sample(165)
        resumed = m.monitor.work_request(True, m.now)
        if resumed:
            result = m.w.recovery_work(resumed, m.directory/'resumed-receipt.json')
            m.monitor.work_result(resumed, result, m.now+1)
        self.assertEqual(m.events.count('unmount:disk:unknown'), 1)
        self.assertNotIn('mount:disk', m.events)
        self.assertNotIn('docker:start', m.events)
        self.assertTrue(all('AUTO-RECOVERED' not in item['subject'] for item in m.monitor.state['pending']))

    def test_foreign_child_mount_is_untouched(self):
        m = self.machine
        m.establish()
        m.disconnect()
        foreign = m.row('9', '2', '240:49', MAIN+'/foreign', '/dev/foreign')
        m.rows.append(foreign)
        m.returned(90)
        result = m.recover()
        self.assertFalse(result['main'], result)
        self.assertIn(foreign, m.rows)
        self.assertEqual(m.events, ['docker:stop'])
        self.assertFalse(m.docker.containers['selected_app']['running'])

    def test_external_container_resume_pauses_before_image_mount_and_preserves_completed_work(self):
        m = self.machine
        m.establish()
        m.disconnect()
        m.returned(90)
        command = m.command
        def resume_after_main_mount(argv, **kwargs):
            result = command(argv, **kwargs)
            if argv[0] == '/usr/bin/mount' and argv[-1] == MAIN:
                m.docker.containers['selected_app'].update(running=True, pid=1301,
                                                         started_at='external-resume')
                m.events.append('docker:external-resume')
            return result
        m.patch(m.w, 'command', resume_after_main_mount)
        result = m.recover()
        self.assertTrue(result['waiting_stop'], result)
        self.assertNotIn('mount:image', m.events)
        self.assertTrue(m.healthy())
        self.assertEqual(m.monitor.state['incident']['attempts'], [])
        paused = m.monitor.state['incident']['paused_attempts']
        self.assertEqual(len(paused), 1)
        self.assertTrue(any(action['target'] == 'main' and action['stage'] == 'returned'
                            for action in paused[0]['actions']))
        self.assertEqual(m.monitor.state['pending'], [])
        m.sample(105)
        request = m.monitor.stop_request(m.now)
        self.assertIsNotNone(request)
        stop = m.w.apps.stop_selected(m.w, request, m.docker)
        self.assertTrue(stop['all_stopped'], stop)
        m.monitor.stop_result(stop)
        m.sample(120)
        self.assertTrue(m.recover()['main'])
        self.finish_and_deliver()
        self.assertEqual(m.events, ['docker:stop', 'unmount:image', 'unmount:disk',
                                    'mount:disk', 'docker:external-resume', 'docker:stop',
                                    'mount:image', 'docker:start', 'email:accepted'])

    def test_container_using_only_physical_disk_recovers_without_image_actions(self):
        m = self.machine
        m.config['dependent']['enabled'] = False
        m.config['docker']['containers'][0].update(images=[], source=MAIN+'/data')
        m.docker.containers['selected_app']['mounts'][0]['Source'] = MAIN+'/data'
        m.rows = [row for row in m.rows if row['target'] != IMAGE_MOUNT]
        m.loop_attached = False
        m.w.configure(m.config)
        m.image_healthy = m.healthy
        m.establish()
        m.disconnect()
        m.returned(90)
        self.assertTrue(m.recover()['main'])
        self.finish_and_deliver()
        self.assertEqual(m.events, ['docker:stop', 'unmount:disk', 'mount:disk',
                                    'docker:start', 'email:accepted'])

    def test_disk_only_configuration_recovers_without_docker_or_images(self):
        m = self.machine
        m.config['dependent']['enabled'] = False
        m.config['docker'].update(enabled=False, containers=[])
        m.w.configure(m.config)
        m.patch(m.w, 'config_load', lambda: dict(automatic_recovery=True,
            usb_reset_enabled=False, docker_enabled=False, docker_containers=[]))
        m.patch(m.w.apps, 'READER', m.w.config_load)
        m.rows = [row for row in m.rows if row['target'] != IMAGE_MOUNT]
        m.loop_attached = False
        # The fixture's mount boundary asserts stopped state; this synthetic
        # container is no longer selected or connected to storage in this case.
        m.docker.containers['selected_app'].update(running=False, mounts=[])
        m.monitor = m.w.Monitor(m.directory/'state.json', now=0, boot=BOOT)
        m.sample(0)
        m.sample(15)
        m.present = False
        m.main_row['super'].add('shutdown')
        m.sample(30)
        m.sample(45)
        request = m.monitor.stop_request(m.now)
        if request:
            stop = m.w.apps.stop_selected(m.w, request, m.docker)
            self.assertTrue(stop['all_stopped'], stop)
            self.assertEqual(stop['containers'], {})
            m.monitor.stop_result(stop)
        m.returned(105)
        self.assertTrue(m.recover()['main'])
        m.sample(120)
        m.sample(135)
        request = m.monitor.app_request()
        if request:
            m.monitor.app_result(m.w.apps.recover(m.w, request, m.docker))
        self.assertEqual(m.events, ['unmount:disk', 'mount:disk'])
        self.assertEqual(m.monitor.state['status'], 'up')
        self.assertEqual(len(m.monitor.state['pending']), 1)


if __name__ == '__main__':
    unittest.main()
