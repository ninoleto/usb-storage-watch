# SPDX-License-Identifier: MIT
"""UI10 refusal and LAN transaction regressions. Synthetic OS boundaries only."""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from gui_fixture import load, UUID
import test_usb_peers as peers


class ReconnectRefusals(unittest.TestCase):
    def setUp(self):
        self.b = load('web_broker')
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        c = self.b.s.default(); c['disk']['uuid'] = UUID
        self.stack.enter_context(patch.object(self.b, 'configuration', return_value=c))
        self.stack.enter_context(patch.object(self.b.s, 'STATE_DIR', self.root))
        self.stack.enter_context(patch.object(self.b.w, 'configure'))
        self.select = self.stack.enter_context(patch.object(self.b.w.usb, 'select_current', return_value={}))
        self.stack.enter_context(patch.object(self.b.w.manual_usb, 'capabilities', return_value={}))
        self.port = self.stack.enter_context(patch.object(self.b.w.manual_usb, 'unmounted'))
        self.command = self.stack.enter_context(patch.object(self.b, 'command'))
        self.worker = Mock(); self.worker.poll.return_value = True
        self.create = self.stack.enter_context(patch.object(self.b.w, 'Worker', return_value=self.worker))
        self.active = True
        self.stack.enter_context(patch.object(self.b, 'service_state', side_effect=lambda: dict(ActiveState='active' if self.active else 'inactive')))

    def test_broker_refusal_keeps_mounts_and_monitor_on_or_off_no_worker(self):
        for active in (True, False):
            self.active = active
            self.port.side_effect = self.b.w.Unsafe('USB2/USB3 peer contains an unrelated device.')
            result = self.b.disk_operation(dict(action='reconnect', uuid=UUID))
            self.assertFalse(result['ok']); self.assertTrue(result['storage_unchanged'])
            self.assertIn('left unchanged', result['message'])
            self.assertEqual(result['service']['ActiveState'], 'active' if active else 'inactive')
            self.assertEqual(json.loads((self.root/'manual-operation.json').read_text()), result['last_operation'])
        self.command.assert_not_called(); self.create.assert_not_called()

    def test_refusal_between_broker_and_worker_preflight_restores_previous_monitor(self):
        for active in (True, False):
            self.active=active; self.command.reset_mock()
            self.worker.output=io.BytesIO(json.dumps(dict(ok=False,storage_unchanged=True,message='Peer changed before unmount.')).encode())
            result=self.b.disk_operation(dict(action='reconnect',uuid=UUID))
            starts=[call for call in self.command.call_args_list if 'start' in call.args[0]]
            self.assertEqual(len(starts), 0)
            self.command.assert_not_called()
            self.assertIn('Monitoring was left unchanged',result['message'])

    def test_uncertain_or_changed_storage_never_claims_unchanged_or_restarts_monitor(self):
        for flag in (False, 'true', None):
            self.command.reset_mock()
            self.worker.output=io.BytesIO(json.dumps(dict(ok=False,storage_unchanged=flag,message='Operation failed after unmount.')).encode())
            result=self.b.disk_operation(dict(action='reconnect',uuid=UUID))
            self.assertFalse(result['ok'])
            self.assertFalse(any('start' in call.args[0] for call in self.command.call_args_list))

    def test_worker_preflight_rejects_before_unmount_or_cycle(self):
        controls=load('controls'); w=Mock(STATE_DIR=self.root, Unsafe=ValueError, WORKER_LOCK_FDS=(), assert_internal_state=Mock())
        w.usb.ensure_enabled.return_value=True
        w.manual_usb.unmounted.side_effect=ValueError('Mounted storage')
        with patch.object(controls,'request',return_value={}),patch.object(controls,'unmount') as unmount:
            with self.assertRaisesRegex(ValueError,'Mounted storage') as error: controls.perform(w,'reconnect')
            unmount.assert_not_called(); w.usb.cycle.assert_not_called(); w.recovery_work.assert_not_called()
        self.assertEqual(w.WORKER_LOCK_FDS,())
        with (self.root/'monitor.lock').open('a') as monitor, (self.root/'recovery.lock').open('a') as recovery:
            controls.fcntl.flock(monitor,controls.fcntl.LOCK_EX|controls.fcntl.LOCK_NB)
            controls.fcntl.flock(recovery,controls.fcntl.LOCK_EX|controls.fcntl.LOCK_NB)


class PeerDiagnostics(unittest.TestCase):
    def setUp(self):
        fixture=peers.USBPeerTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        for name in ('controller','hs','ss','u'):setattr(self,name,getattr(fixture,name))

    def test_occupied_peer_reports_exact_ports_and_device_without_writing(self):
        child=self.controller/'usb2'/'2-3';child.mkdir()
        (child/'manufacturer').write_text('Synthetic vendor')
        (child/'product').write_text('Unrelated USB stick')
        (self.hs/'device').symlink_to(child)
        result=self.u.peer_diagnostic(self.ss)
        self.assertFalse(result['supported'])
        for value in ('usb3-port7','usb2-port3','Unrelated USB stick','must not be disconnected'):
            self.assertIn(value,result['message'])
        self.assertEqual((self.ss/'disable').read_text(),'0\n')
        self.assertEqual((self.hs/'disable').read_text(),'0\n')


class NetworkTransactions(unittest.TestCase):
    def setUp(self):
        self.b=load('web_broker'); b=self.b
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.config=self.root/'config.json';self.config.write_text(json.dumps(b.common.DEFAULT))
        for target,name,value in ((b.common,'WEB_DIR',self.root),(b.common,'WEB_CONFIG',self.config),(b.s,'STATE_DIR',self.root)):
            self.stack.enter_context(patch.object(target,name,value))
        self.stack.enter_context(patch.object(b.pwd,'getpwnam',return_value=SimpleNamespace(pw_gid=os.getgid())))
        self.stack.enter_context(patch.object(b.os,'chown'))
        self.commands=[];self.service='inactive';self.pid='0'
        def command(argv,*_):
            self.commands.append(argv)
            if 'show' in argv:return 'ActiveState='+self.service+'\nMainPID='+self.pid
            return ''
        self.stack.enter_context(patch.object(b,'command',side_effect=command))

    def apply(self,enabled):
        value=dict(self.b.common.DEFAULT,lan=enabled,scheme='http',address='192.168.50.24',hostname='192.168.50.24')
        self.b.NETWORK_LOCK.acquire()
        self.b.apply_network(value,{'config.json':json.dumps(value)},'synthetic-operation')
        self.assertFalse(self.b.NETWORK_LOCK.locked())
        self.assertTrue(all(self.b.LAN_SERVICE in cmd for cmd in self.commands))
        return self.b.lan_status()

    def test_enable_reports_success_only_after_listener_check(self):
        with patch.object(self.b,'lan_ready') as ready:
            result=self.apply(True)
        ready.assert_called_once();self.assertEqual(result['phase'],'complete')
        self.assertTrue(result['enabled']);self.assertTrue(json.loads(self.config.read_text())['lan'])

    def test_disable_verified_inactive_with_zero_pid(self):
        result=self.apply(False)
        self.assertEqual(result['phase'],'complete');self.assertFalse(result['enabled'])

    def test_activating_or_live_pid_does_not_claim_disabled(self):
        for state,pid in (('activating','0'),('inactive','123'),('active','123'),('unknown','0')):
            self.service=state;self.pid=pid
            self.assertEqual(self.apply(False)['phase'],'failed')

    def test_queue_receipt_precedes_mutation_and_rejects_overlap(self):
        with patch.object(self.b.threading,'Timer') as timer:
            first=self.b.queue_network(self.b.common.DEFAULT,{'config.json':'not written'})
            self.assertTrue(first['pending']);self.assertEqual(self.b.lan_status()['phase'],'applying')
            self.assertNotEqual(self.config.read_text(),'not written');self.assertFalse(self.commands)
            with self.assertRaisesRegex(ValueError,'already running'):
                self.b.queue_network(self.b.common.DEFAULT,{})
            timer.return_value.start.assert_called_once()
        self.b.NETWORK_LOCK.release()


if __name__=='__main__':unittest.main()
