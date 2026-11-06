# SPDX-License-Identifier: MIT
"""Real module HTTP/session/broker/worker path with isolated simulated storage/Docker."""
import copy,json,os,shutil,subprocess,sys,threading,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tests'))
from werkzeug.serving import make_server,WSGIRequestHandler
from test_ui33_unmount import RepeatedUnmount,ID,OTHER,PHOTO
NODE=os.environ.get('USW_NODE') or shutil.which('node')
class Quiet(WSGIRequestHandler):
 def log_request(self,*_):pass
class ModuleBroker(unittest.TestCase):
 def scenario(self,mode):
  if not NODE:self.skipTest('Set USW_NODE to Node 26 for module integration checks')
  f=RepeatedUnmount();f.setUp();self.addCleanup(f.doCleanups);
  if not mode.startswith('sleep-'):f.earlier_unmount_then_remount_and_add_app()
  else:
   real=f.b.common.module('engine');original_worker=real.Worker
   def worker(argv,payload,timeout,**kwargs):
    self.assertEqual(payload['action'],'sleep');result=original_worker([sys.executable,'-I',str(Path(__file__).with_name('sleep_worker_fixture.py')),str(f.m.root),mode],payload,15,**kwargs);f.started_workers.append(result.proc.pid);return result
   f.m.patch(f.b.w,'Worker',worker)
  saved=f.b.s.CONFIG.read_bytes();token=f.m.management_token();requests=[]
  if mode=='stop-failure':f.fail_stop=True
  if mode=='busy-storage':(f.m.root/'busy-storage').touch()
  def transport(req):
   action=req['action']
   if action=='fleet-status':return dict(status=200,data=dict(drives=[dict(configured=True,profile_id='legacy',uuid=f.m.uuid,name='Synthetic drive',mountpoint=f.b.configuration()['disk']['mountpoint'],connected=True,mount_state='mounted',monitoring='active',progress=dict(phase='done',code='healthy'))]))
   if action=='docker-overview':return dict(status=200,data=dict(inventory_ok=True,containers=[dict(id=v['id'],name=v['name'],state='running' if v['running'] else 'stopped',discovered=True,control_block='') for v in f.runtime.values()],applications=dict(revision='synthetic',settings=[])))
   if action in ('disk-operation','docker-container-action'):
    requests.append(action)
    if mode=='stale':f.rows[0]['id']='new-mount'
    if mode=='recovery':f.b.cli.save(f.b.s.STATE_DIR/'state.json',dict(incident=dict(phase='wait1',control_ids=[ID,PHOTO])))
   return f.m.broker.handle(req)
  # Allocate a loopback port, then create Flask's exact-origin allowlist for it.
  import socket
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  app=f.m.web.create_app(dict(f.b.common.DEFAULT,port=port),transport);server=make_server('127.0.0.1',port,app,threaded=True,request_handler=Quiet);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  code='''import {Client} from './src/client.js';import {Controller} from './src/controller.js';let input='';for await(const v of process.stdin)input+=v;const x=JSON.parse(input);const c=new Controller(new Client({url:x.url},x.token));let result;try{try{await c.execute(x.kind,x.id,x.action,x.uuid);result={ok:true}}catch(e){result={ok:false,error:e.message}}await c.refresh();result.pending=c.pending}finally{c.dispose()}console.log(JSON.stringify(result));'''
  value=dict(uuid=f.m.uuid,url=f'http://127.0.0.1:{port}',token=token,kind='app' if mode=='recovery' else 'drive',id=ID if mode=='recovery' else 'legacy',action='sleep' if mode.startswith('sleep-') else 'stop' if mode=='recovery' else 'unmount')
  result=subprocess.run([NODE,'--input-type=module','-e',code],input=json.dumps(value),text=True,capture_output=True,cwd=Path(__file__).resolve().parents[1],timeout=25);self.assertEqual(result.returncode,0,result.stderr);out=json.loads(result.stdout);self.assertIsNone(out['pending']);self.assertEqual(len(requests),1)
  self.assertTrue(f.runtime[OTHER]['running']);self.assertEqual(f.b.s.CONFIG.read_bytes(),saved)
  if mode.startswith('sleep-'):
   events=(f.m.root/'sleep-events').read_text().splitlines();self.assertEqual(len(f.started_workers),1);self.assertTrue(f.m.active);self.assertEqual(f.events,[])
   if mode=='sleep-success':self.assertTrue(out['ok'],out);self.assertEqual(events,['users','sync','users','-y','-C'])
   else:self.assertFalse(out['ok'],out);self.assertNotIn('-y',events);self.assertIn('holds the drive' if mode=='sleep-busy' else 'did not settle',out['error'])
  elif mode=='success':
   self.assertTrue(out['ok'],out);self.assertEqual(len(f.started_workers),2);self.assertEqual(f.events,['stop:'+ID,'stop:'+PHOTO]);self.assertEqual((f.m.root/'worker-events').read_text().splitlines(),['users','verify:image','unmount:image','sync','unmount:disk']);self.assertEqual(set(f.receipt()['held_ids']),{ID,PHOTO})
  else:
   self.assertFalse(out['ok'],out)
   if mode in ('stale','recovery'):self.assertEqual(f.events,[]);self.assertEqual(len(f.started_workers),1)
   if mode=='stop-failure':self.assertEqual(f.events,['stop:'+ID]);self.assertEqual(len(f.started_workers),1);self.assertIn('HTTP 403',out['error']);self.assertNotIn('secret',out['error'])
   if mode=='busy-storage':self.assertEqual((f.m.root/'worker-events').read_text().splitlines(),['users']);self.assertIn('unrelated process',out['error'])
 def test_manual_sleep_now(self):self.scenario('sleep-success')
 def test_manual_sleep_busy_users(self):self.scenario('sleep-busy')
 def test_manual_sleep_writes_do_not_settle(self):self.scenario('sleep-writes')
 def test_repeat_unmount_after_remount_explicit_starts_added_folder_app(self):self.scenario('success')
 def test_stopping_failure_prevents_storage_worker(self):self.scenario('stop-failure')
 def test_changed_mount_after_review_is_refused(self):self.scenario('stale')
 def test_recovery_begun_after_client_read_blocks_stale_confirm(self):self.scenario('recovery')
 def test_worker_busy_storage_refusal_preserves_unrelated_users(self):self.scenario('busy-storage')
if __name__=='__main__':unittest.main()
