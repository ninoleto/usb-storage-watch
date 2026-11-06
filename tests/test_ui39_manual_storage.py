# SPDX-License-Identifier: MIT
"""Shared manual admission, real selections/locks/HTTP, simulated storage/Docker."""
import copy
import fcntl
import json
import struct
import threading
import unittest
import uuid
from unittest.mock import Mock, patch

from gui_fixture import load
import test_ui18_docker_actions as manual

ID = manual.IDENTITY
IMAGE = '33333333-3333-4333-8333-333333333333'


class ManualStorage(unittest.TestCase):
    def setUp(self):
        manual.ManualControls.setUp(self)
        self.boot = load('boot_start'); self.engines = {}; self.events = []; self.mode = 'ready'
        self.verify_hook = lambda: None
        original = self.b.common.module
        self.f.main.patch(self.b.common, 'module', lambda name, *args:
                          self.boot if name == 'boot_start' else original(name, *args))
        real_engine = self.boot.engine
        def engine(b, drive, config):
            w = real_engine(b, drive, config)
            actual_main, actual_image = w.verify_main, w.verify_dependent
            def verify():
                self.events.append('verify:' + drive); self.verify_hook()
                if self.mode == 'missing': raise FileNotFoundError('synthetic absent device')
                if self.mode == 'unverifiable': raise PermissionError('private OS detail')
                if self.mode == 'directory':
                    with patch.object(w, 'device_number', return_value='240:1'), patch.object(w, 'read_rows', return_value=[]):
                        actual_main()  # Actual verifier rejects a directory without a mount.
                if self.mode == 'uuid':
                    data = bytearray(1024); struct.pack_into('<H', data, 0x38, 0xef53)
                    data[0x68:0x78] = uuid.UUID(IMAGE).bytes
                    w.superblock(bytes(data), config['disk']['uuid'], False)
                return '240:1'
            def image(item):
                self.events.append('image:' + item['uuid'])
                if self.mode == 'image-missing':
                    with patch.object(w, 'read_rows', return_value=[]): actual_image(item)
                if self.mode == 'image-wrong':
                    data = bytearray(1024); struct.pack_into('<H', data, 0x38, 0xef53)
                    data[0x68:0x78] = uuid.UUID(config['disk']['uuid']).bytes
                    w.superblock(bytes(data), item['uuid'], False)
            w.verify_main = Mock(side_effect=verify); w.verify_dependent = Mock(side_effect=image)
            w.mount_main = Mock(side_effect=AssertionError('No implicit mount'))
            w.recover_image = Mock(side_effect=AssertionError('No implicit image mount'))
            self.engines[drive] = w
            return w
        self.f.main.patch(self.boot, 'engine', engine)
        self.configure()
        self.headers = {'Origin':'http://127.0.0.1:8765', 'X-USW-Request':'1', 'X-CSRF-Token':self.f.session['csrf']}
        self.http = self.f.main.web.create_app(dict(self.b.common.DEFAULT, port=8765), self.f.main.broker.handle).test_client()
        self.http.set_cookie('usw_session', self.f.session['token'], domain='127.0.0.1')

    data = manual.ManualControls.data
    run_action = manual.ManualControls.run_action

    def configure(self, images=False, recovery=True, boot=False, retained=False):
        c = self.b.configuration(); mount = c['disk']['mountpoint']
        if images:
            c['images'] = [dict(name='files', uuid=IMAGE, enabled=False, image=mount+'/files.img',
                                mountpoint=mount+'/files', fstab_options='loop,nofail,nodev,nosuid')]
        spec = dict(name='erugo', container_id=ID, images=[IMAGE] if images else [], source='', destination='', grace=30)
        c['docker'].update(enabled=recovery, containers=[] if retained or not recovery else [spec])
        self.b.cli.save(self.f.main.config, c)
        if boot:
            self.b.cli.save(self.boot.paths(self.b)[0], dict(version=1, containers=[dict(
                id=ID, name='erugo', enabled=False, drives=[dict(id='legacy', images=spec['images'])])]))
        if retained:
            editor=self.b.common.module('app_settings')
            self.b.cli.save(editor.preferences_path(self.b), {ID:dict(id=ID,name='erugo',enabled=False,
                drives=[dict(id='legacy',images=spec['images'])],specs={'legacy':spec})})

    def hold(self):
        p = self.b.s.STATE_DIR/'manual-unmount.json'
        self.b.cli.save(p, dict(boot=self.b.w.boot_id(), phase='complete', control_ids=[ID], held_ids=[ID], uuid=self.f.main.uuid))
        return p

    def assert_refused(self, mode, text, *, images=False):
        self.configure(images=images); self.mode=mode; held=self.hold(); before=held.read_bytes()
        configs=[m.config.read_bytes() for m in (self.f.main,self.f.second)]
        for action in ('start','restart'):
            self.docker.current['running'] = action == 'restart'
            response = self.http.post('/api/docker-container-action', base_url='http://127.0.0.1:8765',
                                      headers=self.headers, json=self.data(action))
            self.assertEqual(response.status_code,400,response.json)
            self.assertIn(text,response.json['error']); self.assertIn('No Docker command',response.json['error'])
            self.assertEqual(held.read_bytes(),before)
            self.assertEqual(self.docker.posts,[])
        self.assertEqual(configs,[m.config.read_bytes() for m in (self.f.main,self.f.second)])
        self.assertFalse((self.b.s.STATE_DIR/'boot-start'/(ID+'.json')).exists())

    def test_completed_unmount_without_incident_cannot_start_into_plain_directory(self):
        self.assert_refused('directory','Expected mount is missing')

    def test_missing_drive(self): self.assert_refused('missing','required filesystem')
    def test_wrong_uuid(self): self.assert_refused('uuid','filesystem UUID is incorrect')
    def test_unverifiable_storage_is_sanitized(self):
        self.assert_refused('unverifiable','PermissionError')
    def test_missing_selected_image(self): self.assert_refused('image-missing','loop mount is absent',images=True)
    def test_wrong_selected_image_uuid(self): self.assert_refused('image-wrong','filesystem UUID is incorrect',images=True)

    def test_ready_storage_monitoring_off_allows_start_restart_and_only_then_clears_hold(self):
        self.configure(images=True); self.f.main.active=False; held=self.hold()
        def post(path, kwargs):
            self.assertEqual(self.events[-2:], ['verify:legacy','image:'+IMAGE])
            self.assertIn(ID,json.loads(held.read_text())['held_ids'])
            self.docker.current.update(running=True,started_at='new-'+str(len(self.docker.posts)))
        self.docker.post_hook=post
        for action in ('start','restart'):
            self.hold(); self.assertTrue(self.run_action(action)['data']['ok'])
            self.assertEqual(json.loads(held.read_text())['held_ids'],[])
        self.assertFalse(self.f.main.active)

    def test_boot_only_and_disabled_retained_choices_are_manual_prerequisites(self):
        for retained in (False,True):
            self.configure(images=True,recovery=False,boot=not retained,retained=retained)
            self.mode='image-missing'
            result=self.run_action('start');self.assertEqual(result['status'],400,result)
            self.assertIn('virtual image files',result['error'])
        self.assertEqual(self.docker.posts,[])

    def test_multiple_drives_union_selected_images_and_omit_unselected_images(self):
        self.configure(images=True)
        self.b.cli.save(self.boot.paths(self.b)[0],dict(version=1,containers=[dict(id=ID,name='erugo',enabled=True,
            drives=[dict(id=self.second,images=[]),dict(id='legacy',images=[])])]))
        self.assertTrue(self.run_action('start')['data']['ok'])
        self.assertEqual(set(self.events),{'verify:legacy','verify:'+self.second,'image:'+IMAGE})

    def test_unrelated_id_with_same_name_has_no_dependencies(self):
        c=self.b.configuration();c['docker']['containers'][0]['container_id']='b'*64;self.b.cli.save(self.f.main.config,c)
        self.mode='missing';self.assertTrue(self.run_action('start')['data']['ok']);self.assertEqual(self.events,[])

    def test_stop_with_unavailable_storage_never_probes_or_clears_hold(self):
        self.configure(images=True);self.mode='missing';self.docker.current['running']=True
        held=self.hold();before=held.read_bytes()
        self.assertTrue(self.run_action('stop')['data']['ok'])
        self.assertEqual(self.events,[]);self.assertEqual(held.read_bytes(),before)
        self.assertIn('/stop?',self.docker.posts[0][0])

    def test_running_start_still_verifies_before_releasing_hold(self):
        self.mode='missing';self.docker.current['running']=True;held=self.hold();before=held.read_bytes()
        self.assertEqual(self.run_action('start')['status'],400)
        self.assertEqual(held.read_bytes(),before);self.assertEqual(self.docker.posts,[])

    def test_settings_changed_during_inspection_refuses_without_replay(self):
        old=self.docker.inspect
        def inspect(identity):
            c=self.b.configuration();c['disk']['label']='Changed';self.b.cli.save(self.f.main.config,c)
            return old(identity)
        self.docker.inspect=inspect
        self.assertIn('settings changed',self.run_action('restart')['error']);self.assertEqual(self.docker.posts,[])

    def test_storage_and_container_locks_held_through_verification_and_post(self):
        root=self.b.cli.drives.roots(self.b.s)[1]
        def locked():
            for path in (self.b.s.STATE_DIR/'recovery.lock',root/'shared-locks'/('docker-restart-'+ID+'.lock')):
                with path.open('rb') as fd:
                    with self.assertRaises(BlockingIOError):fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.verify_hook=locked
        self.docker.post_hook=lambda *_:(locked(),self.docker.current.update(running=True,started_at='new'))
        self.assertTrue(self.run_action('start')['data']['ok'])

    def test_competing_storage_operation_refuses_and_releases_partial_locks(self):
        path=self.b.s.STATE_DIR/'recovery.lock';path.touch(mode=0o600)
        with path.open('rb') as fd:
            fcntl.flock(fd,fcntl.LOCK_EX)
            result=self.run_action('restart');self.assertEqual(result['status'],400)
            self.assertIn('Another operation',result['error']);self.assertEqual(self.docker.posts,[])
        self.assertTrue(self.run_action('start')['data']['ok'])

    def test_unpinned_legacy_selection_requires_explicit_identity_review(self):
        c=self.b.configuration();c['docker']['containers'][0].pop('container_id');self.b.cli.save(self.f.main.config,c)
        self.assertIn('no pinned container identity',self.run_action('start')['error'])
        self.assertEqual(self.docker.posts,[])

    def test_unselected_registered_images_do_not_become_prerequisites(self):
        self.configure(images=True)
        c=self.b.configuration();c['docker']['containers'][0]['images']=[];self.b.cli.save(self.f.main.config,c)
        self.mode='image-missing';self.assertTrue(self.run_action('start')['data']['ok'])
        self.assertEqual(self.events,['verify:legacy'])

    def test_corrupt_choices_refuse_without_disclosing_contents(self):
        self.boot.paths(self.b)[0].write_text('private-invalid-json')
        result=self.run_action('start');self.assertEqual(result['status'],400)
        self.assertIn('choices could not be verified',result['error'])
        self.assertNotIn('private-invalid-json',result['error']);self.assertEqual(self.docker.posts,[])

    def test_competing_app_actions_refused_while_unrelated_app_remains_usable(self):
        reached=threading.Event();release=threading.Event();results=[]
        def pause():
            reached.set();self.assertTrue(release.wait(4))
        self.verify_hook=pause
        old=self.docker.inspect
        self.docker.inspect=lambda identity:dict(old(identity),id=identity,name='erugo' if identity==ID else 'unrelated')
        thread=threading.Thread(target=lambda:results.append(self.run_action('start')))
        thread.start()
        try:
            self.assertTrue(reached.wait(3))
            self.assertIn('Another operation',self.run_action('stop')['error'])
            other=self.f.request('docker-container-action',dict(id='b'*64,name='unrelated',action='start',confirm=True),profile=None)
            self.assertTrue(other['data']['ok'],other)
        finally:release.set();thread.join(4)
        self.assertFalse(thread.is_alive());self.assertTrue(results[0]['data']['ok'],results)


if __name__ == '__main__': unittest.main()
