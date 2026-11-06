# SPDX-License-Identifier: MIT
"""Production Gunicorn/TLS + real guarded broker, with simulated OS boundaries.
Requires a private fixture-only marker and generated TLS files. Never a live DB.
"""
import json,multiprocessing,os,socket,sqlite3,ssl,subprocess,sys,time,urllib.request
from pathlib import Path
from types import SimpleNamespace
import companion_broker_fixture as h
from flask import request
h.controls.update(fault='',fault_active=False)
config=dict(h.b.common.DEFAULT,address_mode='automatic',lan=True,scheme='https',address='127.0.0.1',hostname='127.0.0.1',port=8765)
app=h.f.m.web.create_app(config,h.transport)
app.route('/fixture',methods=['GET','POST'])(h.fixture)
@app.after_request
def response_fault(response):
 endpoint=request.path.split('/')[-1];fault=h.controls['fault']
 if request.method=='POST' and endpoint in ('disk-operation','monitor','docker-container-action'):
  h.controls['fault_active']=True
  if fault!='post-reset':return response
 elif not h.controls['fault_active']:return response
 elif endpoint=='fleet-status' and fault=='fleet-json':
  response.set_data('deliberately invalid JSON');return response
 elif endpoint=='fleet-status' and fault=='fleet-timeout':
  time.sleep(8.5);return response
 elif not ((endpoint=='fleet-status' and fault=='fleet-reset') or (endpoint in ('fleet-status','docker-overview','session') and fault=='all-reset')):
  return response
 # The operation has already completed; fault injection affects its response or
 # read-only status responses only. Production backend code is unchanged.
 connection=request.environ['gunicorn.socket'];connection.shutdown(socket.SHUT_RDWR);connection.close()
 return response

def run():
 tls=Path(os.environ['TLS_FIXTURE_DIR']).resolve();database=Path(os.environ['COMPANION_FIXTURE_DB']).resolve()
 assert (database.parent.parent/'fixture-only').read_text().strip()=='usw-companion-fixture'
 db=sqlite3.connect(database)
 for identity,raw in db.execute('SELECT id,value FROM instances').fetchall():
  conf=json.loads(raw);conf.update(config=dict(url='https://127.0.0.1:8765',ca=(tls/'certificate.pem').read_text()),secrets=dict(token=h.token),moduleVersionId='dev');db.execute('UPDATE instances SET value=? WHERE id=?',(json.dumps(conf),identity))
 db.commit();db.close()
 def server():
  web=h.f.m.web;web.listener_config=lambda _: (config,'');web.common.WEB_DIR=tls;web.create_app=lambda _:app
  original=web.common.module
  web.common.module=lambda name:SimpleNamespace(discover=lambda:[],choose=lambda *_:dict(address='127.0.0.1')) if name=='network_addresses' else original(name)
  sys.argv=['web.py','--lan'];web.main()
 proc=multiprocessing.get_context('fork').Process(target=server);proc.start()
 try:
  context=ssl.create_default_context(cafile=str(tls/'certificate.pem'))
  for _ in range(80):
   try:
    with urllib.request.urlopen('https://127.0.0.1:8765/fixture',context=context,timeout=1) as response:assert json.load(response)['marker']=='usw-direct-real-broker-fixture'
    break
   except OSError:time.sleep(.1)
  else:raise RuntimeError('TLS fixture did not start')
  return subprocess.call(sys.argv[1:])
 finally:proc.terminate();proc.join(8);h.f.doCleanups()
if __name__=='__main__':raise SystemExit(run())
