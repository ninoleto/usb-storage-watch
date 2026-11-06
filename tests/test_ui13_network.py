# SPDX-License-Identifier: MIT
"""Certificate rotation uses disposable files and simulated service failures."""
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from gui_fixture import Machine
from test_ui12_network import net, common, web, Timer

class CertificateRenewal(unittest.TestCase):
    def setUp(self):
        self.machine=Machine();self.addCleanup(self.machine.close)
        self.c=net.Context(SimpleNamespace(**vars(self.machine.b)))
        config_patch=patch.object(self.c.b.common,'WEB_CONFIG',self.c.web_dir/'config.json');config_patch.start();self.addCleanup(config_patch.stop)
        self.c.own_web=lambda p:None
        self.real=lambda args,timeout=30:subprocess.run(args,capture_output=True,text=True,check=True,timeout=timeout).stdout
        self.c.command=self.real
        self.c.prepare_certificate()
        self.cfg=common.network_config(dict(common.DEFAULT,lan=True,address='192.168.50.2',hostname='192.168.50.2',scheme='https',port=8766,http_port=8765,https_port=8766))
        self.c.atomic(self.c.web_dir/'config.json',json.dumps(self.cfg))
        self.original=self.c.leaf(self.cfg['address'])
        for name,contents in self.original.items():self.c.atomic(self.c.web_dir/name,contents)
        self.m=net.Manager(self.c,timer=Timer)
        self.service_calls=[]
        self.c.stopped=lambda unit:None
        self.c.ready=lambda entry,cert:None
        self.c.publish_port=lambda c:None
        self.c.addresses=lambda:[dict(address=self.cfg['address'],interface='physical-test',automatic=True)]
    def services(self,args,timeout=30):
        if args[0].endswith('systemctl'):self.service_calls.append(args);return ''
        return self.real(args,timeout)
    def test_renewal_uses_same_ca_new_leaf_and_preserves_ports_and_local_listener(self):
        self.c.command=self.services
        before=self.c.certificate_info();self.assertTrue(before['renewable']);self.assertIn('server_expires',before)
        response=self.m.renew();self.assertEqual(response['kind'],'certificate-renew')
        self.assertNotIn('PRIVATE',json.dumps(response));self.assertNotIn('files',response)
        self.assertEqual((self.c.web_dir/'certificate.pem').read_text(),self.original['certificate.pem'])
        self.m.job.run();self.assertEqual(self.m.status()['phase'],'complete')
        self.assertNotEqual((self.c.web_dir/'certificate.pem').read_text(),self.original['certificate.pem'])
        self.assertEqual((self.c.web_dir/'local-network-ca.pem').read_text(),self.original['local-network-ca.pem'])
        self.assertEqual(self.c.certificate_info()['fingerprint'],before['fingerprint']);self.assertEqual(self.c.config(),self.cfg)
        self.assertNotIn(['/usr/bin/systemctl','restart',net.LOCAL],self.service_calls)
        self.assertIn(['/usr/bin/systemctl','restart',net.LAN],self.service_calls)
        verified=self.real(['/usr/bin/openssl','verify','-CAfile',str(self.c.web_dir/'local-network-ca.pem'),str(self.c.web_dir/'certificate.pem')])
        self.assertIn('OK',verified)
    def test_renewal_failure_restores_old_certificate_and_configuration(self):
        failures=[True]
        def fail_once(args,timeout=30):
            if args==['/usr/bin/systemctl','restart',net.LAN] and failures[0]:
                failures[0]=False;raise ValueError('Synthetic renewal failure')
            return self.services(args,timeout)
        self.c.command=fail_once;self.m.renew();self.m.job.run()
        self.assertEqual(self.m.status()['phase'],'failed');self.assertIn('restored and verified',self.m.status()['message'])
        for name,contents in self.original.items():self.assertEqual((self.c.web_dir/name).read_text(),contents)
        self.assertEqual(self.c.config(),self.cfg)
    def test_renewal_crash_receipt_restores_before_serving(self):
        self.c.command=self.services;self.m.renew();record=self.m.read()
        for name,contents in record['files'].items():self.m.write_web(name,contents)
        net.Manager(self.c,timer=Timer).recover()
        self.assertEqual(self.m.status()['phase'],'cancelled')
        self.assertEqual((self.c.web_dir/'certificate.pem').read_text(),self.original['certificate.pem'])
    def test_foreign_ca_is_not_silently_replaced_and_pending_test_prevents_renewal(self):
        self.c.command=self.services
        (self.c.web_dir/'local-network-ca.pem').write_text('EXTERNALLY MANAGED CA')
        self.assertFalse(self.c.certificate_info()['renewable'])
        with self.assertRaisesRegex(ValueError,'confirm HTTPS'):self.m.renew()
        self.assertFalse(self.m.receipt.exists())
        (self.c.web_dir/'local-network-ca.pem').write_text(self.original['local-network-ca.pem'])
        self.m.write(dict(operation='synthetic',phase='pending'))
        with self.assertRaisesRegex(ValueError,'pending'):self.m.renew()
    def test_certificate_download_uses_importable_filename_and_requires_session(self):
        def rpc(req):return dict(status=200,data={})
        with patch.object(web.common,'WEB_DIR',self.c.web_dir):
            client=web.create_app(dict(common.DEFAULT),rpc).test_client()
            response=client.get('/download/proposed-trust-certificate.pem',base_url='http://127.0.0.1:8765')
            self.assertEqual(response.status_code,200)
            self.assertIn('usb-storage-watch-ca.crt',response.headers['Content-Disposition'])
            self.assertNotIn(b'PRIVATE KEY',response.data)
            denied=web.create_app(dict(common.DEFAULT),lambda r:dict(status=401)).test_client()
            self.assertEqual(denied.get('/download/proposed-trust-certificate.pem',base_url='http://127.0.0.1:8765').status_code,401)

if __name__=='__main__':unittest.main()
