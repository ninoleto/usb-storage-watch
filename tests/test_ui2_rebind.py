# SPDX-License-Identifier: MIT
"""No hardware touched: simulated UUID replacement, refusal, preview and rollback."""
import json
import unittest
from unittest.mock import Mock, patch
from multidrive_fixture import FleetMachine
from gui_fixture import load, UUID

NEW='33333333-3333-4333-8333-333333333333'
PIN={'uuid':UUID,'serial':'ADATA test serial 100','wwn':'','vendor':'125f','product':'312b','size':31675383808}


class RebindTests(unittest.TestCase):
    def setUp(self):
        self.f=FleetMachine();self.addCleanup(self.f.close)
        self.b=self.f.main.b
        self.rb=load('web_rebind')
        self.f.main.active=False
        self.b.fstab=self.f.main.fstab
        self.f.main.fstab.write_text(self.f.main.original+
                                    f'UUID={UUID} /mnt/drive-a ext4 defaults,nofail,nodev,nosuid,x-systemd.device-timeout=10s 0 0\n'+
                                    f'UUID={NEW} /mnt/usb-storage-watch-{NEW} ext4 defaults,nofail,nodev,nosuid,x-systemd.device-timeout=10s 0 0\n'+
                                    f'UUID=22222222-2222-4222-8222-222222222222 /mnt/drive-b ext4 defaults,nofail,nodev,nosuid 0 0\n')
        self.newrow=dict(uuid=NEW,mountpoint='',eligible=True,device='/dev/synthetic1',model='ADATA USB Flash Drive',
                         size=31675383808,filesystem='ext4',transport='usb',reason='')
        self.f.main.patch(self.b,'disks',lambda:[self.newrow])
        self.f.main.patch(self.b.w.drives,'hardware',lambda *args:dict(PIN,uuid=NEW))
        self.f.main.patch(self.b.migration,'pending',lambda _:None)
        (self.f.main.state/'drive-identity.json').write_text(json.dumps(PIN))
        self.b.FSTAB=self.f.main.fstab
        # ADATA was reformatted, so its old mount has disappeared.
        self.f.main.patch(self.b.w,'read_rows',lambda:[])

    def review(self):
        return self.f.main.broker.handle(dict(action='drive-rebind-plan',write=False,data={'uuid':NEW},drive='legacy',token=self.f.session['token'],csrf=self.f.session['csrf']))

    def test_both_hardware_identity_and_new_filesystem_required(self):
        review=self.rb.inspect(self.f.main.broker.fleet,'legacy',NEW)
        self.assertEqual(review['old_uuid'],UUID)
        self.assertEqual(review['new_uuid'],NEW)
        self.assertEqual(review['mountpoint'],'/mnt/usb-storage-watch-'+NEW)
        self.assertTrue(self.rb.hardware_match(PIN,dict(PIN,uuid=NEW)))
        self.assertFalse(self.rb.hardware_match(PIN,dict(PIN,serial='unexpected',uuid=NEW)))
        self.assertFalse(self.rb.hardware_match({'uuid':UUID,'serial':''},dict(PIN,uuid=NEW)))
        self.assertIn('UUID='+NEW,review['fstab']['after'])
        self.assertNotIn('UUID='+UUID,review['fstab']['after'])

    def test_in_app_plan_and_review_requires_explicit_consent(self):
        result=self.review()
        self.assertEqual(result['status'],200,result)
        plan=result['data']
        self.assertEqual(plan['new_uuid'],NEW)
        wrong=self.f.request('drive-rebind-apply',dict(uuid=NEW,revision='wrong',confirm=True))
        self.assertEqual(wrong['status'],400)
        self.assertIn('UUID='+UUID,self.f.main.fstab.read_text())

    def test_actual_rebind_updates_only_adata_and_archives_state(self):
        self.f.main.state.joinpath('state.json').write_text(json.dumps({
            'version':2,'target':[UUID,'/mnt/drive-a'],'status':'down','pending':[],
            'incident':{'phase':'wait1'},'count':1}))
        plan=self.review()
        self.assertEqual(plan['status'],200,plan)
        with patch.object(self.rb.subprocess,'run',return_value=Mock(returncode=3)):
            # Fleet loads its own instance of the rebind module; patch that subprocess globally.
            import subprocess
            with patch.object(subprocess,'run',return_value=Mock(returncode=3)):
                applied=self.f.request('drive-rebind-apply',dict(uuid=NEW,revision=plan['data']['revision'],confirm=True))
        self.assertEqual(applied['status'],200,applied)
        config=json.loads(self.f.main.config.read_text())
        self.assertEqual(config['disk']['uuid'],NEW)
        self.assertTrue(config['recovery']['mount'])
        self.assertFalse(config['usb']['enabled'])
        self.assertIn('UUID='+NEW,self.f.main.fstab.read_text())
        self.assertNotIn('UUID='+UUID,self.f.main.fstab.read_text())
        self.assertEqual(json.loads((self.f.main.state/'drive-identity.json').read_text())['uuid'],NEW)
        self.assertIsNone(json.loads((self.f.main.state/'state.json').read_text())['incident'])
        backups=list((self.f.main.state/'rebind-backups').glob('*/backup.json'))
        self.assertEqual(len(backups),1)
        old=json.loads(backups[0].read_text())
        self.assertEqual(json.loads(old['files']['state'])['incident']['phase'],'wait1')
        self.assertEqual(json.loads(old['files']['config'])['disk']['uuid'],UUID)

    def test_new_filesystem_can_be_mounted_with_old_pin_still_saved(self):
        # A drive freshly formatted by the app is commonly already mounted.
        # The old hardware pin is valid for recognition, not for new UUID
        # block_checks. The new visible mount still needs kernel identity checks.
        newpath='/mnt/usb-storage-watch-'+NEW
        self.newrow['mountpoint']=newpath
        rows=self.b.w.parse_mounts('1 0 240:0 / / rw - ext4 /dev/system rw\n'
                                  f'2 1 {self.f.main.dev} / {newpath} rw - ext4 /dev/synthetic1 rw\n')
        self.b.w.read_rows=lambda:rows
        self.b.w.visible_mount=lambda entries,target:next((r for r in entries if r['target']==target),None)
        self.b.w.mounted_checks=lambda *args: self.fail('Incorrectly used old UUID hardware pin')
        self.assertEqual(self.rb.inspect(self.f.main.broker.fleet,'legacy',NEW)['new_uuid'],NEW)

    def test_old_mount_still_active_is_refused(self):
        self.b.w.read_rows=lambda:[dict(target='/mnt/drive-a')]
        with self.assertRaisesRegex(ValueError,'previous mount location is still active'):
            self.rb.inspect(self.f.main.broker.fleet,'legacy',NEW)

    def test_rebind_rejects_mismatched_hardware_and_duplicate_candidates(self):
        original=self.f.main.fstab.read_text()
        self.b.w.drives.hardware=lambda *args: dict(PIN,uuid=NEW,serial='other hardware')
        with self.assertRaisesRegex(ValueError,'does not match'):
            self.rb.inspect(self.f.main.broker.fleet,'legacy',NEW)
        self.assertEqual(self.f.main.fstab.read_text(),original)

    def test_fstab_conflict_is_rejected_before_approval(self):
        original=self.f.main.fstab.read_text()
        self.f.main.fstab.write_text(original + 'UUID='+NEW+' /mnt/conflict ext4 defaults 0 0\n')
        with self.assertRaisesRegex(ValueError,'Conflicting persistent mount'):
            self.rb.inspect(self.f.main.broker.fleet,'legacy',NEW)

    def test_rebind_failure_rolls_back_all_critical_adata_files(self):
        old_fstab=self.f.main.fstab.read_text()
        old_config=self.f.main.config.read_text()
        old_pin=(self.f.main.state/'drive-identity.json').read_text()
        old_state='{"version":2,"target":["'+UUID+'","/mnt/drive-a"],"status":"down","pending":[],"incident":{"phase":"wait1"}}'
        (self.f.main.state/'state.json').write_text(old_state)
        plan=self.review()
        self.assertEqual(plan['status'],200)
        original=self.b.command
        calls=[0]
        def broken_reload(args,timeout=10):
            if args==['/usr/bin/systemctl','daemon-reload'] and calls[0]==0:
                calls[0]+=1
                raise OSError('synthetic first reload interruption')
            return original(args,timeout)
        from unittest.mock import patch
        with patch.object(self.rb.subprocess,'run',return_value=Mock(returncode=3)),patch.object(self.b,'command',side_effect=broken_reload):
            result=self.f.request('drive-rebind-apply',dict(uuid=NEW,revision=plan['data']['revision'],confirm=True))
        self.assertEqual(result['status'],400,result)
        self.assertEqual(self.f.main.fstab.read_text(),old_fstab)
        self.assertEqual(json.loads(self.f.main.config.read_text()),json.loads(old_config))
        self.assertEqual(json.loads((self.f.main.state/'drive-identity.json').read_text()),json.loads(old_pin))
        self.assertEqual(json.loads((self.f.main.state/'state.json').read_text()),json.loads(old_state))
        self.assertEqual(len(list((self.f.main.state/'rebind-backups').glob('*/backup.json'))),1)

    def test_dependent_images_prevent_loss_of_paths(self):
        c=self.b.configuration();c['dependent'].update(enabled=True,uuid='33333333-3333-4333-8333-333333333333',mountpoint='/mnt/drive-a/img',image='/mnt/drive-a/image.img',fstab_options='loop,nofail,nodev')
        self.b.cli.save(self.f.main.config,c)
        with self.assertRaisesRegex(ValueError,'dependent'):
            self.rb.inspect(self.f.main.broker.fleet,'legacy',NEW)


if __name__=='__main__':unittest.main()
