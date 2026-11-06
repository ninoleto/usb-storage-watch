# SPDX-License-Identifier: MIT
#!/usr/bin/python3 -I
"""Shared, root-only SMTP delivery for Linux. Body/payload arrives on stdin.

Public commands: test; check-config; send --subject TITLE; send --json.
Exit 0 means SMTP accepted the message, not that it reached the inbox.
Each delivery has a 20-second total deadline. Callers own retry/queue policy.
"""
import argparse
import datetime as dt
import email.message
import email.utils
import json
import os
from pathlib import Path
import re
import resource
import smtplib
import socket
import ssl
import stat
import subprocess
import sys
import uuid

CONFIG = Path('/etc/usb-storage-watch/smtp.json')
SCRIPT = Path(__file__).resolve()
TIMEOUT = 20
MAX_BODY = 65536


def address(value):
    if (not isinstance(value, str) or not value.isascii()
            or not re.fullmatch(r'[^\s<>@,;\x00-\x1f]+@[^\s<>@,;\x00-\x1f]+\.[^\s<>@,;\x00-\x1f]+', value)
            or email.utils.parseaddr(value)[1] != value):
        raise ValueError('Expected one plain email address')
    return value


def validate_config(config):
    if (config.get('version') != 1 or config.get('security') not in ('starttls', 'tls')
            or not isinstance(config.get('host'), str)
            or not re.fullmatch(r'[A-Za-z0-9.-]+', config['host'])
            or type(config.get('port')) is not int or not 1 <= config['port'] <= 65535
            or not isinstance(config.get('username'), str) or not config['username']
            or not isinstance(config.get('password'), str) or not config['password']):
        raise ValueError('Invalid SMTP configuration')
    address(config.get('sender'))
    address(config.get('recipient'))
    return config


def load_config():
    parent = CONFIG.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0
            or parent.st_mode & 0o077):
        raise PermissionError('Configuration directory must be root-owned mode 0700')
    fd = os.open(CONFIG, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'r', encoding='utf-8') as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise PermissionError('Configuration must be root-owned mode 0600')
        return validate_config(json.load(handle))


def validate_payload(payload):
    if (not isinstance(payload, dict) or not isinstance(payload.get('subject'), str)
            or not 1 <= len(payload['subject']) <= 200
            or any(ord(c) < 32 or ord(c) == 127 for c in payload['subject'])
            or not isinstance(payload.get('body'), str)
            or len(payload['body'].encode('utf-8')) > MAX_BODY):
        raise ValueError('Invalid notification payload')
    payload = dict(payload)
    payload['id'] = str(uuid.UUID(payload.get('id') or str(uuid.uuid4())))
    return payload


def test_payload(event_id=None):
    return validate_payload({
        'id': event_id or str(uuid.uuid4()),
        'subject': '[TEST ONLY] Linux / Storage email notifications',
        'body': ('This is the requested Linux notification installation test.\n'
                 'No disk failure, USB operation, or application restart was performed.\n'
                 f'Host: {socket.gethostname()}\n'
                 f'Time: {dt.datetime.now().astimezone().isoformat(timespec="seconds")}\n\n'
                 'Please confirm that this message reached your inbox (or spam folder).\n'
                 'SMTP acceptance alone does not confirm inbox delivery.\n')})


def smtp_send(config, payload):
    """Never authenticate before mandatory, certificate-verified STARTTLS."""
    message = email.message.EmailMessage()
    message['Subject'] = payload['subject']
    message['From'] = config['sender']
    message['To'] = config['recipient']
    message['Date'] = email.utils.formatdate(localtime=True)
    message['Message-ID'] = f"<{payload['id']}@usb-storage-notify.local>"
    message.set_content(payload['body'])
    context = ssl.create_default_context()
    server = (smtplib.SMTP_SSL(config['host'], config['port'], timeout=8, context=context)
              if config['security'] == 'tls' else smtplib.SMTP(config['host'], config['port'], timeout=8))
    try:
        server.ehlo()
        if config['security'] == 'starttls':
            server.starttls(context=context)
            server.ehlo()
        server.login(config['username'], config['password'])
        refused = server.send_message(message, from_addr=config['sender'],
                                      to_addrs=[config['recipient']])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
        # DATA has been accepted. A failed QUIT must not turn success into a retry.
    finally:
        try:
            server.close()
        except OSError:
            pass  # Closing an accepted SMTP transaction must not create a duplicate retry.


def safe_error(error):
    # Exception messages and SMTP response bodies may contain private data.
    code = getattr(error, 'smtp_code', None)
    return type(error).__name__ + (f' (SMTP {code})' if type(code) is int else '')


def delivery_diagnostic(result):
    """Allowlisted diagnostics only: never retain arbitrary subprocess output."""
    descriptions = {
        'gaierror': 'DNS address lookup failed',
        'TimeoutError': 'Connection or delivery timed out',
        'ConnectionRefusedError': 'Connection was refused',
        'ConnectionResetError': 'Connection was reset',
        'ConnectionAbortedError': 'Connection was aborted',
        'BrokenPipeError': 'Connection closed during delivery',
        'PermissionError': 'A required file or network operation was denied',
        'FileNotFoundError': 'A required notification file was not found',
        'OSError': 'A file or network operation failed',
        'ValueError': 'Notification configuration or payload was invalid',
        'JSONDecodeError': 'Notification configuration or payload was invalid JSON',
        'SSLCertVerificationError': 'SMTP certificate verification failed',
        'SSLError': 'The TLS connection failed',
        'SMTPAuthenticationError': 'SMTP authentication was refused',
        'SMTPConnectError': 'The SMTP greeting was refused',
        'SMTPHeloError': 'The SMTP greeting exchange failed',
        'SMTPNotSupportedError': 'The SMTP server lacks a required capability',
        'SMTPRecipientsRefused': 'The recipient was refused',
        'SMTPSenderRefused': 'The sender was refused',
        'SMTPDataError': 'The SMTP message was refused',
        'SMTPServerDisconnected': 'The SMTP server disconnected',
        'SMTPResponseException': 'The SMTP server returned an error',
        'SMTPException': 'SMTP delivery failed',
    }
    for output in (result.stdout, result.stderr):
        if not isinstance(output, str): continue
        if output.strip() == 'Delivery deadline exceeded; acceptance may be ambiguous.':
            return 'Delivery deadline exceeded; acceptance may be ambiguous.'
        match = re.fullmatch(r'Notification failed: ([A-Za-z]+)(?: \(SMTP ([0-9]{3})\))?', output.strip())
        if match and match[1] in descriptions:
            return descriptions[match[1]] + ' (' + match[1] + (', SMTP ' + match[2] if match[2] else '') + ').'
    code = result.returncode
    return 'Notification worker failed (exit ' + str(code) + '); no recognized sanitized reason was returned.'


def bounded_send(payload):
    try:
        result = subprocess.run(
            [sys.executable, '-I', str(SCRIPT), '_worker'],
            input=json.dumps(validate_payload(payload)), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=TIMEOUT,
            cwd='/', close_fds=True)
    except subprocess.TimeoutExpired:
        return False, 'Delivery deadline exceeded; acceptance may be ambiguous.'
    if result.returncode == 0:
        return True, 'SMTP accepted the message; inbox delivery is not yet confirmed.'
    # Only this program's sanitized worker output is relayed.
    return False, result.stdout.strip()[:160] or 'Notification worker failed.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('check-config', help='Validate protected SMTP settings without printing credentials')
    sub.add_parser('test', help='Send one clearly labelled test to the configured recipient')
    sender = sub.add_parser('send', help='Read body from stdin, or a JSON payload with --json')
    sender.add_argument('--subject')
    sender.add_argument('--event-id')
    sender.add_argument('--json', action='store_true')
    sub.add_parser('_worker', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run with sudo or from a root-owned system service.')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    os.chdir('/')
    if args.command == 'check-config':
        config = load_config()
        print(f"Configuration valid: {config['host']}:{config['port']}, verified TLS; "
              'credentials withheld.')
        return 0
    if args.command == '_worker':
        payload = validate_payload(json.loads(sys.stdin.read(MAX_BODY * 6 + 4097)))
        smtp_send(load_config(), payload)
        print('SMTP accepted.')
        return 0
    if args.command == 'test':
        payload = test_payload()
    elif args.json:
        if args.subject or args.event_id:
            parser.error('--json cannot be combined with --subject or --event-id')
        payload = json.loads(sys.stdin.read(MAX_BODY * 6 + 4097))
    else:
        if not args.subject:
            parser.error('send requires --subject, or --json')
        payload = {'subject': args.subject, 'body': sys.stdin.read(MAX_BODY + 1), 'id': args.event_id}
    okay, detail = bounded_send(payload)
    print(detail)
    return 0 if okay else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('Notification failed: ' + safe_error(error), file=sys.stderr if '_worker' not in sys.argv else sys.stdout)
        raise SystemExit(1)
