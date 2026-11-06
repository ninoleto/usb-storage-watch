# SPDX-License-Identifier: MIT
"""UI32 selector contrast and reviewed unmount; synthetic HTTP only, production CSP."""
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
from test_ui31_browser import API as PriorAPI,ROOT,CSP,ERUGO,OTHER,OLD,BLUE

MESSAGE='Safe unmount in progress. Controls are temporarily unavailable.'
class API(PriorAPI):
    def __init__(self):
        super().__init__();self.mounted['legacy']=True;self.unmounts=[];self.reviews=0;self.intent=False;self.refuse=False
    def reply(self,req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1];data=req.get('data') or {}
        if action=='unmount-plan':
            assert req['method']=='GET';self.reviews+=1
            return dict(status=200,body=dict(token='review-'+str(self.reviews),apps=[dict(id=ERUGO,name='sample-app',running=True,images=['sample-volume']),dict(id='e'*64,name='already-stopped',running=False,images=[])],message='Apps stay stopped; mounting the drive again will not start them. Monitoring will stop.'))
        if action=='disk-operation' and data.get('action')=='unmount':
            self.unmounts.append(copy.deepcopy(data));assert data['confirm'] is True and data['token']=='review-'+str(self.reviews)
            if self.refuse:return dict(status=400,body=dict(error='Drive or app changed since review. Nothing was stopped or unmounted.'))
            self.mounted['legacy']=False
            return dict(status=200,body=dict(ok=True,message='Filesystem safely unmounted. Apps left stopped: sample-app.'))
        result=super().reply(req)
        if action=='docker-overview' and self.intent:
            for row in result['body']['containers']:
                if row['id']==ERUGO:row['control_block']=MESSAGE
        return result

def run():
    shots=Path(os.environ.get('USW_UI32_SCREENSHOTS','/tmp/usw-ui32-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,390,768,1440):
            api=API();errors=[];arrows=[];context=browser.new_context(viewport=dict(width=width,height=1100),has_touch=True)
            def serve(route):
                req=route.request;path=urlsplit(req.url).path;headers={'Content-Security-Policy':CSP,'Cache-Control':'no-store'}
                if path.startswith('/api/'):
                    value=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None))
                    route.fulfill(status=value['status'],json=value['body'],headers=headers);return
                name='index.html' if path=='/' else path.removeprefix('/static/')
                if name not in ('index.html','app.js','network.js','style.css','icon.svg','select-arrow.svg'):route.fulfill(status=404,body='');return
                if name=='select-arrow.svg':arrows.append(name)
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(10000)
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda m:errors.append(m.text) if m.type=='error' and 'Content Security Policy' in m.text else None)
            def nav(value):
                page.evaluate('(r)=>navigate(r)',value);page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r',arg=value)
            page.goto('http://localhost:8765/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap();page.wait_for_selector('[data-drive-card]')
            for route,selector in [('advanced','advanced-drive'),('images','image-drive'),('history','history-filter')]:
                nav(route);trigger=page.locator('#'+selector+'-control')
                values=trigger.evaluate('(e)=>{let s=getComputedStyle(e);return [s.borderTopWidth,s.borderTopColor,s.backgroundColor,getComputedStyle(e.querySelector(".picker-mark")).color]}')
                assert values==['2px','rgb(255, 255, 255)',BLUE,'rgb(255, 255, 255)'],values
                before=trigger.bounding_box()
                unchanged=trigger.evaluate('(e)=>{const a=e.getBoundingClientRect();e.style.borderWidth="1px";e.style.padding="12px 16px";const b=e.getBoundingClientRect();e.removeAttribute("style");return a.height===b.height&&a.width===b.width;}')
                assert unchanged,'Selector dimensions changed'
                trigger.focus();page.keyboard.press('ArrowDown');expect(page.locator('.touch-picker')).to_be_visible();page.keyboard.press('Home');page.keyboard.press('Enter')
                page.wait_for_function('()=>!apiBusy&&!routeLoading');trigger=page.locator('#'+selector+'-control');page.keyboard.press('Tab');trigger.focus();expect(trigger).to_have_css('outline-style','solid')
                trigger.tap();page.locator('.picker-option:not(:disabled)').first.tap()
                # A disabled source select must also disable its custom trigger.
                disabled=page.locator('#'+selector).evaluate('(e)=>{e.disabled=true;syncTouchSelects();const b=document.getElementById(e.id+"-control"),r=[b.disabled,getComputedStyle(b).opacity];e.disabled=false;syncTouchSelects();return r;}')
                assert disabled[0] and float(disabled[1])<.6,disabled
                assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(shots/f'ui32-{route}-{width}.png'),full_page=True)
            nav('apps');old=page.locator(f'[data-unavailable-entry="{OLD}"]');old.locator('summary').tap();old.locator('[data-action="entry-reconnect"]').tap()
            native=old.locator('select');expect(native).to_be_visible()
            assert native.evaluate('(e)=>getComputedStyle(e).borderTopWidth')=='2px'
            assert native.evaluate('(e)=>getComputedStyle(e).borderTopColor')=='rgb(255, 255, 255)'
            assert 'select-arrow.svg' in native.evaluate('(e)=>getComputedStyle(e).backgroundImage');native.select_option(OTHER)
            card=page.locator(f'[data-container-id="{ERUGO}"]');card.locator('[data-app-panel="boot"] [role="switch"]').uncheck()
            images=card.locator('[data-app-panel="recovery"] .app-images');images.locator('summary').tap()
            draft=page.evaluate('id=>JSON.stringify(dockerView(id).appDraft)',ERUGO);api.intent=True;page.evaluate('()=>pollLive()')
            expect(card.locator('.app-recovery-notice')).to_have_text(MESSAGE)
            assert card.locator('button,input,select,textarea').evaluate_all('(els)=>els.every(e=>e.matches(":disabled"))')
            assert card.locator('.app-recovery-notice').evaluate('(e)=>getComputedStyle(e).opacity')=='1'
            expect(images).to_have_attribute('open','');api.intent=False;page.evaluate('()=>pollLive()');expect(card.locator('.app-recovery-notice')).to_be_hidden()
            assert page.evaluate('id=>JSON.stringify(dockerView(id).appDraft)',ERUGO)==draft
            nav('drive/legacy');button=page.locator('[data-action="toggle-mount"]');expect(button).to_be_enabled();button.tap()
            dialog=page.locator('#modal-root');expect(dialog).to_contain_text('Apps to stop: sample-app (aaaaaaaaaaaa) · images: sample-volume.');expect(dialog).to_contain_text('Already stopped: already-stopped.')
            expect(dialog).to_contain_text('mounting the drive again will not start them');assert not api.unmounts
            page.screenshot(path=str(shots/f'ui32-unmount-{width}.png'),full_page=True)
            dialog.locator('[data-action="close-modal"]').tap();assert not api.unmounts
            button.tap();api.refuse=True;dialog.locator('[data-action="confirmed-action"]').tap()
            expect(page.locator('body')).to_contain_text('Drive or app changed since review. Nothing was stopped or unmounted.');assert len(api.unmounts)==1
            # No automatic transport/error retry and no unrelated mutation.
            assert not api.saves and not api.entry_writes and not api.action_counts[ERUGO]
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1');assert arrows and not errors,errors
            context.close();print('PASS UI32',width,'px: white borders/arrows, unchanged touch dimensions, focus/disabled states, native selector, unmount review/cancel/stale refusal, app lock and retained draft.',flush=True)
        browser.close()

if __name__=='__main__':run()
