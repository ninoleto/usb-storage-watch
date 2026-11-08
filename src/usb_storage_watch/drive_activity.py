# SPDX-License-Identifier: MIT
"""Passive Linux block/cgroup observations. Attribution never authorizes standby."""
from pathlib import Path
import re
import time

BLOCK = Path('/sys/class/block')
PROC = Path('/proc')
CGROUP = Path('/sys/fs/cgroup')


def topology(w, binding):
    rows = w.read_rows()
    depths = {dev: 0 for dev in binding['devs']}
    loops = {}
    # Resolve backing paths against the longest visible mount, without stat/read
    # of media files. A loop mounted outside its parent's path still depends on it.
    pending = {}
    for path in BLOCK.glob('loop*/loop/backing_file'):
        try:
            source = w.unescape_mount(path.read_text().strip())
            if not source.startswith('/'): source = '/' + source
            matches = [r for r in rows if w.covers(r['target'], source)]
            if not matches: continue
            parent = max(matches, key=lambda r: len(r['target']))
            node = path.parent.parent
            dev = (node/'dev').read_text().strip()
            pending[dev] = (parent['dev'], source, (path.parent/'offset').read_text().strip(),
                            (path.parent/'sizelimit').read_text().strip())
        except FileNotFoundError:
            continue  # Revalidation below detects a disappearing relevant loop.
    for _ in range(len(pending)):
        for dev, info in pending.items():
            if info[0] in depths and dev not in depths:
                depths[dev] = depths[info[0]] + 1
                loops[dev] = info
    selected = [r for r in rows if r['dev'] in depths]
    # Snapshot mount IDs/options/root, not just target strings. Remounts invalidate it.
    signature = sorted((r['id'], r['dev'], r['root'], r['target'], r['fs'],
                        tuple(sorted(r['vfs'])), tuple(sorted(r['super']))) for r in selected)
    targets = []
    for row in sorted(selected, key=lambda r:(depths[r['dev']],len(r['target'])), reverse=True):
        if row['target'] not in targets: targets.append(row['target'])
    return dict(devices=sorted(depths), loops=loops, mounts=signature, targets=targets)


def loop_activity(topo):
    result=[]
    for dev in sorted(topo['loops']):
        values=[int(v) for v in (Path('/sys/dev/block')/dev/'stat').read_text().split()]
        if len(values)<11: raise ValueError('Dependent image I/O counters unavailable')
        result.append((dev,values[:8]+values[11:],values[8]))
    return result


def swap_guard(w, topo):
    for line in (PROC/'swaps').read_text().splitlines()[1:]:
        source = w.unescape_mount(line.split()[0])
        if source.startswith('/dev/'):
            def depends(dev, seen):
                if dev in topo['devices']: return True
                if dev in seen: return False
                seen.add(dev)
                return any(depends((node/'dev').read_text().strip(),seen) for node in (Path('/sys/dev/block')/dev/'slaves').iterdir())
            if depends(w.device_number(source),set()):
                raise w.Unsafe('Active swap is on this drive; standby refused.')
        else:
            # stat only configured active swap, not ordinary open files.
            import os
            info = Path(source).stat()
            if f'{os.major(info.st_dev)}:{os.minor(info.st_dev)}' in topo['devices']:
                raise w.Unsafe('Active swap file is on this drive; standby refused.')


def counters(text):
    result = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts: continue
        if not re.fullmatch(r'\d+:\d+', parts[0]): raise ValueError('Invalid I/O device')
        fields = dict(p.split('=',1) for p in parts[1:])
        result[parts[0]] = tuple(int(fields[k]) for k in ('rbytes','wbytes'))
        if min(result[parts[0]]) < 0: raise ValueError('Invalid I/O counter')
    return result


def metric(pid):
    process = PROC/str(pid)
    start = (process/'stat').read_text().rsplit(')',1)[1].split()[19]
    groups = [v[3:] for v in (process/'cgroup').read_text().splitlines() if v.startswith('0::')]
    if len(groups)!=1 or groups[0]=='/' or '..' in Path(groups[0]).parts:
        raise ValueError('No distinct cgroup v2 accounting')
    path = (CGROUP/groups[0].lstrip('/')).resolve(strict=True)
    if not path.is_relative_to(CGROUP.resolve()): raise ValueError('Invalid cgroup path')
    info = path.stat()
    values = counters((path/'io.stat').read_text())
    if start != (process/'stat').read_text().rsplit(')',1)[1].split()[19]:
        raise ValueError('Process changed')
    return dict(key=(pid,start,str(path),info.st_dev,info.st_ino), values=values, at=time.monotonic())


def capture(w, topo):
    result = dict(containers={}, available=True)
    deadline = time.monotonic()+6
    try:
        docker = w.apps.Docker()
        items = docker.request('GET','/containers/json?all=0',timeout=2)
        for item in items:
            cid = item['Id']
            if not re.fullmatch('[a-f0-9]{64}', cid): raise ValueError('Invalid container identity')
            roots = topo['targets']
            access = any(any(w.covers(root,m.get('Source','')) for root in roots) for m in item.get('Mounts',[]))
            name = ' '.join(str((item.get('Names') or [cid[:12]])[0]).lstrip('/').split())[:100]
            row = dict(id=cid,name=name,access_configured=access,metric=None)
            result['containers'][cid] = row
            try:
                remaining = deadline-time.monotonic()
                if remaining<=0: raise ValueError('Observation budget exhausted')
                detail = docker.request('GET','/containers/'+cid+'/json',timeout=min(1,remaining))
                if detail['Id']!=cid or not detail['State']['Running']: raise ValueError('Container changed')
                pid = detail['State']['Pid']
                if type(pid) is not int or pid<=0: raise ValueError('PID unavailable')
                row['metric'] = metric(pid)
            except (OSError, ValueError, KeyError, IndexError, TypeError, w.apps.AppError):
                row['reason'] = 'Per-device cgroup v2 I/O measurement unavailable or container changed.'
    except (OSError, ValueError, KeyError, IndexError, TypeError, w.apps.AppError):
        result['available'] = False
    measured=[row for row in result['containers'].values() if row['metric']]
    shared=set()
    for a in measured:
        for b in measured:
            if a is not b:
                left=Path(a['metric']['key'][2]);right=Path(b['metric']['key'][2])
                if left.is_relative_to(right) or right.is_relative_to(left):
                    shared.update((a['id'],b['id']))
    for cid in shared:
        result['containers'][cid]['metric']=None
        result['containers'][cid]['reason']='Shared or nested container cgroup cannot be attributed separately.'
    return result


def rates(before, after, seconds):
    if seconds<=0 or len(before)!=len(after) or any(b<a for a,b in zip(before,after)):
        raise ValueError('Counters reset or interval unavailable')
    return [(b-a)/seconds for a,b in zip(before,after)]


def container_rates(a,b,binding,topo):
    if a['key']!=b['key']: raise ValueError('Container process/cgroup changed')
    physical=(Path(binding['sys'])/'dev').read_text().strip()
    # Prefer a single physical layer. Never add loop bytes to physical bytes.
    present=set(a['values'])|set(b['values'])
    devices=([physical] if physical in present else sorted(set(binding['devs']) & present))
    basis='physical'
    if not devices:
        devices=sorted(set(topo['devices']) & present)
        basis='loop (logical)' if devices else 'physical'
        # Nested loops may account the same operation more than once.
        devices=[d for d in devices if topo['loops'].get(d,('',))[0] not in devices]
    total=lambda x:tuple(sum(x['values'].get(d,(0,0))[i] for d in devices) for i in (0,1))
    interval=b['at']-a['at']
    return rates(total(a),total(b),interval),interval,basis


def report(first,last,binding,topo,before,after,seconds):
    out=dict(interval_seconds=seconds,containers=[],inventory_available=first['available'] and last['available'],
             limitation='Buffered/shared-file writes and filesystem/kernel work may not be attributed to a container. Missing metrics are not zero activity. Loop rates are logical and are not added to physical totals.')
    physical=rates((before[2]*512,before[6]*512),(after[2]*512,after[6]*512),seconds)
    out.update(read_bytes_per_second=physical[0],write_bytes_per_second=physical[1])
    attributed=[0,0]
    for cid in sorted(set(first['containers'])|set(last['containers'])):
        a=first['containers'].get(cid); b=last['containers'].get(cid); row=dict(b or a)
        row.pop('metric',None)
        row.update(state='measurement unavailable',read_bytes_per_second=None,write_bytes_per_second=None)
        try:
            if not a or not b or not a['metric'] or not b['metric']: raise ValueError('Missing metrics')
            value,interval,basis=container_rates(a['metric'],b['metric'],binding,topo)
            row.update(state='observed activity' if any(value) else 'access configured; no activity observed',
                       read_bytes_per_second=value[0],write_bytes_per_second=value[1],interval_seconds=interval,basis=basis)
            if basis=='physical': attributed=[x+y for x,y in zip(attributed,value)]
        except (OSError,ValueError,KeyError):
            row['reason']='Per-device measurement unavailable, reset, or identity changed during observation.'
        if row['access_configured'] or row['state']=='observed activity' or row['state']=='measurement unavailable':
            out['containers'].append(row)
    out['unattributed_read_bytes_per_second']=max(0,physical[0]-attributed[0])
    out['unattributed_write_bytes_per_second']=max(0,physical[1]-attributed[1])
    return out


def observe(w):
    standby=w.standby
    binding=standby.identity(w); topo=topology(w,binding)
    first=capture(w,topo); before,_=standby.activity(binding); start=time.monotonic()
    time.sleep(2)
    last=capture(w,topo); after,inflight=standby.activity(binding); elapsed=time.monotonic()-start
    if standby.identity(w)!=binding or topology(w,binding)!=topo:
        raise w.Unsafe('Drive connection or mounts changed; take a new activity sample.')
    result=report(first,last,binding,topo,before,after,elapsed)
    result.update(observed_at=w.timestamp(),in_flight=inflight)
    return result
