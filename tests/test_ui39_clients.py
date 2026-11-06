# SPDX-License-Identifier: MIT
"""Production UI and unchanged Companion client; only fixture storage/Docker.

The browser routes status fixtures locally and sends commands through real
authenticated Flask/broker handlers. Companion uses a verified localhost HTTPS
listener with real authentication, CSRF and the same manual backend.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler
from flask import request, jsonify
from test_ui39_manual_storage import ManualStorage, ID
from test_ui30_browser import API, ROOT, CSP


def browser_checks():
    shots=Path(os.environ.get('USW_UI39_SCREENSHOTS','/tmp/usw-ui39-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,768,1440):
            f=ManualStorage();f.setUp()
            try:
                f.mode='directory';held=f.hold();before=held.read_bytes();api=API();errors=[];reads=[0];read_failure=[False]
                api.containers[0].update(name='erugo',state='stopped')
                for app in api.apps:
                    if app['id']==ID:app['name']='erugo'
                context=browser.new_context(viewport=dict(width=width,height=1000),has_touch=True)
                def serve(route):
                    req=route.request;path=urlsplit(req.url).path;headers={'Content-Security-Policy':CSP}
                    if path=='/api/docker-container-action':
                        r=f.http.post(path,base_url='http://127.0.0.1:8765',headers=f.headers,json=req.post_data_json)
                        api.containers[0]['state']='running' if f.docker.current['running'] else 'stopped'
                        route.fulfill(status=r.status_code,json=r.json,headers=headers);return
                    if path.startswith('/api/'):
                        if path.endswith('docker-overview'):
                            reads[0]+=1
                            if read_failure[0]:route.fulfill(status=503,json=dict(error='Synthetic status unavailable'),headers=headers);return
                        r=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None))
                        route.fulfill(status=r['status'],json=r['body'],headers=headers);return
                    name='index.html' if path=='/' else path.removeprefix('/static/')
                    assert name in ('index.html','app.js','network.js','style.css','icon.svg','select-arrow.svg')
                    route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
                context.route('**/*',serve);page=context.new_page();page.set_default_timeout(8000);page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:8765/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap()
                page.wait_for_selector('[data-drive-card]');page.evaluate('()=>navigate("apps")')
                page.wait_for_function('()=>!apiBusy&&!routeLoading&&lastLoadedRoute==="apps"')
                card=page.locator('[data-container-id="'+ID+'"]')
                toggle=card.locator('[data-action="docker-collapse"]')
                if toggle.get_attribute('aria-expanded')!='true':toggle.tap()
                result=card.locator('[data-docker-control-status]')
                card.locator('[data-action="docker-start"]').tap()
                expect(result).to_contain_text('Expected mount is missing')
                expect(result).to_contain_text('No Docker command was sent')
                assert not f.docker.posts and held.read_bytes()==before
                # A stale browser offers Restart, but backend storage refusal precedes any stop.
                api.containers[0]['state']='running';f.docker.current['running']=True
                page.locator('[data-action="applications-refresh"]').tap()
                expect(card.locator('.docker-live-state')).to_contain_text('Running')
                card.locator('[data-action="docker-restart"]').tap()
                page.locator('#modal-root [data-action="confirmed-action"]').tap()
                expect(result).to_contain_text('Expected mount is missing');assert not f.docker.posts
                # Healthy explicit start succeeds; later failed status reads do not rewrite its result.
                api.containers[0]['state']='stopped';f.docker.current['running']=False;f.mode='ready'
                page.locator('[data-action="applications-refresh"]').tap()
                expect(card.locator('[data-action="docker-start"]')).to_be_enabled()
                card.locator('[data-action="docker-start"]').tap();expect(result).to_contain_text('Container is running.')
                assert len(f.docker.posts)==1
                read_failure[0]=True;page.locator('[data-action="applications-refresh"]').tap()
                expect(page.locator('body')).to_contain_text('Synthetic status unavailable')
                expect(result).to_contain_text('Container is running.');assert len(f.docker.posts)==1
                assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(shots/f'ui39-{width}.png'),full_page=True)
                context.close();print('PASS dashboard',width,'px: backend refusal, retained hold, restart-before-stop protection, confirmed result survives failed status read.',flush=True)
            finally:f.doCleanups()
        browser.close()


class Quiet(WSGIRequestHandler):
    def log_request(self,*_):pass


def companion_checks(node):
    f=ManualStorage();f.setUp();server=None
    try:
        root=f.f.main.root;cert=root/'ca.pem';key=root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=Fixture','-addext','subjectAltName=IP:127.0.0.1'],check=True,timeout=15,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        failed_reads=[False];commands=[];f.mode='missing';held=f.hold();before=held.read_bytes()
        def transport(req):
            action=req['action']
            if action in ('fleet-status','docker-overview'):
                if failed_reads[0]:return dict(status=503,error='Synthetic status unavailable')
                if action=='fleet-status':return dict(status=200,data=dict(drives=[]))
                return dict(status=200,data=dict(inventory_ok=True,containers=[dict(id=ID,name='erugo',state='running' if f.docker.current['running'] else 'stopped',discovered=True,control_block='')]))
            result=f.f.main.broker.handle(req)
            if action=='docker-container-action':
                commands.append(req['data']['action'])
                if result['status']==200:failed_reads[0]=True
                else:assert held.read_bytes()==before
            return result
        config=dict(f.b.common.DEFAULT,lan=True,address_mode='automatic',scheme='https',address='127.0.0.1',hostname='127.0.0.1',port=port)
        app=f.f.main.web.create_app(config,transport)
        @app.post('/api/fixture')
        def fixture():
            f.mode=request.json['mode'];failed_reads[0]=False
            return jsonify(ok=True)
        server=make_server('127.0.0.1',port,app,threaded=True,ssl_context=(str(cert),str(key)),request_handler=Quiet)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        project=Path(__file__).resolve().parents[1];module=project/'integrations/companion-module-usb-storage-watch/src'
        script=root/'check.mjs'
        script.write_text('''import assert from 'node:assert/strict';
import {Client} from '''+json.dumps((module/'client.js').as_uri())+''';
import {Controller,values} from '''+json.dumps((module/'controller.js').as_uri())+''';
let input='';for await(const part of process.stdin)input+=part;const x=JSON.parse(input),logs=[];
const client=new Client(x,x.token,row=>logs.push(row)),c=new Controller(client);
try {
 await assert.rejects(()=>c.execute('app',x.id,'start'),/required filesystem/);
 assert.equal(values(c).result_label,'Refused');assert.equal(values(c).connected,'yes');
 await client.request('fixture',{mode:'ready'});
 await c.execute('app',x.id,'start');
 assert.equal(values(c).result_label,'Completed');assert.equal(values(c).status_fresh,'no');
 await client.request('fixture',{mode:'ready'});await c.refresh();assert.equal(values(c).result_label,'Completed');
 assert(logs.every(v=>v.tls_verified));assert(!JSON.stringify(logs).includes(x.token));
 assert.equal(logs.filter(v=>v.method==='POST'&&v.endpoint==='/api/docker-container-action').length,2);
 console.log('PASS unchanged Companion 0.2.6 client/controller over verified HTTPS: shared backend refusal, real management/session/CSRF path, confirmed result survives failed status reads, no replay.');
} finally {c.dispose();}
''')
        subprocess.run([node,str(script)],input=json.dumps(dict(url=f'https://127.0.0.1:{port}',ca=cert.read_text(),token=f.f.main.management_token(),id=ID)),text=True,check=True,timeout=35)
        assert commands==['start','start'] and len(f.docker.posts)==1
    finally:
        if server:server.shutdown();server.server_close()
        f.doCleanups()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--node',required=True);p.add_argument('--companion-only',action='store_true');args=p.parse_args()
    if not args.companion_only:browser_checks()
    companion_checks(args.node)
