# SPDX-License-Identifier: MIT
"""DEV9 target routing and configuration transactions; hardware boundaries isolated."""
import copy
import json
import unittest
from unittest.mock import Mock, patch
from multidrive_fixture import FleetMachine, SECOND


class DriveRouting(unittest.TestCase):
    def setUp(self):
        self.f=FleetMachine();self.addCleanup(self.f.close);self.m=self.f.main;self.b=self.m.b
        self.profile=self.f.add();self.child=self.f.second

    def test_scope_required_global_settings_and_preferences_independent(self):
        for action in ('status','monitor','config','events'):
            response=self.f.request(action,{} if action=='monitor' else None,profile=None)
            self.assertEqual(response['status'],400,response)
        self.assertEqual(self.f.request('global-config',profile=None)['status'],200)
        rows=self.f.request('notification-preferences',profile=None)['data']['drives']
        self.assertEqual({r['id'] for r in rows},{'legacy',self.profile})

    def test_recovery_configuration_is_independent_of_monitor_enablement(self):
        before=self.m.config.read_bytes();self.child.active=True
        plan=self.f.request('recovery-plan',None,self.profile)
        self.assertEqual(plan['status'],400)
        req=dict(action='recovery-plan',write=False,data={'enabled':'true'},drive=self.profile,token=self.f.session['token'])
        plan=self.m.broker.handle(req);self.assertEqual(plan['status'],200,plan)
        value=plan['data'];result=self.f.request('recovery-settings',dict(enabled=True,uuid=SECOND,token=value['token'],consent=True),self.profile)
        self.assertEqual(result['status'],200,result);self.assertTrue(self.child.active);self.assertTrue(self.child.b.configuration()['recovery']['mount'])
        self.assertEqual(self.m.config.read_bytes(),before);self.assertTrue(self.m.active)
        self.child.active=False;req['data']['enabled']='false';value=self.m.broker.handle(req)['data']
        result=self.f.request('recovery-settings',dict(enabled=False,uuid=SECOND,token=value['token'],consent=True),self.profile)
        self.assertEqual(result['status'],200,result);self.assertFalse(self.child.active)
        self.assertTrue(self.child.b.configuration()['disk']['fstab_options'])

    def test_recovery_confirmation_cannot_change_a_different_drive(self):
        req=dict(action='recovery-plan',write=False,data={'enabled':'false'},drive='legacy',token=self.f.session['token'])
        value=self.m.broker.handle(req)['data'];before=self.child.config.read_bytes()
        result=self.f.request('recovery-settings',dict(enabled=False,uuid=value['uuid'],token=value['token'],consent=True),self.profile)
        self.assertEqual(result['status'],400);self.assertEqual(self.child.config.read_bytes(),before)

    def test_history_is_combined_chronological_and_filter_explicit(self):
        for m,at,label in ((self.m,'2026-01-01T01:00:00Z','A outage'),(self.child,'2026-01-01T02:00:00Z','B outage')):
            m.broker.history=m.b.History(m.state/'history.sqlite3')
            m.broker.history.record('same-key',at,label,['Synthetic incident'])
        result=self.f.request('fleet-events',profile=None)['data']
        self.assertEqual([e['title'] for e in result['events']],['B outage','A outage'])
        self.assertEqual([e['drive_id'] for e in result['events']],[self.profile,'legacy'])
        req=dict(action='fleet-events',write=False,data={'drive':'legacy'},drive=self.profile,token=self.f.session['token'])
        self.assertEqual([e['title'] for e in self.m.broker.handle(req)['data']['events']],['A outage'])

    def test_notification_preference_changes_only_named_drive(self):
        before=self.m.config.read_bytes();self.child.active=True;c=self.child.b.configuration()
        self.child.patch(self.child.b.n,'load_config',Mock())
        result=self.f.request('notification-settings',dict(revision=self.child.b.s.digest(c),enabled=True),self.profile)
        self.assertEqual(result['status'],200,result);self.assertTrue(self.child.active)
        self.assertEqual(self.m.config.read_bytes(),before);self.assertTrue(self.m.active)
        self.assertTrue(self.child.b.configuration()['notifications']['enabled'])
        self.assertFalse(self.child.b.configuration()['recovery']['mount'])

    def test_mount_anywhere_and_expected_location_are_separate(self):
        self.child.current='/mnt/somewhere-else'
        result=self.f.request('status',profile=self.profile)['data']
        self.assertTrue(result['mounted']);self.assertFalse(result['mounted_expected']);self.assertFalse(result['health']['healthy'])
        self.assertEqual(result['profile_id'],self.profile);self.assertTrue(result['observed_at'])

    def test_device_types_require_passive_evidence(self):
        classify=self.b.media_kind
        self.assertEqual(classify({'ID_DRIVE_THUMB':'1'},'1'),'flash')
        self.assertEqual(classify({'ID_ATA':'1'},'0'),'ssd')
        self.assertEqual(classify({'ID_ATA_ROTATION_RATE_RPM':'5400'},'1'),'hdd')
        self.assertEqual(classify({},'0'),'unknown')
        self.assertEqual(classify({'ID_MODEL':'Unknown USB'},'1'),'unknown')

    def test_preparation_target_uses_physical_identity_not_header(self):
        fleet=self.m.broker.fleet;disk=dict(device='/dev/disk/by-id/usb-Disposable_B',model='B',serial='DISPOSABLE',size=256*1024**2,layout=[],devs=[self.child.dev])
        with patch.object(self.b.preparation,'binding',return_value=disk),patch.object(self.b.preparation,'signatures',return_value={'filesystems':[{'UUID':SECOND}]}):
            child,broker=fleet.preparation_target({'device':disk['device']})
            self.assertIs(child,self.child.b)
        chosen=dict(token='consent-for-B',phrase='ERASE DISPOSABLE',created=__import__('time').monotonic(),disk=disk,name='B',selected=True)
        with patch.object(fleet,'preparation_target',return_value=(self.child.b,self.child.broker)),patch.object(self.child.b.preparation,'plan',return_value=chosen),patch.object(self.b.pwd,'getpwnam',return_value=Mock(pw_uid=1000,pw_gid=1000)),patch.object(self.child.broker,'start_preparation',return_value={'operation':'B-operation'}) as start:
            plan=self.f.request('prepare-drive-plan',{'device':disk['device'],'name':'B'},'legacy')
            self.assertEqual(plan['status'],200,plan)
            session=self.m.broker.sessions.sessions[self.f.session['token']]
            session['physical_preparation']=(self.profile,chosen)
            result=self.f.request('prepare-drive',dict(token=chosen['token'],confirmation=chosen['phrase'],erase=True),'legacy')
            self.assertEqual(result['status'],200,result);start.assert_called_once();self.assertTrue(self.m.active)
            self.assertEqual(self.f.request('prepare-drive',dict(token=chosen['token'],confirmation=chosen['phrase'],erase=True),self.profile)['status'],400)

    def test_preparation_refuses_duplicate_uuid_or_different_physical_identity(self):
        fleet=self.m.broker.fleet;disk={'device':'/dev/disk/by-id/usb-Test','devs':[self.child.dev]}
        with patch.object(self.b.preparation,'binding',return_value=disk),patch.object(self.b.preparation,'signatures',return_value={'filesystems':[{'UUID':SECOND}]}):
            with patch.object(self.b,'target',side_effect=ValueError('Duplicate UUID')):
                with self.assertRaisesRegex(ValueError,'Duplicate UUID'):fleet.preparation_target({'device':disk['device']})
            disk['devs']=['240:99']
            with self.assertRaisesRegex(ValueError,'different physical disk'):fleet.preparation_target({'device':disk['device']})
        self.assertTrue(self.m.active)
