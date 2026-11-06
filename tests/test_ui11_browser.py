"""UI11 real Chromium workflows with synthetic APIs, no live devices."""
import copy
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from test_ui10_browser import API as PreviousAPI, ROOT


class API(PreviousAPI):
    def __init__(self):
        super().__init__()
        self.configs={};self.revisions={'legacy':1,'drive-b':1}
        self.fail_save=False;self.fail_events=False;self.docker_absent=False;self.running=True
        self.bind='/mnt/legacy/backup/app'
        self.rows=[dict(id='a'*64,name='test-erugo',running=True,paused=False,health=None,eligible=True,reason='',binds=[dict(source=self.bind,destination='/data',eligible=True,reason='')]),dict(id='b'*64,name='unrelated',running=True,eligible=False,reason='No safe writable bind on the selected disk.',binds=[])]
    def reply(self,req):
        parts=req['url'].split('/api/',1)[1].split('?',1)[0].split('/')
        drive=parts[1] if parts[0]=='drives' else None;action=parts[-1];data=req.get('data') or {};write=req['method']=='POST'
        def ok(value):self.calls.append((req['method'],drive,action,data));return dict(status=200,body=value)
        def fail(message):self.calls.append((req['method'],drive,action,data));return dict(status=409,body=dict(error=message))
        if self.session:
            if action=='network-state':
                return ok(dict(config=dict(lan=False,address='192.168.50.24',scheme='http',http_port=8765,https_port=8766),url=None,local_url='http://127.0.0.1:8765',addresses=[],transaction=dict(phase='idle'),certificate=dict(available=False)))
            if action=='fleet-events' and self.fail_events:return fail('Synthetic history error')
            if action in ('timing-settings','standby-settings'):
                if self.fail_save:return fail('Synthetic save refusal')
                c=self.configs[drive]
                if action=='timing-settings':
                    for key,value in data['timings'].items():c[key].update(value)
                else:c['standby'].update(enabled=data['enabled'],idle_seconds=data['idle_seconds'])
                self.revisions[drive]+=1
                return ok(dict(message='Settings saved.',revision='r'+str(self.revisions[drive])))
            if action=='docker':
                if self.docker_absent:return fail('Synthetic Docker unavailable')
                return ok(dict(containers=copy.deepcopy(self.rows) if drive=='legacy' else []))
            if action=='application-status':
                if self.docker_absent:return fail('Synthetic Docker unavailable')
                c=self.configs.get(drive,{}).get('docker',{})
                return ok(dict(enabled=c.get('enabled',False),service=dict(ActiveState='active' if self.monitor[drive] else 'inactive'),observed_at='2026-11-01T06:00:00Z',containers=[dict(**x,state='running' if self.running else 'stopped',health=None,recovery={}) for x in c.get('containers',[])]))
            if action=='application-settings':
                if self.monitor[drive]:return fail('Stop monitoring first')
                if data['revision']!='r'+str(self.revisions[drive]):return fail('Settings changed')
                if self.fail_save:return fail('Synthetic Docker save refusal')
                c=self.configs[drive]['docker']
                if 'containers' in data:c['containers']=[dict(name='test-erugo',source=self.bind,destination=x['destination'],grace=30) for x in data['containers']]
                if data.get('enabled') and not c['containers']:return fail('Select a container first')
                c['enabled']=data['enabled'];self.revisions[drive]+=1
                return ok(dict(message='Saved',revision='r'+str(self.revisions[drive])))
            if action=='application-check':return ok(dict(observed_at='2026-11-01T06:00:00Z',message='Storage access check finished. No containers were restarted.',containers=[dict(name='test-erugo',verified=True,message='Storage access verified.')]))
        result=super().reply(req)
        if result['status']==200 and action=='config':
            if drive not in self.configs:
                self.configs[drive]=copy.deepcopy(result['body']['config']);self.configs[drive]['docker']['enabled']=False
            result['body']['config']=copy.deepcopy(self.configs[drive]);result['body']['revision']='r'+str(self.revisions[drive])
        return result


def run():
    html=(ROOT/'index.html').read_text().replace('<link rel="stylesheet" href="/static/style.css">','').replace('<script src="/static/app.js" defer></script>','').replace('<script src="/static/network.js" defer></script>','')
    shots=Path(os.environ['USW_UI11_SCREENSHOTS']) if os.environ.get('USW_UI11_SCREENSHOTS') else None
    if shots:shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(has_touch=True)
        for width in (320,390,768,1440):
            api=API();page=context.new_page();page.set_default_timeout(10000);page.set_viewport_size(dict(width=width,height=950));errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.set_content(html);page.add_style_tag(content=(ROOT/'style.css').read_text())
            page.expose_binding('ui11_api',lambda _s,r:api.reply(r))
            page.evaluate('''()=>{window.fetch=async(url,options={})=>{
              if(window.holdAction&&String(url).endsWith('/'+window.holdAction))await new Promise(resolve=>window.releaseAction=resolve);
              const r=await window.ui11_api({url:String(url),method:options.method||'GET',data:options.body?JSON.parse(options.body):null});
              return new Response(JSON.stringify(r.body),{status:r.status,headers:{'Content-Type':'application/json'}});
            }}''')
            page.add_script_tag(content=(ROOT/'network.js').read_text())
            page.add_script_tag(content=(ROOT/'app.js').read_text())
            page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').click()
            expect(page.locator('[data-drive-card]')).to_have_count(2)
            def nav(r):page.evaluate('(r)=>navigate(r)',r);page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r',arg=r)
            def idle():page.wait_for_function('()=>!apiBusy')
            def choose(id,value):page.select_option('#'+id,value,force=True);page.wait_for_function('()=>!apiBusy&&!routeLoading');page.wait_for_function('()=>!Array.from(applicationViews.values()).some(v=>v.loading)')
            def writes(action):return [c for c in api.calls if c[0]=='POST' and c[2]==action]

            expect(page.locator('[data-drive-card="drive-b"] .button-start')).to_have_css('border-top-width','2px')
            nav('drive/legacy')
            expect(page.locator('[data-action="mount-location"]')).to_be_disabled()
            expect(page.locator('.mount-location-hint')).to_contain_text('Unmount')
            api.mounted['legacy']=False;page.evaluate("()=>refreshDetail('legacy')")
            expect(page.locator('[data-action="mount-location"]')).to_be_enabled()
            page.locator('[data-action="mount-location"]').click();expect(page.locator('#modal-mount-path')).to_be_visible();page.locator('[data-action="close-modal"]').click()
            api.mounted['legacy']=True

            # Refresh must provide feedback beside the actual clicked control.
            for r in ('drive/legacy','history'):
                nav(r);page.evaluate("()=>{window.holdAction='fleet-events';window.releaseAction=null;}")
                page.locator('[data-action="refresh-events"]').click()
                expect(page.locator('[data-event-refresh-status]')).to_have_text('Refreshing…')
                expect(page.locator('[data-action="refresh-events"]')).to_be_disabled()
                page.wait_for_function('()=>!!window.releaseAction');page.evaluate('()=>{window.holdAction=null;window.releaseAction();}')
                expect(page.locator('[data-event-refresh-status]')).to_have_text('Updated')
                api.fail_events=True;page.locator('[data-action="refresh-events"]').click()
                expect(page.locator('[data-event-refresh-status]')).to_contain_text('Synthetic history error');api.fail_events=False
            count=page.evaluate('()=>state.history.length');page.evaluate("()=>{toast('Clear me');toast('Error to clear',true);}")
            page.locator('[data-action="notifications"]').click();page.locator('[data-action="clear-notifications"]').click()
            expect(page.locator('.notification-history')).to_have_text('No messages in this browser session.')
            expect(page.locator('#notification-count')).to_have_text('0');expect(page.locator('.toast')).to_have_count(0)
            assert page.evaluate('()=>state.history.length')==count
            page.locator('[data-action="close-modal"]').click()

            nav('advanced');timing=page.locator('[data-action="timings-save"]');sleep=page.locator('[data-settings-save="standby"]')
            expect(timing).to_be_disabled();expect(sleep).to_be_disabled()
            page.locator('[data-timing="check"]').fill('16');expect(timing).to_be_enabled();expect(sleep).to_be_disabled()
            page.locator('[data-timing="check"]').fill('15');expect(timing).to_be_disabled()
            page.locator('[data-action="stepper-adjust"][data-id="check"][data-value="+1"]').click();timing.click();idle()
            expect(timing).to_be_disabled();expect(page.locator('[data-settings-status="timings"]')).to_have_text('Saved')
            page.locator('[data-timing="check"]').fill('17')
            page.locator('#standby-auto').check();expect(sleep).to_be_enabled();sleep.click();idle()
            expect(sleep).to_be_disabled();expect(timing).to_be_enabled();expect(page.locator('[data-timing="check"]')).to_have_value('17')
            choose('advanced-drive','drive-b');expect(timing).to_be_disabled();choose('advanced-drive','legacy')
            expect(page.locator('[data-timing="check"]')).to_have_value('17');expect(timing).to_be_enabled()
            api.fail_save=True;timing.click();idle();expect(timing).to_be_enabled();expect(page.locator('[data-settings-status="timings"]')).to_contain_text('Save not confirmed');api.fail_save=False
            page.evaluate("()=>{window.holdAction='timing-settings';window.releaseAction=null;}");timing.click()
            page.wait_for_function('()=>!!window.releaseAction');page.locator('[data-timing="check"]').fill('18')
            page.evaluate('()=>{window.holdAction=null;window.releaseAction();}');idle()
            expect(timing).to_be_enabled();expect(page.locator('[data-timing="check"]')).to_have_value('18')
            timing.click();idle();expect(timing).to_be_disabled()
            if shots and width in (390,1440):page.screenshot(path=str(shots/f'settings-{width}.png'),full_page=True)

            # UI16 replaced the drive-first Docker page and its monitor lock.
            # The current container-first workflows are covered independently by
            # test_ui16_browser.py; this suite retains the unrelated UI11 regressions.
            assert not errors,errors
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            print(f'PASS UI11 browser {width}px: settings drafts/save races, clear messages, inline refresh and mounted-drive location guard')
            page.close()
        browser.close()


if __name__=='__main__':run()
