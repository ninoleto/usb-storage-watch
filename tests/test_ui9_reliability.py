# SPDX-License-Identifier: MIT
"""Resource, request isolation and image preference regressions; synthetic disks."""
from contextlib import ExitStack, redirect_stdout
import errno
import gc
import io
import os
from pathlib import Path
import socketserver
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gui_fixture import load
from multidrive_fixture import FleetMachine
from test_application_storage import image

b = load('web_broker')


class HistoryResources(unittest.TestCase):
    def test_repeated_reads_writes_close_descriptors_without_gc(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(b.s, 'STATE_DIR', Path(tmp)):
            history = b.History(Path(tmp) / 'history.db')
            gc.collect()
            before = len(os.listdir('/proc/self/fd'))
            enabled = gc.isenabled()
            gc.disable()
            try:
                for i in range(500):
                    history.record(str(i), str(i), 'Synthetic event', ['Synthetic detail'])
                    history.events()
                self.assertLessEqual(len(os.listdir('/proc/self/fd')), before + 1)
            finally:
                if enabled:
                    gc.enable()

    def test_transaction_commits_rolls_back_and_always_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = b.History(Path(tmp) / 'history.db')
            with history.connect() as db:
                db.execute("INSERT INTO events VALUES ('one','now','title','detail')")
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
            with self.assertRaisesRegex(ValueError, 'rollback'):
                with history.connect() as failed:
                    failed.execute("INSERT INTO events VALUES ('two','now','title','detail')")
                    raise ValueError('rollback')
            with self.assertRaises(sqlite3.ProgrammingError):
                failed.execute('SELECT 1')
            with history.connect() as check:
                self.assertEqual(check.execute('SELECT id FROM events').fetchall(), [('one',)])

    def test_database_lock_fails_within_bounded_wait_then_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = b.History(Path(tmp) / 'history.db')
            with history.connect() as held:
                held.execute('BEGIN EXCLUSIVE')
                start = time.monotonic()
                with self.assertRaises(sqlite3.OperationalError):
                    history.record('blocked', 'now', 'title', [])
                self.assertLess(time.monotonic() - start, 1.5)
            history.record('after', 'now', 'title', [])


class BrokerAvailability(unittest.TestCase):
    def test_slow_background_history_does_not_block_actual_unix_requests(self):
        entered, release = threading.Event(), threading.Event()
        def capture():
            entered.set()
            release.wait(3)
        broker = SimpleNamespace(request_lock=threading.RLock(), prepare_progress=Mock(), fleet=None)
        history = SimpleNamespace(capture=capture)
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                b.common.receive(self.rfile)
                self.wfile.write(b'{"status":200,"data":{"alive":true}}\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'broker.sock')
            try:
                actual_server=b.BrokerServer(path, Handler, broker=broker, history=history)
            except PermissionError:
                self.skipTest('This runtime forbids Unix sockets; real service acceptance requires the Ubuntu host.')
            with actual_server as server:
                thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':0.01}, daemon=True)
                thread.start()
                try:
                    self.assertTrue(entered.wait(1))
                    original_observer = server.observer
                    with patch.object(b.common, 'SOCKET', path):
                        for _ in range(10):
                            self.assertTrue(b.common.rpc({'write':False})['data']['alive'])
                    self.assertIs(server.observer, original_observer)
                finally:
                    release.set()
                    server.shutdown()
                    thread.join(1)
                    server.observer.join(1)

    def test_blocked_observer_allows_request_dispatch_and_never_overlaps(self):
        entered, release, handled = threading.Event(), threading.Event(), threading.Event()
        def capture():
            entered.set();release.wait(3)
        broker=SimpleNamespace(request_lock=threading.RLock(),prepare_progress=Mock(),fleet=None)
        with patch.object(b.socket,'socket',return_value=Mock()):
            with b.BrokerServer('/synthetic/broker.sock',socketserver.BaseRequestHandler,
                                broker=broker,history=SimpleNamespace(capture=capture)) as server:
                try:
                    server.service_actions()
                    self.assertTrue(entered.wait(1))
                    original=server.observer
                    for _ in range(30):
                        server.next_observation=0
                        server.service_actions()
                        self.assertIs(server.observer,original)
                    with patch.object(server,'finish_request',side_effect=lambda *_:handled.set()):
                        server.process_request(Mock(),None)
                        self.assertTrue(handled.wait(1))
                finally:
                    release.set();server.observer.join(1)

    def test_accept_resource_exhaustion_backs_off_and_logs_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(b.socket,'socket',return_value=Mock()):
            with b.BrokerServer(str(Path(tmp)/'test.sock'), socketserver.BaseRequestHandler,
                                broker=Mock(), history=Mock()) as server:
                output = io.StringIO()
                with patch.object(socketserver.UnixStreamServer, 'get_request', side_effect=OSError(errno.EMFILE, 'sensitive-path')), \
                     patch.object(b.time, 'sleep') as sleep, redirect_stdout(output):
                    for _ in range(3):
                        with self.assertRaises(OSError):
                            server.get_request()
                self.assertEqual(sleep.call_count, 3)
                sleep.assert_called_with(0.25)
                self.assertEqual(output.getvalue().count('Administration accept'), 1)
                self.assertIn('errno=24', output.getvalue())
                self.assertNotIn('sensitive-path', output.getvalue())

    def test_request_capacity_is_bounded_and_rejection_closes_socket(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(b.socket,'socket',return_value=Mock()):
            with b.BrokerServer(str(Path(tmp)/'test.sock'), socketserver.BaseRequestHandler,
                                broker=Mock(), history=Mock()) as server:
                for _ in range(16):
                    self.assertTrue(server.request_slots.acquire(False))
                client = Mock()
                server.process_request(client, None)
                self.assertIn(b'503', client.sendall.call_args.args[0])
                client.close.assert_called_once()
                for _ in range(16):
                    server.request_slots.release()

    def test_busy_drive_refuses_quickly_other_drive_still_responds(self):
        fleet = FleetMachine()
        self.addCleanup(fleet.close)
        other = fleet.add()
        entered, release = threading.Event(), threading.Event()
        def hold():
            with fleet.main.broker.request_lock:
                entered.set()
                release.wait(3)
        thread = threading.Thread(target=hold)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            start = time.monotonic()
            self.assertEqual(fleet.request('status')['status'], 409)
            self.assertLess(time.monotonic()-start, 1.5)
            self.assertEqual(fleet.request('status', profile=other)['status'], 200)
        finally:
            release.set()
            thread.join(1)

    def test_fleet_includes_current_passive_standby(self):
        fleet = FleetMachine()
        self.addCleanup(fleet.close)
        fleet.main.patch(fleet.main.b.w.standby, 'status', lambda _ctx: {'applicable':True,'state':'active','sleeping':False})
        result = fleet.request('fleet-status')
        self.assertEqual(result['status'], 200)
        row = next(r for r in result['data']['drives'] if r['profile_id']=='legacy')
        self.assertEqual(row['standby']['state'], 'active')


class IndependentImageRecovery(unittest.TestCase):
    def setUp(self):
        self.w = load('engine')
        self.c = self.w.settings.default()
        self.c['disk'].update(uuid='11111111-1111-4111-8111-111111111111', mountpoint='/mnt/storage', fstab_options='defaults')
        self.c['images'] = [image(2), image(3)]
        self.c['images'][1]['enabled'] = False
        self.c['images'][1]['fstab_options'] += ',noauto'
        self.w.configure(self.c)

    def test_next_recovery_mounts_only_images_with_preference_enabled(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            for name in ('verify_main','verify_access','verify_dependent'):
                stack.enter_context(patch.object(self.w, name))
            stack.enter_context(patch.object(self.w,'snapshot',return_value={'healthy':True,'detected':True,'mounts':[]}))
            stack.enter_context(patch.object(self.w,'recover_image',side_effect=lambda item,*args:calls.append(item['uuid'])))
            result=self.w.recovery_work({'incident':'synthetic','number':1}, Path(tmp)/'receipt')
            self.assertTrue(result['dependent'])
            self.assertEqual(calls, [self.c['images'][0]['uuid']])

    def test_only_image_unmounted_does_not_start_a_drive_outage(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=self.w.Monitor(Path(tmp)/'state.json', boot='synthetic')
            state={'healthy':True,'dependent':False,'dependent_detail':'User unmounted image','detected':True,'detail':'Main mount healthy','mounts':[]}
            engine.sample(state, now=100, wall='first')
            engine.sample(state, now=115, wall='second')
            self.assertIsNone(engine.state['incident'])
            self.assertIsNone(engine.work_request(True, now=200))

    def test_disabled_image_manual_mount_uses_its_own_registered_fstab(self):
        item=self.c['images'][1]
        text=f"{item['image']} {item['mountpoint']} ext4 {item['fstab_options']} 0 0\n"
        with patch.object(self.w.Path,'read_text',return_value=text):
            self.w.fstab_check(item['mountpoint'])
        with patch.object(self.w.Path,'read_text',return_value=text.replace(item['image'],'/wrong.img')):
            with self.assertRaises(self.w.Unsafe):
                self.w.fstab_check(item['mountpoint'])


class PassiveActivity(unittest.TestCase):
    def test_rapid_refresh_preserves_active_then_idle_without_power_commands(self):
        standby=load('standby')
        with tempfile.TemporaryDirectory() as tmp:
            now=[10.0]; counters=[1]
            w=SimpleNamespace(STATE_DIR=Path(tmp),clock_now=lambda:now[0],Unsafe=RuntimeError)
            with patch.object(standby,'identity',return_value={'connection':1}), \
                 patch.object(standby,'storage_kind',return_value='mechanical'), \
                 patch.object(standby,'activity',side_effect=lambda _: (list(counters),0)), \
                 patch.object(standby,'power_command') as power:
                self.assertEqual(standby.status(w)['state'],'unknown')
                counters[0]+=1;now[0]+=.1
                self.assertEqual(standby.status(w)['state'],'active')
                for _ in range(5):
                    now[0]+=.1
                    result=standby.status(w)
                    self.assertEqual(result['state'],'active')
                    self.assertIn('Disk I/O observed',result['message'])
                now[0]+=1
                self.assertEqual(standby.status(w)['state'],'idle')
                now[0]+=.01
                self.assertEqual(standby.status(w)['state'],'idle')
                power.assert_not_called()


if __name__=='__main__':
    unittest.main()
