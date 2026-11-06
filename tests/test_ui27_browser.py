# SPDX-License-Identifier: MIT
"""Packaged network UI; intercepted APIs, no host networking changes."""
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from test_ui12_browser import API as PriorAPI, ROOT
from test_ui13_browser import CSP


class API(PriorAPI):
    def __init__(self):
        super().__init__();self.saved.update(address_mode='manual',scheme='https',port=8766)
        self.cert=True;self.replacement=True;self.verified=False
        self.addresses=[dict(address='192.168.50.3',interface='physical-example',automatic=True,advanced=False,metric=100,default_route=True),
                        dict(address='100.64.0.2',interface='vpn-example',automatic=False,advanced=True)]

    def reply(self,req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1]
        if action=='network-stage':
            data=dict(req['data']);self.replacement=not data.pop('replace_trust',False) if self.replacement else False
            if data.get('address_mode')=='automatic' and data['lan']:
                data['address']=next((v['address'] for v in self.addresses if v['automatic']),'127.0.0.1')
            req=dict(req,data=data)
        value=super().reply(req)
        if action=='network-state' and value['status']==200:
            body=value['body'];body['addresses']=copy.deepcopy(self.addresses)
            body['certificate'].update(replacement_required=self.replacement,renewable=not self.replacement)
            chosen=next((v for v in self.addresses if (v['automatic'] if self.saved['address_mode']=='automatic' else v['address']==self.saved['address'])),None)
            phase=('disabled' if not self.saved['lan'] else 'ready' if chosen and self.verified else
                   'checking' if chosen else 'waiting' if self.saved['address_mode']=='automatic' else 'unavailable')
            body['url']=self.url(self.saved) if phase=='ready' else None
            body['listener']=dict(phase=phase,url=body['url'],interface=(chosen or {}).get('interface'),
                message={'disabled':'Local network access is disabled.','ready':'Network listener verified.',
                    'checking':'Verifying the selected network listener.','waiting':'Waiting for a network address',
                    'unavailable':'The selected manual address is unavailable. Switch to Automatic.'}[phase])
        return value


def run():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,390,768,1440):
            api=API();errors=[];context=browser.new_context(viewport=dict(width=width,height=1000),has_touch=True)
            def serve(route):
                req=route.request;path=urlsplit(req.url).path;headers={'Content-Security-Policy':CSP,'Cache-Control':'no-store'}
                if path.startswith('/api/'):
                    value=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None))
                    route.fulfill(status=value['status'],json=value['body'],headers=headers);return
                name='index.html' if path=='/' else path.removeprefix('/static/')
                if name not in ('index.html','app.js','network.js','style.css','icon.svg'):route.fulfill(status=404);return
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:8765/#advanced');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap()
            page.wait_for_function('()=>networkView.loaded&&!routeLoading')
            card=page.locator('.network-url').first
            expect(card).to_contain_text('manual address is unavailable');expect(card.locator('button')).to_have_count(0)
            page.locator('[data-network-input="address_mode"][value="automatic"]').check()
            expect(page.locator('.network-selected-interface')).to_contain_text('physical-example · 192.168.50.3')
            expect(page.locator('[data-action="network-apply"]')).to_be_disabled()
            page.locator('#network-replace-trust').check();expect(page.locator('[data-action="network-apply"]')).to_be_enabled()
            page.locator('[data-action="network-apply"]').tap();page.wait_for_function('()=>!networkView.busy')
            expect(page.locator('[data-action="network-confirm"]')).to_be_disabled();expect(card.locator('button')).to_have_count(0)
            new=context.new_page();new.on('pageerror',lambda e:errors.append(str(e)))
            new.goto(page.locator('.network-test-link').get_attribute('href'));new.wait_for_function('()=>networkView.loaded&&!routeLoading')
            new.locator('[data-action="network-confirm"]').tap();new.wait_for_function('()=>!networkView.busy');new.evaluate('()=>refreshNetwork()')
            new.wait_for_function('()=>networkView.transaction.phase==="complete"')
            api.verified=True;page.evaluate('()=>refreshNetwork()')
            expect(card.locator('code')).to_have_text('https://192.168.50.3:8766')
            api.saved.update(address='192.168.50.4',hostname='192.168.50.4');api.addresses[0]['address']='192.168.50.4';api.verified=False
            page.evaluate('()=>refreshNetwork()');expect(card.locator('button')).to_have_count(0)
            api.verified=True;page.evaluate('()=>refreshNetwork()');expect(card.locator('code')).to_have_text('https://192.168.50.4:8766')
            api.addresses=api.addresses[1:];page.evaluate('()=>refreshNetwork()')
            expect(card).to_contain_text('Waiting for a network address');expect(card.locator('button')).to_have_count(0)
            expect(page.locator('.network-selected-interface')).to_have_text('Waiting for a network address')
            page.locator('[data-network-input="address_mode"][value="manual"]').check();page.locator('#network-address-control').tap()
            expect(page.get_by_role('dialog').get_by_role('option').filter(has_text='vpn-example')).to_have_count(1)
            page.keyboard.press('Escape')
            page.locator('[data-network-input="address_mode"][value="automatic"]').check()
            page.locator('#network-lan').uncheck();page.locator('[data-action="network-apply"]').tap();page.wait_for_function('()=>!networkView.busy')
            page.locator('[data-action="network-confirm"]').tap();page.wait_for_function('()=>!networkView.busy');page.evaluate('()=>refreshNetwork()')
            page.wait_for_function('()=>networkView.transaction.phase==="complete"');expect(card).to_contain_text('Local network access is disabled.')
            expect(page.locator('.network-url').nth(1).locator('code')).to_have_text('http://127.0.0.1:8765')
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'),width
            assert not errors,errors
            print(f'PASS UI27 {width}px: unavailable Manual URL hidden, Automatic interface, trust acknowledgement, exact-origin confirmation, verified URL changes, no virtual fallback and localhost disable')
            context.close()
        browser.close()


if __name__=='__main__':run()
