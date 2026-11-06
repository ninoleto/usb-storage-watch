# SPDX-License-Identifier: MIT
"""Supervise only this app's single-address LAN listener; localhost is independent."""
import hashlib
import json
import secrets
import subprocess
import threading
import time

LAN = 'usb-storage-watch-lan.service'
ACTIVE = ('preparing', 'pending', 'committing', 'cancelling')


class Supervisor:
    def __init__(self, manager, clock=time.monotonic):
        self.m, self.c, self.clock = manager, manager.c, clock
        self.live = dict(phase='checking', message='Checking the network listener.', url=None)
        self.verified_config = None
        self.verified_at = 0
        self.retry_key, self.retry_at = None, 0
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.thread = threading.Thread(target=self.loop, name='usw-network-address', daemon=True)
        self.thread.start()

    def loop(self):
        while True:
            self.tick()
            time.sleep(3)

    def state(self, phase, message, selected=None):
        self.live = dict(phase=phase, message=message, url=None,
                         interface=(selected or {}).get('interface'), address=(selected or {}).get('address'))

    def verified(self, config, selected):
        self.verified_config, self.verified_at = dict(config), self.clock()
        self.state('ready', 'Network listener verified on ' + selected['interface'] + '.', selected)
        self.live['url'] = config['scheme']+'://'+config['hostname']+':'+str(config['port'])

    def public(self, config, addresses):
        selected = self.c.selection(config, addresses)
        if not config['lan']: return dict(phase='disabled', message='Local network access is disabled.', url=None)
        if not selected:
            return dict(phase='waiting' if config['address_mode']=='automatic' else 'unavailable', url=None,
                message='Waiting for a network address' if config['address_mode']=='automatic' else
                        'The selected manual address is unavailable. Switch to Automatic to follow the current connection.')
        value = dict(self.live)
        if (self.verified_config != config or self.clock()-self.verified_at > 12 or
                value.get('address') != selected['address'] or value.get('interface') != selected.get('interface')):
            value['url'] = None
            if value['phase']=='ready': value.update(phase='checking', message='Verifying the selected network listener.')
        value.update(selected_address=selected['address'], selected_interface=selected.get('interface'))
        return value

    def stop(self):
        service = self.c.service()
        if service.get('ActiveState') not in ('inactive', 'failed') or service.get('MainPID', '0') != '0':
            self.c.command(['/usr/bin/systemctl', 'stop', LAN], 20)
            self.c.stopped(LAN)

    def signature(self, config, selected):
        hashes = []
        for name in ('certificate.pem', 'key.pem', 'local-network-ca.pem'):
            path = self.c.web_dir/name
            hashes.append(hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else '')
        return json.dumps([config, selected, hashes], sort_keys=True)

    def tick(self):
        if not self.m.lock.acquire(blocking=False): return
        try:
            if getattr(self.m, 'recovery_error', ''): return
            receipt = self.m.read()
            if receipt and receipt['phase'] in ACTIVE: return
            config = self.c.config()
            if not config['lan']:
                self.state('disabled', 'Local network access is disabled.')
                self.stop(); self.retry_key = None
                return
            rows = self.c.addresses(); selected = self.c.selection(config, rows)
            if not config['lan'] or not selected:
                self.state('disabled' if not config['lan'] else 'waiting', 'Waiting for a network address')
                self.stop(); self.retry_key = None
                return
            key = self.signature(config, selected)
            if self.retry_key == key and self.clock() < self.retry_at: return
            if (self.verified_config != config or self.live.get('address') != selected['address'] or
                    self.live.get('interface') != selected.get('interface')):
                self.state('checking', 'Verifying the selected network listener.', selected)
            try:
                if config['address_mode']=='automatic' and (selected['address'] != config['address'] or
                        (config['scheme']=='https' and not self.c.certificate_covers(selected['address']))):
                    value, files = self.c.follow_material(config, selected['address'])
                    before = {name:(self.c.web_dir/name).read_text() if (self.c.web_dir/name).exists() else None
                              for name in ('config.json','certificate.pem','key.pem','local-network-ca.pem')}
                    record = dict(operation=secrets.token_hex(16), kind='address-follow', phase='committing',
                        config=value, previous=config, files=files, before=before,
                        message='Following the selected physical connection; verifying the listener.')
                    self.m.write(record)
                    self.m.commit(record['operation'])
                    if self.m.read()['phase'] != 'complete': raise ValueError('Automatic listener change failed validation.')
                    config = self.c.config()
                else:
                    service = self.c.service()
                    if service.get('ActiveState') != 'active':
                        self.c.command(['/usr/bin/systemctl', 'start', LAN], 20)
                    elif self.verified_config is not None and self.verified_config != config:
                        self.c.command(['/usr/bin/systemctl', 'restart', LAN], 20)
                    cert = (self.c.web_dir/'certificate.pem').read_text() if config['scheme']=='https' else None
                    self.c.ready(config, cert)
                current = self.c.selection(config)
                if not current or current['address'] != config['address'] or current.get('interface') != selected.get('interface'):
                    raise ValueError('Address changed during listener verification.')
                self.verified(config, current); self.retry_key = None
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                detail = str(exc) if str(exc).startswith(('HTTPS certificate', 'Prepare and trust')) else 'Network listener could not be verified. Check the selected address, port and HTTPS certificate; localhost remains available.'
                self.state('error', detail, selected)
                self.retry_key, self.retry_at = key, self.clock()+60
                self.stop()
        except Exception:
            # A discovery/service error must not kill supervision or publish stale URLs.
            self.state('error', 'Local network discovery or listener supervision is unavailable; localhost remains available.')
        finally:
            self.m.lock.release()
