# SPDX-License-Identifier: MIT
"""DEV7 retrievable credential lifecycle; private paths and synthetic accounts."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from concurrent.futures import ThreadPoolExecutor
from gui_fixture import Machine

class TokenLifecycle(unittest.TestCase):
    def setUp(self):
        self.m=Machine();self.addCleanup(self.m.close);self.b=self.m.b;self.a=self.b.auth
        self.m.patch(self.a,'administrator',lambda name:Mock(pw_name=name,pw_uid=1000,pw_gid=1000))
        self.legacy=self.m.config.with_name('management-token.json');self.file=self.m.state/'management.token'
        self.m.patch(self.a,'installation_account',lambda old:'admin')

    def verify(self,value):return self.a.verify_management_token(self.legacy,value,self.m.state)
    def ensure(self):return self.a.ensure_management_token(self.legacy,self.m.state)
    def login(self,value):return self.m.broker.handle(dict(action='login',write=True,data={'management_token':value}))

    def test_fresh_install_creates_unique_private_retrievable_token_and_is_idempotent(self):
        self.assertEqual(self.ensure(),'created');token=self.file.read_text().strip()
        self.assertEqual(self.verify(token),'admin');self.assertEqual(self.file.stat().st_uid,os.geteuid())
        self.assertEqual(self.file.stat().st_mode & 0o777,0o600);self.assertEqual(self.m.state.stat().st_mode & 0o777,0o700)
        before=self.file.read_bytes();self.assertEqual(self.ensure(),'preserved');self.assertEqual(self.file.read_bytes(),before)
        with ThreadPoolExecutor(max_workers=4) as pool:self.assertEqual(list(pool.map(lambda _:self.ensure(),range(4))),['preserved']*4)
        second=self.a.rotate_management_token(self.m.state,'admin');self.assertNotEqual(second,token)
        with self.assertRaises(self.a.Denied):self.verify(token)
        self.assertEqual(self.verify(second),'admin')

    def test_dev6_migration_preserves_old_verifier_sessions_settings_and_companion_tokens(self):
        old=self.m.management_token();saved=self.legacy.read_bytes();session=self.login(old)['data']
        sentinels=[self.m.config.with_name('smtp.json'),self.m.config.with_name('standby-api.json'),self.m.config.with_name('companion-api.json'),self.m.state/'state.json',self.m.state/'history.fixture']
        for p in sentinels:p.write_bytes(b'preserve-existing-data')
        self.assertEqual(self.ensure(),'transition');new=self.file.read_text().strip()
        self.assertEqual(self.legacy.read_bytes(),saved);self.assertEqual(self.verify(old),'admin');self.assertEqual(self.verify(new),'admin')
        self.assertEqual(self.m.broker.sessions.check(session['token'])['username'],'admin')
        self.assertTrue(self.a.management_transition(self.legacy,self.m.state))
        self.assertTrue(all(p.read_bytes()==b'preserve-existing-data' for p in sentinels))

    def test_explicit_rotation_retires_legacy_and_all_sessions_and_logout(self):
        old=self.m.management_token();self.ensure();new=self.file.read_text().strip()
        first=self.login(old)['data'];second=self.login(new)['data']
        reply=self.m.broker.handle(dict(action='management-token',write=True,token=second['token'],csrf=second['csrf'],data={'confirm':True}))
        self.assertEqual(reply['status'],200);current=reply['data']['management_token']
        self.assertEqual(current,self.file.read_text().strip());self.assertEqual(self.verify(current),'admin')
        for token in (old,new):self.assertEqual(self.login(token)['status'],401)
        for session in (first,second):
            with self.assertRaises(self.a.Denied):self.m.broker.sessions.check(session['token'])
        self.assertFalse(self.a.management_transition(self.legacy,self.m.state))
        signed=self.login(current)['data'];self.m.broker.sessions.logout(signed['token'])
        with self.assertRaises(self.a.Denied):self.m.broker.sessions.check(signed['token'])

    def test_missing_file_needs_explicit_recovery_and_never_revives_retired_dev6(self):
        old=self.m.management_token();self.ensure();self.a.rotate_management_token(self.m.state,'admin');self.file.unlink()
        self.assertEqual(self.ensure(),'recovery-required');self.assertFalse(self.file.exists())
        self.assertEqual(self.login(old)['status'],401)
        # Existing local-only administrator authentication authorizes regeneration.
        session=self.m.broker.handle(dict(action='login',write=True,local=True,data={'username':'admin','password':'synthetic'}))['data']
        result=self.m.broker.handle(dict(action='management-token',write=True,token=session['token'],csrf=session['csrf'],data={'confirm':True}))
        self.assertEqual(result['status'],200);self.assertEqual(self.verify(self.file.read_text().strip()),'admin')
        self.assertEqual(self.login(old)['status'],401)

    def test_failed_atomic_replace_leaves_previous_credential_consistent(self):
        self.ensure();old=self.file.read_text().strip()
        with patch.object(self.a.os,'replace',side_effect=OSError('synthetic disk error')):
            with self.assertRaises(OSError):self.a.rotate_management_token(self.m.state,'admin')
        self.assertEqual(self.file.read_text().strip(),old);self.assertEqual(self.verify(old),'admin')
        self.assertEqual(list(self.m.state.glob('.management-*')),[])

    def test_failure_after_credential_commit_still_invalidates_sessions(self):
        self.ensure();old=self.file.read_text().strip();session=self.login(old)['data']
        original=self.a.atomic_secret
        def interrupted(path,value):
            if path.name=='management-token-initialized':raise OSError('synthetic post-commit error')
            return original(path,value)
        with patch.object(self.a,'atomic_secret',side_effect=interrupted):
            result=self.m.broker.handle(dict(action='management-token',write=True,token=session['token'],csrf=session['csrf'],data={'confirm':True}))
        self.assertEqual(result['status'],503)
        with self.assertRaises(self.a.Denied):self.m.broker.sessions.check(session['token'])
        self.assertNotEqual(self.file.read_text().strip(),old)
        self.assertEqual(self.verify(self.file.read_text().strip()),'admin')
        self.assertEqual(self.login(old)['status'],401)

    def test_wrong_mode_symlinks_and_account_changes_are_refused(self):
        self.ensure();token=self.file.read_text().strip();self.file.chmod(0o644)
        self.assertEqual(self.login(token)['status'],401);self.file.chmod(0o600)
        with patch.object(self.a,'administrator',return_value=Mock(pw_uid=2000)):
            self.assertEqual(self.login(token)['status'],401)
        self.file.rename(self.m.state/'safe-copy');self.file.symlink_to(self.m.state/'safe-copy')
        self.assertEqual(self.login(token)['status'],401)
        self.a.rotate_management_token(self.m.state,'admin')
        self.assertFalse(self.file.is_symlink());self.assertEqual((self.m.state/'safe-copy').read_text().strip(),token)
        self.file.write_bytes(b'\xffinvalid token encoding')
        self.assertEqual(self.ensure(),'recovery-required')
        self.assertEqual(self.file.read_bytes(),b'\xffinvalid token encoding')
        self.assertEqual(self.login(token)['status'],401)
        self.a.rotate_management_token(self.m.state,'admin')
        self.assertEqual(self.verify(self.file.read_text().strip()),'admin')

    def test_local_http_lan_http_lan_https_auth_csrf_and_secret_boundaries(self):
        self.ensure();token=self.file.read_text().strip()
        for scheme,lan,host in [('http',False,'localhost'),('http',True,'10.0.0.2'),('https',True,'10.0.0.2')]:
            with self.subTest(scheme=scheme,lan=lan):
                config=dict(self.b.common.DEFAULT,lan=lan,scheme=scheme,address=host if lan else '127.0.0.1',hostname=host)
                client=self.m.web.create_app(config,self.m.broker.handle).test_client();base=scheme+'://'+host+':8765'
                headers={'Origin':base,'X-USW-Request':'1'}
                self.assertEqual(client.get('/api/drives/legacy/config',base_url=base).status_code,401)
                info=client.get('/api/login-info',base_url=base);self.assertNotIn(token,info.text)
                self.assertEqual(info.json['bootstrap'],not lan)
                for path in ('/management.token','/static/management.token','/api/management.token'):
                    response=client.get(path,base_url=base);self.assertNotIn(token,response.text);self.assertNotEqual(response.status_code,200)
                result=client.post('/api/login',base_url=base,headers=headers,json={'management_token':token});self.assertEqual(result.status_code,200)
                self.assertNotIn(token,result.text)
                configuration=client.get('/api/drives/legacy/config',base_url=base);self.assertEqual(configuration.status_code,200);self.assertNotIn(token,configuration.text)
                self.assertEqual(client.post('/api/management-token',base_url=base,headers=headers,json={'confirm':True}).status_code,401)
                self.assertEqual(client.get('/api/companion/v1/status',base_url=base,headers={'Authorization':'Bearer '+token}).status_code,404)
                if lan:self.assertEqual(client.post('/api/login',base_url=base,headers=headers,json={'username':'admin','password':'synthetic'}).status_code,401)

    def test_named_installing_admin_is_selected_before_desktop_fallback(self):
        # Actual production selector, synthetic identity database.
        from gui_fixture import load
        auth=load('web_auth');accounts=[Mock(pw_name='first',pw_uid=1000),Mock(pw_name='installer',pw_uid=1001)]
        with patch.object(auth.pwd,'getpwall',return_value=accounts),patch.object(auth,'administrator',side_effect=lambda name:next(a for a in accounts if a.pw_name==name)),patch.dict(os.environ,{'SUDO_USER':'installer'},clear=True):
            self.assertEqual(auth.installation_account(None),'installer')
            self.assertEqual(auth.installation_account({'username':'first'}),'first')

if __name__=='__main__':unittest.main()
