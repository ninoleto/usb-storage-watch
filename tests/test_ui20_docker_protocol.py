# SPDX-License-Identifier: MIT
"""Docker lifecycle and actual HTTP framing, using an isolated loopback server."""
import copy
import http.client
import http.server
import json
from pathlib import Path
import socketserver
import tempfile
import threading
import unittest
from unittest.mock import patch

from gui_fixture import load
from test_apps import Temp, a, w, observation
import test_ui18_docker_actions as manual_fixture

IDENTITY = 'a' * 64


class StopBeforeRecovery(Temp):
    def stop(self, **extra):
        request = dict(incident='test-outage', boot='boot-test', **extra)
        return a.stop_selected(self.ctx, request, self.docker)

    def test_failure_stops_even_when_storage_unavailable(self):
        self.healthy = False
        result = self.stop()
        self.assertTrue(result['all_stopped'], result)
        self.assertEqual([row[2] for row in self.docker.changes], ['stop'] * 3)
        self.ctx.verify_main.assert_not_called()
        self.ctx.verify_dependent.assert_not_called()
        self.stop()
        self.assertEqual(len(self.docker.changes), 3)

    def test_already_stopped_is_verified_without_command(self):
        for current in self.docker.containers.values():
            current['running'] = False
        result = self.stop()
        self.assertTrue(result['all_stopped'])
        self.assertEqual(self.docker.changes, [])
        self.assertTrue(all(v['status'] == 'already_stopped' for v in result['containers'].values()))

    def test_unknown_stop_acceptance_reads_back_without_repeating(self):
        self.docker.timeout_after_apply.add('app_one')
        result = self.stop()
        self.assertTrue(result['all_stopped'])
        self.assertIn('api_error', result['containers']['app_one'])
        self.stop()
        self.assertEqual(len(self.docker.changes), 3)

    def test_rejected_stop_never_repeats_or_reports_all_stopped(self):
        self.docker.fail.add('app_one')
        result = self.stop()
        self.assertFalse(result['all_stopped'])
        self.assertEqual(result['containers']['app_one']['status'], 'failed')
        self.docker.fail.clear()
        result = self.stop()
        self.assertFalse(result['all_stopped'])
        self.assertEqual([row[0] for row in self.docker.changes].count('app_one'), 1)

    def test_saved_intent_after_process_death_is_read_only(self):
        value = dict(version=1, incident='test-outage', boot='boot-test', complete=False,
                     containers={name: dict(status='intent', action_count=1, container_id=current['id'])
                                 for name, current in self.docker.containers.items()})
        a.save_stop(self.ctx, value)
        result = self.stop()
        self.assertFalse(result['all_stopped'])
        self.assertEqual(self.docker.changes, [])

    def test_stop_deselection_does_not_send_command(self):
        with patch.object(a, 'selected_now', return_value=False):
            result = self.stop()
        self.assertTrue(result['all_stopped'])
        self.assertEqual(self.docker.changes, [])

    def test_verified_stop_then_new_container_execution_gets_one_new_stop(self):
        self.stop()
        self.docker.containers['app_one'].update(running=True, started_at='new-runtime-after-stop')
        result = self.stop()
        self.assertTrue(result['all_stopped'])
        entry = result['containers']['app_one']
        self.assertEqual(len(entry['stop_history']), 1)
        self.assertEqual([row[0] for row in self.docker.changes].count('app_one'), 2)
        self.stop()
        self.assertEqual([row[0] for row in self.docker.changes].count('app_one'), 2)

    def test_boot_change_rechecks_state_and_stops_only_a_proven_new_execution(self):
        self.stop()
        self.docker.containers['app_one'].update(running=True, started_at='boot-policy-new-runtime')
        self.ctx.boot_id = lambda: 'new-boot'
        result = a.stop_selected(self.ctx, dict(incident='test-outage', boot='new-boot'), self.docker)
        self.assertTrue(result['all_stopped'])
        self.assertEqual(result['boot'], 'new-boot')
        self.assertEqual([row[0] for row in self.docker.changes].count('app_one'), 2)
        self.assertEqual([row[0] for row in self.docker.changes].count('app_two'), 1)

    def test_uncertain_stop_gets_new_epoch_only_after_actual_host_reboot(self):
        self.docker.fail.add('app_one')
        self.stop()
        self.docker.fail.clear()
        self.docker.containers['app_one']['started_at'] = 'new-boot-runtime'
        self.ctx.boot_id = lambda: 'new-boot'
        result = a.stop_selected(self.ctx, dict(incident='test-outage', boot='new-boot'), self.docker)
        self.assertTrue(result['all_stopped'])
        self.assertEqual([row[0] for row in self.docker.changes].count('app_one'), 2)
        history = result['containers']['app_one']['stop_history']
        self.assertEqual(history[0]['status'], 'failed')
        self.assertEqual(history[0]['action_boot'], 'boot-test')
        a.stop_selected(self.ctx, dict(incident='test-outage', boot='new-boot'), self.docker)
        self.assertEqual([row[0] for row in self.docker.changes].count('app_one'), 2)

    def test_claimed_boot_change_without_actual_host_reboot_never_resets_budget(self):
        self.docker.fail.add('app_one')
        self.stop()
        with self.assertRaisesRegex(a.AppError, 'another host boot'):
            a.stop_selected(self.ctx, dict(incident='test-outage', boot='invented-boot'), self.docker)
        self.assertEqual([row[0] for row in self.docker.changes].count('app_one'), 1)

    def test_unknown_stop_after_daemon_restart_in_same_host_boot_is_not_repeated(self):
        self.docker.fail.add('app_one')
        self.stop()
        self.docker.fail.clear()
        self.docker.containers['app_one']['started_at'] = 'new-daemon-runtime-same-host'
        result = self.stop()
        self.assertFalse(result['all_stopped'])
        self.assertEqual([row[0] for row in self.docker.changes].count('app_one'), 1)

    def test_preboot_start_intent_gets_new_epoch_only_after_fresh_verified_stop(self):
        request = self.ready()
        def crash(name):
            raise KeyboardInterrupt()
        self.docker.after_change = crash
        with self.assertRaises(KeyboardInterrupt):
            a.recover(self.ctx, request, self.docker)
        old_receipt = a.ledger_path(self.ctx).read_text()
        self.assertEqual(json.loads(old_receipt)['containers']['app_one']['status'], 'intent')
        # The host rebooted while the start acknowledgement was unresolved.
        # Docker's restart policy has started a new execution in the new boot.
        self.docker.after_change = lambda name: None
        self.docker.containers['app_one'].update(running=True, started_at='new-boot-policy-start')
        self.ctx.boot_id = lambda: 'new-boot'
        restarted = w.Monitor(self.directory/'state.json', now=0, boot='new-boot')
        stop_request = restarted.stop_request(0)
        self.assertIsNotNone(stop_request)
        stopped = a.stop_selected(self.ctx, stop_request, self.docker)
        self.assertTrue(stopped['all_stopped'])
        restarted.stop_result(stopped)
        restarted.sample(observation(), 0)
        restarted.sample(observation(), 15)
        resumed = restarted.app_request()
        self.assertIsNotNone(resumed)
        result = a.recover(self.ctx, resumed, self.docker)
        self.assertTrue(result['all_verified'], result)
        self.assertEqual(result['boot'], 'new-boot')
        self.assertEqual(result['previous_boot'], 'boot-test')
        self.assertIn(old_receipt, [path.read_text() for path in (self.directory/'application-history').glob('start-epoch-*.json')])
        self.assertEqual([row[2] for row in self.docker.changes if row[0] == 'app_one'], ['start', 'stop', 'start'])
        a.recover(self.ctx, resumed, self.docker)
        self.assertEqual([row[2] for row in self.docker.changes if row[0] == 'app_one'], ['start', 'stop', 'start'])

    def test_new_boot_without_persisted_fresh_stop_preserves_old_start_intent(self):
        request = self.ready()
        value = dict(version=1, incident=request['incident'], boot='previous-boot', complete=False,
                     containers={'app_one': dict(status='intent', action_count=1, container_id='1' * 64)})
        a.save(self.ctx, value)
        original = a.ledger_path(self.ctx).read_text()
        with self.assertRaisesRegex(a.AppError, 'fresh container stop'):
            a.recover(self.ctx, request, self.docker)
        self.assertEqual(a.ledger_path(self.ctx).read_text(), original)
        self.assertEqual(self.docker.changes, [])

    def test_missing_stop_result_does_not_start(self):
        request = self.ready()
        request['stop'] = None
        result = a.recover(self.ctx, request, self.docker)
        self.assertFalse(result['all_verified'])
        self.assertEqual(self.docker.changes, [])

    def test_other_drive_wait_is_durable_and_later_starts_once(self):
        request = self.ready()
        with patch.object(a, 'other_selected_storage', side_effect=a.StorageWaiting('Other disk absent')):
            first = a.recover(self.ctx, request, self.docker)
        self.assertFalse(first['complete'])
        self.assertTrue(first['waiting_storage'])
        self.assertEqual(self.docker.changes, [])
        second = a.recover(self.ctx, request, self.docker)
        self.assertTrue(second['all_verified'], second)
        self.assertEqual([x[2] for x in self.docker.changes], ['start'] * 3)
        a.recover(self.ctx, request, self.docker)
        self.assertEqual(len(self.docker.changes), 3)

    def test_selected_image_failure_leaves_container_stopped(self):
        request = self.ready()
        image = dict(uuid='11111111-1111-4111-8111-111111111111', name='backup image')
        apps = copy.deepcopy(a.APPS)
        apps['app_one']['images'] = [image['uuid']]
        def attempted(w, request, value):
            value['images'] = {image['uuid']: dict(name=image['name'], status='warning', detail='Mount failed')}
        with patch.object(a, 'APPS', apps), patch.object(a, 'registered_images', return_value=[image]), \
             patch.object(a, 'prepare_images', side_effect=attempted):
            result = a.recover(self.ctx, request, self.docker)
        self.assertNotIn('app_one', [row[0] for row in self.docker.changes])
        self.assertEqual(result['containers']['app_one']['status'], 'failed')
        self.assertIn('stays stopped', result['containers']['app_one']['reason'])
        self.assertEqual([row[0] for row in self.docker.changes], ['app_two', 'app_three'])


class WireHTTPServer(socketserver.TCPServer):
    allow_reuse_address = True


class DockerWireTests(unittest.TestCase):
    def setUp(self):
        self.apps = load('apps')
        self.tmp = tempfile.TemporaryDirectory(prefix='usw-wire-')
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'docker.sock')
        self.requests = []
        self.response = (204, b'')
        case = self
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *args):
                pass
            def do_POST(self):
                length = int(self.headers.get('Content-Length', '0'))
                body = self.rfile.read(length)
                case.requests.append(dict(path=self.path, length=self.headers.get('Content-Length'), body=body))
                status, data = case.response
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(data)
        self.server = WireHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        # AF_UNIX server sockets are forbidden in this test environment. The
        # production HTTP client/parser is exercised against a real TCP server;
        # only the socket transport is replaced, not request/response handling.
        port = self.server.server_address[1]
        class TestConnection(http.client.HTTPConnection):
            def __init__(self, host, timeout):
                super().__init__('127.0.0.1', port, timeout=timeout)
        self.enterContext(patch.object(self.apps, 'LocalConnection', TestConnection))
        self.enterContext(patch.object(self.apps, 'API', '/v1.47'))

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def test_actual_post_framing_empty_start_and_204(self):
        result = self.apps.Docker().request('POST', '/containers/' + IDENTITY + '/start')
        self.assertIsNone(result)
        self.assertEqual(self.requests, [dict(path='/v1.47/containers/' + IDENTITY + '/start', length='0', body=b'')])

    def test_actual_304_noop_is_allowed_only_explicitly(self):
        self.response = (304, b'')
        self.assertIsNone(self.apps.Docker().request('POST', '/containers/' + IDENTITY + '/stop?t=30', allowed_status=(304,)))
        with self.assertRaises(self.apps.DockerHTTPError) as error:
            self.apps.Docker().request('POST', '/containers/' + IDENTITY + '/restart?t=30')
        self.assertEqual(error.exception.status, 304)

    def test_daemon_refusal_keeps_cause_without_secret_or_raw_body(self):
        cases = [('invalid mount config: bind source path does not exist: /private/token', 'storage folder'),
                 ('driver failed programming connectivity: bind: cannot assign requested address secret', 'host IP address'),
                 ('Bind for 0.0.0.0:8080 failed: port is already allocated secret', 'published port'),
                 ('failed to bind host port for 0.0.0.0:8080: address already in use secret', 'published port'),
                 ('permission denied private-token', 'denied access')]
        for daemon, expected in cases:
            with self.subTest(expected=expected):
                self.response = (500, json.dumps(dict(message=daemon)).encode())
                with self.assertRaises(self.apps.DockerHTTPError) as error:
                    self.apps.Docker().request('POST', '/containers/' + IDENTITY + '/start')
                self.assertIn(expected, str(error.exception))
                self.assertNotIn('private', str(error.exception))
                self.assertNotIn('secret', str(error.exception))
                self.assertEqual(error.exception.status, 500)
        self.assertEqual(len(self.requests), len(cases))


class ManualDefiniteRefusal(manual_fixture.ManualControls):
    def test_definite_daemon_error_is_actionable_not_transport_uncertainty(self):
        module = load('apps')
        def refuse(path, kwargs):
            raise module.daemon_refusal(500, b'{"message":"bind source path does not exist: /private/token"}')
        self.docker.post_hook = refuse
        result = self.run_action('start')['data']
        self.assertFalse(result['ok'])
        self.assertFalse(result['uncertain'])
        self.assertIn('storage folder', result['message'])
        self.assertNotIn('/private/token', result['message'])
        self.assertEqual(len(self.docker.posts), 1)


if __name__ == '__main__':
    unittest.main()
