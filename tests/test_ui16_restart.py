# SPDX-License-Identifier: MIT
"""UI16: user-selected drive/image restart policy, using synthetic Docker and mounts."""
import copy
import fcntl
import json
from unittest.mock import Mock, patch
from test_apps import Temp, a, w


class ExplicitRestartChoices(Temp):
    def image_selection(self, names=('app_one',), enabled=False):
        image = dict(name='sample-volume', enabled=enabled,
                     uuid='22222222-2222-4222-8222-222222222222',
                     image=self.ctx.MOUNT + '/sample-volume.img',
                     mountpoint=self.ctx.MOUNT + '/sample-volume',
                     fstab_options='loop,nofail,nodev,nosuid,noexec')
        self.ctx.SETTINGS = copy.deepcopy(w.SETTINGS)
        self.ctx.SETTINGS['dependent']['enabled'] = False
        self.ctx.SETTINGS['dependent']['uuid'] = ''
        self.ctx.SETTINGS['images'] = [image]
        self.ctx.DEPENDENCIES = [image] if enabled else []
        specs = copy.deepcopy(a.APPS)
        for name in specs:
            specs[name]['images'] = [image['uuid']] if name in names else []
        self.stack.enter_context(patch.object(a, 'APPS', specs))
        self.ctx.recover_image = Mock()
        return image

    def test_unknown_baseline_does_not_override_selected_restart(self):
        request = self.ready()
        for before in request['plan'].values():
            before.clear()
            before['known'] = False
        result = a.recover(self.ctx, request, self.docker)
        self.assertEqual(len(self.docker.changes), 3)
        self.assertTrue(all(action == 'start' for _, _, action in self.docker.changes))
        self.assertTrue(result['all_verified'])

    def test_source_and_namespace_proofs_never_gate_selected_restart(self):
        request = self.ready()
        with patch.object(a, 'source_proof', side_effect=AssertionError('Unexpected bind gate')), \
             patch.object(a, 'namespace_proof', side_effect=AssertionError('Unexpected namespace gate')), \
             patch.object(a, 'required_bindings', side_effect=AssertionError('Unexpected dependency gate')):
            result = a.recover(self.ctx, request, self.docker)
        self.assertEqual(len(self.docker.changes), 3)
        self.assertEqual(self.docker.accesses, [])
        self.assertTrue(result['all_verified'])

    def test_explicit_image_selection_attempted_before_restart_even_if_auto_mount_off(self):
        image = self.image_selection()
        trace = []
        self.ctx.recover_image.side_effect = lambda item, request, note: trace.append('image:' + item['uuid'])
        original = self.docker.change
        def change(name, identity, action):
            trace.append('restart:' + name)
            return original(name, identity, action)
        self.docker.change = change
        result = a.recover(self.ctx, self.ready(), self.docker)
        self.assertLess(trace.index('image:' + image['uuid']), trace.index('restart:app_one'))
        self.assertEqual(self.ctx.recover_image.call_count, 1)
        self.assertTrue(result['all_verified'])

    def test_selected_image_failure_keeps_its_container_stopped(self):
        self.image_selection()
        self.ctx.recover_image.side_effect = w.Unsafe('Synthetic image mount failure')
        result = a.recover(self.ctx, self.ready(), self.docker)
        self.assertEqual(len(self.docker.changes), 2)
        self.assertEqual(result['containers']['app_one']['status'], 'failed')
        self.assertIn('stays stopped', result['containers']['app_one']['reason'])
        self.assertTrue(result['storage_verified'])
        self.assertIn('Synthetic image mount failure', str(result['images']))

    def test_shared_image_selected_by_two_containers_is_attempted_once(self):
        self.image_selection(('app_one', 'app_two'))
        result = a.recover(self.ctx, self.ready(), self.docker)
        self.assertEqual(self.ctx.recover_image.call_count, 1)
        self.assertEqual(len(self.docker.changes), 3)
        self.assertTrue(result['all_verified'])

    def test_none_selection_does_not_attempt_registered_image(self):
        self.image_selection(())
        result = a.recover(self.ctx, self.ready(), self.docker)
        self.ctx.recover_image.assert_not_called()
        self.assertTrue(result['all_verified'])

    def test_image_failure_from_drive_stage_is_not_repeated(self):
        image = self.image_selection(enabled=True)
        request = self.ready(loopfs=False)
        state = copy.deepcopy(self.monitor.state)
        state['incident']['result']['images'] = [dict(uuid=image['uuid'], name=image['name'], healthy=False,
                                                     detail='Already attempted during drive recovery')]
        self.monitor.commit(state)
        result = a.recover(self.ctx, request, self.docker)
        self.ctx.recover_image.assert_not_called()
        self.assertEqual(len(self.docker.changes), 2)
        self.assertEqual(result['containers']['app_one']['status'], 'failed')
        self.assertIn('Already attempted', str(result['images']))

    def test_configured_container_id_wins_over_unknown_running_history(self):
        specs = copy.deepcopy(a.APPS)
        specs['app_one']['container_id'] = 'a' * 64
        with patch.object(a, 'APPS', specs):
            request = self.ready()
            result = a.recover(self.ctx, request, self.docker)
        self.assertNotIn('app_one', [name for name, _, _ in self.docker.changes])
        self.assertEqual(result['containers']['app_one']['status'], 'failed')
        self.assertEqual(len(self.docker.changes), 2)

    def test_image_intent_is_not_replayed_after_worker_crash(self):
        image = self.image_selection()
        request = self.ready()
        self.ctx.recover_image.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            a.recover(self.ctx, request, self.docker)
        self.assertEqual(self.docker.changes, [])
        self.ctx.recover_image.side_effect = None
        result = a.recover(self.ctx, request, self.docker)
        self.assertEqual(self.ctx.recover_image.call_count, 1)
        self.assertEqual(result['images'][image['uuid']]['status'], 'warning')
        self.assertEqual(len(self.docker.changes), 2)
        self.assertEqual(result['containers']['app_one']['status'], 'failed')

    def test_saved_deselection_before_durable_intent_skips_container(self):
        request = self.ready()
        choices = [dict(name=name, container_id='') for name in a.APPS if name != 'app_one']
        with patch.object(a, 'READER', return_value=dict(docker_enabled=True, docker_containers=choices)):
            result = a.recover(self.ctx, request, self.docker)
        self.assertNotIn('app_one', [name for name, _, _ in self.docker.changes])
        self.assertEqual(result['containers']['app_one']['action_count'], 0)

    def test_saved_deselection_after_durable_intent_does_not_send_restart(self):
        request = self.ready()
        choices = [dict(name=name, container_id='') for name in a.APPS]
        original = self.ctx.atomic_write
        def write(path, data, **kw):
            original(path, data, **kw)
            if '"status": "intent"' in data:
                choices[:] = [row for row in choices if row['name'] != 'app_one']
        self.ctx.atomic_write = write
        with patch.object(a, 'READER', side_effect=lambda: dict(docker_enabled=True, docker_containers=choices)):
            result = a.recover(self.ctx, request, self.docker)
        self.assertNotIn('app_one', [name for name, _, _ in self.docker.changes])
        self.assertEqual(result['containers']['app_one']['action_count'], 1)

    def test_deselected_image_is_not_mounted_from_stale_worker_preferences(self):
        self.image_selection()
        request = self.ready()
        choices = [dict(name=name, container_id='', images=[]) for name in a.APPS]
        with patch.object(a, 'READER', return_value=dict(docker_enabled=True, docker_containers=choices)):
            result = a.recover(self.ctx, request, self.docker)
        self.ctx.recover_image.assert_not_called()
        self.assertEqual(len(self.docker.changes), 3)
        self.assertTrue(result['all_verified'])

    def test_selected_nested_images_are_mounted_parent_before_child(self):
        parent = self.image_selection()
        child = dict(parent, name='child', uuid='33333333-3333-4333-8333-333333333333',
                     image=parent['mountpoint'] + '/child.img', mountpoint=parent['mountpoint'] + '/child')
        self.ctx.SETTINGS['images'] = [child, parent]
        a.APPS['app_one']['images'] = [child['uuid'], parent['uuid']]
        trace = []
        self.ctx.recover_image.side_effect = lambda item, request, note: trace.append(item['name'])
        result = a.recover(self.ctx, self.ready(), self.docker)
        self.assertEqual(trace, ['sample-volume', 'child'])
        self.assertTrue(result['all_verified'])

    def test_other_drive_holding_container_lock_prevents_overlapping_restart(self):
        request = self.ready()
        directory = self.directory / 'shared-locks'
        directory.mkdir(mode=0o700)
        path = directory / ('docker-restart-' + '1'*64 + '.lock')
        with path.open('a') as other:
            path.chmod(0o600)
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            started = self.clock.now
            result = a.recover(self.ctx, request, self.docker)
        self.assertGreater(self.clock.now, started)
        self.assertLessEqual(self.clock.now - started, a.WORK_TIMEOUT)
        self.assertNotIn('app_one', [name for name, _, _ in self.docker.changes])
        self.assertEqual(result['containers']['app_one']['action_count'], 0)
        self.assertIn('no overlapping command', result['containers']['app_one']['reason'])
        self.assertEqual([name for name, _, _ in self.docker.changes], ['app_two', 'app_three'])

    def test_waiting_for_container_lock_rechecks_live_start_time_before_intent(self):
        request = self.ready()
        directory = self.directory / 'shared-locks'
        directory.mkdir(mode=0o700)
        path = directory / ('docker-restart-' + '1'*64 + '.lock')
        original_change = self.docker.change
        trace = []
        def change(name, identity, action):
            if name == 'app_one':
                with path.open('a') as contender:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                trace.append('restart-while-locked')
            return original_change(name, identity, action)
        self.docker.change = change
        with path.open('a') as other:
            path.chmod(0o600)
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release(duration):
                self.clock.sleep(duration)
                self.docker.containers['app_one']['started_at'] = 'other-drive-finished'
                fcntl.flock(other, fcntl.LOCK_UN)
            with patch.object(a.time, 'sleep', side_effect=release):
                result = a.recover(self.ctx, request, self.docker)
        self.assertEqual(result['containers']['app_one']['before_started_at'], 'other-drive-finished')
        self.assertEqual(trace, ['restart-while-locked'])
        self.assertEqual(result['containers']['app_one']['status'], 'verified')
        with path.open('a') as later:
            fcntl.flock(later, fcntl.LOCK_EX | fcntl.LOCK_NB)


class EditableWhileMonitoring(Temp):
    def setUp(self):
        super().setUp()
        self.original = copy.deepcopy(w.SETTINGS)
        self.addCleanup(w.configure, self.original)

    def changed_docker(self):
        changed = copy.deepcopy(self.original)
        changed['docker']['containers'] = [dict(name='new-app', source='', destination='', grace=30,
                                                 container_id='a'*64, images=[])]
        return w.settings.validate(changed)

    def test_docker_only_changes_do_not_invalidate_storage_config(self):
        changed = self.changed_docker()
        self.assertNotEqual(w.settings.digest(changed), w.CONFIG_DIGEST)
        self.assertEqual(w.storage_config_digest(changed), w.STORAGE_CONFIG_DIGEST)
        with patch.object(w.settings, 'read', return_value=changed):
            value = w.config_load()
        self.assertEqual(value['docker_containers'][0]['name'], 'new-app')
        self.assertTrue(value['automatic_recovery'])

    def test_monitor_hot_reload_adopts_new_container_selection(self):
        changed = self.changed_docker()
        with patch.object(w.settings, 'read', return_value=changed):
            w.refresh_docker_settings()
        self.assertEqual(set(a.APPS), {'new-app'})
        self.assertEqual(a.APPS['new-app']['container_id'], 'a'*64)
        self.assertEqual(w.SETTINGS['docker'], changed['docker'])
        self.assertEqual(w.CONFIG_DIGEST, w.settings.digest(changed))

    def test_disk_and_usb_changes_still_require_controlled_restart(self):
        for group, key, value in [('disk', 'mountpoint', '/mnt/other'), ('usb', 'enabled', False)]:
            changed = copy.deepcopy(self.original)
            changed[group][key] = value
            with self.subTest(group=group), patch.object(w.settings, 'read', return_value=changed):
                with self.assertRaises(w.Unsafe):
                    w.config_load()
                with self.assertRaises(w.Unsafe):
                    w.refresh_docker_settings()

    def test_request_survives_docker_selection_change_but_not_storage_change(self):
        request = dict(config_digest=w.CONFIG_DIGEST, storage_config_digest=w.STORAGE_CONFIG_DIGEST)
        changed = self.changed_docker()
        with patch.object(w.settings, 'read', return_value=changed):
            w.refresh_docker_settings()
            w.require_configuration(request)
        with patch.object(w.settings, 'read', return_value=changed):
            with self.assertRaises(w.Unsafe):
                w.require_configuration(dict(request, storage_config_digest='different-storage'))

    def test_incident_and_workers_carry_storage_digest(self):
        self.outage()
        incident = self.monitor.state['incident']
        self.assertEqual(incident['storage_config_digest'], w.STORAGE_CONFIG_DIGEST)
        work = self.monitor.work_request(True, 105)
        self.assertEqual(work['storage_config_digest'], w.STORAGE_CONFIG_DIGEST)
        from test_apps import storage_result, observation
        self.monitor.work_result(work, storage_result(), 106)
        self.monitor.sample(observation(), 120)
        self.monitor.sample(observation(), 135)
        request = self.monitor.app_request()
        self.assertEqual(request['storage_config_digest'], w.STORAGE_CONFIG_DIGEST)

    def test_pending_transaction_uses_previous_docker_preferences_for_this_drive(self):
        changed = self.changed_docker()
        journal = self.directory / 'docker-settings-transaction.json'
        journal.write_text(json.dumps(dict(version=1, before={w.settings.PROFILE_ID: self.original})))
        with patch.object(w.settings, 'read', return_value=changed):
            current = w.runtime_configuration()
            self.assertEqual(current['docker'], self.original['docker'])
            loaded = w.config_load()
            self.assertTrue(loaded['automatic_recovery'])
            self.assertEqual(loaded['docker_containers'], self.original['docker']['containers'])
            w.refresh_docker_settings()
        self.assertEqual(w.SETTINGS['docker'], self.original['docker'])
        self.assertEqual(w.STORAGE_CONFIG_DIGEST, w.storage_config_digest(self.original))

    def test_invalid_transaction_disables_docker_without_claiming_drive_config_changed(self):
        changed = self.changed_docker()
        journal = self.directory / 'docker-settings-transaction.json'
        cases = ['{invalid', '{}', json.dumps(dict(version=2, before={w.settings.PROFILE_ID: self.original}))]
        for body in cases:
            journal.write_text(body)
            with self.subTest(body=body), patch.object(w.settings, 'read', side_effect=lambda *_: copy.deepcopy(changed)):
                loaded = w.config_load()
                self.assertTrue(loaded['automatic_recovery'])
                self.assertFalse(loaded['docker_enabled'])
                self.assertEqual(loaded['docker_containers'], [])
                w.require_configuration(dict(storage_config_digest=w.STORAGE_CONFIG_DIGEST))

    def test_pending_transaction_cannot_mask_physical_storage_settings_change(self):
        changed = self.changed_docker()
        changed['usb']['enabled'] = False
        journal = self.directory / 'docker-settings-transaction.json'
        journal.write_text(json.dumps(dict(version=1, before={w.settings.PROFILE_ID: self.original})))
        with patch.object(w.settings, 'read', return_value=changed):
            with self.assertRaises(w.Unsafe):
                w.config_load()
            with self.assertRaises(w.Unsafe):
                w.refresh_docker_settings()

    def test_unrelated_drive_transaction_preserves_current_docker_choices(self):
        changed = self.changed_docker()
        journal = self.directory / 'docker-settings-transaction.json'
        journal.write_text(json.dumps(dict(version=1, before={'unrelated-profile': self.original})))
        with patch.object(w.settings, 'read', return_value=changed):
            loaded = w.config_load()
            self.assertTrue(loaded['docker_enabled'])
            self.assertEqual(loaded['docker_containers'], changed['docker']['containers'])
            self.assertTrue(loaded['automatic_recovery'])
