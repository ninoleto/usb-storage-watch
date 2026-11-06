# SPDX-License-Identifier: MIT
"""Whole-card admission and blue selectors; synthetic APIs and production CSP."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
from test_ui30_browser import API as PriorAPI, ERUGO, OTHER, ROOT, CSP, MESSAGE
from test_ui29_browser import OLD

BLUE='rgb(21, 43, 70)'
AMBER='rgb(244, 205, 120)'


class API(PriorAPI):
    def __init__(self):super().__init__();self.old_incident=False
    def reply(self,req):
        result=super().reply(req)
        if urlsplit(req['url']).path.endswith('/docker-overview') and result['status']==200:
            for row in result['body']['containers']:
                if row['id']==OLD and self.old_incident:row['control_block']=MESSAGE
        return result


def run():
    shots=Path(os.environ.get('USW_UI31_SCREENSHOTS','/tmp/usw-ui31-shots'));shots.mkdir(parents=True,exist_ok=True)
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
                if name not in ('index.html','app.js','network.js','style.css','icon.svg'):route.abort();return
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(10000)
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda m:errors.append(m.text) if m.type=='error' and 'Content Security Policy' in m.text else None)
            def nav(value):
                page.evaluate('(r)=>navigate(r)',value);page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r',arg=value)
            def poll():page.evaluate('()=>pollLive()')
            page.goto('http://localhost:8765/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap();page.wait_for_selector('[data-drive-card]');nav('apps')
            card=page.locator(f'[data-container-id="{ERUGO}"]');other=page.locator(f'[data-container-id="{OTHER}"]')
            card.locator('[data-app-panel="boot"] [role="switch"]').uncheck()
            images=card.locator('[data-app-panel="recovery"] .app-images');images.locator('summary').tap()
            advanced=card.locator('.app-advanced');advanced.locator('summary').tap()
            card.locator('[data-action="app-review"]').tap();expect(card.locator('[data-action="app-save"]')).to_be_enabled()
            draft=page.evaluate('id=>JSON.stringify(dockerView(id).appDraft)',ERUGO)
            api.incidents=2;poll()
            notice=card.locator('.app-recovery-notice');expect(notice).to_have_text(MESSAGE);expect(notice).to_be_visible()
            assert notice.evaluate('(e)=>getComputedStyle(e).color')==AMBER
            assert notice.evaluate('(e)=>{for(;e;e=e.parentElement)if(Number(getComputedStyle(e).opacity)!==1)return false;return true;}')
            assert not notice.evaluate('(e)=>!!e.closest("fieldset")')
            assert card.locator('button,input,select,textarea').evaluate_all('(els)=>els.every(e=>e.matches(":disabled"))')
            switches=card.locator('[role="switch"]');assert switches.count()==2
            assert switches.evaluate_all('(els)=>els.every(e=>e.disabled&&getComputedStyle(e).cursor==="not-allowed"&&getComputedStyle(e).backgroundColor==="rgb(70, 83, 98)"&&Number(getComputedStyle(e).opacity)<.6)')
            expect(images).to_have_attribute('open','');expect(advanced).to_have_attribute('open','')
            # Pointer, keyboard and stale/programmatic handlers cannot edit or collapse.
            for el in switches.all():el.locator('..').click(force=True);el.dispatch_event('change');el.dispatch_event('keydown',dict(key=' '))
            images.locator('summary').click(force=True);advanced.locator('summary').dispatch_event('keydown',dict(key='Enter'))
            card.locator('.docker-container-header').click(force=True)
            page.evaluate("id=>{dockerView(id).appConflict=true;refreshDockerDOM();reloadDockerSettings(id);act('app-cancel',id);act('docker-reload',id);}",ERUGO)
            expect(card.locator('[data-action="docker-reload"]')).to_be_disabled()
            assert page.evaluate('id=>JSON.stringify(dockerView(id).appDraft)',ERUGO)==draft
            expect(images).to_have_attribute('open','');expect(advanced).to_have_attribute('open','')
            expect(card.locator('.docker-container-body')).to_be_visible();assert not api.saves and api.action_counts[ERUGO]==0
            other.locator('[data-action="docker-start"]').tap();expect(other.locator('.docker-live-state')).to_contain_text('Running')
            # Poll updates live status while the card remains fully locked.
            api.container(ERUGO)['state']='running';api.incidents=1;poll()
            expect(card.locator('.docker-live-state')).to_contain_text('Running');expect(switches.first).to_be_disabled()
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(shots/f'ui31-lock-{width}.png'),full_page=True)
            api.incidents=0;poll();expect(notice).to_be_hidden();expect(switches.first).to_be_enabled()
            expect(images).to_have_attribute('open','');assert page.evaluate('id=>JSON.stringify(dockerView(id).appDraft)',ERUGO)==draft
            # A previously opened manual confirmation gets live status and refuses submit.
            card.locator('[data-action="docker-stop"]').tap();confirm=page.locator('#modal-root [data-action="confirmed-action"]')
            expect(confirm).to_be_enabled();api.incidents=1;poll();expect(confirm).to_be_disabled()
            expect(page.locator('#modal-root .app-recovery-notice')).to_have_text(MESSAGE)
            confirm.click(force=True);assert api.action_counts[ERUGO]==0
            page.locator('#modal-root [data-action="close-modal"]').first.tap();api.incidents=0;poll()
            # Locked collapsed cards still show readable status and keep expansion state.
            card.locator('.docker-container-header').tap();api.incidents=1;poll()
            expect(card.locator('.docker-container-body')).to_be_hidden();expect(notice).to_be_visible()
            card.locator('.docker-container-header').click(force=True);expect(card.locator('.docker-container-body')).to_be_hidden()
            api.incidents=0;poll();expect(card.locator('.docker-container-body')).to_be_hidden()
            # Missing identities freeze pending review, target and expansion as well.
            old=page.locator(f'[data-unavailable-entry="{OLD}"]');old.locator('summary').tap();old.locator('[data-action="entry-reconnect"]').tap()
            picker=old.locator('select');expect(picker).to_be_enabled();assert picker.evaluate('(e)=>getComputedStyle(e).backgroundColor')==BLUE
            picker.select_option(OTHER);old.locator('[data-action="entry-review"]').tap();expect(old.locator('[data-action="entry-apply"]')).to_be_enabled()
            api.old_incident=True;poll();expect(old.locator('.app-recovery-notice')).to_have_text(MESSAGE)
            assert old.locator('button,input,select').evaluate_all('(els)=>els.every(e=>e.matches(":disabled"))')
            old.locator('summary').click(force=True);expect(old).to_have_attribute('open','')
            page.evaluate("id=>act('entry-cancel',id)",OLD);assert page.evaluate('id=>dockerView(id).entryTarget',OLD)==OTHER
            assert not api.entry_writes;api.old_incident=False;poll();expect(old.locator('select')).to_have_value(OTHER)
            # Shared dropdown color, dimensions and pointer/keyboard interaction.
            for route,select_id in [('advanced','advanced-drive'),('images','image-drive'),('history','history-filter')]:
                nav(route);trigger=page.locator('#'+select_id+'-control');expect(trigger).to_be_visible()
                assert trigger.evaluate('(e)=>getComputedStyle(e).backgroundColor')==BLUE
                assert trigger.bounding_box()['height']>=64
                trigger.focus();page.keyboard.press('ArrowDown');expect(page.locator('.touch-picker')).to_be_visible()
                page.keyboard.press('End');page.keyboard.press('Home');page.keyboard.press('Enter');expect(page.locator('.touch-picker')).to_have_count(0)
                expect(page.locator('#'+select_id+'-control')).to_be_focused()
                trigger=page.locator('#'+select_id+'-control');assert trigger.evaluate('(e)=>getComputedStyle(e).outlineStyle')!='none'
                trigger.tap();expect(page.locator('.touch-picker')).to_be_visible();page.locator('.picker-option:not(:disabled)').first.tap()
                assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
                if route=='advanced':
                    expect(page.locator('.timing-settings > .standby-subsection')).to_be_visible()
                    assert page.locator('#standby-idle').evaluate('(e)=>getComputedStyle(e).backgroundColor')!=BLUE
                page.screenshot(path=str(shots/f'ui31-{route}-{width}.png'),full_page=True)
            assert not errors,errors;assert not api.saves and not api.entry_writes and api.action_counts[ERUGO]==0
            context.close();print('PASS UI31',width,'px: full card lock, stale modal, live status, preserved drafts/expansion, unrelated app, blue keyboard/touch selectors',flush=True)
        browser.close()


if __name__=='__main__':run()
