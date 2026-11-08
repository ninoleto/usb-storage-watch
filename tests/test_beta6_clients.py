"""Real localhost browser/broker and verified-TLS Companion client; synthetic storage."""
import argparse,io,json,os,subprocess,threading
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import Mock
from werkzeug.serving import make_server,WSGIRequestHandler
from playwright.sync_api import sync_playwright,expect
from test_ui39_manual_storage import ManualStorage
from test_ui30_browser import API,ROOT,CSP

class Quiet(WSGIRequestHandler):
    def log(self,*a,**kw):pass

class Host:
    def __init__(self):
        self.f=ManualStorage();self.f.setUp();self.m=self.f.f.main;self.b=self.f.b;w=self.b.w
        self.mode='idle';self.sent=[];self.requests=[];root=self.m.root/'power';root.mkdir();(root/'dev').write_text('240:0');(root/'node').touch()
        self.binding=dict(sys=str(root),path=str(root/'node'),devs=['240:0','240:1'])
        self.m.patch(w.standby,'identity',lambda _:self.binding)
        self.m.patch(w.standby,'storage_kind',lambda *_:'mechanical')
        self.m.patch(w.standby,'status',lambda _:dict(sleeping=False,applicable=True,state='idle',label='Idle'))
        self.m.patch(w.standby.io,'topology',lambda *_:dict(devices=['240:0','240:1'],loops={},mounts=[],targets=['/fixture/image','/fixture/disk']))
        self.m.patch(w.standby.io,'swap_guard',lambda *_:None)
        self.m.patch(w.standby.io,'capture',lambda *_:dict(available=False,containers={}))
        self.m.patch(w.standby,'activity',lambda _:([0]*14,1 if self.mode=='busy' else 0))
        self.m.patch(w.standby,'users',Mock(side_effect=AssertionError('Standby scanned consumers')))
        self.m.patch(w.standby,'power_command',lambda _,flag,path:self.sent.append(flag) or 'drive state is: standby')
        self.m.patch(w.usb,'load',lambda _:None)
        self.context=lambda: w.usb_context(self.m.state)
        host=self
        class Worker:
            def __init__(self,argv,data,*a,**kw):
                assert data['action']=='sleep';host.requests.append(data['action'])
                ctx=host.context();ctx.assert_internal_state=lambda:None;ctx.snapshot=lambda:dict(healthy=True)
                ctx.command=lambda argv,**kw:None;ctx.device_number=lambda _:'240:0';ctx.WORKER_LOCK_FDS=()
                try: result=dict(ok=True,result='success',message=w.controls.perform(ctx,'sleep'))
                except w.Unsafe as e:result=dict(ok=False,result=w.standby.error_result(e),message=str(e))
                self.output=io.BytesIO(json.dumps(result).encode())
            def poll(self):return True
            def cancel(self):pass
            def close(self):pass
        self.m.patch(w,'Worker',Worker)
        self.uuid=self.b.configuration()['disk']['uuid']
    def close(self):self.f.doCleanups()

def browser_checks():
    shots=Path(os.environ.get('USW_BETA6_SHOTS','/tmp/usw-beta6-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,768,1440):
            h=Host();api=API();errors=[]
            try:
                context=browser.new_context(viewport=dict(width=width,height=1100),has_touch=True)
                def serve(route):
                    req=route.request;path=urlsplit(req.url).path;headers={'Content-Security-Policy':CSP}
                    if path.endswith('/drive-activity'):
                        # Real authenticated read endpoint; mock only kernel/Docker observations.
                        result=h.f.http.get('/api/drives/legacy/drive-activity',base_url='http://127.0.0.1:8765')
                        route.fulfill(status=result.status_code,json=result.json,headers=headers);return
                    if path.endswith('/disk-operation'):
                        result=h.f.http.post('/api/drives/legacy/disk-operation',base_url='http://127.0.0.1:8765',headers=h.f.headers,json=dict(action='sleep',uuid=h.uuid))
                        route.fulfill(status=result.status_code,json=result.json,headers=headers);return
                    if path.startswith('/api/'):
                        r=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None))
                        route.fulfill(status=r['status'],json=r['body'],headers=headers);return
                    name='index.html' if path=='/' else path.removeprefix('/static/')
                    route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
                context.route('**/*',serve);page=context.new_page();page.set_default_timeout(20000);page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:8765');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap()
                page.wait_for_selector('[data-drive-card]');page.locator('[data-action="manage-drive"]').first.tap()
                page.locator('[data-action="drive-activity"]').tap();expect(page.locator('.drive-activity')).to_contain_text('Unattributed physical activity')
                expect(page.locator('.drive-activity')).to_contain_text('inventory incomplete')
                # Render measured, idle and unavailable rows from tested accounting output schema.
                page.evaluate('''()=>{const d=configured()[0],v=driveActivitySamples.get(d.id).value;v.containers=[
                {name:'long_application_name_with_64_characters_for_a_narrow_button_layout',state:'observed activity',read_bytes_per_second:1048576,write_bytes_per_second:0,interval_seconds:2,basis:'physical'},
                {name:'idle app',state:'access configured; no activity observed',read_bytes_per_second:0,write_bytes_per_second:0,interval_seconds:2,basis:'physical'},
                {name:'unknown app',state:'measurement unavailable',read_bytes_per_second:null,write_bytes_per_second:null}];render();}''')
                expect(page.locator('.drive-activity')).to_contain_text('long_application_name_with_64_characters_for_a_narrow_button_layout');expect(page.locator('.drive-activity')).to_contain_text('measurement unavailable')
                page.locator('[data-action="sleep-hdd"]').tap();expect(page.locator('[role="dialog"]')).to_contain_text('Applications stay running')
                page.locator('[data-action="confirmed-action"]').tap();expect(page.locator('body')).to_contain_text('applications remain running')
                assert h.requests==['sleep'] and h.sent==['-y','-C'] and not h.f.docker.posts
                assert not errors,errors
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(shots/f'standby-{width}.png'),full_page=True)
                context.close();print('PASS browser',width,'px; real authenticated broker/lock/standby guards, simulated storage/power; no Docker mutations',flush=True)
            finally:h.close()
        browser.close()

def companion(node):
    h=Host();server=None;thread=None
    try:
        cert=h.m.root/'ca.pem';key=h.m.root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=Fixture','-addext','subjectAltName=IP:127.0.0.1'],check=True,timeout=15,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def transport(req):
            if req['action']=='fleet-status':return dict(status=200,data=dict(drives=[dict(id='legacy',profile_id='legacy',configured=True,name='Test HDD',uuid=h.uuid,known=True,connected=True,mount_state='mounted',monitoring=True,standby=dict(state='idle'))]))
            if req['action']=='docker-overview':return dict(status=200,data=dict(inventory_ok=True,containers=[]))
            return h.m.broker.handle(req)
        server=make_server('127.0.0.1',0,lambda e,s:[],threaded=True,ssl_context=(str(cert),str(key)),request_handler=Quiet)
        config=dict(h.b.common.DEFAULT,lan=True,address_mode='automatic',scheme='https',address='127.0.0.1',hostname='127.0.0.1',port=server.server_port)
        server.app=h.m.web.create_app(config,transport)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        module=Path(__file__).resolve().parents[1]/'integrations/companion-module-usb-storage-watch/src'
        script=h.m.root/'check.mjs'
        script.write_text("import assert from 'node:assert/strict';\n"+'import {Client} from '+json.dumps((module/'client.js').as_uri())+';\nimport {Controller,values} from '+json.dumps((module/'controller.js').as_uri())+''';
let input='';for await(const p of process.stdin)input+=p;const x=JSON.parse(input),logs=[];
const c=new Controller(new Client(x,x.token,r=>logs.push(r)));
try{if(x.busy)await assert.rejects(()=>c.execute('drive','legacy','sleep',x.uuid),/did not settle/);else await c.execute('drive','legacy','sleep',x.uuid);assert.equal(values(c).result_label,x.busy?'Refused':'Completed');
assert(c.message.includes(x.busy?'did not settle':'applications remain running'));assert(logs.every(v=>v.tls_verified));
assert.equal(logs.filter(v=>v.method==='POST'&&v.endpoint.endsWith('/disk-operation')).length,1);
console.log('PASS Companion production client verified TLS/auth/CSRF, single request, '+values(c).result_label);
}finally{c.dispose();}''')
        token=h.m.management_token()
        for mode in ('idle','busy'):
            h.mode=mode
            subprocess.run([node,str(script)],input=json.dumps(dict(url=f'https://127.0.0.1:{server.server_port}',ca=cert.read_text(),token=token,uuid=h.uuid,busy=mode=='busy')),text=True,check=True,timeout=40)
        assert h.requests==['sleep','sleep'] and h.sent==['-y','-C'] and not h.f.docker.posts
    finally:
        if server:
            if thread:server.shutdown()
            server.server_close()
        h.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--node',required=True);p.add_argument('--companion-only',action='store_true');args=p.parse_args()
    if not args.companion_only:browser_checks()
    companion(args.node)
