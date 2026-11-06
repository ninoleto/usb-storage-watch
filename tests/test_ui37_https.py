# SPDX-License-Identifier: MIT
"""Current Companion HTTP client against real Gunicorn TLS and dashboard sessions.
OS boundaries are isolated by Machine. No storage/container command is sent.
"""
import argparse,hashlib,json,multiprocessing,os,ssl,subprocess,sys,time,urllib.request
from pathlib import Path
from types import SimpleNamespace
from gui_fixture import Machine


def run(node):
    with_machine=Machine()
    try:
        m=with_machine;token=m.management_token();before=m.config.with_name('management-token.json').read_bytes()
        tls=m.root/'tls';tls.mkdir();cert=tls/'certificate.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(tls/'key.pem'),'-out',str(cert),'-days','1','-subj','/CN=Synthetic Setup CA','-addext','subjectAltName=IP:127.0.0.1'],check=True,timeout=15,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        (tls/'local-network-ca.pem').write_bytes(cert.read_bytes())
        config=dict(m.b.common.DEFAULT,lan=True,address_mode='automatic',scheme='https',address='127.0.0.1',hostname='127.0.0.1',port=18765)
        def server():
            web=m.web;app=web.create_app(config,m.broker.handle);web.create_app=lambda _:app;web.listener_config=lambda _: (config,'');web.common.WEB_DIR=tls
            original=web.common.module
            web.common.module=lambda name:SimpleNamespace(discover=lambda:[],choose=lambda *_:dict(address='127.0.0.1')) if name=='network_addresses' else original(name)
            sys.argv=['web.py','--lan'];web.main()
        proc=multiprocessing.get_context('fork').Process(target=server);proc.start()
        try:
            url='https://127.0.0.1:18765';context=ssl.create_default_context(cafile=str(cert))
            for _ in range(40):
                try:
                    with urllib.request.urlopen(url+'/',context=context,timeout=.5) as r:assert r.status==200
                    break
                except OSError:time.sleep(.1)
            else:raise AssertionError('Fixture HTTPS listener unavailable')
            root=Path(__file__).resolve().parents[1]
            module=root/'integrations/companion-module-usb-storage-watch/src/client.js'
            script=m.root/'verify.mjs'
            script.write_text('''import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Client} from '''+json.dumps(module.as_uri())+''';
const fixture=JSON.parse(readFileSync(process.argv[2],'utf8')), logs=[];
const client=new Client(fixture,fixture.token,row=>logs.push(row));
try {
  const info=await client.request('integration-info');
  assert.equal(info.certificate_pem,fixture.ca);
  assert.equal(info.module.version,'0.2.6');
  for(const endpoint of ['session','fleet-status','docker-overview']) await client.request(endpoint);
  for(const endpoint of ['companion/v1/status','companion-token','standby-token','sleep-hdd'])
    await assert.rejects(()=>client.request(endpoint),e=>e.request.http_status===404);
  assert(logs.every(r=>r.tls_verified));
  assert.equal(logs.filter(r=>r.method==='POST').length,1); // Login only.
  assert(!JSON.stringify(logs).includes(fixture.token));
  console.log('PASS unchanged Companion 0.2.6 client: verified TLS, management login, independent status reads, complete public CA/module info, retired routes 404; no command requests.');
} finally {client.close();}
''')
            conf=m.root/'fixture.json';conf.write_text(json.dumps(dict(url=url,ca=cert.read_text(),token=token)));conf.chmod(0o600)
            subprocess.run([node,str(script),str(conf)],check=True,timeout=35)
            assert before==m.config.with_name('management-token.json').read_bytes()
        finally:
            proc.terminate();proc.join(8)
    finally:with_machine.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--node',required=True);run(p.parse_args().node)
