# SPDX-License-Identifier: MIT
"""Current recovery stage must replace old success messages in the dashboard."""
import copy
import unittest
from unittest.mock import patch
from gui_fixture import load

b=load('web_broker')

class RecoveryProgressTests(unittest.TestCase):
    def setUp(self):
        self.c=b.s.default();self.c['disk']['uuid']='11111111-1111-4111-8111-111111111111'
        self.c['recovery']['mount']=True
        self.state=dict(status='down',sample_boot='boot',sample_at=100,
                        incident=dict(id='incident',phase='wait1',boot='boot',due=160,attempts=[],
                                      stop=dict(phase='pending')))
        self.probe=dict(healthy=False,detected=False)
    def progress(self):
        with patch.object(b.w,'boot_id',return_value='boot'):
            return b.recovery_progress(self.c,self.state,self.probe,dict(ActiveState='active'),100)
    def test_stop_is_shown_before_absence_wait(self):
        self.assertEqual(self.progress()['code'],'stopping')
        self.state['incident']['stop']=dict(phase='done',result=dict(all_stopped=True))
        self.assertEqual(self.progress()['code'],'waiting_return')
        self.assertIsNone(self.progress()['wait_seconds'])
    def test_failed_stop_keeps_its_specific_reason_visible(self):
        self.state['incident']['stop']=dict(phase='pending',result=dict(all_stopped=False,
            containers={'files':dict(status='uncertain',reason='Docker has not confirmed the stop.')}))
        result=self.progress()
        self.assertEqual(result['code'],'waiting_stop')
        self.assertIn('not confirmed',result['detail'])
    def test_manual_mount_wait_does_not_claim_automatic_work(self):
        self.c['recovery']['mount']=False
        self.state['incident']['stop']=dict(phase='done',result=dict(all_stopped=True))
        self.assertEqual(self.progress()['code'],'waiting_manual')
    def test_start_stage_names_selected_storage_and_email_order(self):
        self.state['incident'].update(phase='applications',stop=dict(phase='done',result=dict(all_stopped=True)))
        self.probe.update(healthy=True,detected=True)
        result=self.progress()
        self.assertEqual(result['code'],'applications')
        self.assertIn('must be mounted',result['detail'])
        self.assertIn('afterward',result['detail'])
    def test_waiting_for_other_selected_disk_explains_which_storage(self):
        self.state['incident'].update(phase='applications',stop=dict(phase='done',result=dict(all_stopped=True)),
            applications=dict(result=dict(waiting_storage=True,containers={
                'files':dict(status='waiting_storage',reason='The Backup drive has not returned.')})))
        result=self.progress()
        self.assertEqual(result['code'],'waiting')
        self.assertIn('Backup drive',result['detail'])

if __name__=='__main__':unittest.main()
