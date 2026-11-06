# SPDX-License-Identifier: MIT
"""Countdown/timeout status and timing editor; synthetic API, production UI/CSP."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
from test_ui32_browser import API as PriorAPI,ROOT,CSP,ERUGO
from test_ui16_browser import OTHER

FAILED='Drive has not returned. Dependent apps remain stopped.'
class API(PriorAPI):
    def __init__(self):super().__init__();self.remaining=240;self.expired=False;self.waiting=True;self.unavailable=False
    def reply(self,req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1]
        if action=='status' and self.unavailable:return dict(status=503,body=dict(error='Synthetic status unavailable'))
        result=super().reply(req)
        if result['status']!=200:return result
        body=result['body'];text=FAILED if self.expired else f'Drive return timeout: {self.remaining//60}:{self.remaining%60:02d} remaining.'
        if action in ('status','fleet-status'):
            for row in body.get('drives',[]) if action=='fleet-status' else [body]:
                if (row.get('id') or row.get('profile_id') or 'legacy')!='legacy':continue
                row.update(connected=not self.waiting,mounted=not self.waiting,mounted_expected=not self.waiting,mount_state='unavailable' if self.waiting else 'mounted',mount_locations=[] if self.waiting else ['/mnt/legacy'],mount_target_occupied=not self.waiting,monitoring='active')
                if 'health' in row:row['health'].update(detected=not self.waiting,healthy=not self.waiting)
                if 'service' in row:row['service']['ActiveState']='active'
                row['progress']=dict(phase='return_failed' if self.expired else 'wait1',incident='synthetic-incident',code='return_failed' if self.expired else 'waiting_return',title='Drive return timeout' if self.expired else 'Waiting for the disk to return',detail=text,drive_return=dict(remaining_seconds=self.remaining,expired=self.expired)) if self.waiting else dict(code='healthy',title='Storage healthy',detail='Verified healthy')
        if action=='docker-overview':
            for row in body['containers']:
                if row['id']==ERUGO:row['control_block']=(text+' Controls are temporarily unavailable.') if self.waiting else ''
        return result

def run():
    shots=Path(os.environ.get('USW_UI35_SCREENSHOTS','/tmp/usw-ui35-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,768,1440):
            api=API();errors=[];context=browser.new_context(viewport=dict(width=width,height=1100),has_touch=True)
            def serve(route):
                req=route.request;path=urlsplit(req.url).path;headers={'Content-Security-Policy':CSP,'Cache-Control':'no-store'}
                if path.startswith('/api/'):
                    value=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None));route.fulfill(status=value['status'],json=value['body'],headers=headers);return
                name='index.html' if path=='/' else path.removeprefix('/static/')
                assert name in ('index.html','app.js','network.js','style.css','icon.svg','select-arrow.svg')
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
            def nav(value):page.evaluate('(r)=>navigate(r)',value);page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r',arg=value)
            page.goto('http://localhost:8765/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap();page.wait_for_selector('[data-drive-card]')
            expect(page.locator('[data-drive-card="legacy"] .drive-recovery-progress')).to_contain_text('4:00 remaining')
            nav('drive/legacy');expect(page.locator('.drive-recovery-progress')).to_contain_text('4:00 remaining')
            api.remaining=117;page.evaluate('()=>pollLive()');expect(page.locator('.drive-recovery-progress')).to_contain_text('1:57 remaining')
            nav('apps');card=page.locator(f'[data-container-id="{ERUGO}"]')
            expect(card.locator('.app-recovery-notice')).to_contain_text('1:57 remaining')
            assert card.locator('button,input,select,textarea').evaluate_all('(es)=>es.every(e=>e.matches(":disabled"))')
            expect(page.locator(f'[data-container-id="{OTHER}"] [data-action="docker-start"]')).to_be_enabled()
            api.expired=True;api.remaining=0;page.evaluate('()=>pollLive()');expect(card.locator('.app-recovery-notice')).to_contain_text(FAILED)
            assert card.locator('.app-recovery-notice').evaluate('(e)=>getComputedStyle(e).opacity')=='1'
            page.screenshot(path=str(shots/f'ui35-apps-{width}.png'),full_page=True)
            nav('drive/legacy');expect(page.locator('.drive-recovery-progress')).to_contain_text(FAILED)
            page.screenshot(path=str(shots/f'ui35-failed-{width}.png'),full_page=True)
            api.unavailable=True;page.evaluate('()=>pollLive()');expect(page.locator('.drive-recovery-progress')).to_have_count(0)
            api.unavailable=False;api.waiting=False;page.evaluate('()=>pollLive()');expect(page.locator('.drive-recovery-progress')).to_have_count(0)
            nav('advanced');field=page.get_by_role('spinbutton',name='Drive return timeout (minutes)')
            expect(field).to_have_value('5');expect(page.get_by_text('Report recovery failure if the drive has not returned within this time.',exact=True)).to_be_visible()
            field.fill('7');button=page.locator('[data-action="timings-save"]');expect(button).to_be_enabled();button.tap();page.wait_for_function('()=>!apiBusy')
            expect(field).to_have_value('7');assert api.configs['legacy']['recovery']['return_timeout_minutes']==7
            field.fill('0');expect(button).to_be_disabled();field.fill('1441');expect(button).to_be_disabled()
            field.fill('8');api.fail_save=True;button.tap();expect(page.locator('[data-settings-status="timings"].error')).to_be_visible();expect(field).to_have_value('8')
            assert api.configs['legacy']['recovery']['return_timeout_minutes']==7
            page.screenshot(path=str(shots/f'ui35-timing-{width}.png'),full_page=True)
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1');assert not errors,errors
            context.close();print('PASS UI35',width,'px: backend countdown/expiry, app restrictions, unrelated app, timing default/save/range/failure.',flush=True)
        browser.close()

if __name__=='__main__':run()
