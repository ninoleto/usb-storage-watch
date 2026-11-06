"""UI13 acceptance through visible touch controls, with production CSP headers.
All host APIs and devices are synthetic. No container or disk is operated.
"""
import copy
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
from test_ui12_browser import API as PreviousAPI,ROOT

CSP="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
class API(PreviousAPI):
    def __init__(self):
        super().__init__();self.saved.update(scheme='https',port=8766);self.certificate_failure=False
        # A picker is useful only when more than one existing access-check
        # mapping exists. UI15 displays singleton mappings as read-only details.
        self.rows[0]['binds'].append(dict(source='/mnt/legacy/backup/other',
            destination='/other',eligible=True,reason=''))
    def reply(self,req):
        action=req['url'].split('/api/',1)[-1].split('?')[0]
        if action=='network-certificate' and self.certificate_failure:
            self.network_calls.append((action,{}));return dict(status=409,body=dict(error='Synthetic certificate preparation failure.'))
        if action=='network-renew':
            self.next+=1;self.transaction=dict(operation='synthetic-'+str(self.next),kind='certificate-renew',phase='committing',message='Renewing server certificate.',config=copy.deepcopy(self.saved),url=self.url(self.saved),seconds_left=0);self.finish_reads=0
            return dict(status=200,body=copy.deepcopy(self.transaction))
        result=super().reply(req)
        if action=='network-state' and result['status']==200:
            body=result['body'];body['certificate'].update(renewable=self.cert and self.saved['scheme']=='https',server_expires='2027-11-01T00:00:00Z')
            body['addresses']=[dict(address='100.108.33.65',interface='tailscale0')]+[dict(address='172.'+str(i)+'.0.1',interface='docker0' if i==17 else 'br-synthetic'+str(i),advanced=True) for i in range(17,27)]+body['addresses']
            if body['transaction'].get('kind')=='certificate-renew' and body['transaction']['phase']=='complete':body['transaction']['message']='Server certificate renewed and verified.'
        return result

def run():
    shots=Path(os.environ.get('USW_UI13_SCREENSHOTS','/tmp/usw-ui13-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,390,768,1440):
            api=API();errors=[];csp_errors=[]
            context=browser.new_context(has_touch=True,viewport=dict(width=width,height=1000),accept_downloads=True)
            def serve(route):
                req=route.request;path=urlsplit(req.url).path
                headers={'Cache-Control':'no-store','Content-Security-Policy':CSP,'X-Content-Type-Options':'nosniff'}
                if path.startswith('/api/'):
                    response=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None))
                    route.fulfill(status=response['status'],json=response['body'],headers=headers);return
                if path=='/download/proposed-trust-certificate.pem':
                    route.fulfill(body='SYNTHETIC PUBLIC CA',headers=dict(headers,**{'Content-Disposition':'attachment; filename=usb-storage-watch-ca.crt','Content-Type':'application/x-pem-file'}));return
                name='index.html' if path=='/' else path.removeprefix('/static/')
                if name not in ('index.html','app.js','network.js','style.css','icon.svg'):route.fulfill(status=404,body='');return
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(10000)
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda m:csp_errors.append(m.text) if m.type=='error' and ('Content Security Policy' in m.text or 'Refused to apply inline style' in m.text) else None)
            page.goto('https://192.168.50.2:8766/#advanced')
            page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap();page.wait_for_function('()=>networkView.loaded&&!routeLoading')
            apply=page.locator('[data-action="network-apply"]');expect(apply).to_be_disabled()
            # The user's exact regression: HTTPS changes while a trust CA has not been prepared.
            page.get_by_role('button',name='Decrease Network HTTPS port').tap()
            expect(page.locator('#network-https_port')).to_have_value('8765');expect(apply).to_be_enabled()
            api.certificate_failure=True;apply.tap();page.wait_for_function('()=>!networkView.busy')
            expect(page.locator('#network-message')).to_contain_text('certificate preparation failure');expect(apply).to_be_enabled()
            page.evaluate('()=>refreshNetwork()');expect(page.locator('#network-message')).to_contain_text('certificate preparation failure')
            assert not any(a=='network-stage' for a,d in api.network_calls)
            api.certificate_failure=False;apply.tap();page.wait_for_function('()=>!networkView.busy&&networkView.transaction.phase==="pending"')
            assert api.cert and api.saved['https_port']==8766
            expect(page.locator('.network-test-link')).to_have_attribute('href','https://192.168.50.2:8765/#advanced')
            page.locator('[data-action="network-cancel"]').tap();page.wait_for_function('()=>!networkView.busy');page.evaluate('()=>refreshNetwork()');page.wait_for_function('()=>networkView.transaction.phase==="cancelled"')
            # Invalid edits have a visible reason and valid corrections enable Apply again.
            for value in ('','80','65536','1234.5'):
                page.locator('#network-http_port').fill(value);expect(apply).to_be_disabled();expect(page.locator('#network-message')).to_contain_text('whole number')
            page.locator('#network-http_port').fill('9000');expect(apply).to_be_enabled()
            page.get_by_role('button',name='Reset to 8765',exact=True).tap();expect(apply).to_be_disabled()
            page.get_by_role('button',name='Increase HTTP / localhost port').tap();expect(apply).to_be_enabled()
            page.get_by_role('button',name='Decrease HTTP / localhost port').tap();expect(apply).to_be_disabled()
            # Address picker is modal, scrollable, touch sized and survives status polling.
            page.locator('#network-address-control').tap();dialog=page.get_by_role('dialog',name='Choose an address');expect(dialog).to_be_visible()
            rows=dialog.get_by_role('option');assert rows.count()==13
            for row in rows.all():assert row.bounding_box()['height']>=70
            assert dialog.locator('.picker-list').evaluate('(x)=>x.scrollHeight>x.clientHeight')
            page.evaluate('()=>refreshNetwork()');expect(dialog).to_be_visible()
            page.evaluate('()=>render()');expect(dialog).to_be_visible()
            assert dialog.evaluate('(d)=>d.contains(document.activeElement)')
            for _ in range(16):page.keyboard.press('Tab');assert dialog.evaluate('(d)=>d.contains(document.activeElement)')
            page.keyboard.press('Escape');expect(dialog).to_have_count(0);expect(page.locator('#network-address-control')).to_be_focused()
            page.locator('#network-address-control').tap()
            if width in (390,1440):page.screenshot(path=str(shots/f'address-picker-{width}.png'))
            dialog.get_by_role('option',name=re.compile('172.26.0.1')).tap();expect(page.locator('#network-address')).to_have_value('172.26.0.1');expect(apply).to_be_enabled()
            # Changing address keeps saved URL cards unchanged until new-origin confirmation.
            expect(page.locator('.network-url code').first).to_have_text('https://192.168.50.2:8766')
            page.locator('#network-address-control').tap();dialog.get_by_role('option',name=re.compile('192.168.50.2')).tap();expect(apply).to_be_disabled()
            # Every certificate guide is an expandable large row with explicit ordered steps.
            page.locator('.certificate-guide > summary').tap()
            guides=page.locator('.certificate-guide > details');assert guides.count()==6
            for guide in guides.all():
                assert guide.locator('summary').bounding_box()['height']>=48
                guide.locator('summary').tap();expect(guide.locator('ol')).to_be_visible();assert guide.locator('li').count()>=3
            expect(page.locator('.certificate-guide')).to_contain_text('chrome://certificate-manager')
            expect(page.locator('.certificate-guide')).to_contain_text('Certificate Trust Settings')
            with page.expect_download() as download:page.get_by_role('button',name='Download local HTTPS trust certificate').tap()
            assert download.value.suggested_filename=='usb-storage-watch-ca.crt'
            if width in (390,1440):page.locator('.certificate-guide').screenshot(path=str(shots/f'certificate-guides-{width}.png'))
            for guide in guides.all():guide.locator('summary').tap()
            page.get_by_role('button',name='Renew server certificate',exact=True).tap();page.get_by_role('button',name='Confirm',exact=True).tap()
            page.wait_for_function('()=>!networkView.busy');page.evaluate('()=>refreshNetwork()');page.wait_for_function('()=>networkView.transaction.phase==="complete"')
            expect(page.locator('#network-message')).to_contain_text('renewed');expect(apply).to_be_disabled()
            page.get_by_role('button',name='Increase Network HTTPS port').tap()
            if width in (390,1440):page.locator('#network-panel').screenshot(path=str(shots/f'network-ready-{width}.png'))
            # All other selectors use the same dialog; no forced/native select_option calls.
            def nav(route):
                button=page.locator('[data-action="nav"][data-value="'+route+'"]')
                if page.locator('[data-action="menu"]').is_visible() and 'open' not in (page.locator('#sidebar').get_attribute('class') or '').split():page.locator('[data-action="menu"]').tap()
                button.tap();page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r',arg=route)
            def pick(identifier,index=0):
                page.wait_for_function('()=>!apiBusy&&!routeLoading&&!Array.from(applicationViews.values()).some(v=>v.loading)')
                trigger=page.locator('#'+identifier+'-control');expect(trigger).to_be_visible();assert trigger.bounding_box()['height']>=64
                native=page.locator('#'+identifier);expect(native).to_be_hidden()
                trigger.tap();picker=page.locator('dialog.touch-picker');expect(picker).to_be_visible();row=picker.get_by_role('option').nth(index)
                assert row.bounding_box()['height']>=70
                row.tap();expect(picker).to_have_count(0);page.wait_for_function('()=>!apiBusy&&!routeLoading');return native.input_value()
            nav('images');pick('image-drive',1);pick('image-drive',0)
            page.locator('[data-action="image-tab"][data-value="create"]').tap();assert pick('new-image-access',1)=='applications'
            nav('history');assert pick('history-filter',1)=='legacy';assert pick('history-filter',0)=='all'
            nav('email');assert pick('smtp-security',0)=='tls';assert pick('smtp-security',1)=='starttls'
            nav('integrations');expect(page.locator('#integration-drive')).to_have_count(0)
            nav('advanced');pick('advanced-drive',1);pick('advanced-drive',0)
            # UI16 replaces both Docker dropdowns with direct per-container
            # drive switches and image tiles (tested by test_ui16_browser.py).
            assert page.evaluate('()=>Array.from(document.querySelectorAll("select")).every(x=>x.hidden)')
            assert page.evaluate('()=>Array.from(document.querySelectorAll("input[type=number]")).every(x=>getComputedStyle(x).appearance==="textfield")')
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
            assert not errors,errors;assert not csp_errors,csp_errors
            print(f'PASS UI13 {width}px: HTTPS Apply regression, explicit validation, certificate failure/retry/download/renewal, six guides, modal focus/scroll/poll, remaining selectors by touch under CSP')
            context.close()
        browser.close()
if __name__=='__main__':run()
