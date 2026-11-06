# SPDX-License-Identifier: MIT
"""Delayed/refused safe unmount UI; isolated HTTP, never real storage operations."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from test_ui32_browser import API, ROOT, CSP

def run():
    shots=Path(os.environ.get('USW_UI33_SCREENSHOTS','/tmp/usw-ui33-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,768,1440):
            api=API();pending=[];requests=[];errors=[]
            context=browser.new_context(viewport=dict(width=width,height=1100),has_touch=True)
            def serve(route):
                req=route.request;path=urlsplit(req.url).path;headers={'Content-Security-Policy':CSP,'Cache-Control':'no-store'}
                if path.startswith('/api/'):
                    request=dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None)
                    if path.endswith('/disk-operation') and request['data'].get('action')=='unmount':
                        requests.append(request);pending.append(route);return
                    value=api.reply(request);route.fulfill(status=value['status'],json=value['body'],headers=headers);return
                name='index.html' if path=='/' else path.removeprefix('/static/')
                assert name in ('index.html','app.js','network.js','style.css','icon.svg','select-arrow.svg'), name
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(10000)
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://localhost:8765/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap();page.wait_for_selector('[data-drive-card]')
            page.evaluate("()=>navigate('drive/legacy')");page.wait_for_function("()=>!apiBusy&&!routeLoading&&lastLoadedRoute==='drive/legacy'")
            for code in (400,503):
                page.locator('[data-action="toggle-mount"]').tap();dialog=page.locator('#modal-root .modal')
                confirm=dialog.locator('[data-action="confirmed-action"]');confirm.tap()
                expect(dialog.locator('.modal-progress')).to_contain_text('Stopping dependent apps')
                expect(confirm).to_be_disabled();expect(dialog.locator('[data-action="close-modal"]')).to_be_disabled()
                count=len(requests);confirm.evaluate('(e)=>e.click()');page.keyboard.press('Escape')
                expect(dialog).to_be_visible();assert len(requests)==count
                page.screenshot(path=str(shots/f'ui33-running-{code}-{width}.png'),full_page=True)
                assert len(pending)==1
                pending.pop().fulfill(status=code,json=dict(error='Another operation controls this drive. Wait for it to finish.'))
                expect(dialog).to_contain_text('This confirmation has been used.')
                expect(dialog).to_contain_text('Wait for it to finish.')
                expect(dialog.locator('.modal-progress')).to_have_count(0)
                expect(confirm).to_be_disabled();expect(dialog.locator('[data-action="close-modal"]')).to_be_enabled()
                confirm.evaluate('(e)=>e.click()');assert len(requests)==count
                page.screenshot(path=str(shots/f'ui33-refused-{code}-{width}.png'),full_page=True)
                assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
                dialog.locator('[data-action="close-modal"]').tap()
            # Fresh review succeeds; the previous one-use confirmation is never replayed.
            page.locator('[data-action="toggle-mount"]').tap();dialog.locator('[data-action="confirmed-action"]').tap()
            expect(dialog.locator('.modal-progress')).to_be_visible()
            result=api.reply(requests[-1]);pending.pop().fulfill(status=result['status'],json=result['body'])
            expect(dialog).to_have_count(0);expect(page.locator('[data-action="toggle-mount"]')).to_contain_text('Mount drive')
            assert len(requests)==3 and api.reviews==3 and len({r['data']['token'] for r in requests})==3
            assert not errors,errors;context.close()
            print('PASS UI33',width,'px: pending progress, duplicate/Escape lock, refused/uncertain single-use feedback, fresh review and success.',flush=True)
        browser.close()

if __name__=='__main__':run()
