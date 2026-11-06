# SPDX-License-Identifier: MIT
"""Drive retirement through the real broker, with isolated OS boundaries."""
import copy
import fcntl
import json
import os
import threading
import time
import unittest
from unittest.mock import Mock, patch
from gui_fixture import UUID
from multidrive_fixture import FleetMachine, SECOND


class RemoveDrive(unittest.TestCase):
    def setUp(self):
        self.f=FleetMachine();self.addCleanup(self.f.close)
        self.main=self.f.main;self.profile=self.f.add();self.other=self.f.second
        self.other.active=True
        for machine in (self.main,self.other):
            original=machine.command
            def command(args,timeout=10,m=machine,original=original):
                value=original(args,timeout)
                if args[:2]==['/usr/bin/systemctl','show']:
                    value+='\nMainPID='+('12345' if m.active else '0')
                return value
            machine.patch(machine.b,'command',command)

    def plan(self,profile='legacy'):
        result=self.f.request('remove-drive-plan',profile=profile)
        self.assertEqual(result['status'],200,result)
        return result['data']

    def remove(self,profile='legacy',plan=None):
        p=plan or self.plan(profile)
        return self.f.request('remove-drive',dict(uuid=p['uuid'],revision=p['revision'],confirm=True),profile)

    def test_disconnected_legacy_removed_without_deleting_storage_or_global_settings(self):
        m=self.main;b=m.b;m.present=False;m.current=''
        m.management_token()
        b.cli.save(b.s.SMTP,{'synthetic':'retained'})
        b.cli.save(m.state/'state.json',{'pending':[{'synthetic':'undelivered'}]})
        b.cli.save(m.state/'drive-identity.json',{'uuid':UUID,'serial':'old-stick'})
        before={p:p.read_bytes() for p in m.root.rglob('*') if p.is_file()}
        p=self.plan();self.assertTrue(m.active);self.assertEqual(p['uuid'],UUID)
        result=self.remove(plan=p);self.assertEqual(result['status'],200,result)
        self.assertTrue(result['data']['removed']);self.assertFalse(m.active);self.assertTrue(self.other.active)
        self.assertFalse(m.config.exists())
        self.assertEqual(m.config.with_name('removed-drive.json').read_bytes(),before[m.config])
        for path,content in before.items():
            if path!=m.config:self.assertEqual(path.read_bytes(),content,str(path))
        rows=self.f.request('fleet-status')['data']['drives']
        self.assertNotIn('legacy',[r['profile_id'] for r in rows])
        self.assertEqual([r['profile_id'] for r in rows if r['configured']],[self.profile])
        self.assertEqual(self.f.request('session')['status'],200)
        self.assertEqual(self.f.request('config')['status'],400)
        self.assertEqual(self.f.request('monitor',{'enabled':True})['status'],400)
        self.assertFalse(m.active)
        self.assertTrue(all(call[:2]==['/usr/bin/systemctl','show'] or call==['/usr/bin/systemctl','disable','--now',b.s.SERVICE] for call in m.calls))

    def test_mounted_secondary_is_retired_without_unmount_and_stale_child_cannot_write(self):
        old=self.other.broker;c=self.other.b.configuration();fstab=self.main.fstab.read_bytes()
        result=self.remove(self.profile);self.assertEqual(result['status'],200,result)
        self.assertEqual(self.other.current,'/mnt/drive-b');self.assertTrue(self.main.active)
        self.assertEqual(self.main.fstab.read_bytes(),fstab)
        rows=self.f.request('fleet-status')['data']['drives']
        self.assertEqual(len([r for r in rows if r['configured']]),1)
        self.assertTrue(any(r['uuid']==SECOND and not r['configured'] for r in rows))
        self.assertNotIn(self.profile,self.main.broker.fleet.children)
        result=old.exclusive_handle(dict(action='monitor',write=True,data={'enabled':True},drive=self.profile,token=self.f.session['token'],csrf=self.f.session['csrf']))
        self.assertEqual(result['status'],400,result);self.assertFalse(self.other.active)
        self.assertFalse(self.other.config.exists())
        self.assertEqual(json.loads(self.other.config.with_name('removed-drive.json').read_text()),c)

    def test_removing_last_drive_keeps_global_auth_and_readd_uses_fresh_profile(self):
        self.assertEqual(self.remove(self.profile)['status'],200)
        self.main.management_token();self.assertEqual(self.remove()['status'],200)
        self.assertFalse(self.main.broker.fleet.records())
        old_state=self.main.state/'state.json';self.main.b.cli.save(old_state,{'old':'retained'})
        result=self.f.request('add-drive',dict(uuid=SECOND));self.assertEqual(result['status'],200,result)
        new=result['data']['profile_id'];self.assertNotIn(new,('legacy',self.profile))
        self.assertFalse(self.f.second.active)
        self.assertEqual(old_state.read_text(),'{\n  "old": "retained"\n}\n')
        self.assertEqual(self.main.broker.fleet.records()[0][0],new)
        self.assertEqual(self.f.request('session')['status'],200)

    def test_removed_hardware_pin_does_not_prevent_explicit_readdition(self):
        pin=dict(uuid=SECOND,serial='old-usb',wwn='',vendor='synthetic',product='synthetic',size=100)
        self.other.b.cli.save(self.other.state/'drive-identity.json',pin)
        self.assertEqual(self.remove(self.profile)['status'],200)
        original=self.main.broker.fleet.factory
        def factory(identifier):
            child,instance=original(identifier)
            self.f.second.patch(child.w.drives,'hardware',Mock(side_effect=lambda w,dev,uid:pin if uid==SECOND else dict(pin,serial='different')))
            return child,instance
        self.main.broker.fleet.factory=factory
        result=self.f.request('add-drive',dict(uuid=SECOND));self.assertEqual(result['status'],200,result)
        self.assertNotEqual(result['data']['profile_id'],self.profile)

    def test_configuration_change_cross_drive_missing_confirm_and_expiry_are_refused(self):
        p=self.plan()
        payload=dict(uuid=p['uuid'],revision=p['revision'],confirm=True)
        self.assertEqual(self.f.request('remove-drive',payload,self.profile)['status'],400)
        self.assertEqual(self.f.request('remove-drive',{**payload,'confirm':False})['status'],400)
        cfg=self.main.b.configuration();cfg['disk']['label']='Renamed'
        self.main.b.cli.save(self.main.config,cfg)
        self.assertEqual(self.remove(plan=p)['status'],400);self.assertTrue(self.main.active)
        p=self.plan();session=self.main.broker.sessions.sessions[self.f.session['token']]
        session['remove:legacy']['expires']=time.monotonic()-1
        self.assertEqual(self.remove(plan=p)['status'],400);self.assertTrue(self.main.config.exists())

    def test_authentication_csrf_and_read_write_boundaries(self):
        for action,write in [('remove-drive-plan',False),('remove-drive',True)]:
            result=self.main.broker.handle(dict(action=action,write=write,drive='legacy',data={}))
            self.assertEqual(result['status'],401,result)
        p=self.plan();payload=dict(uuid=p['uuid'],revision=p['revision'],confirm=True)
        result=self.main.broker.handle(dict(action='remove-drive',write=True,drive='legacy',data=payload,token=self.f.session['token']))
        self.assertEqual(result['status'],401)
        self.assertEqual(self.f.request('remove-drive-plan',{})['status'],400)
        self.assertEqual(self.f.request('remove-drive')['status'],400)
        self.assertEqual(self.f.request('remove-drive-plan',profile='../../etc')['status'],400)
        self.assertTrue(self.main.active)

    def test_stop_failure_or_unverified_stop_keeps_registration(self):
        p=self.plan()
        with patch.object(self.main.b,'command',side_effect=ValueError('synthetic stop failure')):
            self.assertEqual(self.remove(plan=p)['status'],400)
        self.assertTrue(self.main.config.exists());self.assertTrue(self.main.active)
        original=self.main.b.command
        def unverified(args,timeout=10):
            value=original(args,timeout)
            return value.replace('MainPID=0','MainPID=999') if 'show' in args else value
        with patch.object(self.main.b,'command',side_effect=unverified):
            result=self.remove();self.assertEqual(result['status'],400,result)
        self.assertTrue(self.main.config.exists());self.assertFalse(self.main.active)

    def test_busy_workers_cleanup_and_migration_block_config_removal(self):
        for name in ('monitor.lock','recovery.lock','preparation.lock','usb-io.lock','usb-ledger.lock'):
            with self.subTest(lock=name):
                path=self.main.state/name
                with path.open('a') as lock:
                    path.chmod(0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    result=self.remove();self.assertEqual(result['status'],400,result)
                    self.assertIn('worker',result['error']);self.assertTrue(self.main.config.exists())
        reset=self.main.state/'usb-reset.json'
        self.main.b.cli.save(reset,{'phase':'enabling'})
        result=self.remove();self.assertEqual(result['status'],400,result);self.assertIn('cleanup',result['error'])
        self.assertEqual(json.loads(reset.read_text()),{'phase':'enabling'})
        reset.unlink()
        with patch.object(self.main.b.migration,'pending',return_value={'phase':'pending'}):
            result=self.remove();self.assertEqual(result['status'],400,result);self.assertIn('location',result['error'])
        with patch.object(self.main.broker,'prepare_worker',Mock()):
            result=self.remove();self.assertEqual(result['status'],400,result);self.assertIn('preparation',result['error'])
        self.assertTrue(self.main.config.exists())

    def test_removal_never_follows_a_config_symlink(self):
        p=self.plan();target=self.main.root/'untouched';target.write_bytes(self.main.config.read_bytes())
        self.main.config.unlink();self.main.config.symlink_to(target)
        result=self.remove(plan=p);self.assertNotEqual(result['status'],200,result)
        self.assertTrue(target.exists());self.assertTrue(self.main.active)

    def test_removed_drive_keeps_dashboard_session_and_historical_token_record(self):
        self.main.management_token()
        path=self.other.config.with_name('companion-api.json')
        self.other.b.cli.save(path,dict(historical='synthetic-unused-record'))
        self.assertEqual(self.remove(self.profile)['status'],200)
        self.assertEqual(self.f.request('session')['status'],200)
        self.assertTrue(self.main.active)

    def test_failed_archive_keeps_configuration_and_does_not_restart_monitoring(self):
        p=self.plan();before=self.main.config.read_bytes()
        with patch('os.replace',side_effect=OSError('synthetic rename failure')):
            result=self.remove(plan=p)
        self.assertNotEqual(result['status'],200,result)
        self.assertEqual(self.main.config.read_bytes(),before)
        self.assertFalse(self.main.config.with_name('removed-drive.json').exists())
        self.assertFalse(self.main.active);self.assertTrue(self.other.active)

    def test_registration_stays_absent_after_fleet_restart(self):
        self.assertEqual(self.remove(self.profile)['status'],200)
        old=self.main.broker.fleet
        restarted=self.main.b.drive_web.Fleet(old.context,self.main.broker)
        self.assertEqual([i for i,c,e in restarted.records()],['legacy'])
        self.assertEqual(self.remove()['status'],200)
        self.assertEqual(restarted.records(),[])

    def other_restart_client(self, extra=(), enabled=True, failure=False):
        c=self.other.b.configuration()
        c['docker'].update(enabled=enabled,containers=[dict(name='other-app',source='/mnt/drive-b/app',destination='/data',grace=10)])
        self.other.b.cli.save(self.other.config,c)
        apps=self.main.b.common.module('apps')
        current=dict(id='a'*64,name='other-app',mounts=[
            dict(Type='bind',Source='/mnt/drive-b/app',Destination='/data',RW=True,Propagation='rprivate'),
            *[dict(Type='bind',Source=source,Destination='/extra-'+str(i),RW=True,Propagation='rprivate') for i,source in enumerate(extra)]])
        inspect=Mock(side_effect=apps.AppError('Synthetic unavailable') if failure else lambda name:copy.deepcopy(current))
        self.main.patch(apps,'Docker',Mock(return_value=Mock(inspect=inspect)))
        original=self.main.b.common.module
        self.main.patch(self.main.b.common,'module',lambda name,*args,**kwargs:apps if name=='apps' else original(name,*args,**kwargs))
        return current,inspect

    def test_other_container_storage_is_advisory_and_never_blocks_removal(self):
        _,inspect=self.other_restart_client(['/mnt/drive-a/uploads'])
        before=self.other.config.read_bytes()
        result=self.remove()
        self.assertEqual(result['status'],200,result);inspect.assert_not_called()
        self.assertFalse(self.main.active);self.assertFalse(self.main.config.exists())
        self.assertTrue(self.other.active);self.assertEqual(self.other.config.read_bytes(),before)

    def test_other_container_ancestor_bind_does_not_block_retirement(self):
        _,inspect=self.other_restart_client(['/mnt'])
        result=self.remove()
        self.assertEqual(result['status'],200,result);inspect.assert_not_called()

    def test_unrelated_other_container_does_not_change_drive_context(self):
        _,inspect=self.other_restart_client(['/mnt/drive-ab/unrelated'])
        engine_apps=copy.deepcopy(self.main.b.w.apps.APPS)
        result=self.remove()
        self.assertEqual(result['status'],200,result);inspect.assert_not_called()
        self.assertEqual(self.main.b.w.apps.APPS,engine_apps)
        self.assertTrue(self.other.active)

    def test_unavailable_docker_does_not_prevent_drive_retirement(self):
        _,inspect=self.other_restart_client(failure=True)
        result=self.remove()
        self.assertEqual(result['status'],200,result);inspect.assert_not_called()
        self.assertFalse(self.main.config.exists());self.assertTrue(self.other.active)

    def test_disabled_other_restart_configuration_needs_no_docker_inspection(self):
        _,inspect=self.other_restart_client(['/mnt/drive-a/uploads'],enabled=False,failure=True)
        result=self.remove()
        self.assertEqual(result['status'],200,result);inspect.assert_not_called()
        self.assertTrue(self.other.active)

    def test_http_routes_are_explicit_and_require_same_origin(self):
        app=self.main.web.create_app(dict(self.main.b.common.DEFAULT,port=8765),self.main.broker.handle)
        client=app.test_client();client.set_cookie('usw_session',self.f.session['token'],domain='localhost')
        p=client.get('/api/drives/legacy/remove-drive-plan',base_url='http://localhost:8765')
        self.assertEqual(p.status_code,200,p.get_json())
        body=p.get_json();payload=dict(uuid=body['uuid'],revision=body['revision'],confirm=True)
        url='/api/drives/legacy/remove-drive'
        response=client.post(url,base_url='http://localhost:8765',json=payload)
        self.assertEqual(response.status_code,403)
        response=client.post(url,base_url='http://localhost:8765',json=payload,headers={'Origin':'http://localhost:8765','X-USW-Request':'1','X-CSRF-Token':self.f.session['csrf']})
        self.assertEqual(response.status_code,200,response.get_json())
        self.assertTrue(response.get_json()['removed'])


if __name__=='__main__':unittest.main()
