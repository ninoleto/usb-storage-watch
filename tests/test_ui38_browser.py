# SPDX-License-Identifier: MIT
"""UI38 focused setup navigation, collapse and same-origin downloads; intercepted APIs, no host operations."""
import copy,os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
from test_ui27_browser import API as PreviousAPI,ROOT,CSP

PEM='-----BEGIN CERTIFICATE-----\n'+'QUJD'*16+'\n'+'REVG'*16+'\n-----END CERTIFICATE-----\n'
class API(PreviousAPI):
    def __init__(self):
        super().__init__();self.saved.update(address_mode='automatic',scheme='https',https_port=9443,port=9443,address='192.168.50.3');self.verified=True
        self.info=dict(certificate_pem=PEM,module=dict(available=True,version='0.2.6'));self.network_failed=False;self.info_failed=False
    def reply(self,req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1]
        if action=='integration-info':return dict(status=503,body=dict(error='Synthetic setup unavailable')) if self.info_failed else dict(status=200,body=copy.deepcopy(self.info))
        if action=='network-state' and self.network_failed:return dict(status=503,body=dict(error='Synthetic network status unavailable'))
        return super().reply(req)

def run():
    shots=Path(os.environ.get('USW_UI38_SCREENSHOTS','/tmp/usw-ui38-shots'));shots.mkdir(parents=True,exist_ok=True)
    module=(ROOT.parent/'companion/module.tgz').read_bytes()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for origin in ('http://localhost:8765','https://192.168.50.3:9443'):
          for width in (320,768,1440):
            api=API();errors=[];writes=[];downloads=[];context=browser.new_context(viewport=dict(width=width,height=1000),has_touch=True,accept_downloads=True)
            context.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async value=>{window.copied=value;}}});")
            def serve(route):
                req=route.request;path=urlsplit(req.url).path;headers={'Content-Security-Policy':CSP,'Cache-Control':'no-store'}
                assert req.url.startswith(origin+'/'),req.url  # Every request stays on the page's origin.
                if path.startswith('/api/'):
                    if req.method=='POST':writes.append(path)
                    r=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None));route.fulfill(status=r['status'],json=r['body'],headers=headers);return
                if path.startswith('/download/'):
                    downloads.append(req.url);pem=path.endswith('.pem')
                    route.fulfill(body=PEM if pem else module,headers=headers|{'Content-Disposition':'attachment; filename="'+('usb-storage-watch-ca.crt' if pem else 'usb-storage-watch-companion-0.2.6.tgz')+'"'},content_type='application/octet-stream');return
                name='index.html' if path=='/' else path.removeprefix('/static/');assert name in ('index.html','app.js','network.js','style.css','icon.svg','select-arrow.svg')
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
            def loaded(value):page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r',arg=value)
            def nav(value):page.evaluate('(r)=>navigate(r)',value);loaded(value)
            def poll():page.evaluate('()=>loadIntegrationData()')
            page.goto(origin+'/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap();page.wait_for_selector('[data-drive-card]');nav('integrations')
            expect(page.locator('#integration-url')).to_have_text('https://192.168.50.3:9443')
            expect(page.locator('#main-content [data-action="rotate-token"]')).to_have_count(0)
            expect(page.locator('#main-content a[href="/download/trust-certificate.pem"]')).to_have_count(0)
            expect(page.locator('#integration-drive')).to_have_count(0)
            expect(page.locator('#integration-pem')).to_be_hidden();expect(page.locator('#integration-pem')).to_have_value(PEM)
            expect(page.get_by_role('button',name='Copy certificate',exact=True)).to_be_visible()
            page.get_by_role('button',name='Copy certificate',exact=True).tap();page.wait_for_function('(pem)=>window.copied===pem',arg=PEM)
            assert page.evaluate('window.copied').startswith('-----BEGIN CERTIFICATE-----\n') and page.evaluate('window.copied').endswith('-----END CERTIFICATE-----\n')
            page.locator('[data-action="integration-copy-url"]').tap();page.wait_for_function("()=>window.copied==='https://192.168.50.3:9443'")
            page.locator('#main-content [data-action="copy-token-command"]').tap();page.wait_for_function("()=>window.copied==='sudo cat /var/lib/usb-storage-watch/management.token'")
            summary=page.locator('#integration-certificate summary');summary.focus();summary.press('Enter');expect(page.locator('#integration-pem')).to_be_visible()
            assert page.locator('#integration-pem').get_attribute('readonly') is not None
            api.saved['https_port']=9553;poll();expect(page.locator('#integration-url')).to_have_text('https://192.168.50.3:9553');expect(page.locator('#integration-pem')).to_be_visible()
            page.locator('#integration-certificate summary').tap();expect(page.locator('#integration-pem')).to_be_hidden()
            api.saved['https_port']=9443;poll();expect(page.locator('#integration-pem')).to_be_hidden()
            link=page.get_by_role('link',name='Download module 0.2.6',exact=True)
            assert link.get_attribute('href')=='/download/companion-module.tgz'
            assert link.evaluate('(a)=>new URL(a.href).origin')==origin
            # Chromium downloads bypass page route interception. Validate the link
            # and ordinary same-origin GET here; real download clicks are checked
            # separately against this host, never a synthetic LAN address.
            content=link.evaluate('async a=>Array.from(new Uint8Array(await (await fetch(a.href)).arrayBuffer()))')
            assert bytes(content)==module
            assert downloads[-1]==origin+'/download/companion-module.tgz'
            page.screenshot(path=str(shots/f'ui38-{urlsplit(origin).scheme}-{width}.png'),full_page=True,animations='disabled')
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
            # Manage token lands and focuses the existing control section, not page top.
            page.get_by_role('button',name='Manage token',exact=True).tap();loaded('advanced')
            page.wait_for_function("()=>document.activeElement.id==='management-token-heading'")
            heading=page.locator('#management-token-heading');assert 0<=heading.bounding_box()['y']<900
            expect(page.locator('#management-token-panel [data-action="rotate-token"]')).to_have_count(1)
            nav('integrations');page.get_by_role('button',name='Network Settings',exact=True).tap();loaded('advanced')
            page.wait_for_function("()=>document.activeElement.id==='network-heading'")
            heading=page.locator('#network-heading');assert 0<=heading.bounding_box()['y']<900
            guide=page.locator('[data-network-detail="certificate"]');guide.locator('summary').first.tap()
            expect(page.get_by_role('button',name='Download local HTTPS trust certificate',exact=True)).to_be_visible()
            nav('integrations');expect(page.locator('#integration-pem')).to_be_hidden()
            api.addresses=[];poll();expect(page.locator('[data-action="integration-copy-url"]')).to_have_count(0)
            api.network_failed=True;poll();expect(page.locator('#integration-url')).to_contain_text('Network status unavailable')
            api.network_failed=False;api.saved['lan']=False;api.saved['http_port']=9012;poll();expect(page.locator('#integration-url')).to_have_text('http://127.0.0.1:9012')
            api.info['certificate_pem']=None;api.info['module']={'available':False};poll();expect(page.locator('#integration-pem')).to_have_count(0);expect(page.locator('a[href="/download/companion-module.tgz"]')).to_have_count(0)
            assert writes==['/api/login'],writes;assert not errors,errors
            context.close();print('PASS UI38',urlsplit(origin).scheme,width,'px: section navigation/focus, complete PEM copy while collapsed, keyboard/touch expansion and refresh persistence, same-origin exact module fetch, CA download retained in Network Settings; no settings writes.',flush=True)
        browser.close()
if __name__=='__main__':run()
