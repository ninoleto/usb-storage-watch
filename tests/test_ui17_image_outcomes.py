# SPDX-License-Identifier: MIT
"""Partial image setup is a visible outcome, never permission to format again.

Only private temporary files are created. Allocation, formatting, mounting,
service changes and filesystem identity are simulated at their OS boundaries.
"""
import copy
from contextlib import ExitStack
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_ui3_images_with_monitoring as monitoring_fixture

images = monitoring_fixture.images


class ImageOutcomeTests(unittest.TestCase):
    def setUp(self):
        monitoring_fixture.ImageMonitoringTests.setUp(self)
        self.image_dir = self.root / 'images'
        self.image_dir.mkdir(mode=0o700)
        self.mount_dir = self.root / 'mounted-image'
        self.mount_dir.mkdir(mode=0o700)
        self.image_path = self.image_dir / 'backups.img'
        self.item = dict(name='backups', uuid='33333333-3333-4333-8333-333333333333',
                         image=str(self.image_path), mountpoint=str(self.mount_dir), enabled=True)
        self.saved = {'images': []}
        self.b.configuration = lambda: copy.deepcopy(self.saved)
        self.b.s.storage_images = lambda c, enabled=False: c['images']
        self.b.w.MOUNT = str(self.root)
        self.b.w.MANUAL_MOUNT = False
        self.b.w.configure = Mock()
        self.b.w.disk_proof = Mock()
        self.b.w.recover_image = Mock()
        self.b.w.verify_dependent = Mock()
        mount_device = self.mount_dir.stat().st_dev
        self.b.w.visible_mount = lambda _rows, _target: dict(dev=f'{os.major(mount_device)}:{os.minor(mount_device)}')
        self.b.preparation.run = Mock(return_value=SimpleNamespace(stdout='', returncode=0))
        self.b.owner = (1000, 1000)
        self.b.w.read_rows = lambda: []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.proposal = self.stack.enter_context(patch.object(images, 'proposal'))
        self.stack.enter_context(patch.object(images, 'rooted', side_effect=self.open_directory))
        self.stack.enter_context(patch.object(images, 'probe', side_effect=self.observation))
        self.save = self.stack.enter_context(patch.object(images, 'save_configuration', side_effect=self.save_config))
        self.stack.enter_context(patch.object(images, 'entries', side_effect=lambda _b: copy.deepcopy(self.saved['images'])))
        self.stack.enter_context(patch.object(images, 'permission_plan', return_value={}))
        self.stack.enter_context(patch.object(images, 'apply_permission_targets'))
        self.stack.enter_context(patch.object(images, 'verify_policy_access'))
        self.stack.enter_context(patch.object(images.os, 'fchown'))
        # Production runs as root. Keep the fixture independent of the test
        # runner's uid without changing ownership of any real host file.
        real_fstat = os.fstat
        self.stack.enter_context(patch.object(images.os, 'fstat', side_effect=lambda fd:
            SimpleNamespace(**{key: (0 if key == 'st_uid' else getattr(real_fstat(fd), key))
                               for key in ('st_uid', 'st_mode', 'st_dev', 'st_ino', 'st_size')})))

    def open_directory(self, _b, directory, create=False):
        path = Path(directory)
        self.assertTrue(path.is_relative_to(self.root), 'fixture must never access host storage')
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY)

    def observation(self, _b=None, _path=None):
        info = self.image_path.stat()
        return dict(uuid=self.item['uuid'], inode=info.st_ino, device=info.st_dev, size=info.st_size)

    def save_config(self, _b, config, old=None, item=None):
        self.saved = copy.deepcopy(config)

    def plan(self, mode='create'):
        if mode == 'existing':
            self.image_path.write_bytes(b'existing image fixture; preserve contents')
            observed = self.observation()
            size = observed['size']
        else:
            observed = None
            size = 1024
        config = {'images': [copy.deepcopy(self.item)]}
        chosen = dict(mode=mode, item=copy.deepcopy(self.item), old=None, observed=observed,
                      size=size, config=config, owner=self.b.owner, data={'mode': mode},
                      revision='rev', token='test-consent', created=time.monotonic())
        self.proposal.side_effect = lambda _b, _data: copy.deepcopy(chosen)
        return chosen

    def apply(self, chosen):
        return images.apply(self.b, chosen, {'token': chosen['token'], 'confirm': True})

    def assert_partial(self, result, *, created, registered):
        self.assertIs(result['ok'], False)
        self.assertIs(result['changed'], True)
        self.assertIs(result['image_created'], created)
        self.assertIs(result['registered'], registered)
        self.assertEqual(result['image']['uuid'], self.item['uuid'])
        self.assertTrue(result['message'])

    def test_new_file_allocation_failure_reports_retained_unregistered_file(self):
        chosen = self.plan()
        self.b.preparation.run.side_effect = ValueError('Synthetic allocation failure')
        result = self.apply(chosen)
        self.assert_partial(result, created=True, registered=False)
        self.assertTrue(self.image_path.is_file())
        self.assertEqual(self.saved, {'images': []})
        self.save.assert_not_called()
        self.b.w.recover_image.assert_not_called()
        self.assertEqual([call.args[0][0] for call in self.b.preparation.run.call_args_list], ['/usr/bin/fallocate'])

    def test_new_file_mount_failure_reports_saved_registration_and_retains_file(self):
        self.monitoring = True
        chosen = self.plan()
        self.b.w.recover_image.side_effect = ValueError('Synthetic mount failure')
        result = self.apply(chosen)
        self.assert_partial(result, created=True, registered=True)
        self.assertTrue(self.image_path.is_file())
        self.assertEqual(self.saved['images'][0]['uuid'], self.item['uuid'])
        self.assertTrue(self.monitoring, 'partial setup must still restore prior monitoring')
        self.assertEqual([call.args[0][0] for call in self.b.preparation.run.call_args_list],
                         ['/usr/bin/fallocate', '/usr/sbin/mkfs.ext4'])

    def test_existing_image_mount_failure_reports_saved_registration_without_creation(self):
        chosen = self.plan('existing')
        before = self.image_path.read_bytes()
        self.b.w.recover_image.side_effect = ValueError('Synthetic mount failure')
        result = self.apply(chosen)
        self.assert_partial(result, created=False, registered=True)
        self.assertEqual(self.image_path.read_bytes(), before)
        self.assertEqual(self.saved['images'][0]['uuid'], self.item['uuid'])
        self.b.preparation.run.assert_not_called()

    def test_repeat_create_cannot_reformat_file_left_by_partial_setup(self):
        chosen = self.plan()
        self.b.w.recover_image.side_effect = ValueError('Synthetic mount failure')
        self.assert_partial(self.apply(chosen), created=True, registered=True)
        self.image_path.write_bytes(b'retained content after interrupted setup')
        before = self.image_path.read_bytes()
        inode = self.image_path.stat().st_ino
        # Even a stale/replayed review that bypassed proposal's existence check
        # must be stopped by the real O_EXCL open before another format command.
        with self.assertRaises((ValueError, FileExistsError)):
            self.apply(chosen)
        self.assertEqual(self.image_path.read_bytes(), before)
        self.assertEqual(self.image_path.stat().st_ino, inode)
        self.assertEqual(sum(call.args[0][0] == '/usr/sbin/mkfs.ext4'
                             for call in self.b.preparation.run.call_args_list), 1)
        self.assertEqual(self.save.call_count, 1)

    def test_refusal_before_file_creation_remains_error_with_no_changes(self):
        chosen = self.plan()
        self.b.preparation.revision.return_value = 'other-revision'
        with self.assertRaisesRegex(ValueError, 'Settings changed'):
            self.apply(chosen)
        self.assertFalse(self.image_path.exists())
        self.assertEqual(self.saved, {'images': []})
        self.b.preparation.run.assert_not_called()
        self.save.assert_not_called()

    def test_failed_new_file_open_does_not_claim_creation_or_overwrite_existing_file(self):
        chosen = self.plan()
        self.image_path.write_bytes(b'already present')
        with self.assertRaises((ValueError, FileExistsError)):
            self.apply(chosen)
        self.assertEqual(self.image_path.read_bytes(), b'already present')
        self.b.preparation.run.assert_not_called()
        self.save.assert_not_called()

    def test_existing_image_success_keeps_success_contract(self):
        chosen = self.plan('existing')
        result = self.apply(chosen)
        self.assertIsNot(result.get('ok'), False)
        self.assertIn('saved, mounted and verified', result['message'])
        self.assertEqual(result['images'][0]['uuid'], self.item['uuid'])
        self.b.preparation.run.assert_not_called()

    def fail_monitor_resume(self):
        self.monitoring = True
        original_command = self.b.command

        def command(argv, timeout=10):
            if argv[1] == 'start':
                self.commands.append(tuple(argv))
                raise ValueError('Synthetic monitor start failure')
            return original_command(argv, timeout)

        self.b.command = command

    def test_monitor_resume_failure_preserves_successful_creation_outcome(self):
        chosen = self.plan()
        self.fail_monitor_resume()
        result = self.apply(chosen)
        self.assert_partial(result, created=True, registered=True)
        self.assertIs(result['monitoring_resumed'], False)
        self.assertIn('monitoring could not resume', result['message'].lower())
        self.assertTrue(self.image_path.is_file())
        self.assertEqual(self.saved['images'][0]['uuid'], self.item['uuid'])
        self.assertFalse(self.monitoring)
        self.assertEqual([cmd[1] for cmd in self.commands], ['stop', 'start'])
        self.assertEqual(sum(call.args[0][0] == '/usr/sbin/mkfs.ext4'
                             for call in self.b.preparation.run.call_args_list), 1)

    def test_monitor_resume_failure_preserves_partial_mount_failure_details(self):
        chosen = self.plan()
        self.fail_monitor_resume()
        self.b.w.recover_image.side_effect = ValueError('Synthetic mount failure')
        result = self.apply(chosen)
        self.assert_partial(result, created=True, registered=True)
        self.assertIs(result['monitoring_resumed'], False)
        self.assertIn('Synthetic mount failure', result['message'])
        self.assertIn('monitoring could not resume', result['message'].lower())
        self.assertTrue(self.image_path.is_file())
        self.assertFalse(self.monitoring)
        self.assertEqual(self.save.call_count, 1)
        self.assertEqual(sum(call.args[0][0] == '/usr/sbin/mkfs.ext4'
                             for call in self.b.preparation.run.call_args_list), 1)


if __name__ == '__main__':
    unittest.main()
