# SPDX-License-Identifier: MIT
"""Persisted stop and live Docker boundaries for ordinary storage cleanup."""
import copy
import fcntl
from unittest.mock import Mock, patch

from test_apps import Temp, a


class StorageStopGuard(Temp):
    def setUp(self):
        super().setUp()
        self.request = dict(incident='guard-outage', boot='boot-test')
        self.receipt = a.stop_selected(self.ctx, self.request, self.docker)
        self.docker.changes.clear()

    def enter(self):
        with a.storage_recovery_guard(self.ctx, self.request, self.docker):
            return True

    def test_verified_stop_holds_manual_action_locks_without_docker_mutation(self):
        paths = [self.directory / 'applications.lock'] + [
            self.directory / 'shared-locks' / ('docker-restart-' + current['id'] + '.lock')
            for current in self.docker.containers.values()]
        receipt = a.stop_ledger_path(self.ctx).read_text()
        with a.storage_recovery_guard(self.ctx, self.request, self.docker):
            for path in paths:
                with path.open('a') as other:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in paths:
            with path.open('a') as other:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(self.docker.changes, [])
        self.assertEqual(a.stop_ledger_path(self.ctx).read_text(), receipt)

    def test_request_claim_cannot_replace_persisted_incident_stop_receipt(self):
        self.request['stop'] = self.receipt
        for changes in ({'incident': 'older-outage'}, {'boot': 'older-boot'},
                        {'complete': False}, {'all_stopped': False}):
            with self.subTest(changes=changes):
                a.save_stop(self.ctx, self.receipt | changes)
                with self.assertRaises(a.AppError):
                    self.enter()
        a.stop_ledger_path(self.ctx).unlink()
        with self.assertRaises(a.AppError):
            self.enter()
        self.assertFalse((self.directory / 'application-history').exists())

    def test_each_selected_identity_requires_its_own_verified_stop(self):
        for changes in ({'status': 'skipped'}, {'container_id': 'f' * 64}):
            with self.subTest(changes=changes):
                receipt = copy.deepcopy(self.receipt)
                receipt['containers']['app_one'].update(changes)
                a.save_stop(self.ctx, receipt)
                with self.assertRaises(a.AppError):
                    self.enter()
        receipt = copy.deepcopy(self.receipt)
        del receipt['containers']['app_one']
        a.save_stop(self.ctx, receipt)
        with self.assertRaisesRegex(a.AppError, 'matching verified stop'):
            self.enter()

    def test_runtime_restarted_paused_restarting_or_replaced_refuses_cleanup(self):
        before = copy.deepcopy(self.docker.containers['app_one'])
        for changes in ({'running': True}, {'paused': True}, {'restarting': True},
                        {'running': None}, {'id': 'f' * 64}):
            with self.subTest(changes=changes):
                self.docker.containers['app_one'] = before | changes
                with self.assertRaises(a.AppError):
                    self.enter()
        self.assertEqual(self.docker.changes, [])

    def test_callback_detects_runtime_change_after_guard_entry(self):
        with a.storage_recovery_guard(self.ctx, self.request, self.docker) as recheck:
            self.assertTrue(callable(recheck))
            self.docker.containers['app_one']['running'] = True
            with self.assertRaisesRegex(a.AppError, 'not confirmed stopped now'):
                recheck()
            self.docker.containers['app_one']['running'] = False
            recheck()
            self.docker.containers['app_one']['id'] = 'f' * 64
            with self.assertRaises(a.AppError):
                recheck()
        self.assertEqual(self.docker.changes, [])

    def test_callback_detects_selection_and_boot_changes_after_guard_entry(self):
        selection = {'docker_enabled': True, 'docker_containers': [
            {'name': name, 'container_id': current['id']}
            for name, current in self.docker.containers.items()]}
        with patch.object(a, 'READER', side_effect=lambda: selection), \
                a.storage_recovery_guard(self.ctx, self.request, self.docker) as recheck:
            original = copy.deepcopy(selection)
            selection['docker_containers'] = selection['docker_containers'][:1]
            with self.assertRaisesRegex(a.AppError, 'selection changed'):
                recheck()
            selection.update(original)
            with patch.object(self.ctx, 'boot_id', return_value='different-boot'):
                with self.assertRaisesRegex(a.AppError, 'current host boot'):
                    recheck()

    def test_live_selection_addition_or_replacement_refuses_cleanup(self):
        base = [{'name': name, 'container_id': current['id']}
                for name, current in self.docker.containers.items()]
        for rows in (base + [{'name': 'new_app', 'container_id': 'e' * 64}],
                     [{'name': 'app_one', 'container_id': 'f' * 64}]):
            with self.subTest(rows=rows), patch.object(a, 'READER', return_value={
                    'docker_enabled': True, 'docker_containers': rows}):
                with self.assertRaises(a.AppError):
                    self.enter()

    def test_selection_change_during_readback_refuses_cleanup(self):
        selection = {'docker_enabled': True, 'docker_containers': [
            {'name': name, 'container_id': current['id']}
            for name, current in self.docker.containers.items()]}
        inspect = self.docker.inspect
        def change_selection(name):
            selection['docker_containers'] = selection['docker_containers'][:1]
            return inspect(name)
        with patch.object(a, 'READER', side_effect=lambda: selection), \
                patch.object(self.docker, 'inspect', side_effect=change_selection):
            with self.assertRaisesRegex(a.AppError, 'selection changed'):
                self.enter()

    def test_disabled_or_empty_selection_needs_no_receipt_or_docker_connection(self):
        a.stop_ledger_path(self.ctx).unlink()
        for current in ({'docker_enabled': False, 'docker_containers': [{'name': 'new_app'}]},
                        {'docker_enabled': True, 'docker_containers': []}):
            with self.subTest(current=current), patch.object(a, 'READER', return_value=current), \
                    patch.object(a, 'Docker') as factory, \
                    patch.object(self.ctx, 'require_configuration', Mock()) as configured:
                with a.storage_recovery_guard(self.ctx, self.request) as recheck:
                    self.assertTrue(callable(recheck))
                    recheck()
                factory.assert_not_called()
                self.assertGreaterEqual(configured.call_count, 1)

    def test_empty_selection_callback_blocks_new_selection_without_docker(self):
        for initially_enabled in (False, True):
            with self.subTest(initially_enabled=initially_enabled):
                selection = {'docker_enabled': initially_enabled, 'docker_containers': []}
                with patch.object(a, 'READER', side_effect=lambda: selection), \
                        patch.object(a, 'Docker') as factory, \
                        a.storage_recovery_guard(self.ctx, self.request) as recheck:
                    selection.update(docker_enabled=True, docker_containers=[
                        {'name': 'app_one', 'container_id': '1' * 64}])
                    with self.assertRaisesRegex(a.AppError, 'selection changed'):
                        recheck()
                    factory.assert_not_called()

    def test_deselection_uses_current_selection_and_keeps_receipt(self):
        self.docker.containers['app_two']['running'] = True
        with patch.object(a, 'READER', return_value={'docker_enabled': True,
                'docker_containers': [{'name': 'app_one', 'container_id': '1' * 64}]}):
            self.assertTrue(self.enter())
        self.assertEqual(self.docker.changes, [])

    def test_existing_manual_lock_prevents_readback_and_cleanup(self):
        identity = self.docker.containers['app_one']['id']
        path = self.directory / 'shared-locks' / ('docker-restart-' + identity + '.lock')
        with path.open('a') as manual, patch.object(a, 'WORK_TIMEOUT', 16), \
                patch.object(self.docker, 'inspect', wraps=self.docker.inspect) as inspect:
            fcntl.flock(manual, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(a.AppError, 'Another operation controls'):
                self.enter()
            inspect.assert_not_called()

    def test_configuration_failure_blocks_even_when_docker_disabled(self):
        with patch.object(a, 'enabled', return_value=False), \
                patch.object(self.ctx, 'require_configuration', side_effect=self.ctx.Unsafe('changed storage')):
            with self.assertRaisesRegex(self.ctx.Unsafe, 'changed storage'):
                self.enter()


if __name__ == '__main__':
    __import__('unittest').main()
