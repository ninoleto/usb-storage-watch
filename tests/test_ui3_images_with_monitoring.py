# SPDX-License-Identifier: MIT
"""Isolated regressions: image setup must work with a running or stopped monitor.

No disk, real service, USB port, image formatting, or existing mount is touched.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from gui_fixture import load

images = load('web_images')

class ImageMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.monitoring = False
        self.commands = []
        self.events = []
        self.service = 'usb-storage-watch-synthetic.service'

        @contextmanager
        def exclusive(_b, own_monitor=True):
            self.events.append(('preparation-lock',own_monitor))
            self.assertFalse(own_monitor, 'running monitor must not be excluded at preview')
            yield 17

        @contextmanager
        def drive_exclusive(_b):
            self.assertFalse(self.monitoring, 'service must be stopped before mutating its configuration')
            self.events.append(('monitor-lock',True))
            yield

        def command(argv, timeout=10):
            self.assertEqual(argv[0], '/usr/bin/systemctl')
            self.assertEqual(argv[2], self.service)
            self.commands.append(tuple(argv))
            self.monitoring = (argv[1] == 'start')
            return ''

        self.b = SimpleNamespace(
            s=SimpleNamespace(STATE_DIR=self.state),
            w=SimpleNamespace(verify_main=Mock(return_value='240:1')),
            preparation=SimpleNamespace(exclusive=exclusive,revision=Mock(return_value='rev')),
            migration=SimpleNamespace(drive_exclusive=drive_exclusive),
            cli=SimpleNamespace(SERVICE=self.service),
            command=command,
            service_state=lambda: {'ActiveState':'active' if self.monitoring else 'inactive'}
        )

    def test_plan_can_review_new_image_while_monitoring_is_on(self):
        self.monitoring = True
        proposal={'mode':'create','item':{'name':'backups'},'old':None,'observed':None,'size':1024,'config':{}}
        with patch.object(images,'proposal',return_value=proposal):
            result=images.plan(self.b,{'mode':'create','name':'backups','size_gb':1})
        self.assertTrue(self.monitoring, 'preview must leave monitor running')
        self.assertEqual(result['mode'],'create')
        self.assertEqual(result['revision'],'rev')
        self.assertEqual(self.commands,[])

    def test_apply_running_monitor_resumes_without_touching_other_drives(self):
        self.monitoring = True
        other_active = True
        with images._image_transaction(self.b) as fd:
            self.assertEqual(fd,17)
            self.assertFalse(self.monitoring)
            self.assertTrue(other_active)
        self.assertTrue(self.monitoring)
        self.assertEqual(self.commands,[('/usr/bin/systemctl','stop',self.service),('/usr/bin/systemctl','start',self.service)])
        self.b.w.verify_main.assert_called_once()

    def test_apply_monitoring_off_preserves_off_state(self):
        self.monitoring = False
        with images._image_transaction(self.b):
            self.assertFalse(self.monitoring)
        self.assertFalse(self.monitoring)
        self.assertEqual(self.commands,[])

    def test_create_failure_resumes_original_running_monitor(self):
        self.monitoring = True
        with self.assertRaisesRegex(RuntimeError,'simulated image creation failed'):
            with images._image_transaction(self.b):
                raise RuntimeError('simulated image creation failed')
        self.assertTrue(self.monitoring)
        self.assertEqual([v[1] for v in self.commands],['stop','start'])

    def test_pending_incident_refuses_before_stopping_active_monitor(self):
        self.monitoring = True
        (self.state/'state.json').write_text(json.dumps({'incident':{'phase':'wait1'}}))
        with self.assertRaisesRegex(ValueError,'Recovery is in progress'):
            with images._image_transaction(self.b):pass
        self.assertTrue(self.monitoring)
        self.assertEqual(self.commands,[])

    def test_unresolved_usb_disable_refuses_before_mutation(self):
        self.monitoring = True
        (self.state/'usb-reset.json').write_text(json.dumps({'phase':'disabling'}))
        with self.assertRaisesRegex(ValueError,'USB reconnection cleanup'):
            images.plan(self.b,{'mode':'create'})
        self.assertTrue(self.monitoring)
        self.assertEqual(self.commands,[])

    def test_changing_service_state_is_refused(self):
        self.b.service_state=lambda:{'ActiveState':'deactivating'}
        with self.assertRaisesRegex(ValueError,'changing state'):
            with images._image_transaction(self.b):pass
        self.assertEqual(self.commands,[])

    def test_restart_failure_is_reported_explicitly(self):
        self.monitoring=True
        def broken(argv,timeout=10):
            self.commands.append(tuple(argv))
            if argv[1]=='start':raise ValueError('synthetic service error')
            self.monitoring=False
        self.b.command=broken
        with self.assertRaisesRegex(ValueError,'monitoring could not resume automatically'):
            with images._image_transaction(self.b):pass
        self.assertEqual([v[1] for v in self.commands],['stop','start'])

    def test_apply_existing_image_uses_new_transaction_with_monitor_on_and_off(self):
        # Test the real apply() routing/consent path. Mock only disk I/O and
        # filesystem metadata; do not replace _image_transaction itself.
        observed={'uuid':'33333333-3333-4333-8333-333333333333','inode':1,'device':1,'size':2048}
        item={'uuid':observed['uuid'],'image':str(self.root/'existing.img'),
              'mountpoint':str(self.root/'mount'), 'name':'existing'}
        config={'images':[item]}
        self.b.configuration=lambda:config
        self.b.w.configure=Mock()
        self.b.w.disk_proof=Mock()
        self.b.w.recover_image=Mock()
        self.b.w.read_rows=lambda:[]
        self.b.s.storage_images=lambda _c,enabled=False:[item]
        self.b.owner=(1000,1000)
        chosen=dict(mode='existing',item=item,observed=observed,size=2048,old=None,
                    revision='rev',token='test-consent',created=time.monotonic(),data={'mode':'existing'},config=config)
        # The tested mocked path allows no real device or mount changes.
        with patch.object(images,'proposal',return_value=dict(item=item,old=None,observed=observed,size=2048)), \
             patch.object(images,'probe',return_value=observed), \
             patch.object(images,'rooted',side_effect=lambda *_a,**_k: __import__('os').open(self.root,__import__('os').O_RDONLY)), \
             patch.object(images,'save_configuration') as save, \
             patch.object(images,'entries',return_value=[]):
            for active in (False,True):
                self.monitoring=active
                self.commands.clear()
                result=images.apply(self.b,chosen,{'token':'test-consent','confirm':True})
                self.assertIn('saved, mounted and verified',result['message'])
                self.assertEqual(self.monitoring,active)
                self.assertEqual([cmd[1] for cmd in self.commands],['stop','start'] if active else [])
            self.assertEqual(save.call_count,2)

if __name__=='__main__':unittest.main()
