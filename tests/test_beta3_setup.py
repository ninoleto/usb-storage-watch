"""Complete authenticated setup with disposable ext4 files and simulated OS metadata.

No real mount, Docker, service or email operation occurs in this suite.
The opt-in beta3_mount_setup.py runner additionally exercises actual loop mounts.
"""
import copy
import errno
import fcntl
import json
import os
from pathlib import Path
import subprocess
from types import FunctionType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from gui_fixture import Machine, UUID, load
import test_beta2_adoption as adoption
IMAGE_UUID=adoption.IMAGE_UUID

SMTP=dict(host='smtp.example.test',port=587,security='starttls',username='sender',
          password='DUMMY-TEST-SECRET',sender='sender@example.test',recipient='recipient@example.test')

class SetupFixture:
    def setUp(self):
        adoption.Adoption.setUp(self)
        self.m.current=str(self.disk);self.m.dev=self.dev
        raw=load('engine')
        # Restore real fstab and image verification functions, replacing only
        # kernel metadata/block I/O observations and service control boundaries.
        self.m.patch(self.w,'fstab_check',FunctionType(raw.fstab_check.__code__,vars(self.w)))
        device=self.root/'dev/block/7:77';device.parent.mkdir(parents=True);device.touch()
        self.loops[0]['name']=str(device)
        self.m.patch(self.w,'Path',lambda p: self.m.fstab if str(p)=='/etc/fstab' else
                     self.root/str(p).lstrip('/') if str(p).startswith(('/sys/','/dev/')) else Path(p))
        self.m.patch(self.w,'device_number',lambda p:'7:77' if str(p)==str(device) else self.dev)
        def proof(p,u,unmounted=False,regular=False):
            if regular:return raw.disk_proof(p,u,regular=True)
            dev='7:77' if str(p)==str(device) else self.dev
            if self.actual_uuid.get(dev)!=u:raise self.w.Unsafe('Fixture UUID mismatch')
            return SimpleNamespace(st_rdev=os.makedev(*map(int,dev.split(':'))))
        self.m.patch(self.w,'disk_proof',proof)
        self.m.patch(self.w,'safe_path',lambda p,dev,directory=True: raw.safe_path(p,self.file.stat().st_dev,directory=directory))
        def command(args,timeout=10):
            assert args[0]=='/usr/sbin/losetup',args
            return json.dumps(dict(loopdevices=self.loops))
        self.m.patch(self.w,'command',command)
        self.m.patch(self.b.n,'bounded_send',Mock(return_value=(True,'Accepted by simulated SMTP transport.')))
        self.ctx=self.b.protection_context()

    def request(self,action,data=None,csrf=True):
        return self.m.broker.handle(dict(action=action,data=data or {},write=data is not None,
            drive=None if action in ('add-drive','smtp','test-email') else 'legacy',
            token=self.session['token'],csrf=self.session['csrf'] if csrf else 'invalid'))

    def adopt(self):
        review=self.request('image-plan',self.data);self.assertEqual(review['status'],200,review)
        result=self.request('image-apply',dict(token=review['data']['token'],confirm=True))
        self.assertEqual(result['status'],200,result)

    def recovery_review(self):
        return self.m.broker.handle(dict(
            action='recovery-plan',data=dict(enabled='true'),write=False,drive='legacy',token=self.session['token']))

    def recovery_save(self,review):
        return self.request('recovery-settings',dict(uuid=UUID,enabled=True,token=review['data']['token'],consent=True))

    def notification(self,enabled=True):
        return self.request('notification-settings',dict(revision=self.b.s.digest(self.b.configuration()),enabled=enabled))

    def run_sequence(self):
        before=adoption.Adoption.snapshot(self)
        # A fresh install: register via the GUI's authenticated fleet route.
        self.b.s.CONFIG.unlink()
        registered=self.request('add-drive',dict(uuid=UUID));self.assertEqual(registered['status'],200,registered)
        self.assertEqual(registered['data']['profile_id'],'legacy');self.assertFalse(self.m.active)
        self.assertFalse(self.b.configuration()['recovery']['mount'])
        self.adopt();self.assertFalse(self.m.active)
        self.assertEqual(self.request('monitor',dict(enabled=True))['status'],200)
        self.assertTrue(self.m.active)
        review=self.recovery_review();self.assertEqual(review['status'],200,review)
        self.assertEqual(self.recovery_save(review)['status'],200)
        self.assertTrue(self.b.configuration()['recovery']['mount']);self.assertTrue(self.m.active)
        refused=self.notification();self.assertEqual(refused['status'],400,refused)
        self.assertIn('Email & Notifications',refused['error']);self.assertTrue(self.m.active)
        self.assertEqual(self.request('smtp',SMTP)['status'],200)
        sent=self.request('test-email',{});self.assertEqual(sent['status'],200,sent);self.assertTrue(sent['data']['accepted'])
        enabled=self.notification();self.assertEqual(enabled['status'],200,enabled)
        self.assertTrue(self.b.configuration()['notifications']['enabled']);self.assertTrue(self.m.active)
        self.assertEqual(adoption.Adoption.snapshot(self),before)
        self.assertEqual({c[2] for c in self.m.calls if c[0]=='/usr/bin/systemctl' and c[1] in ('start','stop','enable')},
                         {self.b.cli.SERVICE} | {'--now'})


class RecoveryPlanning(SetupFixture,unittest.TestCase):
    def test_complete_fresh_setup_sequence(self):self.run_sequence()

    def test_registered_mounted_image_plans_but_actual_remount_guard_stays_strict(self):
        # The unchanged Beta 2 engine accepts the physical mount alone.
        self.w.recovery_backing(self.rows[:2],str(self.disk),self.dev,mounted=True)
        with self.assertRaises(self.w.Unsafe):self.w.recovery_backing(self.rows,str(self.disk),self.dev,mounted=True)
        self.adopt();result=self.recovery_review();self.assertEqual(result['status'],200,result)
        with self.assertRaises(self.w.Unsafe):self.w.recovery_backing(self.rows,str(self.disk),self.dev,mounted=True)

    def test_unknown_stacked_shared_nested_and_wrong_identity_refused(self):
        self.assertEqual(self.recovery_review()['status'],400)  # Not registered yet.
        self.adopt();before=self.b.s.CONFIG.read_bytes();rows=copy.deepcopy(self.rows)
        variants=[rows+[dict(rows[-1],id='4')],rows+[dict(rows[-1],id='4',target=str(self.disk/'unknown'))],
                  rows+[dict(rows[-1],id='4',target='/mnt/shared-alias')],
                  rows+[dict(rows[-1],id='4',parent='3',target=str(self.target/'foreign'),dev='8:99')]]
        for bad in variants:
            self.rows=bad
            with self.subTest(rows=bad):self.assertEqual(self.recovery_review()['status'],400)
        self.rows=rows
        for key,value in [('back-file',str(self.disk/'other.img')),('back-ino',1),('back-maj:min','8:99')]:
            old=self.loops[0][key];self.loops[0][key]=value
            with self.subTest(key=key):self.assertEqual(self.recovery_review()['status'],400)
            self.loops[0][key]=old
        for dev in (self.dev,'7:77'):
            old=self.actual_uuid[dev];self.actual_uuid[dev]='wrong'
            with self.subTest(uuid=dev):self.assertEqual(self.recovery_review()['status'],400)
            self.actual_uuid[dev]=old
        for key in ('offset','sizelimit'):
            p=self.root/'sys/dev/block/7:77/loop'/key;p.write_text('512')
            self.assertEqual(self.recovery_review()['status'],400);p.write_text('0')
        self.assertEqual(self.b.s.CONFIG.read_bytes(),before);self.assertFalse(self.m.active)

    def test_fstab_and_topology_change_after_review_refuse_before_monitor_stop(self):
        self.adopt();self.m.active=True;review=self.recovery_review();self.assertEqual(review['status'],200,review)
        self.rows[-1]['id']='30';calls=len(self.m.calls)
        result=self.recovery_save(review);self.assertEqual(result['status'],400,result)
        self.assertTrue(self.m.active);self.assertFalse(self.b.configuration()['recovery']['mount'])
        self.assertFalse(any(c[1]=='stop' for c in self.m.calls[calls:] if c[0]=='/usr/bin/systemctl'))
        self.m.fstab.write_text(self.m.fstab.read_text()+self.entry)
        self.assertEqual(self.recovery_review()['status'],400)

    def test_disabled_registered_image_retained_and_missing_main_not_ignored(self):
        self.adopt();c=self.b.configuration();c['images'][0]['enabled']=False;self.b.cli.save(self.b.s.CONFIG,c)
        self.assertEqual(self.recovery_review()['status'],200)
        self.rows=self.rows[:1]+self.rows[2:];self.m.current=''
        self.assertEqual(self.recovery_review()['status'],400)

    def test_surviving_worker_refuses_activation_without_saving(self):
        self.adopt();review=self.recovery_review();self.assertEqual(review['status'],200,review)
        before=self.b.s.CONFIG.read_bytes()
        with (self.b.s.STATE_DIR/'monitor.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual(self.recovery_save(review)['status'],400)
        self.assertEqual(self.b.s.CONFIG.read_bytes(),before)


class Notifications(SetupFixture,unittest.TestCase):
    def test_missing_and_unreadable_are_actionable_sanitized_without_state_changes(self):
        self.m.active=True;before=self.b.s.CONFIG.read_bytes()
        # Real missing file through the fixture's configuration reader.
        result=self.notification();self.assertEqual(result['status'],400,result)
        self.assertIn('Email is not configured',result['error'])
        for error in (PermissionError('DUMMY-TEST-SECRET private path'),OSError(errno.EIO,'DUMMY-TEST-SECRET'),
                      ValueError('DUMMY-TEST-SECRET'),AttributeError('DUMMY-TEST-SECRET')):
            with self.subTest(error=type(error).__name__),patch.object(self.b.n,'load_config',side_effect=error):
                result=self.notification();self.assertEqual(result['status'],400,result)
                self.assertIn('Email & Notifications',result['error']);self.assertNotIn('DUMMY-TEST-SECRET',json.dumps(result))
        self.assertEqual(self.b.s.CONFIG.read_bytes(),before);self.assertTrue(self.m.active)
        self.assertFalse(any(c[1] in ('stop','start') for c in self.m.calls if c[0]=='/usr/bin/systemctl'))

    def test_valid_email_enables_and_disabling_needs_no_smtp(self):
        self.m.active=True;self.assertEqual(self.request('smtp',SMTP)['status'],200)
        self.assertEqual(self.notification()['status'],200);self.assertTrue(self.m.active)
        with patch.object(self.b.n,'load_config',side_effect=AssertionError('Disable must not read SMTP')):
            self.assertEqual(self.notification(False)['status'],200)
        self.assertTrue(self.m.active);self.assertFalse(self.b.configuration()['notifications']['enabled'])

    def test_service_failure_is_not_misreported_as_smtp_setup(self):
        self.assertEqual(self.request('smtp',SMTP)['status'],200);before=self.b.s.CONFIG.read_bytes()
        original=self.b.command
        def fail(args,timeout=10):
            if args[:2]==['/usr/bin/systemctl','stop']:raise OSError('DUMMY-TEST-SECRET service failure')
            return original(args,timeout)
        with patch.object(self.b,'command',fail):result=self.notification()
        self.assertEqual(result['status'],503,result);self.assertNotIn('Email is not configured',result['error'])
        self.assertNotIn('DUMMY-TEST-SECRET',json.dumps(result));self.assertEqual(self.b.s.CONFIG.read_bytes(),before)

if __name__=='__main__':unittest.main()
