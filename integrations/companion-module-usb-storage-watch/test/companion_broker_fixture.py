# SPDX-License-Identifier: MIT
"""Actual Companion -> authenticated web/broker -> real worker IPC with fake OS.
Disposable test configuration only. No production Docker/storage/service calls.
"""
import copy,json,os,sqlite3,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tests'))
from flask import request,jsonify
from werkzeug.serving import make_server,WSGIRequestHandler
from test_ui33_unmount import RepeatedUnmount,ID,OTHER,PHOTO
from gui_fixture import load
class Quiet(WSGIRequestHandler):
 def log_request(self,*_):pass
f=RepeatedUnmount();f.setUp();f.earlier_unmount_then_remount_and_add_app();b=f.b;root=f.m.root
(root/'original-rows.json').write_text(json.dumps(f.rows));token=f.m.management_token()
controls=dict(sleep_mode='sleep-success',delay=0,fail_stop=False,race=False,drive_patch={},app_patch={})
workers=[];requests=[];docker_calls=[];standby='active'
real=load('engine');original_worker=real.Worker;original_post=f.post
# Existing fake Docker boundary; record the exact backend requests.
def docker(method,path,**kw):
 docker_calls.append(path);result=original_post(method,path,**kw)
 if '/stop?' not in path:f.runtime[path.split('/')[2]]['started_at']='fixture-start-'+str(len(docker_calls))
 return result
f.docker.request=docker
def worker(argv,payload,timeout,**kw):
 action=payload['action'];time.sleep(controls['delay'])
 (root/'rows.json').write_text(json.dumps(f.rows));(root/'runtime.json').write_text(json.dumps(f.runtime))
 script=ROOT/'tests/unmount_worker_fixture.py' if action=='unmount' else Path(__file__).with_name('sleep_worker_fixture.py' if action=='sleep' else 'mount_worker_fixture.py')
 args=[sys.executable,'-I',str(script),str(root)]+([controls['sleep_mode']] if action=='sleep' else [])
 result=original_worker(args,payload,15,**kw);workers.append(dict(action=action,pid=result.proc.pid));return result
f.m.patch(b.w,'Worker',worker)
def drive():
 return dict(configured=True,profile_id='legacy',uuid=f.m.uuid,name='Fixture Toshiba',mountpoint=b.configuration()['disk']['mountpoint'],connected=True,mount_state='mounted' if f.rows else 'unmounted',monitoring='active' if f.m.active else 'inactive',standby=dict(state=standby,applicable=True,sleeping=standby=='standby'),progress=dict(code='healthy',phase='done')) | controls['drive_patch']
def transport(req):
 global standby
 action=req['action']
 if action=='fleet-status':return dict(status=200,data=dict(drives=[drive()]))
 if action=='docker-overview':return dict(status=200,data=dict(inventory_ok=True,containers=[dict(id=v['id'],name=v['name'],state='running' if v['running'] else 'stopped',discovered=True,control_block='') | controls['app_patch'].get(v['id'],{}) for v in f.runtime.values()],applications=dict(revision='fixture',settings=[])))
 if action in ('disk-operation','docker-container-action','monitor'):
  requests.append(dict(action=action,data={k:v for k,v in req.get('data',{}).items() if k!='token'}))
  if controls['race']:b.cli.save(b.s.STATE_DIR/'state.json',dict(incident=dict(phase='wait1',control_ids=[ID,PHOTO])))
  f.fail_stop=controls['fail_stop']
 result=f.m.broker.handle(req)
 if action=='disk-operation':
  if (root/'rows.json').exists():f.rows=json.loads((root/'rows.json').read_text());f.m.current=b.configuration()['disk']['mountpoint'] if f.rows else ''
  if result.get('data',{}).get('ok') and req['data']['action']=='sleep':standby='standby'
 return result
app=f.m.web.create_app(dict(b.common.DEFAULT,port=8765),transport)
@app.route('/fixture',methods=['GET','POST'])
def fixture():
 if request.method=='POST':
  data=request.get_json();assert set(data)<=set(controls);controls.update(data)
  if not controls['race']:b.cli.save(b.s.STATE_DIR/'state.json',{})
 return jsonify(marker='usw-direct-real-broker-fixture',drive=drive(),apps=f.runtime,workers=workers,requests=requests,docker_calls=docker_calls,unmount_events=(root/'worker-events').read_text() if (root/'worker-events').exists() else '',sleep_events=(root/'sleep-events').read_text() if (root/'sleep-events').exists() else '',mount_events=(root/'mount-events').read_text() if (root/'mount-events').exists() else '',receipt=f.receipt(),controls=controls)
if __name__=='__main__':
 # Seed only this disposable Companion database with this isolated API's token.
 database=Path(os.environ['COMPANION_FIXTURE_DB']).resolve();assert 'companion-direct' in database.parts
 db=sqlite3.connect(database)
 for identity,raw in db.execute('SELECT id,value FROM instances').fetchall():
  conf=json.loads(raw);conf.update(config=dict(url='http://127.0.0.1:8765',ca=''),secrets=dict(token=token),moduleVersionId='dev');db.execute('UPDATE instances SET value=? WHERE id=?',(json.dumps(conf),identity))
 db.commit();db.close()
 server=make_server('127.0.0.1',8765,app,threaded=True,request_handler=Quiet);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:raise SystemExit(subprocess.call(sys.argv[1:]))
 finally:server.shutdown();f.doCleanups()
