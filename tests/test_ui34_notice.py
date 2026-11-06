# SPDX-License-Identifier: MIT
"""Display proof only: retained intent, exact Docker identity and selected storage."""
import copy
import http.client
import unittest
from types import SimpleNamespace
from gui_fixture import load
import test_ui32_unmount as prior

ID, IMAGE = prior.ID, prior.IMAGE

class ReadyNotice(unittest.TestCase):
    def setUp(self):
        prior.Unmount.setUp(self)
        self.intent=load('manual_intent');self.runtime[ID]['running']=False
        self.probe=dict(healthy=True,dependent=True)
        self.saved=dict(boot=self.b.w.boot_id(),phase='complete',control_ids=[ID],held_ids=[ID],uuid=self.f.main.uuid)
        self.path=self.b.s.STATE_DIR/'manual-unmount.json';self.b.cli.save(self.path,self.saved)
        self.missing_drive=None;self.missing_image=False;self.verifications=[]
        boot=load('boot_start');boot.engine=self.engine
        original=self.b.common.module
        self.f.main.patch(self.b.common,'module',lambda name,*args:boot if name=='boot_start' else original(name,*args))

    inspect=prior.Unmount.inspect
    post=prior.Unmount.post
    users=prior.Unmount.users
    command=prior.Unmount.command

    def engine(self,b,drive,c):
        def main():
            self.verifications.append(('main',drive))
            if drive==self.missing_drive:raise self.b.w.Unsafe('Filesystem not verified')
        def image(item):
            self.verifications.append(('image',item['uuid']))
            if self.missing_image:raise self.b.w.Unsafe('Image not mounted')
        return SimpleNamespace(verify_main=main,verify_dependent=image,settings=b.s,SETTINGS=c)

    def notice(self):return self.intent.ready_apps(self.b,self.b.configuration(),self.probe)

    def test_ready_stopped_apps_with_monitoring_on_or_off_without_writes(self):
        before=self.path.read_bytes();configs=[m.config.read_bytes() for m in (self.f.main,self.f.second)]
        for active in (False,True):
            self.f.main.active=active
            self.assertEqual(self.notice(),[dict(id=ID,name='test-app')])
        self.assertIn(('image',IMAGE),self.verifications)
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual(configs,[m.config.read_bytes() for m in (self.f.main,self.f.second)]);self.assertEqual(self.events,[])

    def test_no_ready_claim_for_unavailable_main_or_selected_image(self):
        for key in ('healthy','dependent'):
            self.probe[key]=False;self.assertEqual(self.notice(),[]);self.probe[key]=True
        self.missing_drive='legacy';self.assertEqual(self.notice(),[])
        self.missing_drive=None;self.missing_image=True;self.assertEqual(self.notice(),[])

    def test_other_selected_drive_and_boot_only_image_are_verified(self):
        c=self.f.second.b.configuration();c['docker'].update(enabled=True,containers=[dict(name='test-app',container_id=ID,source='',destination='',grace=10,images=[])]);self.b.cli.save(self.f.second.config,c)
        self.missing_drive=self.f.second.b.s.PROFILE_ID;self.assertEqual(self.notice(),[])
        self.missing_drive=None;c=self.b.configuration();c['docker']['containers'][0]['images']=[];self.b.cli.save(self.b.s.CONFIG,c)
        self.missing_image=True;self.assertEqual(self.notice(),[])  # Still selected for boot.

    def test_release_running_missing_or_replaced_identity_clears_notice(self):
        self.runtime[ID]['running']=True;self.assertEqual(self.notice(),[])
        self.runtime[ID]['running']=False;self.runtime[ID]['id']='d'*64;self.assertEqual(self.notice(),[])
        self.runtime[ID]['id']=ID
        for failure in (OSError('Docker unavailable'),http.client.BadStatusLine('Incomplete Docker response')):
            self.docker.inspect=lambda _:(_ for _ in ()).throw(failure);self.assertEqual(self.notice(),[])
        self.docker.inspect=self.inspect;self.b.cli.save(self.path,self.saved|dict(held_ids=[]));self.assertEqual(self.notice(),[])

    def test_new_boot_wrong_uuid_malformed_receipt_and_normal_manual_stop_are_not_intent(self):
        for change in (dict(boot='old-boot'),dict(uuid='other'),dict(held_ids='invalid')):
            self.b.cli.save(self.path,self.saved|change);self.assertEqual(self.notice(),[])
        self.path.unlink();self.assertEqual(self.notice(),[])

    def test_live_unmount_and_recovery_hide_ready_notice_until_terminal(self):
        with self.b.cli.drives.lock(self.b.s.STATE_DIR,'manual-unmount.lock'):self.assertEqual(self.notice(),[])
        self.b.cli.save(self.b.s.STATE_DIR/'state.json',dict(incident=dict(phase='wait1',control_ids=[ID])));self.assertEqual(self.notice(),[])
        self.b.cli.save(self.b.s.STATE_DIR/'state.json',dict(incident=dict(phase='done',control_ids=[ID])));self.assertTrue(self.notice())

    def test_ordinary_folder_and_retained_disabled_choices_need_no_images(self):
        c=self.b.configuration();c['images']=[];c['docker']['enabled']=False;c['docker']['containers'][0]['images']=[];self.b.cli.save(self.b.s.CONFIG,c)
        boot=self.boot.read(self.b);boot['containers'][0].update(enabled=False,drives=[dict(id='legacy',images=[])]);self.b.cli.save(self.boot.paths(self.b)[0],boot)
        self.assertTrue(self.notice());self.assertFalse(any(k=='image' for k,v in self.verifications))

if __name__=='__main__':unittest.main()
