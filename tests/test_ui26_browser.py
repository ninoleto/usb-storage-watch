# SPDX-License-Identifier: MIT
"""Packaged guided setup with intercepted APIs; no real Docker/source mutations."""
import copy
import os
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from test_ui25_browser import API as PriorAPI
from test_ui20_browser import ROOT, ERUGO, CSP


class API(PriorAPI):
    def __init__(self):
        super().__init__();self.applied=[];self.plans=[];self.blocked=False
        self.setup=dict(policy=dict(Name='unless-stopped',MaximumRetryCount=0),manager='Docker Compose',
                        conflicts=['Docker can restart independently of storage readiness.'],available=True)
        self.boot['settings']=[dict(id=ERUGO,name='sample-app',enabled=True,drives=[dict(id='legacy',images=[])])]

    def reply(self, req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1]
        if self.session and action=='docker-setup-plan':
            self.plans.append(req['data']);assert req['data']==dict(id=ERUGO,name='sample-app')
            return dict(status=200,body=dict(id=ERUGO,name='sample-app',token='preview-only',allowed=not self.blocked,
                policy=self.setup['policy'],live_change=True,
                explanation='Manage computer startup and storage recovery, not a general application-crash restart watchdog.',
                compose=dict(service='app',files=['/srv/example/compose.yaml','/srv/example/production.override.yaml'],
                    file='/srv/example/production.override.yaml',changes=True,source_before='unless-stopped',source_after='"no"'),
                storage=dict(boot=[dict(id='legacy',images=[])],recovery=[]),
                instructions=['Effective Compose configuration is ambiguous. Set services.app.restart to "no" in the authoritative override and validate with the original environment.'] if self.blocked else []))
        if self.session and action=='docker-setup-apply':
            assert not self.blocked
            assert req['data']==dict(id=ERUGO,name='sample-app',token='preview-only',confirm=True)
            self.applied.append(copy.deepcopy(req['data']))
            self.setup.update(policy=dict(Name='no',MaximumRetryCount=0),original_policy=dict(Name='unless-stopped',MaximumRetryCount=0),source_verified=True,conflicts=[])
            return dict(status=200,body=dict(ok=True,message='Restart policy verified as no. Container execution unchanged.',setup=self.setup))
        result=super().reply(req)
        if action=='docker-overview' and result['status']==200:
            for row in result['body']['containers']:
                if row['id']==ERUGO:row['setup']=copy.deepcopy(self.setup)
        return result


def run():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,390,768,1440):
            api=API();errors=[];context=browser.new_context(viewport=dict(width=width,height=1000),has_touch=True)
            def serve(route):
                req=route.request;path=urlsplit(req.url).path;headers={'Content-Security-Policy':CSP,'Cache-Control':'no-store'}
                if path.startswith('/api/'):
                    value=api.reply(dict(url=req.url,method=req.method,data=req.post_data_json if req.method=='POST' else None))
                    route.fulfill(status=value['status'],json=value['body'],headers=headers);return
                name='index.html' if path=='/' else path.removeprefix('/static/')
                if name not in ('index.html','app.js','network.js','style.css','icon.svg'):
                    route.fulfill(status=404,body='');return
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://localhost:8765/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap()
            expect(page.locator('[data-drive-card]')).to_have_count(2)
            page.evaluate("()=>navigate('apps')");page.wait_for_function("()=>!apiBusy&&!routeLoading&&lastLoadedRoute==='apps'")
            card=page.locator(f'[data-container-id="{ERUGO}"]');setup=card.locator('.docker-setup-controls')
            expect(card.locator('.boot-choice').filter(has=page.locator('[data-change="boot-enabled"]'))).to_contain_text('Start automatically when the computer starts')
            expect(setup).to_contain_text('unless-stopped');expect(setup).to_contain_text('Docker Compose')
            expect(setup).to_contain_text('ordinary folders');expect(setup).to_contain_text('not a general application-crash restart watchdog')
            before=page.evaluate('id=>JSON.stringify([dockerView(id).draft,dockerView(id).bootDraft])',ERUGO)
            card.locator('[data-action="docker-setup-plan"]').tap()
            expect(setup.locator('.setup-diff')).to_contain_text('+ restart: "no"');assert not api.applied
            expect(setup.locator('.setup-review')).to_contain_text('backed up privately')
            card.locator('[data-action="docker-setup-apply"]').tap()
            expect(setup.locator(':scope > [role="status"]')).to_have_text('Restart policy verified as no. Container execution unchanged.')
            assert len(api.applied)==1
            assert page.evaluate('id=>JSON.stringify([dockerView(id).draft,dockerView(id).bootDraft])',ERUGO)==before
            api.blocked=True;card.locator('[data-action="docker-setup-plan"]').tap()
            expect(setup).to_contain_text('Setup is incomplete');expect(setup.locator('[data-action="docker-setup-apply"]')).to_have_count(0)
            assert len(api.applied)==1 and len(api.plans)==2
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'),width
            assert not errors,errors;context.close()
            print(f'PASS UI26 {width}px: policy/manager/storage, exact preview, explicit confirmation, unchanged drafts and ambiguous-source instructions')
        browser.close()


if __name__=='__main__':run()
