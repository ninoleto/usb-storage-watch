# SPDX-License-Identifier: MIT
"""USB inspection regression: prove descriptor identity without ignoring denial."""
import ctypes
import contextlib
import os
from pathlib import Path
import stat
import types
import unittest
from unittest import mock

import test_usb_recovery as base

w, u = base.w, base.u


class DescriptorProofTests(base.Temp):
    def setUp(self):
        super().setUp()
        for name in ('port', 'devices', 'block', 'proc', 'uuid'):
            (self.directory / name).mkdir()
        (self.directory / 'port/state').write_text('not attached\n')
        (self.directory / 'port/disable').write_text('0\n')
        (self.directory / 'proc/swaps').write_text('Filename Type Size Used Priority\n')
        self.proc = self.directory / 'proc/10'
        self.proc.mkdir()
        (self.proc / 'fd').mkdir()
        (self.proc / 'maps').write_text('')
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for attr, path in [('PORT', 'port'), ('DEVICE', 'absent-device'), ('USB_DEVICES', 'devices'),
                           ('SYS_BLOCK', 'block'), ('PROC', 'proc'), ('UUID_DIR', 'uuid')]:
            stack.enter_context(mock.patch.object(u, attr, self.directory / path))
        stack.enter_context(mock.patch.object(u, 'port_identity'))
        (self.proc / 'fdinfo').mkdir()
        (self.proc / 'root').symlink_to('/')
        self.file = self.directory / 'unrelated-file'
        self.file.write_text('unrelated')
        self.fd = self.proc / 'fd/3'
        self.fd.symlink_to(self.file)
        value = self.file.stat()
        self.info = value
        self.dev = f'{os.major(value.st_dev)}:{os.minor(value.st_dev)}'
        self.mounts = f'1 0 {self.dev} / / rw - ext4 /dev/unrelated rw\n'
        (self.proc / 'mountinfo').write_text(self.mounts)
        (self.proc / 'fdinfo/3').write_text(f'pos:\t0\nflags:\t0100000\nmnt_id:\t1\nino:\t{value.st_ino}\n')

    def denied(self):
        original = Path.stat
        def inspect(path, *args, **kwargs):
            if path == self.fd:
                raise PermissionError('simulated procfs descriptor denial')
            return original(path, *args, **kwargs)
        return mock.patch.object(Path, 'stat', inspect)

    def proof(self):
        return u.verify_unrelated_descriptor(self.ctx, self.proc, self.fd,
            str(self.file), {'240:17'}, w.parse_mounts(self.mounts))

    def test_positive_mount_and_inode_proof_allows_unrelated_descriptor(self):
        with self.denied():
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_wrong_inode_is_not_permission_to_skip_descriptor(self):
        (self.proc / 'fdinfo/3').write_text('mnt_id: 1\nino: 1\n')
        with self.denied(), self.assertRaisesRegex(w.Unsafe, 'Process 10, descriptor 3'):
            u.require_absent_and_isolated(self.ctx, self.request)

    def test_unknown_mount_id_fails_closed(self):
        (self.proc / 'fdinfo/3').write_text(f'mnt_id: 999\nino: {self.info.st_ino}\n')
        self.assertFalse(self.proof())

    def test_duplicate_or_incomplete_fdinfo_fails_closed(self):
        for text in ('mnt_id: 1\n', 'mnt_id: 1\nino: 2\nino: 2\n', 'mnt_id: x\nino: 1\n'):
            with self.subTest(text=text):
                (self.proc / 'fdinfo/3').write_text(text)
                self.assertFalse(self.proof())

    def test_open_raw_device_alias_remains_blocked(self):
        original = Path.stat
        def inspect(path, *args, **kwargs):
            if str(path) == str(self.proc / 'root') + str(self.file):
                return types.SimpleNamespace(st_dev=self.info.st_dev, st_ino=self.info.st_ino,
                    st_mode=stat.S_IFBLK, st_rdev=os.makedev(240, 17))
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'stat', inspect), self.assertRaisesRegex(w.Unsafe, 'block-device handle'):
            self.proof()

    def test_changed_descriptor_between_observations_is_not_verified(self):
        identity = u.descriptor_identity(self.proc, self.fd.name)
        with mock.patch.object(u, 'descriptor_identity', side_effect=[identity, identity | {'ino': '1'}]):
            self.assertFalse(self.proof())

    def test_changed_mount_between_observations_is_not_verified(self):
        (self.proc / 'mountinfo').write_text(self.mounts.replace(self.dev, '240:19'))
        self.assertFalse(self.proof())

    def test_removed_file_is_not_verified_from_fdinfo_alone(self):
        self.file.unlink()
        self.assertFalse(self.proof())

    def test_deleted_descriptor_is_not_verified_by_reused_path(self):
        self.assertFalse(u.verify_unrelated_descriptor(self.ctx, self.proc, self.fd,
            str(self.file) + ' (deleted)', {'240:17'}, w.parse_mounts(self.mounts)))

    def test_inotify_kernel_handle_does_not_need_filesystem_stat(self):
        self.fd.unlink()
        self.fd.symlink_to('anon_inode:inotify')
        with self.denied(), mock.patch.object(u, 'verify_unrelated_descriptor') as fallback:
            u.require_absent_and_isolated(self.ctx, self.request)
        fallback.assert_not_called()

    def test_unknown_anonymous_name_still_fails_closed(self):
        self.fd.unlink()
        self.fd.symlink_to('anon_inode:unknown-kind')
        with self.denied(), self.assertRaisesRegex(w.Unsafe, 'Process 10, descriptor 3'):
            u.require_absent_and_isolated(self.ctx, self.request)


class ActualKernelDescriptorTests(unittest.TestCase):
    def test_linux_inotify_descriptor_matches_positive_classifier(self):
        library = ctypes.CDLL(None, use_errno=True)
        if not hasattr(library, 'inotify_init1'):
            self.skipTest('Linux inotify unavailable')
        descriptor = library.inotify_init1(os.O_CLOEXEC)
        if descriptor < 0:
            self.skipTest('inotify unavailable in this runtime')
        try:
            self.assertTrue(u.kernel_only_fd_target(os.readlink(f'/proc/self/fd/{descriptor}')))
        finally:
            os.close(descriptor)


if __name__ == '__main__':
    unittest.main()
