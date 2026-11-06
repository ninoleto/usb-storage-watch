# SPDX-License-Identifier: MIT
"""Focused DEV4 listener, formatting, access and configuration regressions."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
from gui_fixture import load,Machine,UUID,DESKTOP


class CoreFixes(unittest.TestCase):
    def test_lan_failure_restores_settings_and_never_restarts_local_service(self):
        b=load('web_broker')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config.json';before=json.dumps(b.common.DEFAULT)+'\n';config.write_text(before)
            for name in ('certificate.pem','key.pem','local-network-ca.pem'):(root/name).write_text('existing '+name)
            snapshot={p.name:p.read_bytes() for p in root.iterdir()};commands=[]
            def command(args,timeout=10):
                commands.append(args)
                if args[1]=='restart':raise ValueError('LAN service could not start')
                return ''
            with patch.object(b.common,'WEB_DIR',root),patch.object(b.common,'WEB_CONFIG',config),patch.object(b.s,'STATE_DIR',root),patch.object(b.pwd,'getpwnam',return_value=Mock(pw_gid=os.getgid())),patch.object(b.os,'chown'),patch.object(b,'command',side_effect=command):
                b.NETWORK_LOCK.acquire()
                b.apply_network(dict(b.common.DEFAULT,lan=True,address='10.0.0.2',hostname='10.0.0.2'),{'config.json':'new','certificate.pem':'new','key.pem':'new','local-network-ca.pem':'new'},'test')
                self.assertEqual(b.lan_status()['phase'],'failed');self.assertFalse(b.NETWORK_LOCK.locked())
                self.assertTrue(all((root/name).read_bytes()==content for name,content in snapshot.items()))
                self.assertTrue(all(b.LAN_SERVICE in args for args in commands));self.assertNotIn('usb-storage-watch-web.service',str(commands))

    def test_lan_setup_error_unlocks_and_interrupted_change_reports_failure(self):
        b=load('web_broker')
        with tempfile.TemporaryDirectory() as tmp,patch.object(b.s,'STATE_DIR',Path(tmp)),patch.object(b.pwd,'getpwnam',side_effect=KeyError('missing account')):
            # Identity lookup must fail without leaving an endless pending operation.
            b.NETWORK_LOCK.acquire()
            b.apply_network(b.common.DEFAULT,{},'test')
            self.assertEqual(b.lan_status()['phase'],'failed')
            self.assertFalse(b.NETWORK_LOCK.locked())
            (Path(tmp)/'lan-operation.json').write_text(json.dumps(dict(phase='applying')))
            self.assertEqual(b.lan_status()['phase'],'failed')

    def test_invalid_lan_file_does_not_break_configuration_read(self):
        m=Machine();self.addCleanup(m.close);m.network.write_text('{broken')
        self.assertEqual(m.b.network_configuration(),m.b.common.DEFAULT)
        login=m.broker.sessions.login('admin','synthetic')
        result=m.broker.handle(dict(drive='legacy',action='config',write=False,token=login['token']))
        self.assertEqual(result['status'],200);self.assertEqual(result['data']['defaults']['monitor']['interval'],15)

    def test_new_parent_traversal_ignores_root_umask_without_changing_existing_folders(self):
        mod=load('web_images');w=load('engine')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);existing=root/'existing';existing.mkdir(mode=0o700);dev=root.stat().st_dev
            w.MOUNT=tmp;w.verify_main=Mock(return_value=f'{os.major(dev)}:{os.minor(dev)}')
            b=Mock(w=w,s=w.settings);b.s.below=w.settings.below;b.s.absolute=w.settings.absolute
            mask=os.umask(0o077)
            try:fd=mod.rooted(b,str(existing/'new'/'folder'),True);os.close(fd)
            finally:os.umask(mask)
            self.assertEqual(existing.stat().st_mode & 0o777,0o700)
            self.assertEqual((existing/'new').stat().st_mode & 0o777,0o755)
            self.assertEqual((existing/'new'/'folder').stat().st_mode & 0o777,0o755)

    def test_acl_grant_keeps_others_effective_permissions_and_default_acl(self):
        mod=load('web_images')
        text='user::rwx\nuser:123:rwx\t#effective:r-x\ngroup::rwx\t#effective:r-x\nmask::r-x\nother::---\ndefault:user::rwx\n'
        result=mod.granted_acl(text,1000,0,'rwx')
        self.assertIn('user:123:r-x\n',result);self.assertIn('group::r-x\n',result)
        self.assertIn('user:1000:rwx\n',result);self.assertIn('default:user::rwx\n',result)

    def test_existing_parent_acl_access_is_preserved_when_adding_traversal(self):
        mod=load('web_images')
        acl='user::rwx\nuser:1000:rw-\ngroup::r--\nmask::rw-\nother::---\n'
        self.assertEqual(mod.effective_acl(acl,1000,0,0,[1000]),set('rw'))
        self.assertEqual(mod.effective_acl(acl,2000,0,0,[0]),set('r'))
        self.assertEqual(mod.effective_acl(acl,2000,0,0,[2000]),set())

    def test_unknown_rotational_metadata_never_claims_idle_or_standby(self):
        mod=load('standby');w=Mock()
        with tempfile.TemporaryDirectory() as tmp,patch.object(mod,'identity',return_value={'sys':tmp}),patch.object(mod,'activity') as activity:
            queue=Path(tmp)/'queue';queue.mkdir()
            for value,label in [('0','Not applicable for flash storage'),('unknown','Unknown')]:
                (queue/'rotational').write_text(value)
                result=mod.status(w);self.assertEqual(result['label'],label);self.assertFalse(result['applicable'])
            activity.assert_not_called()

    def test_malformed_format_worker_result_is_terminal_and_never_retried(self):
        m=Machine();self.addCleanup(m.close);worker=Mock();worker.poll.return_value=True;m.broker.prepare_worker=worker
        m.b.preparation.record(m.b.preparation_context(),dict(phase='formatting',message='Formatting'))
        with patch.object(m.b.w,'worker_json',side_effect=ValueError('bad JSON')):
            result=m.broker.prepare_progress()
        self.assertEqual(result['phase'],'failed');self.assertIsNone(m.broker.prepare_worker);worker.cancel.assert_called_once()
        self.assertEqual(m.broker.prepare_progress()['phase'],'failed')

    def test_formatting_blocks_conflicting_writes_without_starting_monitoring(self):
        m=Machine();self.addCleanup(m.close);worker=Mock();worker.poll.return_value=None;m.broker.prepare_worker=worker
        m.b.preparation.record(m.b.preparation_context(),dict(phase='formatting'))
        login=m.broker.sessions.login('admin','synthetic')
        for action in ('monitor','image-apply','disk-operation','prepare-drive'):
            result=m.broker.handle(dict(drive='legacy',action=action,write=True,token=login['token'],csrf=login['csrf'],data={}))
            self.assertEqual(result['status'],400);self.assertIn('Formatting',result['error'])
        self.assertFalse(m.active)

    def test_numeric_defaults_stay_constant_and_server_rejects_out_of_range(self):
        m=Machine();self.addCleanup(m.close);c=m.b.s.default();c['disk'].update(uuid=UUID,mountpoint=DESKTOP);m.b.cli.save(m.config,c)
        for group,key,value in [('monitor','interval',0),('usb','disable_seconds',9),('docker','worker_timeout',99999),('monitor','observations',True)]:
            with self.subTest(group=group,key=key),self.assertRaises(ValueError):m.b.timing_settings(dict(revision=m.b.s.digest(c),timings={group:{key:value}}))
        self.assertEqual(m.b.configuration(),c)

class IndependentSettings(unittest.TestCase):
    def test_setup_preserves_saved_email_and_multiple_spaces_byte_for_byte(self):
        from test_application_storage import image
        m=Machine();self.addCleanup(m.close);b=m.b
        c=b.s.default();c['disk'].update(uuid=UUID,mountpoint=DESKTOP,fstab_options='defaults')
        c['images']=[image(2,DESKTOP),image(3,DESKTOP)];c['notifications']['enabled']=True;b.cli.save(m.config,c)
        mail=b.s.SMTP;mail.write_text('{"saved":"DUMMY-TEST-PASSWORD"}\n');before=mail.read_bytes()
        m.patch(b.w,'fstab_check',Mock())  # synthetic configured dependent mounts
        plan=b.protection.plan(b.protection_context(),UUID,True)
        b.protection.activate(b.protection_context(),dict(uuid=UUID,automatic=True,token=plan['token'],consent=True))
        self.assertEqual(mail.read_bytes(),before);self.assertTrue(b.configuration()['notifications']['enabled'])
        self.assertEqual(b.configuration()['images'],c['images']);self.assertTrue(m.active)

    def test_unknown_service_state_is_never_reported_as_stopped(self):
        b=load('web_broker');c=b.s.default();c['disk']['uuid']=UUID
        for state in ('activating','deactivating','unknown',None):
            value=b.recovery_progress(c,{},dict(healthy=True),dict(ActiveState=state))
            self.assertEqual(value['code'],'unknown');self.assertNotIn('disabled',value['title'].lower())

if __name__=='__main__':unittest.main()
