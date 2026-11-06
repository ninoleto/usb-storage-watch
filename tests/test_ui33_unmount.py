# SPDX-License-Identifier: MIT
"""Authenticated frontend/broker plus real worker IPC/flocks; no host mutations."""
import copy
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from gui_fixture import load
import test_ui32_unmount as prior

ID, OTHER = prior.ID, prior.OTHER

PHOTO = 'c'*64

class RepeatedUnmount(unittest.TestCase):
    def setUp(self):
        prior.Unmount.setUp(self)
        self.m = self.f.main
        original = self.b.common.module
        self.m.patch(self.b.common, 'module', lambda name, *args:
                     self.boot if name == 'boot_start' else original(name, *args))
        def engine(b, drive, config):
            def mounted(target):
                if not any(row['target'] == target and row['fs'] == 'ext4' for row in self.rows):
                    raise self.b.w.Unsafe('Expected mount is missing.')
            return SimpleNamespace(STATE_DIR=self.b.s.STATE_DIR, SETTINGS=config, settings=self.b.s,
                Unsafe=self.b.w.Unsafe, verify_main=lambda:mounted(config['disk']['mountpoint']),
                verify_dependent=lambda image:mounted(image['mountpoint']))
        self.m.patch(self.boot, 'engine', engine)
        self.started_workers = []
        real = load('engine')
        def worker(argv, payload, timeout, **kwargs):
            self.assertEqual(argv[-1], '_manual')
            (self.m.root/'rows.json').write_text(json.dumps(self.rows))
            (self.m.root/'runtime.json').write_text(json.dumps(self.runtime))
            result = real.Worker([sys.executable, '-I', str(Path(__file__).with_name('unmount_worker_fixture.py')), str(self.m.root)], payload, 15, **kwargs)
            self.started_workers.append(result.proc.pid)
            return result
        self.m.patch(self.b.w, 'Worker', worker)
        self.m.patch(self.b.w, 'worker_json', real.worker_json)
        self.headers = {'Origin':'http://127.0.0.1:8765', 'X-USW-Request':'1', 'X-CSRF-Token':self.f.session['csrf']}
        self.http = self.m.web.create_app(dict(self.b.common.DEFAULT,port=8765), self.m.broker.handle).test_client()
        self.http.set_cookie('usw_session', self.f.session['token'], domain='127.0.0.1')

    inspect = prior.Unmount.inspect
    post = prior.Unmount.post
    users = prior.Unmount.users
    command = prior.Unmount.command
    receipt = prior.Unmount.receipt

    def review(self):
        result = self.http.get('/api/drives/legacy/unmount-plan?uuid='+self.m.uuid, base_url='http://127.0.0.1:8765', headers=self.headers)
        self.assertEqual(result.status_code, 200, result.json)
        return dict(uuid=self.m.uuid,action='unmount',token=result.json['token'],confirm=True)

    def apply(self, data):
        result=self.http.post('/api/drives/legacy/disk-operation',base_url='http://127.0.0.1:8765',headers=self.headers,json=data)
        error=self.m.root/'worker-error'
        if error.exists():self.fail(error.read_text())
        return result

    def earlier_unmount_then_remount_and_add_app(self):
        rows=copy.deepcopy(self.rows)
        first=self.apply(self.review());self.assertEqual(first.status_code,200,first.json);self.assertTrue(first.json['ok'],first.json)
        self.assertEqual(self.receipt()['phase'],'complete')
        self.assertTrue(self.b.w.manual_intent.stopped(self.b.w,ID))
        self.rows=json.loads((self.m.root/'rows.json').read_text())
        before = (self.b.s.STATE_DIR/'manual-unmount.json').read_bytes()
        for action in ('start', 'restart'):
            refused=self.f.request('docker-container-action',dict(id=ID,name='test-app',action=action,confirm=True),profile=None)
            self.assertEqual(refused['status'],400,refused)
            self.assertIn('Expected mount is missing',refused['error'])
            self.assertEqual((self.b.s.STATE_DIR/'manual-unmount.json').read_bytes(),before)
            self.assertFalse(self.runtime[ID]['running'])
        # External observation of the user's later remount, then a real broker
        # manual Start. Mount alone must not release deliberate-stop intent.
        self.rows=rows;self.m.active=True
        self.assertTrue(self.b.w.manual_intent.stopped(self.b.w,ID))
        result=self.f.request('docker-container-action',dict(id=ID,name='test-app',action='start',confirm=True),profile=None)
        self.assertTrue(result['data']['ok'],result);self.assertEqual(self.receipt()['held_ids'],[])
        self.runtime[PHOTO]=dict(self.runtime[OTHER],id=PHOTO,name='folder-app',running=False)
        c=self.b.configuration();c['docker']['containers'].append(dict(name='folder-app',container_id=PHOTO,source='',destination='',grace=10,images=[]));self.b.cli.save(self.b.s.CONFIG,c)
        boot=self.boot.read(self.b);boot['containers'].append(dict(id=PHOTO,name='folder-app',enabled=True,drives=[dict(id='legacy',images=[])]));self.b.cli.save(self.boot.paths(self.b)[0],boot)
        result=self.f.request('docker-container-action',dict(id=PHOTO,name='folder-app',action='start',confirm=True),profile=None)
        self.assertTrue(result['data']['ok'],result)
        self.events.clear();(self.m.root/'worker-events').write_text('')

    def test_earlier_unmount_remount_manual_start_then_added_folder_app_real_worker(self):
        self.earlier_unmount_then_remount_and_add_app()
        saved=self.b.s.CONFIG.read_bytes();boot=self.boot.paths(self.b)[0].read_bytes()
        data=self.review();response=self.apply(data)
        self.assertEqual(response.status_code,200,response.json);self.assertTrue(response.json['ok'],response.json)
        self.assertEqual(len(set(self.started_workers)),2)
        self.assertEqual(self.events,['stop:'+ID,'stop:'+PHOTO])
        self.assertEqual((self.m.root/'worker-events').read_text().splitlines(),['users','verify:image','unmount:image','sync','unmount:disk'])
        self.assertEqual(json.loads((self.m.root/'rows.json').read_text()),[])
        self.assertEqual(set(self.receipt()['held_ids']),{ID,PHOTO});self.assertEqual(self.receipt()['phase'],'complete')
        self.assertTrue(self.runtime[OTHER]['running']);self.assertEqual(self.b.s.CONFIG.read_bytes(),saved);self.assertEqual(self.boot.paths(self.b)[0].read_bytes(),boot)
        self.assertEqual(self.apply(data).status_code,400)  # One use; no second worker.
        self.assertEqual(len(self.started_workers),2)

    def test_live_worker_blocks_controls_and_duplicate_confirm_without_self_block(self):
        self.earlier_unmount_then_remount_and_add_app()
        data=self.review();(self.m.root/'worker-ready').unlink();(self.m.root/'pause-worker').touch()
        responses=[];thread=threading.Thread(target=lambda:responses.append(self.apply(data)));thread.start()
        try:
            deadline=time.monotonic()+5
            while not (self.m.root/'worker-ready').exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue((self.m.root/'worker-ready').exists(),responses[0].json if responses else 'No worker')
            guard=self.b.common.module('app_control');items=[(i,c) for i,c,e in self.m.broker.fleet.records() if not e]
            self.assertEqual(set(guard.restrictions(self.b,items)),{ID,PHOTO})
            duplicate=self.apply(data);self.assertEqual(duplicate.status_code,409,duplicate.json)
            self.assertIn('Wait for it to finish',duplicate.json['error'])
            locked=self.f.request('docker-container-action',dict(id=PHOTO,name='folder-app',action='start',confirm=True),profile=None)
            self.assertEqual(locked['status'],400)
            unrelated=self.f.request('docker-container-action',dict(id=OTHER,name='unrelated',action='start',confirm=True),profile=None)
            self.assertTrue(unrelated['data']['ok'])
        finally:
            (self.m.root/'pause-worker').unlink();thread.join(8)
        self.assertFalse(thread.is_alive());self.assertTrue(responses[0].json['ok'],responses[0].json)
        self.assertEqual(guard.restrictions(self.b,items),{})
        self.assertTrue(self.b.w.manual_intent.stopped(self.b.w,PHOTO))

    def test_orphan_active_and_failed_receipts_allow_new_review_without_losing_holds(self):
        for phase in ('active','failed','complete'):
            with self.subTest(phase=phase):
                self.b.cli.save(self.b.s.STATE_DIR/'manual-unmount.json',dict(boot=self.b.w.boot_id(),phase=phase,control_ids=[ID],held_ids=[OTHER]))
                result=self.apply(self.review())
                self.assertEqual(result.status_code,200,result.json);self.assertTrue(result.json['ok'],result.json)
                self.assertIn(OTHER,self.receipt()['held_ids'])

    def test_other_drive_manual_operation_and_recovery_remain_restricted(self):
        guard=self.b.common.module('app_control')
        items=[(i,c) for i,c,e in self.m.broker.fleet.records() if not e]
        other=self.f.second.b
        other.cli.save(other.s.STATE_DIR/'manual-unmount.json',dict(boot=self.b.w.boot_id(),phase='active',control_ids=[ID],held_ids=[ID]))
        with self.b.cli.drives.lock(self.b.s.STATE_DIR,'manual-unmount.lock') as own, self.b.cli.drives.lock(other.s.STATE_DIR,'manual-unmount.lock'):
            with self.assertRaisesRegex(ValueError,'Safe unmount in progress'):
                guard.require_idle(self.b,items,ID,unmount_owner=('legacy',own))
        self.b.cli.save(self.b.s.STATE_DIR/'state.json',dict(incident=dict(phase='wait1',control_ids=[ID])))
        with self.b.cli.drives.lock(self.b.s.STATE_DIR,'manual-unmount.lock') as own:
            with self.assertRaisesRegex(ValueError,'Recovery in progress'):
                guard.require_idle(self.b,items,ID,unmount_owner=('legacy',own))

    def test_worker_busy_storage_refusal_keeps_holds_without_unmount(self):
        self.earlier_unmount_then_remount_and_add_app()
        (self.m.root/'busy-storage').touch()
        response=self.apply(self.review())
        self.assertEqual(response.status_code,200,response.json);self.assertFalse(response.json['ok'])
        self.assertIn('unrelated process',response.json['message'])
        self.assertEqual((self.m.root/'worker-events').read_text().splitlines(),['users'])
        self.assertEqual(json.loads((self.m.root/'rows.json').read_text()),self.rows)
        self.assertEqual(self.receipt()['phase'],'failed');self.assertEqual(set(self.receipt()['held_ids']),{ID,PHOTO})
        self.assertTrue(self.runtime[OTHER]['running'])

    def test_completed_receipt_with_live_inherited_lock_still_blocks_other_callers(self):
        self.b.cli.save(self.b.s.STATE_DIR/'manual-unmount.json',dict(boot=self.b.w.boot_id(),phase='complete',control_ids=[ID],held_ids=[ID]))
        guard=self.b.common.module('app_control');items=[('legacy',self.b.configuration())]
        with self.b.cli.drives.lock(self.b.s.STATE_DIR,'manual-unmount.lock') as owned, self.b.cli.drives.lock(self.b.s.STATE_DIR,'different.lock') as unrelated:
            self.assertEqual(guard.restrictions(self.b,items)[ID],self.b.w.manual_intent.MESSAGE)
            with self.assertRaisesRegex(ValueError,'Safe unmount in progress'):
                guard.require_idle(self.b,items,ID,unmount_owner=('legacy',unrelated))
            guard.require_idle(self.b,items,ID,unmount_owner=('legacy',owned))
        self.assertEqual(guard.restrictions(self.b,items),{})
        self.assertTrue(self.b.w.manual_intent.stopped(self.b.w,ID))

if __name__=='__main__':unittest.main()
