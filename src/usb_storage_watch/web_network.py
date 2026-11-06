# SPDX-License-Identifier: MIT
"""Test proposed listeners before committing network settings.

Only this application's units/files are managed. Saved listeners remain active
until authenticated confirmation arrives through the exact proposed endpoint.
The private receipt makes cancellation and interrupted commits recoverable.
"""
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import hashlib
import pwd
import secrets
import socket
import ssl
import subprocess
import tempfile
import threading
import time

LOCAL = 'usb-storage-watch-web.service'
LAN = 'usb-storage-watch-lan.service'
TEST = 'usb-storage-watch-network-test@{}.service'
FILES = ('config.json', 'certificate.pem', 'key.pem', 'local-network-ca.pem')
ACTIVE = ('preparing', 'pending', 'committing', 'cancelling')
WINDOW = 180
PORT_HINT = Path('/run/usb-storage-watch-dashboard.port')


class Context:
    """Root-only material preparation, shared by the broker's transaction manager."""
    def __init__(self, broker):
        self.b = broker
        self.state, self.web_dir = broker.s.STATE_DIR, broker.common.WEB_DIR
        self.atomic, self.command = broker.w.atomic_write, broker.command

    def config(self):
        try:
            raw = json.loads(self.b.common.WEB_CONFIG.read_text())
        except FileNotFoundError:
            raw = self.b.common.DEFAULT
        except (OSError, ValueError):
            raise ValueError('Saved network settings need local administrator review before changing connections.') from None
        return self.b.common.network_config(raw)

    def own_web(self, path):
        os.chown(path, 0, pwd.getpwnam('usb-storage-watch-web').pw_gid)

    def publish_port(self, value):
        # Only a public numeric port, never configuration or credentials.
        self.atomic(PORT_HINT, str(value['http_port'])+'\n', mode=0o644)

    def stopped(self, unit):
        fields = dict(line.split('=', 1) for line in self.command([
            '/usr/bin/systemctl', 'show', unit, '--property=ActiveState,MainPID']).splitlines() if '=' in line)
        if fields.get('ActiveState') not in ('inactive', 'failed') or fields.get('MainPID') != '0':
            raise ValueError('The previous listener did not stop. Review network services locally.')

    def ready(self, entry, certificate):
        deadline = time.monotonic() + 8
        while True:
            try:
                if entry['lan'] and entry['address'] not in [v['address'] for v in self.addresses()]:
                    raise ValueError('The listener address is no longer assigned to this computer.')
                if entry.get('scheme')=='https' and certificate==(self.web_dir/'certificate.pem').read_text() and not self.certificate_trusted():
                    raise ValueError('The saved HTTPS certificate does not match the configured trust authority.')
                self.b.lan_ready(entry, certificate)
                return
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise ValueError('The proposed dashboard did not become ready. Check the selected address and ports.') from None
                time.sleep(.2)

    def addresses(self):
        return self.b.common.module('network_addresses').discover(self.command)

    def selection(self, value, addresses=None):
        return self.b.common.module('network_addresses').choose(value, self.addresses() if addresses is None else addresses)

    def service(self):
        return dict(line.split('=', 1) for line in self.command([
            '/usr/bin/systemctl', 'show', LAN, '--property=ActiveState,SubState,MainPID'], 5).splitlines() if '=' in line)

    def certificate_covers(self, address):
        try:
            cert = ssl._ssl._test_decode_cert(str(self.web_dir/'certificate.pem'))
            return (('IP Address', address) in cert.get('subjectAltName', ()) and
                    ssl.cert_time_to_seconds(cert['notBefore']) <= time.time() < ssl.cert_time_to_seconds(cert['notAfter']) and
                    self.certificate_trusted())
        except (OSError, ValueError, KeyError, ssl.SSLError): return False

    def certificate_trusted(self):
        certificate = self.web_dir/'certificate.pem'
        authority = self.web_dir/'local-network-ca.pem'
        try:
            self.command(['/usr/bin/openssl', 'verify', '-CAfile', str(authority if authority.exists() else certificate),
                          '-untrusted', str(certificate), str(certificate)], 5)
            return True
        except (OSError, ValueError, subprocess.SubprocessError): return False

    def https_files(self, address, replace_trust=False):
        if self.certificate_covers(address) and (self.web_dir/'key.pem').is_file():
            return {name:(self.web_dir/name).read_text() if (self.web_dir/name).exists() else None
                    for name in FILES if name != 'config.json'}
        info = self.certificate_info()
        if not info['renewable'] and not replace_trust:
            raise ValueError('HTTPS certificate does not cover this address and its trusted signing key is unavailable. '
                             'Prepare/download the proposed trust certificate and explicitly approve replacing trust, '
                             'or supply a certificate covering this address. HTTPS remains required.')
        if not info['available']:
            raise ValueError('Prepare and trust the HTTPS certificate before testing this connection.')
        return self.leaf(address)

    def follow_material(self, previous, address):
        value = dict(previous, address=address, hostname=address)
        files = {'config.json': json.dumps(value)+'\n'}
        if value['scheme'] == 'https': files.update(self.https_files(address))
        return value, files

    def certificate_info(self):
        path = self.web_dir / 'proposed-network-ca.pem'
        result = dict(available=False, fingerprint='', renewable=False)
        try:
            content = path.read_text()
            fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(content)).hexdigest().upper()
            result.update(available=True, fingerprint=':'.join(fingerprint[i:i+2] for i in range(0, len(fingerprint), 2)))
        except (OSError, ValueError):
            content = ''
        try:
            decoded = ssl._ssl._test_decode_cert(str(self.web_dir/'certificate.pem'))
            result['server_expires'] = datetime.fromtimestamp(
                ssl.cert_time_to_seconds(decoded['notAfter']), timezone.utc).isoformat()
        except (OSError, ValueError, KeyError):
            pass
        current = self.config()
        if current['lan'] and current['scheme'] == 'https':
            try:
                issuer = self.state/'network-issuer'
                result['renewable'] = bool(content and
                    (self.web_dir/'local-network-ca.pem').read_text() == content and
                    (issuer/'ca.pem').read_text() == content and
                    (issuer/'key.pem').is_file() and not (issuer/'key.pem').is_symlink())
            except OSError:
                pass
            if not result['renewable']:
                result['renewal_reason'] = ('This HTTPS connection uses an older or externally supplied certificate. '
                    'Download and trust this app’s certificate, then apply HTTPS on an unused port and confirm that connection first.')
            result['replacement_required'] = not result['renewable']
        return result

    def renewal_material(self):
        if not self.certificate_info()['renewable']:
            raise ValueError('Enable and confirm HTTPS using this app’s trust certificate before renewing it.')
        value = self.config()
        files = self.leaf(value['address'])
        files['config.json'] = json.dumps(value)+'\n'
        return value, files

    def prepare_certificate(self):
        # This issuer survives address changes; it never changes live TLS files.
        issuer = self.state / 'network-issuer'
        if issuer.is_symlink():
            raise ValueError('Network certificate directory needs administrator review.')
        issuer.mkdir(mode=0o700, exist_ok=True)
        issuer.chmod(0o700)
        ca, key = issuer / 'ca.pem', issuer / 'key.pem'
        if not ca.exists() and not key.exists():
            with tempfile.TemporaryDirectory(prefix='issuer-', dir=issuer) as directory:
                root = Path(directory)
                self.command(['/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-days', '3650',
                    '-subj', '/CN=USB Storage Watch Local Network', '-keyout', str(root/'key.pem'), '-out', str(root/'ca.pem'),
                    '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign'], 30)
                self.atomic(key, (root/'key.pem').read_text(), mode=0o600)
                self.atomic(ca, (root/'ca.pem').read_text(), mode=0o600)
        if not ca.is_file() or not key.is_file() or ca.is_symlink() or key.is_symlink():
            raise ValueError('Network issuer is incomplete. Review certificates locally before proceeding.')
        self.command(['/usr/bin/openssl', 'x509', '-in', str(ca), '-checkend', '86400', '-noout'])
        path = self.web_dir / 'proposed-network-ca.pem'
        self.atomic(path, ca.read_text(), mode=0o640)
        self.own_web(path)
        return self.certificate_info()

    def leaf(self, address):
        self.prepare_certificate()
        issuer = self.state / 'network-issuer'
        with tempfile.TemporaryDirectory(prefix='network-leaf-', dir=self.state) as directory:
            root = Path(directory)
            self.command(['/usr/bin/openssl', 'req', '-new', '-newkey', 'rsa:3072', '-nodes', '-subj', '/CN='+address,
                '-keyout', str(root/'key.pem'), '-out', str(root/'request.pem')], 30)
            (root/'extensions').write_text('subjectAltName=IP:'+address+'\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
            self.command(['/usr/bin/openssl', 'x509', '-req', '-in', str(root/'request.pem'),
                '-CA', str(issuer/'ca.pem'), '-CAkey', str(issuer/'key.pem'), '-set_serial', '0x'+secrets.token_hex(16),
                '-days', '365', '-sha256', '-extfile', str(root/'extensions'), '-out', str(root/'certificate.pem')], 30)
            return {'certificate.pem': (root/'certificate.pem').read_text()+(issuer/'ca.pem').read_text(),
                    'key.pem': (root/'key.pem').read_text(), 'local-network-ca.pem': (issuer/'ca.pem').read_text()}

    def material(self, data):
        required = {'lan', 'address', 'scheme', 'http_port', 'https_port'}
        if not required <= set(data) or set(data) - required - {'address_mode','replace_trust'}:
            raise ValueError('Send the complete network settings from the current dashboard.')
        data = dict(data)
        replace_trust = data.pop('replace_trust', False)
        if type(replace_trust) is not bool: raise ValueError('Explicitly approve any required trust replacement.')
        data.setdefault('address_mode', 'manual')
        if data['address_mode'] not in ('automatic', 'manual'): raise ValueError('Choose Automatic or Manual address selection.')
        if type(data['lan']) is not bool or data['scheme'] not in ('http', 'https'):
            raise ValueError('Choose LAN access and HTTP or HTTPS.')
        for name in ('http_port', 'https_port'):
            if type(data[name]) is not int or not 1024 <= data[name] <= 65535:
                raise ValueError('Ports must be between 1024 and 65535.')
        previous = self.config()
        address = data['address']
        chosen = None
        if data['lan']:
            if not self.b.auth.management_configured(self.b.s.CONFIG.with_name('management-token.json'), self.state):
                raise ValueError('Create your management token before enabling local network access.')
            chosen = self.selection(data)
            if data['address_mode'] == 'automatic': address = chosen['address'] if chosen else '127.0.0.1'
            elif not chosen:
                raise ValueError('Choose one of this computer’s currently assigned private network addresses.')
            if chosen:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.bind((address, 0))
        elif not self.b.common.private_network_address(address):
            address = '127.0.0.1'
        value = dict(data, address=address, hostname=address, port=data[data['scheme']+'_port'])
        if not value['lan'] and address == '127.0.0.1':
            value['hostname'] = 'localhost'
        value = self.b.common.network_config(value)
        files = {'config.json': json.dumps(value)+'\n'}
        if value == previous:
            return value, files
        if value['lan'] and value['scheme'] == 'https':
            # Retest an unchanged HTTPS endpoint with its current certificate.
            # Replacing it before confirmation would invalidate existing access.
            if previous['lan'] and endpoint_key(value) == endpoint_key(previous):
                files.update({name: (self.web_dir/name).read_text() for name in
                              ('certificate.pem', 'key.pem')})
                ca = self.web_dir/'local-network-ca.pem'
                files['local-network-ca.pem'] = ca.read_text() if ca.exists() else None
            else:
                if chosen:
                    files.update(self.https_files(address, replace_trust or not (previous['lan'] and previous['scheme']=='https')))
                elif not previous['lan'] or previous['scheme'] != 'https' or replace_trust:
                    if not self.certificate_info()['available']:
                        raise ValueError('Prepare and trust the HTTPS certificate before enabling Automatic HTTPS.')
                    files['local-network-ca.pem'] = (self.web_dir/'proposed-network-ca.pem').read_text()
        return value, files


def endpoints(c):
    result = [dict(lan=False, address='127.0.0.1', hostname='localhost',
                   scheme='http', port=c['http_port'])]
    if c['lan'] and c['address'] != '127.0.0.1':
        result.append(dict(lan=True, address=c['address'], hostname=c['hostname'],
                           scheme=c['scheme'], port=c['port']))
    return result


def endpoint_key(c):
    return c['address'], c['port'], c['scheme']


def url(c, local=False):
    if local or not c['lan'] or c['address'] == '127.0.0.1':
        return 'http://127.0.0.1:' + str(c['http_port'])
    return c['scheme'] + '://' + c['hostname'] + ':' + str(c['port'])


class Manager:
    def __init__(self, context, clock=time.time, timer=threading.Timer, monotonic=time.monotonic):
        self.c, self.clock, self.timer = context, clock, timer
        self.monotonic, self.deadline, self.deadline_operation = monotonic, None, None
        self.lock = threading.RLock()
        self.receipt = context.state / 'network-transaction.json'
        self.job = None
        self.expiry = None
        self.follower = context.b.common.module('network_follow').Supervisor(self) if hasattr(context, 'b') else None

    def read(self):
        try:
            value = json.loads(self.receipt.read_text())
        except FileNotFoundError:
            return None
        if (not isinstance(value, dict) or value.get('phase') not in
                (*ACTIVE, 'complete', 'cancelled', 'expired', 'failed')
                or not isinstance(value.get('operation'), str)):
            raise ValueError('Network transaction record needs administrator review.')
        return value

    def write(self, value):
        self.c.atomic(self.receipt, json.dumps(value) + '\n', mode=0o600)

    def later(self, seconds, fn, *args):
        timer = self.timer(seconds, fn, args=args)
        timer.daemon = True
        timer.start()
        return timer

    def public(self, value):
        if not value:
            return dict(phase='idle', message='Current settings saved.')
        result = {k: value[k] for k in ('operation', 'kind', 'phase', 'message', 'expires_at',
                                       'config', 'previous', 'url', 'local_url', 'trust_changed') if k in value}
        result['seconds_left'] = max(0, int(self.remaining(value)))
        return result

    def remaining(self, value):
        seconds = value.get('expires_at', 0) - self.clock()
        if self.deadline is not None and self.deadline_operation == value['operation']:
            seconds = min(seconds, self.deadline-self.monotonic())
        return seconds

    def status(self):
        # Receipts are atomically replaced. Status must remain responsive while
        # systemd starts/stops listeners in the background.
        return self.public(self.read())

    def ensure_idle(self):
        value = self.read()
        if value and value['phase'] in ACTIVE:
            raise ValueError('Confirm or cancel the pending network change first.')

    def write_web(self, name, contents):
        path = self.c.web_dir / name
        if contents is None:
            path.unlink(missing_ok=True)
        else:
            self.c.atomic(path, contents, mode=0o640)
            self.c.own_web(path)

    def stop_tests(self):
        errors = []
        for role in ('local', 'lan'):
            try:
                self.c.command(['/usr/bin/systemctl', 'stop', TEST.format(role)], 20)
                self.c.stopped(TEST.format(role))
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                errors.append(type(exc).__name__)
        if errors:
            raise ValueError('Temporary listener cleanup could not be verified. Review network services locally.')
        for name in ('test-local.json', 'test-lan.json', 'test-certificate.pem', 'test-key.pem'):
            (self.c.web_dir / name).unlink(missing_ok=True)

    def stage(self, data):
        with self.lock:
            self.ensure_idle()
            previous = self.c.config()
            value, files = self.c.material(data)
            if value == previous:
                raise ValueError('These network settings are already saved.')
            old = endpoints(previous)
            new = endpoints(value)
            for entry in new:
                for existing in old:
                    if (entry['address'], entry['port']) == (existing['address'], existing['port']) and endpoint_key(entry) != endpoint_key(existing):
                        raise ValueError('That address and port currently use another protocol. Choose an unused port for the connection test.')
            before = {name: (self.c.web_dir / name).read_text() if (self.c.web_dir / name).exists() else None for name in FILES}
            record = dict(operation=secrets.token_hex(16), phase='preparing', config=value,
                          previous=previous, files=files, before=before, url=url(value),
                          trust_changed=bool(files.get('local-network-ca.pem') and files['local-network-ca.pem'] != before.get('local-network-ca.pem')),
                          local_url=url(value, True), message='Opening the proposed connection. Current access stays available.')
            self.write(record)
            self.job = self.later(.2, self.prepare, record['operation'])
            return self.public(record)

    def renew(self):
        """Renew the active leaf with the same issuer, restoring it on failure.

        A durable before-image covers a crash during the LAN listener restart.
        The localhost listener and saved addresses are unchanged.
        """
        with self.lock:
            self.ensure_idle()
            value, files = self.c.renewal_material()
            before = {name: (self.c.web_dir/name).read_text() if (self.c.web_dir/name).exists()
                      else None for name in FILES}
            record = dict(operation=secrets.token_hex(16), kind='certificate-renew',
                          phase='committing', config=value, previous=value, files=files,
                          before=before, url=url(value), local_url=url(value, True),
                          message='Renewing and verifying the HTTPS server certificate. Localhost stays available.')
            self.write(record)
            self.job = self.later(.5, self.commit, record['operation'])
            return self.public(record)

    def prepare(self, operation):
        with self.lock:
            record = self.read()
            if not record or record['operation'] != operation or record['phase'] != 'preparing':
                return
            try:
                self.stop_tests()
                value = record['config']
                for name in ('certificate.pem', 'key.pem'):
                    if record['files'].get(name):
                        self.write_web('test-' + name, record['files'][name])
                old_keys = {endpoint_key(x) for x in endpoints(record['previous'])}
                for entry in endpoints(value):
                    role = 'lan' if entry['lan'] else 'local'
                    if endpoint_key(entry) not in old_keys:
                        cfg = dict(value, **entry)
                        self.write_web('test-' + role + '.json', json.dumps(cfg) + '\n')
                        self.c.command(['/usr/bin/systemctl', 'start', TEST.format(role)], 20)
                    self.c.ready(entry, record['files'].get('certificate.pem'))
                record.update(phase='pending', expires_at=self.clock() + WINDOW,
                              message='Test the proposed connection and confirm there. Current settings stay available until then.')
                self.deadline, self.deadline_operation = self.monotonic()+WINDOW, operation
                self.write(record)
                self.expiry = self.later(WINDOW, self.expire, operation)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                detail = str(exc)
                try:
                    self.stop_tests()
                except (OSError, ValueError, subprocess.SubprocessError) as cleanup:
                    detail += ' ' + str(cleanup)
                record.update(phase='failed', message=detail + ' Previous saved settings were not changed.')
                self.write(record)
            finally:
                self.job = None

    def expire(self, operation):
        with self.lock:
            record = self.read()
            if record and record['operation'] == operation and record['phase'] == 'pending':
                if self.remaining(record) <= 0:
                    self.cancel(operation, expired=True)
                else:
                    self.expiry = self.later(self.remaining(record), self.expire, operation)

    def cancel(self, operation, expired=False):
        with self.lock:
            record = self.read()
            if not record or record['operation'] != operation:
                raise ValueError('The pending network change no longer matches. Refresh settings.')
            if record['phase'] in ('cancelled', 'expired', 'cancelling'):
                return self.public(record)
            if record['phase'] not in ('preparing', 'pending'):
                raise ValueError('This network change can no longer be cancelled.')
            if self.expiry:
                self.expiry.cancel()
            record.update(phase='cancelling', message='Closing the connection test. Previous settings retained.')
            self.write(record)
            self.job = self.later(.2, self.finish_cancel, operation, expired)
            return self.public(record)

    def finish_cancel(self, operation, expired):
        with self.lock:
            record = self.read()
            if not record or record['operation'] != operation or record['phase'] != 'cancelling':
                return
            try:
                self.stop_tests()
                record.update(phase='expired' if expired else 'cancelled',
                    message='Confirmation timed out. Previous settings retained.' if expired else 'Change cancelled. Previous settings retained.')
                record.pop('files', None); record.pop('before', None)
            except (OSError, ValueError, subprocess.SubprocessError):
                record.update(phase='failed', message='Previous settings retained, but temporary listener cleanup needs local administrator review.')
            self.write(record)
            self.job = None

    def confirm(self, operation, origin):
        with self.lock:
            record = self.read()
            if not record or record['operation'] != operation:
                raise ValueError('The pending network change no longer matches. Refresh settings.')
            if record['phase'] in ('committing', 'complete') and origin == record['url']:
                return self.public(record)  # Lost-response retries do not repeat writes.
            if record['phase'] != 'pending' or self.remaining(record) <= 0:
                raise ValueError('The connection test expired or is not ready. Previous settings retained.')
            if origin != record['url']:
                raise ValueError('Open the proposed URL, sign in, and confirm from that connection.')
            record.update(phase='committing', message='Connection confirmed. Saving and verifying network settings…')
            self.write(record)
            if self.expiry:
                self.expiry.cancel()
            self.job = self.later(.5, self.commit, operation)
            return self.public(record)

    def apply_saved(self, value, previous, restoring=False):
        # The local listener is restarted only if its port changes.
        if value['http_port'] != previous['http_port']:
            self.c.command(['/usr/bin/systemctl', 'restart', LOCAL], 25)
        selected = self.c.selection(value) if self.follower else None
        available = bool(selected) if self.follower else value['lan']
        if available and self.follower and selected['address'] != value['address']:
            if restoring: available = False
            else: raise ValueError('The automatic address changed during confirmation. Review the new connection.')
        if self.follower and value['lan'] and not available and not restoring and value['address']!='127.0.0.1':
            raise ValueError('The proposed network address is no longer assigned. Previous settings will be restored.')
        if value['lan'] and available:
            self.c.command(['/usr/bin/systemctl', 'restart', LAN], 25)
            self.c.command(['/usr/bin/systemctl', 'enable', LAN], 10)
        elif value['lan']:
            self.c.command(['/usr/bin/systemctl', 'stop', LAN], 25)
            self.c.stopped(LAN)
            self.c.command(['/usr/bin/systemctl', 'enable', LAN], 10)
        else:
            self.c.command(['/usr/bin/systemctl', 'disable', '--now', LAN], 25)
            self.c.stopped(LAN)
        for entry in endpoints(value):
            if entry['lan'] and not available: continue
            cert = (self.c.web_dir / 'certificate.pem').read_text() if entry['scheme'] == 'https' else None
            self.c.ready(entry, cert)
        if hasattr(self.c, 'publish_port'):
            self.c.publish_port(value)
        if self.follower:
            if available: self.follower.verified(value, selected)
            else: self.follower.state('waiting' if value['lan'] else 'disabled', 'Waiting for a network address' if value['lan'] else 'Local network access is disabled.')

    def restore(self, record):
        for name, content in record['before'].items():
            self.write_web(name, content)
        self.apply_saved(record['previous'], record['config'], restoring=True)

    def commit(self, operation):
        with self.lock:
            record = self.read()
            if not record or record['operation'] != operation or record['phase'] != 'committing':
                return
            try:
                self.stop_tests()
                for name, content in record['files'].items():
                    self.write_web(name, content)
                self.apply_saved(record['config'], record['previous'])
                record.update(phase='complete', message=(
                    'Server certificate renewed and verified. Your installed trust certificate stays the same.'
                    if record.get('kind') == 'certificate-renew' else
                    'Automatic network address updated and listener verified.' if record.get('kind') == 'address-follow' else
                    'Connection confirmed and network settings saved.'))
                if record.get('trust_changed'):
                    record['message'] += ' HTTPS trust changed; import the displayed trust certificate on your other clients.'
                record.pop('files', None); record.pop('before', None)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                detail = str(exc)
                try:
                    self.restore(record)
                    detail += ' Previous settings restored and verified.'
                except (OSError, ValueError, subprocess.SubprocessError):
                    detail += ' Restoration could not be verified; use the previous localhost URL to review services.'
                record.update(phase='failed', message=detail)
            self.write(record)
            self.job = None

    def recover(self):
        """Called before serving requests after a broker restart."""
        with self.lock:
            record = self.read()
            self.stop_tests()
            if not record or record['phase'] not in ACTIVE:
                return
            if record['phase'] == 'committing':
                self.restore(record)
            record.update(phase='cancelled', message='Network test interrupted by restart. Previous saved settings retained.')
            record.pop('files', None); record.pop('before', None)
            self.write(record)
