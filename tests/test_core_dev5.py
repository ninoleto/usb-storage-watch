# SPDX-License-Identifier: MIT
"""DEV5 mount/access separation, token authentication and private-LAN regressions."""
import errno
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from gui_fixture import load,Machine,UUID,DESKTOP
from test_application_storage import image

class ImageAccess(unittest.TestCase):
    def test_mount_metadata_and_user_access_have_independent_results(self):
        m=Machine();self.addCleanup(m.close);b=m.b;c=b.s.default();c['disk'].update(uuid=UUID,mountpoint=DESKTOP)
        item=image(2,DESKTOP);c['images']=[item];b.cli.save(m.config,c)
        rows=[dict(target=item['mountpoint'])]
        with patch.object(b.w,'read_rows',return_value=rows),patch.object(b.w,'dependent_metadata') as metadata,patch.object(b.images,'account_access') as access:
            for failure,state in [(PermissionError(errno.EPERM,'Operation not permitted'),'inspection-failed'),(None,'denied')]:
                access.side_effect=failure;access.return_value=dict(read=False,write=False,traverse=False)
                result=b.images.entries(b.image_context((1000,1000)))[0]
                self.assertTrue(result['mounted']);self.assertTrue(result['verified']);self.assertEqual(result['mount_state'],'mounted')
                self.assertEqual(result['access_state'],state)
            metadata.side_effect=b.w.Unsafe('Unexpected UUID or loop backing identity')
            result=b.images.entries(b.image_context((1000,1000)))[0]
            self.assertTrue(result['mounted']);self.assertFalse(result['verified']);self.assertEqual(result['mount_state'],'verification-failed')
            self.assertIn('Unexpected UUID',result['mount_error'])
        with patch.object(b.w,'read_rows',return_value=[]):self.assertEqual(b.images.entries(b.image_context())[0]['mount_state'],'unmounted')

    def test_permission_policies_validate_input_and_custom_ids_do_not_inherit_host_groups(self):
        mod=load('web_images');owner=(1000,1000)
        for bad in ([],True,'user',{'kind':'bad'},{'kind':'custom','uid':0,'gid':1000},{'kind':'selected','users':[{}]},{'kind':'applications','group':'no-such-usw-test-group'}):
            with self.subTest(value=bad),self.assertRaises(ValueError):mod.access_policy(bad,owner)
        policy=mod.access_policy(dict(kind='custom',uid=2000,gid=2000,rights='r-x'),owner)
        self.assertEqual(policy['users'][0]['uid'],1000);self.assertFalse(policy['users'][1]['local'])
        with patch.object(mod.os,'getgrouplist') as groups:
            self.assertEqual(mod.account_groups(2000,2000,False),[2000]);groups.assert_not_called()
        self.assertEqual(mod.access_policy({},owner)['kind'],'user')

    def test_broker_credential_drop_failure_is_not_reported_as_unmounted(self):
        mod=load('web_images')
        with patch('subprocess.run',side_effect=PermissionError(errno.EPERM,'Operation not permitted')):
            with self.assertRaisesRegex(ValueError,'credential-drop capabilities'):mod.account_access(None,'/tmp',(1000,1000))

class ManagementAccess(unittest.TestCase):
    def setUp(self):
        self.m=Machine();self.addCleanup(self.m.close);self.b=self.m.b;self.broker=self.m.broker
        self.m.patch(self.b.auth,'administrator',lambda name:Mock(pw_name=name,pw_uid=1000,pw_gid=1000))
        self.login=self.broker.sessions.login('admin','synthetic')
        self.write=dict(write=True,token=self.login['token'],csrf=self.login['csrf'])

    def create(self):
        session=self.broker.sessions.login('admin','synthetic')
        return self.broker.handle(dict(write=True,token=session['token'],csrf=session['csrf'],action='management-token',data={'confirm':True}))['data']['management_token']

    def test_management_token_hash_private_storage_login_rotation_and_csrf(self):
        token=self.create();path=self.m.state/'management.token'
        self.assertEqual(path.read_text().strip(),token);self.assertEqual(path.stat().st_mode & 0o777,0o600)
        other=self.broker.handle(dict(action='login',write=True,data={'management_token':token}))['data']
        self.assertEqual(other['username'],'admin')
        self.assertEqual(self.broker.handle(dict(action='management-token',write=True,token=other['token'],data={'confirm':True}))['status'],401)
        new=self.create();self.assertNotEqual(new,token)
        self.assertEqual(self.broker.handle(dict(action='session',write=False,token=other['token']))['status'],401)
        self.assertEqual(self.broker.handle(dict(action='login',write=True,data={'management_token':token}))['status'],401)
        self.assertEqual(self.broker.handle(dict(action='login',write=True,data={'management_token':new}))['status'],200)
        # No monitoring/SMTP/Companion configuration is created or overwritten.
        self.assertFalse(self.m.config.exists());self.assertFalse(self.b.s.SMTP.exists())

    def test_bootstrap_is_local_only_and_invalid_token_record_allows_local_recovery(self):
        data=dict(username='admin',password='synthetic')
        self.assertEqual(self.broker.handle(dict(action='login',write=True,data=data))['status'],401)
        self.assertEqual(self.broker.handle(dict(action='login',write=True,data=data,secure=True))['status'],401)
        self.assertEqual(self.broker.handle(dict(action='login',write=True,data=data,local=True))['status'],200)
        self.create();path=self.m.state/'management.token';path.write_text('{bad')
        info=self.broker.handle(dict(action='login-info',write=False,local=True))['data']
        self.assertTrue(info['bootstrap']);self.assertFalse(info['token_configured'])
        self.assertEqual(self.broker.handle(dict(action='login',write=True,data=data,local=True))['status'],200)
        self.assertTrue(self.create().startswith('usw7_'))

    def test_token_rate_limit_and_account_identity_are_enforced(self):
        token=self.create()
        with patch.object(self.b.auth,'administrator',return_value=Mock(pw_uid=2000)):
            self.assertEqual(self.broker.handle(dict(action='login',write=True,data={'management_token':token}))['status'],401)
        for _ in range(10):self.broker.handle(dict(action='login',write=True,data={'management_token':'wrong'}))
        result=self.broker.handle(dict(action='login',write=True,data={'management_token':token}))
        self.assertEqual(result['status'],401);self.assertIn('Too many',result['error'])

    def test_lan_http_needs_warning_token_private_assigned_ip_and_preserves_local(self):
        data=dict(enabled=True,confirm=True,scheme='http',address='10.0.0.2',hostname='10.0.0.2')
        with patch.object(self.b.socket,'socket') as sock,patch.object(self.b,'queue_network',side_effect=lambda v,f:dict(value=v,files=f)):
            with self.assertRaisesRegex(ValueError,'Acknowledge'):self.b.network(data)
            data['acknowledge_http']=True
            with self.assertRaisesRegex(ValueError,'management token'):self.b.network(data)
            self.create();result=self.b.network(data)
            self.assertEqual(result['value']['scheme'],'http');self.assertEqual(set(result['files']),{'config.json'})
            for address in ('0.0.0.0','127.0.0.1','8.8.8.8','::'):
                with self.assertRaises(ValueError):self.b.network(dict(data,address=address))
            self.assertEqual(self.b.network(dict(data,address='100.64.0.2'))['value']['address'],'100.64.0.2')
            sock.return_value.__enter__.return_value.bind.side_effect=OSError('Address not assigned')
            with self.assertRaises(OSError):self.b.network(data)

    def test_existing_https_configuration_is_preserved_and_lan_http_cookie_is_separate(self):
        common=self.b.common;old=dict(common.DEFAULT,lan=True,address='10.0.0.2',hostname='10.0.0.2')
        self.assertEqual(common.network_config(old)['scheme'],'https');self.assertEqual(common.network_config(common.DEFAULT)['scheme'],'http')
        web=self.m.web
        for scheme,cookie,secure in [('http','usw_lan_http',False),('https','usw_session',True)]:
            app=web.create_app(dict(old,scheme=scheme),lambda req:dict(status=200,data={'token':'test-session','csrf':'test-csrf','username':'admin'}))
            client=app.test_client();url=scheme+'://10.0.0.2:8765'
            response=client.post('/api/login',base_url=url,headers={'Origin':url,'X-USW-Request':'1'},json={'management_token':'synthetic'})
            self.assertEqual(response.status_code,200);header=response.headers['Set-Cookie'];self.assertIn(cookie+'=',header)
            self.assertEqual('Secure' in header,secure)

    def test_invalid_saved_lan_settings_cannot_create_public_listener(self):
        for change in ({'address':'0.0.0.0'},{'address':'8.8.8.8'},{'port':True},{'scheme':'ftp'},{'hostname':None}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.m.web.create_app(dict(self.b.common.DEFAULT,lan=True,address='10.0.0.2',**{k:v for k,v in change.items() if k!='address'}) | ({'address':change['address']} if 'address' in change else {}))

class ManualReconnect(unittest.TestCase):
    def test_manual_reset_does_not_enter_mount_recovery(self):
        controls=load('controls');w=Mock();w.Unsafe=ValueError;w.WORKER_LOCK_FDS=();w.assert_internal_state=Mock()
        with tempfile.TemporaryDirectory() as tmp:
            w.STATE_DIR=Path(tmp)
            w.manual_usb.reset.return_value='Software reset verified; left unmounted.'
            with patch.object(controls,'unmount') as unmount:
                self.assertIn('left unmounted',controls.perform(w,'reconnect'))
                unmount.assert_not_called();w.recovery_work.assert_not_called()
                w.usb.ensure_enabled.assert_not_called()

if __name__=='__main__':unittest.main()
