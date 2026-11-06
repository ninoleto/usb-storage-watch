"""UI5 — pure isolated recovery preference and network-switch tests."""
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
from test_ui4_regressions import ImageIntentTests,images,broker

class ImagePreference(ImageIntentTests):
    def test_disable_recovery_without_unmounting_or_touching_others(self):
        before=list(self.rows)
        result=images.manage(self.b,{'uuid':self.image['uuid'],'action':'set-recovery','enabled':False})
        self.assertFalse(result['enabled']);self.assertFalse(self.c['images'][0]['enabled'])
        self.assertIn('noauto',self.c['images'][0]['fstab_options'].split(','))
        self.assertEqual(before,self.rows);self.assertFalse(self.commands);self.assertFalse(self.recoveries)
    def test_enable_recovery_does_not_mount_an_unmounted_image(self):
        self.c['images'][0]['enabled']=False;self.c['images'][0]['fstab_options']+=',noauto';self.rows=self.rows[:1]
        result=images.manage(self.b,{'uuid':self.image['uuid'],'action':'set-recovery','enabled':True})
        self.assertTrue(result['enabled']);self.assertTrue(self.c['images'][0]['enabled'])
        self.assertNotIn('noauto',self.c['images'][0]['fstab_options']);self.assertFalse(self.recoveries)
    def test_invalid_pref_or_unexpected_keys_refused(self):
        for val in (None,1,'true',{},[]):
            with self.assertRaisesRegex(ValueError,'Choose Mount on recovery'):
                images.manage(self.b,{'uuid':self.image['uuid'],'action':'set-recovery','enabled':val})
        with self.assertRaisesRegex(ValueError,'Choose Mount on recovery'):
            images.manage(self.b,{'uuid':self.image['uuid'],'action':'set-recovery','enabled':False,'unsafe':True})
        self.assertFalse(self.saves)
    def test_disable_recovery_is_independent_of_detected_docker_storage(self):
        self.c['docker']['enabled']=True
        self.c['docker']['containers']=[dict(name='test',source=self.image['mountpoint']+'/data',
            destination='/data',grace=30,container_id='a'*64,images=[self.image['uuid']])]
        result=images.manage(self.b,{'uuid':self.image['uuid'],'action':'set-recovery','enabled':False})
        self.assertFalse(result['enabled']);self.assertFalse(self.c['images'][0]['enabled'])
        self.assertEqual(self.c['docker']['containers'][0]['images'],[self.image['uuid']])
        self.assertEqual(len(self.saves),1);self.assertFalse(self.commands)

    def test_remove_image_clears_only_its_explicit_restart_image_choices(self):
        self.rows=self.rows[:1]
        self.c['docker']['enabled']=True
        self.c['docker']['containers']=[dict(name='test',source=self.image['mountpoint']+'/data',
            destination='/data',grace=30,container_id='a'*64,images=[self.image['uuid']])]
        before=dict(self.c['docker']['containers'][0])
        result=images.manage(self.b,{'uuid':self.image['uuid'],'action':'remove','confirm':True})
        self.assertIn('kept',result['message'])
        self.assertEqual(self.c['images'],[]);self.assertTrue(self.c['docker']['enabled'])
        self.assertEqual(self.c['docker']['containers'],[dict(before,images=[])])
        self.assertEqual(len(self.saves),1);self.assertFalse(self.commands)

class NetworkSwitch(unittest.TestCase):
    def test_reuse_matching_certificate_and_address_without_rotation(self):
        with TemporaryDirectory() as root:
            path=Path(root)
            (path/'certificate.pem').write_text('SYNTHETIC-CERT')
            (path/'key.pem').write_text('SYNTHETIC-KEY')
            (path/'local-network-ca.pem').write_text('SYNTHETIC-CA')
            calls=[]
            with patch.object(broker.common,'WEB_DIR',path),patch.object(broker,'lan_info',return_value={'addresses':[{'address':'192.168.50.24'}]}),patch.object(broker,'network_configuration',return_value={'lan':True,'address':'192.168.50.24','hostname':'192.168.50.24','port':8765,'scheme':'http'}),patch.object(broker,'network',side_effect=lambda d:calls.append(d) or dict(operation='synthetic',pending=True)):
                result=broker.lan_auto(dict(enabled=True,confirm=True,address='192.168.50.24',scheme='https'))
            self.assertTrue(result['pending']);self.assertEqual(calls[0]['certificate'],'SYNTHETIC-CERT')
            self.assertEqual(calls[0]['local_ca'],'SYNTHETIC-CA')
    def test_only_assigned_private_host_addresses_allowed(self):
        calls=[]
        with patch.object(broker,'lan_info',return_value={'addresses':[{'address':'192.168.50.24'}]}),patch.object(broker,'network',side_effect=lambda d:calls.append(d) or dict(pending=True)):
            broker.lan_auto(dict(enabled=True,confirm=True,address='192.168.50.24',scheme='http',acknowledge_http=True))
            with self.assertRaisesRegex(ValueError,'current local network'):
                broker.lan_auto(dict(enabled=True,confirm=True,address='8.8.8.8',scheme='http',acknowledge_http=True))
        self.assertEqual(len(calls),1);self.assertTrue(calls[0]['acknowledge_http'])

if __name__=='__main__':unittest.main()
