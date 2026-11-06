"""UI5 interactive Chromium actions, no hardware or network changes."""
from playwright.sync_api import sync_playwright,expect
from test_approved_ui_live import ROOT,MockBroker
UUID='33333333-3333-4333-8333-333333333333'
class Fake(MockBroker):
 def __init__(self):
  super().__init__();self.scheme='https';self.op='synthetic';self.pref=True;self.new_event=False;self.calls_ui5=[]
 def reply(self,r):
  action=r['url'].split('?')[0].split('/')[-1]
  if self.session:
   if action=='global-config':return dict(status=200,body=dict(smtp={},network=dict(lan=True,scheme=self.scheme,address='192.168.50.24')))
   if action=='lan-info':return dict(status=200,body=dict(addresses=[dict(address='192.168.50.24')],fingerprint='SYNTHETIC',certificate=True))
   if action=='lan-auto':self.scheme=r['data']['scheme'];self.calls_ui5.append(r['data']);return dict(status=200,body=dict(operation=self.op,pending=True))
   if action=='lan-status':return dict(status=200,body=dict(operation=self.op,phase='complete'))
   if action=='application-images':return dict(status=200,body=dict(images=[dict(name='virtual1',uuid=UUID,enabled=self.pref,size=2147483648,image='/mnt/test/virtual1.img',mountpoint='/mnt/test/virtual1',mount_state='mounted')]))
   if action=='image-action':self.pref=r['data']['enabled'];self.calls_ui5.append(r['data']);return dict(status=200,body=dict(message='Preference saved.'))
   if action=='fleet-events':
    events=[dict(drive_id='legacy',title='Initial event',time='2026-10-31T15:00:00Z'),dict(drive_id='drive-b',title='Other disk',time='2026-10-31T14:00:00Z')]
    if self.new_event:events.insert(0,dict(drive_id='legacy',title='New manual event',time='2026-10-31T16:00:00Z'))
    return dict(status=200,body=dict(events=events))
  return super().reply(r)

def run():
 html=(ROOT/'index.html').read_text().replace('<link rel="stylesheet" href="/static/style.css">','').replace('<script src="/static/app.js" defer></script>','')
 with sync_playwright() as p:
  b=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  for width in (320,390,768,1440):
   fake=Fake();page=b.new_page(viewport=dict(width=width,height=850));page.set_default_timeout(9000);errors=[]
   page.on('pageerror',lambda error:errors.append(str(error)))
   page.set_content(html);page.add_style_tag(content=(ROOT/'style.css').read_text())
   page.expose_binding('test_api',lambda _src,request:fake.reply(request))
   page.evaluate('''()=>{window.fetch=async(url,opts={})=>{const r=await window.test_api({url:String(url),method:opts.method||'GET',data:opts.body?JSON.parse(opts.body):null});return new Response(JSON.stringify(r.body),{status:r.status,headers:{'Content-Type':'application/json'}})}}''')
   page.add_script_tag(content=(ROOT/'app.js').read_text())
   page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').click()
   expect(page.locator('[data-drive-card]')).to_have_count(2)
   def nav(k):
    if width<=670:page.locator('[data-action="menu"]').click()
    page.locator(f'[data-action="nav"][data-value="{k}"]').click()
   nav('images');page.locator('[data-action="image-tab"][data-value="configured"]').click()
   box=page.locator('[data-toggle="image-recovery"]');expect(box).to_be_checked();box.uncheck();expect(box).not_to_be_checked()
   page.wait_for_function('()=>!apiBusy');assert fake.pref is False
   expect(page.locator('[data-action="image-toggle-mount"]')).to_contain_text('Unmount image')
   box.check();page.wait_for_function('()=>!apiBusy');assert fake.pref is True
   nav('history');expect(page.locator('#history-events .history-entry')).to_have_count(2)
   page.locator('#history-filter').select_option('legacy');fake.new_event=True
   page.locator('[data-action="refresh-events"]').click();expect(page.locator('#history-events .history-entry')).to_have_count(2)
   expect(page.locator('#history-filter')).to_have_value('legacy')
   page.locator('[data-action="refresh-events"]').click();expect(page.locator('#history-events .history-entry')).to_have_count(2)
   nav('advanced');details=page.locator('details').filter(has=page.locator('#network-security'));details.locator('summary').click()
   page.locator('#network-security').select_option('http');button=page.locator('[data-action="apply-network-security"]');expect(button).to_be_enabled();button.click()
   expect(page.get_by_role('heading',name='Apply network security?')).to_be_visible();page.locator('#modal-root [data-action="confirmed-action"]').click()
   expect(page.locator('#modal-root')).to_be_empty(timeout=10000);page.wait_for_function("()=>state.lanSecure==='http'")
   assert len(fake.calls_ui5)==3 and fake.calls_ui5[-1]['scheme']=='http',fake.calls_ui5
   if page.locator('#network-security').is_hidden():details.locator('summary').click()
   page.locator('#network-security').select_option('https');page.locator('[data-action="apply-network-security"]').click()
   page.locator('#modal-root [data-action="confirmed-action"]').click();expect(page.locator('#modal-root')).to_be_empty(timeout=10000)
   page.wait_for_function("()=>state.lanSecure==='https'")
   assert len(fake.calls_ui5)==4 and fake.calls_ui5[-1]['scheme']=='https'
   assert not errors,errors
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Horizontal overflow'
   print('PASS UI5 browser',width,'px: image preference, manual events refresh, network apply, responsive design')
   page.close()
  b.close()
if __name__=='__main__':run()
