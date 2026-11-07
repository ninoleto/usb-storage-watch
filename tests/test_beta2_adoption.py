"""Reviewed image adoption: real ext4 file/probe, config writes and locks.

Mount/loop/udev observations and service commands are isolated fixtures. No loop
device is attached and no real filesystem, service, Docker or FTP is operated.
"""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from gui_fixture import Machine, UUID

IMAGE_UUID = '22222222-2222-4222-8222-222222222222'

class Adoption(unittest.TestCase):
    def setUp(self):
        self.m=Machine();self.addCleanup(self.m.close);self.b=self.m.b;self.w=self.b.w
        self.root=self.m.root;self.disk=self.m.disk_data;self.target=self.disk/'ftp'/'files'
        self.target.mkdir(parents=True);self.target.chmod(0o750)
        (self.target/'existing-file').write_bytes(b'Unchanged FTP fixture contents')
        self.file=self.disk/'backups.img'
        with self.file.open('wb') as f:f.truncate(32*1024**2)
        subprocess.run(['/usr/sbin/mkfs.ext4','-q','-F','-U',IMAGE_UUID,str(self.file)],
                       check=True,capture_output=True,timeout=15)
        st=self.file.stat();self.dev=f'{os.major(st.st_dev)}:{os.minor(st.st_dev)}'
        self.config=self.b.s.default();self.config['disk'].update(uuid=UUID,mountpoint=str(self.disk),fstab_options='defaults')
        self.b.cli.save(self.b.s.CONFIG,self.config);self.w.configure(self.config)
        self.options='loop,defaults,nofail,noatime,x-systemd.requires-mounts-for='+str(self.disk)
        self.entry=f'{self.file} {self.target} ext4 {self.options} 0 0\n'
        self.m.fstab.write_text(f'# Keep this exact existing mount table\nUUID={UUID} {self.disk} ext4 defaults 0 2\n'+self.entry)
        self.rows=self.w.parse_mounts(f'1 0 240:0 / / rw - ext4 /dev/system rw\n2 1 {self.dev} / {self.disk} rw - ext4 /dev/fixture rw\n3 2 7:77 / {self.target} rw - ext4 /dev/loop-fixture rw\n')
        self.loops=[dict(name='/dev/loop-fixture',**{'back-file':str(self.file),'back-ino':st.st_ino,'back-maj:min':self.dev},offset=0,sizelimit=0)]
        self.actual_uuid={self.dev:UUID,'7:77':IMAGE_UUID}
        for name,value in {'backing_file':str(self.file),'offset':'0','sizelimit':'0'}.items():
            p=self.root/'sys/dev/block/7:77/loop'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
        p=self.root/'sys/fs/ext4/fixture/errors_count';p.parent.mkdir(parents=True);p.write_text('0')
        p=self.root/'dev/disk/by-uuid'/UUID;p.parent.mkdir(parents=True);p.touch()
        self.m.patch(self.w,'Path',lambda p: self.root/str(p).lstrip('/') if str(p).startswith(('/sys/','/dev/disk/by-uuid')) else Path(p))
        self.m.patch(self.w,'read_rows',lambda:copy.deepcopy(self.rows))
        self.m.patch(self.w,'device_number',lambda p:'7:77' if str(p)=='/dev/loop-fixture' else self.dev)
        self.m.patch(self.w,'disk_proof',lambda p,u:SimpleNamespace(st_rdev=os.makedev(*map(int,self.dev.split(':')))))
        def block(dev,expected):
            if self.actual_uuid.get(dev)!=expected:raise self.w.Unsafe('Fixture filesystem UUID mismatch.')
            return 'fixture'
        self.m.patch(self.w,'block_checks',block)
        self.m.patch(self.w,'loop_inventory',lambda:copy.deepcopy(self.loops))
        safe=self.w.safe_path
        def safe_path(p,dev,*args,**kwargs):
            self.assertEqual(dev,os.makedev(7,77))
            return safe(p,st.st_dev,*args,**kwargs)
        self.m.patch(self.w,'safe_path',safe_path)
        self.m.patch(self.w,'assert_internal_state',Mock())
        self.m.patch(self.w,'recover_image',Mock(side_effect=AssertionError('Adoption must never mount')))
        self.ctx=self.b.image_context();self.images=self.b.images
        self.data=dict(mode='existing',name='Existing backups',image=str(self.file))
        self.session=self.m.broker.sessions.login('admin','synthetic')

    def snapshot(self):
        return dict(fstab=self.m.fstab.read_bytes(),fstab_mode=self.m.fstab.stat().st_mode,
                    folder=tuple(self.target.stat()),data=(self.target/'existing-file').read_bytes(),
                    image=hashlib.sha256(self.file.read_bytes()).hexdigest(),rows=copy.deepcopy(self.rows))
    def plan(self):return self.images.plan(self.ctx,self.data)
    def apply(self,plan):return self.images.apply(self.ctx,plan,dict(token=plan['token'],confirm=True))
    def request(self,action,data,csrf=True):
        return self.m.broker.local_handle(dict(action=action,data=data,write=True,token=self.session['token'],
            csrf=self.session['csrf'] if csrf else 'invalid'))

    def test_broker_review_apply_preserves_mount_fstab_data_and_permissions(self):
        before=self.snapshot();config=self.b.configuration()
        review=self.request('image-plan',self.data);self.assertEqual(review['status'],200,review)
        value=review['data'];self.assertEqual(value['mode'],'adopt')
        for text in (str(self.file),str(self.target),IMAGE_UUID):self.assertIn(text,value['message'])
        self.assertEqual(self.b.configuration(),config)
        consent=dict(token=value['token'],confirm=True)
        self.assertEqual(self.request('image-apply',consent,csrf=False)['status'],401)
        result=self.request('image-apply',consent);self.assertEqual(result['status'],200,result)
        self.assertTrue(result['data']['registered']);self.assertFalse(result['data']['image_created'])
        self.assertEqual(self.snapshot(),before)
        current=self.b.configuration();item=current['images'].pop()
        self.assertEqual(current,config);self.assertEqual(item['mountpoint'],str(self.target));self.assertEqual(item['fstab_options'],self.options)
        self.assertTrue(list((self.b.s.STATE_DIR/'image-backups').glob('*.json')))
        self.assertEqual(self.request('image-apply',consent)['status'],400)
        self.assertFalse(any(c[0]=='/usr/bin/systemctl' and c[1] in ('stop','start','restart','daemon-reload') for c in self.m.calls))

    def test_repeat_adoption_retains_name_disabled_choice_and_all_settings(self):
        self.apply(self.plan());cfg=self.b.configuration();cfg['images'][0].update(name='Retained name',enabled=False)
        self.b.cli.save(self.b.s.CONFIG,cfg);before=self.snapshot();saved=self.b.s.CONFIG.read_bytes()
        self.data['name']='Do not rename'
        review=self.plan();self.assertTrue(review['already_registered']);result=self.apply(review)
        self.assertFalse(result['changed']);self.assertEqual(self.b.s.CONFIG.read_bytes(),saved);self.assertEqual(self.snapshot(),before)

    def test_conflicting_fstab_and_registration_refused(self):
        original=self.m.fstab.read_text()
        for entry in (self.entry, f'UUID={IMAGE_UUID} /mnt/other ext4 loop 0 0\n',
                      f'/dev/loop-fixture /mnt/other ext4 defaults 0 0\n',
                      f'/other.img {self.target} ext4 loop 0 0\n'):
            with self.subTest(entry=entry):
                self.m.fstab.write_text(original+entry)
                with self.assertRaises(ValueError):self.plan()
        self.m.fstab.write_text(original)
        cfg=self.b.configuration();cfg['images']=[dict(name='conflict',enabled=False,uuid=IMAGE_UUID,
            image=str(self.disk/'other.img'),mountpoint=str(self.disk/'elsewhere'),fstab_options='loop,noauto')]
        self.b.cli.save(self.b.s.CONFIG,cfg)
        with self.assertRaisesRegex(ValueError,'conflicts'):self.plan()

    def test_main_and_image_identity_and_mount_refusals(self):
        for dev in (self.dev,'7:77'):
            old=self.actual_uuid[dev];self.actual_uuid[dev]='wrong'
            with self.subTest(dev=dev),self.assertRaises(self.w.Unsafe):self.plan()
            self.actual_uuid[dev]=old
        rows=copy.deepcopy(self.rows)
        for index in (1,2):
            self.rows=[r for i,r in enumerate(rows) if i!=index]
            with self.subTest(missing=index),self.assertRaises(self.w.Unsafe):self.plan()
        self.rows=rows
        for key,value in [('back-file',str(self.disk/'wrong.img')),('back-ino',1),('back-maj:min','8:99'),('offset',512),('sizelimit',4096),('name','/dev/not-the-loop')]:
            old=self.loops[0][key];self.loops[0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.plan()
            self.loops[0][key]=old
        self.loops.append(copy.deepcopy(self.loops[0]))
        with self.assertRaisesRegex(ValueError,'ambiguous'):self.plan()

    def test_changed_identity_or_settings_after_review_is_refused(self):
        review=self.plan();before=self.b.s.CONFIG.read_bytes();self.loops[0]['back-ino']+=1
        with self.assertRaises(ValueError):self.apply(review)
        self.assertEqual(self.b.s.CONFIG.read_bytes(),before)
        self.loops[0]['back-ino']-=1;review=self.plan();self.m.fstab.write_text(self.m.fstab.read_text()+'# administrator change\n')
        with self.assertRaisesRegex(ValueError,'Settings changed'):self.apply(review)
        self.assertEqual(self.b.s.CONFIG.read_bytes(),before)

    def test_active_incident_and_worker_locks_refuse(self):
        review=self.plan();receipt=self.b.s.STATE_DIR/'state.json';receipt.write_text(json.dumps(dict(incident=dict(phase='wait1'))))
        with self.assertRaisesRegex(ValueError,'Recovery is in progress'):self.apply(review)
        receipt.write_text('{}')
        for name in ('preparation.lock','monitor.lock'):
            with (self.b.s.STATE_DIR/name).open('a') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.subTest(lock=name),self.assertRaises((OSError,ValueError)):self.apply(review)
        self.assertEqual(self.b.configuration()['images'],[])

    def test_unsafe_symlink_and_offset_are_refused(self):
        actual=self.target.with_name('real-files');self.target.rename(actual);self.target.symlink_to(actual)
        with self.assertRaises(self.w.Unsafe):self.plan()
        self.target.unlink();actual.rename(self.target)
        (self.root/'sys/dev/block/7:77/loop/offset').write_text('512')
        with self.assertRaises(self.w.Unsafe):self.plan()

    def test_monitoring_resume_only_own_unit_no_mount_or_ftp_operations(self):
        self.m.active=True;self.apply(self.plan());self.assertTrue(self.m.active)
        writes=[c for c in self.m.calls if c[0]=='/usr/bin/systemctl' and c[1] in ('start','stop','restart','daemon-reload')]
        self.assertEqual(writes,[['/usr/bin/systemctl','stop',self.b.cli.SERVICE],['/usr/bin/systemctl','start',self.b.cli.SERVICE]])

    def test_readback_failure_rolls_back_configuration(self):
        review=self.plan();before=self.b.configuration();storage=self.snapshot();save=self.b.cli.save
        def corrupt_once(path,value):
            value=copy.deepcopy(value)
            if path==self.b.s.CONFIG and value['images']:value['notifications']['enabled']=True
            save(path,value)
        self.m.patch(self.b.cli,'save',corrupt_once)
        with self.assertRaisesRegex(ValueError,'readback'):self.apply(review)
        self.assertEqual(self.b.configuration(),before);self.assertEqual(self.snapshot(),storage)

    def test_change_during_backup_refused_before_config_write(self):
        review=self.plan();save=self.b.cli.save;before=self.b.s.CONFIG.read_bytes()
        def changed(path,value):
            save(path,value)
            if 'image-backups' in path.parts:self.loops[0]['offset']=512
        self.m.patch(self.b.cli,'save',changed)
        with self.assertRaises(ValueError):self.apply(review)
        self.assertEqual(self.b.s.CONFIG.read_bytes(),before)

    def test_foreign_profile_cannot_claim_same_image_uuid(self):
        foreign=copy.deepcopy(self.config);foreign['disk'].update(uuid=IMAGE_UUID,mountpoint='/mnt/foreign')
        self.m.patch(self.b.cli.drives,'files',lambda s:[('foreign',self.root/'foreign.json')])
        self.m.patch(self.b.cli.drives,'read',lambda s,p:foreign)
        with self.assertRaisesRegex(ValueError,'another drive profile'):self.plan()

if __name__=='__main__':unittest.main()
