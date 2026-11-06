# SPDX-License-Identifier: MIT
"""Package lifecycle hooks. Operate only on this package's service."""
import argparse
import json
from pathlib import Path
import subprocess
import os
import uuid

STATE=Path('/var/lib/usb-storage-watch')
SERVICE='usb-storage-watch.service'
MARKER=STATE/'package-was-active'


def call(*args, okay=(0,)):
    p=subprocess.run(['/usr/bin/systemctl',*args],timeout=45,capture_output=True,text=True)
    if p.returncode not in okay: raise RuntimeError('Service operation failed: '+args[0])
    return p.returncode


def pending(directory=STATE):
    path=directory/'usb-reset.json'
    if path.exists() and json.loads(path.read_text()).get('phase')!='enabled':
        raise RuntimeError('Unresolved USB re-enable obligation; keep installed helpers and resolve before removal/upgrade')


def instances():
    yield SERVICE,STATE,MARKER
    directory=STATE/'drives'
    if directory.exists():
        if directory.is_symlink():raise ValueError('Unsafe drive state directory')
        for path in sorted(directory.iterdir()):
            if path.is_symlink() or str(uuid.UUID(path.name))!=path.name:
                raise ValueError('Invalid drive state directory')
            yield 'usb-storage-watch@'+path.name+'.service',path,path/'package-was-active'


def main(action):
    if os.environ.get('DPKG_ROOT'): return
    if os.geteuid()!=0: raise PermissionError('Root required')
    systemd=Path('/run/systemd/system').is_dir()
    boot_units = Path('/usr/lib/systemd/system/usb-storage-watch-boot.timer').exists()
    if action in ('prepare-upgrade','prepare-remove'):
        if systemd and boot_units:
            call('stop', 'usb-storage-watch-boot.timer', 'usb-storage-watch-boot.service')
            if action == 'prepare-remove': call('disable', 'usb-storage-watch-boot.timer', okay=(0,1))
        for service,directory,marker in instances():
            if systemd:
                active=call('is-active','--quiet',service,okay=(0,3,4))==0
                if active:
                    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
                    if action=='prepare-upgrade': marker.touch(mode=0o600)
                    call('stop',service)
            pending(directory)
            if action=='prepare-remove':
                if systemd: call('disable',service,okay=(0,1))
                marker.unlink(missing_ok=True)
    elif action=='finish-upgrade':
        if systemd:
            call('daemon-reload')
            if boot_units: call('enable', '--now', 'usb-storage-watch-boot.timer')
            for service,directory,marker in instances():
                if marker.exists():call('start',service);marker.unlink()
    elif action=='reload' and systemd: call('daemon-reload')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('prepare-upgrade','prepare-remove','finish-upgrade','reload'))
    try: main(parser.parse_args().action)
    except Exception as exc:
        print('Package maintenance stopped: '+str(exc));raise SystemExit(1)
