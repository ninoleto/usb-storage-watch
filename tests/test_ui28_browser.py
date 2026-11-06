# SPDX-License-Identifier: MIT
"""Responsive app editor, production CSP and isolated synthetic host responses."""
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from test_ui26_browser import API as PriorAPI
from test_ui20_browser import ROOT, ERUGO, IMAGE, CSP


class API(PriorAPI):
    def __init__(self):
        super().__init__();self.reviews=[];self.saves=[];self.partial=False;self.lost=False;self.app_revision=1
        self.apps=[dict(id=row['id'],name=row['name'],boot=dict(enabled=row['id']==ERUGO,drives=[dict(id='legacy',images=[IMAGE])] if row['id']==ERUGO else []),
                  recovery=dict(enabled=row['id']==ERUGO,drives=[dict(id='drive-b',images=[]),dict(id='legacy',images=[IMAGE])] if row['id']==ERUGO else [])) for row in self.containers]
        for d in self.docker_drives:d.update(mountpoint='/mnt/'+d['id'],monitoring=d['id']!='legacy',monitor_enabled=True,automatic_mount=True)
        self.setup.update(compose_source='/srv/example/compose.yaml',compose_service='app')

    def reply(self,req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1];data=req.get('data') or {}
        if self.session and action=='docker-app-plan':
            assert data['revision']=='apps-'+str(self.app_revision)
            self.reviews.append(copy.deepcopy(data));desired=data['settings'];actual=next(x for x in self.apps if x['id']==desired['id'])
            changed=[k for k in ('boot','recovery') if desired[k]!=actual[k]];assert changed
            p=super().reply(dict(req,url=req['url'].replace(action,'docker-setup-plan'),data=dict(id=desired['id'],name=desired['name'])))['body'] if any(desired[k]['enabled'] for k in changed) else None
            if p and self.blocked:p['instructions']=['Use the authoritative Portainer stack editor or linked Git source to set restart: "no" on only the selected service. Source is externally managed and has not been updated.']
            self.pending=dict(token='review-'+str(len(self.reviews)),settings=copy.deepcopy(desired),changed=changed,policy=p,allowed=not p or p['allowed'])
            return dict(status=200,body=copy.deepcopy(self.pending))
        if self.session and action=='docker-app-save':
            assert data==dict(token=self.pending['token'],confirm=True);assert self.pending['allowed'];self.saves.append(copy.deepcopy(data))
            desired=self.pending['settings'];actual=next(x for x in self.apps if x['id']==desired['id'])
            if self.partial:
                actual['recovery']=copy.deepcopy(desired['recovery']);result=dict(ok=False,applied=['Drive recovery saved'],message='Computer startup was not confirmed. Refresh before reviewing again.')
            else:
                actual.update(copy.deepcopy(desired));result=dict(ok=True,applied=['Computer startup saved','Drive recovery saved'],message='Settings saved and verified.')
            self.app_revision+=1
            if self.lost:return dict(status=503,body=dict(error='Save response lost'))
            return dict(status=200,body=result)
        result=super().reply(req)
        if action=='docker-overview' and result['status']==200:
            result['body']['applications']=dict(revision='apps-'+str(self.app_revision),settings=copy.deepcopy(self.apps))
        return result


def run():
    shots=Path(os.environ.get('USW_UI28_SCREENSHOTS','/tmp/usw-ui28-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/google-chrome'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
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
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(12000);page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' and 'Content Security Policy' in msg.text else None)
            page.goto('http://localhost:8765/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap()
            expect(page.locator('[data-drive-card]')).to_have_count(2)
            page.evaluate("()=>navigate('apps')");page.wait_for_function("()=>!apiBusy&&!routeLoading&&lastLoadedRoute==='apps'")
            card=page.locator(f'[data-container-id="{ERUGO}"]');boot=card.locator('[data-app-panel="boot"]');recovery=card.locator('[data-app-panel="recovery"]')
            review=card.locator('[data-action="app-review"]');expect(review).to_be_disabled()
            expect(card.locator('.app-advanced')).not_to_have_attribute('open','')
            expect(boot).to_contain_text('Start this app after the computer turns on, once the selected drives are ready.')
            expect(recovery).to_contain_text('Monitoring is off. Start monitoring for this drive in Overview')
            expect(recovery.locator('.app-drive').filter(has_text='MQ01UBD050').locator('.app-images')).to_have_count(0)
            expect(recovery.locator('[data-change="app-drive"]:checked')).to_have_count(2)
            boxes=[panel.bounding_box() for panel in (boot,recovery)]
            assert (abs(boxes[0]['y']-boxes[1]['y'])<2)==(width>1100),boxes
            assert all(el.bounding_box()['height']>=48 for el in card.locator('.app-option:visible,.app-drive-choice:visible,.app-image-choice:visible').all())
            page.screenshot(path=str(shots/f'ui28-{width}.png'),full_page=True)
            old=copy.deepcopy(api.apps[0]);toggle=recovery.locator('[data-change="app-enabled"]');toggle.uncheck()
            expect(recovery.locator('[data-change="app-drive"]').first).to_be_disabled()
            expect(recovery.locator(f'[data-change="app-image"][value="{IMAGE}"]')).to_be_checked()
            expect(boot.locator('[data-change="app-enabled"]')).to_be_checked();assert not api.saves and not api.reviews
            review.tap();expect(card.locator('.app-review')).to_contain_text('Saved drive and image selections will be retained.')
            assert not api.saves
            card.locator('[data-action="app-save"]').tap();expect(card.locator('.app-save-status')).to_contain_text('Settings saved and verified.')
            assert api.apps[0]['boot']==old['boot'];assert api.apps[0]['recovery']['drives']==old['recovery']['drives']
            expect(review).to_be_disabled()
            # Refresh/reload persists retained choices and manual controls stay independent.
            page.evaluate('()=>loadApplications()');expect(recovery.locator('[data-change="app-drive"]').first).to_be_disabled()
            manual=card.locator('.docker-manual-controls');manual.locator('[data-action="docker-start"]').tap()
            expect(manual.locator('[role="status"]')).to_contain_text('Runtime status verified')
            expect(manual.locator('[role="status"]:visible')).to_have_count(1);assert api.action_counts[ERUGO]==1
            toggle.check();review.tap();expect(card.locator('.setup-diff')).to_contain_text('+ restart: "no"')
            expect(card.locator('.app-review')).to_contain_text('backed up privately');assert len(api.saves)==1
            card.locator('[data-action="app-save"]').tap();expect(review).to_be_disabled()
            # A changed-back switch is a no-op and cannot open a confirmation.
            boot_toggle=boot.locator('[data-change="app-enabled"]');boot_toggle.uncheck();boot_toggle.check();expect(review).to_be_disabled()
            card.locator('.app-advanced summary').tap();expect(card.locator('.app-advanced')).to_have_attribute('open','')
            page.evaluate('()=>loadApplications()');expect(card.locator('.app-advanced')).to_have_attribute('open','')
            expect(card.locator('.app-advanced')).to_contain_text('not a general application-crash restart watchdog')
            # External deployment: instructions, no available save, no false success.
            api.blocked=True;boot.locator('.app-images summary').tap();boot.locator(f'[data-change="app-image"][value="{IMAGE}"]').uncheck();review.tap()
            expect(card.locator('.app-review')).to_contain_text('Portainer');expect(card.locator('[data-action="app-save"]')).to_have_count(0)
            assert len(api.saves)==2
            card.locator('[data-action="app-cancel"]').tap();api.blocked=False
            # Partial save leaves only unapplied choices dirty, with an accurate result.
            toggle.uncheck();api.partial=True;review.tap();card.locator('[data-action="app-save"]').tap()
            expect(card.locator('.app-save-status')).to_contain_text('Drive recovery saved. Computer startup was not confirmed.')
            expect(review).to_be_enabled();assert api.apps[0]['recovery']['enabled'] is False
            api.partial=False;review.tap();card.locator('[data-action="app-save"]').tap();expect(review).to_be_disabled()
            # Lost acknowledgement is read back; never replay the POST or claim policy verification.
            boot_toggle.uncheck();api.lost=True;review.tap();before=len(api.saves);card.locator('[data-action="app-save"]').tap()
            expect(card.locator('.app-save-status')).to_contain_text('Docker policy/source confirmation is unavailable')
            expect(review).to_be_disabled();assert len(api.saves)==before+1
            # Disable/enable does not erase image choices, multi-disk recovery or monitor state.
            assert not api.monitor['legacy'];assert not api.boot_posts and not api.applied
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'),width
            assert not errors,errors;context.close()
            print(f'PASS UI28 {width}px: responsive panels, touch controls, independent switches, retained images, monitoring warnings, manual action, review/save, Portainer, partial/lost responses and no no-op review')
        browser.close()


if __name__=='__main__':run()
