# SPDX-License-Identifier: MIT
"""Isolated network transactions: no systemd, live listeners or host configuration."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from gui_fixture import load, Machine

net=load('web_network')
common=load('web_common')
web=load('web')

class Timer:
    def __init__(self,seconds,fn,args=()):self.seconds,self.fn,self.args=seconds,fn,args;self.cancelled=False
    def start(self):pass
    def cancel(self):self.cancelled=True
    def run(self):
        if not self.cancelled:self.fn(*self.args)

class Context:
    def __init__(self,root):
        self.state=root/'state';self.web_dir=root/'web';self.state.mkdir();self.web_dir.mkdir()
        self.calls=[];self.fail=False
        self.initial=common.network_config(dict(common.DEFAULT,lan=True,address='192.168.50.2',hostname='192.168.50.2',scheme='http'))
        self.atomic(self.web_dir/'config.json',json.dumps(self.initial))
    def atomic(self,path,text,mode=0o600):path.write_text(text);path.chmod(mode)
    def own_web(self,path):pass
    def config(self):return common.network_config(json.loads((self.web_dir/'config.json').read_text()))
    def material(self,data):
        value=dict(self.config(),**data);value['hostname']=value['address'];value['port']=value[value['scheme']+'_port']
        return value,{'config.json':json.dumps(value),'certificate.pem':'SYNTHETIC CERTIFICATE','key.pem':'SYNTHETIC PRIVATE MATERIAL'}
    def command(self,args,timeout):
        self.calls.append(args)
        if self.fail and 'restart' in args and net.LAN in args:
            self.fail=False;raise ValueError('Synthetic listener failure')
    def stopped(self,unit):self.calls.append(['stopped',unit])
    def ready(self,endpoint,certificate):self.calls.append(['ready',endpoint['address'],endpoint['port']])

class Transactions(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.c=Context(Path(temporary.name));self.now=1000;self.elapsed=0
        self.m=net.Manager(self.c,clock=lambda:self.now,timer=Timer,monotonic=lambda:self.elapsed)
    def stage(self,**kwargs):
        result=self.m.stage(dict(address='192.168.50.3',**kwargs));self.m.job.run();return self.m.status()
    def test_old_listeners_and_saved_config_survive_until_new_origin_confirms(self):
        result=self.stage();self.assertEqual(result['phase'],'pending');self.assertEqual(result['seconds_left'],180)
        self.assertEqual(self.c.config(),self.c.initial)
        self.assertFalse(any('restart' in row or 'disable' in row for row in self.c.calls))
        self.assertNotIn('SYNTHETIC PRIVATE',json.dumps(result));self.assertNotIn('files',result);self.assertNotIn('before',result)
        for origin in (None,net.url(self.c.initial),result['url']+'/path','http://attacker.invalid'):
            with self.assertRaises(ValueError):self.m.confirm(result['operation'],origin)
        self.m.confirm(result['operation'],result['url']);self.assertEqual(self.c.config(),self.c.initial)
        self.m.job.run();self.assertEqual(self.c.config()['address'],'192.168.50.3')
        self.assertEqual(self.m.status()['phase'],'complete')
        calls=copy.deepcopy(self.c.calls);self.m.confirm(result['operation'],result['url']);self.assertEqual(calls,self.c.calls)
        self.assertNotIn('before',self.m.read());self.assertNotIn('files',self.m.read())
    def test_timeout_and_cancel_keep_old_settings(self):
        result=self.stage();self.now+=181;self.m.expire(result['operation']);self.m.job.run()
        self.assertEqual(self.m.status()['phase'],'expired');self.assertEqual(self.c.config(),self.c.initial)
        result=self.stage();self.m.cancel(result['operation']);self.m.job.run()
        self.assertEqual(self.m.status()['phase'],'cancelled');self.assertEqual(self.c.config(),self.c.initial)
        with self.assertRaises(ValueError):self.m.confirm(result['operation'],result['url'])
    def test_restart_cancels_pending_and_rolls_back_interrupted_commit(self):
        result=self.stage();net.Manager(self.c,timer=Timer).recover()
        self.assertEqual(self.m.status()['phase'],'cancelled');self.assertEqual(self.c.config(),self.c.initial)
        result=self.stage();self.m.confirm(result['operation'],result['url'])
        self.c.atomic(self.c.web_dir/'config.json',json.dumps(result['config']))
        net.Manager(self.c,timer=Timer).recover();self.assertEqual(self.c.config(),self.c.initial)
        self.assertEqual(self.m.status()['phase'],'cancelled')
    def test_commit_failure_restores_and_verifies_old_configuration(self):
        result=self.stage();self.c.fail=True;self.m.confirm(result['operation'],result['url']);self.m.job.run()
        self.assertEqual(self.c.config(),self.c.initial);self.assertEqual(self.m.status()['phase'],'failed')
        self.assertIn('restored and verified',self.m.status()['message'])
    def test_protocol_collision_and_concurrent_change_refused(self):
        with self.assertRaisesRegex(ValueError,'another protocol'):
            self.m.stage(dict(scheme='https',https_port=8765))
        result=self.stage()
        with self.assertRaisesRegex(ValueError,'pending'):self.m.stage(dict(lan=False))
        with self.assertRaises(ValueError):self.m.cancel('wrong-operation')
        self.assertEqual(self.c.config(),self.c.initial)
    def test_disable_requires_local_connection_and_local_port_is_staged(self):
        result=self.stage(lan=False,http_port=9010)
        self.assertEqual(result['url'],'http://127.0.0.1:9010')
        with self.assertRaises(ValueError):self.m.confirm(result['operation'],'http://192.168.50.3:9010')
        self.assertIn(['/usr/bin/systemctl','start',net.TEST.format('local')],self.c.calls)
        self.assertNotIn(['/usr/bin/systemctl','restart',net.LOCAL],self.c.calls)
        self.m.confirm(result['operation'],result['url']);self.m.job.run()
        self.assertFalse(self.c.config()['lan']);self.assertEqual(self.c.config()['http_port'],9010)
        self.assertIn(['/usr/bin/systemctl','restart',net.LOCAL],self.c.calls)
    def test_prepare_error_keeps_configuration_and_status_is_nonblocking(self):
        self.c.ready=Mock(side_effect=ValueError('Port unavailable'))
        result=self.stage();self.assertEqual(result['phase'],'failed');self.assertEqual(self.c.config(),self.c.initial)
        self.m.lock=Mock();self.m.lock.__enter__=Mock(side_effect=AssertionError('Status must not wait for a service operation'))
        self.assertEqual(self.m.status()['phase'],'failed')
    def test_expired_origin_cannot_commit_even_if_timer_is_delayed(self):
        result=self.stage();self.now+=181
        with self.assertRaises(ValueError):self.m.confirm(result['operation'],result['url'])
        self.assertEqual(self.c.config(),self.c.initial)
    def test_backward_wall_clock_cannot_extend_confirmation_window(self):
        result=self.stage();self.now-=3600;self.elapsed+=181
        self.assertEqual(self.m.status()['seconds_left'],0)
        with self.assertRaises(ValueError):self.m.confirm(result['operation'],result['url'])
        self.m.expire(result['operation']);self.m.job.run()
        self.assertEqual(self.m.status()['phase'],'expired');self.assertEqual(self.c.config(),self.c.initial)

class Boundaries(unittest.TestCase):
    def test_material_rejects_invalid_ports_addresses_and_types_before_writes(self):
        m=Machine();self.addCleanup(m.close);context=net.Context(SimpleNamespace(**vars(m.b)))
        context.addresses=lambda:[dict(address='192.168.50.2')]
        base=dict(lan=True,address='192.168.50.2',scheme='http',http_port=8765,https_port=8766)
        original=m.network.read_bytes()
        with patch.object(context.b.auth,'management_configured',return_value=True),patch.object(net.socket,'socket'):
            for values in [dict(lan='true'),dict(scheme='ftp'),dict(http_port=80),dict(http_port=True),dict(https_port=65536),dict(address='0.0.0.0'),dict(address='8.8.8.8'),dict(address='192.168.50.9')]:
                with self.assertRaises(ValueError):context.material(dict(base,**values))
            value,files=context.material(base)
        self.assertEqual(value['port'],8765);self.assertEqual(json.loads(files['config.json']),value)
        self.assertEqual(m.network.read_bytes(),original)

    def test_launcher_accepts_only_a_trusted_numeric_local_port(self):
        launcher=load('open_dashboard')
        real_fstat=os.fstat
        def owned(fd):
            value=real_fstat(fd)
            return SimpleNamespace(st_uid=0,st_mode=value.st_mode,st_size=value.st_size)
        with tempfile.TemporaryDirectory() as root, patch.object(launcher.os,'fstat',side_effect=owned):
            path=Path(root)/'port';path.write_text('9010\n');path.chmod(0o644)
            self.assertEqual(launcher.dashboard_url(path),'http://127.0.0.1:9010/')
            for text in ('https://remote.invalid/', '0', '65536', '9010;anything'):
                path.write_text(text);self.assertEqual(launcher.dashboard_url(path),'http://127.0.0.1:8765/')
            path.write_text('9010');path.chmod(0o666)
            self.assertEqual(launcher.dashboard_url(path),'http://127.0.0.1:8765/')

    def test_origin_is_derived_from_listener_not_json(self):
        calls=[]
        def rpc(request):calls.append(request);return dict(status=200,data={})
        app=web.create_app(dict(common.DEFAULT),rpc);client=app.test_client()
        headers={'Origin':'http://127.0.0.1:8765','X-USW-Request':'1','X-CSRF-Token':'synthetic'}
        result=client.post('/api/network-confirm',base_url='http://127.0.0.1:8765',headers=headers,json={'operation':'synthetic','origin':'https://192.168.50.3:8766'})
        self.assertEqual(result.status_code,200);self.assertEqual(calls[-1]['origin'],'http://127.0.0.1:8765')
        result=client.post('/api/network-confirm',base_url='http://192.168.50.3:8766',headers=headers,json={})
        self.assertEqual(result.status_code,403);self.assertEqual(len(calls),1)
    def test_auth_csrf_and_legacy_no_auto_apply(self):
        m=Machine();self.addCleanup(m.close)
        for action,write in [('network-state',False),('network-stage',True),('network-confirm',True),('network-cancel',True),('network-certificate',True),('network-renew',True)]:
            self.assertEqual(m.broker.local_handle(dict(action=action,write=write,data={}))['status'],401)
        session=m.broker.sessions.login('admin','synthetic')
        for action in ('network-stage','network-confirm','network-cancel','network-certificate','network-renew'):
            self.assertEqual(m.broker.local_handle(dict(action=action,write=True,data={},token=session['token']))['status'],401)
        for action in ('network','lan-auto'):
            result=m.broker.local_handle(dict(action=action,write=True,data={},token=session['token'],csrf=session['csrf']))
            self.assertEqual(result['status'],400);self.assertIn('test and confirm',result['error'])
    def test_local_port_and_test_path_allowlist(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(web.common,'WEB_DIR',Path(directory)),patch.object(web.common,'WEB_CONFIG',Path(directory)/'config.json'):
            web.common.WEB_CONFIG.write_text(json.dumps(dict(lan=True,http_port=9010,address='invalid')))
            cfg,prefix=web.listener_config([]);self.assertEqual(cfg['port'],9010);self.assertFalse(cfg['lan'])
            web.common.WEB_CONFIG.write_text('{bad');self.assertEqual(web.listener_config([])[0]['port'],8765)
            with self.assertRaises(ValueError):web.listener_config(['--network-test','../../key'])
    def test_public_certificate_and_private_material_boundary(self):
        m=Machine();self.addCleanup(m.close);context=net.Context(SimpleNamespace(**vars(m.b)))
        context.own_web=lambda path:None
        def command(argv,timeout=10):return subprocess.run(argv,timeout=timeout,capture_output=True,text=True,check=True).stdout
        context.command=command
        first=context.prepare_certificate();self.assertTrue(first['available'])
        key=context.state/'network-issuer/key.pem';self.assertEqual(key.stat().st_mode&0o777,0o600)
        for address in ('192.168.50.2','192.168.50.3'):
            files=context.leaf(address);self.assertEqual(files['local-network-ca.pem'],(context.web_dir/'proposed-network-ca.pem').read_text())
            cert=context.state/'verify.pem';cert.write_text(files['certificate.pem'])
            self.assertIn('does match',command(['/usr/bin/openssl','x509','-in',str(cert),'-checkip',address,'-noout']))
        self.assertEqual(context.prepare_certificate(),first)
        self.assertEqual(json.loads(m.network.read_text()),m.b.common.DEFAULT)
        self.assertNotIn('PRIVATE',json.dumps(first));self.assertNotIn('PRIVATE',(context.web_dir/'proposed-network-ca.pem').read_text())

if __name__=='__main__':unittest.main()
