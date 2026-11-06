# SPDX-License-Identifier: MIT
"""Saved header choices and chronological history; synthetic API only."""
import copy,os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
from test_ui32_browser import API as PriorAPI,ROOT,CSP,ERUGO
from test_ui29_browser import OLD

class API(PriorAPI):
    def __init__(self):super().__init__();self.settings_mode='known';self.read_failed=False;self.recovery_active=False
    def reply(self,req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1]
        if action=='docker-overview' and self.read_failed:return dict(status=503,body=dict(error='Synthetic read failure'))
        result=super().reply(req)
        if result['status']!=200:return result
        if action=='docker-overview':
            body=result['body'];settings=body['applications']
            if self.settings_mode=='missing':settings['settings']=[v for v in settings['settings'] if v['id']!=ERUGO]
            if self.settings_mode=='error':settings['error']='Saved settings unavailable'
            if self.settings_mode=='partial':next(v for v in settings['settings'] if v['id']==ERUGO).pop('boot')
            if self.recovery_active:
                next(r for r in body['containers'] if r['id']==ERUGO)['control_block']='Recovery in progress. Controls are temporarily unavailable.'
        if action=='fleet-events':
            start='2026-01-01T00:28:55+01:00'
            result['body']['events']=[dict(drive_id='legacy',title='Storage RECOVERY FAILED — Drive return timeout',time='2026-01-01T01:02:14+01:00',outage_started=start,detail='Timeout recorded'),dict(drive_id='legacy',title='Storage AUTO-RECOVERED — Attempt 1',time='2026-01-01T01:12:39+01:00',outage_started=start,detail='Recovered and verified')]
        return result

def run():
    shots=Path(os.environ.get('USW_UI36_SCREENSHOTS','/tmp/usw-ui36-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,768,1440):
            api=API();errors=[];context=browser.new_context(viewport=dict(width=width,height=1100),has_touch=True,timezone_id='Europe/Zagreb')
            def serve(route):
                req=route.request;path=urlsplit(req.url).path;headers={'Content-Security-Policy':CSP,'Cache-Control':'no-store'}
                if path.startswith('/api/'):
                    v=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None));route.fulfill(status=v['status'],json=v['body'],headers=headers);return
                name='index.html' if path=='/' else path.removeprefix('/static/');assert name in ('index.html','app.js','network.js','style.css','icon.svg','select-arrow.svg')
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
            def nav(value):page.evaluate('(r)=>navigate(r)',value);page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r',arg=value)
            def poll():page.evaluate('()=>loadApplications({background:true})');page.wait_for_function('()=>!dockerPage.reading')
            page.goto('http://localhost:8765/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap();page.wait_for_selector('[data-drive-card]');nav('apps')
            card=page.locator(f'[data-container-id="{ERUGO}"]');header=card.locator('.docker-container-header');badges=header.locator('.app-saved-indicators')
            expect(badges).to_contain_text('Startup enabled');expect(badges).to_contain_text('Recovery enabled')
            runtime=header.locator('.docker-live-state').inner_text()
            card.locator('[data-app-panel="boot"] [role="switch"]').uncheck();expect(badges).to_contain_text('Startup enabled');assert not api.saves
            header.tap();expect(header).to_have_attribute('aria-expanded','false');expect(card.locator('.docker-container-body')).to_be_hidden();poll();expect(badges).to_contain_text('Startup enabled')
            page.screenshot(path=str(shots/f'ui36-collapsed-{width}.png'),full_page=True,animations='disabled')
            actual=next(v for v in api.apps if v['id']==ERUGO);actual['boot']['enabled']=False;api.app_revision+=1;poll();expect(badges).to_contain_text('Startup off');expect(header.locator('.docker-live-state')).to_have_text(runtime)
            actual['recovery']['enabled']=False;api.app_revision+=1;poll();expect(badges).to_contain_text('Recovery off')
            for mode in ('missing','error'):
                api.settings_mode=mode;poll();expect(badges).to_contain_text('Startup unknown');expect(badges).to_contain_text('Recovery unknown')
            api.settings_mode='known';poll();expect(badges).to_contain_text('Startup off')
            api.read_failed=True;poll();expect(badges).to_contain_text('Startup unknown');api.read_failed=False;poll();expect(badges).to_contain_text('Startup off')
            api.settings_mode='partial';poll();expect(badges).to_contain_text('Startup unknown');expect(badges).to_contain_text('Recovery off');api.settings_mode='known';poll()
            actual['boot']['enabled']=True;actual['recovery']['enabled']=True;api.app_revision+=1;api.recovery_active=True;poll()
            expect(header).to_be_disabled();expect(badges).to_contain_text('Startup enabled');expect(card.locator('.app-recovery-notice')).to_be_visible();expect(header).to_have_attribute('aria-expanded','false')
            expect(page.locator(f'[data-unavailable-entry="{OLD}"] .app-saved-indicators')).to_contain_text('Startup off')
            nav('history');entries=page.locator('#history-events .history-entry');expect(entries).to_have_count(2)
            expect(entries.first.locator('h3')).to_contain_text('AUTO-RECOVERED');expect(entries.first.locator('.history-meta').first).to_contain_text('01:12:39')
            expect(entries.nth(1).locator('.history-meta').first).to_contain_text('01:02:14');expect(entries.first.locator('.history-outage-start')).to_contain_text('Outage started:');expect(entries.first.locator('.history-outage-start')).to_contain_text('00:28:55')
            page.screenshot(path=str(shots/f'ui36-history-{width}.png'),full_page=True,animations='disabled')
            nav('drive/legacy');expect(page.locator('#drive-recent-events .history-entry').first.locator('h3')).to_contain_text('AUTO-RECOVERED')
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1');assert not errors,errors;assert not api.saves
            context.close();print('PASS UI36',width,'px: collapsed saved choices/drafts/unknown state/missing apps, recovery lock, outcome ordering and separate outage time.',flush=True)
        browser.close()

if __name__=='__main__':run()
