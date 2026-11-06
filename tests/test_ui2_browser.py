"""Chromium end-to-end interactions for fixed API contracts, using synthetic responses."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from test_approved_ui_live import ROOT, MockBroker

NEW='33333333-3333-4333-8333-333333333333'
class ReviewBroker(MockBroker):
    def __init__(self):
        super().__init__()
        self.rebound=False
    def reply(self,req):
        name=req['url'].split('?')[0].split('/')[-1]
        if self.session and name=='drive-rebind-candidates':
            return {'status':200,'body':{'drives':[{'profile_id':'legacy','old_uuid':self.drives['legacy'][1],
                     'new_uuid':NEW,'mountpoint':'/mnt/usb-storage-watch-'+NEW,'name':'ADATA'}]}}
        if self.session and name=='drive-rebind-plan':
            assert 'uuid='+NEW in req['url']
            return {'status':200,'body':{'new_uuid':NEW,'old_uuid':self.drives['legacy'][1],
                     'mountpoint':'/mnt/usb-storage-watch-'+NEW,'revision':'rebind-token'}}
        if self.session and name=='drive-rebind-apply':
            assert req['data']=={'uuid':NEW,'revision':'rebind-token','confirm':True}
            self.rebound=True;self.drives['legacy']=('ADATA USB Flash Drive',NEW,32_000_000_000)
            return {'status':200,'body':{'message':'Profile safely updated.'}}
        if self.session and name=='migration-plan':
            return {'status':200,'body':{'token':'mount-review-token','message':'Verified change.'}}
        if self.session and name=='change-mount-location':
            self.calls.append((req['method'],'legacy',name,req.get('data')))
            assert req['data']['token']=='mount-review-token'
            assert req['data']['revision']=='r1'
            assert req['data']['confirm'] is True
            return {'status':200,'body':{'message':'Mount updated.'}}
        if self.session and name=='image-discover':
            return {'status':200,'body':{'images':[{'name':'project','path':'/mnt/legacy/project.img','size':2*1024**3}],'truncated':False}}
        if self.session and name=='image-plan':
            assert req['data']['mode'] in ('existing','create')
            return {'status':200,'body':{'token':'image-token','message':'Image reviewed.'}}
        result=super().reply(req)
        if name=='fleet-status' and not self.rebound:
            for drive in result['body']['drives']:
                if drive['profile_id']=='legacy':drive.update(connected=False,mounted=False,mounted_expected=False)
        self.calls.append((req['method'],None,'verified-'+name,req.get('data')))
        return result

def run():
    html=(ROOT/'index.html').read_text().replace('<link rel="stylesheet" href="/static/style.css">','').replace('<script src="/static/app.js" defer></script>','')
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (390,1440):
            broker=ReviewBroker();page=browser.new_page(viewport={'width':width,'height':900});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.set_content(html);page.add_style_tag(content=(ROOT/'style.css').read_text())
            page.expose_binding('mock_usw',lambda _source,req:broker.reply(req))
            page.evaluate("""(()=>{window.fetch=async(url,opts={})=>{const r=await window.mock_usw({url:String(url),method:opts.method||'GET',data:opts.body?JSON.parse(opts.body):null});return new Response(JSON.stringify(r.body),{status:r.status,headers:{'Content-Type':'application/json'}});};})()""")
            page.add_script_tag(content=(ROOT/'app.js').read_text())
            page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').click()
            expect(page.locator('[data-drive-card]')).to_have_count(2)
            page.locator('[data-drive-card="legacy"] [data-action="find-reformatted-drive"]').click()
            expect(page.get_by_role('heading',name='Reconnect previously configured drive?')).to_be_visible()
            page.locator('#modal-root [data-action="confirmed-action"]').click()
            page.wait_for_function('()=>location.hash.includes("drive/legacy")',timeout=6000)
            assert broker.rebound,'Explicit rebind did not reach backend'
            expect(page.get_by_role('heading',name='ADATA USB Flash Drive',exact=True).first).to_be_visible()
            page.locator('[data-action="mount-location"]').click()
            page.locator('#modal-mount-path').fill('/mnt/adata-test')
            page.locator('[data-action="mount-location-preview"]').click()
            expect(page.get_by_role('heading',name='Apply mount location change?')).to_be_visible()
            page.locator('#modal-root [data-action="confirmed-action"]').click()
            page.wait_for_timeout(100)
            assert any(c[2]=='change-mount-location' for c in broker.calls),'Mount plan token was never committed'
            if width<=670:page.locator('[data-action="menu"]').click()
            page.locator('[data-action="nav"][data-value="images"]').click()
            page.wait_for_timeout(250)
            page.locator('[data-action="image-tab"][data-value="import"]').click()
            page.locator('[data-action="rescan-images"]').click()
            expect(page.locator('input[name="existing-image"]')).to_have_count(1)
            expect(page.locator('[data-action="import-discovered"]')).to_be_disabled()
            page.locator('input[name="existing-image"]').check()
            expect(page.locator('[data-action="import-discovered"]')).to_be_enabled()
            page.locator('[data-action="import-discovered"]').click()
            expect(page.get_by_role('heading',name='Register existing virtual disk image?')).to_be_visible()
            assert not errors, errors
            print(f'PASS {width}px — safe re-identification, two-step mount migration token and immediate image selection')
            page.close()
        browser.close()

if __name__=='__main__':run()
