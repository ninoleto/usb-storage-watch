"""Reviewed project access: real temporary files/Compose, synthetic Docker/accounts."""
import copy,fcntl,json,os,stat,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from test_beta4_permissions import Fixture,IDENTITY

class Access(Fixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.account.pw_dir=str(self.root);self.reader.pw_name='plex'
        self.f.main.patch(self.editor,'grp',SimpleNamespace(getgrgid=lambda gid:SimpleNamespace(gr_name='shared-project',gr_mem=['plex'],gr_gid=gid)))
        self.source.write_text('services:\n  app:\n    image: example.invalid/photoprism:fixed\n    restart: unless-stopped\n    volumes:\n      - ./shared-media:/photoprism/storage\n      - /mnt/external/photos:/photoprism/originals\n')
        self.rehash()
        self.docker.raw['Mounts']=[dict(Type='bind',Source=str(self.media),Destination='/photoprism/storage',RW=True)]

    def reviewed_access(self,plan=None):
        plan=plan or self.review(self.intent())
        return self.m.permission_plan(self.fleet,dict(id=IDENTITY,name='folder-app',token=plan['policy']['token']),self.session)

    def children(self):return [(p.stat().st_uid,p.stat().st_gid,p.stat().st_mode,p.read_bytes() if p.is_file() else None) for p in (self.media,self.data)]

    def writable(self):self.project.chmod(0o775);self.source.chmod(0o664)

    def test_photoprism_directory_and_compose_one_review_then_save(self):
        self.writable();children=self.children();settings=self.current();raw=copy.deepcopy(self.docker.raw)
        plan=self.review(self.intent());self.assertFalse(plan['allowed']);review=self.reviewed_access(plan)
        self.assertEqual([(v['path'],v['mode'],v['proposed_mode']) for v in review['paths']],[(str(self.project),'0775','0755'),(str(self.source),'0664','0644')])
        self.assertEqual(review['paths'][0]['affected_users'],['plex'])
        self.assertEqual(review['paths'][0]['child_data'],[dict(app='folder-app',path=str(self.media))])
        self.assertIn('create, delete or rename',review['message']);self.assertIn('Native services',review['message'])
        self.assertEqual(self.project.stat().st_mode&0o777,0o775);self.assertEqual(self.source.stat().st_mode&0o777,0o664)
        with self.assertRaises(ValueError):self.commit(plan)
        result=self.permission_apply(review);self.assertTrue(result['ok']);self.assertTrue(result['review']['allowed'])
        self.assertEqual((self.project.stat().st_mode&0o777,self.source.stat().st_mode&0o777),(0o755,0o644))
        self.assertEqual(self.children(),children);self.assertEqual(self.current(),settings);self.assertEqual(self.docker.raw,raw)
        record=json.loads(next(self.m.directory(self.b,IDENTITY).glob('permissions-*.json')).read_text())
        self.assertEqual(record['phase'],'verified');self.assertEqual(len(record['targets']),2)
        self.assertTrue(self.commit(self.review(self.intent()))['ok']);self.assertEqual(len(self.docker.updates),1)
        self.assertEqual(self.children(),children)

    def test_immich_directory_env_and_compose_setgid_read_traverse_preserved(self):
        self.source.write_text('services:\n  app:\n    image: example.invalid/immich:fixed\n    restart: always\n    environment:\n      PRIVATE: ${PRIVATE}\n    volumes:\n      - ./shared-media:/data\n    depends_on:\n      - database\n  database:\n    image: example.invalid/database:fixed\n    restart: always\n')
        self.rehash();self.project.chmod(0o2770);self.source.chmod(0o660);self.environment.chmod(0o660)
        children=self.children();review=self.reviewed_access()
        self.assertEqual([v['proposed_mode'] for v in review['paths']],['2750','0640','0640'])
        self.assertTrue(self.permission_apply(review)['ok']);self.assertEqual(self.project.stat().st_mode&0o7777,0o2750)
        self.assertTrue(self.commit(self.review(self.intent()))['ok']);self.assertEqual(self.children(),children)
        self.assertIn('    restart: always',self.source.read_text()) # unrelated database preserved

    def test_remove_only_necessary_write_bits(self):
        self.members.remove(self.reader);self.f.main.patch(self.editor,'grp',SimpleNamespace(getgrgid=lambda gid:SimpleNamespace(gr_name='owner-only',gr_mem=[],gr_gid=gid)))
        self.project.chmod(0o777);self.source.chmod(0o666)
        review=self.reviewed_access();self.assertEqual([v['proposed_mode'] for v in review['paths']],['0775','0664'])
        self.assertTrue(self.permission_apply(review)['ok'])
        self.assertEqual(self.project.stat().st_mode&0o777,0o775);self.assertEqual(self.source.stat().st_mode&0o777,0o664)

    def test_unsafe_ancestor_refused_without_changing_children(self):
        self.writable();self.root.chmod(0o775);before=self.media_snapshot()
        plan=self.review(self.intent());self.assertFalse(any(v['adjustable'] for v in plan['policy']['diagnostics']))
        with self.assertRaises(ValueError):self.reviewed_access(plan)
        self.assertEqual(self.media_snapshot(),before);self.assertEqual(self.docker.updates,[])

    def test_shared_project_mount_and_other_app_mount_refused(self):
        self.writable();original=self.docker.request
        other=copy.deepcopy(self.docker.raw);other.update(Id='d'*64,Name='/other-app',Mounts=[dict(Type='bind',Source=str(self.project),Destination='/data')])
        def request(method,path,*args,**kw):
            if path=='/containers/json?all=1':return [dict(Id=IDENTITY),dict(Id=other['Id'])]
            if path=='/containers/'+other['Id']+'/json':return copy.deepcopy(other)
            return original(method,path,*args,**kw)
        with patch.object(self.docker,'request',side_effect=request):
            plan=self.review(self.intent());self.assertFalse(any(v['adjustable'] for v in plan['policy']['diagnostics']))
            self.assertIn('other-app',plan['policy']['diagnostics'][0]['limitation'])
            with self.assertRaises(ValueError):self.reviewed_access(plan)
        self.assertEqual(self.project.stat().st_mode&0o777,0o775);self.assertEqual(self.docker.updates,[])

    def test_stale_directory_file_membership_data_and_mounts(self):
        for change in ('directory','file','membership','child','mount'):
            with self.subTest(change=change):
                self.writable();review=self.reviewed_access();mounts=copy.deepcopy(self.docker.raw['Mounts'])
                if change=='directory':self.project.chmod(0o777)
                elif change=='file':self.source.write_text(self.source.read_text()+'# changed\n')
                elif change=='membership':self.members.append(SimpleNamespace(pw_uid=self.owner+400,pw_name='new-writer',pw_gid=self.gid))
                elif change=='child':self.media.chmod(0o777)
                else:self.docker.raw['Mounts'].append(dict(Type='bind',Source=str(self.project),Destination='/all'))
                before=(self.project.stat().st_mode,self.source.stat().st_mode)
                with self.assertRaises(ValueError):self.permission_apply(review)
                self.assertEqual((self.project.stat().st_mode,self.source.stat().st_mode),before);self.assertEqual(self.docker.updates,[])
                self.docker.raw['Mounts']=mounts

    def test_partial_failure_restores_exact_paths_and_reports_each(self):
        self.writable();review=self.reviewed_access();real=os.fchmod;source=self.source.stat().st_ino;children=self.children()
        def fail(fd,mode):
            if os.fstat(fd).st_ino==source:raise PermissionError('DO-NOT-EXPOSE')
            real(fd,mode)
        with patch.object(self.editor.os,'fchmod',side_effect=fail):result=self.permission_apply(review)
        self.assertFalse(result['ok']);self.assertEqual([v['status'] for v in result['outcomes']],['restored','unchanged'])
        self.assertNotIn('DO-NOT-EXPOSE',str(result));self.assertEqual(self.children(),children)
        self.assertEqual((self.project.stat().st_mode&0o777,self.source.stat().st_mode&0o777),(0o775,0o664));self.assertEqual(self.docker.updates,[])
        with self.assertRaises(ValueError):self.permission_apply(review)

    def test_partial_failure_unknown_rollback_reported_without_replay(self):
        self.writable();review=self.reviewed_access();real=os.fchmod;source=self.source.stat().st_ino;calls=[]
        def fail(fd,mode):
            if os.fstat(fd).st_ino in (source,self.project.stat().st_ino):calls.append((os.fstat(fd).st_ino,mode))
            if os.fstat(fd).st_ino==source or mode==0o775:raise PermissionError('synthetic')
            real(fd,mode)
        with patch.object(self.editor.os,'fchmod',side_effect=fail):result=self.permission_apply(review)
        self.assertFalse(result['ok']);self.assertEqual([v['status'] for v in result['outcomes']],['uncertain','unchanged'])
        self.assertEqual(self.project.stat().st_mode&0o777,0o755);self.assertEqual(len(calls),3);self.assertEqual(self.docker.updates,[])

    def test_missing_inventory_or_shared_data_no_guess(self):
        self.writable();original=self.docker.request
        with patch.object(self.docker,'request',side_effect=lambda method,path,*a,**kw: [] if path=='/containers/json?all=1' else original(method,path,*a,**kw)):
            plan=self.review(self.intent());self.assertFalse(any(v['adjustable'] for v in plan['policy']['diagnostics']))
            self.assertIn('mount usage',plan['policy']['diagnostics'][0]['limitation'])
        self.docker.raw['Mounts'][0]['Source']=str(self.project/'missing-data')
        plan=self.review(self.intent());self.assertIn('missing',plan['policy']['diagnostics'][0]['limitation'])
        self.assertEqual(self.docker.updates,[])

    def test_portainer_server_image_is_compose_not_external_owner(self):
        self.docker.raw['Config']['Labels']['io.portainer.server']='true'
        self.docker.raw['Config']['Labels']['org.opencontainers.image.title']='Portainer CE'
        plan=self.review(self.intent());self.assertEqual(plan['policy']['manager'],'Docker Compose');self.assertTrue(plan['allowed'])
        self.assertTrue(self.commit(plan)['ok']);self.assertEqual(len(self.docker.updates),1)

    def test_management_evidence_and_external_unknown_remain_guarded(self):
        for key in ('io.portainer.stack.name','com.portainer.stack.id','io.portainer.edge_stack_id'):
            self.docker.raw['Config']['Labels']=dict(self.labels,**{'io.portainer.server':'true',key:'fixture'})
            plan=self.review(self.intent());self.assertEqual(plan['policy']['manager'],'Portainer');self.assertFalse(plan['allowed'])
            with self.assertRaises(ValueError):self.commit(plan)
        for key in ('io.portainer.unrecognised','com.portainer.unrecognised'):
            self.docker.raw['Config']['Labels']=dict(self.labels,**{key:'hint'})
            plan=self.review(self.intent());self.assertEqual(plan['policy']['manager'],'Unverified external management');self.assertFalse(plan['allowed'])
        self.docker.raw['Config']['Labels']=dict(self.labels,**{'com.docker.compose.project.working_dir':'/data/compose/42'})
        self.assertFalse(self.review(self.intent())['allowed']);self.assertEqual(self.docker.updates,[])

    def test_batch_rechecks_app_lock_and_authentication(self):
        self.writable();review=self.reviewed_access()
        directory=self.b.cli.drives.roots(self.b.s)[1]/'shared-locks';directory.mkdir(exist_ok=True)
        with (directory/('docker-restart-'+IDENTITY+'.lock')).open('a') as fd:
            os.fchmod(fd.fileno(),0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError,'Another operation'):self.permission_apply(review)
        self.assertEqual(self.project.stat().st_mode&0o777,0o775)
        for action in ('docker-permission-plan','docker-permission-apply'):
            self.assertEqual(self.f.main.broker.handle(dict(action=action,write=True,data={}))['status'],401)
        self.assertEqual(self.docker.updates,[])

    def test_unknown_account_home_is_reported_as_unverified(self):
        self.writable()
        with patch.object(self.editor.pwd,'getpwuid',side_effect=KeyError('private account lookup')):
            plan=self.review(self.intent())
        issue=plan['policy']['diagnostics'][0]
        self.assertFalse(issue['adjustable']);self.assertIn('could not be verified',issue['limitation'])
        self.assertNotIn('private account lookup',str(plan));self.assertEqual(self.project.stat().st_mode&0o777,0o775)
        self.assertEqual(self.docker.updates,[])

    def test_product_agent_metadata_and_controller_priority(self):
        self.docker.raw['Config']['Labels']=dict(self.labels,**{'io.portainer.agent':'true'})
        self.assertEqual(self.m.manager(self.docker.raw),'Docker Compose')
        self.docker.raw['Config']['Labels']['com.docker.swarm.service.id']='fixture'
        self.assertEqual(self.m.manager(self.docker.raw),'Docker Swarm')
        self.assertFalse(self.review(self.intent())['allowed'])

    def test_external_access_control_labels_are_not_deployment_ownership(self):
        self.docker.raw['Config']['Labels'].update({'io.portainer.accesscontrol.teams':'fixture','io.portainer.accesscontrol.public':'true'})
        plan=self.review(self.intent());self.assertEqual(plan['policy']['manager'],'Docker Compose');self.assertTrue(plan['allowed'])

if __name__=='__main__':unittest.main()
