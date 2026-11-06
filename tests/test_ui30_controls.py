# SPDX-License-Identifier: MIT
"""Incident-wide admission with real private files/locks and synthetic Docker."""
import copy
import json
import unittest
from unittest.mock import patch
from gui_fixture import load
import test_ui18_docker_actions as manual
import test_ui28_apps as editor

ID=manual.IDENTITY
OTHER='c'*64
MESSAGE='Recovery in progress. Controls are temporarily unavailable.'


def incident(machine, phase='wait1', ids=None, **extra):
    value=dict(id='11111111-1111-4111-8111-111111111111',boot='synthetic-boot',phase=phase,**extra)
    if ids is not None:value['control_ids']=ids
    machine.b.cli.save(machine.state/'state.json',dict(incident=value))


class ManualGuard(unittest.TestCase):
    setUp=manual.ManualControls.setUp
    data=manual.ManualControls.data
    run_action=manual.ManualControls.run_action

    def test_all_active_stages_refuse_each_command_and_do_not_cancel_boot(self):
        for phase in ('wait1','wait2','running','verify','applications'):
            incident(self.f.main,phase,[ID])
            for action in ('start','stop','restart'):
                result=self.run_action(action)
                self.assertEqual(result['status'],400,result);self.assertEqual(result['error'],MESSAGE)
        self.assertEqual(self.docker.posts,[]);self.client.assert_not_called()
        self.assertFalse((self.b.s.STATE_DIR/'boot-start'/(ID+'.json')).exists())

    def test_terminal_success_and_failure_release_but_other_incident_still_blocks(self):
        incident(self.f.main,'done',[ID],outcome='Recovered')
        incident(self.f.second,'wait2',[ID])
        self.assertEqual(self.run_action('start')['status'],400)
        incident(self.f.second,'done',[ID],outcome='Recovery failed')
        self.assertTrue(self.run_action('start')['data']['ok'])
        self.assertEqual(len(self.docker.posts),1)

    def test_new_incident_relocks_after_previous_terminal_failure(self):
        incident(self.f.main,'done',[ID],outcome='Recovery failed')
        self.assertTrue(self.run_action('start')['data']['ok'])
        incident(self.f.main,'wait1',[ID])
        self.assertEqual(self.run_action('stop')['status'],400)
        self.assertEqual(len(self.docker.posts),1)

    def test_exact_identity_unrelated_and_same_name_replacement_not_blocked(self):
        incident(self.f.main,ids=[OTHER])
        self.assertTrue(self.run_action('start')['data']['ok'])
        self.assertEqual(len(self.docker.posts),1)

    def test_recheck_after_docker_read_catches_incident_before_post(self):
        self.client.side_effect=lambda *_:(incident(self.f.main,ids=[ID]) or self.docker,'v1.47')
        result=self.run_action('start')
        self.assertEqual(result['status'],400);self.assertEqual(result['error'],MESSAGE)
        self.assertEqual(self.docker.posts,[])

    def test_guard_is_under_existing_container_lock(self):
        import fcntl
        directory=self.b.cli.drives.roots(self.b.s)[1]/'shared-locks'
        original=self.client.side_effect
        def check(*_):
            with (directory/('docker-restart-'+ID+'.lock')).open('a') as handle:
                with self.assertRaises(BlockingIOError):fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return self.docker,'v1.47'
        self.client.side_effect=check
        self.assertTrue(self.run_action('start')['data']['ok'])

    def test_legacy_receipt_uses_explicit_config_and_survives_monitoring_off(self):
        c=self.b.configuration();c['docker'].update(enabled=True,containers=[dict(name='erugo',container_id=ID,images=[],source='',destination='',grace=30)])
        self.b.cli.save(self.f.main.config,c);self.f.main.active=False
        incident(self.f.main)
        self.assertEqual(self.run_action('restart')['status'],400)
        self.assertFalse(self.f.main.active);self.assertEqual(self.docker.posts,[])

    def test_bad_state_fails_closed_for_selected_app_only(self):
        c=self.b.configuration();c['docker'].update(enabled=True,containers=[dict(name='erugo',container_id=ID,images=[],source='',destination='',grace=30)])
        self.b.cli.save(self.f.main.config,c);(self.f.main.state/'state.json').write_text('{broken')
        result=self.run_action('start');self.assertEqual(result['status'],400)
        self.assertIn('Recovery status is unavailable',result['error']);self.assertEqual(self.docker.posts,[])
        self.docker.current.update(id=OTHER,name='other')
        result=self.module.manual_action(self.f.main.broker.fleet,dict(id=OTHER,name='other',action='start',confirm=True))
        self.assertTrue(result['ok'])


class SettingsGuard(unittest.TestCase):
    setUp=editor.AppSettings.setUp
    current=editor.AppSettings.current
    desired=editor.AppSettings.desired
    review=editor.AppSettings.review
    commit=editor.AppSettings.commit

    def test_review_is_refused_and_read_only_overview_remains_available(self):
        incident(self.f.main,ids=[editor.IDENTITY]);desired=self.desired();desired['recovery']['enabled']=False
        with self.assertRaisesRegex(ValueError,MESSAGE):self.review(desired)
        overview=self.web.overview(self.fleet)
        self.assertEqual(next(v for v in overview['containers'] if v['id']==editor.IDENTITY)['control_block'],MESSAGE)
        self.assertTrue(overview['inventory_ok']);self.assertEqual(self.docker.updates,[])

    def test_stale_preview_cannot_apply_any_policy_or_setting(self):
        desired=self.desired();desired['boot']['drives'][0]['images']=[]
        self.docker.raw['HostConfig']['RestartPolicy']=dict(Name='always',MaximumRetryCount=0)
        plan=self.review(desired);before=self.current()
        incident(self.f.second,ids=[editor.IDENTITY])
        with self.assertRaisesRegex(ValueError,MESSAGE):self.commit(plan)
        self.assertEqual(self.current(),before);self.assertEqual(self.docker.updates,[])
        incident(self.f.second,'done',[editor.IDENTITY])
        with self.assertRaises(ValueError):self.commit(plan) # never queued/replayed

    def test_direct_boot_recovery_and_legacy_editors_cannot_bypass(self):
        incident(self.f.main,ids=[editor.IDENTITY]);before=self.current()
        with self.assertRaisesRegex(ValueError,MESSAGE):
            self.boot.update(self.fleet,dict(revision=self.boot.public(self.b)['revision'],container=dict(id=editor.IDENTITY,name='folder-app',enabled=False,drives=[])))
        with self.assertRaisesRegex(ValueError,MESSAGE):
            self.web.save(self.fleet,dict(id=editor.IDENTITY,name='folder-app',revision=self.web.revision(self.web.records(self.fleet)),drives=[dict(id=i,enabled=False,images=[]) for i,_ in self.web.records(self.fleet)]))
        with self.assertRaisesRegex(ValueError,MESSAGE):
            self.b.application_settings(dict(revision=self.b.s.digest(self.b.configuration()),enabled=False))
        self.assertEqual(self.current(),before)

    def test_policy_confirmation_rechecks_even_when_preview_was_allowed(self):
        plan=self.m.plan(self.fleet,dict(id=editor.IDENTITY,name='folder-app'),self.session)
        incident(self.f.main,ids=[editor.IDENTITY])
        with self.assertRaisesRegex(ValueError,MESSAGE):
            self.m.apply(self.fleet,dict(id=editor.IDENTITY,name='folder-app',token=plan['token'],confirm=True),self.session)
        self.assertEqual(self.docker.updates,[])

    def test_inactive_retained_choices_do_not_authorize_or_block_recovery(self):
        c=self.b.configuration();c['docker']['enabled']=False;self.b.cli.save(self.f.main.config,c)
        incident(self.f.main) # old receipt, no selected engine app
        self.assertNotIn(editor.IDENTITY,load('app_control').restrictions(self.b,self.web.records(self.fleet)))

    def test_new_engine_incident_pins_selected_ids_without_retained_or_name_matching(self):
        engine=load('engine');config=self.b.configuration()
        with patch.object(engine,'SETTINGS',config):
            value=engine.new_incident('time','failure',10,'boot')
        self.assertEqual(value['control_ids'],[editor.IDENTITY])
        config['docker']['enabled']=False
        with patch.object(engine,'SETTINGS',config):
            self.assertEqual(engine.new_incident('time','failure',10,'boot')['control_ids'],[])


import test_ui29_entries as entries


class EntryGuard(unittest.TestCase):
    setUp=entries.EntrySettings.setUp
    snapshot=entries.EntrySettings.snapshot
    preview=entries.EntrySettings.preview
    confirm=entries.EntrySettings.confirm

    def test_missing_source_cannot_be_removed_during_its_incident(self):
        plan=self.preview();before=self.entries.documents(self.b)
        incident(self.f.main,ids=[entries.OLD])
        with self.assertRaisesRegex(ValueError,MESSAGE):self.confirm(plan)
        self.assertEqual(before,self.entries.documents(self.b));self.assertTrue(self.history.exists())

    def test_reconnect_target_cannot_be_changed_during_its_incident(self):
        plan=self.preview('reconnect',dict(id=entries.TARGET,name='destination'));before=self.entries.documents(self.b)
        incident(self.f.second,ids=[entries.TARGET])
        with self.assertRaisesRegex(ValueError,MESSAGE):self.confirm(plan)
        self.assertEqual(before,self.entries.documents(self.b));self.assertEqual(self.docker.updates,[])


if __name__=='__main__':unittest.main()
