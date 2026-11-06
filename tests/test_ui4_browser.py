"""UI4 Chromium workflows against synthetic JSON transport; no host/disk operations."""
from playwright.sync_api import sync_playwright, expect
from test_approved_ui_live import ROOT, MockBroker

class API(MockBroker):
  def reply(self, req):
    action=req['url'].split('?')[0].split('/')[-1]
    if self.session and action=='disk-operation':
      self.calls.append((req['method'],req['url'].split('/api/drives/')[1].split('/')[0],action,req.get('data')))
      return {'status':200,'body':{'message':'USB port re-enabled; disk identity verified.'}}
    if self.session and action=='lan-info':
      return {'status':200,'body':{'certificate':True,'fingerprint':'SHA256:EXAMPLE-TEST-ONLY'}}
    if self.session and action=='management-token':
      self.session=False
      return {'status':200,'body':{'message':'Management token replaced.','management_token':'synthetic-replacement'}}
    if self.session and action=='standby-settings':
      return {'status':200,'body':{'message':'HDD standby saved.'}}
    if action=='global-config':
      return {'status':200,'body':{'smtp':{'host':'mail.example.test','port':465,'security':'tls','username':'test','sender':'test@example.test','recipient':'test@example.test'},'network':{'lan':True,'scheme':'https','address':'192.0.2.10'}}}
    result=super().reply(req)
    if action=='fleet-status' and result['status']==200:
      for row in result['body']['drives']:
        if row['profile_id']=='drive-b':row['media_kind']='hdd'
    if action=='status' and result['status']==200:
      if '/drive-b/' in req['url']:
        result['body']['standby']={'applicable':True,'state':'idle','enabled':False,'idle_seconds':900}
        result['body']['discovered']['media_kind']='hdd'
    return result

def run():
  html=(ROOT/'index.html').read_text().replace('<link rel="stylesheet" href="/static/style.css">','').replace('<script src="/static/app.js" defer></script>','')
  with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
    for width in (390,1440):
      b=API();b.monitor['legacy']=False;page=browser.new_page(viewport={'width':width,'height':900});errors=[]
      page.on('pageerror',lambda e: errors.append(str(e)))
      page.set_content(html);page.add_style_tag(content=(ROOT/'style.css').read_text())
      page.expose_binding('mock_usw',lambda _source,req:b.reply(req))
      page.evaluate('''(()=>{window.fetch=async(url,opts={})=>{
        if(String(url).includes('/disk-operation'))await new Promise(resolve=>setTimeout(resolve,850));
        const res=await window.mock_usw({url:String(url),method:opts.method||'GET',data:opts.body?JSON.parse(opts.body):null});
        return new Response(JSON.stringify(res.body),{status:res.status,headers:{'Content-Type':'application/json'}});
      };})()''')
      page.add_script_tag(content=(ROOT/'app.js').read_text())
      page.locator('#usw-login-token').fill('synthetic-token');page.locator('#usw-login-form button').click()
      expect(page.locator('[data-drive-card]')).to_have_count(2)
      page.locator('[data-drive-card="legacy"] [data-action="manage-drive"]').click()
      expect(page.get_by_text('Monitoring off',exact=True).first).not_to_have_css('color','rgb(236, 170, 74)')
      page.locator('[data-action="reconnect-drive"]').click()
      confirm=page.locator('#modal-root [data-action="confirmed-action"]')
      cancel=page.locator('#modal-root [data-action="close-modal"]')
      confirm.click()
      expect(confirm).to_be_disabled()
      expect(cancel).to_be_disabled()
      expect(page.locator('#modal-root .modal-progress')).to_be_visible()
      # Programmatic clicks on disabled controls must not send another operation.
      page.evaluate("document.querySelector('#modal-root [data-action=confirmed-action]').click();document.querySelector('#modal-root [data-action=close-modal]').click()")
      expect(confirm).to_be_disabled()
      page.wait_for_timeout(1000)
      assert len([c for c in b.calls if c[2]=='disk-operation'])==1,b.calls
      expect(page.locator('#modal-root')).to_be_empty()
      # Select mechanical test HDD for standby settings.
      if width<=670:page.locator('[data-action="menu"]').click()
      page.locator('[data-action="nav"][data-value="advanced"]').click()
      expect(page.locator('.network-trust summary')).to_be_visible()
      page.locator('.network-trust summary').click()
      expect(page.get_by_text('Download local HTTPS trust certificate')).to_be_visible()
      page.locator('#advanced-drive').select_option('drive-b')
      expect(page.get_by_role('heading',name='HDD standby & noise control')).to_be_visible()
      expect(page.locator('#standby-idle')).to_have_value('15')
      # Management token rotation is confirmed and invalidates the current session.
      page.locator('[data-action="rotate-token"]').click()
      expect(page.get_by_role('heading',name='Replace management token?')).to_be_visible()
      page.locator('#modal-root [data-action="confirmed-action"]').click()
      expect(page.get_by_role('heading',name='Connect to USB Storage Watch')).to_be_visible()
      assert not errors,errors
      print('PASS UI4',width,'px: pending-modal lock, network trust, mechanical HDD controls, token rotation')
      page.close()
    browser.close()
if __name__=='__main__':run()
