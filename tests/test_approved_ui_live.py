"""Real Chromium runs the approved UI using synthetic broker responses.
No USB, Docker, SMTP or privileged system operation is executed.
"""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]/'src/usb_storage_watch/web_static'
A='11111111-1111-4111-8111-111111111111';B='22222222-2222-4222-8222-222222222222'

class MockBroker:
  def __init__(self):
    self.session=False;self.calls=[]
    self.monitor={'legacy':True,'drive-b':False};self.recovery={'legacy':True,'drive-b':False}
    self.notifications={'legacy':True,'drive-b':False};self.mounted={'legacy':True,'drive-b':True}
    self.drives={'legacy':('ADATA USB Flash Drive',A,32_000_000_000), 'drive-b':('SanDisk 3.2Gen1',B,16_000_000_000)}
  def reply(self,req):
    method=req['method'];parts=req['url'].split('/api/',1)[1].split('?',1)[0].split('/')
    drive=parts[1] if parts[0]=='drives' else None;action=parts[-1];data=req.get('data') or {}
    self.calls.append((method,drive,action,data))
    ok=lambda body:{'status':200,'body':body}
    if action=='session':return {'status':200 if self.session else 401,'body':{'csrf':'csrf','username':'tester'} if self.session else {'error':'Not signed in.'}}
    if action=='login':self.session=data.get('management_token')=='synthetic-token';return {'status':200 if self.session else 401,'body':{'csrf':'csrf'} if self.session else {'error':'Invalid token.'}}
    if not self.session:return {'status':401,'body':{'error':'Not signed in.'}}
    if action=='fleet-status':
      return ok({'drives':[{'profile_id':k,'configured':True,'uuid':v[1],'name':v[0],'size':v[2],
        'media_kind':'flash','connected':True,'mounted':self.mounted[k],'mounted_expected':self.mounted[k],'mountpoint':'/mnt/'+k,
        'monitoring':'active' if self.monitor[k] else 'inactive','recovery_enabled':self.recovery[k],
        'observed_at':'2026-10-31T02:00:00Z'} for k,v in self.drives.items()], 'refreshed_at':'2026-10-31T02:00:00Z'})
    if action=='status':return ok({'health':{'detected':True,'healthy':True},'mounted_expected':self.mounted[drive],'mounted':self.mounted[drive],
      'service':{'ActiveState':'active' if self.monitor[drive] else 'inactive'},'notifications':self.notifications[drive],
      'usb':{'direct':True,'software_reconnect':True},'discovered':{'model':self.drives[drive][0],'media_kind':'flash'}})
    if action=='config':return ok({'revision':'r1','config':{'disk':{'uuid':self.drives[drive][1]},'docker':{'containers':[]},
      'monitor':{'interval':15,'observations':2},'recovery':{'wait':60},'usb':{'enumeration_seconds':20},'standby':{'idle_seconds':900}}})
    if action=='monitor':self.monitor[drive]=data['enabled'];return ok({'message':'Monitoring updated.'})
    if action=='notification-settings':assert data['revision']=='r1';self.notifications[drive]=data['enabled'];return ok({'message':'Saved.'})
    if action=='recovery-plan':return ok({'uuid':self.drives[drive][1],'token':'review-123','message':'Review recovery settings.'})
    if action=='recovery-settings':
      assert data['token']=='review-123' and data['consent'] is True;self.recovery[drive]=data['enabled'];return ok({'message':'Saved.'})
    if action=='fleet-events':return ok({'events':[{'drive_id':'legacy','title':'ADATA recovered','time':'2026-10-31T02:00:00Z'},
      {'drive_id':'drive-b','title':'SanDisk connected','time':'2026-10-31T01:00:00Z'}]})
    if action=='application-images':return ok({'images':[]})
    if action=='image-discover':return ok({'images':[],'truncated':False})
    if action=='image-plan':return ok({'message':'Image creation reviewed.','token':'image-123'})
    if action=='image-apply':return ok({'message':'Image saved.'})
    if action=='prepare-disks':return ok({'disks':[{'device':'/dev/disk/by-id/usb-test','model':'TEST USB','size':4_000_000_000,'serial':'SYNTH123','reason':''}],'operations':[]})
    if action=='prepare-drive-plan':return ok({'model':'TEST USB','size':4_000_000_000,'serial':'SYNTH123','phrase':'ERASE SYNTH123','token':'format-123'})
    if action=='global-config':return ok({'smtp':{'host':'example.test','port':465,'security':'tls','username':'tester','sender':'test@example.test','recipient':'test@example.test'},'network':{'lan':False,'scheme':'https','address':'127.0.0.1'}})
    if action=='integration-info':return ok({'module':{'available':False},'certificate_pem':None})
    if action=='logout':self.session=False;return ok({'message':'Signed out.'})
    return {'status':400,'body':{'error':'No mock handler for '+action}}

def run():
  with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
    for width in (320,390,768,1440):
      b=MockBroker();page=browser.new_page(viewport={'width':width,'height':900});errors=[]
      page.on('pageerror',lambda err:errors.append(str(err)))
      html=(ROOT/'index.html').read_text().replace('<link rel="stylesheet" href="/static/style.css">','').replace('<script src="/static/app.js" defer></script>','')
      page.set_content(html)
      page.add_style_tag(content=(ROOT/'style.css').read_text())
      page.expose_binding('mock_usw',lambda _source,req:b.reply(req))
      page.evaluate("""(()=>{const nativeFetch=window.fetch.bind(window); window.fetch=async(url,opts={})=>{
        if(!String(url).startsWith('/api/'))return nativeFetch(url,opts);
        const r=await window.mock_usw({url:String(url),method:opts.method||'GET',data:opts.body?JSON.parse(opts.body):null});
        return new Response(JSON.stringify(r.body),{status:r.status,headers:{'Content-Type':'application/json'}});
      };})()""")
      page.add_script_tag(content=(ROOT/'app.js').read_text())
      expect(page.get_by_role('heading',name='Connect to USB Storage Watch')).to_be_visible()
      page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').click()
      expect(page.get_by_role('heading',name='USB drive overview')).to_be_visible(timeout=12000)
      expect(page.locator('[data-drive-card]')).to_have_count(2)
      assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Overflow on Overview at {width}'
      if width==1440:page.screenshot(path='/mnt/data/USB-Storage-Watch-UI1-Overview.png',full_page=True)
      page.locator('[data-drive-card="legacy"] [data-action="manage-drive"]').click()
      expect(page.get_by_role('heading',name='ADATA USB Flash Drive',exact=True).first).to_be_visible(timeout=10000)
      if width==1440:page.screenshot(path='/mnt/data/USB-Storage-Watch-UI1-Manage-Drive.png',full_page=True)
      page.locator('[data-toggle="drive-setting"][data-key="notifications"]').uncheck()
      page.wait_for_function('()=>window.fetch && !document.querySelector("[data-toggle=notifications]")',timeout=1000) if False else None
      page.wait_for_timeout(300)
      assert b.notifications['legacy'] is False and b.notifications['drive-b'] is False
      page.locator('[data-action="toggle-monitoring"]').first.click()
      page.wait_for_timeout(400)
      assert b.monitor['legacy'] is False and b.monitor['drive-b'] is False
      page.locator('[data-toggle="drive-setting"][data-key="recovery"]').click()
      expect(page.get_by_role('heading',name='Disable automatic recovery?')).to_be_visible()
      page.locator('#modal-root [data-action="confirmed-action"]').click()
      page.wait_for_timeout(350)
      assert b.recovery['legacy'] is False and b.recovery['drive-b'] is False
      def navigate(tab):
        if width<=670:page.locator('[data-action="menu"]').click()
        page.locator(f'[data-action="nav"][data-value="{tab}"]').click()
      navigate('history')
      expect(page.get_by_role('heading',name='Event History')).to_be_visible()
      expect(page.locator('.history-entry')).to_have_count(2)
      page.locator('#history-filter').select_option('legacy')
      expect(page.locator('.history-entry')).to_have_count(1)
      navigate('images')
      expect(page.get_by_role('heading',name='Virtual Disk Images (.img)')).to_be_visible()
      # Switching tabs must not fire background image scans or display errors.
      scans=lambda:len([call for call in b.calls if call[2]=='image-discover'])
      page.locator('[data-action="image-tab"][data-value="import"]').click()
      expect(page.get_by_role('button',name='Scan USB drive')).to_be_enabled()
      assert scans()==0,'Switching tabs unexpectedly scanned the storage device'
      page.locator('[data-action="rescan-images"]').click()
      page.wait_for_timeout(120)
      assert scans()==1,'One explicit click should trigger exactly one image scan'
      page.locator('[data-action="image-tab"][data-value="create"]').click()
      page.locator('#new-image-name').fill('scratch');page.locator('#new-image-capacity').fill('1')
      page.locator('[data-form="image-create"] button').click()
      expect(page.get_by_role('heading',name='Create virtual disk image?')).to_be_visible()
      page.locator('#modal-root [data-action="close-modal"]').click()
      assert not any(c[2]=='image-apply' for c in b.calls)
      navigate('prepare')
      expect(page.get_by_role('heading',name='Prepare Drive')).to_be_visible()
      expect(page.locator('[data-action="format-review"]')).to_be_disabled()
      page.locator('[data-change="prepare-selection"]').first.check()
      page.locator('[data-action="format-review"]').click()
      expect(page.get_by_role('heading',name='Permanently erase this USB drive?')).to_be_visible()
      expect(page.locator('[data-action="confirm-real-format"]')).to_be_disabled()
      page.locator('#modal-root [data-action="close-modal"]').click()
      assert not any(c[2]=='prepare-drive' for c in b.calls)
      for tab,title in [('email','Email & Notifications'),('apps','Docker & Applications'),('integrations','Integrations'),('advanced','Advanced Settings')]:
        navigate(tab)
        expect(page.get_by_role('heading',name=title)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Overflow on {tab} at {width}'
      # A drive that is not mounted must not invite an operation destined to fail.
      b.mounted['legacy']=False
      page.evaluate('refreshFleet({display:false})')
      page.wait_for_timeout(120)
      navigate('images')
      page.locator('[data-action="image-tab"][data-value="import"]').click()
      expect(page.get_by_text('This USB drive is not mounted.',exact=False)).to_be_visible()
      expect(page.get_by_role('button',name='Scan USB drive')).to_be_disabled()
      page.locator('[data-action="image-tab"][data-value="create"]').click()
      expect(page.locator('[data-form="image-create"] button')).to_be_disabled()
      assert scans()==1,'Unmounted drive must not be scanned'
      assert not errors,f'Browser errors at {width}px: {errors}'
      print(f'PASS {width}px — token login, explicit scan, unmounted-drive guidance, safe image controls and no overflow')
      page.close()
    browser.close()

if __name__=='__main__':run()
