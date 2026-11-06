# SPDX-License-Identifier: MIT
"""Explicit administrator-only disk preparation. Never imported by recovery.

One-use, session-bound consent covers one observed physical USB attachment.
Kernel exclusive claims exclude mounts during partitioning and formatting.
"""
from contextlib import contextmanager
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import subprocess
import time
import uuid

SYS_DEV_BLOCK = Path('/sys/dev/block')
BY_ID_DIR = Path('/dev/disk/by-id')


def run(argv, *, input=None, fds=(), timeout=15, codes=(0,)):
    result = subprocess.run(argv, input=input, capture_output=True, text=True,
                            timeout=timeout, check=False, pass_fds=fds,
                            env=dict(os.environ, LC_ALL='C'), cwd='/')
    if result.returncode not in codes:
        raise ValueError(Path(argv[0]).name + ' could not complete safely. No automatic retry will be made.')
    return result


def inventory(b):
    rows = json.loads(run(['/usr/bin/lsblk', '--json', '--bytes', '--paths', '--output',
                          'NAME,TYPE,SIZE,MODEL,SERIAL,TRAN,RO,FSTYPE,UUID,MOUNTPOINTS']).stdout)['blockdevices']
    result = []
    for disk in rows:
        if disk['type'] != 'disk' or disk.get('tran') != 'usb':
            continue
        node = Path(disk['name'])
        # ATA-pass-through USB bridges may publish ata-* or wwn-* links
        # instead of usb-* links. Only lsblk-confirmed USB disks are listed.
        links = []
        for prefix in ('usb-', 'ata-', 'wwn-', 'scsi-'):
            links.extend(sorted(str(p) for p in BY_ID_DIR.glob(prefix + '*')
                                if not re.search(r'-part\d+$', p.name) and p.resolve() == node))
        if not links:
            continue
        children = list(b.cli.flatten([disk]))
        reason = ('This drive is read-only.' if disk.get('ro') else
                  'Unmount this drive and close its files before preparing it.' if any(
                      p for child in children for p in child.get('mountpoints') or []) else
                  'RAID, LVM and other managed storage cannot be prepared here.' if any(
                      child['type'] not in ('disk', 'part') or
                      child.get('fstype') in ('LVM2_member', 'linux_raid_member', 'swap', 'zfs_member') for child in children) else '')
        # Only passive kernel/udev metadata is read; never spin up a drive to
        # identify its type. A false rotational bit alone does not prove HDD.
        media='unknown'
        try:
            dev=b.w.device_number(node)
            whole=(SYS_DEV_BLOCK/dev).resolve(strict=True)
            props=b.w.udev(dev)
            if b.w.usb.is_verified_usb_block(whole,props):
                rotation=(whole/'queue/rotational').read_text().strip()
                media=b.media_kind(props,rotation)
        except (OSError,ValueError,AttributeError):
            pass
        result.append(dict(device=links[0], model=(disk.get('model') or 'USB drive').strip(),
                           serial=disk.get('serial') or '', size=int(disk['size']),
                           media_kind=media,reason=reason))
    return result


def binding(b, device):
    # Names supplied by a client are never interpreted as kernel disk names.
    if not isinstance(device, str) or not re.fullmatch(r'/dev/disk/by-id/(?:usb|ata|wwn|scsi)-[A-Za-z0-9_.:+-]+', device):
        raise ValueError('Select a USB drive by its stable identity.')
    matches = [row for row in inventory(b) if row['device'] == device]
    if len(matches) != 1:
        raise ValueError('The selected physical USB drive is missing or ambiguous.')
    row = matches[0]
    if row['reason']:
        raise ValueError(row['reason'])
    dev = b.w.device_number(device)
    sys = (SYS_DEV_BLOCK / dev).resolve(strict=True)
    props = b.w.udev(dev)
    if (sys / 'partition').exists() or not any(re.fullmatch(r'usb\d+', p.name) for p in sys.parents):
        raise ValueError('Only a whole physical USB drive can be prepared.')
    serial = props.get('ID_SERIAL_SHORT', '')
    # An ATA-over-USB bridge can expose ID_BUS=ata. Trust only the real
    # kernel USB ancestry plus a serial that agrees with lsblk, never the
    # ID_BUS string or a potentially misleading /dev/disk/by-id prefix.
    if (not b.w.usb.is_verified_usb_block(sys, props)
            or not serial or serial != row['serial']):
        raise ValueError('The selected drive needs a verified USB connection and matching unique serial number.')
    if sum(r['serial'] == serial for r in inventory(b)) != 1:
        raise ValueError('Duplicate USB serial numbers; drive identity is ambiguous.')
    size = int((sys / 'size').read_text()) * 512
    if size != row['size'] or size < 128 * 1024**2 or (sys / 'ro').read_text().strip() != '0':
        raise ValueError('Drive capacity or write access could not be verified.')
    parts = sorted((p.parent for p in sys.glob('*/partition')), key=lambda p: int((p / 'partition').read_text()))
    layout = [dict(dev=(p / 'dev').read_text().strip(), number=int((p / 'partition').read_text()),
                   start=int((p / 'start').read_text()), size=int((p / 'size').read_text())) for p in parts]
    return dict(**row, sys=str(sys), dev=dev, devs=[dev] + [p['dev'] for p in layout], layout=layout,
                sequence=(sys / 'diskseq').read_text().strip(), boot=b.w.boot_id())


def unused(b, disk):
    devices = set(disk['devs'])
    for dev in devices:
        node = Path('/sys/dev/block') / dev
        if any((node / 'holders').iterdir()):
            raise ValueError('This disk has active RAID, LVM or other block-device users.')
    # Check every visible mount namespace, including containers and hidden mounts.
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if any(r['dev'] in devices for r in b.w.parse_mounts((proc / 'mountinfo').read_text())):
                raise ValueError('Part of this drive is mounted or used by the system/a container. Unmount it first.')
        except (FileNotFoundError, ProcessLookupError):
            continue
    loops = json.loads(run(['/usr/sbin/losetup', '--json', '--list', '--output', 'NAME,BACK-MAJ:MIN']).stdout)
    if any(row.get('back-maj:min') in devices for row in loops['loopdevices']):
        raise ValueError('An active loop filesystem uses this disk.')
    # Reuse process fd/mmap/raw-device, swap and Docker guards from safe standby.
    context = b.w.usb_context()
    context.SETTINGS = b.configuration()
    b.w.apps.configure(context.SETTINGS['docker'])
    b.w.standby.users(context, disk)


def signatures(disk, fds=()):
    found = []
    for dev in disk['devs']:
        path = '/dev/block/' + dev
        result = run(['/usr/sbin/blkid', '-p', '-o', 'export', path], fds=fds, codes=(0, 2))
        props = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if props.get('USAGE') in ('raid', 'other') or props.get('TYPE') in ('swap', 'LVM2_member', 'zfs_member'):
            raise ValueError('Swap, RAID, LVM and other managed storage cannot be erased here.')
        found.append(props)
    result = run(['/usr/sbin/sfdisk', '--json', disk['device']], fds=fds, codes=(0, 1))
    if result.returncode and (disk['layout'] or 'does not contain a recognized partition table' not in result.stderr):
        raise ValueError('The partition layout could not be verified.')
    return dict(filesystems=found, table=json.loads(result.stdout) if result.returncode == 0 else None)


def revision(b):
    return b.s.digest(dict(config=b.configuration(), fstab=b.FSTAB.read_text()))


def verify_fd(b, fd, disk, dev):
    # BLKGETDISKSEQ identifies the attachment even if /dev names are reused.
    sequence = struct.unpack('Q', fcntl.ioctl(fd, 0x80081280, bytes(8)))[0]
    if (not stat.S_ISBLK(os.fstat(fd).st_mode) or str(sequence) != disk['sequence']
            or b.w.device_number('/proc/self/fd/' + str(fd)) != dev):
        raise ValueError('The physical disk attachment changed; preparation refused.')


@contextmanager
def exclusive(b, own_monitor=True):
    # Preparing an additional disk must not stop or acquire the selected disk's
    # monitoring/recovery locks. The shared configuration lock still serializes
    # mount-table writes, and O_EXCL plus namespace checks guard the target disk.
    guard=b.migration.exclusive(b.migration_context()) if own_monitor else b.cli.drives.configuration_lock(b.s)
    with guard:
        with (b.s.STATE_DIR / ('recovery.lock' if own_monitor else 'preparation.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            current = b.configuration()
            if current['disk']['uuid']:
                b.w.configure(current)
            b.w.assert_internal_state()
            if b.migration.pending(b.migration_context()):
                raise ValueError('Finish the pending mount location change first.')
            previous = b.w.WORKER_LOCK_FDS
            b.w.WORKER_LOCK_FDS = (*previous, lock.fileno())
            try:
                yield lock.fileno()
            finally:
                b.w.WORKER_LOCK_FDS = previous


def plan(b, data):
    if set(data) != {'device', 'name'} or not isinstance(data['name'], str) or not re.fullmatch(r'[A-Za-z0-9 _.-]{0,16}', data['name']):
        raise ValueError('Use an optional drive name of up to 16 letters, numbers, spaces, dots, dashes or underscores.')
    # Review is read-only; final consent stops monitoring before exclusive guards.
    disk = binding(b, data['device'])
    unused(b, disk)
    observed = signatures(disk)
    # Only the selected filesystem and its configured images may have their
    # exact permanent entries retired by an explicit reformat.
    old_uuids = {p.get('UUID') for p in observed['filesystems']} - {None}
    other_owner(b,old_uuids)
    c=b.configuration()
    selected=c['disk']['uuid'] in old_uuids
    if selected and b.w.load_state(b.s.STATE_DIR/'state.json').get('pending'):
        raise ValueError('Previous notifications are still queued. Deliver them before erasing the selected drive.')
    for entry in b.fstab_entries():
        if selected and entry[0]=='UUID='+c['disk']['uuid'] and b.w.unescape_mount(entry[1])==c['disk']['mountpoint']:
            continue
        if entry[0].startswith('UUID=') and entry[0][5:].strip('\"\'') in old_uuids:
            raise ValueError('This drive has an existing permanent mount entry. Administrator review is required before erasing it.')
        if not entry[0].startswith('UUID='):
            for dev, props in zip(disk['devs'], observed['filesystems']):
                if b.same_source(entry[0], dict(uuid=props.get('UUID', ''), device='/dev/block/' + dev)):
                    raise ValueError('An existing permanent mount uses this disk. No entries or data were changed.')
    phrase = 'ERASE ' + re.sub(r'[^A-Za-z0-9]', '', disk['serial'])[-8:]
    return dict(token=secrets.token_urlsafe(32), created=time.monotonic(), disk=disk,
                signatures=observed, revision=revision(b), name=data['name'].strip(), phrase=phrase, selected=selected)


def public_plan(chosen):
    disk = chosen['disk']
    return {key: disk[key] for key in ('device', 'model', 'serial', 'size')} | dict(
        token=chosen['token'], phrase=chosen['phrase'], partitions=len(disk['layout']), name=chosen['name'], selected=chosen.get('selected',False))


def record(b, value):
    b.cli.save(b.s.STATE_DIR / 'prepare-drive.json', value)


def status(b):
    path = b.s.STATE_DIR / 'prepare-drive.json'
    value = json.loads(path.read_text()) if path.exists() else None
    if value and value['phase'] == 'ready':
        try:
            dev = b.w.device_number('/dev/disk/by-uuid/' + value['uuid'])
            b.w.mounted_checks(b.w.read_rows(), value['mountpoint'], dev, value['uuid'])
            value['available'] = True
        except (OSError, ValueError, b.w.Unsafe):
            value['available'] = False
    return value


def confirm(chosen, data):
    if (not chosen or set(data) != {'token', 'confirmation', 'erase'} or data.get('erase') is not True
            or data.get('token') != chosen['token'] or data.get('confirmation') != chosen['phrase']
            or time.monotonic() - chosen['created'] > 300):
        raise ValueError('Review the selected drive again, confirm permanent erasure, and type its exact confirmation text.')


def prepare(b, chosen, data):
    original_state=b.w.STATE_DIR
    try:return prepare_disk(b,chosen,data)
    finally:b.w.STATE_DIR=original_state


def prepare_disk(b, chosen, data):
    confirm(chosen,data)
    with exclusive(b,own_monitor=chosen.get('selected',True)) as lock:
        disk = chosen['disk']
        if revision(b) != chosen['revision'] or binding(b, disk['device']) != disk:
            raise ValueError('The drive or settings changed. Review the drive again; nothing was erased.')
        unused(b, disk)
        other_owner(b,{p.get('UUID') for p in chosen['signatures']['filesystems']} - {None})
        # A kernel claim on the entire physical disk refuses mounted partitions
        # and prevents a desktop/container mount from racing the formatter.
        fd = os.open(disk['device'], os.O_RDWR | os.O_EXCL | os.O_CLOEXEC)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fds = (lock, fd)
            pinned = '/proc/self/fd/' + str(fd)
            verify_fd(b, fd, disk, disk['dev'])
            if signatures(disk, fds) != chosen['signatures'] or binding(b, disk['device']) != disk:
                raise ValueError('Device identity or partition layout changed; nothing was erased.')
            unused(b, disk)
            fs_uuid = str(uuid.uuid4())
            mountpoint = '/mnt/usb-storage-watch-' + fs_uuid
            path = b.cli.root_path('/', mountpoint)
            if path.exists() or any(b.w.unescape_mount(e[1]) == mountpoint for e in b.fstab_entries()):
                raise ValueError('The new mount location already exists; nothing was erased.')
            value = dict(operation=chosen.get('operation'),phase='preparing', message='Preparing the selected disk. Do not disconnect it.',
                         device=disk['device'], serial=disk['serial'], uuid=fs_uuid,
                         name=chosen['name'] or disk['model'][:40], mountpoint=mountpoint)
            original=b.configuration()
            b.cli.save(b.s.STATE_DIR/'prepare-backups'/(fs_uuid+'.json'),
                       dict(fstab=b.FSTAB.read_text(),config=original,selected=disk,
                            state=b.w.load_state(b.s.STATE_DIR/'state.json')))
            if chosen.get('selected'):
                owned={('UUID='+original['disk']['uuid'],original['disk']['mountpoint'])}
                owned.update((item['image'],item['mountpoint']) for item in b.s.storage_images(original,False))
                lines=[line for line in b.FSTAB.read_text().splitlines(keepends=True) if not (
                    len(line.split())>=2 and (line.split()[0],b.w.unescape_mount(line.split()[1])) in owned)]
                b.w.atomic_write(b.FSTAB,''.join(lines),mode=0o644)
                disarmed=b.s.default()
                disarmed['disk']=copy.deepcopy(original['disk'])
                for key in ('monitor','notifications'): disarmed[key]=copy.deepcopy(original[key])
                b.cli.save(b.s.CONFIG,disarmed)
                b.cli.save(b.s.STATE_DIR/'state.json',b.w.fresh_state())
                b.command(['/usr/bin/systemctl','daemon-reload'])
                # Explicit reformat consent retires the old UUID pin. Keep its
                # exact contents with the preparation backup, never reuse it.
                pin=b.s.STATE_DIR/'drive-identity.json'
                if pin.exists():pin.replace(b.s.STATE_DIR/'prepare-backups'/(fs_uuid+'-identity.json'))
            expected_revision=revision(b)
            record(b, value)  # No automatic replay, including after interruption.
            try:
                run(['/usr/sbin/sfdisk', '--no-reread', '--no-tell-kernel', '--wipe', 'always',
                     '--wipe-partitions', 'always', pinned], input='label: gpt\n, , L\n', fds=fds)
                os.fsync(fd)
                # BLKRRPART through the sole disk opener; utilities opening it
                # again cannot reread partitions while our claim is held.
                fcntl.ioctl(fd, 0x125f)
                fresh = binding(b, disk['device'])
                if (any(fresh[k] != disk[k] for k in ('serial', 'size', 'sequence', 'boot', 'sys', 'dev'))
                        or len(fresh['layout']) != 1 or fresh['layout'][0]['number'] != 1):
                    raise ValueError('The new partition identity could not be verified.')
                unused(b, fresh)
                part = fresh['layout'][0]['dev']
                # udev deliberately waits on our flock. Use the kernel-created
                # node derived from sysfs, then verify its fd/disk sequence;
                # never wait for udev's partition symlinks under this lock.
                part_node = Path('/dev') / (Path('/sys/dev/block') / part).resolve(strict=True).name
                pfd = os.open(part_node, os.O_RDWR | os.O_CLOEXEC)
                try:
                    target = '/proc/self/fd/' + str(pfd)
                    verify_fd(b, pfd, fresh, part)
                    if binding(b, disk['device']) != fresh:
                        raise ValueError('The drive changed before filesystem creation.')
                    unused(b, fresh)
                    # Keep a pinned whole-device fd and flock to exclude udev,
                    # but hand the kernel claim to mke2fs: it opens the partition
                    # O_EXCL itself and refuses a mount racing that handoff.
                    # Never use -F to override the formatter's safety checks.
                    pin = os.open(pinned, os.O_RDWR | os.O_CLOEXEC)
                    try:
                        verify_fd(b, pin, disk, disk['dev'])
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        fcntl.flock(pin, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except Exception:
                        os.close(pin)
                        raise
                    os.close(fd)
                    fd, fds = pin, (lock, pin)
                    if binding(b, disk['device']) != fresh:
                        raise ValueError('The drive changed before filesystem creation.')
                    unused(b, fresh)
                    verify_fd(b, pfd, fresh, part)
                    value.update(phase='formatting',message='Creating the ext4 filesystem. Do not disconnect the drive.');record(b,value)
                    run(['/usr/sbin/mkfs.ext4', '-q', '-E', 'nodiscard', '-U', fs_uuid,
                         '-L', chosen['name'], target], fds=(*fds, pfd), timeout=180)
                    os.fsync(pfd)
                    check = run(['/usr/sbin/blkid', '-p', '-o', 'export', target], fds=(*fds, pfd)).stdout
                    props = dict(line.split('=', 1) for line in check.splitlines() if '=' in line)
                    if props.get('UUID') != fs_uuid or props.get('TYPE') != 'ext4':
                        raise ValueError('The new filesystem could not be verified.')
                finally:
                    os.close(pfd)
                value.update(phase='mounting', message='Filesystem created; configuring and mounting it.')
                record(b, value)
                c = b.s.default()
                c['disk'].update(uuid=fs_uuid, label=value['name'], mountpoint=mountpoint)
                c['recovery']['mount'] = True
                row = dict(uuid=fs_uuid, device=str(part_node), mountpoint='')
                addition = b.mount_plan(c, row, ['fstab'])
                if revision(b) != expected_revision:
                    raise ValueError('Configuration changed during preparation; the formatted drive was left for review.')
                if not chosen.get('selected'):
                    # Preparing an unregistered disk must not overwrite the
                    # selected monitor's hardware pin or current USB binding.
                    b.w.STATE_DIR=b.s.STATE_DIR/'prepare-backups'/(fs_uuid+'-verification')
                    b.w.STATE_DIR.mkdir(mode=0o700)
                b.w.configure(c)
                backing = b.w.recovery_backing(b.w.read_rows(), mountpoint, part, mounted=False)
                b.w.protected_mount_directory(mountpoint, backing, create=True)
                # Publish the UUID destination before releasing udev's flock,
                # so desktop discovery sees the permanent mount configuration.
                if addition:
                    b.w.atomic_write(b.FSTAB, b.FSTAB.read_text() + addition, mode=0o644)
                    b.command(['/usr/bin/systemctl', 'daemon-reload'])
            except Exception:
                message = ('The ext4 filesystem was created, but mount setup failed. Do not erase it again; review its mount settings.' if value['phase'] in ('mounting','verifying') else
                           'Preparation stopped after erasure began. The drive may be partly prepared. No automatic retry will run; review it before trying again.')
                value.update(phase='failed', message=message)
                record(b, value)
                raise
        finally:
            os.close(fd)
        try:
            # Refresh only this disk/partition's udev metadata, then use existing
            # UUID mount planning and engine mount/identity guards.
            run(['/usr/bin/udevadm', 'trigger', '--action=change', fresh['sys']])
            run(['/usr/bin/udevadm', 'trigger', '--action=change', str((Path('/sys/dev/block') / part).resolve())])
            run(['/usr/bin/udevadm', 'settle', '--timeout=15'], timeout=20)
            if b.w.device_number('/dev/disk/by-uuid/' + fs_uuid) != part:
                raise ValueError('The new UUID did not resolve to the prepared partition.')
            b.w.configure(c)
            if not b.w.snapshot()['healthy']:
                b.w.mount_available(b.w.read_rows(), mountpoint, part)
                b.w.fstab_check(mountpoint)
                b.w.disk_proof((Path('/dev/disk/by-uuid') / fs_uuid).resolve(strict=True), fs_uuid, unmounted=True)
                # Explicit preparation can mount before a monitor config exists.
                # Use the same filesystem guards, without enabling recovery.
                run(['/usr/bin/mount', '--', mountpoint], fds=(lock,), timeout=15)
            value.update(phase='verifying',message='Verifying the filesystem UUID, mount and write access.');record(b,value)
            b.w.verify_main()
            if chosen.get('selected'):
                b.w.drives.enroll(b.w.usb_context(),part)
            directory = os.open(mountpoint, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                if os.fstat(directory).st_dev != os.makedev(*map(int, part.split(':'))):
                    raise ValueError('The mounted drive changed before assigning its owner.')
                # The owner comes from the authenticated administrator, never
                # from HTTP fields. A new drive is writable in their file manager.
                os.fchown(directory, *chosen.get('owner', (0, 0)))
            finally:
                os.close(directory)
            if chosen.get('selected'):
                for key in ('monitor','notifications'): c[key]=copy.deepcopy(original[key])
                c['recovery'].update({key:val for key,val in original['recovery'].items() if key!='mount'})
                c['standby']['idle_seconds']=original['standby']['idle_seconds']
                b.cli.save(b.s.CONFIG,b.s.validate(c))
                b.w.configure(c)
                b.cli.save(b.s.STATE_DIR/'state.json',b.w.fresh_state())
            value.update(phase='ready', message='Drive ready. Your Linux filesystem is mounted.', config=c)
            record(b, value)
        except Exception:
            value.update(phase='failed', message='The ext4 filesystem was created, but its mount could not be completed. Do not erase it again; review the mount in Advanced settings.')
            record(b, value)
            raise
        finally:
            current = b.configuration()
            if current['disk']['uuid']:
                b.w.configure(current)
        return value


def other_owner(b,uuids):
    for identifier,path in b.cli.drives.files(b.s):
        if path==b.s.CONFIG:continue
        c=b.cli.drives.read(b.s,path)
        if c['disk']['uuid'] in uuids:
            raise ValueError('This disk belongs to another drive profile. Open Manage drive for that disk before preparing it. No data was changed.')


def activate(b, data):
    with exclusive(b):
        value = status(b)
        if (not value or value['phase'] != 'ready' or set(data) != {'uuid', 'confirm'}
                or data.get('uuid') != value['uuid'] or data.get('confirm') is not True):
            raise ValueError('Prepare a drive and review it before enabling automatic recovery.')
        old = b.configuration()
        changing = old['disk']['uuid'] != value['uuid']
        if changing and old['disk']['uuid']:
            raise ValueError('Keep this drive’s existing settings. Use Add USB drive on Overview to monitor the newly prepared disk independently.')
        if old['disk']['uuid']:
            b.w.configure(old)
        state_path = b.s.STATE_DIR / 'state.json'
        state = b.w.load_state(state_path)
        if changing and state['pending']:
            raise ValueError('Previous notifications are still queued. Deliver them before changing the selected drive.')
        c = copy.deepcopy(value['config'] if changing else old)
        if changing:
            for key in ('monitor', 'notifications'):
                c[key] = copy.deepcopy(old[key])
            c['recovery'].update({k: v for k, v in old['recovery'].items() if k != 'mount'})
            c['standby']['idle_seconds'] = old['standby']['idle_seconds']
        c['recovery']['mount'] = True
        c['usb']['enabled'] = True
        b.s.validate(c)
        b.w.configure(c)
        b.w.verify_main()
        b.w.fstab_check(b.w.MOUNT)
        # Preserve old disk-specific settings and history, never apply them to a
        # freshly erased drive. Existing SMTP credentials remain in place.
        if changing:
            b.cli.save(b.s.STATE_DIR / 'prepare-backups' / (value['uuid'] + '-activation.json'),
                       dict(config=old, state=state))
        before = {path: path.read_text() if path.exists() else None for path in (b.s.CONFIG, state_path)}
        try:
            b.cli.save(b.s.CONFIG, c)
            if changing:
                b.cli.save(state_path, b.w.fresh_state())
        except Exception:
            for path, original in before.items():
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    b.w.atomic_write(path, original)
            if old['disk']['uuid']:
                b.w.configure(old)
            raise
    b.command(['/usr/bin/systemctl', 'enable', '--now', b.cli.SERVICE], 30)
    return dict(message='Automatic recovery is enabled for your prepared drive.')


if __name__ == '__main__':
    # Private root worker, invoked only by the authenticated broker. Formatting
    # keeps the same disk guards/locks; the broker stays responsive for progress.
    import importlib.util
    import sys
    if sys.argv[1:] != ['_prepare'] or os.geteuid()!=0: raise SystemExit(2)
    spec=importlib.util.spec_from_file_location('prepare_broker',Path(__file__).with_name('web_broker.py'))
    broker=importlib.util.module_from_spec(spec);spec.loader.exec_module(broker)
    request=json.loads(sys.stdin.read(65536))
    try:
        confirm(request['chosen'],request['data'])
        if request['chosen'].get('selected',True):
            broker.command(['/usr/bin/systemctl','disable','--now',broker.cli.SERVICE],35)
        value=prepare(broker.preparation_context(),request['chosen'],request['data'])
        print(json.dumps(dict(ok=True,data=value)))
    except Exception as exc:
        print(json.dumps(dict(ok=False,error=str(exc))))
