# SPDX-License-Identifier: MIT
"""Multiple-image upgrade/recovery and explicit file-only setup regressions."""
import copy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from gui_fixture import load, Machine, UUID, DESKTOP


def image(number,base='/mnt/storage'):
    return dict(name='Image '+str(number),enabled=True,uuid=f'{number:08d}-1111-4111-8111-111111111111',
                image=base+f'/image{number}.img',mountpoint=base+f'/app{number}',fstab_options='loop,nofail,nodev,nosuid')


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.w=load('engine');self.s=self.w.settings
        self.c=self.s.default();self.c['disk'].update(uuid=UUID,fstab_options='defaults')

    def test_existing_single_image_upgrade_keeps_values_and_orders_new_dependencies(self):
        old=image(2);old.pop('name');self.c['dependent']=old;self.c.pop('images')
        original=copy.deepcopy(self.c)
        upgraded=self.s.validate(self.c)
        self.assertEqual(upgraded['dependent'],original['dependent'])
        child=image(3);child['image']=old['mountpoint']+'/nested.img';child['mountpoint']=old['mountpoint']+'/nested'
        upgraded['images']=[child,image(4)]
        self.w.configure(upgraded)
        self.assertEqual(self.w.DEPENDENCIES[0]['uuid'],old['uuid'])
        self.assertLess([v['uuid'] for v in self.w.DEPENDENCIES].index(old['uuid']),[v['uuid'] for v in self.w.DEPENDENCIES].index(child['uuid']))
        self.assertEqual(self.w.IMAGE,old['image'])

    def test_duplicate_uuid_path_mount_or_cycle_is_refused(self):
        for field in ('uuid','image','mountpoint'):
            self.c['images']=[image(2),image(3)];self.c['images'][1][field]=self.c['images'][0][field]
            with self.subTest(field=field),self.assertRaises(ValueError):self.s.validate(self.c)
        one,two=image(2),image(3);one['image']=two['mountpoint']+'/a.img';two['image']=one['mountpoint']+'/b.img'
        self.c['images']=[one,two]
        with self.assertRaisesRegex(ValueError,'circular'):self.s.validate(self.c)

    def test_disabled_parent_blocks_enabled_child_and_many_containers_supported(self):
        one,two=image(2),image(3);one['enabled']=False;two['image']=one['mountpoint']+'/a.img'
        self.c['images']=[two,one]
        with self.assertRaisesRegex(ValueError,'parent'):self.s.validate(self.c)
        self.c['images']=[]
        self.c['docker'].update(enabled=True,containers=[dict(name='app'+str(n),source='/mnt/storage/app'+str(n),destination='/data',grace=30) for n in range(15)])
        self.assertEqual(len(self.s.validate(self.c)['docker']['containers']),15)

    def test_multiple_images_restored_in_order_and_partial_results_are_per_image(self):
        parent,child=image(2),image(3);child['image']=parent['mountpoint']+'/child.img'
        self.c['images']=[child,parent,image(4)];self.w.configure(self.c)
        calls=[]
        def restore(item,request,note):
            calls.append(item['uuid'])
            if item['uuid']==child['uuid']:raise self.w.Unsafe('Image UUID mismatch')
        with tempfile.TemporaryDirectory() as directory,patch.object(self.w,'snapshot',return_value=dict(healthy=True,detected=True,mounts=[])),patch.object(self.w,'verify_main'),patch.object(self.w,'verify_access'),patch.object(self.w,'verify_dependent'),patch.object(self.w,'recover_image',side_effect=restore):
            result=self.w.recovery_work(dict(incident='test',number=1),Path(directory)/'receipt')
        self.assertLess(calls.index(parent['uuid']),calls.index(child['uuid']))
        self.assertTrue(result['main']);self.assertFalse(result['dependent'])
        self.assertEqual(len(result['images']),3)
        self.assertEqual([v['name'] for v in result['images'] if not v['healthy']],[child['name']])
        self.assertIn('Image UUID mismatch',result['dependent_reason'])

    def test_child_never_mounts_hidden_files_when_parent_image_is_missing(self):
        parent,child=image(2),image(3);child['image']=parent['mountpoint']+'/child.img'
        self.c['images']=[child,parent];self.w.configure(self.c)
        with patch.object(self.w,'verify_dependent',side_effect=self.w.Unsafe('Parent image absent')) as verify,patch.object(self.w,'command') as command:
            with self.assertRaisesRegex(self.w.Unsafe,'Parent image absent'):
                self.w.recover_image(child,dict(allow_mount=True,blocked=[]),lambda *args:None)
            verify.assert_called_once_with(parent);command.assert_not_called()

    def test_more_than_ten_container_ledger_entries_remain_readable(self):
        self.c['docker'].update(enabled=True,containers=[dict(name='app'+str(n),source='/mnt/storage/app'+str(n),destination='/data',grace=30) for n in range(15)])
        self.w.configure(self.c)
        with tempfile.TemporaryDirectory() as directory:
            ctx=self.w.usb_context(Path(directory))
            record=dict(version=1,incident='test',complete=True,containers={name:dict(status='preserved_stopped',action_count=0) for name in self.w.apps.APPS})
            self.w.apps.save(ctx,record)
            self.assertEqual(len(self.w.apps.read_ledger(ctx,'test')['containers']),15)


class ImageSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.w=load('engine');self.s=self.w.settings;self.mod=load('web_images');self.p=load('web_prepare')
        self.c=self.s.default();self.c['disk'].update(uuid=UUID,mountpoint=str(self.root),fstab_options='defaults')
        self.w.configure(self.c)
        dev=self.root.stat().st_dev;self.dev=f'{os.major(dev)}:{os.minor(dev)}'
        self.enterContext(patch.object(self.w,'verify_main',return_value=self.dev))
        self.enterContext(patch.object(self.w,'read_rows',return_value=[dict(target=str(self.root),dev=self.dev)]))
        self.enterContext(patch.object(self.p,'exclusive',side_effect=lambda _:nullcontext()))
        self.b=SimpleNamespace(w=self.w,s=self.s,preparation=self.p,configuration=lambda:copy.deepcopy(self.c),fstab_entries=lambda:[])

    def real_image(self,name):
        path=self.root/name
        with path.open('xb') as output:output.truncate(32*1024**2)
        subprocess.run(['/usr/sbin/mkfs.ext4','-q','-E','nodiscard',str(path)],check=True,capture_output=True)
        return path

    def test_real_ext4_images_are_detected_without_modification_or_manual_uuid(self):
        for name in ('one.img','two.img'):
            path=self.real_image(name);before=path.read_bytes()
            value=self.mod.proposal(self.b,dict(mode='existing',name=name,image=str(path),mountpoint=str(self.root/name.replace('.img',''))))
            self.s.disk_uuid(value['item']['uuid'])
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(value['observed']['inode'],path.stat().st_ino)

    def test_symlink_image_or_mount_component_and_non_ext4_are_refused(self):
        path=self.real_image('existing.img');(self.root/'alias.img').symlink_to(path)
        with self.assertRaises(OSError):self.mod.probe(self.b,str(self.root/'alias.img'))
        (self.root/'escape').symlink_to('/tmp')
        with self.assertRaises(OSError):self.mod.rooted(self.b,str(self.root/'escape'/'new'),create=True)
        (self.root/'invalid.img').write_bytes(b'not a filesystem')
        with self.assertRaises(ValueError):self.mod.probe(self.b,str(self.root/'invalid.img'))

    def test_new_image_never_overwrites_existing_file_and_requires_confirmation(self):
        folder=self.root/'usb-storage-watch-volumes/.images';folder.mkdir(parents=True);sentinel=folder/'Photos.img';sentinel.write_text('keep me')
        with self.assertRaisesRegex(ValueError,'already exists'):self.mod.proposal(self.b,dict(mode='create',name='Photos',size_gib=1))
        with patch.object(self.p,'run') as run:
            for data in ({},{'confirm':True},{'confirm':False,'token':'t'}):
                with self.assertRaises(ValueError):self.mod.apply(self.b,None,data)
            run.assert_not_called()
        self.assertEqual(sentinel.read_text(),'keep me')

    def test_remove_configuration_keeps_image_and_backup_and_fstab_unrelated_lines(self):
        m=Machine();self.addCleanup(m.close);b=m.b
        c=b.s.default();c['disk'].update(uuid=UUID,mountpoint=DESKTOP,fstab_options='defaults');c['images']=[image(2,DESKTOP),image(3,DESKTOP)]
        b.cli.save(m.config,c);sentinel=m.disk_data/'existing.img';sentinel.write_bytes(b'keep image contents')
        m.current=''
        first=c['images'][0];m.fstab.write_text(m.original+first['image']+' '+first['mountpoint']+' ext4 loop 0 0\n')
        with patch.object(b.preparation,'exclusive',side_effect=lambda _,**kw:nullcontext()):
            result=b.images.manage(b.image_context(),dict(uuid=first['uuid'],action='remove',confirm=True))
        self.assertIn('kept',result['message']);self.assertEqual(sentinel.read_bytes(),b'keep image contents')
        self.assertEqual(m.fstab.read_text(),m.original);self.assertEqual(len(b.configuration()['images']),1)
        self.assertEqual(len(list((m.state/'image-backups').glob('*.json'))),1)

    def test_image_endpoints_require_admin_and_csrf_and_session_bound_one_use_consent(self):
        m=Machine();self.addCleanup(m.close);b=m.b
        req=dict(drive='legacy',action='image-plan',write=True,data=dict(mode='create',name='Test',size_gib=1))
        with patch.object(b.images,'plan',return_value=dict(item=image(2),size=1024,mode='create',token='consent')) as plan,patch.object(b.pwd,'getpwnam',return_value=Mock(pw_uid=1000,pw_gid=1000)):
            self.assertEqual(m.broker.handle(req)['status'],401);plan.assert_not_called()
            login=m.broker.sessions.login('admin','synthetic');credentials={key:login[key] for key in ('token','csrf')}
            self.assertEqual(m.broker.handle(req|credentials)['status'],200)
            with patch.object(b.images,'apply',side_effect=ValueError('Synthetic refusal')) as apply:
                action=dict(drive='legacy',action='image-apply',write=True,data=dict(confirm=True,token='consent'))|credentials
                self.assertEqual(m.broker.handle(action)['status'],400)
                self.assertEqual(m.broker.handle(action)['status'],400)
                self.assertIsNone(apply.call_args.args[1])


class ReformatPlanTests(unittest.TestCase):
    def test_selected_drive_is_reviewable_but_unrelated_permanent_entry_blocks(self):
        m=Machine();self.addCleanup(m.close);b=m.b;p=b.preparation
        c=b.s.default();c['disk'].update(uuid=UUID,mountpoint=DESKTOP,fstab_options='defaults');b.cli.save(m.config,c)
        m.fstab.write_text(m.original+f'UUID={UUID} {DESKTOP} ext4 defaults 0 0\n')
        disk=dict(serial='TEST0001',devs=['240:1'],layout=[])
        with patch.object(p,'exclusive',side_effect=lambda _:nullcontext()),patch.object(p,'binding',return_value=disk),patch.object(p,'unused') as unused,patch.object(p,'signatures',return_value=dict(filesystems=[dict(UUID=UUID)])),patch.object(p,'run') as run:
            result=p.plan(b.preparation_context(),dict(device='synthetic',name='New'))
            self.assertTrue(result['selected']);unused.assert_called_once();run.assert_not_called()
            m.fstab.write_text(m.original+f'UUID={UUID} /mnt/unrelated ext4 defaults 0 0\n')
            with self.assertRaisesRegex(ValueError,'permanent'):p.plan(b.preparation_context(),dict(device='synthetic',name='New'))

class LocalNetworkTests(unittest.TestCase):
    def test_auto_lan_accepts_only_discovered_private_address_and_creates_valid_tls(self):
        import ssl
        b=load('web_broker')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def command(args,timeout=10):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=timeout).stdout
            with patch.object(b.s,'STATE_DIR',root),patch.object(b.common,'WEB_DIR',root),patch.object(b,'command',side_effect=command),patch.object(b,'lan_info',return_value=dict(addresses=[dict(address='10.0.0.2')])) ,patch.object(b,'network',return_value=dict(url='https://10.0.0.2:8765',message='Saved')) as network:
                for data in (dict(enabled=True,address='10.0.0.2'),dict(enabled=True,confirm=True,address='8.8.8.8'),dict(enabled=True,confirm=True,address='0.0.0.0')):
                    with self.assertRaises(ValueError):b.lan_auto(data)
                network.assert_not_called()
                result=b.lan_auto(dict(enabled=True,confirm=True,address='10.0.0.2'))
                args=network.call_args.args[0]
                certificate=root/'verify.pem';key=root/'verify-key.pem'
                certificate.write_text(args['certificate']);key.write_text(args['key'])
                ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(certificate,key)
                self.assertIn('does match certificate',command(['/usr/bin/openssl','x509','-in',str(certificate),'-checkip','10.0.0.2','-noout']))
                (root/'local-network-ca.pem').write_text(args['local_ca'])
                command(['/usr/bin/openssl','verify','-CAfile',str(root/'local-network-ca.pem'),str(certificate)])
                self.assertIn('SHA256',result['fingerprint'].upper());self.assertNotIn('PRIVATE KEY',json.dumps(result))
                self.assertEqual((root/'local-network-ca.pem').read_text(),result['certificate'])


if __name__=='__main__':unittest.main()
