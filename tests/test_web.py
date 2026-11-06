# SPDX-License-Identifier: MIT
"""GUI trust boundaries and presentation tests; synthetic data, no host mutations."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location('test_' + name, ROOT / 'src/usb_storage_watch' / (name + '.py'))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value

auth, common, broker, web = (load(name) for name in ('web_auth', 'web_common', 'web_broker', 'web'))
UUID = '11111111-1111-4111-8111-111111111111'
TOKEN = 'synthetic-session'

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.sessions = auth.Sessions(lambda user, password: user == 'admin' and password == 'synthetic', lambda: self.now)

    def test_login_yields_distinct_opaque_tokens_without_password(self):
        first = self.sessions.login('admin', 'synthetic'); second = self.sessions.login('admin', 'synthetic')
        self.assertNotEqual(first['token'], second['token'])
        self.assertNotEqual(first['token'], first['csrf'])
        self.assertNotIn('password', json.dumps(self.sessions.sessions))

    def test_mutation_needs_csrf(self):
        value = self.sessions.login('admin', 'synthetic')
        for csrf in (None, '', 'wrong', 12):
            with self.assertRaises(auth.Denied): self.sessions.check(value['token'], csrf, True)
        self.assertEqual(self.sessions.check(value['token'], value['csrf'], True)['username'], 'admin')

    def test_idle_expiry_and_logout(self):
        value = self.sessions.login('admin', 'synthetic'); self.now += 900
        with self.assertRaises(auth.Denied): self.sessions.check(value['token'])
        value = self.sessions.login('admin', 'synthetic'); self.sessions.logout(value['token'])
        with self.assertRaises(auth.Denied): self.sessions.check(value['token'])

    def test_absolute_expiry_even_with_activity(self):
        value = self.sessions.login('admin', 'synthetic')
        for _ in range(47): self.now += 600; self.sessions.check(value['token'])
        self.now += 600
        with self.assertRaises(auth.Denied): self.sessions.check(value['token'])

    def test_global_login_throttle_cannot_be_bypassed_by_username(self):
        for i in range(10):
            with self.assertRaises(auth.Denied): self.sessions.login('unknown' + str(i), 'wrong')
        with self.assertRaisesRegex(auth.Denied, 'Too many'): self.sessions.login('admin', 'synthetic')
        self.now += 301
        self.assertTrue(self.sessions.login('admin', 'synthetic')['token'])

    def test_session_count_is_bounded(self):
        for _ in range(50): self.sessions.login('admin', 'synthetic')
        self.assertEqual(len(self.sessions.sessions), 32)

    def test_malformed_pam_input_is_rejected(self):
        for user, password in ((None, 'x'), ('x', None), ('x\0', 'secret'), ('x', 'x'*1025), ('', 'x')):
            self.assertFalse(auth.authenticate(user, password))

    def test_root_account_cannot_use_web_login(self):
        account = Mock(pw_uid=0, pw_gid=0)
        with patch.object(auth.pwd, 'getpwnam', return_value=account), patch.object(auth.os, 'getgrouplist', return_value=[0]):
            self.assertFalse(auth.authenticate('root', 'synthetic'))

class TransportTests(unittest.TestCase):
    def test_bounded_object_framing(self):
        self.assertEqual(common.receive(io.BytesIO(b'{"a":1}\n')), {'a':1})
        for data in (b'[]\n', b'{}', b'x' * (common.MAX_MESSAGE + 1), b'not-json\n'):
            with self.assertRaises(ValueError): common.receive(io.BytesIO(data))

@unittest.skipUnless(importlib.util.find_spec('flask'), 'Optional Flask dependency absent')
class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.transport = Mock(return_value={'status':200,'data':{'message':'done'}})
        self.app = web.create_app(dict(common.DEFAULT), self.transport)
        self.client = self.app.test_client()
        self.origin = 'http://localhost:8765'
        self.headers = {'Origin':self.origin,'X-USW-Request':'1','X-CSRF-Token':'csrf'}

    def request(self, path, method='GET', **kwargs):
        return self.client.open(path, method=method, base_url=self.origin, **kwargs)

    def test_login_cookie_flags_and_token_not_in_response(self):
        self.transport.return_value = {'status':200,'data':{'token':TOKEN,'csrf':'csrf','username':'admin'}}
        response = self.request('/api/login', 'POST', headers=self.headers, json={'username':'admin','password':'synthetic'})
        self.assertEqual(response.status_code,200)
        self.assertNotIn(TOKEN, response.text)
        for flag in ('HttpOnly','SameSite=Strict','Path=/'): self.assertIn(flag,response.headers['Set-Cookie'])

    def test_security_headers_and_self_hosted_assets(self):
        response = self.request('/')
        self.assertEqual(response.status_code,200)
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        response.close()
        for asset in ('app.js','style.css','icon.svg'):
            response=self.request('/static/'+asset)
            self.assertEqual(response.status_code,200);response.close()
        self.assertEqual(self.request('/static/secret').status_code,404)

    def test_dns_rebinding_and_proxy_header_spoofing_rejected(self):
        response = self.client.get('/api/status', base_url='http://evil.example.com:8765')
        self.assertEqual(response.status_code,403)
        response = self.request('/api/status', headers={'Host':'evil.example.com:8765','X-Forwarded-Host':'localhost:8765'})
        self.assertEqual(response.status_code,403)
        self.transport.assert_not_called()

    def test_cross_origin_missing_origin_and_form_posts_rejected(self):
        for headers in ({}, {'Origin':'http://evil.example.com','X-USW-Request':'1'}, {'Origin':self.origin}):
            self.assertEqual(self.request('/api/login','POST',headers=headers,json={}).status_code,403)
        self.assertEqual(self.request('/api/login','POST',headers=self.headers,data={'username':'admin'}).status_code,403)
        self.transport.assert_not_called()

    def test_http_methods_and_action_allowlist(self):
        self.assertEqual(self.request('/api/monitor').status_code,404)
        self.assertEqual(self.request('/api/run-command','POST',headers=self.headers,json={}).status_code,404)
        self.assertEqual(self.request('/api/login').status_code,405)
        self.assertEqual(self.request('/api/config','PUT',headers=self.headers,json={}).status_code,405)
        self.transport.assert_not_called()

    def test_requests_have_size_limit(self):
        response=self.request('/api/login','POST',headers=self.headers,json={'password':'x'*70000})
        self.assertEqual(response.status_code,413); self.transport.assert_not_called()

    def test_drive_route_is_explicit_and_conflicting_header_is_rejected(self):
        response=self.request('/api/drives/legacy/status')
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.transport.call_args.args[0]['drive'],'legacy')
        self.transport.reset_mock()
        response=self.request('/api/drives/legacy/status',headers={'X-USW-Drive':UUID})
        self.assertEqual(response.status_code,400);self.transport.assert_not_called()

    def test_unavailable_broker_is_readable_and_sanitized(self):
        self.transport.side_effect = OSError('private detail')
        response=self.request('/api/status'); self.assertEqual(response.status_code,503)
        self.assertNotIn('private detail',response.text)

    def test_tls_mode_requires_https_and_sets_secure_cookie(self):
        client=web.create_app(dict(common.DEFAULT,lan=True,address='192.168.50.2',hostname='storage.example.com'),self.transport).test_client()
        self.transport.return_value={'status':200,'data':{'token':TOKEN,'csrf':'csrf'}}
        response=client.post('/api/login',base_url='https://storage.example.com:8765',json={},headers={'Origin':'https://storage.example.com:8765','X-USW-Request':'1'})
        self.assertEqual(response.status_code,200); self.assertIn('Secure',response.headers['Set-Cookie'])
        self.assertEqual(client.get('/',base_url='http://localhost:8765').status_code,403)

    def test_lan_change_preserves_local_browser_cookie(self):
        response=self.request('/api/network','POST',headers=self.headers,json={'enabled':False,'confirm':True})
        self.assertEqual(response.status_code,200);self.assertNotIn('Set-Cookie',response.headers)

class BrokerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        state = patch.object(broker.s, 'STATE_DIR', Path(directory.name)); state.start(); self.addCleanup(state.stop)
        self.c=broker.s.default(); self.c['disk'].update(uuid=UUID,mountpoint='/mnt/storage')
        self.row=dict(uuid=UUID,mountpoint='/mnt/storage',eligible=True)

    def test_os_disk_excluded_with_nested_mapper_and_sibling_partition(self):
        part={'type':'part','name':'/dev/synthetic1','fstype':'ext4','uuid':UUID,'size':1000,'mountpoints':[]}
        system={'type':'disk','model':'System','children':[dict(part,children=[{'type':'crypt','mountpoints':['/']}]),part]}
        data={'type':'disk','model':'Data','children':[part]}
        with patch.object(broker,'command',return_value=json.dumps({'blockdevices':[system,data]})):
            rows=broker.disks()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['model'],'Data')

    def test_duplicate_uuids_are_ineligible(self):
        part={'type':'part','name':'/dev/synthetic1','fstype':'ext4','uuid':UUID,'size':1000,'mountpoints':[]}
        with patch.object(broker,'command',return_value=json.dumps({'blockdevices':[{'type':'disk','children':[part,part]}]})):
            self.assertTrue(all(not row['eligible'] for row in broker.disks()))

    def test_clone_of_os_uuid_is_not_selectable(self):
        part={'type':'part','name':'/dev/synthetic1','fstype':'ext4','uuid':UUID,'size':1000,'mountpoints':[]}
        disks=[{'type':'disk','children':[dict(part,mountpoints=['/'])]}, {'type':'disk','children':[part]}]
        with patch.object(broker,'command',return_value=json.dumps({'blockdevices':disks})):
            rows=broker.disks();self.assertEqual(len(rows),1);self.assertFalse(rows[0]['eligible'])

    def test_first_run_status_does_not_validate_empty_uuid(self):
        with patch.object(broker,'configuration',return_value=broker.s.default()),patch.object(broker,'disks',return_value=[]),patch.object(broker,'command',return_value='ActiveState=inactive\n'),patch.object(broker.w,'configure') as configure:
            result=broker.status();self.assertFalse(result['configured']);self.assertFalse(result['mounted']);configure.assert_not_called()

    def test_unsupported_filesystems_are_visible_but_not_selectable(self):
        disk={'type':'disk','name':'/dev/synthetic','fstype':'vfat','uuid':'synthetic','size':1000,'mountpoints':[]}
        with patch.object(broker,'command',return_value=json.dumps({'blockdevices':[disk]})):
            rows=broker.disks();self.assertFalse(rows[0]['eligible']);self.assertIn('ext4',rows[0]['reason'])

    def test_system_or_absent_uuid_cannot_be_submitted_directly(self):
        with patch.object(broker,'disks',return_value=[]), self.assertRaises(ValueError):broker.target(UUID)

    def test_smtp_password_is_write_only_and_empty_retains_existing(self):
        value=dict(version=1,host='smtp.example.com',port=587,security='starttls',username='test',password='DUMMY-TEST-SECRET',sender='sender@example.com',recipient='recipient@example.com')
        with patch.object(broker.s,'SMTP') as path, patch.object(broker.n,'load_config',return_value=value):
            path.exists.return_value=True
            public=broker.smtp_public();self.assertNotIn('password',public);self.assertTrue(public['password_set'])
            submitted={k:v for k,v in value.items() if k not in ('version','password')};submitted['password']=''
            self.assertEqual(broker.prepare_smtp(submitted)['password'],value['password'])

    def test_invalid_smtp_does_not_echo_submitted_secret(self):
        with patch.object(broker.s,'SMTP') as path:
            path.exists.return_value=False
            with self.assertRaisesRegex(ValueError,'Check the SMTP') as context:broker.prepare_smtp({'host':'private-value','password':'private-value'})
        self.assertNotIn('private-value',str(context.exception))

    def test_stale_config_is_rejected_without_mutation(self):
        with patch.object(broker.cli,'stopped'),patch.object(broker,'configuration',return_value=self.c),patch.object(broker.cli,'save') as save:
            with self.assertRaisesRegex(ValueError,'another session'):broker.save_configuration({'revision':'old'})
            save.assert_not_called()

    def test_nonempty_unmounted_target_can_be_saved_without_changing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory);sentinel=target/'sentinel';sentinel.write_text('preserve')
            with patch.object(broker.cli,'stopped'),patch.object(broker,'configuration',return_value=self.c), \
                    patch.object(broker,'target',return_value=dict(self.row,mountpoint='')), \
                    patch.object(broker.cli,'root_path',return_value=target), \
                    patch.object(broker.cli,'save') as save:
                broker.save_configuration({'revision':broker.s.digest(self.c),'uuid':UUID})
                save.assert_called_once()
            self.assertEqual(sentinel.read_text(),'preserve')

    def test_enabling_each_recovery_mode_requires_confirmation(self):
        for key in ('mount','usb','docker'):
            with self.subTest(key=key),patch.object(broker.cli,'stopped'),patch.object(broker,'configuration',return_value=self.c),patch.object(broker,'target',return_value=self.row),patch.object(broker.cli,'save') as save:
                with self.assertRaisesRegex(ValueError,'Explicit confirmation'):broker.save_configuration({'revision':broker.s.digest(self.c),'uuid':UUID,key:True})
                save.assert_not_called()

    def test_disk_switch_preserves_old_state(self):
        with patch.object(broker.cli,'stopped'),patch.object(broker,'configuration',return_value=self.c),patch.object(broker,'target',return_value=dict(self.row,uuid='22222222-2222-4222-8222-222222222222')):
            with self.assertRaisesRegex(ValueError,'archival'):broker.save_configuration({'revision':broker.s.digest(self.c),'uuid':UUID})

    def test_raw_configuration_paths_and_usb_profiles_cannot_be_supplied(self):
        with patch.object(broker.cli,'stopped'),patch.object(broker,'configuration',return_value=self.c):
            with self.assertRaisesRegex(ValueError,'Unknown configuration'):broker.save_configuration({'revision':broker.s.digest(self.c),'disk':{'mountpoint':'/etc'},'profile':{}})

    def test_mount_entry_requires_own_confirmation_and_reuses_reviewed_options(self):
        with patch.object(Path,'read_text',return_value=''):
            with self.assertRaisesRegex(ValueError,'permanent'):broker.mount_plan(self.c,self.row,[])
            addition=broker.mount_plan(self.c,self.row,['fstab']); self.assertIn('UUID='+UUID,addition);self.assertIn('nodev,nosuid',addition)
        line=f'UUID={UUID} /mnt/storage ext4 defaults,nofail 0 0\n'
        with patch.object(Path,'read_text',return_value=line):
            self.assertIsNone(broker.mount_plan(self.c,self.row,[]));self.assertEqual(self.c['disk']['fstab_options'],'defaults,nofail')
        with patch.object(Path,'read_text',return_value='/dev/other /mnt/storage ext4 defaults 0 0\n'):
            with self.assertRaisesRegex(ValueError,'conflicts'):broker.mount_plan(self.c,self.row,['fstab'])

    def test_docker_selection_derives_source_and_name_from_fresh_inspection(self):
        rows=[dict(id='a'*64,name='demo',binds=[dict(source='/mnt/storage/demo',destination='/data',eligible=True)])]
        with patch.object(broker,'container_rows',return_value=rows):
            result=broker.selected_containers(self.c,[{'id':'a'*64,'destination':'/data'}]);self.assertEqual(result[0]['source'],'/mnt/storage/demo')
            for bad in ({'id':'a'*64,'destination':'/data','source':'/etc'}, {'id':'b'*64,'destination':'/data'}):
                with self.assertRaises(ValueError):broker.selected_containers(self.c,[bad])
            unmatched=broker.selected_containers(self.c,[dict(id='a'*64,destination='/elsewhere')])[0]
            self.assertEqual(unmatched['source'],'');self.assertEqual(unmatched['destination'],'')
            self.assertEqual(unmatched['container_id'],'a'*64)

    def test_docker_discovery_accepts_incomplete_recovery_draft_without_enabling_actions(self):
        self.c['recovery']['mount']=True;self.c['docker']['enabled']=True
        docker=Mock();docker.request.return_value=[]
        with patch.object(broker,'docker_api'),patch.object(broker.w.apps,'Docker',return_value=docker):
            self.assertEqual(broker.container_rows(self.c),[])
        self.assertFalse(broker.w.SETTINGS['recovery']['mount']);self.assertFalse(broker.w.SETTINGS['docker']['enabled'])
        self.assertTrue(self.c['recovery']['mount']);self.assertTrue(self.c['docker']['enabled'])

    def test_broker_checks_auth_and_csrf_independent_of_http(self):
        sessions=broker.auth.Sessions(lambda u,p:True);b=broker.Broker(Mock(),sessions)
        login=b.handle({'action':'login','local':True,'write':True,'data':{'username':'admin','password':'synthetic'}})['data']
        self.assertEqual(b.handle({'action':'status','write':False})['status'],401)
        self.assertEqual(b.handle({'action':'smtp','write':True,'token':login['token'],'data':{}})['status'],401)
        self.assertEqual(b.handle({'action':'run-command','write':True,'token':login['token'],'csrf':login['csrf']})['status'],400)

    def test_lan_change_preserves_authenticated_sessions(self):
        sessions=broker.auth.Sessions(lambda u,p:True);b=broker.Broker(Mock(),sessions)
        login=sessions.login('admin','synthetic');sessions.login('admin','synthetic')
        with patch.object(broker,'network_action',return_value={'url':'http://127.0.0.1:8765','phase':'pending'}):
            response=b.handle({'action':'network-stage','write':True,'token':login['token'],'csrf':login['csrf'],'data':{'lan':False}})
        self.assertEqual(response['status'],200);self.assertEqual(len(sessions.sessions),2)

    def test_network_rejects_public_wildcard_loopback_and_missing_confirmation(self):
        with self.assertRaisesRegex(ValueError,'confirmation'):broker.network({'enabled':True})
        for address in ('0.0.0.0','127.0.0.1','8.8.8.8','169.254.1.1','::1'):
            with self.subTest(address=address),self.assertRaises(ValueError):broker.network({'enabled':True,'confirm':True,'address':address,'hostname':'storage.example.com'})

    def test_tls_hostname_mismatch_refused_even_if_openssl_exits_zero(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(broker.s,'STATE_DIR',Path(directory)),patch.object(broker.socket,'socket'),patch.object(broker.ssl,'SSLContext'),patch.object(broker,'command',return_value='Hostname wrong.example.com does NOT match certificate\n'),patch.object(broker.w,'atomic_write') as write:
            with self.assertRaisesRegex(ValueError,'TLS certificate'):
                broker.network(dict(enabled=True,confirm=True,address='192.168.50.2',hostname='wrong.example.com',certificate='synthetic certificate',key='synthetic key'))
            write.assert_not_called()

    def test_docker_api_negotiates_older_daemon_without_remote_socket(self):
        connection=Mock();connection.getresponse.return_value.status=200
        connection.getresponse.return_value.read.return_value=b'{"ApiVersion":"1.45","MinAPIVersion":"1.24"}'
        with patch.object(broker.w.apps,'LocalConnection',return_value=connection):
            broker.docker_api(self.c)
        self.assertEqual(self.c['docker']['api'],'v1.45');connection.request.assert_called_once_with('GET','/version')

class WebLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.module=load('web_install');self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        base=Path(self.temporary.name)
        for name,value in [('STATE',base),('MARKER',base/'installed'),('RESTART',base/'restart'),('CONFIG',base/'web-config.json')]:
            p=patch.object(self.module,name,value);p.start();self.addCleanup(p.stop)
        for p in [patch.object(self.module.os,'geteuid',return_value=0),patch.object(self.module,'systemd_available',return_value=True),patch.object(self.module.auth,'ensure_management_token'),patch.object(self.module,'setup'),patch.object(self.module,'available',return_value=True)]:
            p.start();self.addCleanup(p.stop)
        self.runner=patch.object(self.module,'run');self.run=self.runner.start();self.addCleanup(self.runner.stop)
        preparation=patch.object(self.module.lifecycle,'prepare');self.prepare=preparation.start();self.addCleanup(preparation.stop)
        # Every OS boundary must stay synthetic on a host with systemd running.
        process=patch.object(self.module.subprocess,'run',return_value=Mock(returncode=1));process.start();self.addCleanup(process.stop)

    def test_headless_explicitly_disables_and_cancels_pending_restart(self):
        self.module.RESTART.write_text(json.dumps(list(self.module.UNITS)))
        self.module.main('finish-upgrade',headless=True)
        self.assertEqual(self.module.MARKER.read_text(),'disabled\n');self.assertFalse(self.module.RESTART.exists())
        self.assertEqual(len(self.run.call_args_list),3)
        self.assertTrue(all('disable' in c.args[0] for c in self.run.call_args_list))
        self.prepare.assert_called_once_with('disable')

    def test_upgrade_preserves_gui_disabled_state(self):
        self.module.MARKER.write_text('disabled\n');self.module.RESTART.write_text('[]')
        self.module.main('finish-upgrade')
        self.run.assert_called_once_with(['/usr/bin/systemctl','daemon-reload'])

    def test_first_install_enables_only_gui_units(self):
        self.module.main('finish-upgrade')
        calls=[call.args[0] for call in self.run.call_args_list]
        self.assertEqual(calls[1:], [['/usr/bin/systemctl','enable','--now',unit] for unit in self.module.UNITS])
        self.assertNotIn('usb-storage-watch.service',sum(calls,[]))

    def test_upgrade_restores_active_listeners_without_enabling_units(self):
        self.module.MARKER.write_text('installed\n')
        self.module.RESTART.write_text(json.dumps([*self.module.UNITS,self.module.LAN]))
        self.module.CONFIG.mkdir();(self.module.CONFIG/'config.json').write_text('{"lan":true}')
        with patch.object(self.module.subprocess,'run',return_value=Mock(returncode=0)):
            self.module.main('finish-upgrade')
        calls=[c.args[0] for c in self.run.call_args_list]
        self.assertEqual(calls[1:],[['/usr/bin/systemctl','start',u] for u in (*self.module.UNITS,self.module.LAN)])

    def test_upgrade_keeps_disabled_lan_off_even_with_old_restart_receipt(self):
        self.module.MARKER.write_text('installed\n')
        self.module.RESTART.write_text(json.dumps([*self.module.UNITS,self.module.LAN]))
        self.module.CONFIG.mkdir();(self.module.CONFIG/'config.json').write_text('{"lan":false}')
        with patch.object(self.module.subprocess,'run',return_value=Mock(returncode=0)):
            self.module.main('finish-upgrade')
        self.assertNotIn(self.module.LAN,str(self.run.call_args_list))

class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.c=broker.s.default();self.c['disk']['uuid']=UUID
        self.connection={'boot':'test-boot','diskseq':1}
        self.state={'status':'up','sample_boot':'test-boot','sample_at':100,
                    'incident':{'id':'test','phase':'done','attempts':[],'result':{'main':True},
                                'outcome':'Storage AUTO-RECOVERED','connection':self.connection}}
        self.probe={'healthy':True,'connection':self.connection}
        p=patch.object(broker.w,'boot_id',return_value='test-boot');p.start();self.addCleanup(p.stop)

    def progress(self,active=True,now=100):
        return broker.recovery_progress(self.c,self.state,self.probe,{'ActiveState':'active' if active else 'inactive'},now)

    def test_historical_success_never_overrides_current_unavailable_disk(self):
        self.assertEqual(self.progress()['code'],'recovered')
        self.probe['healthy']=False
        self.assertEqual(self.progress()['code'],'confirming')
        self.state['status']='down'
        self.assertEqual(self.progress()['code'],'failed')
        self.state['reconnect_pending']=True
        self.assertEqual(self.progress()['title'],'New USB connection detected')

    def test_disabled_service_cannot_show_recovery_in_progress(self):
        self.state['status']='down';self.state['incident']['phase']='running'
        self.assertEqual(self.progress(False)['code'],'disabled')

    def test_failed_applications_are_partial_even_with_healthy_recovered_disk(self):
        self.state['incident']['applications']={'result':{'all_verified':False}}
        self.assertEqual(self.progress()['code'],'partial')
        self.assertIn('applications need attention',self.progress()['title'])
        self.state['incident']['applications']['result']['all_verified']=True
        self.assertEqual(self.progress()['code'],'recovered')
        self.probe['healthy']=False
        self.assertEqual(self.progress()['code'],'confirming')

    def test_unavailable_dependent_filesystem_is_partial_recovery(self):
        self.probe.update(dependent=False,dependent_detail='Configured loop is absent.')
        self.assertEqual(self.progress()['code'],'partial')
        self.assertEqual(self.progress()['detail'],'Configured loop is absent.')

    def test_wait_running_verification_and_applications_are_distinct(self):
        self.state['status']='down';i=self.state['incident'];i.update(boot='test-boot',due=160)
        for phase,code in [('wait1','waiting'),('wait2','waiting'),('running','running'),('verify','verify'),('applications','applications')]:
            with self.subTest(phase=phase):
                i['phase']=phase;result=self.progress();self.assertEqual(result['code'],code)
                if code=='waiting':self.assertEqual(result['wait_seconds'],60)

    def test_stale_monitor_samples_do_not_claim_health_or_recovery(self):
        self.assertEqual(self.progress(now=200)['code'],'starting')
        self.probe['connection']={'boot':'test-boot','diskseq':2}
        self.assertEqual(self.progress()['code'],'healthy')


class HistoryTests(unittest.TestCase):
    def test_archived_incident_is_imported_after_current_incident_changes(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(broker.s,'STATE_DIR',Path(directory)):
            archive=Path(directory)/'incidents';archive.mkdir()
            (archive/'old.json').write_text(json.dumps({'id':'old','first_failure':'earlier','phase':'done','outcome':'Earlier failure'}))
            (Path(directory)/'state.json').write_text(json.dumps({'incident':{'id':'new','first_failure':'later','phase':'wait1'}}))
            events=broker.History(Path(directory)/'history.sqlite3').events()
            self.assertEqual({v['title'] for v in events},{'Earlier failure','Storage outage'})

    def test_large_unicode_history_fits_bounded_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            history=broker.History(Path(directory)/'history.sqlite3')
            for i in range(40):history.record(str(i),str(i),'Outage',['é'*6000])
            with patch.object(history,'capture'):events=history.events()
            self.assertGreater(len(events),0);self.assertLess(len(events),40)
            self.assertLess(len(json.dumps({'status':200,'data':{'events':events}}).encode()),common.MAX_MESSAGE)

    def test_history_survives_restart_is_bounded_and_not_raw_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'history.sqlite3'; history=broker.History(path)
            for i in range(205):history.record(str(i),f'{i:04}', 'Outage', ['Attempt 1: recovered'])
            with history.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],200)
            history=broker.History(path)
            with patch.object(history,'capture'):
                events=history.events();self.assertEqual(len(events),40);self.assertEqual(events[0]['time'],'0204')
                self.assertEqual(events[0]['detail'],'Attempt 1: recovered')

if __name__ == '__main__': unittest.main()
