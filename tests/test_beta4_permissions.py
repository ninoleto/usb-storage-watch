"""Real private permissions/Compose config; simulated accounts, Docker and services."""
import copy
import fcntl
import grp
import json
import os
from pathlib import Path
import pwd
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_ui28_apps as prior
from test_ui26_setup import IDENTITY

class Fixture:
    current=prior.AppSettings.current
    desired=prior.AppSettings.desired
    review=prior.AppSettings.review
    commit=prior.AppSettings.commit

    def setUp(self):
        prior.AppSettings.setUp(self)
        self.tmp=tempfile.TemporaryDirectory(prefix='usw-permissions-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.project=self.root/'project';self.project.mkdir(mode=0o755)
        self.source=self.project/'compose.yaml';self.environment=self.project/'.env'
        self.media=self.project/'shared-media';self.media.mkdir(mode=0o775)
        self.data=self.media/'existing.txt';self.data.write_bytes(b'Preserve media contents');self.data.chmod(0o664)
        self.source.write_text('services:\n  app:\n    image: example.invalid/erugo:fixed\n    restart: unless-stopped\n    environment:\n      PRIVATE: ${PRIVATE}\n    volumes:\n      - /mnt/external/uploads:/data\n  unrelated:\n    image: example.invalid/other:fixed\n    restart: always\n')
        self.environment.write_text('PRIVATE=DO-NOT-EXPOSE-ENV-CONTENTS\n')
        self.source.chmod(0o644);self.environment.chmod(0o600)
        account=self.editor.pwd.getpwuid(os.getuid());self.owner=account.pw_uid;self.gid=self.source.stat().st_gid
        self.reader=SimpleNamespace(pw_uid=self.owner+123,pw_name='media-reader',pw_gid=self.gid,pw_dir=str(self.root))
        self.account=SimpleNamespace(pw_uid=self.owner,pw_name='fixture-owner',pw_gid=self.gid,pw_dir=str(self.project))
        self.members=[self.account,self.reader]
        self.f.main.patch(self.editor,'pwd',SimpleNamespace(getpwuid=lambda uid:self.account if uid==self.owner else self.reader,
            getpwnam=lambda name:next(p for p in self.members if p.pw_name==name),getpwall=lambda:self.members))
        self.f.main.patch(self.editor,'grp',SimpleNamespace(getgrgid=lambda gid:SimpleNamespace(gr_name='fixture-shared',gr_mem=['media-reader'],gr_gid=gid)))
        # The plugin only renders private configuration; no Docker daemon access.
        self.editor.binary()
        self.labels={'com.docker.compose.project':'synthetic','com.docker.compose.service':'app',
                     'com.docker.compose.project.working_dir':str(self.project),
                     'com.docker.compose.project.config_files':str(self.source)}
        self.rehash()
        c=self.b.configuration();c['docker'].update(enabled=False,containers=[]);self.b.cli.save(self.f.main.config,c)
        self.b.cli.save(self.boot.paths(self.b)[0],dict(version=1,containers=[]))
        self.docker.raw['HostConfig']['RestartPolicy']=dict(Name='unless-stopped',MaximumRetryCount=0)

    def rehash(self):
        ctx=self.editor.context(self.labels)
        self.labels['com.docker.compose.config-hash']=self.editor.run(ctx,ctx['files'],hash_service=True)
        self.docker.raw['Config']['Labels']=copy.deepcopy(self.labels)

    def intent(self):
        desired=self.desired()
        for key in ('boot','recovery'):desired[key]=dict(enabled=True,drives=[dict(id='legacy',images=[])])
        return desired

    def permission_review(self,plan,index=0):
        return self.m.permission_plan(self.fleet,dict(id=IDENTITY,name='folder-app',token=plan['policy']['token'],index=index),self.session)

    def permission_apply(self,review):
        return self.m.permission_apply(self.fleet,dict(id=IDENTITY,name='folder-app',token=review['token'],confirm=True),self.session)

    def media_snapshot(self):
        return [(str(p),p.stat().st_uid,p.stat().st_gid,stat.S_IMODE(p.stat().st_mode),p.read_bytes() if p.is_file() else None)
                for p in (self.root,self.project,self.media,self.data)]


class Permissions(Fixture,unittest.TestCase):
    def test_erugo_shared_file_explicit_review_then_normal_setup(self):
        self.source.chmod(0o664);before=self.media_snapshot();contents=self.source.read_bytes();settings=self.current()
        plan=self.review(self.intent());self.assertFalse(plan['allowed'])
        issue=plan['policy']['diagnostics'][0]
        self.assertEqual((issue['path'],issue['role'],issue['type'],issue['mode']),(str(self.source),'compose_file','file','0664'))
        self.assertEqual(issue['affected_users'],['media-reader']);self.assertEqual(issue['group']['name'],'fixture-shared')
        self.assertEqual(issue['owner']['name'],'fixture-owner');self.assertTrue(issue['adjustable'])
        self.assertNotIn('DO-NOT-EXPOSE',json.dumps(plan));self.assertNotIn('docker update',json.dumps(plan))
        with self.assertRaises(ValueError):self.commit(plan)
        self.assertEqual(self.current(),settings);self.assertEqual(self.source.stat().st_mode&0o777,0o664)
        review=self.permission_review(plan);self.assertEqual(review['path']['proposed_mode'],'0644')
        self.assertEqual(self.docker.updates,[]);self.assertEqual(self.source.stat().st_mode&0o777,0o664)
        raw=copy.deepcopy(self.docker.raw);result=self.permission_apply(review)
        self.assertTrue(result['ok']);self.assertFalse(result['settings_saved']);self.assertTrue(result['review']['allowed'])
        self.assertEqual(self.source.stat().st_mode&0o777,0o644);self.assertEqual(self.source.read_bytes(),contents)
        self.assertEqual(self.current(),settings);self.assertEqual(self.media_snapshot(),before);self.assertEqual(self.docker.raw,raw)
        record=next(self.m.directory(self.b,IDENTITY).glob('permissions-*.json'))
        self.assertEqual(record.stat().st_mode&0o777,0o600);self.assertEqual(json.loads(record.read_text())['targets'][0]['mode'],'0664')
        with self.assertRaises(ValueError):self.permission_apply(review)
        saved=self.commit(self.review(self.intent()));self.assertTrue(saved['ok'],saved)
        self.assertEqual(self.current()['configured'][IDENTITY],dict(boot=True,recovery=True))
        self.assertEqual(self.current()['settings'][0]['boot']['drives'][0]['images'],[])
        self.assertEqual(self.docker.raw['HostConfig']['RestartPolicy']['Name'],'no')
        self.assertIn('restart: always',self.source.read_text());self.assertEqual(self.media_snapshot(),before)

    def test_unsafe_ancestor_directory_refused(self):
        self.source.write_text('services:\n  app:\n    image: example.invalid/immich:fixed\n    restart: always\n    depends_on:\n      database: {condition: service_started}\n      redis: {condition: service_started}\n  database:\n    image: example.invalid/postgres:fixed\n  redis:\n    image: example.invalid/redis:fixed\n')
        self.rehash()
        for folder,role in ((self.root,'parent_directory'),):
            original=folder.stat().st_mode&0o777;folder.chmod(0o775);before=self.media_snapshot()
            plan=self.review(self.intent());self.assertFalse(plan['allowed']);issue=plan['policy']['diagnostics'][0]
            self.assertEqual((issue['path'],issue['role'],issue['type']),(str(folder),role,'directory'))
            self.assertFalse(issue['adjustable']);self.assertIn('separate owner review',issue['limitation'])
            with self.assertRaises(ValueError):self.permission_review(plan)
            self.assertEqual(before,self.media_snapshot());self.assertEqual(self.docker.updates,[])
            folder.chmod(original)  # Fixture owner resolves it; the application never does.
        self.assertTrue(self.commit(self.review(self.intent()))['ok'])

    def test_photoprism_environment_file_no_content_exposure(self):
        self.source.write_text('services:\n  app:\n    image: example.invalid/photoprism:fixed\n    restart: unless-stopped\n    env_file: ./settings.env\n    volumes:\n      - /mnt/external/photos:/photoprism/originals\n      - ./ssd:/photoprism/storage\n')
        env=self.project/'settings.env';env.write_text('SECRET=DO-NOT-EXPOSE-ENV-CONTENTS\n');env.chmod(0o644);self.rehash();env.chmod(0o664)
        plan=self.review(self.intent());issue=plan['policy']['diagnostics'][0]
        self.assertEqual(issue['path'],str(env));self.assertEqual(issue['role'],'environment_file')
        self.assertNotIn('DO-NOT-EXPOSE',json.dumps(plan));data=env.read_bytes()
        result=self.permission_apply(self.permission_review(plan));self.assertTrue(result['ok'])
        self.assertEqual(env.read_bytes(),data);self.assertEqual(env.stat().st_mode&0o777,0o644)
        self.assertTrue(self.commit(self.review(self.intent()))['ok'])

    def test_stale_file_membership_inode_and_parent_refuse_without_mutation(self):
        self.source.chmod(0o664)
        for change in ('contents','mode','inode','membership','parent'):
            plan=self.review(self.intent());review=self.permission_review(plan)
            if change=='contents':self.source.write_text(self.source.read_text()+'# changed\n')
            if change=='mode':self.source.chmod(0o666)
            if change=='inode':
                contents=self.source.read_bytes();self.source.rename(self.project/'old.yaml');self.source.write_bytes(contents);self.source.chmod(0o664)
            if change=='membership':self.members.append(SimpleNamespace(pw_uid=self.owner+124,pw_name='new-member',pw_gid=self.gid))
            if change=='parent':self.project.chmod(0o775)
            before=self.source.stat().st_mode
            with self.assertRaises(ValueError):self.permission_apply(review)
            self.assertEqual(self.source.stat().st_mode,before);self.assertEqual(self.docker.updates,[])
            self.project.chmod(0o755);self.source.chmod(0o664)

    def test_bind_media_acl_hardlink_and_special_bits_not_adjustable(self):
        self.source.chmod(0o664)
        for case in ('bind','acl','hardlink','special'):
            with self.subTest(case=case):
                original=copy.deepcopy(self.docker.raw['Mounts'])
                if case=='bind':self.docker.raw['Mounts']=[dict(Type='bind',Source=str(self.project),Destination='/app')]
                if case=='hardlink':os.link(self.source,self.project/'second-link')
                if case=='special':self.source.chmod(0o2664)
                with patch.object(self.editor,'access_acl',return_value='present' if case=='acl' else 'none'):
                    plan=self.review(self.intent());self.assertFalse(plan['policy']['diagnostics'][0]['adjustable'])
                    with self.assertRaises(ValueError):self.permission_review(plan)
                self.docker.raw['Mounts']=original
                if case=='hardlink':(self.project/'second-link').unlink()
                self.source.chmod(0o664)

    def test_recovery_lock_identity_and_stale_confirmation_enforced(self):
        self.source.chmod(0o664);review=self.permission_review(self.review(self.intent()))
        control=self.b.common.module('app_control')
        original=self.b.common.module
        with patch.object(control,'require_idle',side_effect=ValueError('Recovery in progress.')),patch.object(self.b.common,'module',side_effect=lambda name,*a:control if name=='app_control' else original(name,*a)):
            with self.assertRaisesRegex(ValueError,'Recovery in progress'):self.permission_apply(review)
        self.assertEqual(self.source.stat().st_mode&0o777,0o664)
        review=self.permission_review(self.review(self.intent()));self.docker.raw['Id']='d'*64
        with self.assertRaises(ValueError):self.permission_apply(review)
        self.assertEqual(self.source.stat().st_mode&0o777,0o664);self.assertEqual(self.docker.updates,[])

    def test_broker_auth_csrf_and_unreviewed_path_rejected(self):
        self.source.chmod(0o664)
        for action in ('docker-permission-plan','docker-permission-apply'):
            self.assertEqual(self.f.main.broker.handle(dict(action=action,write=True,data={}))['status'],401)
            self.assertEqual(self.f.main.broker.handle(dict(action=action,write=True,data={},token=self.f.session['token'],csrf='wrong'))['status'],401)
        p=self.f.request('docker-app-plan',dict(revision=self.current()['revision'],settings=self.intent()),profile=None)
        self.assertEqual(p['status'],200,p)
        target=dict(id=IDENTITY,name='folder-app',token=p['data']['policy']['token'],index=0)
        bad=self.f.request('docker-permission-plan',dict(target,path='/etc/passwd'),profile=None);self.assertEqual(bad['status'],400)
        p=self.f.request('docker-permission-plan',target,profile=None);self.assertEqual(p['status'],200,p)
        data=dict(id=IDENTITY,name='folder-app',token=p['data']['token'],confirm=True)
        self.assertEqual(self.f.request('docker-permission-apply',dict(data,mode=0o777),profile=None)['status'],400)
        result=self.f.request('docker-permission-apply',data,profile=None);self.assertEqual(result['status'],200,result)
        self.assertTrue(result['data']['ok']);self.assertEqual(self.docker.updates,[])

    def test_chmod_failure_and_readback_failure_leave_original_permissions(self):
        self.source.chmod(0o664);inode=self.source.stat().st_ino;real_chmod=os.fchmod
        review=self.permission_review(self.review(self.intent()))
        def fail(fd,mode):
            if os.fstat(fd).st_ino==inode:raise PermissionError('DO-NOT-EXPOSE private OS error')
            real_chmod(fd,mode)
        with patch.object(self.editor.os,'fchmod',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'original permissions are unchanged'):self.permission_apply(review)
        self.assertEqual(self.source.stat().st_mode&0o777,0o664);self.assertEqual(self.docker.updates,[])
        review=self.permission_review(self.review(self.intent()));original=self.editor.path_issues
        def changed(path,*args,**kwargs):
            if Path(path)==self.source and self.source.stat().st_mode&0o777==0o644:return [{'synthetic':'readback failure'}]
            return original(path,*args,**kwargs)
        with patch.object(self.editor,'path_issues',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'original mode was restored'):self.permission_apply(review)
        self.assertEqual(self.source.stat().st_mode&0o777,0o664);self.assertEqual(self.docker.updates,[])

    def test_remaining_compose_conflict_is_not_reported_as_completed_setup(self):
        self.source.chmod(0o664);self.docker.raw['Config']['Labels']['com.docker.compose.config-hash']='e'*64
        before=self.current();result=self.permission_apply(self.permission_review(self.review(self.intent())))
        self.assertTrue(result['ok']);self.assertFalse(result['settings_saved']);self.assertFalse(result['review']['allowed'])
        self.assertIn('remaining',result['message']);self.assertEqual(self.current(),before);self.assertEqual(self.docker.updates,[])
        self.assertEqual(self.source.stat().st_mode&0o777,0o644)

    def test_competing_app_lock_rejects_without_changing_file(self):
        self.source.chmod(0o664);review=self.permission_review(self.review(self.intent()))
        directory=self.b.cli.drives.roots(self.b.s)[1]/'shared-locks';directory.mkdir(exist_ok=True)
        with (directory/('docker-restart-'+IDENTITY+'.lock')).open('a') as fd:
            os.fchmod(fd.fileno(),0o600)
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError,'Another operation'):self.permission_apply(review)
        self.assertEqual(self.source.stat().st_mode&0o777,0o664);self.assertEqual(self.docker.updates,[])

    def test_missing_file_unknown_membership_and_partial_save_remain_honest(self):
        self.source.rename(self.project/'saved.yaml')
        plan=self.review(self.intent());issue=plan['policy']['diagnostics'][0]
        self.assertEqual(issue['path'],str(self.source));self.assertEqual(issue['type'],'unknown')
        self.assertIsNone(issue['mode']);self.assertFalse(issue['adjustable'])
        (self.project/'saved.yaml').rename(self.source);self.source.chmod(0o664)
        with patch.object(self.editor.grp,'getgrgid',side_effect=KeyError('private NSS error')):
            plan=self.review(self.intent());issue=plan['policy']['diagnostics'][0]
            self.assertFalse(issue['group']['known']);self.assertFalse(issue['adjustable'])
        self.source.chmod(0o644);plan=self.review(self.intent())
        with patch.object(self.boot,'update',side_effect=OSError('DO-NOT-EXPOSE')):
            result=self.commit(plan)
        self.assertFalse(result['ok']);self.assertEqual(self.current()['configured'][IDENTITY],dict(boot=False,recovery=True))
        self.assertFalse(self.desired()['boot']['enabled']);self.assertTrue(self.desired()['recovery']['enabled'])
        self.assertNotIn('DO-NOT-EXPOSE',str(result))

    def test_multiple_inputs_reviewed_individually_without_adding_read_access(self):
        self.source.chmod(0o664);self.environment.chmod(0o660);data=self.environment.read_bytes()
        plan=self.review(self.intent());issues=plan['policy']['diagnostics']
        self.assertEqual([i['role'] for i in issues],['compose_file','environment_file'])
        self.assertEqual(issues[1]['proposed_mode'],'0640')
        result=self.permission_apply(self.permission_review(plan,index=1))
        self.assertTrue(result['ok']);self.assertFalse(result['review']['allowed'])
        self.assertEqual(self.environment.stat().st_mode&0o777,0o640);self.assertEqual(self.environment.read_bytes(),data)
        self.assertEqual(self.source.stat().st_mode&0o777,0o664)
        result=self.permission_apply(self.permission_review(self.review(self.intent())))
        self.assertTrue(result['review']['allowed']);self.assertEqual(self.docker.updates,[])

    def test_change_during_private_record_write_is_rechecked_before_chmod(self):
        self.source.chmod(0o664);review=self.permission_review(self.review(self.intent()))
        original=self.b.w.atomic_write
        def race(path,text,*a,**kw):
            result=original(path,text,*a,**kw)
            if Path(path).name.startswith('permissions-'):self.source.chmod(0o666)
            return result
        with patch.object(self.b.w,'atomic_write',side_effect=race):
            with self.assertRaisesRegex(ValueError,'changed before applying'):self.permission_apply(review)
        self.assertEqual(self.source.stat().st_mode&0o777,0o666);self.assertEqual(self.docker.updates,[])

    def test_open_denial_reports_path_without_promising_a_mode_fix(self):
        original=os.open
        def denied(path,*args,**kwargs):
            if Path(path)==self.source:raise PermissionError('DO-NOT-EXPOSE OS error')
            return original(path,*args,**kwargs)
        with patch.object(self.editor.os,'open',side_effect=denied):plan=self.review(self.intent())
        issue=plan['policy']['diagnostics'][0]
        self.assertEqual(issue['path'],str(self.source));self.assertEqual(issue['problem'],'read_failed')
        self.assertEqual(issue['mode'],'0644');self.assertFalse(issue['adjustable'])
        self.assertNotIn('DO-NOT-EXPOSE',str(plan));self.assertEqual(self.docker.updates,[])

    def test_uncertain_owner_change_does_not_blindly_restore_permissions(self):
        self.source.chmod(0o664);inode=self.source.stat().st_ino;review=self.permission_review(self.review(self.intent()))
        original=os.fstat;chmod=os.fchmod;writes=[]
        def changed(fd):
            info=original(fd)
            if info.st_ino==inode and stat.S_IMODE(info.st_mode)==0o644:
                values=list(info);values[stat.ST_UID]=self.owner+1
                return os.stat_result(values)
            return info
        def tracked(fd,mode):
            if original(fd).st_ino==inode:writes.append(mode)
            return chmod(fd,mode)
        with patch.object(self.editor.os,'fstat',side_effect=changed),patch.object(self.editor.os,'fchmod',side_effect=tracked):
            with self.assertRaisesRegex(ValueError,'outcome needs administrator review'):self.permission_apply(review)
        self.assertEqual(writes,[0o644]);self.assertEqual(self.docker.updates,[])

if __name__=='__main__':unittest.main()
