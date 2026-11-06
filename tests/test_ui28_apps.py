# SPDX-License-Identifier: MIT
"""Unified app editor with isolated files and synthetic Docker/service boundaries."""
import copy
import unittest
import tempfile
from unittest.mock import patch
from gui_fixture import load
from test_ui26_setup import Setup, IDENTITY

IMAGE='33333333-3333-4333-8333-333333333333'


class AppSettings(unittest.TestCase):
    def setUp(self):
        Setup.setUp(self)
        self.editor_app=load('app_settings');self.boot=load('boot_start')
        original=self.b.common.module
        self.f.main.patch(self.b.common,'module',lambda name,*args:self.editor_app if name=='app_settings' else self.boot if name=='boot_start' else original(name,*args))
        self.rows=[dict(id=IDENTITY,name='folder-app',state='running',discovered=True)]
        self.f.main.patch(self.web,'discover',lambda *_:(copy.deepcopy(self.rows),'v1.47'))
        self.docker.inspect=lambda identity:dict(id=self.docker.raw['Id'],name=self.docker.raw['Name'].lstrip('/'))
        c=self.b.configuration();c['images']=[dict(name='optional',uuid=IMAGE,mountpoint='/mnt/drive-a/optional',image='/mnt/drive-a/optional.img',enabled=False,fstab_options='loop,nodev,nosuid,noexec')]
        c['docker'].update(enabled=True,containers=[dict(name='folder-app',container_id=IDENTITY,source='',destination='',grace=30,images=[IMAGE])])
        self.b.cli.save(self.f.main.config,c)
        self.b.cli.save(self.boot.paths(self.b)[0],dict(version=1,containers=[dict(id=IDENTITY,name='folder-app',enabled=True,drives=[dict(id='legacy',images=[IMAGE])])]))
        self.docker.raw['HostConfig']['RestartPolicy']=dict(Name='no',MaximumRetryCount=0)

    def current(self):return self.editor_app.snapshot(self.b,self.web.records(self.fleet),self.rows)
    def desired(self):return copy.deepcopy(next(v for v in self.current()['settings'] if v['id']==IDENTITY))
    def review(self,desired):return self.editor_app.plan(self.fleet,dict(revision=self.current()['revision'],settings=desired),self.session)
    def commit(self,plan):return self.editor_app.save(self.fleet,dict(token=plan['token'],confirm=True),self.session)

    def test_off_retains_images_across_refresh_and_reenable_without_touching_boot(self):
        desired=self.desired();boot_before=self.boot.paths(self.b)[0].read_bytes()
        desired['recovery']['enabled']=False
        plan=self.review(desired);self.assertIsNone(plan['policy']);self.assertEqual(self.docker.updates,[])
        self.assertTrue(self.commit(plan)['ok'])
        self.assertEqual(self.desired(),desired);self.assertEqual(self.b.configuration()['docker']['containers'],[])
        self.assertEqual(self.boot.paths(self.b)[0].read_bytes(),boot_before)
        self.assertEqual(load('app_settings').snapshot(self.b,self.web.records(self.fleet),self.rows)['settings'],self.current()['settings'])
        desired['recovery']['enabled']=True
        self.assertTrue(self.commit(self.review(desired))['ok'])
        self.assertEqual(self.b.configuration()['docker']['containers'][0]['images'],[IMAGE])
        self.assertFalse(self.b.configuration()['images'][0]['enabled']);self.assertEqual(self.docker.updates,[])

    def test_off_on_restores_existing_grace_and_legacy_mapping_without_runtime_actions(self):
        c=self.b.configuration();spec=c['docker']['containers'][0]
        spec.update(grace=75,source='/mnt/drive-a/uploads',destination='/data')
        self.b.cli.save(self.f.main.config,c);original=copy.deepcopy(spec)
        desired=self.desired();desired['recovery']['enabled']=False
        self.assertTrue(self.commit(self.review(desired))['ok'])
        desired['recovery']['enabled']=True
        self.assertTrue(self.commit(self.review(desired))['ok'])
        self.assertEqual(self.b.configuration()['docker']['containers'][0],original)
        self.assertEqual(self.docker.updates,[])

    def test_failed_recovery_save_restores_private_choices_when_engine_unchanged(self):
        desired=self.desired();desired['recovery']['enabled']=False
        before=self.current();plan=self.review(desired)
        with patch.object(self.web,'save',side_effect=OSError('synthetic')):result=self.commit(plan)
        self.assertFalse(result['ok']);self.assertEqual(self.current(),before)

    def test_boot_off_retains_choices_without_changing_recovery_or_monitoring(self):
        old=[m.config.read_bytes() for m in (self.f.main,self.f.second)];desired=self.desired()
        self.f.main.active=False;self.f.second.active=False
        desired['boot']['enabled']=False
        self.assertTrue(self.commit(self.review(desired))['ok'])
        self.assertEqual(self.desired(),desired);self.assertEqual(old,[m.config.read_bytes() for m in (self.f.main,self.f.second)])
        self.assertFalse(self.f.main.active);self.assertFalse(self.f.second.active)

    def test_multiple_disks_optional_images_and_original_policy_preserved(self):
        self.docker.raw['HostConfig']['RestartPolicy']=dict(Name='unless-stopped',MaximumRetryCount=0)
        before=copy.deepcopy(self.docker.raw);desired=self.desired()
        desired['recovery']['drives']=[dict(id='legacy',images=[]),dict(id=self.other,images=[])]
        plan=self.review(desired);self.assertEqual(self.docker.updates,[]);self.assertTrue(plan['policy']['live_change'])
        self.assertTrue(self.commit(plan)['ok'])
        for m in (self.f.main,self.f.second):self.assertEqual(m.b.configuration()['docker']['containers'][0]['images'],[])
        expected=copy.deepcopy(before);expected['HostConfig']['RestartPolicy']=dict(Name='no',MaximumRetryCount=0)
        self.assertEqual(self.docker.raw,expected);self.assertEqual(self.desired()['boot']['drives'],[dict(id='legacy',images=[IMAGE])])

    def test_noop_and_missing_prerequisite_review_refused_without_changes(self):
        with self.assertRaisesRegex(ValueError,'No settings changed'):self.review(self.desired())
        desired=self.desired();desired['boot']['drives']=[]
        with self.assertRaises(ValueError):self.review(desired)
        self.assertEqual(self.docker.updates,[])

    def test_exact_identity_stale_revision_and_authentication(self):
        desired=self.desired();desired['boot']['drives'][0]['images']=[]
        plan=self.review(desired);self.docker.raw['Id']='d'*64
        result=self.commit(plan);self.assertFalse(result['ok']);self.assertEqual(self.docker.updates,[])
        self.docker.raw['Id']=IDENTITY;plan=self.review(desired)
        c=self.b.configuration();c['disk']['label']='Changed elsewhere';self.b.cli.save(self.f.main.config,c)
        with self.assertRaisesRegex(ValueError,'changed after review'):self.commit(plan)
        for action in ('docker-app-plan','docker-app-save'):
            response=self.f.main.broker.handle(dict(action=action,write=True,data={}))
            self.assertEqual(response['status'],401)
        response=self.f.request('docker-app-plan',dict(revision=self.current()['revision'],settings=desired),profile=None)
        self.assertEqual(response['status'],200,response)
        response=self.f.request('docker-app-save',dict(token=response['data']['token'],confirm=True),profile=None)
        self.assertEqual(response['status'],200,response);self.assertTrue(response['data']['ok'],response)

    def test_new_routes_reject_csrf_and_unreviewed_file_arguments(self):
        for action in ('docker-app-plan','docker-app-save'):
            result=self.f.main.broker.handle(dict(action=action,write=True,data={},token=self.f.session['token'],csrf='wrong'))
            self.assertEqual(result['status'],401)
        desired=self.desired();desired['boot']['enabled']=False
        result=self.f.request('docker-app-plan',dict(revision=self.current()['revision'],settings=desired,path='/etc/passwd'),profile=None)
        self.assertEqual(result['status'],400)
        self.assertEqual(self.docker.updates,[])

    def test_partial_failure_reports_verified_policy_and_preserves_unsaved_boot(self):
        desired=self.desired();desired['boot']['drives'][0]['images']=[]
        self.docker.raw['HostConfig']['RestartPolicy']=dict(Name='always',MaximumRetryCount=0)
        plan=self.review(desired);before=self.boot.paths(self.b)[0].read_bytes()
        with patch.object(self.boot,'update',side_effect=OSError('private host failure')):result=self.commit(plan)
        self.assertFalse(result['ok']);self.assertIn('Docker startup policy verified',result['applied'][0])
        self.assertIn('Computer startup was not confirmed',result['message']);self.assertNotIn('private host failure',str(result))
        self.assertEqual(before,self.boot.paths(self.b)[0].read_bytes());self.assertEqual(len(self.docker.updates),1)
        with self.assertRaises(ValueError):self.commit(plan)

    def test_policy_failure_does_not_write_storage_settings(self):
        desired=self.desired();desired['recovery']['drives'][0]['images']=[]
        self.docker.raw['HostConfig']['RestartPolicy']=dict(Name='always',MaximumRetryCount=0);self.docker.failure='refused'
        plan=self.review(desired);before=[m.config.read_bytes() for m in (self.f.main,self.f.second)]
        result=self.commit(plan);self.assertFalse(result['ok']);self.assertEqual(result['applied'],[])
        self.assertEqual(before,[m.config.read_bytes() for m in (self.f.main,self.f.second)])

    def test_portainer_instructions_prevent_claiming_source_updated_but_off_allowed(self):
        self.docker.raw['Config']['Labels']={'io.portainer.stack.name':'example'}
        desired=self.desired();desired['boot']['drives'][0]['images']=[]
        plan=self.review(desired);self.assertFalse(plan['allowed']);self.assertIn('Portainer',str(plan['policy']['instructions']))
        with self.assertRaises(ValueError):self.commit(plan)
        desired=self.desired();desired['boot']['enabled']=False;desired['recovery']['enabled']=False
        self.assertTrue(self.commit(self.review(desired))['ok']);self.assertEqual(self.docker.updates,[])

    def test_unrelated_disabled_choices_are_preserved_on_off_and_ambiguous_enable_refused(self):
        c=self.b.configuration();other=dict(name='other',container_id='e'*64,source='',destination='',grace=30,images=[])
        c['docker']['containers'].append(other);c['docker']['enabled']=False;self.b.cli.save(self.f.main.config,c)
        desired=self.desired();desired['recovery']['enabled']=True
        with self.assertRaisesRegex(ValueError,'other saved apps'):self.review(desired)
        self.assertEqual(self.b.configuration()['docker']['containers'][-1],other)
        # The original endpoint must also keep other disabled choices.
        self.web.save(self.fleet,dict(id=IDENTITY,name='folder-app',revision=self.web.revision(self.web.records(self.fleet)),drives=[dict(id=i,enabled=False,images=[]) for i,_ in self.web.records(self.fleet)]))
        self.assertEqual(self.b.configuration()['docker']['containers'],[other]);self.assertFalse(self.b.configuration()['docker']['enabled'])

    def test_missing_disabled_boot_image_is_retained_when_turning_off(self):
        c=self.b.configuration();c['images']=[];c['docker']['containers'][0]['images']=[];self.b.cli.save(self.f.main.config,c)
        desired=self.desired();desired['boot']['enabled']=False
        self.assertTrue(self.commit(self.review(desired))['ok']);self.assertEqual(self.desired()['boot']['drives'][0]['images'],[IMAGE])

    def test_monitoring_and_mount_readiness_are_exposed_without_actions(self):
        self.f.main.active=False;c=self.b.configuration();c['recovery']['mount']=False;self.b.cli.save(self.f.main.config,c)
        result=self.web.overview(self.fleet);drive=next(d for d in result['drives'] if d['id']=='legacy')
        self.assertFalse(drive['monitoring']);self.assertFalse(drive['automatic_mount']);self.assertEqual(drive['mountpoint'],'/mnt/drive-a')
        self.assertFalse(self.f.main.active)

    def test_combined_review_uses_validated_compose_source_and_private_backup(self):
        try:self.editor.binary()
        except self.editor.Unavailable:self.skipTest('System Compose plugin unavailable')
        with tempfile.TemporaryDirectory(prefix='usw-app-compose-') as directory:
            from pathlib import Path
            project=Path(directory);source=project/'compose.yaml'
            text='services:\n  app:\n    image: example.invalid/fixed\n    restart: always\n  unrelated:\n    image: example.invalid/other\n    restart: unless-stopped\n'
            source.write_text(text);source.chmod(0o600)
            labels={'com.docker.compose.project':'synthetic','com.docker.compose.service':'app','com.docker.compose.project.working_dir':str(project),'com.docker.compose.project.config_files':str(source)}
            ctx=self.editor.context(labels);labels['com.docker.compose.config-hash']=self.editor.run(ctx,ctx['files'],hash_service=True)
            self.docker.raw['Config']['Labels']=labels
            desired=self.desired();desired['boot']['drives'][0]['images']=[]
            plan=self.review(desired);self.assertTrue(plan['policy']['compose']['changes']);self.assertEqual(source.read_text(),text)
            result=self.commit(plan);self.assertTrue(result['ok'],result)
            self.assertEqual(source.read_text(),text.replace('restart: always','restart: "no"'))
            record=self.m.read(self.b,IDENTITY);self.assertEqual(record['phase'],'verified')
            backup=Path(record['backups'][0]['backup']);self.assertEqual(backup.read_text(),text);self.assertEqual(backup.stat().st_mode&0o777,0o600)
            self.assertEqual(self.docker.updates,[])

    def test_missing_container_can_be_disabled_without_docker_or_losing_choices(self):
        desired=self.desired();desired['boot']['enabled']=False;desired['recovery']['enabled']=False
        with patch.object(self.web,'client',side_effect=AssertionError('Docker should not be used')):
            result=self.commit(self.review(desired))
        self.assertTrue(result['ok']);self.assertEqual(self.desired(),desired)

    def test_remembered_missing_id_does_not_transfer_to_same_name_replacement(self):
        desired=self.desired();desired['recovery']['enabled']=False;desired['boot']['enabled']=False
        self.assertTrue(self.commit(self.review(desired))['ok'])
        self.rows=[dict(id='d'*64,name='folder-app',discovered=True)]
        result=self.web.overview(self.fleet)['applications']['settings']
        old=next(v for v in result if v['id']==IDENTITY);new=next(v for v in result if v['id']=='d'*64)
        self.assertEqual(old['recovery']['drives'],desired['recovery']['drives']);self.assertEqual(new['recovery']['drives'],[])


if __name__=='__main__':unittest.main()
