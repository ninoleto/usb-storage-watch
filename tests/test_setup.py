# SPDX-License-Identifier: MIT
"""Setup preflight, mount consent, preservation and hardware status regressions."""
import subprocess
import unittest
from unittest.mock import Mock, patch
from gui_fixture import Machine, UUID, DESKTOP, STABLE


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.m = Machine()
        self.addCleanup(self.m.close)
        self.b = self.m.b

    def test_physical_virtual_unknown_and_detection_timeout(self):
        for code, output, kind in [(1, 'none\n', 'physical'), (0, 'vmware\n', 'virtual'), (0, 'docker\n', 'virtual'), (2, '', 'unknown'), (1, '', 'unknown')]:
            with self.subTest(kind=kind, output=output), patch.object(self.b.subprocess, 'run', return_value=Mock(returncode=code, stdout=output)):
                # Machine supplies a presentation fixture; test the real function from a fresh module.
                from gui_fixture import load
                self.assertEqual(load('web_broker').virtualization()['kind'], kind)
        with patch.object(self.b.subprocess, 'run', side_effect=subprocess.TimeoutExpired('detect', 5)):
            self.assertEqual(load('web_broker').virtualization()['kind'], 'unknown')

    def test_preview_is_read_only_and_proposes_stable_mount(self):
        plan = self.b.inspect_mount(UUID)
        self.assertEqual(plan['mountpoint'], STABLE)
        self.assertTrue(plan['temporary']); self.assertTrue(plan['transition']); self.assertTrue(plan['needs_entry'])
        self.assertEqual(self.m.fstab.read_text(), self.m.original)
        self.assertFalse(self.m.config.exists())
        self.assertEqual(list(self.m.state.iterdir()), [])
        self.assertFalse((self.m.root / 'mounts').exists())

    def test_desktop_aliases_are_temporary(self):
        for path in ['/run/media/test/disk', '/media/test/disk', '/run/custom/disk']:
            self.m.current = path
            self.assertTrue(self.b.inspect_mount(UUID)['temporary'])
            self.assertEqual(self.b.inspect_mount(UUID)['mountpoint'], STABLE)

    def test_prepare_requires_consent_and_unchanged_proposal(self):
        plan = self.b.inspect_mount(UUID)
        data = dict(uuid=UUID, revision=self.b.s.digest(self.b.configuration()), plan_token=plan['token'])
        with self.assertRaisesRegex(self.b.FieldError, 'Confirm'): self.b.prepare_mount(data)
        self.m.fstab.write_text(self.m.original + '# external edit\n')
        with self.assertRaisesRegex(self.b.FieldError, 'changed'): self.b.prepare_mount(data | dict(confirm=True))
        self.assertNotIn('UUID=', self.m.fstab.read_text())
        self.assertFalse(self.m.config.exists())

    def test_prepare_preserves_content_and_blocks_busy_desktop_until_released(self):
        plan = self.b.inspect_mount(UUID)
        result = self.b.prepare_mount(dict(uuid=UUID, revision=self.b.s.digest(self.b.configuration()), plan_token=plan['token'], confirm=True))
        self.assertFalse(result['plan']['needs_entry'])
        self.assertEqual(self.m.current, DESKTOP)
        self.assertTrue(self.m.fstab.read_text().startswith(self.m.original))
        self.assertEqual((self.m.disk_data / 'sentinel').read_bytes(), b'Existing filesystem contents\x00preserve me')
        self.assertFalse(self.m.config.exists())
        with self.assertRaisesRegex(self.b.FieldError, 'still mounted'):
            self.b.save_configuration(self.m.payload(), validate_only=True)
        self.m.current = ''  # Operator safely releases desktop mount; fixture does not execute unmount.
        self.b.save_configuration(self.m.payload(), validate_only=True)
        self.assertFalse(self.m.config.exists())
        self.b.save_configuration(self.m.payload())
        c = self.b.configuration()
        self.assertEqual(c['disk']['mountpoint'], STABLE)
        self.assertTrue(c['recovery']['mount'])
        self.assertFalse(c['usb']['enabled']); self.assertFalse(c['docker']['enabled']); self.assertFalse(c['notifications']['enabled'])
        self.assertEqual(self.m.fstab.read_text().count('UUID='), 1)

    def test_final_save_catches_new_desktop_conflict(self):
        self.m.current = ''
        plan = self.b.inspect_mount(UUID)
        data = self.m.payload(mount_token=plan['token'])
        self.b.save_configuration(data, validate_only=True)
        self.m.current = DESKTOP
        with self.assertRaisesRegex(self.b.FieldError, 'still mounted'): self.b.save_configuration(data)
        self.assertFalse(self.m.config.exists()); self.assertEqual(self.m.fstab.read_text(), self.m.original)

    def test_final_save_requires_consent_for_exact_preview(self):
        self.m.current = ''
        plan = self.b.inspect_mount(UUID)
        data = self.m.payload(mount_token=plan['token'])
        self.m.fstab.write_text(self.m.original + '# changed\n')
        with self.assertRaisesRegex(self.b.FieldError, 'proposal changed'): self.b.save_configuration(data)
        self.assertFalse(self.m.config.exists())
        self.assertNotIn('UUID=', self.m.fstab.read_text())

    def test_existing_entry_reused_unchanged_without_fstab_consent(self):
        self.m.current = '/mnt/existing'
        original = self.m.original + f'UUID={UUID} /mnt/existing ext4 defaults,nofail,noexec 0 0\n'
        self.m.fstab.write_text(original)
        plan = self.b.inspect_mount(UUID)
        self.assertFalse(plan['needs_entry'])
        payload = self.m.payload(); payload['confirmations'] = ['mount']
        self.b.save_configuration(payload)
        self.assertEqual(self.m.fstab.read_text(), original)
        self.assertEqual(self.b.configuration()['disk']['fstab_options'], 'defaults,nofail,noexec')

    def test_conflicting_entries_and_device_aliases_preserved(self):
        for line in ['/dev/synthetic1 /mnt/old ext4 defaults 0 0\n',
                     f'UUID={UUID} /mnt/a ext4 defaults 0 0\nUUID={UUID} /mnt/b ext4 defaults 0 0\n',
                     f'UUID={UUID} /mnt/a ext4 defaults,user 0 0\n',
                     f'/dev/other {STABLE} ext4 defaults 0 0\n']:
            with self.subTest(line=line):
                self.m.fstab.write_text(line)
                with self.assertRaises(ValueError): self.b.inspect_mount(UUID)
                self.assertEqual(self.m.fstab.read_text(), line)

    def test_nonempty_or_symlink_proposed_target_preserved(self):
        target = self.m.root / 'mounts' / STABLE.lstrip('/')
        target.mkdir(parents=True)
        sentinel = target / 'sentinel'; sentinel.write_text('preserve')
        self.assertTrue(self.b.inspect_mount(UUID)['needs_entry'])
        self.assertEqual(sentinel.read_text(), 'preserve')
        sentinel.unlink(); target.rmdir(); target.symlink_to(self.m.disk_data)
        with self.assertRaisesRegex(self.b.FieldError, 'symlink'): self.b.inspect_mount(UUID)
        self.assertTrue(target.is_symlink())

    def test_virtualization_never_grants_qualification(self):
        self.m.environment = dict(kind='virtual', name='vmware')
        session = self.m.broker.sessions.login('admin', 'synthetic')
        result = self.m.broker.handle(dict(drive='legacy',action='qualify', write=True, data={}, token=session['token'], csrf=session['csrf']))
        self.assertEqual(result['status'], 400); self.assertIn('Virtualization detected', result['error'])
        self.b.cli.bounded_candidate.assert_not_called()

    def test_preflight_errors_include_actionable_field_and_step(self):
        self.m.current = ''
        session = self.m.broker.sessions.login('admin', 'synthetic')
        payload = self.m.payload(); payload['confirmations'] = ['mount']
        result = self.m.broker.handle(dict(drive='legacy',action='validate', write=True, data=payload, token=session['token'], csrf=session['csrf']))
        self.assertEqual(result['field'], 'confirm-fstab'); self.assertEqual(result['step'], 2)
        self.assertFalse(self.m.config.exists()); self.assertEqual(self.m.fstab.read_text(), self.m.original)

    def test_prepare_reload_failure_rolls_back_entry_without_config_save(self):
        plan = self.b.inspect_mount(UUID)
        with patch.object(self.b, 'command', side_effect=ValueError('reload failed')):
            with self.assertRaisesRegex(ValueError, 'reload failed'):
                self.b.prepare_mount(dict(uuid=UUID, revision=self.b.s.digest(self.b.configuration()), plan_token=plan['token'], confirm=True))
        self.assertEqual(self.m.fstab.read_text(), self.m.original)
        self.assertFalse(self.m.config.exists())

    def test_prepare_catches_concurrent_fstab_edit_after_backup(self):
        plan = self.b.inspect_mount(UUID)
        original_save = self.b.cli.save
        def save(path, value):
            original_save(path, value)
            self.m.fstab.write_text(self.m.original + '# concurrent edit\n')
        with patch.object(self.b.cli, 'save', side_effect=save):
            with self.assertRaisesRegex(self.b.FieldError, 'changed'):
                self.b.prepare_mount(dict(uuid=UUID, revision=self.b.s.digest(self.b.configuration()), plan_token=plan['token'], confirm=True))
        self.assertEqual(self.m.fstab.read_text(), self.m.original + '# concurrent edit\n')
        self.assertFalse(self.m.config.exists())

    def test_malformed_and_quoted_existing_entries_fail_closed(self):
        for line in [f'UUID={UUID} /mnt/incomplete\n', f'UUID="{UUID}" /mnt/existing ext4 defaults 0 0\n']:
            self.m.fstab.write_text(line)
            with self.assertRaises(ValueError): self.b.inspect_mount(UUID)
            self.assertEqual(self.m.fstab.read_text(), line)

    def test_established_nonempty_mountpoint_remains_configurable(self):
        self.m.current = ''
        c = self.b.s.default()
        c['disk'].update(uuid=UUID, mountpoint=STABLE, fstab_options='defaults,nofail')
        c['recovery']['mount'] = True
        self.b.cli.save(self.m.config, c)
        original = self.m.original + f'UUID={UUID} {STABLE} ext4 defaults,nofail 0 0\n'
        self.m.fstab.write_text(original)
        target = self.b.cli.root_path('/', STABLE)
        target.mkdir(parents=True)
        sentinel = target / 'existing'; sentinel.write_text('preserve')
        self.b.save_configuration(self.m.payload())
        self.assertEqual(sentinel.read_text(), 'preserve')
        self.assertEqual(self.m.fstab.read_text(), original)


if __name__ == '__main__': unittest.main()
