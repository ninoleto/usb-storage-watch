"""UI10 touch, preference and LAN regressions; synthetic APIs, no host writes."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from test_ui9_browser import API as PreviousAPI, ROOT


class API(PreviousAPI):
    def __init__(self):
        super().__init__()
        self.network = dict(lan=False, scheme='http', address='192.168.50.24')
        self.operation = dict(phase='idle')
        self.network_data = None
        self.network_reads = 0
        self.network_failure = False
        self.preference_failure = False
        self.prepare_phase = 'formatting'

    def preparation(self):
        message={'ready':'Drive ready. Your Linux filesystem is mounted.',
                 'failed':'Preparation failed; review the drive.'}.get(self.prepare_phase,'Creating the ext4 filesystem.')
        return dict(operation='synthetic-preparation',name='Synthetic HDD',phase=self.prepare_phase,message=message)

    def reply(self, request):
        action = request['url'].split('?')[0].split('/')[-1]
        data = request.get('data') or {}
        def ok(body):
            self.calls.append((request['method'], None, action, data))
            return dict(status=200, body=body)
        if self.session:
            if action == 'prepare-progress':
                return ok(self.preparation())
            if action == 'lan-info':
                return ok(dict(addresses=[dict(address=self.network['address'])], operation=self.operation))
            if action in ('lan-auto', 'network'):
                self.network_data = data
                self.network_reads = 0
                self.operation = dict(operation='synthetic-network', phase='applying', message='Applying')
                return ok(dict(operation='synthetic-network', pending=True))
            if action == 'lan-status':
                self.network_reads += 1
                if self.network_reads == 1:
                    return dict(status=503, body=dict(error='Administration service unavailable. Try again shortly.'))
                self.operation = dict(operation='synthetic-network',
                    phase='failed' if self.network_failure else 'complete',
                    message='Previous settings restored.' if self.network_failure else 'Network settings verified.')
                if not self.network_failure:
                    self.network.update(lan=self.network_data['enabled'], scheme=self.network_data.get('scheme', self.network['scheme']))
                return ok(self.operation)
            if action == 'image-action' and self.preference_failure:
                self.calls.append((request['method'], 'legacy', action, data))
                return dict(status=409, body=dict(error='Synthetic preference refusal.'))
        result = super().reply(request)
        if result['status'] == 200:
            body = result['body']
            if action == 'global-config':
                body['network'] = dict(self.network)
            if action == 'fleet-status':
                # A USB stick with ambiguous kernel metadata is not a known HDD.
                body['drives'][1].update(media_kind='unknown', standby=dict(state='unknown', applicable=False))
            if action == 'status' and '/drive-b/' in request['url']:
                body['discovered']['media_kind'] = 'unknown'
                body['standby'] = dict(state='unknown', applicable=False)
            if action == 'prepare-disks':
                body['operations'] = [self.preparation()]
        return result


def run():
    html = (ROOT/'index.html').read_text().replace('<link rel="stylesheet" href="/static/style.css">','').replace('<script src="/static/app.js" defer></script>','')
    shots = Path(os.environ['USW_UI10_SCREENSHOTS']) if os.environ.get('USW_UI10_SCREENSHOTS') else None
    if shots: shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/chromium'), headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        context = browser.new_context(has_touch=True)
        for width in (320,390,768,1440):
            api = API(); page = context.new_page(); page.set_viewport_size(dict(width=width,height=900)); errors=[]
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.set_content(html); page.add_style_tag(content=(ROOT/'style.css').read_text())
            page.expose_binding('ui10_api', lambda _source,request: api.reply(request))
            page.evaluate('''() => {window.fetch=async(url,options={})=>{
              if(window.holdPreference&&String(url).endsWith('/image-action'))await new Promise(resolve=>window.releasePreference=resolve);
              const result=await window.ui10_api({url:String(url),method:options.method||'GET',data:options.body?JSON.parse(options.body):null});
              if(window.loseNetworkReceipt&&String(url).endsWith('/lan-auto'))throw new TypeError('Failed to fetch');
              return new Response(JSON.stringify(result.body),{status:result.status,headers:{'Content-Type':'application/json'}});
            }}''')
            page.add_script_tag(content=(ROOT/'app.js').read_text())
            page.locator('#usw-login-token').fill('synthetic-token'); page.locator('#usw-login-form button').click()
            expect(page.locator('[data-drive-card]')).to_have_count(2)
            def nav(route):
                page.evaluate('(r)=>navigate(r)', route)
                page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r', arg=route)
            def writes(action): return [c for c in api.calls if c[0]=='POST' and c[2]==action]

            expect(page.locator('[data-action="open-add-drive"]')).to_have_css('background-color','rgb(25, 95, 162)')
            expect(page.get_by_text('HDD sleep: Not supported',exact=True)).to_be_visible()
            nav('drive/drive-b')
            expect(page.get_by_text('HDD sleep: Not supported',exact=True)).to_be_visible()
            expect(page.get_by_text('HDD: Unknown',exact=True)).to_have_count(0)
            expect(page.locator('[data-action="sleep-hdd"]')).to_have_count(0)

            # The reserved status bar never moves content or covers inputs.
            nav('images'); switch=page.locator('[data-toggle="image-recovery"]')
            switch.scroll_into_view_if_needed()
            before=switch.bounding_box()
            page.evaluate('()=>{for(let i=0;i<30;i++)toast("Synthetic message "+i);}')
            assert switch.bounding_box()==before
            expect(page.locator('.toast')).to_have_count(1)
            page.evaluate('()=>window.holdPreference=true')
            switch.tap(); page.wait_for_function('()=>!!window.releasePreference')
            for _ in range(7):
                page.evaluate('()=>toast("Another notification")')
                switch.tap(timeout=1500)
                expect(switch).to_be_enabled()
            expect(switch).to_be_checked()
            page.evaluate('()=>{window.holdPreference=false;window.releasePreference();}')
            page.wait_for_function('()=>!preferencesSaving&&!imagePreferences.size')
            assert [c[3]['enabled'] for c in writes('image-action')]==[False,True]
            assert api.image_recovery and api.image_mounted
            expect(page.locator('.preference-status')).to_have_text('Saved')
            assert not any('pending' in n for n in page.locator('.toast').all_text_contents())
            # Failure reconciles once, shows an inline error and never retries.
            api.preference_failure=True; switch.tap()
            page.wait_for_function('()=>!preferencesSaving&&!imagePreferences.size')
            expect(switch).to_be_checked()
            expect(page.locator('.preference-status')).to_contain_text('Save failed')
            assert len(writes('image-action'))==3
            api.preference_failure=False
            page.locator('[data-action="notifications"]').tap()
            expect(page.locator('.notification-history')).to_contain_text('Synthetic preference refusal')
            page.locator('[data-action="close-modal"]').tap()
            if shots and width in (390,1440): page.screenshot(path=str(shots/f'images-{width}.png'),full_page=True)

            nav('apps')
            gap=page.evaluate('()=>$("#apps-drive").closest(".field").getBoundingClientRect().top-$(".card>.callout").getBoundingClientRect().bottom')
            assert gap>=20
            nav('history')
            gap=page.evaluate('()=>$(".card>.callout").getBoundingClientRect().top-$("#history-filter").closest(".field").getBoundingClientRect().bottom')
            assert gap>=20
            nav('prepare')
            progress=page.locator('.preparation-progress.working')
            expect(progress).to_have_css('background-color','rgb(0, 0, 0)')
            expect(progress.locator('p')).to_have_css('color','rgb(255, 225, 113)')
            expect(progress.locator('.busy-spinner')).to_have_count(1)
            if shots and width in (390,1440): page.screenshot(path=str(shots/f'prepare-{width}.png'),full_page=True)

            # A real terminal API response must stop the busy presentation
            # immediately, and it must stay stopped after revisiting the page.
            api.prepare_phase='ready'
            page.evaluate("()=>waitFormat('synthetic-preparation')")
            ready=page.locator('.preparation-progress.finished.success')
            expect(ready).to_contain_text('Synthetic HDD — Ready')
            expect(ready).to_contain_text('Your Linux filesystem is mounted')
            expect(ready).to_have_attribute('aria-busy','false')
            expect(ready.locator('.busy-spinner')).to_have_count(0)
            expect(ready.locator('svg')).to_have_count(1)
            if shots and width in (390,1440): page.screenshot(path=str(shots/f'prepare-ready-{width}.png'),full_page=True)
            nav('overview');nav('prepare')
            expect(page.locator('.preparation-progress.finished.success')).to_be_visible()
            expect(page.locator('.preparation-progress .busy-spinner')).to_have_count(0)
            api.prepare_phase='failed'
            page.evaluate("()=>waitFormat('synthetic-preparation')")
            expect(page.locator('.preparation-progress.finished.failed')).to_contain_text('Preparation failed')
            expect(page.locator('.preparation-progress .busy-spinner')).to_have_count(0)

            nav('advanced'); lan=page.locator('[data-toggle="lan"]')
            lan.tap(); page.locator('[data-action="confirmed-action"]').tap()
            expect(page.locator('.modal-progress')).to_be_visible()
            expect(page.locator('[data-action="confirmed-action"]')).to_be_disabled()
            # One request even if a second click is dispatched while applying.
            page.evaluate('()=>$("[data-action=confirmed-action]").dispatchEvent(new MouseEvent("click",{bubbles:true}))')
            page.wait_for_function('()=>!apiBusy&&!modalPending')
            expect(lan).to_be_checked(); assert len(writes('lan-auto'))==1
            expect(page.locator('.network-result')).to_contain_text('Network settings verified')
            lan.tap(); page.locator('[data-action="confirmed-action"]').tap()
            page.wait_for_function('()=>!apiBusy&&!modalPending'); expect(lan).not_to_be_checked()
            assert len(writes('lan-auto'))==2

            api.network_failure=True
            lan.tap(); page.locator('[data-action="confirmed-action"]').tap()
            page.wait_for_function('()=>!apiBusy&&!modalPending')
            expect(page.locator('#modal-root')).to_contain_text('Previous settings restored')
            expect(lan).not_to_be_checked()
            page.locator('[data-action="close-modal"]').tap(); api.network_failure=False

            # A lost POST response is unknown, never automatically resubmitted.
            page.evaluate('()=>window.loseNetworkReceipt=true')
            lan.tap(); page.locator('[data-action="confirmed-action"]').tap()
            page.wait_for_function('()=>!apiBusy&&!modalPending')
            expect(page.locator('#modal-root')).to_contain_text('result is unconfirmed')
            assert len(writes('lan-auto'))==4
            page.locator('[data-action="close-modal"]').tap()
            page.evaluate('()=>{window.loseNetworkReceipt=false;localDashboard=()=>false;state.lan=true;render();}')
            before_reads=api.network_reads
            lan.tap(); page.locator('[data-action="confirmed-action"]').tap()
            page.wait_for_function('()=>!apiBusy&&!modalPending')
            expect(page.locator('#modal-root')).to_contain_text('cannot verify completion')
            # Remote disable requires a localhost check, not polling the stopped listener.
            assert api.network_reads==0 and before_reads>=0
            assert len(writes('lan-auto'))==5
            page.locator('[data-action="close-modal"]').tap()
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
            assert not errors, errors
            print(f'PASS UI10 browser {width}px: nonblocking messages, rapid preferences/failure, LAN verified/rollback/lost response/remote handoff, media, blue button, spacing, progress')
            page.close()
        context.close(); browser.close()


if __name__=='__main__': run()
