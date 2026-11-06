"""Real Chromium network handoff plus responsive controls; all APIs are synthetic."""
import copy
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
from test_ui11_browser import API as PriorAPI,ROOT

class API(PriorAPI):
    def __init__(self):
        super().__init__();self.saved=dict(lan=True,address='192.168.50.2',hostname='192.168.50.2',scheme='http',port=8765,http_port=8765,https_port=8766)
        self.transaction=dict(phase='idle',message='Current settings saved.');self.cert=False;self.network_calls=[];self.next=0;self.finish_reads=0;self.reject=False
    def url(self,c,local=False):return 'http://127.0.0.1:'+str(c['http_port']) if local or not c['lan'] else c['scheme']+'://'+c['address']+':'+str(c[c['scheme']+'_port'])
    def reply(self,req):
        action=req['url'].split('/api/',1)[-1].split('?')[0];data=req.get('data') or {}
        if action.startswith('network-') and self.session:
            self.calls.append((req['method'],None,action,data));self.network_calls.append((action,data))
            def ok(body):return dict(status=200,body=copy.deepcopy(body))
            def fail(message):return dict(status=409,body=dict(error=message))
            if action=='network-state':
                if self.transaction['phase'] in ('committing','cancelling'):
                    self.finish_reads+=1
                    if self.finish_reads>=2:
                        if self.transaction['phase']=='committing':self.saved=copy.deepcopy(self.transaction['config']);self.transaction.update(phase='complete',message='Connection confirmed and network settings saved.')
                        else:self.transaction.update(phase='cancelled',message='Change cancelled. Previous settings retained.')
                return ok(dict(config=self.saved,url=self.url(self.saved) if self.saved['lan'] else None,local_url=self.url(self.saved,True),addresses=[dict(address='192.168.50.2',interface='enp1s0'),dict(address='192.168.50.3',interface='enp2s0')],transaction=self.transaction,certificate=dict(available=self.cert,fingerprint='SYNTHETIC PUBLIC FINGERPRINT' if self.cert else ''),recovery_error=''))
            if action=='network-certificate':self.cert=True;return ok(dict(available=True,fingerprint='SYNTHETIC PUBLIC FINGERPRINT'))
            if action=='network-stage':
                if self.reject:return fail('Synthetic occupied port; previous settings retained.')
                self.next+=1;cfg=dict(data,hostname=data['address'],port=data[data['scheme']+'_port'])
                self.transaction=dict(operation='synthetic-'+str(self.next),phase='pending',message='Waiting for confirmation. Current access stays available.',seconds_left=180,url=self.url(cfg),local_url=self.url(cfg,True),config=cfg,previous=copy.deepcopy(self.saved))
                return ok(self.transaction)
            if action=='network-confirm':
                parsed=urlsplit(req['url']);origin=parsed.scheme+'://'+parsed.netloc
                if origin!=self.transaction['url']:return fail('Open and confirm from the proposed connection.')
                self.transaction.update(phase='committing',message='Connection confirmed. Saving and verifying network settings…');self.finish_reads=0;return ok(self.transaction)
            if action=='network-cancel':self.transaction.update(phase='cancelling',message='Closing the connection test.');self.finish_reads=0;return ok(self.transaction)
        result=super().reply(req)
        if result['status']==200 and action.endswith('application-status'):
            for row in result['body'].get('containers',[]):row['required_storage']=['Example drive','image: test-backups']
        return result

def run():
    shots=Path(os.environ.get('USW_UI12_SCREENSHOTS','/tmp/usw-ui12-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(has_touch=True)
        for width in (320,390,768,1440):
            api=API();errors=[];lost=[False]
            def respond(route):
                req=route.request;path=urlsplit(req.url).path
                if path.startswith('/api/'):
                    result=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None))
                    if lost[0] and path=='/api/network-stage':lost[0]=False;route.abort();return
                    route.fulfill(status=result['status'],json=result['body']);return
                if path=='/download/proposed-trust-certificate.pem':route.fulfill(body='SYNTHETIC PUBLIC CA',headers={'Content-Disposition':'attachment; filename=usb-storage-watch-ca.crt'});return
                name='index.html' if path=='/' else path.removeprefix('/static/')
                if name not in ('index.html','app.js','network.js','style.css','icon.svg'):route.fulfill(status=404,body='');return
                route.fulfill(path=str(ROOT/name),content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',respond)
            page=context.new_page();page.set_viewport_size(dict(width=width,height=1000));page.set_default_timeout(10000);page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto('http://192.168.50.2:8765/#advanced')
            page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').click()
            page.wait_for_function('()=>networkView.loaded&&!routeLoading')
            expect(page.locator('[data-action="network-apply"]')).to_be_disabled()
            expect(page.locator('.network-url code').first).to_have_text('http://192.168.50.2:8765')
            page.locator('#network-address-control').tap();page.get_by_role('option',name=re.compile('192.168.50.3.*enp2s0')).tap()
            page.locator('[data-action="network-step"][data-id="http_port"][data-value="1"]').tap()
            expect(page.locator('#network-http_port')).to_have_value('8766')
            page.locator('[data-action="network-step"][data-id="http_port"][data-value="8765"]').tap()
            page.locator('#network-http_port').fill('9010')
            page.evaluate('()=>refreshNetwork()');expect(page.locator('#network-http_port')).to_have_value('9010')
            expect(page.locator('.network-url code').first).to_have_text('http://192.168.50.2:8765')
            # HTTPS preparation is local feedback and never changes active listeners.
            page.locator('input[data-network-input="scheme"][value="https"]').check()
            expect(page.locator('[data-action="network-apply"]')).to_be_enabled()
            page.locator('.network-trust > summary').click() if not page.locator('.network-trust').evaluate('(x)=>x.open') else None
            with page.expect_download() as download:
                page.locator('[data-action="network-download"]').click()
            assert download.value.suggested_filename=='usb-storage-watch-ca.crt'
            page.wait_for_function('()=>!networkView.busy')
            expect(page.locator('.fingerprint')).to_be_visible()
            expect(page.locator('[data-action="network-apply"]')).to_be_enabled()
            page.locator('input[data-network-input="scheme"][value="http"]').check()
            lost[0]=True;page.locator('[data-action="network-apply"]').tap();page.wait_for_function('()=>!networkView.busy&&networkView.transaction.phase==="pending"')
            assert len([c for c in api.network_calls if c[0]=='network-stage'])==1
            expect(page.locator('[data-action="network-confirm"]')).to_be_disabled()
            expect(page.locator('#network-address')).to_be_disabled()
            expect(page.locator('#network-countdown')).to_contain_text('seconds left to confirm')
            expect(page.locator('.network-test-link')).to_have_attribute('href','http://192.168.50.3:9010/#advanced')
            assert api.saved['address']=='192.168.50.2'
            if width in (390,1440):page.locator('#network-panel').screenshot(path=str(shots/f'network-test-{width}.png'))
            # Open the actual generated URL, then confirm on that origin.
            new=context.new_page();new.set_viewport_size(dict(width=width,height=1000));new.on('pageerror',lambda e:errors.append(str(e)))
            new.goto(page.locator('.network-test-link').get_attribute('href'));new.wait_for_function('()=>networkView.loaded&&!routeLoading')
            expect(new.locator('#network-address')).to_have_value('192.168.50.3');expect(new.locator('#network-http_port')).to_have_value('9010')
            expect(new.locator('[data-action="network-confirm"]')).to_be_enabled();new.locator('[data-action="network-confirm"]').tap()
            new.wait_for_function('()=>!networkView.busy');new.evaluate('()=>refreshNetwork()');new.wait_for_function('()=>networkView.transaction.phase==="complete"')
            expect(new.locator('[data-action="network-apply"]')).to_be_disabled();expect(new.locator('.network-url code').first).to_have_text('http://192.168.50.3:9010')
            # Cancellation and server timeout preserve old settings and form drafts elsewhere.
            new.locator('#network-http_port').fill('9020');new.locator('[data-action="network-apply"]').tap();new.wait_for_function('()=>!networkView.busy')
            new.locator('[data-action="network-cancel"]').tap();new.wait_for_function('()=>!networkView.busy');new.evaluate('()=>refreshNetwork()')
            new.wait_for_function('()=>networkView.transaction.phase==="cancelled"');expect(new.locator('#network-http_port')).to_have_value('9010')
            new.locator('#network-http_port').fill('9030');new.locator('[data-action="network-apply"]').tap();new.wait_for_function('()=>!networkView.busy')
            api.transaction.update(phase='expired',seconds_left=0,message='Confirmation timed out. Previous settings retained.')
            new.evaluate('()=>refreshNetwork()');expect(new.locator('#network-message')).to_contain_text('timed out');expect(new.locator('[data-action="network-apply"]')).to_be_disabled()
            # Refusal remains visible beside Apply, without a blocking modal or auto retry.
            api.reject=True;new.locator('#network-http_port').fill('9040');new.locator('[data-action="network-apply"]').tap();new.wait_for_function('()=>!networkView.busy')
            expect(new.locator('#network-message')).to_contain_text('occupied port');assert api.saved['http_port']==9010;api.reject=False
            # Disabling LAN is confirmed at localhost, never the remote old URL.
            new.locator('#network-http_port').fill('9010');new.locator('#network-lan').uncheck();new.locator('[data-action="network-apply"]').tap();new.wait_for_function('()=>!networkView.busy')
            expect(new.locator('.network-test-link')).to_have_attribute('href','http://127.0.0.1:9010/#advanced');expect(new.locator('[data-action="network-confirm"]')).to_be_disabled()
            local=context.new_page();local.set_viewport_size(dict(width=width,height=1000));local.goto('http://127.0.0.1:9010/#advanced');local.wait_for_function('()=>networkView.loaded&&!routeLoading')
            local.locator('[data-action="network-confirm"]').tap();local.wait_for_function('()=>!networkView.busy');local.evaluate('()=>refreshNetwork()');local.wait_for_function('()=>networkView.transaction.phase==="complete"')
            assert api.saved['lan'] is False
            expect(local.locator('.network-url code').first).to_have_text('Local network access is disabled.')
            for tab in (page,new,local):assert tab.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
            assert not errors,errors
            print(f'PASS UI12 browser {width}px: draft/save URLs, touch ports, certificate, lost response, new-origin confirmation, cancellation, timeout, refusal, localhost disable')
            for tab in (page,new,local):tab.close()
            context.unroute('**/*',respond)
        context.close();browser.close()
if __name__=='__main__':run()
