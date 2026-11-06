# SPDX-License-Identifier: MIT
"""No email is sent: subprocess outcomes are simulated, receipts are real."""
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from gui_fixture import load
import test_ui25_boot as fixtures


class NotificationReceipt(unittest.TestCase):
    setUp=fixtures.BootStartup.setUp
    request=fixtures.BootStartup.request
    verify=fixtures.BootStartup.verify
    mount=fixtures.BootStartup.mount
    run_boot=fixtures.BootStartup.run_boot
    receipt=fixtures.BootStartup.receipt

    def attempt(self,result=None,error=None):
        self.w.SETTINGS['notifications']['enabled']=True
        self.w.CONFIG_DIGEST=self.b.s.digest(self.w.SETTINGS)
        with patch.object(self.m.subprocess,'run',return_value=result,side_effect=error) as send:
            self.run_boot();self.run_boot()
        self.assertEqual(send.call_count,1);self.assertEqual(self.events,['mount','start'])
        self.assertEqual(self.receipt()['phase'],'verified');return self.receipt()

    def test_safe_worker_reason_and_exit_saved_without_retries(self):
        value=self.attempt(SimpleNamespace(returncode=1,stdout='Notification failed: SMTPAuthenticationError (SMTP 535)\n',stderr=''))
        self.assertEqual(value['notification'],'failed');self.assertEqual(value['notification_exit_status'],1)
        self.assertIn('SMTPAuthenticationError, SMTP 535',value['notification_error'])
        self.assertTrue(value['notification_attempted_at']);self.assertTrue(value['notification_id'])

    def test_arbitrary_error_output_is_not_saved(self):
        value=self.attempt(SimpleNamespace(returncode=2,stdout='password=synthetic-private',stderr='Traceback with synthetic-token'))
        self.assertNotIn('synthetic',json.dumps(value));self.assertIn('exit 2',value['notification_error'])

    def test_timeout_retains_ambiguity_without_retry_or_start_failure(self):
        value=self.attempt(error=subprocess.TimeoutExpired('private-command',25,output='synthetic-private'))
        self.assertEqual(value['notification'],'uncertain');self.assertIn('acceptance is unknown',value['notification_error'])
        self.assertNotIn('private',json.dumps(value))

    def test_launch_failure_is_retained_without_leaking_path(self):
        value=self.attempt(error=PermissionError('private/path'))
        self.assertEqual(value['notification'],'failed');self.assertIn('could not be launched',value['notification_error'])
        self.assertNotIn('private/path',json.dumps(value))

    def test_success_is_acceptance_not_inbox_delivery(self):
        value=self.attempt(SimpleNamespace(returncode=0,stdout='SMTP accepted.',stderr=''))
        self.assertEqual(value['notification'],'accepted');self.assertNotIn('notification_error',value)

    def test_allowlisted_dns_tls_configuration_and_deadline_details(self):
        notify=load('notify')
        for name,expected in [('gaierror','DNS'),('SSLCertVerificationError','certificate'),('PermissionError','denied'),('FileNotFoundError','file')]:
            detail=notify.delivery_diagnostic(SimpleNamespace(returncode=1,stdout='',stderr='Notification failed: '+name))
            self.assertIn(expected,detail)
        detail=notify.delivery_diagnostic(SimpleNamespace(returncode=1,stdout='Delivery deadline exceeded; acceptance may be ambiguous.',stderr=''))
        self.assertIn('ambiguous',detail)
        for output in ['Notification failed: PasswordIsSecret','Notification failed: SMTPAuthenticationError secret','Notification failed: OSError\nsecret']:
            detail=notify.delivery_diagnostic(SimpleNamespace(returncode=1,stdout=output,stderr=''))
            self.assertNotIn('Secret',detail);self.assertNotIn('secret',detail);self.assertIn('no recognized',detail)


if __name__=='__main__':unittest.main()
