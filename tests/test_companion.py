# SPDX-License-Identifier: MIT
"""Current dashboard setup boundary; obsolete credentials never authorize actions."""
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import unittest
from unittest.mock import Mock, patch
from gui_fixture import Machine


class CompanionSetup(unittest.TestCase):
    def setUp(self):
        self.m=Machine();self.addCleanup(self.m.close);self.b=self.m.b
        self.token=self.m.management_token();self.original=self.m.config.with_name('management-token.json').read_bytes()
        self.url='https://storage.example.test:8766'
        self.headers={'Origin':self.url,'X-USW-Request':'1'}
        cfg=dict(self.b.common.DEFAULT,lan=True,scheme='https',address='192.168.50.2',hostname='storage.example.test',port=8766,https_port=8766)
        self.client=self.m.web.create_app(cfg,self.m.broker.handle).test_client()
        self.m.patch(self.m.web.common,'WEB_DIR',self.m.root)
        self.assets=self.m.web.integrations

    def login(self,token=None):
        r=self.client.post('/api/login',base_url=self.url,json={'management_token':token or self.token},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text);self.csrf=r.json['csrf'];return r

    def get(self,path):return self.client.get(path,base_url=self.url)

    def certificate(self):
        cert=self.m.root/'local-network-ca.pem';key=self.m.root/'private.key'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=Synthetic Setup CA'],check=True,timeout=15,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return cert,key

    def test_current_session_setup_downloads_and_token_unchanged(self):
        cert,key=self.certificate();self.login()
        info=self.get('/api/integration-info');self.assertEqual(info.status_code,200)
        self.assertEqual(info.json['certificate_pem'],cert.read_text())
        ca=self.get('/download/trust-certificate.pem');self.assertEqual(ca.data,cert.read_bytes())
        package=self.get('/download/companion-module.tgz');self.assertEqual(package.status_code,200)
        self.assertEqual(hashlib.sha256(package.data).hexdigest(),info.json['module']['sha256'])
        self.assertEqual(info.json['module']['version'],'0.2.6')
        for response in (info,ca,package):
            self.assertNotIn(key.read_bytes(),response.data);self.assertNotIn(self.token.encode(),response.data)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
        for action in ('session','fleet-status','docker-overview'):
            self.assertEqual(self.get('/api/'+action).status_code,200)
        self.assertEqual(self.original,self.m.config.with_name('management-token.json').read_bytes())

    def test_downloads_require_dashboard_session_and_origin(self):
        for path in ('/api/integration-info','/download/companion-module.tgz','/download/trust-certificate.pem'):
            self.assertEqual(self.get(path).status_code,401)
            self.assertEqual(self.client.get(path,base_url=self.url,headers={'Authorization':'Bearer '+self.token}).status_code,401)
            self.assertEqual(self.client.get(path,base_url='http://storage.example.test:8766').status_code,403)
        self.login()
        self.assertEqual(self.client.get('/api/integration-info',base_url='https://wrong.example.test:8766').status_code,403)
        self.assertEqual(self.client.post('/api/management-token',base_url=self.url,headers=self.headers,json={'confirm':True}).status_code,401)
        self.assertEqual(self.client.post('/api/management-token',base_url=self.url,json={'confirm':True}).status_code,403)
        self.assertEqual(self.original,self.m.config.with_name('management-token.json').read_bytes())

    def test_old_tokens_cannot_login_read_write_or_use_downloads(self):
        for filename,prefix in [('companion-api.json','uswc_'),('standby-api.json','')]:
            token=prefix+secrets.token_urlsafe(32)
            record=dict(version=1,username='admin',uid=1000,uuid=self.m.uuid,permissions=['status','mount','sleep-hdd'],sha256=hashlib.sha256(token.encode()).hexdigest())
            path=self.m.config.with_name(filename);self.b.cli.save(path,record)
            saved=path.read_bytes()
            self.assertEqual(self.client.post('/api/login',base_url=self.url,headers=self.headers,json={'management_token':token}).status_code,401)
            for action in ('session','fleet-status','docker-overview','integration-info'):
                self.assertEqual(self.client.get('/api/'+action,base_url=self.url,headers={'Authorization':'Bearer '+token}).status_code,401)
            with patch.object(self.b,'disk_operation') as worker:
                r=self.client.post('/api/drives/legacy/disk-operation',base_url=self.url,headers=self.headers|{'Authorization':'Bearer '+token},json={'action':'sleep','uuid':self.m.uuid})
                self.assertEqual(r.status_code,401);worker.assert_not_called()
            self.assertEqual(path.read_bytes(),saved)  # Removal does not erase old evidence.

    def test_removed_routes_and_broker_operations_cannot_execute(self):
        self.login()
        with patch.object(self.b,'disk_operation') as worker:
            for path in ('/api/companion/v1/status','/api/companion/v1/capabilities','/api/companion/v1/command','/api/sleep-hdd','/api/companion-token','/api/drives/legacy/companion-token','/api/drives/legacy/standby-token'):
                self.assertEqual(self.get(path).status_code,404,path)
                r=self.client.post(path,base_url=self.url,headers=self.headers|{'X-CSRF-Token':self.csrf},json={})
                self.assertEqual(r.status_code,404,path)
            session=self.m.broker.sessions.login('admin','synthetic')
            for action in ('companion-v1','sleep-hdd','companion-token','standby-token'):
                r=self.m.broker.handle(dict(action=action,drive='legacy',write=True,data={},token=session['token'],csrf=session['csrf']))
                self.assertEqual(r['status'],400,r)
            worker.assert_not_called()

    def test_current_manual_standby_still_uses_guarded_disk_operation(self):
        self.login()
        with patch.object(self.m.broker,'manual_action',side_effect=lambda label,fn:fn()),patch.object(self.b,'disk_operation',return_value={'ok':False,'result':'busy','message':'Synthetic write activity'}) as worker:
            r=self.client.post('/api/drives/legacy/disk-operation',base_url=self.url,headers=self.headers|{'X-CSRF-Token':self.csrf},json={'action':'sleep','uuid':self.m.uuid})
            self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json['result'],'busy')
            worker.assert_called_once_with({'action':'sleep','uuid':self.m.uuid})

    def test_missing_corrupt_or_symlink_assets_fail_closed(self):
        self.login();self.assertIsNone(self.get('/api/integration-info').json['certificate_pem'])
        self.assertEqual(self.get('/download/trust-certificate.pem').status_code,404)
        folder=self.m.root/'empty-package';folder.mkdir()
        with patch.object(self.assets,'PACKAGE_DIR',folder):
            self.assertFalse(self.get('/api/integration-info').json['module']['available'])
            self.assertEqual(self.get('/download/companion-module.tgz').status_code,404)
            (folder/'module.json').write_text(json.dumps(dict(version='0.2.6',sha256='bad')));(folder/'module.tgz').write_bytes(b'wrong bytes')
            self.assertEqual(self.get('/download/companion-module.tgz').status_code,404)
        cert,key=self.certificate();saved=cert.read_text();cert.write_text(saved+key.read_text())
        self.assertEqual(self.get('/download/trust-certificate.pem').status_code,404)
        cert.unlink();cert.symlink_to(key)
        self.assertEqual(self.get('/download/trust-certificate.pem').status_code,404)
