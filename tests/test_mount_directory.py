# SPDX-License-Identifier: MIT
"""Real descriptor walks in a private tree; synthetic mount metadata only."""
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from gui_fixture import load

w = load('engine')
ROOT = '1 0 240:0 / / rw - ext4 /dev/system rw\n'
RUN = '2 1 0:17 / /run rw - tmpfs tmpfs rw\n'
TARGET = '/run/media/test/USW_TEST'


class BackingTests(unittest.TestCase):
    def test_existing_desktop_entry_can_recover_on_run_tmpfs(self):
        parent = w.recovery_backing(w.parse_mounts(ROOT + RUN), TARGET, '240:1')
        self.assertEqual(parent['target'], '/run')

    def test_root_backing_preserved(self):
        for target in ('/mnt/storage', '/media/test/disk'):
            self.assertEqual(w.recovery_backing(w.parse_mounts(ROOT + RUN), target, '240:1')['target'], '/')

    def test_rejects_other_filesystem_under_run(self):
        for fs in ('nfs', 'ext4', 'fuse', 'overlay'):
            with self.subTest(fs=fs), self.assertRaises(w.Unsafe):
                w.recovery_backing(w.parse_mounts(ROOT + RUN.replace('tmpfs tmpfs', fs + ' other')), TARGET, '240:1')

    def test_rejects_submount_readonly_stacked_and_unrelated_runtime_mounts(self):
        for value in [ROOT + RUN.replace('/run rw', '/run ro'), ROOT + RUN.replace('tmpfs rw', 'tmpfs ro'),
                      ROOT + RUN + '3 2 0:18 / /run/media rw - tmpfs tmpfs rw\n',
                      ROOT + RUN + '3 2 0:18 / /run rw - tmpfs tmpfs rw\n',
                      ROOT + RUN + f'3 2 240:8 / {TARGET}/nested rw - ext4 /dev/other rw\n']:
            with self.subTest(value=value), self.assertRaises(w.Unsafe):
                w.recovery_backing(w.parse_mounts(value), TARGET, '240:1')
        with self.assertRaises(w.Unsafe):
            w.recovery_backing(w.parse_mounts(ROOT + RUN), '/run/unrelated/disk', '240:1')

    def test_readonly_planning_ignores_only_verified_selected_live_mount(self):
        rows = w.parse_mounts(ROOT + RUN + f'3 2 240:1 / {TARGET} rw - ext4 /dev/usb rw\n')
        self.assertEqual(w.recovery_backing(rows, TARGET, '240:1', mounted=True)['target'], '/run')
        with self.assertRaises(w.Unsafe): w.recovery_backing(rows, TARGET, '240:1')


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.fd = os.open(self.path, os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.dev = self.path.stat().st_dev
        # Host tests run unprivileged; emulate root ownership only inside this
        # private tree. Opens, mkdir, no-follow, modes and contents remain real.
        original = os.fstat
        def info(fd):
            value = original(fd)
            return SimpleNamespace(st_uid=0, st_mode=value.st_mode, st_dev=value.st_dev)
        p = patch.object(w.os, 'fstat', side_effect=info)
        p.start(); self.addCleanup(p.stop)

    def walk(self, parts, create=False):
        return w.walk_mount_directory(self.fd, parts, self.dev, create)

    def test_planning_never_creates_missing_directory(self):
        self.walk(['media', 'account', 'drive'])
        self.assertEqual(list(self.path.iterdir()), [])

    def test_recreates_removed_desktop_directory_without_touching_data(self):
        self.walk(['media', 'account', 'drive'], create=True)
        drive = self.path / 'media/account/drive'
        drive.rmdir()  # UDisks cleanup can remove the empty directory.
        self.walk(['media', 'account', 'drive'], create=True)
        (drive / 'sentinel').write_bytes(b'keep data')
        self.walk(['media', 'account', 'drive'], create=True)
        self.assertEqual((drive / 'sentinel').read_bytes(), b'keep data')

    def test_refuses_symlink_and_regular_file_components(self):
        (self.path / 'link').symlink_to(self.path, target_is_directory=True)
        (self.path / 'file').write_text('keep')
        for part in ('link', 'file'):
            with self.subTest(part=part), self.assertRaises(OSError): self.walk([part, 'drive'], create=True)
        self.assertEqual((self.path / 'file').read_text(), 'keep')

    def test_writable_parent_or_final_directory_is_rejected_without_chmod(self):
        parent = self.path / 'parent'; parent.mkdir(); parent.chmod(0o777)
        for parts in (['parent'], ['parent', 'drive']):
            with self.assertRaises(w.Unsafe): self.walk(parts, create=True)
        self.assertEqual(parent.stat().st_mode & 0o777, 0o777)
        self.assertFalse((parent / 'drive').exists())

    def test_non_root_owner_and_wrong_backing_are_rejected(self):
        with patch.object(w.os, 'fstat', return_value=SimpleNamespace(st_uid=1000, st_mode=stat.S_IFDIR | 0o755, st_dev=self.dev)):
            with self.assertRaises(w.Unsafe): self.walk(['drive'], create=True)
        with self.assertRaises(w.Unsafe): w.walk_mount_directory(self.fd, ['drive'], self.dev + 1, True)
        self.assertEqual(list(self.path.iterdir()), [])


if __name__ == '__main__': unittest.main()
