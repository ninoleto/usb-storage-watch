# SPDX-License-Identifier: MIT
"""Responsive recovery admission and nested independently-saved HDD controls.

Production CSP/source; all host responses and operations are synthetic.
"""
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from test_ui29_browser import API as PriorAPI
from test_ui20_browser import ROOT, ERUGO, CSP
from test_ui16_browser import OTHER

MESSAGE='Recovery in progress. Controls are temporarily unavailable.'


class API(PriorAPI):
    def __init__(self):
        super().__init__();self.incidents=0;self.rejected=0;self.containers[1]['state']='stopped'

    def reply(self,req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1]
        if self.incidents and action in ('docker-app-save','docker-app-plan','docker-container-action'):
            data=req.get('data') or {};identity=data.get('id') or data.get('settings',{}).get('id')
            if action=='docker-app-save' or identity==ERUGO:
                self.rejected+=1;return dict(status=400,body=dict(error=MESSAGE))
        result=super().reply(req)
        if action=='docker-overview' and result['status']==200:
            for row in result['body']['containers']:row['control_block']=MESSAGE if row['id']==ERUGO and self.incidents else ''
        return result


def run():
    shots=Path(os.environ.get('USW_UI30_SCREENSHOTS','/tmp/usw-ui30-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/google-chrome'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,390,768,1440):
            api=API();errors=[];context=browser.new_context(viewport=dict(width=width,height=1100),has_touch=True)
            def serve(route):
                req=route.request;path=urlsplit(req.url).path;headers={'Content-Security-Policy':CSP,'Cache-Control':'no-store'}
                if path.startswith('/api/'):
                    value=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None))
                    route.fulfill(status=value['status'],json=value['body'],headers=headers);return
                name='index.html' if path=='/' else path.removeprefix('/static/')
                if name not in ('index.html','app.js','network.js','style.css','icon.svg'):route.fulfill(status=404,body='');return
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(12000)
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda m:errors.append(m.text) if m.type=='error' and 'Content Security Policy' in m.text else None)
            page.goto('http://localhost:8765/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap()
            page.wait_for_selector('[data-drive-card]')
            page.evaluate("()=>navigate('apps')");page.wait_for_function("()=>!apiBusy&&!routeLoading&&lastLoadedRoute==='apps'")
            card=page.locator(f'[data-container-id="{ERUGO}"]');other=page.locator(f'[data-container-id="{OTHER}"]')
            toggle=card.locator('[data-app-panel="boot"] [data-change="app-enabled"]');toggle.uncheck()
            card.locator('[data-action="app-review"]').tap();expect(card.locator('[data-action="app-save"]')).to_be_enabled()
            draft=page.evaluate('id=>JSON.stringify(dockerView(id).appDraft)',ERUGO)
            images=card.locator('[data-app-panel="recovery"] .app-images');images.locator('summary').tap()
            card.locator('.app-advanced summary').tap()
            # The backend refuses a previously enabled save; no queued retry.
            api.incidents=2;card.locator('[data-action="app-save"]').tap()
            expect(card.locator('.app-save-status')).to_contain_text(MESSAGE);assert api.rejected==1 and not api.saves
            expect(card.locator('.app-recovery-notice')).to_have_text(MESSAGE)
            assert card.locator('input:not(:disabled)').count()==0
            assert card.locator('.docker-control-actions button:not(:disabled)').count()==0
            expect(card.locator('[data-action="app-review"]')).to_be_disabled()
            assert page.evaluate('id=>JSON.stringify(dockerView(id).appDraft)',ERUGO)==draft
            expect(images).to_have_attribute('open','');expect(images.locator('input').first).to_be_disabled()
            expect(images.locator('summary')).to_have_attribute('aria-disabled','true')
            expect(card.locator('.app-advanced')).to_have_attribute('open','')
            other.locator('[data-action="docker-start"]').tap();expect(other.locator('.docker-live-state')).to_contain_text('Running')
            assert api.action_counts[OTHER]==1 and api.action_counts[ERUGO]==0
            api.incidents=1;page.evaluate('()=>loadApplications()');expect(toggle).to_be_disabled()
            expect(images).to_have_attribute('open','');assert not api.saves
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(shots/f'ui30-recovery-{width}.png'),full_page=True)
            api.incidents=0;page.evaluate('()=>loadApplications()');expect(toggle).to_be_enabled()
            expect(card.locator('[data-action="docker-start"]')).to_be_enabled();expect(card.locator('[data-action="app-review"]')).to_be_enabled()
            assert page.evaluate('id=>JSON.stringify(dockerView(id).appDraft)',ERUGO)==draft
            assert not api.saves and api.action_counts[ERUGO]==0
            # HDD section is always expanded and shares the timing card.
            page.evaluate("()=>navigate('advanced')");page.wait_for_function("()=>!apiBusy&&!routeLoading&&lastLoadedRoute==='advanced'")
            panel=page.locator('.timing-settings');hdd=panel.locator('.standby-subsection')
            expect(hdd).to_have_count(1);expect(hdd.locator('h3')).to_have_text('HDD standby & noise control')
            expect(page.locator('.stack > .standby-card')).to_have_count(0);expect(hdd.locator('details,summary')).to_have_count(0)
            assert hdd.evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(16, 24, 31)'
            expect(hdd.locator('#standby-idle')).to_be_visible()
            old=copy.deepcopy(api.configs['legacy']);timing=panel.locator('[data-action="timings-save"]');sleep=hdd.locator('[data-settings-save="standby"]')
            panel.locator('[data-timing="check"]').fill('37');hdd.locator('#standby-idle').fill('0')
            expect(timing).to_be_enabled();expect(sleep).to_be_disabled() # independent validation
            timing.tap();expect(panel.locator('[data-settings-status="timings"]')).to_have_text('Saved')
            assert api.configs['legacy']['monitor']['interval']==37;assert api.configs['legacy']['standby']==old['standby']
            hdd.locator('#standby-idle').fill('31');hdd.locator('#standby-auto').check();expect(sleep).to_be_enabled()
            panel.locator('[data-timing="check"]').fill('38');sleep.tap()
            expect(hdd.locator('[data-settings-status="standby"]')).to_have_text('Saved')
            assert api.configs['legacy']['standby']['idle_seconds']==1860;assert api.configs['legacy']['monitor']['interval']==37
            expect(panel.locator('[data-timing="check"]')).to_have_value('38');expect(timing).to_be_enabled()
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(shots/f'ui30-hdd-{width}.png'),full_page=True)
            assert not errors,errors;context.close();print('PASS UI30 responsive controls and nested independent HDD saves:',width,flush=True)
        browser.close()


if __name__=='__main__':run()
