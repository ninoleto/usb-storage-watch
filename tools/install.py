#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Install/upgrade/remove only USB Storage Watch. --root stages without host actions."""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import tempfile

SOURCE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('maintenance',SOURCE/'src/usb_storage_watch/maintenance.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
spec=importlib.util.spec_from_file_location('web_install',SOURCE/'src/usb_storage_watch/web_install.py')
web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
MANIFEST='var/lib/usb-storage-watch/install-manifest.json'
ALLOWED=('usr/lib/usb-storage-watch/','usr/share/doc/usb-storage-watch/')
SINGLES=('usr/sbin/usb-storage-watch','usr/lib/systemd/system/usb-storage-watch.service','usr/lib/systemd/system/usb-storage-watch@.service',
         'usr/lib/systemd/system/usb-storage-watch-boot.service','usr/lib/systemd/system/usb-storage-watch-boot.timer',
         'usr/lib/systemd/system/usb-storage-watch-web.service',
         'usr/lib/systemd/system/usb-storage-watch-lan.service',
         'usr/lib/systemd/system/usb-storage-watch-network-test@.service',
         'usr/lib/systemd/system/usb-storage-watch-broker.service','etc/pam.d/usb-storage-watch-web',
         'usr/share/applications/usb-storage-watch.desktop',
         'usr/share/icons/hicolor/scalable/apps/usb-storage-watch.svg')


def target(root,relative):
    p=root/relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts: raise ValueError('Invalid package path')
    for part in [*reversed(p.parents),p]:
        if part.is_symlink(): raise ValueError('Refusing symlink in installation path: '+str(part))
    return p


def payload():
    files={}
    for p in (SOURCE/'src/usb_storage_watch').glob('*.py'):
        files['usr/lib/usb-storage-watch/'+p.name]=p
    files['usr/sbin/usb-storage-watch']=SOURCE/'packaging/usb-storage-watch'
    files['usr/lib/systemd/system/usb-storage-watch.service']=SOURCE/'packaging/usb-storage-watch.service'
    for name in ('usb-storage-watch-boot.service','usb-storage-watch-boot.timer','usb-storage-watch@.service','usb-storage-watch-web.service','usb-storage-watch-broker.service','usb-storage-watch-lan.service','usb-storage-watch-network-test@.service'):
        files['usr/lib/systemd/system/'+name]=SOURCE/'packaging'/name
    files['usr/share/applications/usb-storage-watch.desktop']=SOURCE/'packaging/usb-storage-watch.desktop'
    files['usr/share/icons/hicolor/scalable/apps/usb-storage-watch.svg']=SOURCE/'src/usb_storage_watch/web_static/icon.svg'
    files['etc/pam.d/usb-storage-watch-web']=SOURCE/'packaging/usb-storage-watch-web.pam'
    for p in (SOURCE/'src/usb_storage_watch/web_static').glob('*'):
        if p.is_file(): files['usr/lib/usb-storage-watch/web_static/'+p.name]=p
    for name in ('module.tgz','module.json'):
        p=SOURCE/'src/usb_storage_watch/companion'/name
        if p.is_file(): files['usr/lib/usb-storage-watch/companion/'+name]=p
    for p in (SOURCE/'src/usb_storage_watch/_vendor').rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
            files['usr/lib/usb-storage-watch/_vendor/'+str(p.relative_to(SOURCE/'src/usb_storage_watch/_vendor'))]=p
    for name in ('README.md','LICENSE','THIRD-PARTY-NOTICES.md','CHANGELOG.md'):
        files['usr/share/doc/usb-storage-watch/'+name]=SOURCE/name
    for dirname in ('docs','examples'):
        for p in (SOURCE/dirname).glob('*'):
            if p.is_file(): files['usr/share/doc/usb-storage-watch/'+dirname+'/'+p.name]=p
    return files


def copy_atomic(source,destination,mode):
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=destination.parent,prefix='.usw-install-')
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(source.read_bytes());os.fchmod(f.fileno(),mode);f.flush();os.fsync(f.fileno())
        os.replace(tmp,destination)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def install(root,remove=False,headless=False):
    # New program directories must never inherit a permissive caller umask.
    os.umask(0o022)
    root=Path(root).absolute()
    if root.resolve()!=root: raise ValueError('Root must not contain symlinks')
    live=str(root)=='/'
    if live and os.geteuid()!=0: raise PermissionError('Use sudo for a live installation')
    if live and Path('/var/lib/dpkg/info/usb-storage-watch.list').exists():
        raise ValueError('Managed by dpkg; upgrade/remove with apt instead')
    manifest=target(root,MANIFEST)
    files=payload()
    for p in files: target(root,p)
    if live:
        m.main('prepare-remove' if remove else 'prepare-upgrade')
        if (Path('/usr/lib/usb-storage-watch/web_install.py')).exists():
            web.main('prepare-remove' if remove else 'prepare-upgrade')
    # Also check staged ledgers; never remove an unresolved enable obligation.
    m.pending(target(root,'var/lib/usb-storage-watch'))
    profiles=target(root,'var/lib/usb-storage-watch/drives')
    if profiles.exists():
        for profile in profiles.iterdir():
            m.pending(target(root,str(profile.relative_to(root))))
    if remove:
        if not manifest.exists(): raise ValueError('Portable install manifest absent; nothing removed')
        prior=json.loads(manifest.read_text())
        for p in prior:
            if p not in SINGLES and not any(p.startswith(x) for x in ALLOWED): raise ValueError('Invalid installed manifest')
            target(root,p)
        for p in prior: target(root,p).unlink(missing_ok=True)
        manifest.unlink()
        if live: m.main('reload')
        print('Program removed. Configuration, delivery queue and recovery history retained.');return
    configdir=target(root,'etc/usb-storage-watch');configdir.mkdir(mode=0o700,parents=True,exist_ok=True)
    statedir=manifest.parent;statedir.mkdir(mode=0o700,parents=True,exist_ok=True)
    for d in (configdir,statedir):
        if d.stat().st_uid!=os.geteuid() or d.stat().st_mode&0o077: raise ValueError('Config/state directories require owner-only permissions')
    backups=statedir/'backups'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    for p in files:
        dest=target(root,p)
        if dest.exists(): copy_atomic(dest,target(root,str(backups.relative_to(root)/p)),0o600)
    for p,source in files.items(): copy_atomic(source,target(root,p),0o755 if p in SINGLES[:1] else 0o644)
    manifest.write_text(json.dumps(sorted(files),indent=2)+'\n');manifest.chmod(0o600)
    if live:
        m.main('finish-upgrade')
        web.main('finish-upgrade',headless=headless)
    print(('Installed' if live else 'Staged')+' USB Storage Watch. Monitor activation remains explicit. Configuration/history preserved.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',default='/');p.add_argument('--uninstall',action='store_true');p.add_argument('--headless',action='store_true');a=p.parse_args()
    try: install(a.root,a.uninstall,a.headless)
    except Exception as exc: print('Installation stopped: '+str(exc),file=sys.stderr);raise SystemExit(1)
