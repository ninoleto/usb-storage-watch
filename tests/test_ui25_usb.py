# SPDX-License-Identifier: MIT
"""Manual USB safety and companion-return simulations; no hardware operations."""
import copy
import json
from contextlib import nullcontext
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gui_fixture import load, Machine
import test_usb_recovery as base


class CompanionReturn(base.Temp):
    def setUp(self):
        super().setUp()
        self.original=copy.deepcopy(base.u.PROFILE)
        port=self.directory/'old-port';port.mkdir();(port/'disable').write_text('0')
        self.original['port']=str(port)
        self.candidate=copy.deepcopy(self.original)
        self.candidate.update(canonical='/verified/peer',device_real='/returned/device')
        self.record=dict(profile=self.original,return_ports=[self.original['canonical'],'/verified/peer'])
        self.ctx.device_number=Mock(return_value='240:33')
        self.addCleanup(base.u.configure,base.u.PROFILE)
        self.stack=self.enterContext(patch.object(base.u,'physical_usb_device',return_value=Path('/returned/device')))
        self.enterContext(patch.object(base.u,'discover',side_effect=lambda *_:self.candidate))
        self.proof=self.enterContext(patch.object(base.u,'healthy_binding'))
        self.bind=self.enterContext(patch.object(base.u,'bind_current'))

    def test_return_on_captured_companion_is_verified_and_rebound(self):
        base.u.returned_binding(self.ctx,self.record)
        self.proof.assert_called_once();self.bind.assert_called_once()

    def test_unrelated_port_or_serial_never_rebound(self):
        for field,value in [('canonical','/unrelated/port'),('disk_serial','other-disk'),('controller_real','/other/controller'),('vid','abcd')]:
            previous=self.candidate[field];self.candidate[field]=value
            with self.assertRaisesRegex(base.w.Unsafe,'outside the verified'):base.u.returned_binding(self.ctx,self.record)
            self.candidate[field]=previous
        self.bind.assert_not_called();self.proof.assert_not_called()

    def test_original_port_must_be_reenabled_before_accepting_peer(self):
        (Path(self.original['port'])/'disable').write_text('1')
        with self.assertRaises(base.w.Unsafe):base.u.returned_binding(self.ctx,self.record)
        self.bind.assert_not_called()

    def test_failed_return_proof_restores_original_binding(self):
        prior=base.u.PROFILE
        self.proof.side_effect=base.w.Unsafe('Changed UUID')
        with self.assertRaises(base.w.Unsafe):base.u.returned_binding(self.ctx,self.record)
        self.assertEqual(base.u.PROFILE,prior);self.bind.assert_not_called()

    def test_missing_old_device_waits_for_companion_uuid_without_certifying_return(self):
        with patch.object(base.u,'DEVICE',self.directory/'missing-old-device'), \
             patch.object(base.u,'port_identity',side_effect=base.w.Unsafe('Companion occupied')) as port:
            self.assertFalse(base.u.ready(self.ctx))
        port.assert_not_called()


class ManualReset(unittest.TestCase):
    def setUp(self):
        self.m=load('manual_usb')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.w=SimpleNamespace(Unsafe=ValueError,DISK_UUID='synthetic',STATE_DIR=Path(self.tmp.name),MOUNT='/mnt/test',
            usb=SimpleNamespace(load=Mock(return_value=None),require_process_isolation=Mock()),
            usb_context=lambda:None,read_rows=lambda:[],covers=lambda root,path:path==root or path.startswith(root+'/'))
        self.value=dict(uuid='synthetic',serial='disk-serial',device='/sys/fake/usb2/2-3.1',
                        bus=2,address=5,node='/dev/bus/usb/002/005',usb_ids='aaaa:bbbb',known_devs=['240:1'],known_sources=['/dev/synthetic'])

    def test_mounted_storage_refused_before_process_scan(self):
        self.w.read_rows=lambda:[dict(dev='240:1',target='/elsewhere')]
        with self.assertRaisesRegex(ValueError,'Unmount'):self.m.unmounted(self.w,self.value)
        self.w.usb.require_process_isolation.assert_not_called()

    def test_namespace_or_descriptor_refusal_is_not_bypassed(self):
        self.w.usb.require_process_isolation.side_effect=ValueError('unverified descriptor')
        with patch.object(self.m.Path,'glob',return_value=[]),self.assertRaisesRegex(ValueError,'unverified descriptor'):
            self.m.unmounted(self.w,self.value)

    def device_setup(self):
        self.w.usb.select_current=Mock(side_effect=ValueError('unsupported port method'))
        self.w.controls=SimpleNamespace(request=lambda _: {})
        self.w.drives=SimpleNamespace(port_lock=lambda *_:nullcontext())
        self.w.atomic_write=Mock();self.w.boot_id=lambda:'boot';self.w.timestamp=lambda:'now'
        self.w.SETTINGS={'usb':{'enumeration_seconds':1}}

    def test_device_address_change_aborts_before_open_or_ioctl(self):
        self.device_setup()
        with patch.object(self.m,'capabilities',side_effect=[self.value,self.value|{'address':6}]), \
             patch.object(self.m,'unmounted',side_effect=lambda w,v=None:v),patch.object(self.m.os,'open') as opened:
            with self.assertRaisesRegex(ValueError,'address changed'):self.m.reset(self.w)
        opened.assert_not_called()

    def test_uncertain_device_reset_cannot_be_replayed(self):
        self.device_setup()
        (self.w.STATE_DIR/'manual-usb.json').write_text(json.dumps(dict(boot='boot',phase='intent')))
        with patch.object(self.m,'capabilities',return_value=self.value), \
             patch.object(self.m,'unmounted',return_value=self.value),patch.object(self.m.os,'open') as opened:
            with self.assertRaisesRegex(ValueError,'uncertain outcome'):self.m.reset(self.w)
        opened.assert_not_called();self.w.usb.select_current.assert_not_called()

    def test_leaf_device_behind_hub_reset_never_targets_parent_or_mounts(self):
        self.device_setup()
        info=SimpleNamespace(st_mode=stat.S_IFCHR,st_rdev=os.makedev(189,132))
        with patch.object(self.m,'capabilities',return_value=self.value), \
             patch.object(self.m,'identity',return_value=self.value), \
             patch.object(self.m,'unmounted',side_effect=lambda w,v=None:v), \
             patch.object(self.m.os,'open',return_value=71) as opened, \
             patch.object(self.m.os,'fstat',return_value=info),patch.object(self.m.os,'close'), \
             patch.object(self.m.fcntl,'ioctl') as reset:
            result=self.m.reset(self.w)
        self.assertEqual(opened.call_args.args[0],self.value['node'])
        reset.assert_called_once_with(71,0x5514,0)
        self.assertIn('left unmounted',result);self.assertIn('not verified',result)

    def test_server_refusal_does_not_stop_monitoring(self):
        machine=Machine();self.addCleanup(machine.close)
        b=machine.b;c=b.s.default();c['disk']['uuid']=machine.uuid
        with patch.object(b,'configuration',return_value=c),patch.object(b.w,'configure'), \
             patch.object(b.w.manual_usb,'capabilities',return_value={}), \
             patch.object(b.w.manual_usb,'unmounted',side_effect=b.w.Unsafe('Unmount first')), \
             patch.object(b,'command') as commands,patch.object(b.w,'Worker') as worker:
            result=b.disk_operation(dict(action='reconnect',uuid=machine.uuid))
        self.assertFalse(result['ok']);worker.assert_not_called()
        self.assertTrue(all(call.args[0][1]=='show' for call in commands.call_args_list))


class ExitedNamespace(unittest.TestCase):
    def test_einval_requires_kernel_exit_proof(self):
        u=load('usb')
        proc=Path('/proc/12345')
        root=Mock();root.iterdir.return_value=[proc]
        root.__truediv__=Mock(return_value=SimpleNamespace(read_text=lambda:'Filename Type Size Used Priority\n'))
        w=SimpleNamespace(Unsafe=ValueError,parse_mounts=Mock(),process_exited=Mock(return_value=False))
        with patch.object(u,'PROC',root),patch.object(Path,'read_text',side_effect=OSError(22,'Invalid argument')):
            with self.assertRaises(OSError):u.require_process_isolation(w,dict(known_devs=['240:1']))
            w.process_exited.return_value=True
            u.require_process_isolation(w,dict(known_devs=['240:1']))
        self.assertEqual(w.process_exited.call_count,2)


if __name__=='__main__':unittest.main()
