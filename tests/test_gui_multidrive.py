# SPDX-License-Identifier: MIT
"""Real Chromium multi-drive workflows; no physical disks or services."""
import importlib.util
import threading
import unittest
from multidrive_fixture import FleetMachine,SECOND
AVAILABLE=importlib.util.find_spec('playwright') and importlib.util.find_spec('flask')


@unittest.skipUnless(AVAILABLE,'Development-only Playwright/Flask dependencies absent')
class MultiDriveGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright=sync_playwright().start();cls.browser=cls.playwright.chromium.launch()
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.playwright.stop()
    def setUp(self):
        from werkzeug.serving import make_server,WSGIRequestHandler
        class Quiet(WSGIRequestHandler):
            def log(self,*a,**kw):pass
        self.f=FleetMachine();self.addCleanup(self.f.close);self.m=self.f.main;self.errors=[]
        self.token=self.m.management_token()
        self.server=make_server('127.0.0.1',0,lambda e,s:[],request_handler=Quiet,threaded=True)
        self.server.app=self.m.web.create_app(dict(self.m.b.common.DEFAULT,port=self.server.server_port),self.m.broker.handle)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(self.server.shutdown(),self.server.server_close(),thread.join(5)))
    def tearDown(self):self.assertEqual(self.errors,[])
    def page(self,width=1280):
        context=self.browser.new_context(viewport=dict(width=width,height=1000));self.addCleanup(context.close)
        page=context.new_page();page.set_default_timeout(7000);page.on('pageerror',lambda err:self.errors.append(str(err)))
        page.goto('http://127.0.0.1:'+str(self.server.server_port));page.locator('#management-token').fill(self.token)
        page.get_by_role('button',name='Connect',exact=True).click();page.locator('.fleet-drive').first.wait_for();return page
    def test_add_and_monitor_second_drive_without_stopping_first(self):
        from playwright.sync_api import expect
        page=self.page();before=self.m.config.read_bytes()
        a=page.locator('.fleet-drive').filter(has_text='ADATA USB Flash Drive')
        b=page.locator('.fleet-drive').filter(has_text='SanDisk 3.2Gen1')
        expect(a).to_contain_text('Monitoring on');expect(b).to_contain_text('Monitoring off')
        page.get_by_role('button',name='Add USB drive',exact=True).first.click()
        expect(page.get_by_role('heading',name='Select a USB drive to add',exact=True)).to_be_visible()
        expect(page.locator('input[name=add-drive]')).to_have_count(1)
        page.locator('input[name=add-drive]').check()
        page.get_by_role('button',name='Add selected drive',exact=True).click()
        self.assertTrue(self.m.active);self.assertEqual(self.m.config.read_bytes(),before)
        page.get_by_role('button',name='Enable automatic recovery',exact=True).click()
        page.get_by_role('button',name='Confirm recovery setting',exact=True).click()
        page.get_by_role('button',name='Disable automatic recovery',exact=True).wait_for()
        page.get_by_role('button',name='Start monitoring',exact=True).click()
        expect(page.locator('#drive-panel')).to_contain_text('Monitoring on')
        page.get_by_role('button',name='Back to Overview',exact=True).click()
        expect(page.locator('.fleet-drive')).to_have_count(2)
        expect(page.locator('.fleet-drive').filter(has_text='SanDisk 3.2Gen1')).to_contain_text('Monitoring on')
        self.assertTrue(self.m.active);self.assertTrue(self.f.second.active);self.assertEqual(self.m.config.read_bytes(),before)
        b=page.locator('.fleet-drive').filter(has_text='SanDisk 3.2Gen1');b.get_by_role('button',name='Stop monitoring',exact=True).click()
        expect(b).to_contain_text('Monitoring off');self.assertTrue(self.m.active);self.assertFalse(self.f.second.active)
        b.get_by_role('button',name='Manage drive',exact=True).click()
        expect(page.locator('#drive-panel')).to_contain_text('SanDisk 3.2Gen1')
        expect(page.locator('#drive-panel')).to_contain_text('/mnt/drive-b')
        self.assertEqual(page.url.split('/')[-1],self.f.second.b.s.PROFILE_ID)
        expect(page.get_by_role('button',name='Unmount safely',exact=True)).to_be_visible()
        page.get_by_role('button',name='Back to Overview',exact=True).click()
        page.locator('.fleet-drive').filter(has_text='ADATA USB Flash Drive').get_by_role('button',name='Manage drive',exact=True).click()
        expect(page.locator('#drive-panel')).to_contain_text('/mnt/drive-a')
        self.assertEqual(page.url.split('/')[-1],'legacy')
        self.m.patch(self.m.b.w.usb,'connection_details',lambda _:dict(direct=False,software_reconnect=False,message='Intermediate hub detected.'))
        page.get_by_role('button',name='Back to Overview',exact=True).click()
        a=page.locator('.fleet-drive').filter(has_text='ADATA USB Flash Drive')
        expect(a.locator('.hub-warning')).to_contain_text('automatic mounting is available')
        a.get_by_role('button',name='Manage drive',exact=True).click()
        expect(page.get_by_role('button',name='Reconnect USB port',exact=False)).to_be_disabled()
        expect(page.get_by_role('button',name='Unmount safely',exact=True)).to_be_enabled()

    def test_hash_navigation_changes_explicit_target_without_reloading(self):
        from playwright.sync_api import expect
        profile=self.f.add();page=self.page()
        page.goto(page.url.split('#')[0]+'#drive/'+profile)
        expect(page.locator('#drive-panel')).to_contain_text('SanDisk 3.2Gen1')
        page.goto(page.url.split('#')[0]+'#drive/legacy')
        expect(page.locator('#drive-panel')).to_contain_text('ADATA USB Flash Drive')
        page.get_by_role('button',name='Stop monitoring',exact=True).click()
        expect(page.locator('#drive-panel')).to_contain_text('Monitoring off')
        self.assertFalse(self.m.active);self.assertFalse(self.f.second.active)

    def test_independent_tabs_and_nested_forms_survive_real_polling_all_sizes(self):
        from playwright.sync_api import expect
        profile=self.f.add();self.f.second.active=True;pages=[];counts=[]
        for width in (1280,768,390):
            page=self.page(width);page.locator('.fleet-drive').filter(has_text='SanDisk 3.2Gen1').get_by_role('button',name='Manage drive',exact=True).click()
            page.locator('#technical-drive-details summary').first.click()
            page.get_by_role('button',name='Change permissions / Fix folder access',exact=True).click()
            page.locator('#folder-access').select_option('custom');page.get_by_text('Technical permission details',exact=True).click()
            page.locator('#folder-uid').fill('5012');page.locator('#folder-gid').fill('5013');page.locator('#folder-uid').focus()
            page.evaluate("window.keptInput=document.getElementById('folder-uid');window.keptParent=document.getElementById('technical-drive-details')")
            counter=[0]
            def response(value,counter=counter):
                if value.url.endswith('/status') and value.status==200:counter[0]+=1
            page.on('response',response);counts.append(counter);pages.append(page)
        other=self.page();other.locator('.fleet-drive').filter(has_text='ADATA USB Flash Drive').get_by_role('button',name='Manage drive',exact=True).click()
        self.m.present=False;self.m.current=''
        pages[0].wait_for_timeout(32000)  # Three production 10-second polling cycles.
        for page,counter in zip(pages,counts):
            self.assertGreaterEqual(counter[0],3)
            expect(page.locator('#folder-access')).to_have_value('custom');expect(page.locator('#folder-uid')).to_have_value('5012')
            expect(page.locator('#drive-panel')).to_contain_text('SanDisk 3.2Gen1');expect(page.locator('#drive-panel')).to_contain_text('Connected')
            self.assertTrue(page.evaluate('keptInput.isConnected && document.activeElement===keptInput && keptParent.open'))
            self.assertTrue(page.locator('#folder-uid').evaluate('(e)=>e.closest("details").open'))
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),page.viewport_size['width'])
            self.assertEqual(page.url.split('/')[-1],profile)
        expect(other.locator('#drive-panel')).to_contain_text('Disconnected')
        self.assertTrue(self.m.active);self.assertTrue(self.f.second.active)

if __name__=='__main__':unittest.main()
