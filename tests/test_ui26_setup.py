# SPDX-License-Identifier: MIT
"""Policy/setup tests: synthetic Docker, real private files; no live container changes."""
import copy
import json
import os
import pwd
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from gui_fixture import load
from multidrive_fixture import FleetMachine

IDENTITY = 'c' * 64
SYSTEM_PWD = SimpleNamespace(getpwuid=pwd.getpwuid, getpwnam=pwd.getpwnam, getpwall=pwd.getpwall)


class Docker:
    def __init__(self):
        self.raw = dict(Id=IDENTITY, Name='/folder-app', Image='sha256:synthetic', RestartCount=0,
            Config=dict(Env=['PRIVATE=synthetic-test-value'], Labels={}),
            HostConfig=dict(RestartPolicy=dict(Name='unless-stopped', MaximumRetryCount=0),
                            PortBindings={'80/tcp':[dict(HostIp='127.0.0.1', HostPort='8080')]}, AutoRemove=False),
            Mounts=[dict(Type='bind', Source='/mnt/external/uploads', Destination='/data')],
            NetworkSettings={}, State=dict(StartedAt='before', Running=True, Paused=False, Restarting=False, Dead=False))
        self.updates = []; self.failure = None

    def request(self, method, path, body=None, **kwargs):
        if method == 'GET':
            if self.failure == 'unreadable' and self.updates: raise OSError('synthetic private daemon output')
            return copy.deepcopy(self.raw)
        assert method == 'POST' and path == '/containers/' + IDENTITY + '/update'
        assert set(body) == {'RestartPolicy'}
        self.updates.append(copy.deepcopy(body))
        if self.failure == 'refused': raise RuntimeError('synthetic private daemon output')
        self.raw['HostConfig']['RestartPolicy'] = copy.deepcopy(body['RestartPolicy'])
        if self.failure in ('timeout', 'unreadable'): raise TimeoutError()


class Setup(unittest.TestCase):
    def setUp(self):
        self.f = FleetMachine(); self.addCleanup(self.f.close); self.other = self.f.add()
        self.b = self.f.main.b; self.m = load('docker_setup'); self.editor = load('compose_setup')
        self.f.main.patch(self.editor, 'pwd', SYSTEM_PWD)
        self.web = load('web_docker'); self.docker = Docker(); self.session = {}
        self.f.main.patch(self.web, 'client', lambda *_:(self.docker, 'v1.47'))
        original = self.b.common.module
        self.f.main.patch(self.b.common, 'module', lambda name,*args:
                          self.m if name=='docker_setup' else self.editor if name=='compose_setup'
                          else self.web if name=='web_docker' else original(name,*args))
        self.fleet = self.f.main.broker.fleet

    def plan(self): return self.m.plan(self.fleet, dict(id=IDENTITY,name='folder-app'), self.session)

    def apply(self, plan):
        return self.m.apply(self.fleet, dict(id=IDENTITY,name='folder-app',token=plan['token'],confirm=True),self.session)

    def test_explicit_update_preserves_runtime_storage_ports_environment_and_original(self):
        before = copy.deepcopy(self.docker.raw)
        configs = [m.config.read_bytes() for m in (self.f.main, self.f.second)]
        plan = self.plan(); self.assertTrue(plan['allowed']); self.assertEqual(self.docker.updates, [])
        self.assertNotIn('synthetic-test-value', json.dumps(plan))
        result = self.apply(plan); self.assertTrue(result['ok'],result)
        expected = copy.deepcopy(before); expected['HostConfig']['RestartPolicy'] = dict(Name='no',MaximumRetryCount=0)
        self.assertEqual(self.docker.raw, expected)
        self.assertEqual(configs,[m.config.read_bytes() for m in (self.f.main,self.f.second)])
        self.assertEqual(self.m.read(self.b,IDENTITY)['original_policy'],before['HostConfig']['RestartPolicy'])
        self.assertNotIn('synthetic-test-value',json.dumps(result))
        self.apply(self.plan()); self.assertEqual(len(self.docker.updates),1)
        self.assertEqual(self.m.read(self.b,IDENTITY)['original_policy']['Name'],'unless-stopped')

    def test_correct_policy_is_a_noop(self):
        self.docker.raw['HostConfig']['RestartPolicy']=dict(Name='no',MaximumRetryCount=0)
        result=self.apply(self.plan());self.assertTrue(result['ok']);self.assertEqual(self.docker.updates,[])

    def test_original_on_failure_retry_limit_is_preserved(self):
        previous=dict(Name='on-failure',MaximumRetryCount=5)
        self.docker.raw['HostConfig']['RestartPolicy']=previous.copy()
        self.assertTrue(self.apply(self.plan())['ok'])
        self.assertEqual(self.m.read(self.b,IDENTITY)['original_policy'],previous)

    def test_confirmation_authentication_and_no_file_write_arguments(self):
        plan=self.plan()
        with self.assertRaises(ValueError):
            self.m.apply(self.fleet,dict(id=IDENTITY,name='folder-app',token=plan['token'],confirm=False),self.session)
        with self.assertRaises(ValueError):self.m.plan(self.fleet,dict(id=IDENTITY,name='folder-app',path='/etc/passwd'),self.session)
        for action in ('docker-setup-plan','docker-setup-apply'):
            result=self.f.main.broker.handle(dict(action=action,write=True,data=dict(id=IDENTITY,name='folder-app')))
            self.assertEqual(result['status'],401)
        result=self.f.request('docker-setup-plan',dict(id=IDENTITY,name='folder-app'),profile=None)
        self.assertEqual(result['status'],200,result)
        bad=self.f.main.broker.handle(dict(action='docker-setup-apply',write=True,data={},token=self.f.session['token'],csrf='wrong'))
        self.assertEqual(bad['status'],401);self.assertEqual(self.docker.updates,[])
        valid=result['data']
        applied=self.f.request('docker-setup-apply',dict(id=IDENTITY,name='folder-app',token=valid['token'],confirm=True),profile=None)
        self.assertEqual(applied['status'],200,applied);self.assertTrue(applied['data']['ok'])
        with self.assertRaises(ValueError):self.apply(valid)

    def test_stale_id_policy_runtime_or_selections_prevents_update(self):
        for change in ('Id','policy','runtime','storage'):
            with self.subTest(change=change):
                before=copy.deepcopy(self.docker.raw); plan=self.plan()
                if change=='Id':self.docker.raw['Id']='d'*64
                elif change=='policy':self.docker.raw['HostConfig']['RestartPolicy']['Name']='always'
                elif change=='runtime':self.docker.raw['State']['StartedAt']='different'
                else:
                    c=self.b.configuration();c['disk']['label']='edited';self.b.cli.save(self.f.main.config,c)
                with self.assertRaises(ValueError):self.apply(plan)
                self.assertEqual(self.docker.updates,[]);self.docker.raw=before

    def test_timeout_is_read_back_not_replayed(self):
        self.docker.failure='timeout';self.assertTrue(self.apply(self.plan())['ok'])
        self.assertEqual(len(self.docker.updates),1)

    def test_unknown_outcome_blocks_another_apply(self):
        self.docker.failure='unreadable';result=self.apply(self.plan())
        self.assertFalse(result['ok']);self.assertEqual(self.m.read(self.b,IDENTITY)['phase'],'uncertain')
        self.docker.failure=None;self.assertFalse(self.plan()['allowed']);self.assertEqual(len(self.docker.updates),1)

    def test_other_manager_and_auto_remove_need_instructions(self):
        for labels in [{'com.docker.swarm.service.id':'synthetic'},{'io.kubernetes.pod.uid':'synthetic'},{'io.portainer.stack.name':'synthetic'}]:
            self.docker.raw['Config']['Labels']=labels;plan=self.plan()
            self.assertFalse(plan['allowed']);self.assertTrue(plan['instructions'])
        self.docker.raw['Config']['Labels']={};self.docker.raw['HostConfig']['AutoRemove']=True
        self.assertFalse(self.plan()['allowed']);self.assertEqual(self.docker.updates,[])

    def test_later_policy_conflict_is_visible(self):
        self.apply(self.plan());self.docker.raw['HostConfig']['RestartPolicy']['Name']='always'
        result=self.m.summary(self.b,self.docker,IDENTITY,'folder-app')
        self.assertTrue(any('independently' in text for text in result['conflicts']))

    def test_disk_only_prerequisites_stay_explicit(self):
        c=self.b.configuration();c['docker'].update(enabled=True,containers=[dict(name='folder-app',container_id=IDENTITY,
            source='',destination='',grace=30,images=[])])
        self.b.cli.save(self.f.main.config,c);self.f.main.active=False;self.f.second.active=False
        boot=self.b.common.module('boot_start');self.b.cli.save(boot.paths(self.b)[0],dict(version=1,containers=[dict(
            id=IDENTITY,name='folder-app',enabled=True,drives=[dict(id='legacy',images=[])])]))
        plan=self.plan();self.assertEqual(plan['storage']['boot'],[dict(id='legacy',images=[])])
        self.assertEqual(plan['storage']['recovery'],[dict(id='legacy',images=[])])
        self.assertTrue(self.apply(plan)['ok']);self.assertFalse(self.f.main.active);self.assertFalse(self.f.second.active)


class ComposeSetup(Setup):
    def setUp(self):
        super().setUp()
        try:self.editor.binary()
        except self.editor.Unavailable:self.skipTest('System Compose plugin unavailable')
        self.tmp=tempfile.TemporaryDirectory(prefix='usw-compose-test-');self.addCleanup(self.tmp.cleanup)
        self.project=Path(self.tmp.name);self.base=self.project/'compose.yaml';self.override=self.project/'override.yaml'
        self.base.write_text('services:\n  app:\n    image: example.invalid/app:fixed\n    restart: always\n    environment:\n      PRIVATE: synthetic-test-value\n    volumes:\n      - /mnt/external/uploads:/data\n  unrelated:\n    image: example.invalid/other:fixed\n    restart: unless-stopped\n')
        self.override.write_text('services:\n  app:\n    restart: unless-stopped # preserve this comment\n    ports:\n      - "127.0.0.1:8080:80"\n')
        self.base.chmod(0o600);self.override.chmod(0o600)
        self.labels={'com.docker.compose.project':'synthetic','com.docker.compose.service':'app',
                     'com.docker.compose.project.working_dir':str(self.project),
                     'com.docker.compose.project.config_files':str(self.base)+','+str(self.override)}
        ctx=self.editor.context(self.labels)
        self.labels['com.docker.compose.config-hash']=self.editor.run(ctx,ctx['files'],hash_service=True)
        self.docker.raw['Config']['Labels']=self.labels

    def test_compose_exact_override_edit_effective_validation_and_private_backup(self):
        base=self.base.read_text();original=self.override.read_text();plan=self.plan()
        self.assertTrue(plan['allowed'],plan['instructions'])
        self.assertEqual(plan['compose']['file'],str(self.override))
        self.assertNotIn('synthetic-test-value',json.dumps(plan));self.assertEqual(self.override.read_text(),original)
        result=self.apply(plan);self.assertTrue(result['ok'],result)
        self.assertEqual(self.base.read_text(),base)
        self.assertEqual(self.override.read_text(),original.replace('restart: unless-stopped','restart: "no"'))
        record=self.m.read(self.b,IDENTITY);backup=Path(record['backups'][0]['backup'])
        self.assertEqual(backup.read_text(),original);self.assertEqual(backup.stat().st_mode & 0o777,0o600)
        self.assertTrue(result['setup']['source_verified'])
        self.assertTrue(self.plan()['allowed'])  # Managed source hash differs from creation hash, with receipt proof.
        self.assertTrue(self.apply(self.plan())['ok']);self.assertEqual(len(self.docker.updates),1)

    def test_refused_live_update_restores_exact_compose_source(self):
        original=self.override.read_text();self.docker.failure='refused'
        result=self.apply(self.plan());self.assertFalse(result['ok'])
        self.assertEqual(self.override.read_text(),original)
        self.assertEqual(self.m.read(self.b,IDENTITY)['phase'],'rolled-back')

    def test_changed_source_after_preview_is_not_overwritten(self):
        plan=self.plan();self.override.write_text(self.override.read_text()+'# someone else edited\n')
        with self.assertRaises(self.editor.Unavailable):self.apply(plan)
        self.assertTrue(self.override.read_text().endswith('# someone else edited\n'));self.assertEqual(self.docker.updates,[])

    def test_new_environment_file_invalidates_preview(self):
        plan=self.plan();env=self.project/'.env';env.write_text('IGNORED=synthetic\n');env.chmod(0o600)
        with self.assertRaises(self.editor.Unavailable):self.apply(plan)
        self.assertEqual(self.docker.updates,[])

    def test_failed_update_does_not_rollback_over_another_source_edit(self):
        original=self.docker.request
        def request(method,path,body=None,**kwargs):
            if method=='POST':
                self.override.write_text(self.override.read_text()+'# concurrent edit\n')
                raise OSError('synthetic failure')
            return original(method,path,body,**kwargs)
        self.docker.request=request
        result=self.apply(self.plan());self.assertFalse(result['ok'])
        self.assertEqual(self.m.read(self.b,IDENTITY)['phase'],'uncertain')
        self.assertTrue(self.override.read_text().endswith('# concurrent edit\n'))

    def test_other_source_change_during_validation_is_not_certified(self):
        plan=self.plan();original=self.override.read_text();run=self.editor.run
        def changing(ctx,files,**kwargs):
            result=run(ctx,files,**kwargs)
            if kwargs.get('hash_service'): self.base.write_text(self.base.read_text()+'# concurrent edit\n')
            return result
        with patch.object(self.editor,'run',side_effect=changing):result=self.apply(plan)
        self.assertFalse(result['ok']);self.assertEqual(self.docker.updates,[])
        self.assertEqual(self.override.read_text(),original)
        self.assertTrue(self.base.read_text().endswith('# concurrent edit\n'))

    def test_shared_group_and_world_write_are_not_private(self):
        info=SimpleNamespace(st_mode=0o664,st_gid=42)
        fake=SimpleNamespace(getpwnam=lambda _:SimpleNamespace(pw_uid=2000),getpwall=lambda:[])
        with patch.object(self.editor,'pwd',fake),patch.object(self.editor.grp,'getgrgid',return_value=SimpleNamespace(gr_mem=['another'])):
            self.assertFalse(self.editor.private_writes(info,1000))
        self.assertFalse(self.editor.private_writes(SimpleNamespace(st_mode=0o666,st_gid=42),1000))

    def test_later_compose_conflict_is_visible(self):
        self.assertTrue(self.apply(self.plan())['ok'])
        self.override.write_text(self.override.read_text().replace('restart: "no"','restart: always'))
        result=self.m.summary(self.b,self.docker,IDENTITY,'folder-app')
        self.assertFalse(result['source_verified']);self.assertTrue(any('Compose' in t for t in result['conflicts']))

    def test_ambiguous_hash_duplicate_alias_remote_include_and_symlink_refused(self):
        original=self.override.read_text()
        variants=['services:\n  app:\n    restart: always\n    restart: no\n',
                  'services:\n  app: &shared\n    restart: always\n  copy: *shared\n',
                  'include: [oci://example.invalid/project]\nservices:\n  app:\n    restart: always\n']
        for text in variants:
            self.override.write_text(text);plan=self.plan();self.assertFalse(plan['allowed'])
        self.override.write_text(original);self.labels['com.docker.compose.config-hash']='e'*64
        self.assertFalse(self.plan()['allowed'])
        self.override.unlink();self.override.symlink_to(self.base)
        self.assertFalse(self.plan()['allowed']);self.assertEqual(self.docker.updates,[])

    def test_add_restart_to_last_override_without_editing_other_fields(self):
        self.override.write_text('services:\n  app:\n    ports:\n      - "127.0.0.1:8080:80"\n')
        ctx=self.editor.context(self.labels);self.labels['com.docker.compose.config-hash']=self.editor.run(ctx,ctx['files'],hash_service=True)
        old=self.override.read_text();plan=self.plan();self.assertTrue(plan['allowed'],plan['instructions'])
        self.assertIsNone(plan['compose']['source_before']);self.assertTrue(self.apply(plan)['ok'])
        self.assertEqual(self.override.read_text(),old.replace('    ports:', '    restart: "no"\n    ports:'))


class OrdinaryFolders(unittest.TestCase):
    def test_existing_empty_directory_is_not_a_verified_physical_filesystem(self):
        w=load('engine')
        with tempfile.TemporaryDirectory() as root:
            w.MOUNT=root;w.DISK_UUID='11111111-1111-4111-8111-111111111111'
            with patch.object(w,'read_rows',return_value=[]),patch.object(w,'device_number',return_value='240:17'):
                self.assertTrue(Path(root).is_dir())
                with self.assertRaisesRegex(w.Unsafe,'Expected mount is missing'):w.verify_main()


if __name__=='__main__':unittest.main()
