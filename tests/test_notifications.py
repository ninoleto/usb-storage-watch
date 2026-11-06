# SPDX-License-Identifier: MIT
#!/usr/bin/python3
"""Offline simulations. No real SMTP, device operations, or system services."""
import base64
import configparser
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import smtplib
import sqlite3
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

sys.dont_write_bytecode = True
BUNDLE = Path(__file__).resolve().parent


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


watch = load('test_watch', BUNDLE.parent / 'src/usb_storage_watch/engine.py')

_fs = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('fixtures.py'))
fixture = importlib.util.module_from_spec(_fs)
_fs.loader.exec_module(fixture)
fixture.configure(watch)

notify = load('test_notify', BUNDLE.parent / 'src/usb_storage_watch/notify.py')


ROOT = '1 0 240:2 / / rw,relatime - ext4 /dev/sda2 rw\n'
STORAGE = '2 1 240:17 / /mnt/storage rw,relatime - ext4 /dev/sdb1 rw,stripe=8191\n'


class Observations(unittest.TestCase):
    def observe(self, text=ROOT + STORAGE, missing=False, block=True, sysfs=True):
        paths = []

        def read(path, *args, **kwargs):
            paths.append(str(path))
            self.assertEqual(str(path), '/proc/self/mountinfo')
            return text

        def device(path, *args, **kwargs):
            paths.append(str(path))
            self.assertEqual(str(path), '/dev/disk/by-uuid/' + watch.DISK_UUID)
            if missing:
                raise FileNotFoundError()
            return types.SimpleNamespace(st_mode=stat.S_IFBLK if block else stat.S_IFREG,
                                         st_rdev=os.makedev(240, 17))

        def directory(path):
            paths.append(str(path))
            self.assertEqual(str(path), '/sys/dev/block/240:17')
            return sysfs

        with mock.patch.object(Path, 'read_text', read), mock.patch.object(watch.os, 'stat', device), \
                mock.patch.object(Path, 'is_dir', directory):
            result = watch.observe()
        self.assertFalse(any(p == '/mnt/storage' or p.startswith('/mnt/storage/') for p in paths))
        return result

    def test_healthy_exact_metadata(self):
        self.assertTrue(self.observe()[0])

    def test_directory_without_mount_is_not_healthy(self):
        self.assertFalse(self.observe(ROOT)[0])

    def test_uuid_missing(self):
        self.assertFalse(self.observe(missing=True)[0])

    def test_uuid_must_resolve_to_block_device(self):
        self.assertFalse(self.observe(block=False)[0])

    def test_stale_device_without_sysfs(self):
        self.assertFalse(self.observe(sysfs=False)[0])

    def test_wrong_device(self):
        self.assertFalse(self.observe(ROOT + STORAGE.replace('240:17', '8:33'))[0])

    def test_wrong_filesystem(self):
        self.assertFalse(self.observe(ROOT + STORAGE.replace('ext4', 'xfs'))[0])

    def test_partial_filesystem_bind_mount(self):
        self.assertFalse(self.observe(ROOT + STORAGE.replace('240:17 / ', '240:17 /subfolder '))[0])

    def test_per_mount_read_only(self):
        self.assertFalse(self.observe(ROOT + STORAGE.replace('rw,relatime', 'ro,relatime'))[0])

    def test_superblock_read_only(self):
        self.assertFalse(self.observe(ROOT + STORAGE.replace('rw,stripe', 'ro,stripe'))[0])

    def test_read_write_must_be_explicit(self):
        self.assertFalse(self.observe(ROOT + STORAGE.replace('rw,relatime', 'relatime'))[0])
        self.assertFalse(self.observe(ROOT + STORAGE.replace('rw,stripe', 'stripe'))[0])

    def test_corrupt_mountinfo_is_unhealthy(self):
        self.assertFalse(self.observe('incomplete mountinfo')[0])

    def test_covering_ancestor_hides_old_mount(self):
        self.assertFalse(self.observe(ROOT + STORAGE + '3 1 0:40 / /mnt rw - tmpfs tmpfs rw\n')[0])

    def test_stacked_wrong_mount(self):
        self.assertFalse(self.observe(ROOT + STORAGE + '3 2 0:40 / /mnt/storage rw - tmpfs tmpfs rw\n')[0])

    def test_ambiguous_mount(self):
        self.assertFalse(self.observe(ROOT + STORAGE + STORAGE.replace('2 1', '3 1'))[0])

    def test_sibling_prefix_does_not_hide_storage(self):
        self.assertTrue(self.observe(ROOT + STORAGE + '3 1 0:40 / /mnt/storage-other rw - tmpfs tmpfs rw\n')[0])

    def test_mount_escape_parser(self):
        row = watch.parse_mounts('7 1 240:17 / /with\\040space rw - ext4 /dev/name\\134slash rw')[0]
        self.assertEqual(row['target'], '/with space')
        self.assertEqual(row['source'], '/dev/name\\slash')


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='usb-storage-notify-test-', dir='/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / 'state.json'
        self.logs = mock.patch.object(watch, 'log')
        self.logs.start()
        self.addCleanup(self.logs.stop)


class SenderTests(TemporaryCase):
    def config(self):
        return {'version': 1, 'host': 'mail.example.test', 'port': 587, 'security': 'starttls',
                'username': 'sender@example.test', 'sender': 'sender@example.test',
                'recipient': 'alerts@example.test', 'password': 'DUMMY-TEST-SECRET'}

    def test_verified_starttls_before_auth_and_data(self):
        server = mock.MagicMock()
        server.send_message.return_value = {}
        with mock.patch.object(notify.smtplib, 'SMTP', return_value=server):
            notify.smtp_send(self.config(), notify.test_payload())
        self.assertEqual([c[0] for c in server.mock_calls],
                         ['ehlo', 'starttls', 'ehlo', 'login', 'send_message', 'close'])
        context = server.starttls.call_args.kwargs['context']
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(server.send_message.call_args.kwargs['to_addrs'], ['alerts@example.test'])

    def test_no_login_when_starttls_or_certificate_verification_fails(self):
        for failure in (smtplib.SMTPNotSupportedError('dummy'), ssl.SSLCertVerificationError('dummy')):
            server = mock.MagicMock()
            server.starttls.side_effect = failure
            with mock.patch.object(notify.smtplib, 'SMTP', return_value=server):
                with self.assertRaises(type(failure)):
                    notify.smtp_send(self.config(), notify.test_payload())
            server.login.assert_not_called()
            server.send_message.assert_not_called()

    def test_rejected_recipient_is_not_success(self):
        server = mock.MagicMock()
        server.send_message.return_value = {'alerts@example.test': (550, b'dummy')}
        with mock.patch.object(notify.smtplib, 'SMTP', return_value=server):
            with self.assertRaises(smtplib.SMTPRecipientsRefused):
                notify.smtp_send(self.config(), notify.test_payload())

    def test_close_error_after_data_acceptance_does_not_retry(self):
        server = mock.MagicMock()
        server.send_message.return_value = {}
        server.close.side_effect = OSError('simulated close failure')
        with mock.patch.object(notify.smtplib, 'SMTP', return_value=server):
            notify.smtp_send(self.config(), notify.test_payload())

    def test_cleartext_configuration_is_rejected(self):
        config = self.config()
        config['security'] = 'none'
        with self.assertRaises(ValueError):
            notify.validate_config(config)

    def test_missing_recipient_is_rejected(self):
        config = self.config()
        del config['recipient']
        with self.assertRaises(ValueError):
            notify.validate_config(config)

    def test_header_injection_and_bad_event_id_are_rejected(self):
        for payload in ({'subject': 'hello\r\nBcc: x@example.test', 'body': 'x'},
                        {'subject': 'hello', 'body': 'x', 'id': '<invalid>'}):
            with self.assertRaises(ValueError):
                notify.validate_payload(payload)

    def test_error_output_does_not_include_credentials_or_response_body(self):
        result = notify.safe_error(smtplib.SMTPAuthenticationError(535, b'DUMMY-TEST-SECRET'))
        self.assertEqual(result, 'SMTPAuthenticationError (SMTP 535)')

    def test_shared_sender_hard_deadline(self):
        worker = self.directory / 'hung.py'
        worker.write_text('import time; time.sleep(10)\n')
        start = time.monotonic()
        with mock.patch.object(notify, 'SCRIPT', worker), mock.patch.object(notify, 'TIMEOUT', 0.1):
            accepted, message = notify.bounded_send(notify.test_payload())
        self.assertFalse(accepted)
        self.assertIn('ambiguous', message)
        self.assertLess(time.monotonic() - start, 2)

    def test_password_not_in_worker_arguments_or_input(self):
        with mock.patch.object(notify.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout='SMTP accepted.')) as run:
            accepted, _ = notify.bounded_send(notify.test_payload())
        self.assertTrue(accepted)
        self.assertNotIn('DUMMY-TEST-SECRET', repr(run.call_args))
        self.assertEqual(run.call_args.kwargs['timeout'], 20)

    def test_unprotected_config_directory_is_rejected(self):
        cfg = self.directory / 'smtp.json'
        cfg.write_text(json.dumps(self.config()))
        os.chmod(self.directory, 0o755)
        with mock.patch.object(notify, 'CONFIG', cfg):
            with self.assertRaises(PermissionError):
                notify.load_config()




if __name__ == '__main__':
    unittest.main(verbosity=2)
