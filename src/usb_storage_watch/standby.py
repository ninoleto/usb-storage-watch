# SPDX-License-Identifier: MIT
"""Guarded HDD standby. Routine observation reads kernel metadata only."""
import json
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import time

_spec = importlib.util.spec_from_file_location('drive_activity', Path(__file__).with_name('drive_activity.py'))
io = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(io)

SAMPLES = {}
SYS_DEV_BLOCK = Path('/sys/dev/block')
BY_ID_DIR = Path('/dev/disk/by-id')
DEV_DIR = Path('/dev')


def refusal(w, result, message):
    error = w.Unsafe(message)
    error.standby_result = result
    return error


def error_result(error):
    if isinstance(error, FileNotFoundError):
        return 'unavailable'
    if isinstance(error, BlockingIOError):
        return 'busy'
    return getattr(error, 'standby_result', 'failed')


def identity(w):
    dev = w.device_number('/dev/disk/by-uuid/' + w.DISK_UUID)
    w.block_checks(dev, w.DISK_UUID)
    part = (SYS_DEV_BLOCK / dev).resolve(strict=True)
    disk = part.parent if (part / 'partition').exists() else part
    props = w.udev(dev)
    if not w.usb.is_verified_usb_block(disk, props):
        raise w.Unsafe('HDD standby requires a real USB-attached disk with a stable serial number.')
    node = DEV_DIR / disk.name
    links = sorted(p for p in BY_ID_DIR.glob('*')
                   if p.resolve() == node and '-part' not in p.name)
    if not links:
        raise w.Unsafe('No stable /dev/disk/by-id identity exists for this disk.')
    # Reject an OS disk even if a data partition on it was configured manually.
    devs = {(disk / 'dev').read_text().strip(), dev}
    devs.update(p.read_text().strip() for p in disk.glob('*/dev'))
    if any(r['dev'] in devs and r['target'] in ('/', '/boot', '/boot/efi', '/usr', '/var', '/home')
           for r in w.read_rows()):
        raise w.Unsafe('Operating-system disk cannot be controlled.')
    return dict(path=str(links[0]), sys=str(disk), devs=sorted(devs), uuid=w.DISK_UUID,
                serial=props['ID_SERIAL'], boot=w.boot_id(),
                sequence=(disk / 'diskseq').read_text().strip())


def activity(binding):
    fields = [int(v) for v in (Path(binding['sys']) / 'stat').read_text().split()]
    if len(fields) < 17:
        raise ValueError('Complete read/write/discard/flush counters are unavailable; standby cannot be verified safely.')
    # Ignore time-in-queue counters; include reads, writes, discards and flushes.
    return fields[:8] + fields[11:], fields[8]


def filesystems(w, binding):
    devices = set(binding['devs'])
    rows = w.read_rows()
    # Include dependent loop devices whose backing file lives on this disk.
    roots = [r['target'] for r in rows if r['dev'] in devices]
    for p in Path('/sys/class/block').glob('loop*/loop/backing_file'):
        if any(w.covers(root, p.read_text().strip()) for root in roots):
            devices.add((p.parent.parent / 'dev').read_text().strip())
    return devices, [r['target'] for r in rows if r['dev'] in devices]


def users(w, binding, docker=True):
    """Strict unmount/removal guard. Standby deliberately does not call this."""
    devices, roots = filesystems(w, binding)
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            mounts = w.parse_mounts((proc / 'mountinfo').read_text())
            ids = {r['id'] for r in mounts if r['dev'] in devices}
            targets = [r['target'] for r in mounts if r['dev'] in devices]
            for fd in (proc / 'fdinfo').iterdir():
                try:
                    fields = dict(line.split(':', 1) for line in fd.read_text().splitlines() if ':' in line)
                    if fields.get('mnt_id', '').strip() in ids:
                        raise refusal(w, 'busy', 'Filesystem has active users (process ' + proc.name + ').')
                    link = proc / 'fd' / fd.name
                    dest = os.readlink(link).removesuffix(' (deleted)')
                    if dest.startswith('/dev/'):
                        try:
                            if w.device_number(link) in devices:
                                raise refusal(w, 'busy', 'Disk has an open block-device handle.')
                        except w.Unsafe as exc:
                            if 'not resolve' not in str(exc):
                                raise
                except (FileNotFoundError, ProcessLookupError):
                    continue
            for name in ('cwd', 'root', 'exe'):
                dest = os.readlink(proc / name).removesuffix(' (deleted)')
                if any(w.covers(root, dest) for root in targets):
                    raise refusal(w, 'busy', 'Filesystem is used by process ' + proc.name + ' (' + name + ').')
            for line in (proc / 'maps').read_text().splitlines():
                major, minor = (int(v, 16) for v in line.split()[3].split(':'))
                if f'{major}:{minor}' in devices:
                    raise refusal(w, 'busy', 'Filesystem has active memory mappings.')
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            if proc.exists():
                raise w.Unsafe('Cannot inspect an active process; operation refused.') from None
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        source = w.unescape_mount(line.split()[0])
        if any(w.covers(root, source) for root in roots):
            raise refusal(w, 'busy', 'Active swap file is on the disk.')
        if source.startswith('/dev/') and w.device_number(source) in devices:
            raise refusal(w, 'busy', 'Disk is used as swap.')
    if docker and Path(w.SETTINGS['docker']['socket']).exists():
        try:
            containers = w.apps.Docker().request('GET', '/containers/json?all=0')
            for container in containers:
                if any(any(w.covers(root, m.get('Source', '')) for root in roots)
                       for m in container.get('Mounts', [])):
                    raise refusal(w, 'busy', 'A running Docker container has access to this disk. Stop it before unmounting or changing storage.')
        except (w.apps.AppError, KeyError, TypeError):
            raise w.Unsafe('Docker access could not be checked; operation refused.') from None


def power_command(w, flag, path):
    # Never use ATA SLEEP (-Y); it may require a hardware reset to recover.
    if flag not in ('-y', '-C'):
        raise w.Unsafe('Unsupported power command.')
    try:
        result = subprocess.run(['/usr/sbin/hdparm', flag, path], capture_output=True,
                                text=True, timeout=10, check=False, pass_fds=w.WORKER_LOCK_FDS)
    except subprocess.TimeoutExpired:
        raise w.Unsafe('USB-SATA bridge did not answer the standby command; power state is uncertain.') from None
    if result.returncode:
        detail = getattr(result, 'stderr', '')
        unsupported = re.search(r'not supported|unsupported|inappropriate ioctl|invalid argument|bad/missing sense', detail, re.I)
        raise refusal(w, 'unsupported' if unsupported else 'failed',
                      'USB-SATA bridge rejected the power command; standby could not be verified.')
    return result.stdout


def settle_manual(w, binding, topology=None):
    """Allow pending writes to settle after sync, with a bounded quiet window."""
    observed = io.capture(w, topology) if topology else None
    before, inflight = activity(binding)
    initial = before
    images = io.loop_activity(topology) if topology else []
    started = time.monotonic()
    deadline = time.monotonic() + 15
    quiet_since = time.monotonic() if not inflight else None
    while time.monotonic() < deadline:
        time.sleep(min(1, max(0, deadline - time.monotonic())))
        if identity(w) != binding:
            raise refusal(w, 'unavailable', 'Disk connection changed while waiting for pending writes.')
        if not w.snapshot()['healthy']:
            raise refusal(w, 'unavailable', 'The expected filesystem is no longer mounted read/write.')
        if topology is not None and io.topology(w, binding) != topology:
            raise refusal(w, 'unavailable', 'Mount or dependent image identity changed during standby preparation.')
        counters, inflight = activity(binding)
        now = time.monotonic()
        if now > deadline:
            break
        next_images = io.loop_activity(topology) if topology else []
        if inflight or any(v[2] for v in next_images):
            quiet_since = None
        elif counters != before or next_images != images or quiet_since is None:
            quiet_since = now
        before = counters
        images = next_images
        if quiet_since is not None and now - quiet_since >= 3:
            return counters, 0
    detail = ''
    if topology and len(initial)>=7:
        try:
            last=io.capture(w, topology)
            after, pending=activity(binding)
            report=io.report(observed,last,binding,topology,initial,after,time.monotonic()-started)
            names=[v['name'] for v in report['containers'] if v['state']=='observed activity']
            detail=f" Read {report['read_bytes_per_second']:.0f} B/s, write {report['write_bytes_per_second']:.0f} B/s; {pending} requests in flight."
            detail+=(' Observed container I/O: '+', '.join(names)+'.') if names else ' Source not attributed; filesystem/background work may be responsible.'
        except (OSError, ValueError, KeyError, w.Unsafe):
            detail=' Activity source measurement unavailable.'
    raise refusal(w, 'busy', 'Disk activity did not settle within 15 seconds after flushing writes; standby was not sent.'+detail+' Wait for I/O to finish and try again.')


def sleep(w, *, manual=False):
    binding = identity(w)
    current = w.snapshot()
    if not current['healthy']:
        raise refusal(w, 'failed' if current.get('unsafe') else 'unavailable',
                      'The expected read/write filesystem must be mounted before HDD standby.')
    if status(w)['sleeping']:
        return 'HDD standby remains confirmed; no new block I/O has occurred.'
    if storage_kind(w,binding) != 'mechanical':
        raise refusal(w, 'unsupported', 'Mechanical HDD standby is not supported or not established by passive metadata; standby refused.')
    topology = io.topology(w, binding)
    io.swap_guard(w, topology)
    # Flush dependent image filesystems before their backing physical filesystem,
    # including images mounted elsewhere. No consumer scan: idle handles are safe.
    for target in topology['targets']:
        if identity(w)!=binding or io.topology(w,binding)!=topology:
            raise refusal(w, 'unavailable', 'Drive identity or mounts changed before flush.')
        w.command(['/usr/bin/sync', '-f', '--', target], timeout=15)
    after_flush, inflight = settle_manual(w, binding, topology)
    quiet_images = io.loop_activity(topology)
    if any(v[2] for v in quiet_images):
        raise refusal(w, 'busy', 'Dependent image I/O is pending; standby deferred.')
    io.swap_guard(w, topology)
    if identity(w) != binding or io.topology(w,binding)!=topology or not w.snapshot()['healthy']:
        raise refusal(w, 'unavailable', 'Disk connection or mounts changed before standby.')
    if inflight or activity(binding) != (after_flush, 0):
        raise refusal(w, 'busy', 'Disk activity changed; standby deferred.')
    fd = os.open(binding['path'], os.O_RDONLY | os.O_CLOEXEC)
    locks = w.WORKER_LOCK_FDS
    try:
        if identity(w) != binding or w.device_number('/proc/self/fd/' + str(fd)) != (Path(binding['sys']) / 'dev').read_text().strip():
            raise w.Unsafe('Disk identity changed before standby.')
        if io.topology(w,binding)!=topology or activity(binding)!=(after_flush,0) or io.loop_activity(topology)!=quiet_images:
            raise refusal(w, 'busy', 'Mounts or activity changed immediately before standby.')
        w.WORKER_LOCK_FDS = (*locks, fd)
        pinned = '/proc/self/fd/' + str(fd)
        power_command(w, '-y', pinned)
        try:
            state = power_command(w, '-C', pinned)
        except w.Unsafe:
            raise refusal(w, 'unverified', 'Standby command sent, but the USB-SATA bridge could not verify power state. Applications remain running; do not assume the disk is asleep.') from None
    finally:
        w.WORKER_LOCK_FDS = locks
        os.close(fd)
    if identity(w)!=binding or io.topology(w,binding)!=topology:
        raise refusal(w, 'unavailable', 'Drive identity or mounts changed after standby; power state is unverified.')
    if activity(binding) != (after_flush, 0) or io.loop_activity(topology)!=quiet_images:
        raise refusal(w, 'busy', 'New disk activity occurred during standby; the HDD may have woken.')
    if not re.search(r'drive state is:\s*standby', state, re.I):
        raise refusal(w, 'unverified', 'Standby command sent, but this USB-SATA bridge did not confirm standby. Support is unverified.')
    save(w, binding, 'Standby confirmed; filesystem remains mounted.', sleeping=True, counters=after_flush)
    return 'HDD standby confirmed. Filesystems remain mounted and applications remain running; new access may wake it.'


def save(w, binding, message, sleeping=False, suppressed=False, counters=None):
    if counters is None:
        counters, _ = activity(binding)
    w.atomic_write(w.STATE_DIR / 'standby.json', json.dumps(dict(
        binding=binding, counters=counters, message=message, sleeping=sleeping, suppressed=suppressed,
        time=w.timestamp(), at=w.clock_now())) + '\n')


def storage_kind(w,binding):
    """Only cached udev and kernel metadata; never ATA/SCSI/SMART queries."""
    rotational=(Path(binding['sys'])/'queue/rotational').read_text().strip()
    props={}
    try:
        for dev in binding.get('devs',[]):
            value=w.udev(dev)
            if isinstance(value,dict):props.update(value)
    except (OSError,ValueError):pass
    model=props.get('ID_MODEL','').replace('_',' ')
    if (rotational=='0' or props.get('ID_ATA_ROTATION_RATE_RPM')=='0'
            or any(v=='1' and (k.startswith('ID_DRIVE_FLASH') or k=='ID_DRIVE_THUMB') for k,v in props.items())
            or re.search(r'\b(?:USB\s+)?flash\s+(?:drive|disk)\b|\bSSD\b',model,re.I)):
        return 'non-mechanical'
    if rotational!='1':return 'unknown'
    rpm=props.get('ID_ATA_ROTATION_RATE_RPM','')
    if rotational=='1' and rpm.isdigit() and int(rpm)>1:return 'mechanical'
    # Some ATA passthrough bridges omit the rotation-rate field. The
    # combination of ATA identity, stable WWN and rotational kernel media
    # metadata is stronger than the rotational bit alone (USB flash drives
    # sometimes misleadingly report that bit as 1).
    if (rotational=='1' and not rpm and props.get('ID_ATA')=='1'
            and props.get('ID_WWN') and props.get('ID_SERIAL')):
        return 'mechanical'
    try:
        saved=json.loads((w.STATE_DIR/'standby.json').read_text())
        if rotational=='1' and saved.get('binding')==binding and saved.get('sleeping'):return 'mechanical'
    except (OSError,ValueError,AttributeError):pass
    return 'unknown'


def status(w):
    """Passive observations: idle is not proof that the spindle stopped."""
    result = dict(applicable=False, sleeping=False, state='unknown', label='Unknown',
                  message='Power state is unknown. Routine checks do not query or wake the drive.')
    try:
        binding = identity(w)
        kind=storage_kind(w,binding)
        if kind == 'non-mechanical':
            return result | dict(state='not-applicable', label='Not applicable for flash storage',
                                 message='This device reports non-rotating storage; HDD standby does not apply.')
        if kind!='mechanical': return result
        result['applicable'] = True
        counters, inflight = activity(binding)
        key = str(w.STATE_DIR)
        previous = SAMPLES.get(key)
        now = w.clock_now()
        if inflight or (previous and previous[0] == binding and previous[1] != counters):
            result.update(state='active', label='Active', message='Disk I/O observed; the drive is active.')
        elif previous and previous[0] == binding and now - previous[2] >= 1:
            result.update(state='idle', label='Idle', message='No recent disk I/O. The disk may still be spinning; standby is not confirmed.')
        elif previous and previous[0] == binding and len(previous) > 3:
            # Closely spaced requests must not erase an established activity
            # observation or continually reset the idle sampling window.
            result['state'] = previous[3]
            result['label'] = {'active':'Active','idle':'Idle'}.get(previous[3], 'Unknown')
            if previous[3] == 'active':
                result['message'] = 'Disk I/O observed; the drive is active.'
            elif previous[3] == 'idle':
                result['message'] = 'No recent disk I/O. The disk may still be spinning; standby is not confirmed.'
        if (not previous or previous[0] != binding or inflight
                or previous[1] != counters or now - previous[2] >= 1):
            SAMPLES[key] = (binding, counters, now, result['state'])
        try:
            saved = json.loads((w.STATE_DIR / 'standby.json').read_text())
        except FileNotFoundError:
            return result
        if binding != saved['binding']:
            return result
        unchanged = (counters, inflight) == (saved['counters'], 0)
        sleeping = saved['sleeping'] and unchanged
        result.update(sleeping=sleeping, suppressed=saved.get('suppressed', False) and unchanged, time=saved['time'])
        if sleeping:
            result.update(state='standby', label='Standby / spun down', message='Standby was confirmed for this connection; no new block I/O has occurred.')
        elif saved.get('suppressed') and unchanged:
            result['message'] = saved['message']
        return result
    except (OSError, ValueError, KeyError, w.Unsafe):
        return result


class Idle:
    def __init__(self):
        self.previous = None
        self.since = 0
        self.retry_at = 0

    def due(self, w):
        if not w.SETTINGS['standby']['enabled'] or not w.snapshot()['healthy']:
            self.previous = None
            return False
        try:
            binding = identity(w)
            counters, inflight = activity(binding)
            sample = (binding, counters)
            now = w.clock_now()
            if sample != self.previous or inflight:
                self.previous, self.since, self.retry_at = sample, now, 0
            if now >= self.retry_at and now - self.since >= w.SETTINGS['standby']['idle_seconds']:
                self.retry_at = now + 60
                saved = status(w)
                return saved.get('applicable',True) and not (saved['sleeping'] or saved.get('suppressed'))
        except (OSError, ValueError, w.Unsafe):
            self.previous = None
        return False
