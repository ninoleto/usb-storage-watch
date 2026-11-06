# SPDX-License-Identifier: MIT
"""Reviewed DEV9 user journeys in Chromium against the real broker with isolated OS boundaries."""
import json
import unittest
from unittest.mock import Mock
import test_gui_advanced as fixture
from gui_fixture import UUID, DESKTOP, STABLE


@unittest.skipUnless(fixture.AVAILABLE,'Development-only Playwright/Flask dependencies absent')
class SimpleGUIWorkflowTests(unittest.TestCase):
    setUpClass=classmethod(fixture.AdvancedGUIWorkflowTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.AdvancedGUIWorkflowTests.tearDownClass.__func__)
    setUp=fixture.AdvancedGUIWorkflowTests.setUp
    tearDown=fixture.AdvancedGUIWorkflowTests.tearDown
    configured=fixture.AdvancedGUIWorkflowTests.configured
    advanced=fixture.AdvancedGUIWorkflowTests.advanced
    nav=fixture.AdvancedGUIWorkflowTests.nav

    def test_genuine_add_selection_review_then_independent_monitoring(self):
        from playwright.sync_api import expect
        self.configured()
        self.assertFalse(self.m.active);self.assertTrue(self.m.b.configuration()['recovery']['mount'])
        expect(self.page.locator('#drive-panel')).to_contain_text('Automatic recovery enabled')
        self.page.get_by_role('button',name='Start monitoring',exact=True).click()
        expect(self.page.locator('#drive-panel')).to_contain_text('Monitoring on');self.assertTrue(self.m.active)
        self.page.get_by_role('button',name='Disable automatic recovery',exact=True).click()
        self.page.get_by_role('button',name='Confirm recovery setting',exact=True).click()
        expect(self.page.locator('#drive-panel')).to_contain_text('Automatic recovery disabled')
        self.assertTrue(self.m.active);self.assertFalse(self.m.b.configuration()['recovery']['mount'])

    def test_overview_always_all_drives_and_refresh_reports_completion(self):
        from playwright.sync_api import expect
        self.configured();self.nav('Overview')
        expect(self.page.locator('.fleet-drive')).to_have_count(1)
        self.page.get_by_role('button',name='Refresh drives',exact=True).click()
        expect(self.page.locator('#notice')).to_contain_text('Drive list refreshed at')
        expect(self.page.get_by_text('Last refreshed:',exact=False)).to_be_visible()
        self.assertEqual(self.page.locator('#drive-panel').count(),0)
        self.assertEqual(self.page.locator('nav').get_by_role('button',name='Setup',exact=True).count(),0)

    def test_manage_contains_only_target_controls_and_one_back(self):
        self.configured()
        for name in ('Add USB drive','Refresh drives','All USB drives'):
            self.assertEqual(self.page.get_by_role('button',name=name,exact=True).count(),0)
        self.assertEqual(self.page.get_by_role('button',name='Back to Overview',exact=True).count(),1)
        self.assertIn('/#drive/legacy',self.page.url)
        self.page.reload();self.page.locator('#drive-panel').wait_for()
        self.assertIn(DESKTOP,self.page.locator('#drive-panel').inner_text())

    def test_existing_uuid_mount_settings_reused_and_files_preserved(self):
        original=self.m.original+f'UUID={UUID} {DESKTOP} ext4 defaults,nofail,nodev,nosuid,x-systemd.device-timeout=10s 0 0\n'
        self.m.fstab.write_text(original);self.configured()
        self.assertEqual(self.m.fstab.read_text(),original)
        self.assertEqual((self.m.disk_data/'sentinel').read_bytes(),b'Existing filesystem contents\x00preserve me')
        self.assertEqual(self.m.b.configuration()['disk']['mountpoint'],DESKTOP)

    def test_stale_recovery_confirmation_does_not_overwrite_settings(self):
        from playwright.sync_api import expect
        self.configured();self.page.get_by_role('button',name='Disable automatic recovery',exact=True).click()
        self.page.get_by_role('button',name='Confirm recovery setting',exact=True).wait_for()
        c=self.m.b.configuration();c['monitor']['interval']=25;self.m.b.cli.save(self.m.config,c)
        self.page.get_by_role('button',name='Confirm recovery setting',exact=True).click()
        expect(self.page.locator('#notice')).to_contain_text('settings changed')
        self.assertEqual(self.m.b.configuration(),c)

    def test_main_controls_send_selected_identity_and_report_results(self):
        from playwright.sync_api import expect
        self.configured()
        def operation(data):
            self.assertEqual(data['uuid'],UUID)
            self.m.current='' if data['action']=='unmount' else DESKTOP
            return dict(ok=True,message='Verified '+data['action'])
        self.m.patch(self.m.b,'disk_operation',operation)
        self.page.get_by_role('button',name='Unmount safely',exact=True).click()
        expect(self.page.locator('#operation-result')).to_contain_text('Verified unmount')
        self.page.get_by_role('button',name='Mount',exact=True).click()
        expect(self.page.locator('#operation-result')).to_contain_text('Verified mount')

    def test_failed_operation_clears_working(self):
        from playwright.sync_api import expect
        self.configured();self.m.patch(self.m.b,'disk_operation',Mock(side_effect=ValueError('Busy test filesystem')))
        self.page.get_by_role('button',name='Unmount safely',exact=True).click()
        expect(self.page.locator('#operation-result')).to_contain_text('Busy test filesystem')
        expect(self.page.get_by_role('button',name='Unmount safely',exact=True)).to_be_enabled()
        self.assertNotIn('Working…',self.page.locator('#page').inner_text())

    def test_email_account_and_notification_preferences_have_explicit_scope(self):
        from playwright.sync_api import expect
        self.configured();self.m.active=True;self.nav('Email & Notifications')
        for key,val in dict(host='smtp.example.test',username='sender',password='SYNTHETIC',sender='sender@example.test',recipient='recipient@example.test').items():self.page.locator('#smtp-'+key).fill(val)
        self.page.get_by_role('button',name='Save email settings',exact=True).click()
        expect(self.page.locator('#email-result')).to_contain_text('Email settings saved')
        self.assertTrue(self.m.active);self.assertFalse(self.m.b.configuration()['notifications']['enabled'])
        self.page.locator('#notifications-legacy').check();self.page.get_by_role('button',name='Save notification preference',exact=True).click()
        expect(self.page.locator('#email-notifications .callout')).to_have_text('Notifications enabled')
        self.assertTrue(self.m.active);self.assertTrue(self.m.b.configuration()['notifications']['enabled'])
        self.m.patch(self.m.b.n,'bounded_send',Mock(return_value=(True,'SMTP accepted the test message. Inbox delivery is not verified.')))
        self.page.get_by_role('button',name='Send test email',exact=True).click()
        expect(self.page.locator('#email-result')).to_contain_text('Inbox delivery is not verified')

    def test_prepare_confirmation_is_physical_and_one_refresh(self):
        from playwright.sync_api import expect
        p=self.m.b.preparation;disk=dict(device='/dev/disk/by-id/usb-Test_TEST0001',model='Disposable USB',serial='TEST0001',size=256*1024**2,reason='',layout=[])
        chosen=dict(disk=disk,token='test-consent',phrase='ERASE TEST0001',name='My Data',created=__import__('time').monotonic())
        progress={'phase':'idle'}
        self.m.patch(p,'inventory',lambda _:[disk]);self.m.patch(p,'plan',Mock(return_value=chosen))
        self.m.patch(self.m.broker.fleet,'preparation_target',lambda data:(self.m.b,self.m.broker))
        self.m.patch(self.m.broker,'prepare_progress',lambda:dict(progress))
        def start(plan,data):
            p.confirm(plan,data);progress.update(operation='test-job',phase='ready',uuid=UUID,name='My Data',mountpoint=STABLE,message='Verified filesystem and mount');return {'operation':'test-job'}
        self.m.patch(self.m.broker,'start_preparation',start)
        self.nav('Prepare drive');self.page.locator('input[name=prepare-drive-choice]').check()
        self.page.get_by_role('button',name='Erase and prepare for Linux',exact=True).click()
        erase=self.page.get_by_role('button',name='Permanently erase this drive',exact=True);expect(erase).to_be_disabled()
        self.page.locator('#prepare-erase').check();self.page.locator('#prepare-confirmation').fill(chosen['phrase']);erase.click()
        expect(self.page.get_by_role('heading',name='Drive ready',exact=True)).to_be_visible()
        self.assertEqual(self.page.get_by_role('button',name='Refresh drives',exact=True).count(),1)
        expect(self.page.get_by_role('button',name='Refresh drives',exact=True)).to_be_enabled()
        self.assertFalse(self.m.active)

    def test_preparation_start_refusal_unlocks_refresh_without_repeating_erasure(self):
        from playwright.sync_api import expect
        p=self.m.b.preparation;disk=dict(device='/dev/disk/by-id/usb-Test_TEST0001',model='Disposable USB',serial='TEST0001',size=256*1024**2,reason='',layout=[])
        chosen=dict(disk=disk,token='test-consent',phrase='ERASE TEST0001',name='Test',created=__import__('time').monotonic())
        self.m.patch(p,'inventory',lambda _:[disk]);self.m.patch(p,'plan',Mock(return_value=chosen))
        self.m.patch(self.m.broker.fleet,'preparation_target',lambda data:(self.m.b,self.m.broker))
        self.m.patch(self.m.broker,'prepare_progress',lambda:dict(phase='idle'))
        start=Mock(side_effect=ValueError('Selected disk became busy. Nothing was erased.'))
        self.m.patch(self.m.broker,'start_preparation',start)
        self.nav('Prepare drive');self.page.locator('input[name=prepare-drive-choice]').check()
        self.page.get_by_role('button',name='Erase and prepare for Linux',exact=True).click()
        self.page.locator('#prepare-erase').check();self.page.locator('#prepare-confirmation').fill(chosen['phrase'])
        self.page.get_by_role('button',name='Permanently erase this drive',exact=True).click()
        expect(self.page.locator('#prepare-result')).to_contain_text('Selected disk became busy')
        expect(self.page.get_by_role('button',name='Refresh drives',exact=True)).to_be_enabled()
        expect(self.page.locator('nav').get_by_role('button',name='Overview',exact=True)).to_be_enabled()
        start.assert_called_once()

    def test_single_drive_event_history_has_drive_attribution(self):
        from playwright.sync_api import expect
        self.configured();self.m.broker.history=self.m.b.History(self.m.state/'history.sqlite3')
        self.m.broker.history.record('test-event','2026-01-01T12:00:00Z','Recovery verified',['Synthetic event'])
        self.nav('Event history');expect(self.page.locator('#combined-history')).to_contain_text('External test disk · Recovery verified')
        self.page.locator('#history-filter').select_option('legacy');self.nav('Overview')
        self.page.get_by_role('button',name='Manage drive',exact=True).click();self.nav('Event history')
        expect(self.page.locator('#history-filter')).to_have_value('legacy')
