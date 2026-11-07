"""Chromium DOM checks; all API requests intercepted, no host operations."""
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
from test_ui27_browser import API as PreviousAPI,ROOT,CSP

class API(PreviousAPI):
    def __init__(self):
        super().__init__();self.saved.update(scheme='http',address='192.168.50.3',hostname='192.168.50.3',port=8765)
        self.replacement=False;self.verified=True;self.fail_fast=False;self.image_writes=0
    def reply(self,req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1]
        if action=='image-plan':
            return dict(status=200,body=dict(mode='adopt',token='reviewed-fixture',message=
                'Backing file: /mnt/fixture/backup.img; filesystem UUID: 22222222-2222-4222-8222-222222222222; '
                'mountpoint: /mnt/fixture/ftp/files. Mount, fstab entry/options, ownership, permissions and files stay unchanged.'))
        if action=='image-apply':
            assert req['data']==dict(token='reviewed-fixture',confirm=True)
            self.image_writes+=1
            return dict(status=200,body=dict(registered=True,image_created=False,changed=True,message='Existing mounted image registered. Mount and fstab preserved.'))
        result=super().reply(req)
        if action=='network-stage' and result['status']==200:
            self.transaction.update(phase='preparing',message='Preparing the proposed listener.')
            result['body']=copy.deepcopy(self.transaction)
            if self.fail_fast:self.transaction.update(phase='failed',message='Synthetic TLS check failed. Previous settings retained.')
        return result

def run():
    shots=Path(os.environ.get('USW_BETA2_SCREENSHOTS','/tmp/usw-beta2-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,768,1440):
            api=API();errors=[];context=browser.new_context(viewport=dict(width=width,height=1000),has_touch=True)
            def serve(route):
                req=route.request;path=urlsplit(req.url).path
                if path.startswith('/api/'):
                    r=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None))
                    route.fulfill(status=r['status'],json=r['body'],headers={'Content-Security-Policy':CSP});return
                name='index.html' if path=='/' else path.removeprefix('/static/')
                assert name in ('index.html','app.js','network.js','style.css','icon.svg','select-arrow.svg')
                route.fulfill(path=str(ROOT/name),headers={'Content-Security-Policy':CSP},content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:8765/#advanced');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap()
            page.wait_for_function('()=>networkView.loaded&&!routeLoading')
            page.locator('[data-network-input="scheme"][value="https"]').check()
            page.locator('[data-action="network-apply"]').tap();page.wait_for_function('()=>!networkView.busy')
            expect(page.locator('#network-message')).to_contain_text('Preparing')
            expect(page.locator('[data-action="network-confirm"]')).to_be_disabled()
            assert 'ready to test' not in page.locator('#network-panel').inner_text().lower()
            api.transaction.update(phase='pending',seconds_left=180,message='Ready for confirmation at the proposed address.')
            page.evaluate('()=>refreshNetwork()')
            expect(page.locator('#network-message')).to_contain_text('Ready for confirmation')
            expect(page.locator('.network-test-link')).to_be_visible()
            assert 'New connection ready for confirmation' in page.locator('#network-panel').inner_text()
            api.transaction.update(phase='failed',message='Synthetic TLS check failed. Previous settings retained.')
            page.evaluate('()=>refreshNetwork()')
            expect(page.locator('#network-message')).to_contain_text('TLS check failed')
            text=page.locator('#network-panel').inner_text()
            assert 'ready for confirmation' not in text.lower() and 'ready to test' not in text.lower(),text
            expect(page.locator('.network-test-link')).to_have_count(0)
            expect(page.locator('[data-action="network-apply"]')).to_be_disabled()
            page.locator('[data-network-input="scheme"][value="https"]').check()
            api.fail_fast=True;page.locator('[data-action="network-apply"]').tap();page.wait_for_function('()=>!networkView.busy')
            expect(page.locator('#network-message')).to_contain_text('TLS check failed')
            assert 'ready for confirmation' not in page.locator('#network-panel').inner_text().lower()
            page.locator('#network-panel').screenshot(path=str(shots/f'network-failed-{width}.png'))
            # Use the real existing-image review helper and confirmation handler.
            # Storage identity enforcement is exercised separately through the real broker.
            page.evaluate("()=>setupImagePlan({id:'legacy',mounted:true,stale:false},{mode:'existing',name:'Backup',image:'/mnt/fixture/backup.img'})")
            expect(page.get_by_role('heading',name='Adopt existing mounted image?')).to_be_visible()
            modal=page.locator('#modal-root');text=modal.inner_text()
            for value in ('/mnt/fixture/backup.img','/mnt/fixture/ftp/files','22222222-2222-4222-8222-222222222222','permissions'):assert value in text
            assert api.image_writes==0
            modal.locator('.modal').screenshot(path=str(shots/f'adopt-review-{width}.png'))
            page.locator('#modal-root [data-action="confirmed-action"]').tap()
            page.wait_for_function('()=>!modalPending');assert api.image_writes==1
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
            assert not errors,errors
            context.close();print('PASS',width,'px: preparing/pending/failure feedback, no stale success, adoption review and one confirmation',flush=True)
        browser.close()

if __name__=='__main__':run()
