# SPDX-License-Identifier: MIT
"""Small cross-drive safeguards; recovery itself remains in the existing engine."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from types import SimpleNamespace
import uuid

_local = threading.local()


def profile_id(value):
    if value != 'legacy' and (not isinstance(value,str) or str(uuid.UUID(value)) != value):
        raise ValueError('Invalid drive profile identifier.')
    return value


def roots(s):
    return (s.CONFIG.parent,s.STATE_DIR) if s.PROFILE_ID=='legacy' else (s.CONFIG_ROOT,s.STATE_ROOT)


def files(s):
    config,_=roots(s)
    if (config/'config.json').exists():yield 'legacy',config/'config.json'
    directory=config/'drives'
    if directory.exists():
        if directory.is_symlink():raise ValueError('Drive configuration directory must not be a symlink.')
        for path in sorted(directory.iterdir()):
            profile_id(path.name)
            if path.is_symlink():raise ValueError('Drive configuration must not contain symlinks.')
            if (path/'config.json').exists():yield path.name,path/'config.json'


def read(s,path):
    parent=path.parent.stat()
    if parent.st_uid!=os.geteuid() or parent.st_mode & 0o077:raise ValueError('Drive configuration must be private and administrator-owned.')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    with os.fdopen(fd) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.geteuid() or info.st_mode & 0o077:
            raise ValueError('Drive configuration permissions are unsafe.')
        return s.validate(json.load(stream))


@contextmanager
def lock(directory,name):
    directory=Path(directory)
    if directory.resolve()!=directory:raise ValueError('Shared lock directory must not contain symlinks.')
    directory.mkdir(parents=True,mode=0o700,exist_ok=True)
    info=directory.stat()
    if info.st_uid!=os.geteuid() or info.st_mode & 0o077:raise ValueError('Shared locks must be private and administrator-owned.')
    path=directory/name;held=getattr(_local,'held',{})
    if str(path) in held:
        yield held[str(path)];return
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode & 0o077 or info.st_nlink!=1:raise ValueError('Unsafe shared operation lock.')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        held[str(path)]=fd;_local.held=held
        try:yield fd
        finally:held.pop(str(path),None)
    finally:os.close(fd)


def configuration_lock(s):return lock(roots(s)[1]/'shared-locks','configuration.lock')


def validate_shared(s,c):
    """Filesystems and service units have one owner; containers may select several drives."""
    own={c['disk']['uuid']}|{v['uuid'] for v in s.storage_images(c,False)}
    for identifier,path in files(s):
        if path==s.CONFIG:continue
        other=read(s,path)
        foreign={other['disk']['uuid']}|{v['uuid'] for v in s.storage_images(other,False)}
        if own & foreign:raise ValueError('This filesystem UUID already belongs to another drive profile.')
        a,b=c['disk']['mountpoint'],other['disk']['mountpoint']
        if a==b or s.below(a,b) or s.below(b,a):raise ValueError('Drive mount locations must not overlap another monitored drive.')
        if set(c['services']['units']) & set(other['services']['units']):
            raise ValueError('That application service already has a recovery owner on another drive.')


def unique_uuid(w,dev,expected,cache=Path('/run/udev/data'),sysblock=Path('/sys/dev/block')):
    # Kernel/udev metadata only: never blkid/probe/read a sleeping filesystem.
    for path in cache.glob('b*'):
        other=path.name[1:]
        if other==dev or not (sysblock/other).exists():continue
        try:matched='E:ID_FS_UUID='+expected in path.read_text().splitlines()
        except FileNotFoundError:continue
        if matched:raise w.Unsafe('Duplicate filesystem UUID on connected devices; no disk operation is permitted.')


def hardware(w,dev,expected):
    props=w.udev(dev);node=(Path('/sys/dev/block')/dev).resolve(strict=True)
    whole=node.parent if (node/'partition').exists() else node
    parent=w.udev((whole/'dev').read_text().strip())
    return dict(uuid=expected,serial=parent.get('ID_SERIAL') or props.get('ID_SERIAL',''),
                wwn=parent.get('ID_WWN') or props.get('ID_WWN',''),
                vendor=parent.get('ID_VENDOR_ID') or props.get('ID_VENDOR_ID',''),
                product=parent.get('ID_MODEL_ID') or props.get('ID_MODEL_ID',''),
                size=int((whole/'size').read_text())*512)


def verify_hardware(w,dev,expected):
    if expected!=w.DISK_UUID:return
    path=w.STATE_DIR/'drive-identity.json'
    if path.exists():
        saved=json.loads(path.read_text())
        if saved.get('uuid')!=expected:raise w.Unsafe('Saved hardware identity belongs to another filesystem; administrator review required.')
        current=hardware(w,dev,expected)
        if saved!=current:raise w.Unsafe('Filesystem UUID returned on different hardware; disk operation refused.')
    else:
        # Preserve the DEV7 verified identity until a complete pin can be enrolled.
        old=w.usb.current_record(w)
        serial=(old or {}).get('serial') or (w.SETTINGS.get('usb',{}).get('profile') or {}).get('disk_serial')
        if serial and w.udev(dev).get('ID_SERIAL')!=serial:raise w.Unsafe('Filesystem UUID belongs to different USB hardware.')


def enroll(w,dev):
    path=w.STATE_DIR/'drive-identity.json'
    if path.exists():return
    value=hardware(w,dev,w.DISK_UUID)
    if value['serial'] or value['wwn']:
        w.atomic_write(path,json.dumps(value)+'\n')


@contextmanager
def port_lock(w,canonical):
    root=w.STATE_DIR if w.settings.PROFILE_ID=='legacy' else w.settings.STATE_ROOT
    with lock(root/'shared-locks','port-'+hashlib.sha256(canonical.encode()).hexdigest()+'.lock') as fd:
        # Durable obligations also exclude a later process after a crashed owner.
        for ledger in [root/'usb-reset.json',*(root/'drives').glob('*/usb-reset.json')]:
            if ledger.parent==w.STATE_DIR:continue
            if ledger.exists():
                value=json.loads(ledger.read_text())
                if value.get('phase')!='enabled':
                    if not isinstance(value.get('port'),str) or not value['port'].startswith('/'):
                        raise w.Unsafe('Another drive has an invalid USB cleanup record; port reconnect requires administrator review.')
                    if value['port']==canonical:
                        raise w.Unsafe('Another drive has an unresolved enable obligation on this USB port.')
        previous=w.WORKER_LOCK_FDS;w.WORKER_LOCK_FDS=(*previous,fd)
        try:yield fd
        finally:w.WORKER_LOCK_FDS=previous


def verify_other_storage(w,paths=()):
    """Check shared Docker bind storage without inspecting Docker or file data."""
    for identifier,path in files(w.settings):
        if path==w.CONFIG:continue
        c=read(w.settings,path);mount=c['disk']['mountpoint']
        if not any(w.covers(mount,p) for p in paths):continue
        dev=w.device_number('/dev/disk/by-uuid/'+c['disk']['uuid'])
        w.mounted_checks(w.read_rows(),mount,dev,c['disk']['uuid'])
        _,root=roots(w.settings)
        other=SimpleNamespace(**vars(w));other.DISK_UUID=c['disk']['uuid'];other.SETTINGS=c
        other.STATE_DIR=root if identifier=='legacy' else root/'drives'/identifier
        verify_hardware(other,dev,c['disk']['uuid'])
        for item in w.apps.required_images(w,paths,c):
            if not item['enabled']:
                raise w.Unsafe('A mapped folder requires an image with Mount on recovery disabled.')
            w.dependent_metadata(w.read_rows(),item)
