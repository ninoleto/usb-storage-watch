# SPDX-License-Identifier: MIT
"""Repeated automatic recovery with reused kernel identities and durable receipts.

The Monitor, cleanup worker and Docker ledgers are real. Device/mount/Docker
boundaries and SMTP acceptance are simulated; no physical-host claim is made.
"""
import copy
import json
import unittest

from test_ui20_lifecycle import Machine, MAIN, IMAGE_MOUNT, BOOT


class RepeatedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.machine = Machine(self)

    def test_three_outages_reusing_mount_identities_recover_once_each_after_restart(self):
        m = self.machine
        original_rows = copy.deepcopy(m.rows)
        m.establish()
        incident_ids, mail_ids, receipts = [], [], []
        expected_cycle = ['docker:stop', 'unmount:image', 'unmount:disk',
                          'mount:disk', 'mount:image', 'docker:start', 'email:accepted']
        for cycle in range(3):
            if cycle:
                # A service restart preserves completed cleanup receipts.
                m.monitor = m.w.Monitor(m.directory/'state.json', now=m.now, boot=BOOT)
                # Kernel mount IDs and loop minors can be reused. Keep the
                # current physical attachment but deliberately reuse every
                # old ID/source/option; on cycle three its dev also matches.
                m.rows = copy.deepcopy(original_rows)
                next(row for row in m.rows if row['target'] == MAIN)['dev'] = m.dev
                m.loop = '7:8'
                m.loop_backing = m.dev
                m.loop_attached = True
                m.sample(m.now + 15)
                m.sample(m.now + 15)
                m.monitor.capture_result(dict(incident=None), m.w.apps.capture(m.w, m.docker))
            event_start = len(m.events)
            self.assertTrue(m.disconnect(m.now + 15)['all_stopped'])
            incident = m.monitor.state['incident']['id']
            self.assertNotIn(incident, incident_ids)
            incident_ids.append(incident)
            failed_tree = [m.w.mount_record(row) for row in m.rows if row['target'] in (MAIN, IMAGE_MOUNT)]
            if cycle:
                old_tree = receipts[0]['capture']['tree']
                self.assertEqual(failed_tree[1], old_tree[1])
                if cycle == 2:
                    self.assertEqual(failed_tree, old_tree)
            m.returned(m.now + 60)
            result = m.recover()
            self.assertTrue(result['main'], result)
            self.assertTrue(result['dependent'], result)
            receipt = json.loads((m.directory/'retained-mount-cleanup.json').read_text())
            self.assertEqual(receipt['incident'], incident)
            self.assertTrue(receipt['complete'])
            self.assertEqual(len(receipt['commands']), 2,
                             'A new outage must not inherit completed unmount commands.')
            self.assertTrue(all(item['removed'] for item in receipt['commands']))
            receipts.append(receipt)
            self.assertEqual(m.monitor.state['pending'], [])
            self.assertTrue(m.finish()['all_verified'])
            self.assertEqual(len(m.monitor.state['pending']), 1)
            event = m.monitor.begin_attempt(m.now)
            self.assertIn('AUTO-RECOVERED', event['subject'])
            self.assertNotIn(event['id'], mail_ids)
            mail_ids.append(event['id'])
            m.events.append('email:accepted')
            m.monitor.finish_attempt(event['id'], True, m.now)
            self.assertEqual(m.events[event_start:], expected_cycle)
            self.assertEqual(m.monitor.state['pending'], [])
            self.assertTrue(m.docker.containers['unrelated_app']['running'])
        archived_cleanup = [json.loads(path.read_text())
                            for path in (m.directory/'cleanup-history').glob('*.json')]
        for receipt in receipts[:-1]:
            self.assertIn(receipt, archived_cleanup)
        for incident in incident_ids[:-1]:
            archived = json.loads((m.directory/'incidents'/f'{incident}.json').read_text())
            self.assertEqual(archived['id'], incident)
            self.assertTrue(archived['notified'])
            self.assertTrue(archived['result']['main'])
        m.sample(m.now + 15)
        self.assertIsNone(m.monitor.stop_request(m.now))
        self.assertIsNone(m.monitor.app_request())
        self.assertEqual(m.events, expected_cycle * 3)
        self.assertEqual(len(set(mail_ids)), 3)

    def test_current_incident_uncertain_unmount_still_blocks_after_worker_restart(self):
        m = self.machine
        m.establish()
        m.disconnect()
        m.returned(90)
        request = m.monitor.work_request(True, m.now)
        self.assertIsNotNone(request)
        original_command = m.command
        def interrupted(argv, **kwargs):
            if argv[0] == '/usr/bin/umount' and argv[-1] == MAIN:
                m.events.append('unmount:disk:unknown')
                raise KeyboardInterrupt('Synthetic lost worker after durable command intent')
            return original_command(argv, **kwargs)
        m.patch(m.w, 'command', interrupted)
        with self.assertRaises(KeyboardInterrupt):
            m.w.recovery_work(request, m.directory/'recovery-receipt.json')
        marker_path = m.directory/'retained-mount-cleanup.json'
        marker = marker_path.read_text()
        self.assertEqual(json.loads(marker)['phase'], 'intent')
        self.assertEqual(json.loads(marker)['incident'], request['incident'])
        m.monitor = m.w.Monitor(m.directory/'state.json', now=120, boot=BOOT)
        # Even direct replay of the same request must respect the durable
        # uncertain command; the Monitor's in-memory block is not sufficient.
        result = m.w.recovery_work(request, m.directory/'resumed-receipt.json')
        self.assertFalse(result['main'], result)
        self.assertEqual(result['actions'], [])
        self.assertIn('uncertain', result['reason'].lower())
        self.assertEqual(marker_path.read_text(), marker)
        self.assertEqual(m.events, ['docker:stop', 'unmount:image', 'unmount:disk:unknown'])
        self.assertFalse(m.docker.containers['selected_app']['running'])
        self.assertFalse(any('AUTO-RECOVERED' in event['subject'] for event in m.monitor.state['pending']))


if __name__ == '__main__':
    unittest.main()
