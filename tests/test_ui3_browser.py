"""Approved GUI: both monitored and unmonitored drives can review image creation.

Synthetic API responses only; this never touches a physical disk or service.
"""
from playwright.sync_api import sync_playwright,expect
from test_approved_ui_live import ROOT,MockBroker

class Broker(MockBroker):
    def __init__(self):
        super().__init__()
        self.plans=[]
        self.applied=[]
    def reply(self,req):
        action=req['url'].split('?')[0].split('/')[-1]
        if self.session and action=='image-plan':
            drive=req['url'].split('/api/drives/')[1].split('/')[0]
            self.plans.append((drive,dict(req['data']),self.monitor[drive]))
        if self.session and action=='image-apply':
            drive=req['url'].split('/api/drives/')[1].split('/')[0]
            self.applied.append((drive,self.monitor[drive]))
        return super().reply(req)

def run():
    html=(ROOT/'index.html').read_text().replace('<link rel="stylesheet" href="/static/style.css">','').replace('<script src="/static/app.js" defer></script>','')
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (390,1440):
            broker=Broker();page=browser.new_page(viewport={'width':width,'height':900});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.set_content(html);page.add_style_tag(content=(ROOT/'style.css').read_text())
            page.expose_binding('mock_usw',lambda _source,req:broker.reply(req))
            page.evaluate('''(()=>{window.fetch=async(url,opts={})=>{const r=await window.mock_usw({url:String(url),method:opts.method||'GET',data:opts.body?JSON.parse(opts.body):null});return new Response(JSON.stringify(r.body),{status:r.status,headers:{'Content-Type':'application/json'}});};})()''')
            page.add_script_tag(content=(ROOT/'app.js').read_text())
            page.locator('#usw-login-token').fill('synthetic-token')
            page.locator('#usw-login-form button').click()
            expect(page.locator('[data-drive-card]')).to_have_count(2)
            if width<=670:page.locator('[data-action="menu"]').click()
            page.locator('[data-action="nav"][data-value="images"]').click()
            for profile in ('legacy','drive-b'):
                page.locator('#image-drive').select_option(profile)
                page.locator('[data-action="image-tab"][data-value="create"]').click()
                expect(page.locator('[data-form="image-create"] button')).to_be_enabled()
                expect(page.locator('.tab-panel')).to_contain_text('briefly paused and resumed automatically')
                page.locator('#new-image-name').fill('test-'+profile)
                page.locator('#new-image-capacity').fill('1')
                page.locator('[data-form="image-create"] button').click()
                expect(page.get_by_role('heading',name='Create virtual disk image?')).to_be_visible()
                expect(page.locator('#modal-root')).to_contain_text('Image creation reviewed')
                page.locator('#modal-root [data-action="confirmed-action"]').click()
                page.wait_for_function('()=>!document.querySelector("#modal-root [data-action=confirmed-action]")',timeout=5000)
                # A client-side API call must not toggle monitoring.
                assert broker.monitor[profile]==(profile=='legacy')
            assert len(broker.plans)==2 and len(broker.applied)==2,(broker.plans,broker.applied)
            assert broker.plans[0][2] is True and broker.plans[1][2] is False
            assert not errors,errors
            print(f'PASS UI3 {width}px: creation with monitoring ON and OFF; both states preserved')
            page.close()
        browser.close()
if __name__=='__main__':run()
