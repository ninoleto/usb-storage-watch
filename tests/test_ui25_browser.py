# SPDX-License-Identifier: MIT
"""Packaged UI with intercepted synthetic APIs; no real network/device actions."""
import copy
import os
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from test_ui20_browser import API as PreviousAPI, ROOT, ERUGO, IMAGE, CSP


class API(PreviousAPI):
    def __init__(self):
        super().__init__()
        self.boot=dict(revision='boot-0',settings=[],results={})
        self.boot_posts=[]

    def reply(self,req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1]
        if self.session and action=='docker-boot-settings':
            data=req['data'];assert data['revision']==self.boot['revision']
            self.boot_posts.append(copy.deepcopy(data))
            self.boot=dict(revision='boot-1',settings=[copy.deepcopy(data['container'])],results={})
            return dict(status=200,body=self.boot|dict(message='Boot startup settings saved.'))
        response=super().reply(req)
        if action=='docker-overview' and response['status']==200:
            response['body']['boot']=copy.deepcopy(self.boot)
        return response


def run():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/chromium'),
                                   headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,390,768,1440):
            api=API();errors=[]
            context=browser.new_context(viewport=dict(width=width,height=1000),has_touch=True)
            def serve(route):
                req=route.request;path=urlsplit(req.url).path
                headers={'Content-Security-Policy':CSP,'Cache-Control':'no-store'}
                if path.startswith('/api/'):
                    result=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None))
                    route.fulfill(status=result['status'],json=result['body'],headers=headers);return
                name='index.html' if path=='/' else path.removeprefix('/static/')
                if name not in ('index.html','app.js','network.js','style.css','icon.svg'):
                    route.fulfill(status=404,body='');return
                route.fulfill(path=str(ROOT/name),headers=headers,
                    content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else
                    'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve)
            page=context.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://localhost:8765/')
            page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap()
            expect(page.locator('[data-drive-card]')).to_have_count(2)
            def nav(route):
                page.evaluate('(route)=>navigate(route)',route)
                page.wait_for_function('(route)=>!apiBusy&&!routeLoading&&lastLoadedRoute===route',arg=route)
            nav('drive/legacy')
            page.evaluate('''()=>{const d=find('legacy');d.usbDetails={last_known:false,topology:'2-3.1',bus_address:'002/007',usb_ids:'aaaa:bbbb',serial:'synthetic-serial'};d.resetAvailable=true;d.stale=false;render();}''')
            reset=page.locator('[data-action="reconnect-drive"]')
            expect(reset).to_be_disabled()
            assert page.locator('.mount-eject .button-icon').evaluate('(e)=>getComputedStyle(e).color')=='rgb(255, 218, 97)'
            expect(page.locator('#drive-summary')).to_contain_text('002/007')
            page.evaluate("()=>{const d=find('legacy');d.mounted=false;render();}")
            expect(reset).to_be_enabled()
            assert reset.evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(104, 30, 41)'
            assert page.locator('.mount-folder .button-icon').evaluate('(e)=>getComputedStyle(e).color')=='rgb(255, 255, 255)'
            page.evaluate("()=>{const d=find('legacy');d.usbDetails.last_known=true;d.connected=false;render();}")
            expect(page.locator('#drive-summary')).to_contain_text('Last-known USB connection');expect(reset).to_be_disabled()
            nav('apps')
            card=page.locator(f'[data-container-id="{ERUGO}"]')
            before=page.evaluate('id=>JSON.stringify(dockerView(id).draft)',ERUGO)
            enable=card.locator('[data-change="boot-enabled"]');expect(enable).not_to_be_checked();enable.check()
            choices=card.locator('[data-change="boot-drive"]');expect(choices).to_have_count(2)
            for choice in choices.all():expect(choice).not_to_be_checked()
            card.locator('[data-change="boot-drive"][data-drive="legacy"]').check()
            card.locator(f'[data-change="boot-image"][value="{IMAGE}"]').check()
            card.locator('[data-action="boot-save"]').tap()
            expect(card.locator('.boot-controls [role="status"]')).to_have_text('Boot startup settings saved.')
            assert api.boot_posts[0]['container']['drives']==[dict(id='legacy',images=[IMAGE])]
            assert page.evaluate('id=>JSON.stringify(dockerView(id).draft)',ERUGO)==before
            expect(card.locator('.boot-controls [role="status"]:visible')).to_have_count(1)
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'),width
            assert not errors,errors
            context.close();print(f'PASS UI25 {width}px: reset guards/identity/icons, independent explicit boot choices and one save result')
        browser.close()


if __name__=='__main__':run()
