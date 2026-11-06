# SPDX-License-Identifier: MIT
"""Exact legacy entry migration, rollback and retained recovery state."""
import json
import stat
import unittest
from unittest.mock import patch
from gui_fixture import Machine, UUID, DESKTOP, STABLE, load


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.m = Machine(); self.addCleanup(self.m.close)
        self.b = self.m.b; self.x = self.b.migration
        self.options = 'defaults,nofail,nodev,nosuid,x-systemd.device-timeout=10s'
        self.entry = f'UUID={UUID} {DESKTOP} ext4 {self.options} 0 0\n'
        self.original = '# Existing operating system entries\n/dev/root / ext4 defaults 0 1\n' + self.entry + '# Trailing comment\n'
        self.m.fstab.write_text(self.original)

    def context(self): return self.b.migration_context()

    def prepare(self):
        plan = self.x.plan(self.context(), UUID)
        return self.x.prepare(self.context(), dict(uuid=UUID, token=plan['token'], revision=self.b.s.digest(self.b.configuration()), confirm=True))

    def rollback(self):
        return self.x.rollback(self.context(), dict(id=self.x.journal(self.context())['id'], confirm=True))

    def save_old_config(self, with_state=False):
        c = self.b.s.default(); c['disk'].update(uuid=UUID, mountpoint=DESKTOP, fstab_options=self.options)
        c['recovery']['mount'] = True
        self.b.cli.save(self.m.config, c)
        if with_state:
            self.b.w.configure(c)
            state = self.b.w.fresh_state()
            state['pending'] = [dict(id=UUID, kind='outcome', time='2000-01-01', host='fixture', detail='retain notification', subject='Test', retry_at=0)]
            state['incident'] = self.b.w.new_incident('2000-01-01', 'Retained outcome', 0, 'fixture')
            state['incident'].update(phase='done', usb_resets=1, outcome='Retained result')
            self.b.cli.save(self.m.state / 'state.json', state)
        return c

    def test_valid_existing_runtime_entry_is_accepted_unchanged(self):
        plan = self.b.inspect_mount(UUID)
        self.assertTrue(plan['can_migrate']); self.assertFalse(plan['needs_entry'])
        self.assertEqual(plan['mountpoint'], DESKTOP)
        data = self.m.payload(); data['confirmations'] = ['mount']
        self.b.save_configuration(data)
        self.assertEqual(self.m.fstab.read_text(), self.original)
        self.assertEqual(self.b.configuration()['disk']['mountpoint'], DESKTOP)
        self.assertEqual(self.m.current, DESKTOP)

    def test_preview_is_read_only_and_changes_only_target_field(self):
        plan = self.x.plan(self.context(), UUID)
        self.assertEqual(plan['replacement'], self.original.replace(DESKTOP, STABLE))
        self.assertEqual(list(self.m.state.iterdir()), [])
        self.assertEqual(self.m.fstab.read_text(), self.original)

    def test_consent_and_stale_preview_are_enforced(self):
        plan = self.x.plan(self.context(), UUID)
        data = dict(uuid=UUID, token=plan['token'], revision=self.b.s.digest(self.b.configuration()))
        with self.assertRaisesRegex(ValueError, 'consent'): self.x.prepare(self.context(), data)
        self.m.fstab.write_text(self.original + '# new unrelated edit\n')
        with self.assertRaisesRegex(ValueError, 'changed'): self.x.prepare(self.context(), data | dict(confirm=True))
        self.assertEqual(self.m.fstab.read_text(), self.original + '# new unrelated edit\n')

    def test_migration_keeps_live_mount_and_protected_backup(self):
        result = self.prepare()
        self.assertEqual(self.m.current, DESKTOP)
        self.assertEqual(self.m.fstab.read_text(), self.original.replace(DESKTOP, STABLE))
        record = self.x.journal(self.context()); saved = self.x.backup(self.context(), record)
        self.assertEqual(saved['fstab'], self.original)
        backup = self.m.state / 'mount-migrations' / record['id'] / 'backup.json'
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(backup.parent.stat().st_mode), 0o700)
        self.assertEqual(result['plan']['mountpoint'], STABLE)
        self.assertFalse(self.m.config.exists())
        with self.assertRaisesRegex(ValueError, 'still mounted'):
            self.b.save_configuration(self.m.payload(), validate_only=True)
        self.assertEqual((self.m.disk_data / 'sentinel').read_bytes(), b'Existing filesystem contents\x00preserve me')

    def test_prepared_migration_survives_broker_reload_and_absent_disk_rollback(self):
        self.prepare(); self.m.present = False
        # A fresh migration module reads the durable journal; no in-memory session token is required.
        other = load('web_migration')
        self.assertEqual(other.public(self.context())['phase'], 'applied')
        self.rollback()
        self.assertEqual(self.m.fstab.read_text(), self.original)
        self.assertFalse(self.m.config.exists())

    def test_saved_configuration_and_runtime_state_migrate_without_resetting_budgets(self):
        self.save_old_config(with_state=True)
        old_state = json.loads((self.m.state / 'state.json').read_text())
        self.prepare(); self.m.current = STABLE
        self.b.save_configuration(self.m.payload())
        state = json.loads((self.m.state / 'state.json').read_text())
        self.assertEqual(state, old_state | dict(target=[UUID, STABLE]))
        self.assertEqual(self.b.configuration()['disk']['mountpoint'], STABLE)
        # Use the real engine reader, not the fixture's observation substitute.
        engine = load('engine'); engine.configure(self.b.configuration())
        self.assertEqual(engine.load_state(self.m.state / 'state.json')['pending'], old_state['pending'])
        self.assertEqual(self.x.journal(self.context())['phase'], 'committed')

    def test_rollback_after_save_restores_config_and_state_exactly(self):
        self.save_old_config(with_state=True)
        before_config = self.m.config.read_bytes(); before_state = (self.m.state / 'state.json').read_bytes()
        self.prepare(); self.m.current = STABLE
        self.b.save_configuration(self.m.payload())
        self.rollback()
        self.assertEqual(self.m.config.read_bytes(), before_config)
        self.assertEqual((self.m.state / 'state.json').read_bytes(), before_state)
        self.assertEqual(self.m.fstab.read_text(), self.original)
        self.assertEqual(self.m.current, STABLE)  # No unmount, even on rollback.

    def test_unrelated_fstab_edits_survive_rollback(self):
        self.prepare()
        with self.m.fstab.open('a') as f: f.write('/dev/other /mnt/other ext4 defaults 0 0\n')
        self.rollback()
        self.assertEqual(self.m.fstab.read_text(), self.original + '/dev/other /mnt/other ext4 defaults 0 0\n')

    def test_rollback_refuses_changed_selected_entry_or_target_conflict(self):
        self.prepare()
        changed = self.m.fstab.read_text().replace('nodev,nosuid', 'nodev,nosuid,noexec')
        self.m.fstab.write_text(changed)
        with self.assertRaisesRegex(ValueError, 'edited elsewhere'): self.rollback()
        self.assertEqual(self.m.fstab.read_text(), changed)
        self.m.fstab.write_text(self.original.replace(DESKTOP, STABLE) + f'/dev/other {DESKTOP} ext4 defaults 0 0\n')
        with self.assertRaisesRegex(ValueError, 'Another entry'): self.rollback()

    def test_new_events_are_never_overwritten_by_rollback(self):
        self.save_old_config(with_state=True); self.prepare(); self.m.current = STABLE
        self.b.save_configuration(self.m.payload())
        current = json.loads((self.m.state / 'state.json').read_text()); current['new_history'] = 'retain'
        self.b.cli.save(self.m.state / 'state.json', current)
        with self.assertRaisesRegex(ValueError, 'newer state'): self.rollback()
        self.assertEqual(json.loads((self.m.state / 'state.json').read_text()), current)

    def test_failed_daemon_reload_restores_original_table(self):
        original_command = self.b.command
        calls = []
        def command(args, *a):
            calls.append(args)
            if len(calls) == 1: raise ValueError('Synthetic reload failure')
            return original_command(args, *a)
        with patch.object(self.b, 'command', side_effect=command):
            with self.assertRaisesRegex(ValueError, 'rolled back'): self.prepare()
        self.assertEqual(self.m.fstab.read_text(), self.original)
        self.assertEqual(self.x.journal(self.context())['phase'], 'rolled_back')

    def test_interrupted_commit_can_roll_back_both_file_versions(self):
        self.save_old_config(with_state=True); before = self.m.config.read_text()
        self.prepare(); self.m.current = STABLE
        original_save = self.b.cli.save
        def save(path, value):
            if path == self.m.config: raise OSError('Synthetic interrupted config save')
            return original_save(path, value)
        with patch.object(self.b.cli, 'save', side_effect=save):
            with self.assertRaises(OSError): self.b.save_configuration(self.m.payload())
        self.assertEqual(self.x.journal(self.context())['phase'], 'committing')
        self.rollback()
        self.assertEqual(self.m.config.read_text(), before)
        self.assertEqual(self.m.fstab.read_text(), self.original)

    def test_active_monitor_and_unfinished_incident_block_migration(self):
        self.m.active = True
        with self.assertRaisesRegex(ValueError, 'Stop monitoring'): self.prepare()
        self.m.active = False; self.save_old_config(with_state=True)
        state = json.loads((self.m.state / 'state.json').read_text()); state['incident']['phase'] = 'wait1'
        self.b.cli.save(self.m.state / 'state.json', state)
        with self.assertRaisesRegex(ValueError, 'unfinished'): self.prepare()
        self.assertEqual(self.m.fstab.read_text(), self.original)

    def test_pending_transaction_blocks_monitor_enable(self):
        self.save_old_config(); self.prepare()
        session = self.m.broker.sessions.login('admin', 'synthetic')
        result = self.m.broker.handle(dict(drive='legacy',action='monitor', write=True, data=dict(enabled=True), token=session['token'], csrf=session['csrf']))
        self.assertEqual(result['status'], 400); self.assertIn('unfinished', result['error'])
        self.assertFalse(self.m.active)

    def test_docker_restart_choices_do_not_block_mount_location_change(self):
        c = self.save_old_config()
        c['docker']['containers'] = [dict(name='example', source=DESKTOP + '/data', destination='/data', grace=30)]
        self.b.cli.save(self.m.config, c)
        before=self.b.configuration()['docker']
        self.prepare();self.m.current=STABLE
        self.b.save_configuration(self.m.payload())
        self.assertEqual(self.b.configuration()['docker'],before)
        self.assertEqual(self.b.configuration()['disk']['mountpoint'],STABLE)
        self.assertEqual(self.m.fstab.read_text(),self.original.replace(DESKTOP,STABLE))

    def test_formatting_options_and_crlf_are_preserved(self):
        original = '# Heading\r\n\tUUID=' + UUID + '\t' + DESKTOP + '\text4\t' + self.options + '\t0 2 # retain\r\n'
        self.m.fstab.write_bytes(original.encode())
        self.prepare()
        self.assertEqual(self.m.fstab.read_bytes(), original.replace(DESKTOP, STABLE).encode())
        self.rollback(); self.assertEqual(self.m.fstab.read_bytes(), original.encode())


if __name__ == '__main__': unittest.main()
