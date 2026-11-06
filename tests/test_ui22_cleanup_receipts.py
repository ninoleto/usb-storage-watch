# SPDX-License-Identifier: MIT
"""Focused receipt races use simulated mount/Docker boundaries only."""
import json
import unittest

from test_ui20_lifecycle import Machine, MAIN, IMAGE_MOUNT


class CleanupReceiptTests(unittest.TestCase):
    def setUp(self):
        self.m = Machine(self)
        self.m.establish()
        self.m.disconnect()
        self.m.returned(90)

    def resume_stop(self):
        m = self.m
        m.now += 1
        request = m.monitor.stop_request(m.now)
        self.assertIsNotNone(request)
        m.monitor.stop_result(m.w.apps.stop_selected(m.w, request, m.docker))
        m.sample(m.now + 15)

    def test_stop_race_before_umount_is_recorded_not_sent_and_resumes(self):
        m = self.m
        write = m.w.write_receipt
        raced = [False]
        def receipt(path, value):
            write(path, value)
            if path.name == 'retained-mount-cleanup.json' and value['phase'] == 'intent' and not raced[0]:
                raced[0] = True
                m.docker.containers['selected_app'].update(running=True, started_at='new-execution', pid=1400)
        m.patch(m.w, 'write_receipt', receipt)
        result = m.recover()
        self.assertTrue(result['waiting_stop'], result)
        self.assertEqual(m.events, ['docker:stop'])
        marker = json.loads((m.directory/'retained-mount-cleanup.json').read_text())
        self.assertEqual(marker['phase'], 'returned')
        self.assertIs(marker['commands'][-1]['sent'], False)
        self.assertTrue(m.w.storage_actions_settled(m.monitor.state['incident']['paused_attempts']))
        self.resume_stop()
        self.assertTrue(m.recover()['main'])
        self.assertEqual(m.events.count('unmount:disk'), 1)
        self.assertEqual(m.events.count('unmount:image'), 1)

    def test_pending_non_autoclear_loop_is_proven_and_detached_after_pause(self):
        m = self.m
        original = m.command
        def command(argv, **kwargs):
            result = original(argv, **kwargs)
            if argv[0] == '/usr/bin/umount' and argv[-1] == IMAGE_MOUNT:
                m.loop_attached = True
                m.docker.containers['selected_app'].update(running=True, started_at='new-execution', pid=1400)
            return result
        m.patch(m.w, 'command', command)
        result = m.recover()
        self.assertTrue(result['waiting_stop'], result)
        self.assertTrue(m.loop_attached)
        self.assertEqual(m.events, ['docker:stop', 'unmount:image'])
        self.resume_stop()
        self.assertTrue(m.recover()['main'])
        self.assertEqual(m.events, ['docker:stop', 'unmount:image', 'docker:stop',
            'detach:image', 'unmount:disk', 'mount:disk', 'mount:image'])

    def test_timed_out_umount_keeps_unknown_intent_and_never_replays(self):
        m = self.m
        original = m.command
        calls = []
        def command(argv, **kwargs):
            if argv[0] == '/usr/bin/umount':
                calls.append(argv)
                raise m.w.Unsafe('umount exceeded its 15s deadline; result uncertain.')
            return original(argv, **kwargs)
        m.patch(m.w, 'command', command)
        request = m.monitor.work_request(True, m.now)
        result = m.w.recovery_work(request, m.directory/'recovery-receipt.json')
        m.monitor.work_result(request, result, m.now + 1)
        self.assertFalse(result['main'])
        marker = json.loads((m.directory/'retained-mount-cleanup.json').read_text())
        self.assertEqual(marker['phase'], 'intent')
        with self.assertRaisesRegex(m.w.Unsafe, 'uncertain'):
            m.w.cleanup_failed_main(request, lambda *args: None)
        self.assertEqual(len(calls), 1)
        self.assertEqual(m.events, ['docker:stop'])


if __name__ == '__main__':
    unittest.main()
