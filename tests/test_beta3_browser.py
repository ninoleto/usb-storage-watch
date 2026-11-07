"""Real localhost HTTP/Chromium and authenticated broker; simulated host boundaries.

No real storage, service, Docker or external email operation. Run explicitly with
Playwright and Chromium; USW_GUI_PAYLOAD can select an extracted Debian payload.
"""
import os
from pathlib import Path
import threading
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler
from test_beta3_setup import RecoveryPlanning, SMTP

class Quiet(WSGIRequestHandler):
    def log(self, *args, **kwargs): pass

def run():
    shots=Path(os.environ.get('USW_BETA3_SCREENSHOTS','/tmp/usw-beta3-shots'))
    shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/google-chrome'),
                                  headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,768,1440):
            f=RecoveryPlanning();f.setUp();server=None;thread=None
            try:
                f.adopt();token=f.m.management_token()
                server=make_server('127.0.0.1',0,lambda e,s:[],request_handler=Quiet)
                config=dict(f.b.common.DEFAULT,http_port=server.server_port,port=server.server_port,lan=False)
                server.app=f.m.web.create_app(config,f.m.broker.handle)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                context=browser.new_context(viewport=dict(width=width,height=1000),has_touch=True)
                page=context.new_page();page.set_default_timeout(12000);errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/#drive/legacy')
                page.locator('#usw-login-token').fill(token);page.locator('#usw-login-form button').tap()
                page.wait_for_function('()=>!routeLoading&&state.drives.length>0')
                page.locator('[data-action="toggle-monitoring"]').tap()
                page.wait_for_function('()=>state.drives[0].monitoring===true')
                recovery=page.locator('[data-key="recovery"]')
                recovery.tap()
                expect(page.get_by_role('heading',name='Enable automatic recovery?')).to_be_visible()
                page.locator('#modal-root [data-action="confirmed-action"]').tap()
                page.wait_for_function('()=>!modalPending&&state.drives[0].recovery===true')
                assert f.b.configuration()['recovery']['mount'] and f.m.active
                saved=f.b.s.CONFIG.read_bytes();notifications=page.locator('[data-key="notifications"]')
                notifications.tap()
                message=notifications.locator('..').get_by_role('status')
                expect(message).to_contain_text('Email is not configured. Open Email & Notifications')
                expect(notifications).not_to_be_checked();expect(notifications).to_be_enabled()
                assert f.b.s.CONFIG.read_bytes()==saved and f.m.active
                assert 'enabled.' not in message.inner_text()
                page.locator('#drive-summary').locator('..').screenshot(path=str(shots/f'missing-email-{width}.png'))
                assert f.request('smtp',SMTP)['status']==200
                assert f.request('test-email',{})['data']['accepted']
                notifications.tap()
                expect(message).to_contain_text('email notifications enabled')
                expect(notifications).to_be_checked()
                assert f.b.configuration()['notifications']['enabled'] and f.m.active
                assert 'not configured' not in message.inner_text()
                assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
                assert not errors,errors
                context.close()
                print(f'PASS {width}px: real HTTP/session/broker recovery review, missing SMTP refusal, unchanged monitor, toggle rollback and successful retry',flush=True)
            finally:
                if thread and thread.is_alive():server.shutdown()
                if server:server.server_close()
                f.doCleanups()
        browser.close()

if __name__=='__main__':run()
