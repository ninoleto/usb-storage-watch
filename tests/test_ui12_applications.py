# SPDX-License-Identifier: MIT
"""Detected storage is advisory; no real Docker or disk operations."""
import copy
import os
from pathlib import Path
from unittest.mock import Mock
from test_apps import Temp, FakeDocker, a, w, observation

class StorageDependencies(Temp):
    def setUp(self):
        super().setUp()
        self.root=self.directory/'storage';self.root.mkdir()
        self.ctx.MOUNT=str(self.root)
        self.ctx.SETTINGS=copy.deepcopy(w.SETTINGS)
        self.ctx.SETTINGS['disk']['mountpoint']=str(self.root)
        self.ctx.SETTINGS['dependent']['enabled']=False
        self.ctx.SETTINGS['dependent']['uuid']=''
        self.image=dict(name='backups',enabled=True,uuid='22222222-2222-4222-8222-222222222222',image=str(self.root/'backup.img'),mountpoint=str(self.root/'backup'),fstab_options='loop,nofail,nodev,nosuid,noexec')
        self.ctx.SETTINGS['images']=[self.image]
        self.ctx.DEPENDENCIES=[self.image]
        specs=copy.deepcopy(a.APPS)
        for name,relative in [('app_one','uploads'),('app_two','backup/app'),('app_three','other')]:
            source=self.root/relative;source.mkdir(parents=True,exist_ok=True);specs[name]['source']=str(source)
        self.stack.enter_context(__import__('unittest.mock',fromlist=['patch']).patch.object(a,'APPS',specs))
        self.docker=FakeDocker()
        self.realdev=f'{os.major(self.root.stat().st_dev)}:{os.minor(self.root.stat().st_dev)}'
        self.ctx.verify_main=Mock(return_value=self.realdev)
        self.image_ready=False;self.image_checks=[]
        def image_check(item):
            self.image_checks.append(item['name'])
            if not self.image_ready:raise w.Unsafe('Required image is missing')
        self.ctx.verify_dependent=Mock(side_effect=image_check)
        def rows():
            text=f'1 0 240:0 / / rw - ext4 /dev/system rw\n2 1 {self.realdev} / {self.root} rw - ext4 /dev/synthetic rw\n'
            if self.image_ready:text+=f'3 2 {self.realdev} / {self.root}/backup rw - ext4 /dev/synthetic-image rw\n'
            return w.parse_mounts(text)
        self.ctx.read_rows=rows
        self.source.side_effect=lambda ctx,name,request=None:self.real_source(ctx,name,request)
        self.ctx.snapshot=lambda:observation(self.healthy,self.image_ready)
    def test_all_selected_apps_restart_despite_detected_missing_image(self):
        result=a.recover(self.ctx,self.ready(loopfs=False),self.docker)
        self.assertEqual([row[0] for row in self.docker.changes],['app_one','app_two','app_three'])
        self.assertEqual(result['containers']['app_one']['status'],'verified')
        self.assertEqual(result['containers']['app_two']['status'],'verified')
        self.assertEqual(result['containers']['app_two']['action_count'],1)
        self.assertTrue(result['all_verified']);self.assertTrue(result['storage_verified'])
        self.assertTrue(result['containers']['app_two']['warnings'])
        self.assertTrue(all(row[2]=='start' for row in self.docker.changes))
    def test_image_bound_container_recovers_after_its_image_is_ready(self):
        self.image_ready=True
        result=a.recover(self.ctx,self.ready(),self.docker)
        self.assertEqual(result['containers']['app_two']['status'],'verified')
        self.assertEqual(len(self.docker.changes),3)
        self.assertTrue(result['all_verified'])
    def test_secondary_image_bind_warns_without_blocking_container(self):
        self.docker.containers['app_one']['mounts'].append(dict(Type='bind',Source=str(self.root/'backup/app'),Destination='/backup',RW=False,Propagation='rprivate'))
        result=a.recover(self.ctx,self.ready(loopfs=False),self.docker)
        self.assertIn('app_one',[row[0] for row in self.docker.changes])
        self.assertEqual(result['containers']['app_one']['action_count'],1)
        self.assertTrue(result['containers']['app_one']['warnings'])
        self.assertIn('app_three',[row[0] for row in self.docker.changes])
    def test_disabled_image_and_underlying_directory_never_count_as_recovered(self):
        self.image['enabled']=False
        with self.assertRaisesRegex(a.AppError,'disabled'):self.real_source(self.ctx,'app_two')
        self.ctx.verify_dependent.assert_not_called()
        self.image['enabled']=True
        self.ctx.verify_dependent.side_effect=None
        with self.assertRaisesRegex(a.AppError,'recovered Storage'):self.real_source(self.ctx,'app_two')
    def test_nested_backing_images_and_recursive_binds_are_required(self):
        nested=dict(self.image,name='nested',image=str(self.root/'backup/nested.img'),mountpoint=str(self.root/'nested'),uuid='33333333-3333-4333-8333-333333333333')
        unrelated=dict(self.image,name='other-image',image=str(self.root/'other.img'),mountpoint=str(self.root/'unrelated'))
        self.ctx.SETTINGS['images']=[self.image,nested,unrelated]
        required=a.required_images(self.ctx,[str(self.root/'nested/app')])
        self.assertEqual([item['name'] for item in required],['backups','nested'])
        self.assertEqual(a.required_images(self.ctx,[str(self.root/'uploads')]),[])
        self.assertEqual(len(a.required_images(self.ctx,[str(self.root)])),3)
    def test_dependency_labels_follow_all_binds(self):
        current=self.docker.inspect('app_one')
        labels=a.required_storage_labels(self.ctx,current)
        self.assertFalse(any('image:' in label for label in labels))
        current['mounts'].append(dict(Type='bind',Source=str(self.root/'backup/app')))
        self.assertIn('image: backups',a.required_storage_labels(self.ctx,current))
