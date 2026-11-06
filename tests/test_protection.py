# SPDX-License-Identifier: MIT
"""Consent, safe reuse and failure handling for basic protection activation."""
import copy
import fcntl
import json
import unittest
from unittest.mock import patch
from gui_fixture import Machine, UUID, DESKTOP


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.m = Machine(); self.addCleanup(self.m.close)
        self.b = self.m.b; self.p = self.b.protection; self.context = self.b.protection_context()

    def plan(self, automatic=True):
        return self.p.plan(self.context, UUID, automatic)

    def payload(self, **kw):
        return dict(uuid=UUID, automatic=True, notifications=False, token=self.plan()['token'], consent=True) | kw

    def activate(self, **kw):
        return self.p.activate(self.context, self.payload(**kw))

    def test_plan_has_no_writes_or_private_engine_details(self):
        result = self.plan()
        self.assertTrue(result['ready'])
        self.assertNotIn('_config', result)
        self.assertFalse(self.m.config.exists()); self.assertEqual(list(self.m.state.iterdir()), [])
        self.assertEqual(self.m.fstab.read_text(), self.m.original)

    def test_consent_and_current_token_required_before_mutations(self):
        for changes in ({'consent':False}, {'consent':1}, {'token':'stale'}, {'automatic':'true'}, {'usb':True}):
            with self.subTest(changes=changes), self.assertRaises(self.p.Problem):
                self.activate(**changes)
            self.assertFalse(self.m.config.exists()); self.assertEqual(self.m.fstab.read_text(), self.m.original)

    def test_live_desktop_registration_is_append_only_and_backup_private(self):
        self.activate()
        self.assertTrue(self.m.fstab.read_text().startswith(self.m.original))
        self.assertEqual(self.m.current, DESKTOP)
        backup = next((self.m.state / 'setup-backups').glob('*.json'))
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(backup.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads(backup.read_text())['fstab'], self.m.original)
        self.assertTrue(self.b.configuration()['usb']['enabled'])
        self.b.cli.bounded_candidate.assert_not_called()

    def test_entry_reuse_does_not_modify_table_or_request_reload(self):
        original = self.m.original + f'UUID={UUID} {DESKTOP} ext4 defaults,nofail,nodev,nosuid,x-systemd.device-timeout=10s 0 0\n'
        self.m.fstab.write_text(original)
        self.assertFalse(self.plan()['change'])
        self.activate()
        self.assertEqual(self.m.fstab.read_text(), original)
        self.assertNotIn(['/usr/bin/systemctl', 'daemon-reload'], self.m.calls)

    def test_duplicate_unsafe_and_conflicting_entries_never_overwritten(self):
        for lines in [f'UUID={UUID} {DESKTOP} ext4 defaults 0 0\n' * 2,
                      f'UUID={UUID} {DESKTOP} ext4 ro 0 0\n',
                      f'UUID={UUID} /mnt/different ext4 defaults 0 0\n',
                      f'/dev/unrelated {DESKTOP} ext4 defaults 0 0\n',
                      f'UUID={UUID} {DESKTOP} ext4 defaults\n']:
            with self.subTest(lines=lines):
                self.m.fstab.write_text(self.m.original + lines)
                result = self.plan()
                self.assertFalse(result['ready']); self.assertEqual(result['action'], 'monitor-only')
                self.assertEqual(self.m.fstab.read_text(), self.m.original + lines)

    def test_unsafe_snapshot_and_parent_directory_block_recovery(self):
        for observed in [dict(detected=True, healthy=False, unsafe=True), dict(detected=False, healthy=False)]:
            with patch.object(self.b.w, 'snapshot', return_value=observed):
                self.assertFalse(self.plan()['ready'])
        with patch.object(self.b.w, 'protected_mount_directory', side_effect=self.b.w.Unsafe('writable parent')):
            self.assertFalse(self.plan()['ready'])

    def test_busy_namespaces_are_checked_before_unmounted_drive_setup(self):
        self.m.current = ''
        with patch.object(self.b.w, 'mount_available', side_effect=self.b.w.Unsafe('namespace busy')):
            self.assertFalse(self.plan()['ready'])
        self.assertFalse(self.m.config.exists())

    def test_active_service_and_surviving_worker_block_configuration(self):
        data = self.payload()
        self.m.active = True
        self.assertEqual(self.plan()['action'], 'pause')
        with self.assertRaises(self.p.Problem): self.p.activate(self.context, data)
        self.m.active = False
        with (self.m.state / 'monitor.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(self.p.Problem): self.p.activate(self.context, data)
        self.assertFalse(self.m.config.exists())

    def test_config_failure_rolls_back_only_own_append(self):
        original = self.b.cli.save
        def save(path, value):
            if path == self.m.config: raise OSError('simulated failure')
            original(path, value)
        with patch.object(self.b.cli, 'save', side_effect=save), self.assertRaises(self.p.Problem): self.activate()
        self.assertEqual(self.m.fstab.read_text(), self.m.original)
        self.assertFalse(self.m.active); self.assertFalse(self.m.config.exists())

    def test_rollback_refuses_to_overwrite_concurrent_admin_edit(self):
        original = self.b.cli.save
        def save(path, value):
            if path == self.m.config:
                self.m.fstab.write_text(self.m.fstab.read_text() + '# Concurrent admin edit\n')
                raise OSError('simulated failure')
            original(path, value)
        with patch.object(self.b.cli, 'save', side_effect=save), self.assertRaises(self.p.Problem): self.activate()
        self.assertTrue(self.m.fstab.read_text().endswith('# Concurrent admin edit\n'))
        self.assertFalse(self.m.active)

    def test_desktop_mount_race_stops_save_and_restores_append(self):
        original = self.m.command
        def command(args, timeout=10):
            if args == ['/usr/bin/systemctl', 'daemon-reload']:
                self.m.current = '/media/other/location'
            return original(args, timeout)
        self.context.command = command
        with self.assertRaises(self.p.Problem): self.activate()
        self.assertEqual(self.m.fstab.read_text(), self.m.original)
        self.assertFalse(self.m.config.exists()); self.assertFalse(self.m.active)

    def test_concurrent_matching_configuration_is_not_overwritten_or_broken(self):
        data = self.payload()
        expected = self.p.proposal(self.context, UUID, True)['_config']
        original = self.m.command
        def command(args, timeout=10):
            if args == ['/usr/bin/systemctl', 'daemon-reload']:
                self.b.cli.save(self.m.config, expected)
            return original(args, timeout)
        self.context.command = command
        with self.assertRaisesRegex(self.p.Problem, 'Settings changed while saving'):
            self.p.activate(self.context, data)
        self.assertEqual(self.b.configuration(), expected)
        self.assertIn('UUID=' + UUID, self.m.fstab.read_text())
        self.assertFalse(self.m.active)

    def test_service_failure_retains_saved_choices_without_claiming_success(self):
        original = self.m.command
        def command(args, timeout=10):
            if args[:2] == ['/usr/bin/systemctl', 'enable']: raise ValueError('start failed')
            return original(args, timeout)
        self.context.command = command
        with self.assertRaisesRegex(self.p.Problem, 'choices are saved'): self.activate()
        self.assertTrue(self.m.config.exists()); self.assertFalse(self.m.active)

    def test_existing_advanced_settings_and_incident_history_are_retained(self):
        c = self.b.s.default()
        c['disk'].update(uuid=UUID, mountpoint=DESKTOP)
        c['monitor'].update(interval=25, observations=3)
        c['recovery'].update(wait=200, attempts=1)
        c['docker']['containers'] = [dict(name='application', source=DESKTOP + '/data', destination='/data', grace=30)]
        self.b.cli.save(self.m.config, c)
        state = b'{"target":[],"pending":["preserve"],"incident":{"phase":"done"}}'
        (self.m.state / 'state.json').write_bytes(state)
        self.activate()
        saved = self.b.configuration()
        self.assertEqual(saved['docker'], self.b.s.validate(c)['docker']); self.assertEqual(saved['usb'], c['usb'] | {'enabled': True})
        self.assertEqual(saved['monitor'], c['monitor']); self.assertEqual(saved['recovery']['attempts'], 1)
        self.assertEqual((self.m.state / 'state.json').read_bytes(), state)

    def test_new_endpoints_require_login_and_csrf_and_http_method(self):
        for action, write in [('protection-plan',False), ('activate-protection',True)]:
            self.assertEqual(self.m.broker.handle(dict(drive='legacy',action=action, write=write, data={}))['status'], 401)
        session = self.m.broker.handle(dict(action='login', local=True, write=True, data=dict(username='admin', password='synthetic')))['data']
        for csrf in ('', 'incorrect'):
            response = self.m.broker.handle(dict(drive='legacy',action='activate-protection', write=True, data=self.payload(), token=session['token'], csrf=csrf))
            self.assertEqual(response['status'], 401)
        self.assertFalse(self.m.config.exists())


if __name__ == '__main__': unittest.main()
