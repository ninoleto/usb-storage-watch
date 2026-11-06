# SPDX-License-Identifier: MIT
"""Real /proc mountinfo reader with synthetic namespaces and storage boundaries."""
import copy
import unittest

from test_ui20_lifecycle import Machine, MAIN, IMAGE_MOUNT, load


class CleanupNamespaceTests(unittest.TestCase):
    def setUp(self):
        m = self.m = Machine(self)
        m.establish()
        m.disconnect()
        self.old_main = copy.deepcopy(m.main_row)
        self.old_image = copy.deepcopy(m.image_row)
        m.returned(90)
        self.proc = m.directory/'synthetic-proc'
        (self.proc/'4321').mkdir(parents=True)
        self.namespace_calls = []
        # Machine normally isolates procfs. Restore the production reader,
        # redirecting only its proc root; use this engine's exception class.
        reader_module = load('engine')
        reader_module.Unsafe = m.w.Unsafe
        self.reader = reader_module.namespace_available
        def namespaces(dev, proc_root=None, allowed_mounts=()):
            self.namespace_calls.append(dev)
            return self.reader(dev, proc_root=self.proc, allowed_mounts=allowed_mounts)
        m.patch(m.w, 'namespace_available', namespaces)
        self.write_namespace([])

    def write_namespace(self, rows):
        def line(row):
            return ('{id} {parent} {dev} {root} {target} '.format(**row) + ','.join(sorted(row['vfs'])) +
                    ' - {fs} {source} '.format(**row) + ','.join(sorted(row['super'])) + '\n')
        (self.proc/'4321'/'mountinfo').write_text(''.join(line(row) for row in rows))

    def clone(self, row, target=None):
        result = copy.deepcopy(row)
        result.update(id=str(int(row['id']) + 800), parent=str(int(row['parent']) + 800))
        if target is not None:
            result['target'] = target
        return result

    def test_real_reader_reproduces_cross_namespace_id_refusal_with_precise_detail(self):
        self.write_namespace([self.clone(self.old_main)])
        with self.assertRaises(self.m.w.Unsafe) as caught:
            self.reader(self.old_main['dev'], self.proc, allowed_mounts=[self.old_main])
        detail = str(caught.exception)
        for item in (self.old_main['dev'], '4321', MAIN):
            self.assertIn(item, detail)
        self.assertNotIn('Returned device', detail)

    def assert_old_reference_recovers(self, namespace_row):
        m = self.m
        self.write_namespace([namespace_row])
        result = m.recover()
        self.assertTrue(result['main'], result)
        self.assertTrue(result['dependent'], result)
        self.assertNotIn(self.old_main['dev'], self.namespace_calls)
        self.assertIn(m.dev, self.namespace_calls)
        self.assertTrue(m.finish()['all_verified'])
        self.assertEqual(m.events, ['docker:stop', 'unmount:image', 'unmount:disk',
                                    'mount:disk', 'mount:image', 'docker:start'])
        self.assertEqual(len(m.monitor.state['pending']), 1)
        self.assertIn('AUTO-RECOVERED', m.monitor.state['pending'][0]['subject'])

    def test_cloned_old_mount_ids_do_not_block_ordinary_local_cleanup(self):
        self.assert_old_reference_recovers(self.clone(self.old_main))

    def test_old_device_bind_in_another_namespace_does_not_block_local_cleanup(self):
        self.assert_old_reference_recovers(self.clone(self.old_main, '/service/retained-storage'))

    def test_returned_live_device_in_another_namespace_still_blocks_remount(self):
        m = self.m
        external = m.row('910', '900', m.dev, '/service/live-storage', '/dev/returned-disk')
        self.write_namespace([external])
        result = m.recover()
        self.assertFalse(result['main'], result)
        self.assertEqual(m.events, ['docker:stop', 'unmount:image', 'unmount:disk'])
        self.assertIn(m.dev, self.namespace_calls)
        self.assertIn('4321', result['reason'])
        self.assertIn('/service/live-storage', result['reason'])

    def test_retained_loop_in_another_namespace_still_blocks_global_detach(self):
        m = self.m
        self.write_namespace([self.clone(self.old_image)])
        original = m.command
        def command(argv, **kwargs):
            result = original(argv, **kwargs)
            if argv[0] == '/usr/bin/umount' and argv[-1] == IMAGE_MOUNT:
                m.loop_attached = True  # Other namespace retains the loop.
            return result
        m.patch(m.w, 'command', command)
        result = m.recover()
        self.assertFalse(result['main'], result)
        self.assertEqual(m.events, ['docker:stop', 'unmount:image'])
        self.assertIn(self.old_image['dev'], self.namespace_calls)
        self.assertIn(self.old_image['dev'], result['reason'])
        self.assertIn('4321', result['reason'])
        self.assertTrue(m.loop_attached)

    def completed_ui22_failure(self, actions=None):
        m = self.m
        request = m.monitor.work_request(True, m.now)
        result = m.w.failed_result('Returned device is already mounted in a process namespace; retained binds must be released first.')
        result['actions'] = actions or []
        m.monitor.work_result(request, result, m.now + 1)
        state = copy.deepcopy(m.monitor.state)
        state['incident'].update(recovery_generation=22, usb_resets=1)
        state['incident']['known_state']['main_mount_proof'] = None
        state['last_healthy']['main_mount_proof'] = None
        m.monitor.commit(state)
        return state['incident']['id']

    def test_ui22_completed_no_action_refusal_migrates_once_and_preserves_usb_budget(self):
        m = self.m
        old_id = self.completed_ui22_failure()
        self.write_namespace([self.clone(self.old_main)])
        m.sample(105)
        fresh = m.monitor.state['incident']
        self.assertNotEqual(fresh['id'], old_id)
        self.assertEqual(fresh['recovery_generation'], 24)
        self.assertEqual(fresh['usb_resets'], 1)
        self.assertEqual(fresh['legacy_recovery_resume'], old_id)
        self.assertIsNone(fresh['known_state']['main_mount_proof'])
        self.assertTrue((m.directory/'incidents'/(old_id+'.json')).exists())
        stop = m.monitor.stop_request(m.now)
        m.monitor.stop_result(m.w.apps.stop_selected(m.w, stop, m.docker))
        m.sample(165)
        self.assertTrue(m.recover()['main'])
        self.assertEqual(m.events.count('docker:stop'), 1)

    def test_ui22_uncertain_or_completed_storage_action_does_not_get_upgrade_budget(self):
        for stage in ('intent', 'returned'):
            with self.subTest(stage=stage):
                old_id = self.completed_ui22_failure([dict(target='main', stage=stage, time='old', detail='old')])
                self.m.sample(self.m.now + 15)
                self.assertEqual(self.m.monitor.state['incident']['id'], old_id)
                self.assertEqual(self.m.monitor.state['incident']['recovery_generation'], 22)
                if stage == 'intent':
                    # Restore the fixture's waiting incident for the independent
                    # completed-action variant without exercising any command.
                    state = copy.deepcopy(self.m.monitor.state)
                    state['incident'].update(phase='wait1', attempts=[], notified=False, blocked=[], due=self.m.now)
                    self.m.monitor.commit(state)


if __name__ == '__main__':
    unittest.main()
