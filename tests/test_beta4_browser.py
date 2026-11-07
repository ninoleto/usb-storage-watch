"""Real HTTP/Chromium/broker/Compose and temporary files; no live Docker/services."""
import os
from pathlib import Path
import threading
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server,WSGIRequestHandler
from test_beta4_permissions import Permissions,IDENTITY

class Quiet(WSGIRequestHandler):
    def log(self,*a,**kw):pass

def run():
    shots=Path(os.environ.get('USW_BETA4_SCREENSHOTS','/tmp/usw-beta4-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,768,1440):
            f=Permissions();f.setUp();server=None;thread=None
            try:
                f.source.chmod(0o664);f.root.chmod(0o775);token=f.f.main.management_token();media=f.media_snapshot()
                server=make_server('127.0.0.1',0,lambda e,s:[],request_handler=Quiet)
                server.app=f.f.main.web.create_app(dict(f.b.common.DEFAULT,lan=False,http_port=server.server_port,port=server.server_port),f.f.main.broker.handle)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                context=browser.new_context(viewport=dict(width=width,height=1100),has_touch=True)
                page=context.new_page();page.set_default_timeout(15000);errors=[];posts=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda req:posts.append(req.url.rsplit('/',1)[-1]) if req.method=='POST' else None)
                page.goto(f'http://127.0.0.1:{server.server_port}/#apps')
                page.locator('#usw-login-token').fill(token);page.locator('#usw-login-form button').tap()
                page.wait_for_function('()=>!routeLoading&&dockerPage.loaded')
                card=page.locator(f'[data-container-id="{IDENTITY}"]');header=card.locator('.docker-container-header');badges=header.locator('.app-saved-indicators')
                expect(badges).to_contain_text('Startup not configured');expect(badges).to_contain_text('Recovery not configured')
                for kind in ('boot','recovery'):
                    card.locator(f'[data-change="app-enabled"][data-kind="{kind}"]').check()
                    card.locator(f'[data-change="app-drive"][data-kind="{kind}"][data-drive="legacy"]').check()
                expect(badges.locator('.enabled')).to_have_count(0)
                expect(card.locator('[data-app-panel="boot"] .app-configuration-status')).to_have_text('Not configured')
                card.locator('[data-action="app-review"]').tap()
                expect(card.locator('.permission-issue').first).to_contain_text('Parent directory')
                expect(card.locator('.permission-issue').first).to_contain_text(str(f.root))
                expect(card.locator('[data-action="app-permission"]')).to_have_count(0)
                expect(card.locator('[data-action="app-save"]')).to_have_count(0)
                assert f.media_snapshot()==media and not f.docker.updates
                card.screenshot(path=str(shots/f'ancestor-{width}.png'))
                # Simulated operator resolves the ancestor. The app never chmods it.
                f.root.chmod(0o700);media=f.media_snapshot()
                card.locator('[data-action="app-cancel"]').tap();card.locator('[data-action="app-review"]').tap()
                issue=card.locator('.permission-issue').first
                expect(issue).to_contain_text('Compose file');expect(issue).to_contain_text('media-reader')
                expect(issue.locator('details')).not_to_have_attribute('open','')
                issue.locator('summary').tap();expect(issue).to_contain_text('fixture-shared');expect(issue).to_contain_text('0664')
                card.locator('[data-action="app-permission"]').tap()
                dialog=page.get_by_role('dialog');expect(dialog).to_contain_text('0664 → 0644');expect(dialog).to_contain_text(str(f.source))
                expect(dialog).to_contain_text('media-reader');assert f.source.stat().st_mode&0o777==0o664
                dialog.screenshot(path=str(shots/f'permission-review-{width}.png'))
                # Stale confirmation cannot modify a changed mode, or be resubmitted.
                f.source.chmod(0o666);page.locator('#modal-root [data-action="confirmed-action"]').tap()
                expect(dialog).to_contain_text('nothing was changed')
                expect(page.locator('#modal-root [data-action="confirmed-action"]')).to_be_disabled()
                expect(dialog).not_to_contain_text('choose Unmount safely')
                assert f.source.stat().st_mode&0o777==0o666 and not f.docker.updates
                expect(badges.locator('.enabled')).to_have_count(0)
                page.locator('#modal-root [data-action="close-modal"]').tap();f.source.chmod(0o664)
                card.locator('[data-action="app-review"]').tap();card.locator('[data-action="app-permission"]').tap()
                page.locator('#modal-root [data-action="confirmed-action"]').tap()
                page.wait_for_function('(id)=>!dockerView(id).appBusy&&dockerView(id).appPlan?.allowed===true',arg=IDENTITY)
                expect(badges).to_contain_text('Startup not configured');expect(badges).to_contain_text('Recovery not configured')
                expect(card.locator('.app-save-status')).to_contain_text('File permissions updated and verified')
                assert f.source.stat().st_mode&0o777==0o644 and not f.docker.updates and f.media_snapshot()==media
                assert 'DO-NOT-EXPOSE' not in page.locator('body').inner_text()
                card.locator('[data-action="app-save"]').tap()
                expect(badges).to_contain_text('Startup enabled');expect(badges).to_contain_text('Recovery enabled')
                expect(card.locator('.app-save-status')).to_contain_text('Settings saved and verified')
                for badge in badges.locator('.enabled').all():
                    expect(badge).to_have_css('border-top-width','2px');expect(badge).to_have_css('border-top-color','rgb(71, 131, 101)')
                header.tap();expect(card.locator('.docker-container-body')).to_be_hidden()
                for badge in badges.locator('.enabled').all():expect(badge).to_have_css('border-top-color','rgb(71, 131, 101)')
                page.screenshot(path=str(shots/f'saved-collapsed-{width}.png'),full_page=True)
                header.tap();card.locator('[data-change="app-enabled"][data-kind="boot"]').uncheck()
                expect(badges).to_contain_text('Startup enabled')  # Saved on until the off change is saved.
                card.locator('[data-action="app-review"]').tap();card.locator('[data-action="app-save"]').tap()
                expect(badges).to_contain_text('Startup off');expect(badges.locator('.enabled')).to_have_count(1)
                assert f.media_snapshot()==media and len(f.docker.updates)==1
                assert posts.count('docker-permission-apply')==2  # One refusal, one explicit fresh confirmation.
                assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
                assert not errors,errors;context.close()
                print(f'PASS {width}px: exact ancestor/file diagnostics, explicit/stale permission review, real broker, preserved media, unsaved state and green saved badges including collapse',flush=True)
            finally:
                if thread and thread.is_alive():server.shutdown()
                if server:server.server_close()
                f.doCleanups()
        browser.close()

if __name__=='__main__':run()
