# SPDX-License-Identifier: MIT
"""UI29 hierarchy and missing identities; synthetic APIs, no live operations."""
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from test_ui28_browser import API as PreviousAPI
from test_ui20_browser import ROOT, ERUGO, IMAGE, CSP
from test_ui16_browser import OTHER

OLD='d'*64
INACTIVE='f'*64


class API(PreviousAPI):
    def __init__(self):
        super().__init__();self.inventory=True;self.entry_reviews=[];self.entry_writes=[];self.reject=False
        self.apps += [dict(id=OLD,name='sample-app',boot=dict(enabled=False,drives=[dict(id='legacy',images=[IMAGE])]),recovery=dict(enabled=False,drives=[])),
                      dict(id=INACTIVE,name='inactive-example',boot=dict(enabled=False,drives=[]),recovery=dict(enabled=False,drives=[dict(id='legacy',images=[IMAGE])]))]
        self.saved_ids=[ERUGO,OLD,INACTIVE]

    def reply(self,req):
        action=urlsplit(req['url']).path.rsplit('/',1)[-1];data=req.get('data') or {}
        if self.session and action=='docker-entry-plan':
            assert self.inventory and data['revision']=='apps-'+str(self.app_revision)
            assert data['id'] in (OLD,INACTIVE);source=next(a for a in self.apps if a['id']==data['id'])
            if data['target']:assert data['target']==dict(id=OTHER,name='independent-uploader') and OTHER not in self.saved_ids
            self.entry_reviews.append(copy.deepcopy(data))
            self.entry_plan=dict(token='entry-'+str(len(self.entry_reviews)),operation=data['operation'],source=dict(id=source['id'],name=source['name']),target=data['target'],settings=copy.deepcopy(source),
                message='Remove only Storage Watch settings; keep Docker and historical records.' if data['operation']=='remove' else 'Reconnect to this selected identity with automatic startup and recovery OFF. Review its app card afterward. Docker and historical records are untouched.')
            return dict(status=200,body=copy.deepcopy(self.entry_plan))
        if self.session and action=='docker-entry-apply':
            assert data==dict(token=self.entry_plan['token'],confirm=True)
            if not self.inventory or self.reject:return dict(status=400,body=dict(error='Docker inventory is unavailable; no saved entry was changed.'))
            self.entry_writes.append(copy.deepcopy(data));plan=self.entry_plan
            self.apps=[a for a in self.apps if a['id']!=plan['source']['id']];self.saved_ids.remove(plan['source']['id'])
            if plan['target']:
                target=next(a for a in self.apps if a['id']==plan['target']['id'])
                for key in ('boot','recovery'):target[key]=copy.deepcopy(plan['settings'][key]);target[key]['enabled']=False
                self.saved_ids.append(target['id'])
            self.app_revision+=1
            return dict(status=200,body=dict(ok=True,message='Saved entry removed.' if not plan['target'] else 'Saved entry reconnected. Automatic options are off.'))
        result=super().reply(req)
        if action=='docker-overview' and result['status']==200:
            body=result['body'];body['inventory_ok']=self.inventory;body['applications']['saved_ids']=self.saved_ids[:]
            live=body['containers'] if self.inventory else []
            body['containers']=live+[dict(id=a['id'],name=a['name'],state='missing' if self.inventory else 'unknown',discovered=False) for a in self.apps if a['id'] in self.saved_ids and not any(r['id']==a['id'] for r in live)]
            body['error']='' if self.inventory else 'Docker inventory is unavailable. Saved settings are retained.'
        return result


def run():
    shots=Path(os.environ.get('USW_UI29_SCREENSHOTS','/tmp/usw-ui29-shots'));shots.mkdir(parents=True,exist_ok=True)
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
                if name not in ('index.html','app.js','network.js','style.css','icon.svg'):route.fulfill(status=404,body='');return
                route.fulfill(path=str(ROOT/name),headers=headers,content_type='text/html' if name.endswith('html') else 'text/javascript' if name.endswith('js') else 'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*',serve);page=context.new_page();page.set_default_timeout(12000)
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda m:errors.append(m.text) if m.type=='error' and 'Content Security Policy' in m.text else None)
            page.goto('http://localhost:8765/');page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').tap()
            expect(page.locator('[data-drive-card]')).to_have_count(2)
            page.evaluate("()=>navigate('apps')");page.wait_for_function("()=>!apiBusy&&!routeLoading&&lastLoadedRoute==='apps'")
            card=page.locator(f'[data-container-id="{ERUGO}"]');boot=card.locator('[data-app-panel="boot"]');recovery=card.locator('[data-app-panel="recovery"]')
            expect(recovery.locator('h3')).to_have_text('Drive failure & recovery')
            bimages=boot.locator('[data-image-section]');rimages=recovery.locator('[data-image-section]')
            expect(bimages.locator('summary')).to_have_text('Virtual images · 1 selected: sample-volume')
            expect(rimages.locator('summary')).to_have_text('Virtual images · 1 selected: sample-volume')
            expect(bimages).not_to_have_attribute('open','');expect(rimages).not_to_have_attribute('open','')
            before=page.evaluate('id=>JSON.stringify(dockerView(id).appDraft)',ERUGO)
            bimages.locator('summary').tap();expect(bimages).to_have_attribute('open','');expect(rimages).not_to_have_attribute('open','')
            expect(bimages).to_contain_text('Select only the virtual images this app needs. Otherwise, leave them unselected.')
            image=bimages.locator(f'[value="{IMAGE}"]');image.uncheck()
            expect(bimages.locator('summary')).to_have_text('Virtual images · 0 selected');expect(bimages).to_have_attribute('open','')
            expect(rimages.locator('summary')).to_have_text('Virtual images · 1 selected: sample-volume')
            image.check();bimages.locator('summary').tap();rimages.locator('summary').tap()
            page.evaluate('()=>loadApplications()');expect(bimages).not_to_have_attribute('open','');expect(rimages).to_have_attribute('open','')
            page.evaluate('()=>render()');expect(bimages).not_to_have_attribute('open','');expect(rimages).to_have_attribute('open','')
            page.reload();page.wait_for_function("()=>!apiBusy&&!routeLoading&&lastLoadedRoute==='apps'")
            expect(bimages).not_to_have_attribute('open','');expect(rimages).to_have_attribute('open','')
            toggle=recovery.locator('[data-change="app-enabled"]');toggle.uncheck()
            expect(rimages).to_have_attribute('open','');expect(rimages.locator(f'[value="{IMAGE}"]')).to_be_checked();expect(rimages.locator(f'[value="{IMAGE}"]')).to_be_disabled()
            toggle.check();assert page.evaluate('id=>JSON.stringify(dockerView(id).appDraft)',ERUGO)==before
            expect(card.locator('[data-action="app-review"]')).to_be_disabled()
            assert bimages.evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(16, 24, 31)'
            assert rimages.bounding_box()['x']>recovery.locator('.app-drive').first.bounding_box()['x']+10
            assert rimages.locator('summary').bounding_box()['height']>=48
            expect(page.locator('.docker-container')).to_have_count(2);expect(page.locator('.unavailable-entry')).to_have_count(2)
            old=page.locator(f'[data-unavailable-entry="{OLD}"]');expect(old.locator('summary')).to_contain_text('sample-app')
            expect(old.locator('summary')).to_contain_text('Missing');expect(old).not_to_have_attribute('open','')
            old.locator('summary').tap();old.locator('[data-action="entry-reconnect"]').tap()
            picker=old.locator('select');expect(picker).to_have_value('')
            expect(picker.locator(f'option[value="{ERUGO}"]')).to_be_disabled()
            expect(old.locator('[data-action="entry-review"]')).to_be_disabled()
            picker.select_option(OTHER);page.evaluate('()=>loadApplications()');expect(picker).to_have_value(OTHER);expect(old).to_have_attribute('open','')
            old.locator('[data-action="entry-review"]').tap();expect(old.locator('.entry-review')).to_contain_text(OTHER);expect(old.locator('.entry-review')).to_contain_text('OFF')
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'),width
            page.screenshot(path=str(shots/f'ui29-unavailable-{width}.png'),full_page=True)
            assert not api.entry_writes;unchanged=copy.deepcopy(api.apps[0])
            old.locator('[data-action="entry-apply"]').tap();expect(old).to_have_count(0)
            expect(page.locator('#entry-result')).to_contain_text('reconnected');assert api.apps[0]==unchanged
            target=next(v for v in api.apps if v['id']==OTHER);assert not target['boot']['enabled'] and target['boot']['drives']==[dict(id='legacy',images=[IMAGE])]
            inactive=page.locator(f'[data-unavailable-entry="{INACTIVE}"]');inactive.locator('summary').tap()
            expect(inactive).to_contain_text('sample-volume');inactive.locator('[data-action="entry-remove"]').tap()
            expect(inactive.locator('.entry-review')).to_contain_text('Storage Watch settings');assert len(api.entry_writes)==1
            # Docker loss between review/confirmation must retain the entry.
            api.inventory=False;inactive.locator('[data-action="entry-apply"]').tap()
            expect(inactive.locator('[role="status"]').last).to_contain_text('inventory is unavailable')
            expect(inactive.locator('summary')).to_contain_text('Status unavailable')
            expect(inactive.locator('[data-action="entry-remove"]')).to_be_disabled()
            expect(page.locator('.unavailable-entry summary').filter(has_text='Missing')).to_have_count(0)
            assert INACTIVE in api.saved_ids and len(api.entry_writes)==1
            api.inventory=True;page.evaluate('()=>loadApplications()');expect(inactive.locator('summary')).to_contain_text('Missing')
            inactive.locator('[data-action="entry-remove"]').tap();inactive.locator('[data-action="entry-apply"]').tap()
            expect(inactive).to_have_count(0);assert api.apps[0]==unchanged;assert len(api.entry_writes)==2
            assert not api.saves and not api.applied and all(n==0 for n in api.action_counts.values())
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'),width
            page.screenshot(path=str(shots/f'ui29-{width}.png'),full_page=True)
            assert not errors,errors;context.close()
            print(f'PASS UI29 {width}px: image hierarchy, independent collapse/edit/refresh persistence, selected names, exact-ID reconnect/removal, protected existing app, inactive entries and Docker outage refusal')
        browser.close()


if __name__=='__main__':run()
