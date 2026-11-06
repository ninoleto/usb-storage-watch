"""UI9 Chromium acceptance: synthetic APIs only; never touch real storage."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from test_ui8_browser import API as SleepAPI, ROOT


class API(SleepAPI):
    def __init__(self):
        super().__init__()
        self.image_mounted = True
        self.image_recovery = True
        self.interval = 15
        self.sleep_seconds = 1800
        self.auto_sleep = False

    def reply(self, request):
        parts = request['url'].split('?')[0].split('/')
        action = parts[-1]
        drive = parts[-2] if '/api/drives/' in request['url'] else None
        data = request.get('data') or {}
        write = request['method']=='POST'
        def ok(value):
            self.calls.append((request['method'],drive,action,data))
            return {'status':200,'body':value}
        if self.session:
            if action=='integration-info':return ok({'module':{'available':False},'certificate_pem':None})
            if action=='timing-settings':
                self.interval=data['timings']['monitor']['interval']
                return ok({'message':'Timings saved'})
            if action=='standby-settings':
                self.sleep_seconds=data['idle_seconds'];self.auto_sleep=data['enabled']
                return ok({'message':'Standby saved'})
            if action=='application-images':
                return ok({'images':[{'name':'backup','uuid':'synthetic-image','size':1024**3,
                    'mount_state':'mounted' if self.image_mounted else 'unmounted',
                    'enabled':self.image_recovery,'image':'/mnt/legacy/images/backup.img',
                    'mountpoint':'/mnt/legacy/backup','access_message':'Synthetic access'}] if drive=='legacy' else []})
            if action=='image-action':
                if data['action']=='set-recovery':self.image_recovery=data['enabled']
                elif data['action']=='mount':self.image_mounted=True
                elif data['action']=='unmount':self.image_mounted=False
                return ok({'message':'Image action completed. Mount on recovery is unchanged.'})
        result=super().reply(request)
        if result['status']==200:
            body=result['body']
            if action=='fleet-status':
                for row in body['drives']:
                    row['standby']={'state':self.standby,'applicable':True,'sleeping':self.standby=='standby'} if row['profile_id']=='legacy' else {'state':'not-applicable','applicable':False}
            if action=='config':
                body['config']['monitor']['interval']=self.interval
                body['config']['standby']={'idle_seconds':self.sleep_seconds,'enabled':self.auto_sleep}
            if action=='status' and drive=='legacy':
                body['standby'].update(enabled=self.auto_sleep,idle_seconds=self.sleep_seconds)
                body['observed_at']='2026-11-01T02:00:00Z'
        return result


def run():
    html=(ROOT/'index.html').read_text().replace('<link rel="stylesheet" href="/static/style.css">','').replace('<script src="/static/app.js" defer></script>','')
    screenshots=Path(os.environ['USW_UI9_SCREENSHOTS']) if os.environ.get('USW_UI9_SCREENSHOTS') else None
    if screenshots:screenshots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(has_touch=True)
        for width in (320,390,768,1440):
            api=API();page=context.new_page();page.set_viewport_size({'width':width,'height':900});errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.set_content(html);page.add_style_tag(content=(ROOT/'style.css').read_text())
            page.expose_binding('ui9_api',lambda _source,request:api.reply(request))
            page.evaluate("""() => {window.fetch=async(url,options={})=>{
              const r=await window.ui9_api({url:String(url),method:options.method||'GET',data:options.body?JSON.parse(options.body):null});
              return new Response(JSON.stringify(r.body),{status:r.status,headers:{'Content-Type':'application/json'}});
            }}""")
            page.add_script_tag(content=(ROOT/'app.js').read_text())
            page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').click()
            expect(page.locator('[data-drive-card]')).to_have_count(2)

            def nav(route):
                page.evaluate('(r)=>navigate(r)',route)
                page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r',arg=route)

            def choose(id, name):
                page.locator('#'+id+'-control').tap()
                page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                expect(page.locator('.touch-options')).to_be_visible()
                rows=page.locator('.touch-option')
                assert rows.count()>0
                assert all(box['height']>=48 for box in rows.evaluate_all('(rows)=>rows.map(r=>({height:r.getBoundingClientRect().height}))'))
                page.get_by_role('option',name=name,exact=True).tap()
                expect(page.locator('.touch-options')).to_have_count(0)
                page.wait_for_function('()=>!apiBusy&&!routeLoading')

            # Overview shows correct media and recovery colors, and does not
            # lose standby state on consecutive fleet refreshes.
            expect(page.locator('[data-drive-card="legacy"] .chip.good').filter(has_text='Recovery enabled')).to_have_count(1)
            expect(page.locator('[data-drive-card="drive-b"] .chip.muted').filter(has_text='Recovery disabled')).to_have_count(1)
            expect(page.get_by_text('HDD sleep: Not supported',exact=True)).to_be_visible()
            for status,label in [('standby','Spun down'),('active','In use'),('idle','Idle')]:
                api.standby=status;page.evaluate('pollLive()')
                expect(page.get_by_text('HDD: '+label,exact=True)).to_be_visible()
            if screenshots and width in (390,1440):page.screenshot(path=str(screenshots/f'overview-{width}.png'),full_page=True)

            nav('drive/legacy');expect(page.locator('#drive-summary')).to_be_visible()
            page.locator('[data-action="refresh-events"]').click()
            expect(page.locator('#drive-events-updated')).not_to_contain_text('Never')
            expect(page.locator('.toast.error')).to_have_count(0)
            page.wait_for_function('()=>!apiBusy&&!routeLoading&&!pollPending')
            for status,label in [('active','In use'),('standby','Spun down'),('idle','Idle')]:
                api.standby=status;page.evaluate('pollLive()')
                expect(page.get_by_text('HDD: '+label,exact=True)).to_be_visible()
            # No overlapping polls, and a late result must not replace a form
            # after navigation or discard unsaved values.
            before=len([c for c in api.calls if c[2]=='status'])
            page.evaluate("""() => {window.ui9_fetch=window.fetch;window.fetch=async(...args)=>{
              if(String(args[0]).endsWith('/status')&&!window.releaseUI9Poll)await new Promise(resolve=>window.releaseUI9Poll=resolve);
              return window.ui9_fetch(...args);
            };pollLive();pollLive();}""")
            page.wait_for_function('()=>!!window.releaseUI9Poll')
            nav('advanced');expect(page.locator('#standby-idle')).to_be_visible()
            page.locator('[data-timing="check"]').fill('37')
            page.evaluate('async()=>{window.releaseUI9Poll();window.fetch=window.ui9_fetch;while(pollPending)await new Promise(r=>setTimeout(r,10));}')
            expect(page.locator('[data-timing="check"]')).to_have_value('37')
            assert len([c for c in api.calls if c[2]=='status'])==before+2

            # Vertical timing order, controls + explanatory text, saved values.
            fields=page.locator('.setting-group [data-stepper]')
            positions=fields.evaluate_all('(els)=>els.map(e=>e.getBoundingClientRect().y)')
            assert positions==sorted(positions) and len(set(positions))==4
            page.locator('[data-action="stepper-adjust"][data-id="check"][data-value="+1"]').click()
            expect(page.locator('[data-timing="check"]')).to_have_value('38')
            page.locator('[data-action="timings-save"]').click()
            page.wait_for_function('()=>!apiBusy');assert api.interval==38
            expect(page.locator('#standby-auto')).to_have_attribute('role','switch')
            page.locator('#standby-auto').check()
            page.locator('[data-action="stepper-adjust"][data-id="sleep"][data-value="+1"]').click()
            expect(page.locator('#standby-idle')).to_have_value('31')
            page.locator('[data-form="standby-settings"] button[type="submit"]').click()
            page.wait_for_function('()=>!apiBusy');assert api.auto_sleep and api.sleep_seconds==1860
            if screenshots and width in (390,1440):page.screenshot(path=str(screenshots/f'advanced-{width}.png'),full_page=True)

            # All generated selectors have custom large menu rows. Standby
            # remains present when switching from HDD to flash and back.
            top=page.locator('.standby-card').evaluate('(e)=>e.offsetTop')
            choose('advanced-drive','SanDisk 3.2Gen1')
            expect(page.locator('.standby-card')).to_be_visible()
            expect(page.locator('#standby-idle')).to_be_disabled()
            expect(page.locator('#standby-auto')).to_be_disabled()
            after=page.locator('.standby-card').evaluate('(e)=>e.offsetTop')
            if abs(after-top)>=3:
                if screenshots:page.screenshot(path=str(screenshots/'layout-debug.png'),full_page=True)
                raise AssertionError(f'Standby position changed at {width}: {top} to {after}')
            page.locator('#advanced-drive-control').focus();page.keyboard.press('ArrowUp');page.keyboard.press('Home');page.keyboard.press('Enter')
            expect(page.locator('#advanced-drive')).to_have_value('legacy')
            expect(page.locator('#standby-idle')).to_be_enabled()
            page.locator('[data-action="stepper-reset"][data-id="sleep"]').click()
            expect(page.locator('#standby-idle')).to_have_value('30')
            assert page.locator('select:not([data-touch-select])').count()==0
            if screenshots and width==390:
                page.locator('#advanced-drive-control').click()
                page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                expect(page.locator('.touch-options')).to_be_visible()
                page.screenshot(path=str(screenshots/'dropdown-390.png'));page.keyboard.press('Escape')

            nav('history');expect(page.locator('#history-filter-control')).to_be_visible()
            choose('history-filter','Synthetic USB HDD')
            expect(page.locator('.history-entry')).to_have_count(1)
            page.locator('[data-action="refresh-events"]').click()
            expect(page.locator('.history-entry')).to_have_count(1)
            expect(page.locator('.toast.error')).to_have_count(0)

            nav('integrations');expect(page.locator('#integration-drive')).to_have_count(0)

            nav('images');expect(page.locator('[data-toggle="image-recovery"]')).to_be_checked()
            page.locator('[data-action="image-toggle-mount"]').click()
            if page.locator('#modal-root [data-action="confirmed-action"]').count():page.locator('#modal-root [data-action="confirmed-action"]').click()
            expect(page.locator('[data-action="image-toggle-mount"]')).to_have_text('Mount image')
            expect(page.locator('[data-toggle="image-recovery"]')).to_be_checked()
            page.locator('[data-toggle="image-recovery"]').uncheck()
            page.wait_for_function('()=>!apiBusy')
            page.locator('[data-action="image-toggle-mount"]').click()
            if page.locator('#modal-root [data-action="confirmed-action"]').count():page.locator('#modal-root [data-action="confirmed-action"]').click()
            expect(page.locator('[data-action="image-toggle-mount"]')).to_have_text('Unmount image')
            expect(page.locator('[data-toggle="image-recovery"]')).not_to_be_checked()
            assert api.image_mounted and not api.image_recovery

            # No passive request should issue any disk operation or image scan.
            assert not any(call[2] in ('disk-operation','image-discover','prepare-drive') for call in api.calls)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), f'Overflow at {width}'
            assert not errors,errors
            print(f'PASS UI9 {width}px: live status, no overlapping polls, event refresh, touch + keyboard menus, stable standby, saved timings, tokens and independent image actions')
            page.close()
        browser.close()


if __name__=='__main__':
    run()
