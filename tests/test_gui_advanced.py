# SPDX-License-Identifier: MIT
"""Real Chromium workflow regressions with isolated OS boundaries.

Run explicitly with Playwright installed; optional in the headless unit suite.
Set USW_GUI_PAYLOAD to an extracted deb's usr/lib/usb-storage-watch to exercise
installed assets and broker code, starting without any saved configuration.
"""
import importlib.util
import threading
import unittest
from gui_fixture import Machine, UUID, DESKTOP, STABLE

AVAILABLE = importlib.util.find_spec('playwright') and importlib.util.find_spec('flask')


@unittest.skipUnless(AVAILABLE, 'Development-only Playwright/Flask browser dependencies absent')
class AdvancedGUIWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.playwright.stop()

    def setUp(self):
        from werkzeug.serving import make_server, WSGIRequestHandler
        class QuietHandler(WSGIRequestHandler):
            def log(self, *args, **kwargs): pass
        self.m = Machine()
        self.addCleanup(self.m.close)
        # Bind only localhost. The actual app validates the assigned port/Origin.
        self.server = make_server('127.0.0.1', 0, lambda e, s: [], request_handler=QuietHandler)
        config = dict(self.m.b.common.DEFAULT, port=self.server.server_port)
        self.server.app = self.m.web.create_app(config, self.m.broker.handle)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        def stop():
            self.server.shutdown(); self.server.server_close(); thread.join(timeout=5)
        self.addCleanup(stop)
        self.context = self.browser.new_context(viewport=dict(width=1280, height=900))
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(7000)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        token=self.m.management_token()
        self.page.goto('http://127.0.0.1:' + str(self.server.server_port))
        self.page.locator('#management-token').fill(token)
        self.page.get_by_role('button', name='Connect', exact=True).click()
        self.page.locator('.fleet-drive').first.wait_for()
        self.assertFalse(self.m.config.exists(), 'A clean install must not have a development configuration')

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def nav(self,name):
        self.page.locator('#shell').wait_for(state='visible')
        target=self.page.locator('nav').get_by_role('button',name=name,exact=True)
        if not target.is_visible():self.page.locator('#menu-toggle').click()
        target.click()

    def configured(self):
        self.page.get_by_role('button',name='Add USB drive',exact=True).first.click()
        self.page.locator('input[name=add-drive]').check()
        self.page.get_by_role('button',name='Add selected drive',exact=True).click()
        self.page.get_by_role('button',name='Enable automatic recovery',exact=True).click()
        self.page.get_by_role('button',name='Confirm recovery setting',exact=True).click()
        self.page.get_by_role('button',name='Disable automatic recovery',exact=True).wait_for()
        self.assertFalse(self.m.active)

    def advanced(self):
        if '/#drive/' not in self.page.url:
            self.nav('Overview');self.page.get_by_role('button',name='Manage drive',exact=True).click()
        panel=self.page.locator('#drive-settings')
        if not panel.evaluate('(e)=>e.open'):panel.locator('summary').first.click()
        self.page.get_by_role('tab',name='Create new',exact=True).wait_for()

    def test_hub_warning_disables_only_reconnect(self):
        from playwright.sync_api import expect
        self.configured()
        self.m.patch(self.m.b.w.usb,'connection_details',lambda _:dict(direct=False,software_reconnect=False,message='Intermediate USB hub'))
        self.m.patch(self.m.b.w.standby,'status',lambda _:dict(state='not-applicable',applicable=False,label='Not applicable for flash storage'))
        self.nav('Overview');self.page.get_by_role('button',name='Manage drive',exact=True).click()
        expect(self.page.get_by_role('button',name='Reconnect USB port',exact=True)).to_be_disabled()
        expect(self.page.get_by_role('button',name='Unmount safely',exact=True)).to_be_enabled()
        expect(self.page.locator('#drive-panel')).to_contain_text('USB hub detected — automatic mounting is available')
        self.assertEqual(self.page.get_by_role('button',name='Sleep HDD now',exact=True).count(),0)
        expect(self.page.locator('#drive-panel')).to_contain_text('Not applicable')
        self.assertEqual(self.page.get_by_role('button',name='Create / replace standby token',exact=True).count(),0)

    def test_old_wizard_removed_settings_have_single_locations(self):
        self.configured();self.advanced()
        for name in ('Continue','Review','Edit advanced storage settings','Qualify USB hardware'):
            self.assertEqual(self.page.get_by_role('button',name=name,exact=True).count(),0)
        self.assertEqual(self.page.locator('#smtp-host').count(),0)
        self.assertEqual(self.page.locator('#automatic-recovery').count(),0)
        self.assertNotIn('Protection',self.page.locator('#page').inner_text())
        self.assertEqual(self.page.get_by_role('button',name='Create / replace integration token',exact=True).count(),0)

    def test_multiple_docker_selections_show_binds_states_and_save(self):
        self.configured()
        rows=[dict(id=str(n)*64,name='app_'+str(n),running=n!=2,eligible=True,reason='',binds=[dict(source=DESKTOP+'/app'+str(n),destination='/data',eligible=True,reason='')]) for n in range(1,4)]
        self.m.b.container_rows.return_value=rows;self.advanced()
        for row in rows:self.page.locator('#container-'+row['id']).check()
        self.page.get_by_role('button',name='Save Docker recovery',exact=True).click()
        self.page.get_by_text('Docker recovery enabled',exact=True).wait_for()
        c=self.m.b.configuration()
        self.assertEqual([v['name'] for v in c['docker']['containers']],['app_1','app_2','app_3'])
        self.assertIn('app_2 · Stopped',self.page.locator('#application-recovery').inner_text())
        for row in rows:self.assertTrue(self.page.locator('#container-'+row['id']).is_checked())

    def test_docker_unavailable_keeps_images_and_settings_accessible(self):
        self.configured();self.m.b.container_rows.side_effect=ValueError('Docker daemon unavailable');self.advanced()
        self.page.get_by_text('Docker discovery is unavailable:',exact=False).wait_for()
        self.page.get_by_role('tab',name='Add existing',exact=True).click()
        self.page.locator('#image-path').wait_for()
        self.assertEqual(self.page.locator('#image-uuid').count(),0)

    def test_new_image_review_requires_explicit_creation_consent(self):
        from unittest.mock import Mock
        from playwright.sync_api import expect
        self.configured()
        self.m.patch(self.m.b.pwd,'getpwnam',Mock(return_value=Mock(pw_uid=1000,pw_gid=1000)))
        item=dict(name='Photos',uuid=UUID,image=DESKTOP+'/photos.img',mountpoint=DESKTOP+'/photos',enabled=True,fstab_options='loop')
        chosen=dict(item=item,size=1024**3,mode='create',token='image-consent')
        plan=self.m.patch(self.m.b.images,'plan',Mock(return_value=chosen))
        apply=self.m.patch(self.m.b.images,'apply',Mock(return_value=dict(message='Image created')))
        self.advanced();self.page.get_by_role('tab',name='Create new',exact=True).click()
        self.page.locator('#image-name').fill('Photos')
        self.page.get_by_role('button',name='Review storage settings',exact=True).click()
        execute=self.page.get_by_role('button',name='Create and format new virtual disk image',exact=True)
        expect(execute).to_be_disabled();apply.assert_not_called()
        self.page.locator('#image-confirm').check();execute.click()
        self.page.get_by_text('Image created',exact=True).wait_for()
        self.assertEqual(plan.call_args.args[1]['name'],'Photos')
        self.assertEqual(apply.call_args.args[2],dict(token='image-consent',confirm=True))

    def test_multiple_images_edit_and_removal_keeps_data_warning(self):
        from unittest.mock import Mock
        self.configured()
        rows=[dict(name='Image '+str(n),uuid=str(n)*8+'-1111-4111-8111-111111111111',image=DESKTOP+'/image'+str(n)+'.img',mountpoint=DESKTOP+'/app'+str(n),enabled=True,mounted=False,fstab_options='loop') for n in (1,2)]
        self.m.patch(self.m.b.images,'entries',lambda _:rows)
        action=self.m.patch(self.m.b.images,'manage',Mock(return_value=dict(message='Configuration removed; file kept')))
        self.advanced()
        self.page.get_by_role('heading',name='Image 1',exact=True).wait_for();self.page.get_by_role('heading',name='Image 2',exact=True).wait_for()
        self.page.get_by_role('button',name='Edit recovery settings',exact=True).nth(1).click()
        self.assertEqual(self.page.locator('#image-path').input_value(),rows[1]['image'])
        self.page.get_by_role('button',name='Cancel',exact=True).click()
        self.page.get_by_role('button',name='Remove recovery configuration',exact=True).first.click()
        self.page.get_by_text('Its image file and all its contents will be kept.',exact=False).wait_for();action.assert_not_called()
        self.page.get_by_role('button',name='Confirm removal — keep image file',exact=True).click()
        self.page.get_by_text('Configuration removed; file kept',exact=True).wait_for()
        self.assertEqual(action.call_args.args[1],dict(uuid=rows[0]['uuid'],action='remove',confirm=True))

    def test_simple_lan_addresses_and_manual_settings_collapsed(self):
        self.configured()
        self.m.patch(self.m.b,'lan_info',lambda:dict(addresses=[dict(address='10.0.0.2',interface='test0',url='https://10.0.0.2:8765')],certificate=''))
        self.nav('Advanced')
        self.page.locator('#local-access').wait_for()
        from playwright.sync_api import expect
        expect(self.page.locator('#local-address')).to_contain_text('10.0.0.2')
        self.assertFalse(self.page.locator('#lan-certificate').is_visible())
        self.page.get_by_text('Technical network settings',exact=True).click()
        self.page.get_by_text('Custom HTTPS certificate',exact=True).click()
        self.assertTrue(self.page.locator('#lan-certificate').is_visible())

    def test_timing_and_services_save_without_wizard(self):
        from playwright.sync_api import expect
        self.configured();self.advanced()
        self.page.locator('#monitor-interval').fill('20')
        self.page.get_by_role('button',name='Save advanced timing',exact=True).click()
        expect(self.page.locator('#notice')).to_have_text('Timing settings saved.')
        self.page.locator('#service-units').fill('example-one.service\nexample-two.service')
        self.page.get_by_role('button',name='Save service recovery',exact=True).click()
        expect(self.page.locator('#notice')).to_have_text('Container recovery settings saved.')
        c=self.m.b.configuration();self.assertEqual(c['monitor']['interval'],20)
        self.assertEqual(c['services']['units'],['example-one.service','example-two.service'])

    def test_location_page_preserves_rollback_access_when_disk_absent(self):
        self.configured()
        self.m.patch(self.m.b.migration,'public',lambda _:dict(phase='prepared',old_mountpoint=DESKTOP,mountpoint=STABLE))
        self.page.get_by_role('button',name='Change mount location',exact=True).click()
        self.page.get_by_role('button',name='Roll back location change',exact=True).wait_for()
        self.assertNotIn('migration',self.page.locator('#page').inner_text().lower())


    def test_mobile_drawer_one_dark_theme_and_no_horizontal_scroll(self):
        from playwright.sync_api import expect
        self.configured();self.page.set_viewport_size(dict(width=390,height=844))
        self.page.locator('#menu-toggle').click();expect(self.page.locator('#menu-toggle')).to_have_attribute('aria-expanded','true')
        self.assertEqual(self.page.locator('#appearance').count(),0)
        expect(self.page.locator('html')).to_have_attribute('data-theme','dark')
        self.page.get_by_role('button',name='Overview',exact=True).click()
        self.page.get_by_role('button',name='Manage drive',exact=True).click();self.advanced()
        expect(self.page.locator('#menu-toggle')).to_have_attribute('aria-expanded','false')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)
        self.page.locator('#menu-toggle').click()
        self.page.emulate_media(color_scheme='light');expect(self.page.locator('html')).to_have_attribute('data-theme','dark')
        self.page.emulate_media(color_scheme='dark');expect(self.page.locator('html')).to_have_attribute('data-theme','dark')
        self.page.locator('#menu-scrim').click(position=dict(x=360,y=400))
        self.page.get_by_role('tab',name='Create new',exact=True).click()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)
        self.assertFalse(self.page.locator('#image-path').is_visible());self.assertFalse(self.page.locator('#image-mount').is_visible())
        self.assertEqual(self.page.locator('#image-size').input_value(),'30')

    def test_numeric_individual_and_group_reset_use_defaults_not_saved_values(self):
        from playwright.sync_api import expect
        self.configured();c=self.m.b.configuration();c['monitor']['interval']=40;self.m.b.cli.save(self.m.config,c);self.advanced()
        field=self.page.locator('#monitor-interval');expect(field).to_have_value('40')
        group=field.locator('xpath=../..');group.get_by_role('button',name='+',exact=True).click();expect(field).to_have_value('45')
        group.get_by_role('button',name='Reset Check the drive every (seconds) to default',exact=True).click();expect(field).to_have_value('15')
        self.page.locator('#monitor-boot_grace').fill('180')
        self.page.get_by_role('button',name='Reset all drive monitoring to defaults',exact=True).click()
        expect(self.page.locator('#monitor-boot_grace')).to_have_value('90')
        self.assertEqual(self.m.b.configuration()['monitor']['interval'],40,'Reset changes draft only until saved')
        self.page.get_by_role('button',name='Save advanced timing',exact=True).click()
        expect(self.page.locator('#notice')).to_have_text('Timing settings saved.')
        self.assertEqual(self.m.b.configuration()['monitor']['interval'],15)

    def test_previous_manual_action_is_timestamped_and_separate_from_live_state(self):
        from playwright.sync_api import expect
        import json
        self.configured()
        self.m.b.w.atomic_write(self.m.state/'manual-operation.json',json.dumps(dict(uuid=UUID,time='2026-01-01T12:00:00+00:00',ok=True,message='Old operation: monitoring stopped.')))
        self.m.active=True
        self.nav('Overview');self.page.get_by_role('button',name='Manage drive',exact=True).click()
        expect(self.page.locator('#connection')).to_contain_text('Monitoring on')
        expect(self.page.locator('#operation-result')).to_contain_text('Previous manual action')
        expect(self.page.locator('#operation-result')).to_contain_text('2026')
        expect(self.page.get_by_role('button',name='Stop monitoring',exact=True)).to_have_class('pause')
        expect(self.page.locator('#drive-panel')).to_contain_text('Test manufacturer')

    def test_formatting_stages_lock_navigation_and_never_offer_monitoring(self):
        from playwright.sync_api import expect
        stage={'operation':'synthetic-prepare','phase':'formatting','message':'Creating ext4 on the selected disposable disk'}
        self.m.patch(self.m.broker,'prepare_progress',lambda:dict(stage))
        self.page.get_by_role('button',name='Prepare drive',exact=True).click()
        self.page.get_by_role('heading',name='FORMATTING IN PROGRESS — DO NOT DISCONNECT THE DRIVE!',exact=True).wait_for()
        expect(self.page.get_by_role('button',name='Overview',exact=True)).to_be_disabled()
        expect(self.page.get_by_role('button',name='Erase and prepare for Linux',exact=True)).to_be_disabled()
        stage.update(phase='mounting',message='Mounting selected filesystem')
        expect(self.page.locator('#prepare-result .stage')).to_have_text('Mounting')
        stage.update(phase='verifying',message='Verifying correct UUID and read/write state')
        expect(self.page.locator('#prepare-result .stage')).to_have_text('Verifying')
        stage.update(phase='ready',message='Verified filesystem mounted',name='Test drive',mountpoint=STABLE)
        self.page.get_by_role('heading',name='Drive ready',exact=True).wait_for()
        expect(self.page.get_by_role('button',name='Overview',exact=True)).to_be_enabled()
        for name in ('Enable automatic recovery','Start monitoring','Back to overview'):
            self.assertEqual(self.page.get_by_role('button',name=name,exact=True).count(),0)
        self.assertFalse(self.m.active)

    def test_permission_correction_is_explicit_and_shows_exact_folder(self):
        from unittest.mock import Mock
        from playwright.sync_api import expect
        self.configured()
        item=dict(name='Imported backup',uuid=UUID,image=DESKTOP+'/existing.img',mountpoint=DESKTOP+'/backup',enabled=True,mounted=True,accessible=False,access_message='Needs folder access',fstab_options='loop')
        self.m.patch(self.m.b.images,'entries',lambda _:[item])
        self.m.patch(self.m.b.images,'permission_plan',lambda *args:dict(token='permission-consent',path=item['mountpoint'],targets=[dict(path=item['mountpoint'],rights='rwx')]))
        apply=self.m.patch(self.m.b.images,'permission_apply',Mock(return_value=dict(message='Access verified')))
        self.advanced();self.page.get_by_role('button',name='Change permissions / Fix folder access',exact=True).click()
        expect(self.page.get_by_role('heading',name='Change permissions / Fix folder access',exact=True)).to_be_visible();apply.assert_not_called()
        self.page.get_by_role('button',name='Review folder access',exact=True).click()
        self.page.get_by_role('button',name='Confirm folder access correction',exact=True).click()
        expect(self.page.locator('#notice')).to_have_text('Access verified')
        self.assertEqual(apply.call_args.args[2],dict(token='permission-consent',confirm=True))

    def test_management_token_rotation_signs_out_current_session(self):
        from playwright.sync_api import expect
        self.configured();self.nav('Advanced')
        self.page.get_by_role('button',name='Replace management token',exact=True).click()
        expect(self.page.locator('#created-token')).to_have_value(__import__('re').compile(r'usw7_.+'))
        token=self.page.locator('#created-token').input_value()
        self.assertNotIn(token,self.m.config.with_name('management-token.json').read_text())
        expect(self.page.locator('#management-token')).to_be_visible()
        expect(self.page.locator('#login-password')).not_to_be_visible()
        self.page.locator('#token-login-form').get_by_role('button',name='Connect',exact=True).click()
        self.page.get_by_role('button',name='Overview',exact=True).wait_for()
        self.assertNotIn(token,self.page.locator('#page').inner_text())
        expect(self.page.locator('#created-token')).to_have_value('')

    def test_one_lan_switch_warning_inline_apply_disable_and_failure(self):
        from playwright.sync_api import expect
        import json
        self.configured();b=self.m.b;state={'enabled':False,'fail':False};calls=[]
        def info():return dict(addresses=[dict(address='10.0.0.2',interface='test0')],certificate='',available=state['enabled'],scheme='http',url='http://10.0.0.2:8765' if state['enabled'] else None,message='LAN active' if state['enabled'] else 'LAN disabled')
        def apply(data):
            calls.append(data)
            if state['fail']:raise ValueError('LAN could not start; previous configuration restored.')
            if data['enabled']:assert data['acknowledge_http'] is True
            state['enabled']=data['enabled'];self.m.network.write_text(json.dumps(dict(b.common.DEFAULT,lan=state['enabled'],scheme='http',address='10.0.0.2',hostname='10.0.0.2')))
            return dict(pending=True,operation='inline-test',url='http://10.0.0.2:8765')
        self.m.patch(b,'lan_info',info);self.m.patch(b,'lan_auto',apply)
        self.m.patch(b,'lan_status',lambda:dict(operation='inline-test',phase='complete',message='LAN setting verified'))
        self.nav('Advanced');switch=self.page.get_by_role('switch',name='Allow access from my local network')
        switch.check();expect(self.page.get_by_role('dialog')).to_contain_text('WARNING — UNENCRYPTED CONNECTION')
        self.page.get_by_role('dialog').get_by_role('button',name='Cancel',exact=True).click();expect(switch).not_to_be_checked();self.assertFalse(calls)
        switch.check();self.page.get_by_role('button',name='I understand — enable LAN HTTP',exact=True).click()
        expect(self.page.get_by_role('button',name='Copy LAN URL',exact=True)).to_be_visible();expect(switch).to_be_enabled()
        switch.uncheck();expect(switch).to_be_enabled();expect(self.page.locator('#lan-live-status')).to_contain_text('LAN disabled')
        state['fail']=True;switch.check();self.page.get_by_role('button',name='I understand — enable LAN HTTP',exact=True).click()
        expect(self.page.locator('#lan-live-status')).to_contain_text('previous configuration restored');expect(switch).not_to_be_checked()
        self.assertEqual(self.page.get_by_role('button',name='Save LAN settings',exact=True).count(),0)
        self.assertEqual(self.page.get_by_role('button',name='Disable LAN access',exact=True).count(),0)
        expect(self.page.get_by_role('heading',name='Local network access',exact=True)).to_be_visible()

    def test_numeric_touch_geometry_dark_contrast_and_no_spinners_at_four_widths(self):
        self.configured();self.advanced()
        for width in (320,390,768,1280):
            self.page.set_viewport_size(dict(width=width,height=900))
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width)
            errors=self.page.locator('.stepper').evaluate_all("""nodes=>nodes.flatMap(n=>{
              const items=[...n.children],errors=[],rects=items.map(x=>x.getBoundingClientRect());
              for(let i=0;i<items.length;i++){
                if(rects[i].width<44 || rects[i].height<44)errors.push('small touch target');
                if(items[i].tagName==='INPUT' && (rects[i].width>100 || getComputedStyle(items[i]).appearance!=='textfield'))errors.push('input is not compact');
                for(let j=i+1;j<items.length;j++)if(Math.min(rects[i].right,rects[j].right)>Math.max(rects[i].left,rects[j].left)+1 && Math.min(rects[i].bottom,rects[j].bottom)>Math.max(rects[i].top,rects[j].top)+1)errors.push('overlap');
              }return errors;
            })""")
            self.assertEqual(errors,[],str(width))
        contrast=self.page.evaluate("""()=>{
          const light=c=>{let a=c.match(/[0-9.]+/g).slice(0,3).map(Number).map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4;});return .2126*a[0]+.7152*a[1]+.0722*a[2];};
          return ['.card','input','.fine','button.primary'].map(sel=>{const e=document.querySelector(sel),s=getComputedStyle(e);let bg=s.backgroundColor,p=e;
            while(bg==='rgba(0, 0, 0, 0)' && p.parentElement){p=p.parentElement;bg=getComputedStyle(p).backgroundColor;}
            let a=light(s.color),b=light(bg);return [sel,(Math.max(a,b)+.05)/(Math.min(a,b)+.05)];});
        }""")
        for selector,ratio in contrast:self.assertGreaterEqual(ratio,4.5,selector)

    def test_virtual_image_explanation_and_four_permission_choices(self):
        from playwright.sync_api import expect
        self.configured();self.advanced()
        expect(self.page.get_by_role('heading',name='Virtual Disk Images (.img)',exact=True)).to_be_visible()
        self.page.get_by_text('Why was this feature created?',exact=True).click()
        expect(self.page.locator('#page')).to_contain_text('30 GB virtual disk image')
        self.page.get_by_role('tab',name='Create new',exact=True).click()
        expect(self.page.locator('#image-access')).to_have_value('user')
        self.assertEqual(self.page.locator('#image-access option').count(),4)
        self.assertFalse(self.page.locator('#image-path').is_visible())
        self.page.locator('#image-access').select_option('applications')
        expect(self.page.locator('#image-group')).to_be_visible()
        self.page.locator('#image-access').select_option('custom')
        expect(self.page.locator('#image-uid')).not_to_be_visible()
        self.page.get_by_text('Technical permission details',exact=True).click()
        expect(self.page.locator('#image-uid')).to_be_visible()

    def test_technical_details_remain_same_open_dom_and_selection_over_two_polls(self):
        from playwright.sync_api import expect
        self.configured();self.nav('Overview');self.page.get_by_role('button',name='Manage drive',exact=True).click()
        detail=self.page.locator('#technical-drive-details');detail.locator('summary').click()
        self.page.evaluate("""() => {window.keptDetails=document.querySelector('#technical-drive-details');const target=[...keptDetails.querySelectorAll('dd')].find(e=>e.textContent.includes('11111111')) || keptDetails.querySelector('dd'); const range=document.createRange();range.selectNodeContents(target);getSelection().removeAllRanges();getSelection().addRange(range);window.keptText=getSelection().toString();}""")
        self.page.wait_for_timeout(11200)
        self.assertTrue(self.page.evaluate("window.keptDetails===document.querySelector('#technical-drive-details') && keptDetails.open"))
        self.assertTrue(self.page.evaluate('getSelection().toString()===window.keptText && window.keptText.length>0'))
        self.m.present=False
        self.page.wait_for_timeout(5300)
        expect(self.page.locator('#drive-panel')).to_contain_text('Disconnected')
        self.assertTrue(self.page.evaluate('keptDetails.isConnected && keptDetails.open'))
        detail.locator('summary').click();self.page.wait_for_timeout(5200)
        self.assertFalse(detail.evaluate('(e)=>e.open'))

    def test_image_create_import_tabs_replace_form_in_place_preserve_list(self):
        from playwright.sync_api import expect
        self.configured();self.advanced()
        create=self.page.get_by_role('tab',name='Create new',exact=True);existing=self.page.get_by_role('tab',name='Add existing',exact=True)
        expect(create).to_have_attribute('aria-selected','true')
        expect(self.page.locator('#image-size')).to_be_visible()
        self.page.evaluate("window.imageSlot=document.querySelector('#image-form-slot')")
        existing.click();expect(existing).to_have_attribute('aria-selected','true')
        self.assertEqual(self.page.locator('#image-size').count(),0)
        self.assertTrue(self.page.evaluate("window.imageSlot===document.querySelector('#image-form-slot')"))
        self.assertEqual(self.page.locator('#image-editor').count(),1)
        expect(self.page.get_by_role('heading',name='Configured virtual disk images',exact=True)).to_be_visible()
        create.click();expect(self.page.locator('#image-size')).to_be_visible()

    def test_local_bootstrap_creates_one_time_token_and_normal_login_is_token_only(self):
        from playwright.sync_api import expect
        self.page.get_by_role('button',name='Sign out',exact=True).click()
        self.m.config.with_name('management-token.json').unlink()
        self.page.reload()
        expect(self.page.get_by_role('heading',name='Connect to USB Storage Watch')).to_be_visible()
        expect(self.page.locator('#login-password')).not_to_be_visible()
        self.page.get_by_text('Additional setup and token recovery',exact=True).click()
        self.page.locator('#open-bootstrap').click()
        self.page.locator('#username').fill('admin');self.page.locator('#login-password').fill('synthetic')
        self.page.locator('#login-form button').click()
        expect(self.page.locator('#created-token')).to_have_value(__import__('re').compile(r'usw7_.+'))
        self.page.get_by_role('button',name='Connect',exact=True).click()
        self.page.get_by_role('button',name='Overview',exact=True).wait_for()
        expect(self.page.locator('#created-token')).to_have_value('')

    def test_action_palette_has_distinct_roles_and_accessible_contrast(self):
        self.configured();self.advanced()
        colors=self.page.evaluate("""() => ['#monitor-interval','.number-adjust','.number-reset','button.primary','#drive-panel button'].map(s=>{const e=document.querySelector(s),c=getComputedStyle(e);return {bg:c.backgroundColor,fg:c.color}})""")
        self.assertEqual(len({v['bg'] for v in colors[:4]}),4)
        def luminance(rgb):
            values=[int(v)/255 for v in __import__('re').findall(r'\d+',rgb)[:3]]
            return sum(a*(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4) for a,v in zip([.2126,.7152,.0722],values))
        for value in colors:
            a,b=sorted([luminance(value['bg']),luminance(value['fg'])]);self.assertGreaterEqual((b+.05)/(a+.05),4.5,value)

if __name__=='__main__':unittest.main()
