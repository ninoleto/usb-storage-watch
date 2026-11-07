"""Real loopback TLS/HTTP probes; disposable PKI and simulated systemd only."""
import copy
import itertools
import json
import socket
import ssl
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from gui_fixture import Machine, load
from test_ui12_network import Timer

net = load('web_network')

class TLS(unittest.TestCase):
    def setUp(self):
        self.machine = Machine(); self.addCleanup(self.machine.close)
        self.b = self.machine.b
        self.c = net.Context(SimpleNamespace(**vars(self.b)))
        self.machine.patch(self.b.common, 'WEB_CONFIG', self.c.web_dir/'config.json')
        self.c.own_web = lambda _: None
        self.c.publish_port = lambda _: None
        self.address = '192.168.50.2'  # Synthetic identity; every TCP connection is pinned to loopback below.
        self.c.addresses = lambda: [dict(address=self.address,available=True,interface='fixture-link',automatic=True)]
        module = self.b.common.module
        def modules(name, *args):
            value = module(name, *args)
            if name == 'network_addresses': value.discover = lambda command: self.c.addresses()
            return value
        self.machine.patch(self.b.common, 'module', modules)
        connect = socket.create_connection
        def loopback_only(address, *args, **kwargs):
            self.assertIn(address[0], (self.address,'127.0.0.1'))
            return connect(('127.0.0.1',address[1]), *args, **kwargs)
        self.machine.patch(socket, 'create_connection', loopback_only)
        self.c.command = self.command
        self.servers = {}; self.calls = []; self.bad = False
        self.addCleanup(self.stop_all)
        self.files = self.c.leaf(self.address)
        self.http = self.start('http',0)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); self.tls_port = sock.getsockname()[1]
        self.initial = dict(self.b.common.DEFAULT,lan=True,scheme='http',address=self.address,hostname=self.address,
                            port=self.http.server_port,http_port=self.http.server_port)
        self.c.atomic(self.c.web_dir/'config.json',json.dumps(self.initial))
        self.c.material = self.material
        self.c.stopped = lambda _: None
        self.manager = net.Manager(self.c,timer=Timer)
        self.machine.patch(self.b, 'NETWORK_MANAGER', self.manager)
        self.session = self.machine.broker.sessions.login('admin','synthetic')

    def command(self,args,timeout=30):
        if args[0].endswith('openssl'):
            return subprocess.run(args,capture_output=True,text=True,check=True,timeout=timeout).stdout
        self.assertEqual(args[0],'/usr/bin/systemctl'); self.calls.append(args)
        action,unit = args[1:3]
        if unit == net.TEST.format('lan'):
            if action == 'start':
                cfg=json.loads((self.c.web_dir/'test-lan.json').read_text());self.start('test',cfg['port'],True)
            elif action == 'stop': self.stop('test')
        elif unit == net.LAN and action == 'restart':
            self.stop('saved')
            if self.c.config()['scheme']=='https':self.start('saved',self.tls_port,True,saved=True)
        return ''

    def material(self,data):
        value=dict(self.initial,lan=True,address=self.address,hostname=self.address,scheme='https',
                   https_port=self.tls_port,port=self.tls_port)
        return value,dict(self.files,**{'config.json':json.dumps(value)})

    def start(self,key,port,tls=False,saved=False):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                host=owner.address if self.headers.get('Host','').split(':')[0]==owner.address else '127.0.0.1'
                self.send_header('X-USW-Listener','wrong' if owner.bad and tls else ('https' if tls else 'http')+'://'+host+':'+str(self.server.server_port))
                self.end_headers();self.wfile.write(b'isolated listener')
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        server.handle_error=lambda *args: None  # Expected TLS rejection closes the connection early.
        if tls:
            prefix='' if saved else 'test-'
            ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(self.c.web_dir/(prefix+'certificate.pem')),str(self.c.web_dir/(prefix+'key.pem')))
            server.socket=ctx.wrap_socket(server.socket,server_side=True)
        self.servers[key]=server
        threading.Thread(target=server.serve_forever,daemon=True).start()
        return server

    def stop(self,key):
        server=self.servers.pop(key,None)
        if server: server.shutdown();server.server_close()
    def stop_all(self):
        for key in list(self.servers): self.stop(key)
    def fast_fail(self):
        return patch.object(net.time,'monotonic',side_effect=itertools.count(0,10))
    def stage(self):
        record=self.manager.stage({})
        with self.fast_fail():self.manager.job.run()
        return record
    def request(self,origin,csrf=True):
        return self.machine.broker.local_handle(dict(action='network-confirm',write=True,
            data={'operation':self.manager.status()['operation']},origin=origin,
            token=self.session['token'],csrf=self.session['csrf'] if csrf else 'invalid'))

    def test_first_https_real_probe_and_authenticated_exact_origin_confirmation(self):
        self.assertFalse((self.c.web_dir/'certificate.pem').exists())
        record=self.stage()
        self.assertEqual(self.manager.status()['phase'],'pending')
        self.assertFalse((self.c.web_dir/'certificate.pem').exists())
        self.assertEqual(self.c.config()['scheme'],'http')
        self.assertEqual(self.request(record['url'],csrf=False)['status'],401)
        self.assertEqual(self.request('http://127.0.0.1:'+str(self.http.server_port))['status'],400)
        self.assertEqual(self.request(record['url'])['status'],200)
        self.manager.job.run()
        self.assertEqual(self.manager.status()['phase'],'complete')
        self.assertEqual(self.c.config()['scheme'],'https')
        self.assertTrue(self.c.certificate_trusted())
        self.c.ready(dict(lan=False,address='127.0.0.1',hostname='127.0.0.1',scheme='http',port=self.http.server_port),None)

    def test_failed_test_rolls_back_without_saved_material_or_false_pending(self):
        before=(self.c.web_dir/'config.json').read_bytes();self.bad=True
        self.stage()
        self.assertEqual(self.manager.status()['phase'],'failed')
        self.assertEqual((self.c.web_dir/'config.json').read_bytes(),before)
        self.assertFalse((self.c.web_dir/'certificate.pem').exists())
        self.assertNotIn('test',self.servers)
        self.bad=False
        self.c.ready(dict(lan=False,address='127.0.0.1',hostname='127.0.0.1',scheme='http',port=self.http.server_port),None)

    def test_rejects_wrong_hostname_chain_exact_certificate_and_listener(self):
        self.stage();self.assertEqual(self.manager.status()['phase'],'pending')
        entry=dict(lan=True,address=self.address,hostname=self.address,scheme='https',port=self.tls_port)
        alternate=self.c.leaf(self.address)['certificate.pem']
        untrusted=self.machine.root/'untrusted.pem'
        subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-subj','/CN=Untrusted fixture',
                        '-keyout',str(self.machine.root/'untrusted.key'),'-out',str(untrusted),'-days','1'],
                        check=True,capture_output=True,timeout=20)
        leaf=untrusted.read_text()
        with self.assertRaises(ssl.SSLCertVerificationError):self.b.lan_ready(entry,leaf)
        for fields,cert,bad in [(dict(hostname='wrong.invalid'),self.files['certificate.pem'],False),
                                 ({},leaf,False),({},alternate,False),({},self.files['certificate.pem'],True)]:
            with self.subTest(fields=fields,bad=bad,chain=cert==leaf):
                self.bad=bad
                with self.fast_fail(),self.assertRaises(ValueError):self.c.ready(dict(entry,**fields),cert)
        self.bad=False
        self.c.ready(entry,self.files['certificate.pem'])

    def test_existing_saved_untrusted_certificate_is_still_rejected(self):
        self.stage();self.assertEqual(self.manager.status()['phase'],'pending')
        for name,value in self.files.items():self.c.atomic(self.c.web_dir/name,value)
        entry=dict(lan=True,address=self.address,hostname=self.address,scheme='https',port=self.tls_port)
        self.c.ready(entry,self.files['certificate.pem'])
        (self.c.web_dir/'local-network-ca.pem').write_text('invalid trust authority')
        with self.fast_fail(),self.assertRaises(ValueError):self.c.ready(entry,self.files['certificate.pem'])

    def test_failed_commit_restores_verified_http_and_removes_unsaved_certificates(self):
        before=(self.c.web_dir/'config.json').read_bytes();record=self.stage()
        self.assertEqual(self.request(record['url'])['status'],200)
        self.bad=True
        with self.fast_fail():self.manager.job.run()
        self.assertEqual(self.manager.status()['phase'],'failed')
        self.assertIn('Previous settings restored and verified',self.manager.status()['message'])
        self.assertEqual((self.c.web_dir/'config.json').read_bytes(),before)
        self.assertFalse((self.c.web_dir/'certificate.pem').exists())
        self.assertNotIn('test',self.servers);self.assertNotIn('saved',self.servers)
        self.b.lan_ready(dict(self.initial,port=self.http.server_port))

if __name__=='__main__':unittest.main()
