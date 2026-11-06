# SPDX-License-Identifier: MIT
"""Read-only deliberate-stop explanation; synthetic status and production UI."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
from test_ui32_browser import API as PriorAPI,ROOT,CSP,ERUGO

TEXT='Drive ready. Apps remain stopped after safe unmount. Start them from Docker Apps when you’re ready.'
class API(PriorAPI):
    def __init__(self):super().__init__();self.ready=True;self.mon=False;self.unavailable=False;self.writes=[]
    def reply(self,req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1]
        if req['method']=='POST' and action!='login':self.writes.append(action)
        if action=='status' and self.unavailable:return dict(status=503,body=dict(error='Status unavailable'))
        result=super().reply(req)
        if result['status']==200:
            rows=result['body'].get('drives',[]) if action=='fleet-status' else [result['body']] if action=='status' else []
            for row in rows:
                row.update(deliberate_stopped_apps=[dict(id=ERUGO,name='test-app')] if self.ready else [],mount_state='mounted',mounted_expected=True,monitoring='active' if self.mon else 'inactive')
                if 'service' in row:row['service']['ActiveState']='active' if self.mon else 'inactive'
        return result

def run():
    shots=Path(os.environ.get('USW_UI34_SCREENSHOTS','/tmp/usw-ui34-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,768,1440):
            api=API();errors=[];context=browser.new_context(viewport=dict(width=width,height=1100),has_touch=True)
            def serve(route):
                req=route.request;path=urlsplit(req.url).path;headers={'Content-Security-Policy':CSP,'Cache-Control':'no-store'}
                if path.startswith('/api/'):
                    v=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None));route.fulfill(status=v['status'],json=v['body'],headers=headers);return
                name='index.html' if path=='/' else path.removeprefix('/static/')
                assert name in ('index.html','app.js','network.js','style.css','icon.svg','select-arrow.svg')
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://localhost:8765/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap();page.wait_for_selector('[data-drive-card]')
            expect(page.locator('.deliberate-stop-notice').first).to_have_text(TEXT)
            page.evaluate("()=>navigate('drive/legacy')");page.wait_for_function("()=>!apiBusy&&!routeLoading&&lastLoadedRoute==='drive/legacy'")
            for monitoring in (False,True):
                api.mon=monitoring;page.evaluate('()=>pollLive()');notice=page.locator('#drive-summary .deliberate-stop-notice');expect(notice).to_have_text(TEXT)
                expect(page.locator('#drive-summary .chip').first).to_contain_text('Monitoring on' if monitoring else 'Monitoring off')
            page.screenshot(path=str(shots/f'ui34-ready-{width}.png'),full_page=True)
            notice.locator('a').tap();page.wait_for_function("()=>lastLoadedRoute==='apps'&&!routeLoading")
            page.evaluate("()=>navigate('drive/legacy')");page.wait_for_function("()=>lastLoadedRoute==='drive/legacy'&&!routeLoading")
            api.ready=False;page.evaluate('()=>pollLive()');expect(page.locator('.deliberate-stop-notice')).to_have_count(0)
            api.ready=True;page.evaluate('()=>pollLive()');expect(page.locator('.deliberate-stop-notice')).to_have_count(1)
            api.unavailable=True;page.evaluate('()=>pollLive()');expect(page.locator('.deliberate-stop-notice')).to_have_count(0)
            assert not api.writes,api.writes;assert not errors,errors
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
            context.close();print('PASS UI34',width,'px: exact notice, existing app navigation, independent monitoring, ready/cleared/unavailable updates; no mutation.',flush=True)
        browser.close()

if __name__=='__main__':run()
