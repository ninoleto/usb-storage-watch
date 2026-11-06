# SPDX-License-Identifier: MIT
"""End-to-end authorization boundary regression for virtual-image discovery.

Uses isolated broker sessions and synthetic disks; never touches the host's devices.
"""
import unittest
from unittest.mock import Mock
from multidrive_fixture import FleetMachine


class ImageRouteTests(unittest.TestCase):
    def setUp(self):
        self.f = FleetMachine()
        self.addCleanup(self.f.close)

    def test_discovery_is_authorized_and_read_only_for_every_drive(self):
        second = self.f.add()
        for profile, machine in (('legacy', self.f.main), (second, self.f.second)):
            payload = {'images': [{'name': 'available', 'path': '/synthetic/available.img', 'size': 1024}], 'truncated': False}
            image_scan = Mock(return_value=payload)
            machine.patch(machine.b.images, 'discover', image_scan)
            request = dict(action='image-discover', data={}, write=False, drive=profile)
            self.assertEqual(self.f.main.broker.handle(request)['status'], 401, 'unauthorized image scan must be refused')
            result = self.f.request('image-discover', profile=profile)
            self.assertEqual(result['status'], 200, result)
            self.assertEqual(result['data'], payload)
            image_scan.assert_called_once()
            denied = self.f.request('image-discover', {}, profile=profile)
            self.assertEqual(denied['status'], 400, denied)
            image_scan.assert_called_once()

    def test_image_listing_and_management_routes_remain_drive_scoped(self):
        second = self.f.add()
        for profile, machine in (('legacy', self.f.main), (second, self.f.second)):
            name='image-'+profile
            listing=Mock(return_value=[{'name':name,'uuid':'fixture-image'}])
            manage=Mock(return_value={'message':'Simulated image action accepted.'})
            machine.patch(machine.b.images,'entries',listing)
            machine.patch(machine.b.images,'manage',manage)
            result=self.f.request('application-images',profile=profile)
            self.assertEqual(result['status'],200,result)
            self.assertEqual(result['data']['images'][0]['name'],name)
            listing.assert_called_once()
            result=self.f.request('image-action',{'action':'mount','uuid':'fixture-image'},profile=profile)
            self.assertEqual(result['status'],200,result)
            manage.assert_called_once()

    def test_frontend_action_contract_has_no_unregistered_broker_operations(self):
        import re
        from pathlib import Path
        from gui_fixture import load
        w=load('web');b=self.f.main.b;f=load('web_drives')
        js=Path(__file__).resolve().parents[1]/'src/usb_storage_watch/web_static/app.js'
        names=set(re.findall(r"apiRequest\(\s*['\"`]([^'\"`?]+)",js.read_text()))
        for name in names:
            with self.subTest(action=name):
                self.assertTrue(name=='login' or name in w.READS|w.WRITES, f'Frontend does not allow {name}')
                self.assertTrue(name=='login' or name in f.GLOBAL|f.FLEET|b.READS|b.WRITES,
                                f'Broker does not allow frontend operation: {name}')

    def test_browser_and_broker_whitelists_agree(self):
        from gui_fixture import load
        web = load('web')
        broker = self.f.main.b
        self.assertIn('image-discover', web.READS)
        self.assertIn('image-discover', broker.READS)
        self.assertNotIn('image-discover', web.WRITES)
        self.assertNotIn('image-discover', broker.WRITES)


if __name__ == '__main__':
    unittest.main()
