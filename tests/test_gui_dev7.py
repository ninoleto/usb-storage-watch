# SPDX-License-Identifier: MIT
"""Real-browser DEV7 regressions. OS/storage/SMTP boundaries remain isolated."""
import unittest
import test_gui_advanced as fixture


@unittest.skipUnless(fixture.AVAILABLE,'Development-only Playwright/Flask dependencies absent')
class DEV7GUI(unittest.TestCase):
    setUpClass=classmethod(fixture.AdvancedGUIWorkflowTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.AdvancedGUIWorkflowTests.tearDownClass.__func__)
    setUp=fixture.AdvancedGUIWorkflowTests.setUp
    tearDown=fixture.AdvancedGUIWorkflowTests.tearDown
    configured=fixture.AdvancedGUIWorkflowTests.configured
    nav=fixture.AdvancedGUIWorkflowTests.nav
    advanced=fixture.AdvancedGUIWorkflowTests.advanced

    def pages(self,view):
        token=self.m.management_token();result=[]
        for width in (1280,768,390):
            context=self.browser.new_context(viewport=dict(width=width,height=1000))
            self.addCleanup(context.close);page=context.new_page();page.set_default_timeout(7000)
            page.on('pageerror',lambda error:self.errors.append(str(error)))
            page.goto('http://127.0.0.1:'+str(self.server.server_port)+'/#'+view)
            page.locator('#management-token').fill(token);page.get_by_role('button',name='Connect',exact=True).click()
            page.locator('#login').wait_for(state='hidden');result.append(page)
        return result

    def poll_counts(self,pages):
        counts=[0]*len(pages)
        for i,page in enumerate(pages):
            def received(response,index=i):
                if any(response.url.endswith(v) for v in ('/status','/lan-info','/notification-preferences')) and response.status==200:counts[index]+=1
            page.on('response',received)
        return counts

    def test_retrieval_help_and_explicit_transition_retirement(self):
        from playwright.sync_api import expect
        legacy=self.m.management_token()
        self.m.patch(self.m.b.auth,'installation_account',lambda _:'admin')
        self.m.b.auth.ensure_management_token(self.m.config.with_name('management-token.json'),self.m.state)
        token=(self.m.state/'management.token').read_text().strip()
        self.page.get_by_role('button',name='Sign out',exact=True).click()
        expect(self.page.get_by_role('heading',name='Where do I find my token?',exact=True)).to_be_visible()
        expect(self.page.get_by_text('sudo cat /var/lib/usb-storage-watch/management.token',exact=True)).to_be_visible()
        expect(self.page.get_by_role('button',name='Copy command',exact=True)).to_be_visible()
        self.context.grant_permissions(['clipboard-read','clipboard-write'])
        self.page.get_by_role('button',name='Copy command',exact=True).click()
        self.assertEqual(self.page.evaluate('navigator.clipboard.readText()'),'sudo cat /var/lib/usb-storage-watch/management.token')
        expect(self.page.locator('#bootstrap-login')).to_be_hidden()
        self.page.locator('#management-token').fill(token);self.page.get_by_role('button',name='Connect',exact=True).click()
        self.nav('Advanced')
        expect(self.page.locator('#management-access')).to_contain_text('DEV6')
        self.assertNotIn(token,self.page.locator('body').inner_text())
        self.assertNotIn(legacy,self.page.locator('body').inner_text())
        self.page.get_by_role('button',name='Replace management token',exact=True).click()
        expect(self.page.locator('#token-created')).to_be_visible()
        self.assertNotEqual(self.page.locator('#created-token').input_value(),token)
        self.assertEqual(self.page.locator('#created-token').input_value(),(self.m.state/'management.token').read_text().strip())

    def test_nested_permission_form_survives_three_real_polls_all_viewports(self):
        from playwright.sync_api import expect
        self.configured();self.m.active=True;pages=self.pages('drive/legacy');counts=self.poll_counts(pages)
        for page in pages:
            page.locator('#technical-drive-details summary').first.click()
            page.get_by_role('button',name='Change permissions / Fix folder access',exact=True).click()
            page.locator('#folder-access').select_option('custom')
            page.get_by_text('Technical permission details',exact=True).click()
            page.locator('#folder-uid').fill('5012');page.locator('#folder-gid').fill('5013')
            page.locator('#folder-rights').select_option('r-x');page.locator('#folder-uid').focus()
            page.evaluate("""() => {window.keptInput=document.querySelector('#folder-uid');window.keptParent=document.querySelector('#technical-drive-details');const node=document.querySelector('.permissions-editor p');const range=document.createRange();range.selectNodeContents(node);getSelection().removeAllRanges();getSelection().addRange(range);window.keptSelection=getSelection().toString();window.keptScroll=scrollY;window.keptTop=keptInput.getBoundingClientRect().top;}""")
        self.m.present=False  # A real status change must render without discarding the editor.
        pages[0].wait_for_timeout(11000)  # Real production interval (10 s), never mocked.
        for page in pages:page.evaluate('window.scrollAfterStatusChange=scrollY')
        pages[0].wait_for_timeout(21000)
        for index,page in enumerate(pages):
            with self.subTest(width=page.viewport_size['width']):
                self.assertGreaterEqual(counts[index],3)
                expect(page.locator('#drive-panel')).to_contain_text('Disconnected')
                expect(page.locator('#folder-access')).to_have_value('custom')
                expect(page.locator('#folder-uid')).to_have_value('5012')
                expect(page.locator('#folder-gid')).to_have_value('5013')
                expect(page.locator('#folder-rights')).to_have_value('r-x')
                self.assertTrue(page.evaluate('keptInput.isConnected && document.activeElement===keptInput && keptParent.open'))
                self.assertTrue(page.locator('#folder-uid').evaluate('(e)=>e.closest("details").open'))
                self.assertEqual(page.evaluate('getSelection().toString()'),page.evaluate('keptSelection'))
                # Chromium anchors the focused field when new status text changes
                # page height. Verify its viewport position, then stable scrolling.
                self.assertLess(abs(page.evaluate('keptInput.getBoundingClientRect().top-keptTop')),5)
                self.assertLess(abs(page.evaluate('scrollY-scrollAfterStatusChange')),5)
        self.assertTrue(self.m.active)  # Polling/editing never pauses the engine.

    def test_drive_image_timing_and_text_drafts_survive_real_polls(self):
        from playwright.sync_api import expect
        self.configured();pages=self.pages('drive/legacy');counts=self.poll_counts(pages)
        for page in pages:
            page.locator('#drive-settings summary').first.click();page.locator('#image-name').fill('Unsaved image name')
            page.locator('#image-size').fill('44');page.locator('#image-editor').get_by_text('Technical settings',exact=True).click()
            page.locator('#image-path').fill('/mnt/storage/draft.img');page.locator('#image-mount').fill('/mnt/storage/draft-folder')
            page.locator('#monitor-interval').fill('65');page.locator('#service-units').fill('example-draft.service')
            page.locator('#image-name').focus();page.locator('#image-name').evaluate('(e)=>{window.editorInput=e;e.setSelectionRange(2,8);window.scrollBefore=scrollY}')
        pages[0].wait_for_timeout(32000)
        for index,page in enumerate(pages):
            self.assertGreaterEqual(counts[index],3)
            for selector,value in [('image-name','Unsaved image name'),('image-size','44'),('image-path','/mnt/storage/draft.img'),('image-mount','/mnt/storage/draft-folder'),('monitor-interval','65'),('service-units','example-draft.service')]:expect(page.locator('#'+selector)).to_have_value(value)
            self.assertTrue(page.evaluate('window.editorInput.isConnected && document.activeElement===editorInput && editorInput.selectionStart===2 && editorInput.selectionEnd===8'))
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),page.viewport_size['width'])
            self.assertLess(abs(page.evaluate('scrollY-scrollBefore')),5)
        self.assertEqual(self.m.b.configuration()['monitor']['interval'],15);self.assertFalse(self.m.active)

    def test_global_network_drafts_survive_real_polls(self):
        from playwright.sync_api import expect
        addresses=[dict(address='10.0.0.2',interface='test0'),dict(address='10.0.0.3',interface='test0')]
        self.m.patch(self.m.b,'lan_info',lambda:dict(addresses=addresses,certificate='',available=False,enabled=False,scheme='http',url=None,message='LAN access disabled.'))
        pages=self.pages('advanced');counts=self.poll_counts(pages)
        for page in pages:
            page.get_by_text('Technical network settings',exact=True).click();page.locator('#local-address').select_option('10.0.0.3')
            page.get_by_text('Custom HTTPS certificate',exact=True).click();page.locator('#lan-hostname').fill('draft.example.test')
            page.locator('#lan-certificate').set_input_files(dict(name='draft.crt',mimeType='text/plain',buffer=b'synthetic public certificate draft'))
            page.locator('#lan-hostname').focus();page.locator('#lan-hostname').evaluate('(e)=>{window.editorInput=e;e.setSelectionRange(2,8)}')
        addresses[:]=[dict(address='10.0.0.2',interface='test0'),dict(address='10.0.0.4',interface='test1')]
        pages[0].wait_for_timeout(32000)
        for index,page in enumerate(pages):
            self.assertGreaterEqual(counts[index],3);expect(page.locator('#local-address')).to_have_value('10.0.0.3')
            expect(page.locator('#lan-hostname')).to_have_value('draft.example.test')
            self.assertTrue(page.evaluate('window.editorInput.isConnected && document.activeElement===editorInput && editorInput.selectionStart===2 && editorInput.selectionEnd===8'))
            self.assertTrue(page.locator('#lan-hostname').evaluate('(e)=>e.closest("details").open && e.closest("details").parentElement.closest("details").open'))
            self.assertEqual(page.locator('#lan-certificate').evaluate('(e)=>e.files[0].name'),'draft.crt')

    def test_email_sections_drafts_and_actions_remain_independent_during_polling(self):
        from playwright.sync_api import expect
        from unittest.mock import Mock
        self.configured();self.m.active=True
        smtp=dict(version=1,host='smtp.example.test',port=587,security='starttls',username='sender',password='DUMMY-TEST-SECRET',sender='sender@example.test',recipient='recipient@example.test')
        self.m.b.cli.save(self.m.b.s.SMTP,smtp)
        send=self.m.patch(self.m.b.n,'bounded_send',Mock(return_value=(True,'SMTP accepted the test message. Inbox delivery is not verified.')))
        pages=self.pages('email');counts=self.poll_counts(pages)
        for page in pages:
            expect(page.get_by_role('heading',name='Email account settings',exact=True)).to_be_visible()
            expect(page.get_by_role('heading',name='Email notifications',exact=True)).to_be_visible()
            page.locator('#smtp-host').fill('unsaved.example.test');page.locator('#smtp-recipient').fill('draft@example.test')
            page.locator('#smtp-password').fill('DUMMY-UNSAVED-PASSWORD');page.locator('#notifications-legacy').check()
            page.locator('#smtp-host').focus();page.locator('#smtp-host').evaluate('(e)=>e.setSelectionRange(2,9)')
        pages[0].wait_for_timeout(32000)
        for index,page in enumerate(pages):
            with self.subTest(width=page.viewport_size['width']):
                self.assertGreaterEqual(counts[index],3)
                expect(page.locator('#smtp-host')).to_have_value('unsaved.example.test')
                expect(page.locator('#smtp-recipient')).to_have_value('draft@example.test')
                expect(page.locator('#smtp-password')).to_have_value('DUMMY-UNSAVED-PASSWORD')
                expect(page.locator('#notifications-legacy')).to_be_checked()
                expect(page.locator('#notification-state-legacy')).to_have_text('Notifications disabled')
                self.assertTrue(page.locator('#smtp-host').evaluate('(e)=>document.activeElement===e && e.selectionStart===2 && e.selectionEnd===9'))
                page.mouse.move(0,0)  # Inspect base colors, not a pointer-dependent hover color after scrolling.
                colors=[page.get_by_role('button',name=name,exact=True).evaluate('(e)=>getComputedStyle(e).backgroundColor') for name in ['Save email settings','Save notification preference','Send test email']]
                self.assertEqual(colors[:2],['rgb(85, 54, 121)']*2);self.assertEqual(colors[2],'rgb(128, 64, 25)')
                if page.viewport_size['width']<680:
                    heading=page.locator('#page-title').bounding_box()
                    self.assertGreater(heading['width'],200);self.assertLess(heading['height'],80)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),page.viewport_size['width'])
        page=pages[0];page.get_by_role('button',name='Save notification preference',exact=True).click()
        expect(page.locator('#notification-state-legacy')).to_have_text('Notifications enabled')
        expect(page.locator('#notification-result-legacy')).not_to_be_empty()
        expect(page.locator('#smtp-host')).to_have_value('unsaved.example.test')
        self.assertEqual(self.m.b.n.load_config()['host'],'smtp.example.test')
        page.get_by_role('button',name='Send test email',exact=True).click()
        expect(page.locator('#email-result')).to_contain_text('Inbox delivery is not verified')
        self.assertEqual(self.m.b.n.load_config()['password'],'DUMMY-TEST-SECRET');self.assertTrue(self.m.active);send.assert_called_once()
        page.locator('#smtp-password').fill('');page.get_by_role('button',name='Save email settings',exact=True).click()
        expect(page.locator('#email-result')).to_contain_text('Email settings saved')
        self.assertEqual(self.m.b.n.load_config()['host'],'unsaved.example.test')
        self.assertEqual(self.m.b.n.load_config()['password'],'DUMMY-TEST-SECRET')
        self.assertTrue(self.m.b.configuration()['notifications']['enabled'])

if __name__=='__main__':unittest.main()
