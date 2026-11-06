# SPDX-License-Identifier: MIT
"""Portable configuration, setup and upgrade safeguards with synthetic data only."""
import contextlib
import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
w=load('distribution_engine',ROOT/'src/usb_storage_watch/engine.py')
s=w.settings
cli=load('distribution_cli',ROOT/'src/usb_storage_watch/cli.py')
fixture=load('distribution_fixture',ROOT/'tests/fixtures.py')
fixture.configure(w)

class PrivacyAuditTests(unittest.TestCase):
    def setUp(self):
        self.audit=load('distribution_privacy',ROOT/'tools/privacy_scan.py').audit

    def test_compressed_documentation_is_inspected_only_when_explicit(self):
        data=gzip.compress(b'Ordinary documentation.\n')
        failures=[];self.audit('document',data,[],failures,compressed=True)
        self.assertEqual(failures,[])
        self.audit('unexpected binary',data,[],failures)
        self.assertTrue(failures)

    def test_screenshot_exception_rejects_replaced_private_content(self):
        failures=[]
        self.audit('docs/GUI-LOGIN.png',b'changed image containing private data',[],failures)
        self.assertIn(('docs/GUI-LOGIN.png','unreviewed screenshot bytes'),failures)

    def test_compression_does_not_hide_private_values(self):
        failures=[]
        self.audit('document',gzip.compress(b'private-validation-marker'),['private-validation-marker'],failures,compressed=True)
        self.assertIn(('document','private origin value'),failures)

    def test_invalid_and_oversized_compressed_documents_fail(self):
        for data in (b'not gzip',gzip.compress(b'content')[:-4],gzip.compress(b'x'*(1024*1024+1))):
            with self.subTest(size=len(data)):
                failures=[];self.audit('document',data,[],failures,compressed=True)
                self.assertTrue(failures)

class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        lock=mock.patch.object(w.drives,'configuration_lock',return_value=contextlib.nullcontext());lock.start();self.addCleanup(lock.stop)
    def test_wizard_reprompts_invalid_numeric_and_boolean_choices(self):
        with mock.patch('builtins.input',side_effect=['abc','0','65536','587']), \
                mock.patch('builtins.print') as output:
            self.assertEqual(cli.integer('SMTP port',587,1,65535),587)
            self.assertEqual(output.call_count,3)
            self.assertIn('1 to 65535',output.call_args.args[0])
        with mock.patch('builtins.input',side_effect=['maybe','Y']),mock.patch('builtins.print'):
            self.assertTrue(cli.yes('Enable recovery?'))
        with mock.patch('builtins.input',return_value='n'):
            self.assertFalse(cli.yes('Enable recovery?',True))

    def test_setup_excludes_whole_system_disk_and_shows_parent_model(self):
        part={'name':'/dev/synthetic1','type':'part','fstype':'ext4','uuid':'11111111-1111-4111-8111-111111111111','mountpoints':[None],'model':None}
        system={'type':'disk','model':'System disk','children':[dict(part,mountpoints=['/']),dict(part)]}
        data={'type':'disk','model':'Test USB','children':[dict(part)]}
        result=mock.Mock(stdout=json.dumps({'blockdevices':[system,data]}))
        with mock.patch.object(cli,'run',return_value=result):
            rows=cli.disks()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['model'],'Test USB')

    def test_candidate_failure_explains_unsupported_topology(self):
        failure=subprocess.CalledProcessError(1,['candidate'],stderr='Operation stopped: USB port has a companion peer; keep USB resets disabled.\n')
        with mock.patch.object(cli,'run',side_effect=failure),self.assertRaisesRegex(ValueError,'companion peer'):
            cli.bounded_candidate()

    def test_defaults_no_automatic_actions_or_private_identity(self):
        c=s.default();s.validate(c,allow_unconfigured=True)
        self.assertFalse(c['recovery']['mount']);self.assertFalse(c['usb']['enabled']);self.assertFalse(c['docker']['enabled'])
        self.assertIsNone(c['usb']['profile']);self.assertEqual(c['docker']['containers'],[]);self.assertEqual(c['disk']['uuid'],'')
        self.assertEqual((c['monitor']['interval'],c['monitor']['observations'],c['recovery']['wait'],c['recovery']['attempts']),(15,2,15,1))
    def test_multiple_arbitrary_disks_and_timings(self):
        c=fixture.configuration(w);c['disk'].update(uuid='33333333-3333-4333-8333-333333333333',mountpoint='/srv/archive')
        c['dependent']['enabled']=False;c['docker'].update(enabled=False,containers=[])
        c['monitor'].update(interval=30,observations=3);c['recovery'].update(wait=120,attempts=1)
        z=load('other_engine',ROOT/'src/usb_storage_watch/engine.py');z.configure(c)
        self.assertEqual((z.MOUNT,z.INTERVAL,z.OBSERVATIONS,z.RECOVERY_DELAY,z.MAX_ATTEMPTS),('/srv/archive',30,3,120,1))
        self.assertEqual(z.apps.APPS,{})
    def test_unknown_keys_and_mutation_types_rejected(self):
        for section,key,bad in [('recovery','mount',1),('usb','enabled','true'),('docker','enabled',None),('monitor','interval',0),('recovery','attempts',3),('usb','enumeration_seconds',300)]:
            c=fixture.configuration(w);c[section][key]=bad
            with self.subTest(key=key),self.assertRaises(s.ConfigError):s.validate(c)
        c=fixture.configuration(w);c['shell']='unsafe'
        with self.assertRaises(s.ConfigError):s.validate(c)
    def test_automatic_usb_needs_runtime_binding_not_manual_attestation(self):
        c=fixture.configuration(w);c['usb']['profile'].update(qualified=False,qualification=None)
        s.validate(c)
        with self.assertRaises(s.ConfigError):s.usb_profile(c['usb']['profile'], qualified=True)
        c['usb']['profile']=None;s.validate(c)
    def test_profile_root_hub_other_port_controller_and_evidence_rejected(self):
        for key,value in [('port','/sys/bus/usb/devices/usb9/authorized'),('device','/sys/bus/usb/devices/9-3'),('canonical','/sys/devices/other'),('qualification',None)]:
            c=fixture.configuration(w);c['usb']['profile'][key]=value
            with self.subTest(key=key),self.assertRaises(s.ConfigError):s.validate(c)
    def test_unsafe_options_and_paths_refused(self):
        for options in ('rw,force','remount,rw','noload','loop','defaults,exec','defaults,errors=continue'):
            c=fixture.configuration(w);c['disk']['fstab_options']=options
            with self.assertRaises(s.ConfigError):s.validate(c)
        for path in ('/','/etc','/sys/disk','/mnt/../etc','relative','/mnt/a b'):
            c=fixture.configuration(w);c['disk']['mountpoint']=path
            with self.assertRaises(s.ConfigError):s.validate(c)
    def test_configuration_change_prevents_worker_mutation(self):
        with mock.patch.object(w.settings,'read',return_value=w.SETTINGS):
            w.require_configuration({'config_digest':w.CONFIG_DIGEST})
            with self.assertRaises(w.Unsafe):w.require_configuration({'config_digest':'old'})
        c=copy.deepcopy(w.SETTINGS);c['recovery']['wait']=120
        with mock.patch.object(w.settings,'read',return_value=c),self.assertRaises(w.Unsafe):w.config_load()
    def test_state_for_different_disk_refused(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'state.json';state=w.fresh_state();state['target']=['other','/elsewhere'];p.write_text(json.dumps(state))
            with self.assertRaises(ValueError):w.load_state(p)
    def test_disabled_dependent_has_no_probe(self):
        with mock.patch.object(w,'DEPENDENT_ENABLED',False),mock.patch.object(w,'read_rows') as rows:
            self.assertIsNone(w.dependent_metadata([]));self.assertIsNone(w.verify_dependent());rows.assert_not_called()
    def test_independent_smtp_tls_and_starttls(self):
        cfg={'version':1,'host':'smtp.example.test','port':465,'security':'tls','username':'test','password':'DUMMY-TEST-SECRET','sender':'sender@example.test','recipient':'recipient@example.test'}
        payload=cli.n.test_payload();smtp=mock.Mock();smtp.send_message.return_value={}
        with mock.patch.object(cli.n.smtplib,'SMTP_SSL',return_value=smtp) as implicit,mock.patch.object(cli.n.smtplib,'SMTP') as plain:
            cli.n.smtp_send(cli.n.validate_config(cfg),payload);implicit.assert_called_once();plain.assert_not_called();smtp.starttls.assert_not_called()
            self.assertTrue(implicit.call_args.kwargs['context'].check_hostname)
        cfg['security']='starttls';cfg['port']=587;smtp.reset_mock()
        with mock.patch.object(cli.n.smtplib,'SMTP',return_value=smtp):cli.n.smtp_send(cfg,payload)
        smtp.starttls.assert_called_once()
    def test_staged_diagnosis_never_calls_host_tools(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'etc/usb-storage-watch/config.json';path.parent.mkdir(parents=True)
            c=s.default();c['disk']['uuid']='11111111-1111-4111-8111-111111111111';path.write_text(json.dumps(c))
            with mock.patch.object(cli,'run') as run,mock.patch.object(cli.w,'snapshot') as snap,mock.patch('sys.stdout',new=io.StringIO()):cli.diagnose(root)
            run.assert_not_called();snap.assert_not_called()
    def test_symlink_staged_root_refused(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'bad';p.symlink_to('/etc')
            with self.assertRaises(ValueError):cli.root_path(root,'/bad/file')
    def test_configuration_backup_and_permissions(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'config/config.json';cli.save(p,{'first':True});cli.save(p,{'second':True})
            self.assertEqual(json.loads(p.with_name('config.json.previous').read_text()),{'first':True})
            self.assertEqual(p.stat().st_mode&0o777,0o600)
    def test_running_monitor_and_pending_reset_block_setup(self):
        with mock.patch.object(cli.subprocess,'run',return_value=mock.Mock(returncode=0)),self.assertRaises(ValueError):cli.stopped()
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'usb-reset.json').write_text('{"phase":"disabling"}')
            with mock.patch.object(cli.s,'STATE_DIR',Path(root)),mock.patch.object(cli.subprocess,'run',return_value=mock.Mock(returncode=3)),self.assertRaises(ValueError):cli.stopped()
    def test_monitor_only_does_not_enqueue_when_mail_disabled(self):
        with tempfile.TemporaryDirectory() as root,mock.patch.dict(w.SETTINGS,notifications={'enabled':False}),mock.patch.object(w,'log'):
            monitor=w.Monitor(Path(root)/'state.json',now=0,boot='simulated',application_tracking=False)
            snap={'healthy':False,'dependent':False,'detected':False,'unsafe':False,'detail':'absent','dependent_detail':'none','mounts':[]}
            monitor.sample(snap,0);monitor.sample(snap,15)
            for now in (75,):
                req=monitor.work_request(False,now);self.assertFalse(req['allow_mount']);self.assertFalse(req['allow_usb'])
                monitor.work_result(req,{'main':False,'dependent':False,'detected':False,'actions':[],'blocked':[],'reason':'absent','dependent_reason':'none','mounts':[]},now+1)
            self.assertEqual(monitor.state['pending'],[])
    def test_enable_cleanup_works_without_config(self):
        argv=['engine.py','_usb-io'];request={'action':'enable','incident':'synthetic'}
        with mock.patch.object(sys,'argv',argv),mock.patch.object(sys,'stdin',io.StringIO(json.dumps(request))),mock.patch.object(w.settings,'read',side_effect=AssertionError('must not load config')),mock.patch.object(w.os,'geteuid',return_value=0),mock.patch.object(w.usb,'io_worker') as worker:
            self.assertEqual(w.main(),0);worker.assert_called_once()
    def test_disable_cannot_bypass_configuration(self):
        with mock.patch.object(sys,'argv',['engine.py','_usb-io']),mock.patch.object(sys,'stdin',io.StringIO('{"action":"disable"}')),mock.patch.object(w.settings,'read',side_effect=s.ConfigError('missing')),mock.patch.object(w.usb,'io_worker') as worker:
            with self.assertRaises(s.ConfigError):w.main()
            worker.assert_not_called()
    def test_enable_uses_saved_qualified_profile(self):
        with tempfile.TemporaryDirectory() as root:
            ctx=w.usb_context(Path(root));req={'incident':'synthetic','number':1,'known_devs':['240:17']};w.usb.reserve(ctx,req)
            saved=w.usb.load(ctx)['profile']
            with mock.patch.object(w.usb,'configure') as configure,mock.patch.object(w.usb,'port_identity',side_effect=w.Unsafe('simulated no hardware')):
                with self.assertRaises(w.Unsafe):w.usb.io_worker(ctx,{'action':'enable','incident':'synthetic'})
                configure.assert_called_once_with(saved)


class WizardAndLifecycleTests(unittest.TestCase):
    def setUp(self):
        exists=Path.exists
        fixture=mock.patch.object(Path,'exists',lambda path: True if str(path)=='/usr/lib/systemd/system/usb-storage-watch-boot.timer' else exists(path))
        fixture.start();self.addCleanup(fixture.stop)
    def test_wizard_saves_monitor_only_without_actions(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'config/config.json'
            disk={'name':'/dev/simulated','fstype':'ext4','uuid':'11111111-1111-4111-8111-111111111111','mountpoints':['/mnt/storage'],'size':'1T','model':'Synthetic'}
            with mock.patch.object(cli.s,'CONFIG',path),mock.patch.object(cli.s,'STATE_DIR',Path(root)/'state'),mock.patch.object(cli,'stopped'),mock.patch.object(cli,'disks',return_value=[disk]),mock.patch('builtins.input',side_effect=['1','','','no','','','','','']),mock.patch('sys.stdout',new=io.StringIO()),mock.patch.object(cli.w,'fstab_check') as fstab,mock.patch.object(cli,'smtp_setup') as smtp:
                cli.setup()
            c=json.loads(path.read_text());self.assertFalse(c['recovery']['mount']);self.assertFalse(c['usb']['enabled']);self.assertFalse(c['docker']['enabled']);fstab.assert_not_called();smtp.assert_not_called()

    def test_existing_fstab_image_registration_only_saves_configuration(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'config/config.json'
            disk=dict(name='/dev/simulated',fstype='ext4',uuid='11111111-1111-4111-8111-111111111111',
                      mountpoints=['/mnt/storage'],size='1T',model='Synthetic')
            image_uuid='22222222-2222-4222-8222-222222222222'
            backing='/mnt/storage/_backup/backup.img';target='/mnt/storage/_files'
            main_opts='defaults,nofail';image_opts='loop,nofail,nodev,nosuid'
            fstab=f"UUID={disk['uuid']} /mnt/storage ext4 {main_opts} 0 0\n{backing} {target} ext4 {image_opts} 0 0\n"
            read=Path.read_text
            answers=['1','','Archive','no','yes',main_opts,'yes',image_uuid,target,backing,image_opts,'no','no','yes']
            with mock.patch.object(cli.s,'CONFIG',path),mock.patch.object(cli.s,'STATE_DIR',Path(root)/'state'),\
                    mock.patch.object(cli,'stopped'),mock.patch.object(cli,'disks',return_value=[disk]),\
                    mock.patch('builtins.input',side_effect=answers),mock.patch('sys.stdout',new=io.StringIO()),\
                    mock.patch.object(Path,'read_text',lambda p,*a,**k: fstab if str(p)=='/etc/fstab' else read(p,*a,**k)),\
                    mock.patch.object(cli.w,'fstab_check',wraps=cli.w.fstab_check) as check,\
                    mock.patch.object(cli.subprocess,'run',side_effect=AssertionError('Registration must not execute an OS/storage command')):
                cli.setup()
            c=json.loads(path.read_text());self.assertEqual(c['dependent'],dict(enabled=True,uuid=image_uuid,
                mountpoint=target,image=backing,fstab_options=image_opts))
            self.assertEqual([call.args[0] for call in check.call_args_list],['/mnt/storage',target])
            self.assertEqual(cli.s.storage_images(c)[0]['uuid'],image_uuid)
            self.assertFalse(c['docker']['enabled']);self.assertFalse(c['usb']['enabled'])
    def test_enable_only_cleanup_survives_configuration_removed_after_restart(self):
        with mock.patch.object(sys,'argv',['engine.py','_usb-cleanup']),mock.patch.object(w.settings,'read',side_effect=AssertionError('no main config needed')),mock.patch.object(w.os,'geteuid',return_value=0),mock.patch.object(w,'assert_internal_state'),mock.patch.object(w.usb,'ensure_enabled',return_value=True) as enable:
            self.assertEqual(w.main(),0);enable.assert_called_once()
    def test_incident_retains_original_configuration_fingerprint_across_restart(self):
        with tempfile.TemporaryDirectory() as root,mock.patch.object(w,'log'):
            p=Path(root)/'state.json';monitor=w.Monitor(p,now=0,boot='synthetic',application_tracking=False)
            snap={'healthy':False,'dependent':False,'detected':False,'unsafe':False,'detail':'absent','dependent_detail':'none','mounts':[]}
            monitor.sample(snap,0);monitor.sample(snap,15)
            old=w.CONFIG_DIGEST
            with mock.patch.object(w,'CONFIG_DIGEST','changed'):
                resumed=w.Monitor(p,now=30,boot='synthetic',application_tracking=False)
                resumed.sample(dict(snap,detected=True,detail='Selected device returned but is not mounted.'),45)
                request=resumed.work_request(True,75);self.assertEqual(request['config_digest'],old)
                with self.assertRaises(w.Unsafe):w.require_configuration(request)
    def test_maintenance_first_install_only_enables_empty_boot_coordinator(self):
        m=load('lifecycle_first',ROOT/'src/usb_storage_watch/maintenance.py')
        with tempfile.TemporaryDirectory() as root,mock.patch.dict(os.environ,{},clear=True),mock.patch.object(m.os,'geteuid',return_value=0),mock.patch.object(m.Path,'is_dir',return_value=True),mock.patch.object(m,'STATE',Path(root)),mock.patch.object(m,'MARKER',Path(root)/'marker'),mock.patch.object(m,'call',return_value=0) as call:
            m.main('finish-upgrade');self.assertEqual(call.call_args_list,[mock.call('daemon-reload'),mock.call('enable','--now','usb-storage-watch-boot.timer')])
    def test_maintenance_restarts_only_previously_active_own_service(self):
        m=load('lifecycle_upgrade',ROOT/'src/usb_storage_watch/maintenance.py')
        with tempfile.TemporaryDirectory() as root,mock.patch.dict(os.environ,{},clear=True),mock.patch.object(m.os,'geteuid',return_value=0),mock.patch.object(m.Path,'is_dir',return_value=True),mock.patch.object(m,'STATE',Path(root)),mock.patch.object(m,'MARKER',Path(root)/'marker'),mock.patch.object(m,'pending'),mock.patch.object(m,'call',return_value=0) as call:
            m.main('prepare-upgrade');self.assertTrue(m.MARKER.exists());m.main('finish-upgrade');self.assertFalse(m.MARKER.exists())
            self.assertIn(mock.call('stop',m.SERVICE),call.call_args_list);self.assertIn(mock.call('start',m.SERVICE),call.call_args_list)
            allowed=[('daemon-reload',),('stop','usb-storage-watch-boot.timer','usb-storage-watch-boot.service'),('enable','--now','usb-storage-watch-boot.timer')]
            self.assertTrue(all(m.SERVICE in item.args or item.args in allowed for item in call.call_args_list))
    def test_staged_maintenance_hooks_do_nothing(self):
        m=load('lifecycle_staged',ROOT/'src/usb_storage_watch/maintenance.py')
        with mock.patch.dict(os.environ,DPKG_ROOT='/synthetic-root'),mock.patch.object(m,'call') as call,mock.patch.object(m,'pending') as pending:
            for action in ('prepare-upgrade','prepare-remove','finish-upgrade','reload'):m.main(action)
            call.assert_not_called();pending.assert_not_called()

class StartupCleanupTests(unittest.TestCase):
    def setUp(self):
        lock=mock.patch.object(w.drives,'configuration_lock',return_value=contextlib.nullcontext());lock.start();self.addCleanup(lock.stop)
    def test_unconfigured_monitor_exits_without_monitoring_or_actions(self):
        with mock.patch.object(sys,'argv',['engine.py','run']),mock.patch.object(w.settings,'read',side_effect=FileNotFoundError()),mock.patch.object(w.Path,'exists',return_value=False),mock.patch.object(w,'run_monitor') as run,mock.patch.object(w,'log'):
            self.assertEqual(w.main(),0);run.assert_not_called()
    def test_unit_does_not_skip_cleanup_when_configuration_is_missing(self):
        unit=(ROOT/'packaging/usb-storage-watch.service').read_text()
        self.assertNotIn('ConditionPathExists',unit)
        self.assertIn('ExecStartPre=-/usr/bin/python3 -I /usr/lib/usb-storage-watch/engine.py _usb-cleanup',unit)

class LastMomentOptInTests(unittest.TestCase):
    def test_mount_opt_out_checked_before_subprocess(self):
        with mock.patch.object(w,'config_load',return_value={'automatic_recovery':False}),mock.patch.object(w.subprocess,'run') as run:
            with self.assertRaises(w.Unsafe):w.command(['/usr/bin/mount','--','/mnt/storage'])
            run.assert_not_called()
    def test_usb_opt_out_checked_before_disable_io(self):
        with tempfile.TemporaryDirectory() as root:
            ctx=w.usb_context(Path(root));ctx.config_load=lambda:{'usb_reset_enabled':False}
            req={'incident':'synthetic','number':1,'known_devs':['240:17']};w.usb.reserve(ctx,req)
            with mock.patch.object(w.usb,'port_identity'),mock.patch.object(w.usb,'require_absent_and_isolated') as absence:
                with self.assertRaisesRegex(w.Unsafe,'disabled before'):w.usb.io_worker(ctx,{'action':'disable','incident':'synthetic'})
                absence.assert_not_called()

if __name__=='__main__':unittest.main()
