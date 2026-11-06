# SPDX-License-Identifier: MIT
"""UI4 targeted tests: no physical devices, mounts, network or systemd changes."""
from contextlib import nullcontext
from pathlib import Path
import copy
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui_fixture import load

images = load('web_images')
settings = load('settings')
broker = load('web_broker')

class ImageIntentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        mount = '/mnt/usb-storage-test'
        image = {
            'name':'Backups','enabled':True,
            'uuid':'22222222-2222-4222-8222-222222222222',
            'image':mount+'/usb-storage-watch-volumes/.images/Backups.img',
            'mountpoint':mount+'/usb-storage-watch-volumes/Backups',
            'fstab_options':'loop,nofail,nodev,nosuid,noexec,x-systemd.requires-mounts-for='+mount,
        }
        self.c=settings.default()
        self.c['disk'].update(uuid='11111111-1111-4111-8111-111111111111',mountpoint=mount,fstab_options='defaults')
        self.c['images']=[image]
        settings.validate(self.c)
        self.mount = mount
        self.image = image
        self.rows=[{'target':mount,'dev':'240:1','id':'1'},{'target':image['mountpoint'],'dev':'240:2','id':'2'}]
        self.commands=[]
        self.recoveries=[]
        self.saves=[]
        def write_config(_b, config, old=None, item=None):
            self.saves.append((copy.deepcopy(config),copy.deepcopy(old),copy.deepcopy(item)))
            self.c=copy.deepcopy(config)
        self.b=SimpleNamespace(
            configuration=lambda:copy.deepcopy(self.c),
            s=settings,
            w=SimpleNamespace(configure=Mock(), read_rows=lambda:self.rows,
                covers=lambda parent, child:child==parent or child.startswith(parent.rstrip('/')+'/'),
                verify_dependent=Mock(), verify_main=Mock(),
                visible_mount=lambda rows,target:next((r for r in rows if r['target']==target),None),
                standby=SimpleNamespace(users=Mock()), usb_context=Mock(),
                command=lambda argv, timeout=15: self.commands.append(argv),
                recover_image=lambda item,req,note:self.recoveries.append(copy.deepcopy(item))),
        )
        patcher1=patch.object(images,'_image_transaction',return_value=nullcontext())
        patcher2=patch.object(images,'save_configuration',side_effect=write_config)
        patcher1.start();patcher2.start();self.addCleanup(patcher1.stop);self.addCleanup(patcher2.stop)

    def test_manual_unmount_preserves_recovery_and_fstab(self):
        r=images.manage(self.b,{'uuid':self.image['uuid'],'action':'unmount'})
        self.assertIn('unmounted',r['message'])
        item=self.c['images'][0]
        self.assertTrue(item['enabled'])
        self.assertNotIn('noauto',item['fstab_options'].split(','))
        self.assertEqual([c[0:2] for c in self.commands[-2:]], [['/usr/bin/sync','-f'],['/usr/bin/umount','--']])
        self.assertEqual(len(self.saves),0)
        settings.validate(self.c)

    def test_manual_mount_preserves_disabled_recovery_without_formatting(self):
        self.c['images'][0]['enabled']=False
        self.c['images'][0]['fstab_options']+=',noauto'
        self.rows=self.rows[:1]
        r=images.manage(self.b,{'uuid':self.image['uuid'],'action':'mount'})
        self.assertIn('mounted',r['message'])
        self.assertFalse(self.c['images'][0]['enabled'])
        self.assertIn('noauto',self.c['images'][0]['fstab_options'])
        self.assertEqual(len(self.recoveries),1)
        self.assertEqual(len(self.saves),0)

    def test_busy_image_unmount_refused_before_any_changes(self):
        self.c['docker']['enabled']=True
        self.c['docker']['containers']=[{'name':'test','source':self.image['mountpoint']+'/data'}]
        self.b.w.standby.users.side_effect=ValueError('A running Docker container has access to this disk.')
        with self.assertRaisesRegex(ValueError,'Docker'):
            images.manage(self.b,{'uuid':self.image['uuid'],'action':'unmount'})
        self.assertFalse(self.commands)
        self.assertFalse(self.saves)

    def test_reject_unknown_operation_before_disk_changes(self):
        with self.assertRaisesRegex(ValueError,'Explicitly confirm'):
            images.manage(self.b,{'uuid':self.image['uuid'],'action':'invalid'})
        self.assertFalse(self.commands)
        self.assertFalse(self.saves)

class ManualHistoryTests(unittest.TestCase):
    def test_audits_meaningful_manual_actions_not_polling(self):
        with tempfile.TemporaryDirectory() as root:
            hist=broker.History(Path(root)/'events.db')
            b=broker.Broker(hist)
            self.assertEqual(b.manual_action('USB port reconnect',lambda:{'message':'Port re-enabled and target verified'})['message'],'Port re-enabled and target verified')
            with self.assertRaisesRegex(ValueError,'busy'):
                b.manual_action('drive unmount',lambda: (_ for _ in ()).throw(ValueError('Disk busy')))
            with hist.connect() as conn:
                rows=list(conn.execute('SELECT title, detail FROM events ORDER BY rowid'))
            self.assertEqual(len(rows),2)
            self.assertIn('Successful',rows[0][0]);self.assertIn('Refused',rows[1][0])

if __name__=='__main__':unittest.main()
