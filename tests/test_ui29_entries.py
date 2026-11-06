# SPDX-License-Identifier: MIT
"""Saved-identity changes use isolated config files and synthetic Docker only."""
import copy
import json
import unittest
from unittest.mock import patch
from gui_fixture import load
from test_ui28_apps import AppSettings, IMAGE
from test_ui26_setup import IDENTITY

OLD='d'*64
TARGET='e'*64


class EntrySettings(unittest.TestCase):
    def setUp(self):
        AppSettings.setUp(self)
        self.entries=load('app_entries');original=self.b.common.module
        self.f.main.patch(self.b.common,'module',lambda name,*args:self.entries if name=='app_entries' else original(name,*args))
        self.boot_value=self.boot.read(self.b)
        self.boot_value['containers'].append(dict(id=OLD,name='folder-app',enabled=False,drives=[dict(id='legacy',images=[IMAGE])]))
        self.b.cli.save(self.boot.paths(self.b)[0],self.boot_value)
        self.history=self.b.s.STATE_DIR/'boot-start'/ (OLD+'.json')
        self.history.parent.mkdir(mode=0o700,parents=True,exist_ok=True);self.history.write_text('{"historical":"must remain"}')
        self.rows.append(dict(id=TARGET,name='destination',state='stopped',discovered=True))

    def snapshot(self):return self.editor_app.snapshot(self.b,self.web.records(self.fleet),self.rows)
    def preview(self,operation='remove',target=None):
        return self.entries.plan(self.fleet,dict(id=OLD,name='folder-app',revision=self.snapshot()['revision'],operation=operation,target=target),self.session)
    def confirm(self,plan):return self.entries.apply(self.fleet,dict(token=plan['token'],confirm=True),self.session)

    def test_old_and_new_same_name_stay_distinct_and_remove_only_old_boot_reference(self):
        view=self.web.overview(self.fleet)
        self.assertTrue(view['inventory_ok']);self.assertEqual(len([r for r in view['containers'] if r['name']=='folder-app']),2)
        self.assertEqual(next(r for r in view['containers'] if r['id']==OLD)['state'],'missing')
        before=self.entries.documents(self.b);raw=copy.deepcopy(self.docker.raw);history=self.history.read_bytes()
        plan=self.preview();self.assertEqual(before,self.entries.documents(self.b))
        self.assertTrue(self.confirm(plan)['ok'])
        after=self.entries.documents(self.b);expected=copy.deepcopy(before);expected['boot']['containers']=expected['boot']['containers'][:1]
        self.assertEqual(after,expected);self.assertEqual(self.docker.raw,raw);self.assertEqual(self.history.read_bytes(),history)
        backups=list((self.b.s.STATE_DIR/'app-entry-backups').glob('*.json'));self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].stat().st_mode&0o777,0o600);self.assertEqual(set(json.loads(backups[0].read_text())['before']),{'boot'})
        with self.assertRaises(ValueError):self.confirm(plan)

    def test_inactive_retained_only_and_recovery_reference_removed_without_touching_active_id(self):
        preference=dict(id=OLD,name='folder-app',enabled=False,drives=[dict(id='legacy',images=[IMAGE])],specs={})
        self.b.cli.save(self.editor_app.preferences_path(self.b),{OLD:preference})
        c=self.f.second.b.configuration();c['docker']['containers']=[dict(name='folder-app',container_id=OLD,source='',destination='',grace=60,images=[])];c['docker']['enabled']=False
        self.b.cli.save(self.f.second.config,c)
        main=self.f.main.config.read_bytes();self.assertTrue(self.confirm(self.preview())['ok'])
        self.assertEqual(self.f.main.config.read_bytes(),main);self.assertFalse(self.f.second.b.configuration()['docker']['enabled'])
        self.assertEqual(self.f.second.b.configuration()['docker']['containers'],[]);self.assertNotIn(OLD,self.editor_app.preferences(self.b))
        self.assertTrue(self.history.exists())

    def test_docker_failure_never_classifies_boot_only_or_retained_only_as_missing(self):
        self.b.cli.save(self.editor_app.preferences_path(self.b),{TARGET:dict(id=TARGET,name='destination',enabled=False,drives=[],specs={})})
        before=self.entries.documents(self.b)
        with patch.object(self.web,'discover',side_effect=OSError('synthetic unavailable')):
            result=self.web.overview(self.fleet)
            self.assertFalse(result['inventory_ok']);self.assertTrue(result['error'])
            self.assertTrue(all(r['state']=='unknown' for r in result['containers']))
            with self.assertRaisesRegex(ValueError,'inventory is unavailable'):self.preview()
        self.assertEqual(before,self.entries.documents(self.b));self.assertTrue(self.history.exists())

    def test_docker_failure_after_review_refuses_removal_without_backup_or_changes(self):
        plan=self.preview();before=self.entries.documents(self.b)
        with patch.object(self.web,'discover',side_effect=OSError()):
            with self.assertRaisesRegex(ValueError,'inventory is unavailable'):self.confirm(plan)
        self.assertEqual(before,self.entries.documents(self.b));self.assertFalse((self.b.s.STATE_DIR/'app-entry-backups').exists())

    def test_source_reappearing_or_destination_replaced_after_preview_is_refused(self):
        plan=self.preview();self.rows.append(dict(id=OLD,name='folder-app',state='stopped',discovered=True))
        with self.assertRaisesRegex(ValueError,'present in Docker'):self.confirm(plan)
        self.rows.pop();plan=self.preview('reconnect',dict(id=TARGET,name='destination'))
        self.rows[-1]['id']='f'*64
        with self.assertRaisesRegex(ValueError,'identity changed or disappeared'):self.confirm(plan)
        self.assertIn(OLD,self.entries.saved_ids(self.entries.documents(self.b)))

    def test_reconnect_requires_explicit_clean_destination_and_never_merges_by_name(self):
        with self.assertRaisesRegex(ValueError,'already has saved'):self.preview('reconnect',dict(id=IDENTITY,name='folder-app'))
        with self.assertRaises(ValueError):self.preview('reconnect',dict(id=TARGET,name='folder-app'))
        with self.assertRaises(ValueError):self.preview('reconnect',None)
        before=copy.deepcopy(self.docker.raw);plan=self.preview('reconnect',dict(id=TARGET,name='destination'))
        self.assertIn('OFF',plan['message']);self.assertTrue(self.confirm(plan)['ok'])
        item=next(v for v in self.boot.read(self.b)['containers'] if v['id']==TARGET)
        self.assertFalse(item['enabled']);self.assertEqual(item['drives'],[dict(id='legacy',images=[IMAGE])]);self.assertEqual(item['name'],'destination')
        self.assertEqual(self.docker.raw,before);self.assertTrue(self.history.exists());self.assertEqual(self.docker.updates,[])

    def test_reconnect_retains_inactive_images_and_options_and_leaves_automatic_settings_off(self):
        values=self.boot.read(self.b);values['containers'][-1]['enabled']=True;self.b.cli.save(self.boot.paths(self.b)[0],values)
        c=self.f.second.b.configuration();spec=dict(name='folder-app',container_id=OLD,source='/mnt/drive-b/uploads',destination='/data',grace=75,images=[])
        c['docker'].update(enabled=True,containers=[spec]);self.b.cli.save(self.f.second.config,c)
        self.assertTrue(self.confirm(self.preview('reconnect',dict(id=TARGET,name='destination')))['ok'])
        pref=self.editor_app.preferences(self.b)[TARGET]
        self.assertFalse(pref['enabled']);self.assertEqual(pref['drives'],[dict(id=self.other,images=[])])
        self.assertEqual(pref['specs'][self.other],dict(spec,container_id=TARGET,name='destination'))
        self.assertEqual(self.f.second.b.configuration()['docker']['containers'],[])
        self.assertTrue(self.b.configuration()['docker']['enabled']);self.assertTrue(self.history.exists())

    def test_stale_revision_config_change_and_unconfirmed_requests_are_refused(self):
        plan=self.preview();before=self.entries.documents(self.b)
        with self.assertRaises(ValueError):self.entries.apply(self.fleet,dict(token=plan['token'],confirm=False),self.session)
        c=self.b.configuration();c['disk']['label']='User changed this';self.b.cli.save(self.f.main.config,c)
        with self.assertRaisesRegex(ValueError,'Settings changed'):self.confirm(plan)
        self.assertEqual(self.boot.read(self.b),before['boot'])

    def test_write_failure_restores_exact_configuration_and_keeps_history_and_backup(self):
        plan=self.preview('reconnect',dict(id=TARGET,name='destination'));before=self.entries.documents(self.b)
        original=self.entries.write_value;calls=[]
        def fail_once(b,path,value):
            original(b,path,value);calls.append(path)
            if len(calls)==1:raise OSError('synthetic after-write failure')
        with patch.object(self.entries,'write_value',side_effect=fail_once):
            with self.assertRaisesRegex(ValueError,'previous settings were restored'):self.confirm(plan)
        self.assertEqual(before,self.entries.documents(self.b));self.assertFalse(self.entries.journal(self.b).exists())
        self.assertTrue(self.history.exists());self.assertEqual(len(list((self.b.s.STATE_DIR/'app-entry-backups').glob('*.json'))),1)

    def test_interrupted_change_rolls_back_but_later_edit_is_never_overwritten(self):
        plan=self.preview();value=self.session['app_entry_plan'];receipt=dict(version=1,before={'boot':value['before']['boot']},after={'boot':value['after']['boot']})
        self.b.cli.save(self.entries.journal(self.b),receipt);self.b.cli.save(self.boot.paths(self.b)[0],receipt['after']['boot'])
        self.web.overview(self.fleet);self.assertEqual(self.boot.read(self.b),receipt['before']['boot'])
        self.b.cli.save(self.entries.journal(self.b),receipt);later=copy.deepcopy(receipt['before']['boot']);later['containers'][0]['enabled']=False
        self.b.cli.save(self.boot.paths(self.b)[0],later)
        with self.assertRaisesRegex(ValueError,'administrator review'):self.web.overview(self.fleet)
        self.assertEqual(self.boot.read(self.b),later)

    def test_entry_routes_require_authentication_csrf_and_reject_file_paths(self):
        for action in ('docker-entry-plan','docker-entry-apply'):
            response=self.f.main.broker.handle(dict(action=action,write=True,data={}))
            self.assertEqual(response['status'],401)
            response=self.f.main.broker.handle(dict(action=action,write=True,data={},token=self.f.session['token'],csrf='wrong'))
            self.assertEqual(response['status'],401)
        data=dict(id=OLD,name='folder-app',revision=self.snapshot()['revision'],operation='remove',target=None)
        self.assertEqual(self.f.request('docker-entry-plan',dict(data,path='/etc/passwd'),profile=None)['status'],400)
        result=self.f.request('docker-entry-plan',data,profile=None);self.assertEqual(result['status'],200,result)
        result=self.f.request('docker-entry-apply',dict(token=result['data']['token'],confirm=True),profile=None)
        self.assertEqual(result['status'],200,result);self.assertTrue(result['data']['ok'])

    def test_invalid_or_duplicate_inventory_cannot_prove_absence(self):
        inventory_module=load('web_docker');original=inventory_module.discover
        current=dict(id=IDENTITY,name='folder-app',dead=False,paused=False,restarting=False,running=True,mounts=[])
        for listing in ([dict(Id='invalid')],[dict(Id=IDENTITY),dict(Id=IDENTITY)]):
            with patch.object(inventory_module,'client',return_value=(self.docker,'v1.47')), patch.object(self.docker,'request',return_value=listing), patch.object(self.docker,'inspect',return_value=current):
                with self.assertRaises(ValueError):original(self.b,self.web.records(self.fleet))

    def test_busy_recovery_lock_refuses_before_writes(self):
        plan=self.preview();before=self.entries.documents(self.b);original=self.b.cli.drives.lock
        def busy(directory,name):
            if name=='recovery.lock':raise BlockingIOError('busy')
            return original(directory,name)
        with patch.object(self.b.cli.drives,'lock',side_effect=busy):
            with self.assertRaisesRegex(ValueError,'operation is busy'):self.confirm(plan)
        self.assertEqual(before,self.entries.documents(self.b))


if __name__=='__main__':unittest.main()
