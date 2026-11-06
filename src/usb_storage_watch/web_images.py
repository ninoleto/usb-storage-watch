# SPDX-License-Identifier: MIT
"""Explicit application-image setup; recovery never creates or formats images."""
import os
import json
import copy
from contextlib import contextmanager
import pwd
import grp
from pathlib import Path
import re
import secrets
import stat
import time
import uuid


class ImageMonitorResumeError(ValueError):
    """Image work ended, but the previously running monitor could not resume."""


def entries(b):
    c=b.configuration()
    if c['disk']['uuid']:b.w.configure(c)
    rows=b.w.read_rows();result=[]
    for item in b.s.storage_images(c,enabled=False):
        mounted=any(row['target']==item['mountpoint'] for row in rows)
        value=dict(item,mounted=mounted,verified=False,mount_state='unmounted',mount_message='Unmounted',
                   accessible=None,access_state='unknown',access_message='Mount this image to check folder access.')
        # Size describes this existing regular backing file, not its mounted free
        # space. Never follow symlinks; if it cannot be inspected, report unknown
        # rather than the incorrect 0 GiB previously shown by the dashboard.
        try:
            info=Path(item['image']).lstat()
            if stat.S_ISREG(info.st_mode) and info.st_nlink==1:
                value['size']=info.st_size
        except OSError:
            pass
        if mounted:
            value.update(mount_state='verification-failed',mount_message='Mounted — verification failed')
            try:
                # Mount presence and identity come from mountinfo, udev and loop
                # metadata. A failed credential drop is not an unmount event.
                b.w.dependent_metadata(rows,item)
                value.update(verified=True,mount_state='mounted',mount_message='Mounted read/write — UUID and loop identity verified')
            except (OSError,ValueError,b.w.Unsafe) as exc:value.update(mount_error=str(exc))
            if value['verified'] and getattr(b,'owner',None):
                try:
                    access=account_access(b,item['mountpoint'],b.owner)
                    allowed=all(access.values())
                    value.update(accessible=allowed,access_state='accessible' if allowed else 'denied',
                                 access_message='Accessible to your local account.' if allowed else 'Access denied: your local account needs folder permissions.')
                except (OSError,ValueError) as exc:value.update(access_state='inspection-failed',access_message='Access inspection failed: '+str(exc))
            try:
                info=Path(item['mountpoint']).stat()
                value['permissions']=dict(uid=info.st_uid,gid=info.st_gid,mode=oct(stat.S_IMODE(info.st_mode)))
            except OSError:pass
        result.append(value)
    return result


def discover(b, directory_limit=400, file_limit=4000):
    """Bounded, read-only discovery within the verified primary USB mount.

    We never follow symlinks or traverse other filesystems (including already
    mounted loop images). Returned paths are candidates, not import approval:
    the existing plan() performs authoritative ext4 and UUID verification.
    """
    c=b.configuration()
    if not c['disk']['uuid']:
        return dict(images=[],truncated=False)
    b.w.configure(c)
    b.w.verify_main()
    mount=Path(b.w.MOUNT)
    root=mount.stat()
    registered={item['image'] for item in b.s.storage_images(c,False)}
    discovered=[];count_dirs=0;count_files=0;truncated=False
    for current, dirs, files in os.walk(mount,topdown=True,followlinks=False):
        here=Path(current)
        depth=len(here.relative_to(mount).parts)
        count_dirs+=1
        if count_dirs>directory_limit:
            truncated=True;break
        valid=[]
        for name in dirs:
            child=here/name
            try:
                info=child.lstat()
                if depth<7 and stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_dev==root.st_dev:
                    valid.append(name)
            except OSError:pass
        dirs[:]=valid
        for name in files:
            count_files+=1
            if count_files>file_limit:truncated=True;break
            if not name.lower().endswith('.img'):continue
            path=here/name
            try:
                info=path.lstat()
                if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or info.st_nlink!=1 or info.st_dev!=root.st_dev or str(path) in registered):continue
            except OSError:continue
            discovered.append(dict(name=path.stem,path=str(path),size=info.st_size))
            if len(discovered)>=100:truncated=True;break
        if truncated:break
    return dict(images=discovered,truncated=truncated)


def local_accounts():
    users=[dict(name=a.pw_name,label=a.pw_gecos.split(',')[0] or a.pw_name) for a in pwd.getpwall()
           if 1000<=a.pw_uid<65534 and a.pw_shell not in ('/usr/sbin/nologin','/sbin/nologin','/bin/false')]
    groups=[g.gr_name for g in grp.getgrall() if g.gr_gid<65534 and g.gr_name not in ('root','usb-storage-watch-web')]
    return dict(users=users,groups=sorted(groups))


def access_policy(data,owner):
    if data is None:data={}
    if not isinstance(data,dict):raise ValueError('Choose image access permissions.')
    kind=data.get('kind','user')
    if kind not in ('user','applications','selected','custom'):raise ValueError('Choose image access permissions.')
    users=[dict(uid=owner[0],gid=owner[1],rights='rwx')];group=None
    if kind=='selected':
        names=data.get('users',[]);allowed={v['name'] for v in local_accounts()['users']}
        if not isinstance(names,list) or not 1<=len(names)<=16 or any(not isinstance(v,str) or v not in allowed for v in names):raise ValueError('Select one or more available local user accounts.')
        for name in names:
            account=pwd.getpwnam(name)
            if account.pw_uid!=owner[0]:users.append(dict(uid=account.pw_uid,gid=account.pw_gid,rights='rwx'))
    elif kind=='applications':
        name=data.get('group')
        try:group=grp.getgrnam(name).gr_gid if name else owner[1]
        except (KeyError,TypeError):raise ValueError('Choose an available local application group.') from None
        if group<=0 or group>=65534:raise ValueError('Choose a non-system-root application group.')
    elif kind=='custom':
        uid,gid=data.get('uid'),data.get('gid');rights=data.get('rights','rwx')
        if any(type(v) is not int or not 1<=v<=2147483646 for v in (uid,gid)) or rights not in ('rwx','r-x'):
            raise ValueError('Enter valid additional user/group IDs and read/write or read-only access in Technical settings.')
        if uid!=owner[0]:users.append(dict(uid=uid,gid=gid,rights=rights,local=False))
        group=gid
    return dict(kind=kind,users=users,group=group,group_rights=data.get('rights','rwx') if kind=='custom' else 'rwx',
                inherit=kind!='user')


def rooted(b, path, create=False):
    """Pin directory components on the verified primary filesystem, without symlinks."""
    base=b.w.MOUNT
    b.s.absolute(path,'Storage path')
    if path != base and not b.s.below(base,path): raise ValueError('Choose a location inside the selected drive.')
    dev=b.w.verify_main()
    expected=os.makedev(*map(int,dev.split(':')))
    fd=os.open(base,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        for part in Path(path).relative_to(base).parts:
            if os.fstat(fd).st_dev != expected: raise ValueError('Storage directory changed filesystem.')
            created=False
            if create:
                try: os.mkdir(part,mode=0o755,dir_fd=fd);created=True
                except FileExistsError: pass
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            if created: os.fchmod(child,0o755)  # broker umask must not hide new mount parents
            os.close(fd);fd=child
        if os.fstat(fd).st_dev != expected: raise ValueError('Choose a folder directly on the primary drive.')
        return fd
    except BaseException:
        os.close(fd);raise


def probe(b,path):
    parent=rooted(b,str(Path(path).parent))
    try: fd=os.open(Path(path).name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
    finally: os.close(parent)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1: raise ValueError('Choose a regular ext4 image file, without links.')
        pinned='/proc/self/fd/'+str(fd)
        output=b.preparation.run(['/usr/sbin/blkid','-p','-o','export',pinned],fds=(fd,)).stdout
        props=dict(line.split('=',1) for line in output.splitlines() if '=' in line)
        if props.get('TYPE')!='ext4': raise ValueError('This file is not an ext4 filesystem image.')
        b.s.disk_uuid(props.get('UUID',''))
        b.w.superblock(os.pread(fd,1024,1024),props['UUID'],False)
        return dict(uuid=props['UUID'],inode=info.st_ino,device=info.st_dev,size=info.st_size)
    finally: os.close(fd)


def proposal(b,data):
    c=b.configuration();b.w.configure(c)
    mode=data.get('mode')
    if mode not in ('create','existing','edit'): raise ValueError('Choose new or existing Virtual Disk Image.')
    name=data.get('name','').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}',name): raise ValueError('Use a name of 1–40 letters, numbers, spaces, dots or dashes.')
    slug=re.sub(r'[^A-Za-z0-9_-]','-',name).strip('-')
    path=(data.get('image') or b.w.MOUNT+'/usb-storage-watch-volumes/.images/'+slug+'.img') if mode=='create' else data.get('image','')
    mount=data.get('mountpoint') or b.w.MOUNT+'/usb-storage-watch-volumes/'+slug
    for value in (path,mount):
        b.s.absolute(value,'Storage location')
        if not b.s.below(b.w.MOUNT,value): raise ValueError('Choose locations inside the selected USB drive.')
    if b.w.covers(mount,path): raise ValueError('The image file cannot be inside its own mount folder.')
    old=next((item for item in b.s.storage_images(c,False) if item['uuid']==data.get('original_uuid')),None)
    if mode=='edit' and not old: raise ValueError('The selected image configuration changed.')
    if old and (path != old['image'] or mount != old['mountpoint']):
        others=[v for v in b.s.storage_images(c,False) if v != old]
        if any(b.w.covers(old['mountpoint'],v[key]) for v in others for key in ('image','mountpoint')):
            raise ValueError('Other images use this mount folder. Update their settings first.')
    if old and any(b.w.covers(old['mountpoint'],r['target']) for r in b.w.read_rows()):
        raise ValueError('Unmount this virtual disk image safely before editing its location.')
    observed=None
    if mode=='create':
        size=data.get('size_gb',data.get('size_gib'))
        if isinstance(size,bool) or not isinstance(size,(int,float)) or not .125<=size<=65536: raise ValueError('Choose a size from 0.125 GB upwards, within the drive’s free space.')
        size=int(size*(1000**3 if 'size_gb' in data else 1024**3))
        if Path(path).exists() or Path(path).is_symlink(): raise ValueError('That image file already exists. Add it as existing storage; it will not be overwritten.')
        fs_uuid=str(uuid.uuid4())
    else:
        observed=probe(b,path);fs_uuid=observed['uuid'];size=observed['size']
    item=dict(name=name,enabled=True,uuid=fs_uuid,image=path,mountpoint=mount,
              fstab_options='loop,nofail,nodev,nosuid,noexec,x-systemd.requires-mounts-for='+b.w.MOUNT)
    other=[v for v in b.s.storage_images(c,False) if not old or v['uuid']!=old['uuid']]
    c['dependent']['enabled']=False;c['images']=other+[item];b.s.validate(c)
    if any(b.w.covers(mount,r['target']) for r in b.w.read_rows()): raise ValueError('The chosen mount folder is already in use.')
    if Path(mount).exists() and (not Path(mount).is_dir() or next(Path(mount).iterdir(),None) is not None):
        raise ValueError('Choose an empty folder for Virtual Disk Image.')
    # Never replace unrelated fstab entries or adopt an attached image silently.
    old_entry=old and (old['image'],old['mountpoint'])
    for fields in b.fstab_entries():
        if (fields[0],b.w.unescape_mount(fields[1]))==old_entry: continue
        if fields[0]==path or b.w.unescape_mount(fields[1])==mount:
            raise ValueError('An existing permanent mount uses this image or folder. Keep its current configuration.')
    if mode!='create' and any(p.read_text().strip()==path for p in Path('/sys/class/block').glob('loop*/loop/backing_file')):
        raise ValueError('This image is already attached. Unmount it before adding or editing its configuration.')
    return dict(item=item,old=old,observed=observed,size=size,mode=mode,config=c)


def _preflight_change(b):
    """Refuse a config change during a pending recovery or unresolved USB reset.

    This is intentionally read-only. A monitor may be running; its durable
    state is authoritative, not the web page's cached status.
    """
    state_path=b.s.STATE_DIR/'state.json'
    if state_path.exists():
        state=json.loads(state_path.read_text())
        incident=state.get('incident')
        if incident and incident.get('phase') not in ('done','legacy'):
            raise ValueError('Recovery is in progress for this drive. Wait until it finishes before changing Virtual Disk Images.')
    reset_path=b.s.STATE_DIR/'usb-reset.json'
    if reset_path.exists():
        reset=json.loads(reset_path.read_text())
        if reset.get('phase')!='enabled':
            raise ValueError('USB reconnection cleanup is unfinished. Resolve it before changing Virtual Disk Images.')


@contextmanager
def _image_transaction(b):
    """Per-drive, monitored OR stopped image update.

    Keep the shared config lock and a per-drive preparation lock throughout.
    If the selected monitor is active, stop only that unit briefly: the engine
    intentionally fails closed on configuration digest changes and must reload
    the new image dependency set before it resumes monitoring. Never toggle
    unit enablement, touch another drive, or bypass monitor/recovery locks.
    """
    resume_monitor=False
    try:
        with b.preparation.exclusive(b,own_monitor=False) as lock:
            service=b.service_state().get('ActiveState')
            if service not in ('active','inactive','failed'):
                raise ValueError("This drive's monitoring service is changing state. Try again when it settles.")
            _preflight_change(b)
            was_running=service=='active'
            if was_running:
                # The main filesystem must be positively verified before any stop.
                b.w.verify_main()
            resume_monitor=was_running
            if was_running:
                b.command(['/usr/bin/systemctl','stop',b.cli.SERVICE],35)
            # The monitor lock MUST be acquired after systemctl stop; it is
            # held for all image/mount/config mutations, excluding any worker
            # that survived a service stop.
            with b.migration.drive_exclusive(b):
                yield lock
    finally:
        if resume_monitor:
            try:
                # Release the configuration and monitor locks before starting a
                # fresh service process: it must read that configuration itself.
                # A failed/ambiguous stop may have actually succeeded, so still
                # restore the previous active state when possible.
                if b.service_state().get('ActiveState')!='active':
                    b.command(['/usr/bin/systemctl','start',b.cli.SERVICE],35)
                if b.service_state().get('ActiveState')!='active':
                    raise ValueError('Monitoring service did not become active.')
            except (OSError,ValueError) as exc:
                raise ImageMonitorResumeError('Image changes may have been saved, but monitoring could not resume automatically. Check this drive in Manage Drive; other drives are unaffected.') from exc


@contextmanager
def _manual_mount(b):
    """An explicit image Mount may run with automatic recovery switched off."""
    previous=getattr(b.w,'MANUAL_MOUNT',False)
    b.w.MANUAL_MOUNT=True
    try:
        yield
    finally:
        b.w.MANUAL_MOUNT=previous


def plan(b,data):
    # Read-only review is allowed while monitoring; it does not mutate a disk.
    with b.preparation.exclusive(b,own_monitor=False):
        _preflight_change(b)
        value=proposal(b,data)
        return dict(**value,data=data,revision=b.preparation.revision(b),token=secrets.token_urlsafe(32),created=time.monotonic())


def public(value):
    return dict(item=value['item'],size=value['size'],mode=value['mode'],token=value['token'],
                message=('Create and format only this new image file. Existing disk files will be kept. If monitoring is on, the app will briefly pause and resume it automatically.' if value['mode']=='create' else 'Use the detected ext4 filesystem. Existing image contents will be kept. Monitoring will resume automatically if already on.'))


def save_configuration(b,c,old=None,item=None):
    original=b.FSTAB.read_text();lines=original.splitlines(keepends=True)
    if old:
        lines=[line for line in lines if not (len(line.split())>=2 and line.split()[0]==old['image'] and b.w.unescape_mount(line.split()[1])==old['mountpoint'])]
    if item: lines.append('\n'+item['image']+' '+item['mountpoint']+' ext4 '+item['fstab_options']+' 0 0\n')
    before=b.configuration()
    b.cli.save(b.s.STATE_DIR/'image-backups'/(secrets.token_hex(16)+'.json'),dict(config=before,fstab=original))
    changed=''.join(lines)
    try:
        b.w.atomic_write(b.FSTAB,changed,mode=0o644);b.cli.save(b.s.CONFIG,b.s.validate(c))
        b.command(['/usr/bin/systemctl','daemon-reload'])
    except Exception:
        if b.FSTAB.read_text()==changed: b.w.atomic_write(b.FSTAB,original,mode=0o644)
        b.cli.save(b.s.CONFIG,before)
        raise


def apply(b,chosen,data):
    outcome={}
    try:
        return _apply(b,chosen,data,outcome)
    except ImageMonitorResumeError as exc:
        # A context-manager exit can fail after creation/registration completed.
        # Preserve that result so the UI closes the consumed confirmation and
        # does not suggest repeating a destructive create request.
        if not outcome:raise
        return dict(outcome,ok=False,changed=True,monitoring_resumed=False,
                    message=outcome['message']+' '+str(exc))


def _apply(b,chosen,data,outcome):
    if not chosen or data!={'token':chosen['token'],'confirm':True} or time.monotonic()-chosen['created']>300:
        raise ValueError('Review the Virtual Disk Image and explicitly confirm it first.')
    with _image_transaction(b) as lock:
        if b.preparation.revision(b)!=chosen['revision']: raise ValueError('Settings changed. Review the image again.')
        current=proposal(b,chosen['data'])
        if chosen['mode']=='create': current['item']['uuid']=chosen['item']['uuid'];current['config']['images'][-1]['uuid']=chosen['item']['uuid']
        if any(current[k]!=chosen[k] for k in ('item','old','observed','size')): raise ValueError('Image identity changed. Nothing was modified.')
        item=chosen['item'];fd=None;image_created=False;registered=False
        phase='creating the image file' if chosen['mode']=='create' else 'checking the image file'
        try:
            if chosen['mode']=='create':
                parent=rooted(b,str(Path(item['image']).parent),create=True)
                try:
                    info=os.fstat(parent)
                    if info.st_uid!=0 or info.st_mode & 0o022:raise ValueError('Choose a dedicated administrator-owned folder for the backing file, so it cannot be accidentally changed or deleted.')
                    if str(Path(item['image']).parent)==b.w.MOUNT+'/usb-storage-watch-volumes/.images': os.fchmod(parent,0o700)
                    fd=os.open(Path(item['image']).name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
                    image_created=True
                finally: os.close(parent)
                free=os.fstatvfs(fd)
                if chosen['size']>free.f_bavail*free.f_frsize-64*1024**2: raise ValueError('Not enough free space; leave at least 64 MiB free on the drive.')
                target='/proc/self/fd/'+str(fd)
                phase='allocating and formatting the image file'
                b.preparation.run(['/usr/bin/fallocate','-l',str(chosen['size']),target],fds=(fd,lock),timeout=30)
                b.w.verify_main()
                # -F is restricted to this newly O_EXCL-created regular file.
                # Never used on an existing image or block device.
                b.preparation.run(['/usr/sbin/mkfs.ext4','-q','-F','-E','nodiscard','-U',item['uuid'],target],fds=(fd,lock),timeout=180)
                os.fsync(fd)
            phase='verifying the image file'
            observed=probe(b,item['image'])
            expected=os.fstat(fd) if fd is not None else None
            if expected and (observed['inode'],observed['device']) != (expected.st_ino,expected.st_dev):
                raise ValueError('The new image file was replaced during creation.')
            if chosen['observed'] and observed != chosen['observed']:
                raise ValueError('The existing image changed during setup.')
            if observed['uuid']!=item['uuid']: raise ValueError('The image UUID differs from the reviewed filesystem.')
            directory=rooted(b,item['mountpoint'],create=True);os.close(directory)
            b.w.disk_proof(Path(item['image']),item['uuid'],unmounted=True,regular=True)
            if b.preparation.revision(b)!=chosen['revision']:
                raise ValueError('Settings changed during image setup. The image file is retained; review its configuration again.')
            phase='saving the image registration'
            save_configuration(b,chosen['config'],chosen['old'],item)
            registered=True
            b.w.configure(chosen['config'])
            phase='mounting the image'
            with _manual_mount(b):
                b.w.recover_image(item,dict(allow_mount=True,blocked=[]),lambda *args:None)
            if chosen['mode']=='create':
                phase='checking folder access'
                b.w.verify_dependent(item)
                directory=os.open(item['mountpoint'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
                try:
                    mounted=b.w.visible_mount(b.w.read_rows(),item['mountpoint'])
                    if os.fstat(directory).st_dev != os.makedev(*map(int,mounted['dev'].split(':'))):
                        raise ValueError('The mounted image changed before assigning its owner.')
                    owner=chosen.get('owner',(0,0))
                    if owner[0]<=0:raise ValueError('Select a named local user for storage access.')
                    os.fchown(directory,*owner);os.fchmod(directory,0o750)
                finally: os.close(directory)
                policy=chosen.get('permissions') or access_policy({},owner)
                permissions=permission_plan(b,item,owner,policy)
                apply_permission_targets(b,permissions)
                verify_policy_access(b,item['mountpoint'],policy)
            phase='reading the updated image status'
            outcome.update(message='Virtual Disk Image saved, mounted and verified.',images=entries(b),
                           image_created=image_created,registered=True,
                           image={key:item[key] for key in ('name','uuid','image','mountpoint')})
            return outcome
        except Exception as exc:
            # Never delete the newly created file on failure or retry formatting.
            if image_created or registered:
                status=('The image file was created and its registration was saved.' if image_created and registered else
                        'The existing image was registered.' if registered else
                        'The image file was created, but its registration was not saved.')
                outcome.update(ok=False,changed=True,image_created=image_created,registered=registered,
                               image={key:item[key] for key in ('name','uuid','image','mountpoint')},
                               message=status+' Setup stopped while '+phase+': '+str(exc)+
                               '. The file was kept. Do not create it again. '+
                               ('Check this image under Already configured before trying Mount image.' if registered else
                                'It is not ready to use; the retained image file needs review before it can be registered.'))
                return outcome
            raise ValueError('Virtual Disk Image setup stopped: '+str(exc)+'. Existing files were kept. Review the image before retrying.') from None
        finally:
            if fd is not None: os.close(fd)


def manage(b,data):
    """Change one image without stopping user monitoring.

    Manual mount state and the saved recovery preference are independent.
    Existing file contents are never reformatted, moved or removed.
    """
    with _image_transaction(b):
        c=b.configuration();b.w.configure(c)
        all_items=b.s.storage_images(c,False)
        item=next((v for v in all_items if v['uuid']==data.get('uuid')),None)
        if not item:raise ValueError('Select a configured virtual disk image.')
        action=data.get('action')
        if action == 'set-recovery':
            if set(data) != {'uuid','action','enabled'} or type(data['enabled']) is not bool:
                raise ValueError('Choose Mount on recovery for the selected image.')
            requested=data['enabled']
            if item['enabled']==requested:
                return dict(message='Mount on recovery is already '+('enabled.' if requested else 'disabled.'),enabled=requested)
            if not requested:
                if c['dependent']['enabled'] and c['dependent']['uuid']==item['uuid']:
                    raise ValueError('Legacy image is required by recovery. Review dependencies before disabling automatic mount.')
                if any(other['enabled'] and other['uuid']!=item['uuid']
                       and (b.w.covers(item['mountpoint'],other['image']) or b.w.covers(item['mountpoint'],other['mountpoint']))
                       for other in all_items):
                    raise ValueError('Another image depends on this image. Disable its recovery first.')
            planned=copy.deepcopy(c);altered=None
            for entry in planned['images']:
                if entry['uuid']==item['uuid']:
                    entry['enabled']=requested
                    opts=[option for option in entry['fstab_options'].split(',') if option!='noauto']
                    if not requested:opts.append('noauto')
                    entry['fstab_options']=','.join(opts);altered=entry
            if altered is None:raise ValueError('Image registration was not found.')
            b.s.validate(planned)
            save_configuration(b,planned,old=item,item=altered)
            b.w.configure(planned)
            return dict(message='Mount on recovery '+('enabled.' if requested else 'disabled.')+' Current mount unchanged.',enabled=requested)
        if set(data)-({'uuid','action','confirm'}):raise ValueError('Unexpected image operation parameter.')
        rows=b.w.read_rows()
        mounted=any(b.w.covers(item['mountpoint'],row['target']) for row in rows)
        if action=='unmount':
            if mounted:
                b.w.verify_dependent(item)
                row=b.w.visible_mount(rows,item['mountpoint'])
                if any(r['target']!=item['mountpoint'] and b.w.covers(item['mountpoint'],r['target']) for r in rows):
                    raise ValueError('Unmount nested virtual images first.')
                b.w.standby.users(b.w.usb_context(),dict(devs=[row['dev']]))
                b.w.command(['/usr/bin/sync','-f','--',item['mountpoint']],timeout=15)
                b.w.command(['/usr/bin/umount','--',item['mountpoint']],timeout=15)
            return dict(message='Virtual disk safely unmounted. Mount on recovery is unchanged.')
        if action=='mount':
            if mounted:b.w.verify_dependent(item)
            else:
                with _manual_mount(b):
                    b.w.recover_image(item,dict(allow_mount=True,blocked=[]),lambda *args:None)
            return dict(message='Virtual disk mounted and verified. Mount on recovery is unchanged.')
        if action!='remove' or data.get('confirm') is not True:raise ValueError('Explicitly confirm removing this recovery configuration.')
        if mounted:raise ValueError('Unmount this virtual disk image safely before removing its recovery configuration.')
        if any(v!=item and (b.w.covers(item['mountpoint'],v['image']) or b.w.covers(item['mountpoint'],v['mountpoint'])) for v in all_items):
            raise ValueError('Other virtual disk images depend on this one; update them first.')
        # The image registration and its explicit Docker mount choices are one
        # settings change. Keep each container's drive restart switch selected.
        # Detected storage paths are advisory, never a removal prerequisite.
        for container in c['docker']['containers']:
            if 'images' in container:
                container['images']=[identity for identity in container['images'] if identity!=item['uuid']]
        c['dependent']['enabled']=False;c['images']=[v for v in all_items if v!=item]
        save_configuration(b,c,old=item)
        return dict(message='Recovery configuration removed. The image file and its contents were kept.')

def account_groups(uid,gid,local=True):
    if local:
        try:return os.getgrouplist(pwd.getpwuid(uid).pw_name,gid)
        except KeyError:pass
    return [gid]


def account_access(b,path,owner,write_test=False,local=True):
    """Run access checks as the authenticated account, never as the root broker."""
    uid,gid=owner
    if uid<=0: raise ValueError('A named, non-root local account is required.')
    groups=account_groups(uid,gid,local)
    program='''import json,os,sys,secrets
path=sys.argv[1]
result={key:os.access(path,flag) for key,flag in [('read',os.R_OK),('write',os.W_OK),('traverse',os.X_OK)]}
if sys.argv[2]=='write':
    name=os.path.join(path,'.usw-access-check-'+secrets.token_hex(16));fd=None
    try:
        with os.scandir(path) as entries: next(entries,None)
        fd=os.open(name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        os.write(fd,b'first');os.lseek(fd,0,0);os.write(fd,b'next!');os.fsync(fd);os.lseek(fd,0,0)
        assert os.read(fd,5)==b'next!'
        result['tested']=True
    finally:
        if fd is not None: os.close(fd);os.unlink(name)
print(json.dumps(result))'''
    import json,subprocess
    try:result=subprocess.run(['/usr/bin/python3','-I','-c',program,path,'write' if write_test else 'read'],
        user=uid,group=gid,extra_groups=groups,cwd='/',capture_output=True,text=True,timeout=10,
        env={'PATH':'/usr/bin:/bin','LC_ALL':'C'})
    except PermissionError as exc:raise ValueError('The administration service could not switch to the intended user (errno '+str(exc.errno)+'). Check that the upgraded broker service is running with its credential-drop capabilities.') from None
    if result.returncode: raise ValueError('Your local account cannot browse and write in this folder. Review its permissions.')
    return json.loads(result.stdout)


def directory_proof(b,item):
    if item is None:
        dev=b.w.verify_main();path=b.w.MOUNT
    else:
        b.w.verify_main();b.w.verify_dependent(item)
        path=item['mountpoint'];dev=b.w.visible_mount(b.w.read_rows(),path)['dev']
    # Pin the actual mounted directory; symlinks are never permission targets.
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:
        for part in Path(path).parts[1:]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            os.close(fd);fd=child
        info=os.fstat(fd)
        if info.st_dev!=os.makedev(*map(int,dev.split(':'))): raise ValueError('Mounted storage identity changed.')
        return fd
    except BaseException: os.close(fd);raise


def permission_plan(b,item,owner,policy=None):
    fd=directory_proof(b,item);os.close(fd)
    policy=policy or access_policy({},owner)
    path=item['mountpoint'] if item else b.w.MOUNT;targets=[]
    for parent in reversed([Path(path),*Path(path).parents]):
        if str(parent)=='/':continue
        inside=str(parent)==b.w.MOUNT or b.s.below(b.w.MOUNT,str(parent))
        checks=[(user,account_access(b,str(parent),(user['uid'],user['gid']),local=user.get('local',True))) for user in policy['users']]
        if not inside:
            if any(not access['traverse'] for _,access in checks):raise ValueError('An inaccessible parent outside the USB drive needs administrator review: '+str(parent))
            continue
        info=parent.lstat()
        if not stat.S_ISDIR(info.st_mode):raise ValueError('A permission target is not a real directory.')
        acl=b.preparation.run(['/usr/bin/getfacl','-c','-p','-n','--',str(parent)]).stdout;changed=acl
        root=str(parent)==path
        for user,access in checks:
            uid,gid=user['uid'],user['gid']
            groups=account_groups(uid,gid,user.get('local',True))
            effective=effective_acl(changed,uid,info.st_uid,info.st_gid,groups)
            rights=user['rights'] if root else ''.join(c if c in effective or c=='x' else '-' for c in 'rwx')
            if root or not access['traverse']:changed=granted_acl(changed,uid,info.st_uid,rights)
        if policy['group'] is not None:
            gid=policy['group'];effective=group_acl(changed,gid,info.st_gid)
            rights=policy['group_rights'] if root else ''.join(c if c in effective or c=='x' else '-' for c in 'rwx')
            changed=granted_acl(changed,gid,info.st_uid,rights,kind='group')
        if root and policy['inherit']:
            default='\n'.join(line.removeprefix('default:') for line in changed.splitlines() if line.startswith('default:')) or 'user::rwx\ngroup::---\nother::---\n'
            for user in policy['users']:default=granted_acl(default,user['uid'],-1,user['rights'])
            if policy['group'] is not None:default=granted_acl(default,policy['group'],-1,policy['group_rights'],kind='group')
            changed='\n'.join(line for line in changed.splitlines() if not line.startswith('default:'))+'\n'+''.join('default:'+line+'\n' for line in default.splitlines() if line)
        if changed.strip()!=acl.strip():targets.append(dict(path=str(parent),device=info.st_dev,inode=info.st_ino,uid=info.st_uid,gid=info.st_gid,
            mode=stat.S_IMODE(info.st_mode),acl=acl,new_acl=changed,rights='configured access' if root else 'traversal'))
    return dict(item=item,owner=owner,policy=policy,path=path,targets=targets,token=secrets.token_urlsafe(32),created=time.monotonic(),revision=b.preparation.revision(b))


def group_acl(original,gid,owner_group):
    lines=[line.split('#',1)[0].strip().split(':') for line in original.splitlines() if line and not line.startswith(('#','default:'))]
    mask=next((set(parts[2])-{'-'} for parts in lines if parts[0]=='mask'),set('rwx'))
    matches=[set(parts[2])-{'-'} for parts in lines if parts[0]=='group' and (int(parts[1]) if parts[1] else owner_group)==gid]
    return set().union(*matches) & mask if matches else next(set(parts[2])-{'-'} for parts in lines if parts[0]=='other')


def effective_acl(original,uid,owner,group,groups):
    entries={tuple(parts[:2]):set(parts[2])-{'-'} for line in original.splitlines()
             if line and not line.startswith(('#','default:'))
             for parts in [line.split('#',1)[0].strip().split(':')]}
    if uid==owner:return entries[('user','')]
    mask=entries.get(('mask',''),set('rwx'))
    if ('user',str(uid)) in entries:return entries[('user',str(uid))] & mask
    matches=[rights for (kind,name),rights in entries.items() if kind=='group' and (int(name) if name else group) in groups]
    return set().union(*matches) & mask if matches else entries[('other','')]


def granted_acl(original,uid,owner,rights,kind='user'):
    lines=[line.split('#',1)[0].strip() for line in original.splitlines() if line and not line.startswith('#')]
    if kind=='user' and uid==owner:
        return '\n'.join('user::'+rights if line.startswith('user::') else line for line in lines)+'\n'
    mask=next((line.split(':')[2] for line in lines if line.startswith('mask::')),'rwx')
    result=[]
    for line in lines:
        if line.startswith(('default:','other:','user::')): result.append(line);continue
        parts=line.split(':')
        if parts[0]=='mask' or (parts[0]==kind and parts[1]==str(uid)):continue
        # Preserve other entries' effective permissions before expanding the mask.
        if parts[0] in ('user','group'): parts[2]=''.join(c if c in mask else '-' for c in parts[2])
        result.append(':'.join(parts))
    result.extend([kind+':'+str(uid)+':'+rights,'mask::rwx'])
    return '\n'.join(result)+'\n'


def apply_permission_targets(b,chosen):
    b.cli.save(b.s.STATE_DIR/'permission-backups'/(secrets.token_hex(16)+'.json'),chosen)
    for item in chosen['targets']:
        fd=os.open(item['path'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            info=os.fstat(fd)
            if (info.st_dev,info.st_ino,info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(item['device'],item['inode'],item['uid'],item['gid'],item['mode']):raise ValueError('Folder identity changed; permission change stopped.')
            acl=b.preparation.run(['/usr/bin/getfacl','-c','-p','-n','--','/proc/self/fd/'+str(fd)],fds=(fd,)).stdout
            if acl!=item['acl']:raise ValueError('Folder access changed; review permissions again.')
            b.preparation.run(['/usr/bin/setfacl','--set-file=-','/proc/self/fd/'+str(fd)],input=item['new_acl'],fds=(fd,))
        finally:os.close(fd)
    fd=directory_proof(b,chosen['item']);os.close(fd)


def verify_policy_access(b,path,policy):
    for user in policy['users']:
        access=account_access(b,path,(user['uid'],user['gid']),write_test=user['rights']=='rwx',local=user.get('local',True))
        if not access['read'] or not access['traverse']:raise ValueError('The intended account cannot browse this image folder.')


def permission_apply(b,chosen,data):
    if not chosen or data!={'token':chosen['token'],'confirm':True} or time.monotonic()-chosen['created']>300:
        raise ValueError('Review and explicitly confirm the folder permission change first.')
    with b.preparation.exclusive(b):
        if b.preparation.revision(b)!=chosen['revision']:raise ValueError('Storage settings changed. Review folder access again.')
        policy=chosen.get('policy') or access_policy({},chosen['owner'])
        fresh=permission_plan(b,chosen['item'],chosen['owner'],policy)
        if fresh['targets']!=chosen['targets']:raise ValueError('Folder permissions or identity changed. Review again before applying.')
        apply_permission_targets(b,chosen);verify_policy_access(b,chosen['path'],policy)
        return dict(message='Folder access verified for the intended accounts. Existing ownership, files and lost+found were not changed.',path=chosen['path'],accessible=True)
