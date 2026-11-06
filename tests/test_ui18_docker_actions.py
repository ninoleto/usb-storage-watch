# SPDX-License-Identifier: MIT
"""Authenticated manual Docker controls; real locks, synthetic Docker only."""
import copy
import fcntl
import json
import os
import threading
import unittest
from unittest.mock import Mock, patch

from gui_fixture import load
from multidrive_fixture import FleetMachine


IDENTITY = 'a' * 64
OTHER = 'b' * 64


class DockerRuntime:
    def __init__(self):
        self.current = dict(id=IDENTITY, name='erugo', running=False, paused=False,
                            restarting=False, dead=False, started_at='old-start',
                            health=None, mounts=[])
        self.inspections = []
        self.posts = []
        self.post_hook = None
        self.read_error = False

    def inspect(self, identity):
        self.inspections.append(identity)
        if self.read_error:
            raise OSError('synthetic unavailable; private daemon details')
        return copy.deepcopy(self.current)

    def request(self, method, path, **kwargs):
        assert method == 'POST', method
        self.posts.append((path, kwargs))
        if self.post_hook:
            return self.post_hook(path, kwargs)
        if '/stop?' in path:
            self.current['running'] = False
        else:
            self.current['running'] = True
            self.current['started_at'] = 'new-start-' + str(len(self.posts))


class ManualControls(unittest.TestCase):
    def setUp(self):
        self.f = FleetMachine()
        self.addCleanup(self.f.close)
        self.second = self.f.add()
        self.b = self.f.main.b
        self.module = load('web_docker')
        self.docker = DockerRuntime()
        self.client = Mock(return_value=(self.docker, 'v1.47'))
        self.f.main.patch(self.module, 'client', self.client)
        self.f.main.patch(self.module, 'MANUAL_VERIFY_SECONDS', 0)
        original = self.b.common.module
        self.f.main.patch(self.b.common, 'module', lambda name, *args:
                          self.module if name == 'web_docker' else original(name, *args))
        self.before = [m.config.read_bytes() for m in (self.f.main, self.f.second)]
        for m in (self.f.main, self.f.second):
            m.calls.clear()

    def data(self, action):
        return dict(id=IDENTITY, name='erugo', action=action, confirm=True)

    def run_action(self, action, **kwargs):
        return self.f.request('docker-container-action', self.data(action), profile=None, **kwargs)

    def assert_unchanged(self):
        self.assertEqual(self.before, [m.config.read_bytes() for m in (self.f.main, self.f.second)])
        self.assertEqual(self.f.main.calls, [])
        self.assertEqual(self.f.second.calls, [])

    def test_start_stop_restart_on_and_off_monitoring_without_restart_configuration(self):
        for active in (True, False):
            with self.subTest(monitoring=active):
                self.f.main.active = active
                self.f.second.active = active
                self.docker.current['running'] = False
                for action, state in (('start', 'running'), ('restart', 'running'), ('stop', 'stopped')):
                    result = self.run_action(action)
                    self.assertEqual(result['status'], 200, result)
                    self.assertTrue(result['data']['ok'], result)
                    self.assertFalse(result['data']['uncertain'])
                    self.assertEqual(result['data']['container']['state'], state)
                    self.assertEqual(result['data']['container']['id'], IDENTITY)
                self.assertEqual(self.f.main.active, active)
                self.assertEqual(self.f.second.active, active)
        self.assertEqual(len(self.docker.posts), 6)
        self.assertTrue(all(value == IDENTITY for value in self.docker.inspections))
        self.assert_unchanged()

    def test_unconfigured_dependencies_are_not_inferred_from_bind_paths(self):
        self.f.main.current = ''
        self.f.main.present = False
        self.docker.current['mounts'] = [dict(Source='/not/mounted/image/uploads')]
        with patch.object(self.b.w, 'verify_main', side_effect=AssertionError('storage gate')), \
             patch.object(self.b.w, 'read_rows', side_effect=AssertionError('storage probe')), \
             patch.object(self.b.w, 'recover_image', side_effect=AssertionError('image mount')):
            result = self.run_action('start')
        self.assertTrue(result['data']['ok'], result)
        self.assert_unchanged()

    def test_no_configured_drives_uses_default_docker_connection(self):
        self.f.main.config.unlink()
        self.f.second.config.unlink()
        self.assertTrue(self.run_action('start')['data']['ok'])
        self.assertEqual(self.client.call_args.args[1], [])

    def test_unreadable_profile_refuses_start_but_does_not_block_stop(self):
        self.f.second.config.write_text('invalid config')
        refused = self.run_action('start')
        self.assertEqual(refused['status'], 400)
        self.assertIn('storage settings could not be read', refused['error'])
        self.assertEqual(self.docker.posts, [])
        self.docker.current['running'] = True
        self.assertTrue(self.run_action('stop')['data']['ok'])
        items = self.client.call_args.args[1]
        self.assertEqual([drive for drive, _ in items], ['legacy'])

    def test_all_existing_connection_settings_unreadable_refuses_to_guess_daemon(self):
        self.f.main.config.write_text('invalid config')
        self.f.second.config.write_text('invalid config')
        result = self.run_action('start')
        self.assertEqual(result['status'], 400)
        self.assertIn('connection settings', result['error'])
        self.client.assert_not_called()

    def test_stopped_restart_is_explicitly_allowed(self):
        result = self.run_action('restart')
        self.assertTrue(result['data']['ok'], result)
        self.assertEqual(self.docker.posts[0][0], '/containers/' + IDENTITY + '/restart?t=30')
        self.assertEqual(self.docker.posts[0][1]['timeout'], 40)

    def test_already_running_start_and_already_stopped_stop_send_no_post(self):
        for running, action in ((True, 'start'), (False, 'stop')):
            self.docker.current['running'] = running
            result = self.run_action(action)
            self.assertTrue(result['data']['ok'])
            self.assertFalse(result['data']['changed'])
        self.assertEqual(self.docker.posts, [])

    def test_start_stop_304_race_requires_authoritative_result(self):
        for action, running in (('start', True), ('stop', False)):
            with self.subTest(action=action):
                self.docker.current['running'] = not running
                def no_op(path, kwargs):
                    self.assertEqual(kwargs['allowed_status'], (304,))
                    self.docker.current['running'] = running
                self.docker.post_hook = no_op
                result = self.run_action(action)['data']
                self.assertTrue(result['ok'])
                self.assertNotIn('changed', result)
                self.assertEqual(result['container']['state'], 'running' if running else 'stopped')
        self.assertEqual(len(self.docker.posts), 2)

    def test_bad_identity_and_unsupported_states_never_send_post(self):
        original = copy.deepcopy(self.docker.current)
        for changes in (dict(id=OTHER), dict(name='replacement'), dict(paused=True),
                        dict(dead=True), dict(restarting=True), dict(running='yes')):
            with self.subTest(changes=changes):
                self.docker.current = dict(original, **changes)
                self.assertEqual(self.run_action('start')['status'], 400)
        self.assertEqual(self.docker.posts, [])

    def test_invalid_request_authentication_and_global_route(self):
        for changes in (dict(confirm=False), dict(confirm=1), dict(action='kill'),
                        dict(id='erugo'), dict(name='../erugo'), dict(extra='unexpected')):
            data = dict(self.data('start'), **changes)
            self.assertEqual(self.f.request('docker-container-action', data, profile=None)['status'], 400)
        self.assertEqual(self.f.request('docker-container-action', self.data('start'))['status'], 400)
        self.assertEqual(self.f.request('docker-container-action', profile=None)['status'], 400)
        for token, csrf in (('', self.f.session['csrf']), (self.f.session['token'], 'wrong')):
            result = self.f.main.broker.handle(dict(action='docker-container-action', write=True,
                data=self.data('start'), drive=None, token=token, csrf=csrf))
            self.assertEqual(result['status'], 401)
        self.assertEqual(self.docker.posts, [])

    def test_actual_web_allowlist_exposes_authenticated_post_not_get(self):
        web = self.f.main.web.create_app(dict(self.b.common.DEFAULT), transport=self.f.main.broker.handle)
        with web.test_client() as client:
            self.assertEqual(client.get('/api/docker-container-action', base_url='http://localhost:8765').status_code, 404)
            response = client.post('/api/docker-container-action', json=self.data('start'),
                                   base_url='http://localhost:8765', headers={'X-USW-Request': '1', 'Origin': 'http://localhost:8765'})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(self.docker.posts, [])
            client.set_cookie('usw_session', self.f.session['token'], domain='localhost')
            response = client.post('/api/docker-container-action', json=self.data('start'),
                                   base_url='http://localhost:8765', headers={
                                       'X-USW-Request': '1', 'Origin': 'http://localhost:8765',
                                       'X-CSRF-Token': self.f.session['csrf']})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()['ok'])
        self.assertEqual(len(self.docker.posts), 1)

    def test_same_shared_lock_blocks_manual_action_during_automatic_recovery(self):
        directory = self.b.cli.drives.roots(self.b.s)[1] / 'shared-locks'
        # Independent open-file description models the automatic worker process.
        fd = os.open(directory / ('docker-restart-' + IDENTITY + '.lock'), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_action('restart')
        finally:
            os.close(fd)
        self.assertEqual(result['status'], 400, result)
        self.assertIn('Another operation', result['error'])
        self.client.assert_not_called()

    def test_slow_docker_call_does_not_hold_configuration_or_drive_request_locks(self):
        observed = []
        def during_post(path, kwargs):
            def check():
                with self.b.cli.drives.configuration_lock(self.b.s):
                    observed.append('settings unlocked')
                for m in (self.f.main, self.f.second):
                    acquired = m.broker.request_lock.acquire(blocking=False)
                    observed.append(acquired)
                    if acquired: m.broker.request_lock.release()
            thread = threading.Thread(target=check)
            thread.start(); thread.join(3)
            self.assertFalse(thread.is_alive())
            self.docker.current.update(running=True, started_at='new-start')
        self.docker.post_hook = during_post
        self.assertTrue(self.run_action('start')['data']['ok'])
        self.assertEqual(observed, ['settings unlocked', True, True])

    def test_concurrent_manual_double_click_does_not_queue_second_post(self):
        entered, release = threading.Event(), threading.Event()
        result = []
        def during_post(path, kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            self.docker.current.update(running=True, started_at='new-start')
        self.docker.post_hook = during_post
        thread = threading.Thread(target=lambda: result.append(self.run_action('restart')))
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            duplicate = self.run_action('restart')
            self.assertEqual(duplicate['status'], 400, duplicate)
            self.assertEqual(len(self.docker.posts), 1)
        finally:
            release.set(); thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result[0]['data']['ok'])

    def test_unknown_post_result_reads_back_and_never_repeats_command(self):
        def lost(path, kwargs):
            self.docker.current.update(running=True, started_at='new-start')
            raise OSError('private daemon failure text')
        self.docker.post_hook = lost
        result = self.run_action('restart')['data']
        self.assertFalse(result['ok']); self.assertTrue(result['uncertain'])
        self.assertEqual(result['container']['state'], 'running')
        self.assertNotIn('private daemon', json.dumps(result))
        self.assertEqual(len(self.docker.posts), 1)

    def test_accepted_post_with_missing_readback_reports_unknown_and_releases_lock(self):
        def accepted(path, kwargs): self.docker.read_error = True
        self.docker.post_hook = accepted
        result = self.run_action('start')['data']
        self.assertFalse(result['ok']); self.assertTrue(result['uncertain'])
        self.assertIsNone(result['container'])
        self.docker.read_error = False; self.docker.post_hook = None
        self.assertTrue(self.run_action('start')['data']['ok'])
        self.assertEqual(len(self.docker.posts), 2)

    def test_restart_must_observe_new_start_time_not_just_old_running_state(self):
        self.docker.current['running'] = True
        self.docker.post_hook = lambda path, kwargs: None
        result = self.run_action('restart')['data']
        self.assertFalse(result['ok']); self.assertTrue(result['uncertain'])
        self.assertIn('new container start was not verified', result['message'])
        self.assertEqual(len(self.docker.posts), 1)

    def test_stopped_after_accepted_start_is_failure_not_success(self):
        self.docker.post_hook = lambda path, kwargs: None
        result = self.run_action('start')['data']
        self.assertFalse(result['ok']); self.assertFalse(result['uncertain'])
        self.assertEqual(result['container']['state'], 'stopped')

    def test_unhealthy_running_is_truthful_command_result_not_upload_success(self):
        self.docker.current['health'] = 'unhealthy'
        result = self.run_action('start')['data']
        self.assertTrue(result['ok'])
        self.assertIn('health check reports unhealthy', result['message'])
        self.assertIn('file access has not been tested', result['message'])


class DockerNoOpResponses(unittest.TestCase):
    def test_304_is_opt_in_for_manual_start_stop_only(self):
        apps = load('apps')
        connection = Mock()
        connection.getresponse.return_value = Mock(status=304, read=lambda _: b'')
        with patch.object(apps, 'LocalConnection', return_value=connection):
            with self.assertRaises(apps.AppError):
                apps.Docker().request('POST', '/containers/' + IDENTITY + '/restart')
            self.assertIsNone(apps.Docker().request('POST', '/containers/' + IDENTITY + '/start', allowed_status=(304,)))
            self.assertIsNone(apps.Docker().request('POST', '/containers/' + IDENTITY + '/stop?t=30', allowed_status=(304,)))
        self.assertEqual(connection.close.call_count, 3)


if __name__ == '__main__':
    unittest.main()
