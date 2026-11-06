# SPDX-License-Identifier: MIT
"""Consent and pre-write refusal checks; real disk tests run only in QEMU."""
from contextlib import nullcontext
import importlib.util
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('prepare_broker', Path(__file__).parents[1] / 'src/usb_storage_watch/web_broker.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
p = b.preparation


class PrepareTests(unittest.TestCase):
    def chosen(self):
        return dict(token='one-use-token', created=time.monotonic(), phrase='ERASE TEST0001',
                    disk=dict(device='/dev/disk/by-id/usb-Test_TEST0001', serial='TEST0001', size=1024,
                              layout=[{'start':2048, 'size':4096}], sequence='14'),
                    revision='settings', signatures={'table':'old'}, name='Data')

    def consent(self, chosen):
        return dict(token=chosen['token'], confirmation=chosen['phrase'], erase=True)

    def test_missing_expired_or_incorrect_consent_never_opens_a_disk(self):
        chosen = self.chosen(); correct = self.consent(chosen)
        cases = [(None, correct), (chosen, dict(correct, erase=False)),
                 (chosen, dict(correct, confirmation='ERASE ANOTHER')),
                 (chosen, dict(correct, token='wrong')), (chosen, dict(correct, device='/dev/sda')),
                 (dict(chosen, created=time.monotonic()-301), correct)]
        with patch.object(p.os, 'open') as opened:
            for proposal, data in cases:
                with self.subTest(data=data), self.assertRaises(ValueError):
                    p.prepare(b.preparation_context(), proposal, data)
            opened.assert_not_called()

    def test_changed_serial_capacity_layout_attachment_or_settings_never_opens_disk(self):
        chosen = self.chosen()
        variants = [dict(chosen['disk'], **change) for change in (
            {'serial':'ANOTHER'}, {'size':2048}, {'layout':[]}, {'sequence':'15'})]
        with patch.object(p, 'exclusive', side_effect=lambda _,**kw:nullcontext(99)), \
                patch.object(p, 'revision', return_value='settings') as revision, \
                patch.object(p, 'binding') as binding, patch.object(p.os, 'open') as opened:
            for changed in variants:
                binding.return_value = changed
                with self.assertRaisesRegex(ValueError, 'changed'):
                    p.prepare(b.preparation_context(), chosen, self.consent(chosen))
            binding.return_value = chosen['disk']; revision.return_value = 'new settings'
            with self.assertRaisesRegex(ValueError, 'changed'):
                p.prepare(b.preparation_context(), chosen, self.consent(chosen))
            opened.assert_not_called()

    def test_raw_kernel_names_and_partition_aliases_are_never_selected(self):
        with patch.object(p, 'inventory', return_value=[]) as inventory:
            for path in ('/dev/sdb', '/dev/disk/by-id/../sdb', '/dev/loop0', '/dev/disk/by-id/usb-Test-part1'):
                with self.assertRaises(ValueError): p.binding(b.preparation_context(), path)
            self.assertEqual(inventory.call_count, 1)

    def test_busy_guard_precedes_exclusive_open_and_every_destructive_command(self):
        chosen = self.chosen()
        with patch.object(p, 'exclusive', side_effect=lambda _,**kw:nullcontext(99)), \
                patch.object(p, 'revision', return_value='settings'), \
                patch.object(p, 'binding', return_value=chosen['disk']), \
                patch.object(p, 'unused', side_effect=ValueError('mounted or busy')), \
                patch.object(p.os, 'open') as opened, patch.object(p, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'mounted or busy'):
                p.prepare(b.preparation_context(), chosen, self.consent(chosen))
            opened.assert_not_called(); command.assert_not_called()

    def test_broker_requires_admin_csrf_and_consumes_session_bound_consent(self):
        sessions = b.auth.Sessions(lambda u,p:True); broker = b.Broker(Mock(), sessions)
        login = sessions.login('admin','test'); other = sessions.login('other','test')
        request = dict(drive='legacy',action='prepare-drive-plan', write=True, data={'device':'synthetic','name':''})
        chosen = self.chosen()
        chosen['disk'].update(model='Test', devs=[], boot='test')
        with patch.object(broker.fleet,'preparation_target',return_value=(b,broker)), patch.object(broker.fleet,'preparations',return_value=[]), patch.object(p, 'plan', return_value=chosen) as plan, \
                patch.object(b.pwd, 'getpwnam', return_value=Mock(pw_uid=1000,pw_gid=1000)), \
                patch.object(broker, 'start_preparation', side_effect=lambda chosen,data:p.confirm(chosen,data)) as operation:
            self.assertEqual(broker.handle(request)['status'],401)
            self.assertEqual(broker.handle(dict(request,token=login['token']))['status'],401)
            plan.assert_not_called()
            admin = dict(token=login['token'],csrf=login['csrf'])
            self.assertEqual(broker.handle(dict(request,**admin))['status'],200)
            action = dict(drive='legacy',action='prepare-drive',write=True,data=self.consent(chosen))
            self.assertEqual(broker.handle(dict(action,token=other['token'],csrf=other['csrf']))['status'],400)
            self.assertEqual(broker.handle(dict(action,**admin))['status'],200)
            self.assertEqual(broker.handle(dict(action,**admin))['status'],400)
            self.assertIs(operation.call_args.args[0],chosen);self.assertEqual(operation.call_count,1)


if __name__ == '__main__': unittest.main()
