# SPDX-License-Identifier: MIT
"""Synthetic API for placed-button tests in a loopback-only Companion instance.
Never accesses host storage, Docker, email, credentials or services.
"""
import copy,json,subprocess,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
TOKEN='usw_'+'s'*43
DRIVE=dict(configured=True,profile_id='drive-a',uuid='11111111-1111-4111-8111-111111111111',name='Archive Toshiba',connected=True,mount_state='mounted',monitoring='active',standby=dict(state='active',applicable=True,sleeping=False),progress=dict(code='healthy',phase='done'))
APPS=[dict(id=c*64,name=n,state='running',discovered=True,control_block='') for c,n in [('a','Gallery'),('b','Media files'),('c','Unrelated app')]]
state=dict(drive=DRIVE,apps=APPS,writes=[],refusal='',delay=0,inventory_ok=True,revision='1')
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*_):pass
 def send(self,status,obj):
  body=json.dumps(obj).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Set-Cookie','usw_session=fixture; HttpOnly; SameSite=Strict');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_GET(self):self.route()
 def do_POST(self):self.route()
 def route(self):
  data=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or '{}');path=self.path
  if path=='/fixture':
   if self.command=='POST':
    for k,v in data.items():
     if k=='drive':state[k].update(v)
     else:state[k]=v
   return self.send(200,copy.deepcopy(state))
  if path=='/api/login':return self.send(200,dict(csrf='fixture-csrf')) if data.get('management_token')==TOKEN else self.send(401,dict(error='Invalid token'))
  if self.headers.get('Cookie')!='usw_session=fixture' or self.headers.get('X-CSRF-Token')!='fixture-csrf':return self.send(401,dict(error='Session required'))
  if path=='/api/fleet-status':return self.send(200,dict(drives=[copy.deepcopy(state['drive'])]))
  if path=='/api/docker-overview':return self.send(200,dict(inventory_ok=state['inventory_ok'],containers=state['apps'],applications=dict(revision=state['revision'],settings=[dict(id=a['id'],boot=dict(enabled=True),recovery=dict(enabled=True)) for a in state['apps']])))
  if path.startswith('/api/drives/drive-a/unmount-plan?'):return self.send(200,dict(token='one-use-review',apps=[dict(id=a['id'],name=a['name'],running=a['state']=='running',images=['files'] if i==0 else []) for i,a in enumerate(state['apps'][:2])],message='Apps stay stopped; monitoring stops.'))
  if self.command!='POST':return self.send(404,dict(error='Unsupported fixture route'))
  state['writes'].append(dict(path=path,data=data));time.sleep(state['delay'])
  if state['refusal']:return self.send(200,dict(ok=False,result='busy',message=state['refusal']))
  if path=='/api/drives/drive-a/disk-operation':
   if data.get('uuid')!=DRIVE['uuid']:return self.send(400,dict(error='Wrong identity'))
   action=data.get('action')
   if action=='sleep':state['drive']['standby']=dict(state='standby',applicable=True,sleeping=True);message='HDD standby confirmed. Filesystem remains mounted; monitoring unchanged.'
   elif action=='unmount' and data.get('token')=='one-use-review':state['drive']['mount_state']='unmounted';state['drive']['monitoring']='inactive';message='Apps stopped and filesystem unmounted.'
   elif action=='mount':state['drive']['mount_state']='mounted';message='Filesystem mounted; apps remain stopped.'
   else:return self.send(400,dict(error='Unknown operation or missing review'))
  elif path=='/api/drives/drive-a/monitor':state['drive']['monitoring']='active' if data['enabled'] else 'inactive';message='Monitoring updated.'
  elif path=='/api/docker-container-action':
   app=next((a for a in state['apps'] if a['id']==data.get('id')),None)
   if not app or app['name']!=data.get('name') or app['control_block']:return self.send(400,dict(error='Identity or recovery protection refused'))
   app['state']='stopped' if data['action']=='stop' else 'running';message='App '+app['state']+' verified.'
  else:return self.send(404,dict(error='Unsupported fixture write'))
  self.send(200,dict(ok=True,message=message))
if __name__=='__main__':
 server=ThreadingHTTPServer(('127.0.0.1',8765),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 if len(sys.argv)>1:raise SystemExit(subprocess.call(sys.argv[1:]))
 threading.Event().wait()
