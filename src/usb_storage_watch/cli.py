# SPDX-License-Identifier: MIT
"""Interactive administration; never probes by writing to disks or USB ports."""
import argparse
import copy
import getpass
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True


def module(name):
    spec=importlib.util.spec_from_file_location('usw_'+name,Path(__file__).with_name(name+'.py'))
    value=importlib.util.module_from_spec(spec)
    if globals().get('PROFILE') is not None:value.PROFILE = dict(PROFILE)
    spec.loader.exec_module(value)
    return value

s=module('settings')
w=module('engine')
n=module('notify')
# The engine's nested configuration reads must share the same thread-local
# lock ownership as the administration transaction which calls them. Loading
# drives.py a second time creates a separate owner registry and makes our own
# flock look like a competing settings save.
drives=w.drives
SERVICE=s.SERVICE
n.CONFIG=s.SMTP


def run(argv, timeout=10):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=True)


def root_path(root, path):
    root=Path(root).absolute()
    if root.is_symlink() or root.resolve()!=root:
        raise ValueError('Installation root must not contain symlinks')
    dest=root/str(path).lstrip('/')
    for part in [*reversed(dest.parents),dest]:
        if part.is_symlink():
            raise ValueError('Refusing a symlink in an installation/configuration path')
    return dest


def ask(prompt, default=''):
    value=input(prompt+(f' [{default}]' if default else '')+': ').strip()
    return value or default


def yes(prompt, default=False):
    while True:
        value = ask(prompt, 'yes' if default else 'no').lower()
        if value in ('yes', 'y', 'no', 'n'):
            return value in ('yes', 'y')
        print('Enter yes or no (y or n).')


def integer(prompt, default, low, high):
    while True:
        value = ask(prompt, str(default) if default != '' else '')
        if value.isascii() and value.isdecimal() and low <= int(value) <= high:
            return int(value)
        print(f'{prompt}: enter a whole number from {low} to {high}.')


def stopped():
    result=subprocess.run(['/usr/bin/systemctl','is-active','--quiet',SERVICE],timeout=8)
    if result.returncode not in (3,4):
        raise ValueError('Stop '+SERVICE+' before changing its configuration; unknown service state is unsafe')
    directory=s.STATE_DIR
    for filename in ('usb-reset.json','state.json'):
        path=directory/filename
        if not path.exists(): continue
        value=json.loads(path.read_text())
        if filename=='usb-reset.json' and value.get('phase')!='enabled':
            raise ValueError('A USB enable obligation remains. Resolve it before reconfiguration')
        if filename=='state.json' and value.get('incident') and value['incident']['phase'] not in ('done','legacy'):
            raise ValueError('An incident is still in progress; retain its configuration until it finishes')


def save(path, value):
    if Path(path)==s.CONFIG:
        with drives.configuration_lock(s):
            drives.validate_shared(s,value)
            return _save(path,value)
    return _save(path,value)


def _save(path, value):
    path=root_path('/',path)
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if path.parent.stat().st_uid!=os.geteuid() or path.parent.stat().st_mode & 0o077:
        raise ValueError('Configuration directory must be owned by the current installer and mode 0700')
    if path.exists():
        backup=path.with_name(path.name+'.previous')
        w.atomic_write(backup,path.read_text())
    w.atomic_write(path,json.dumps(value,indent=2)+'\n')


def flatten(items):
    for item in items:
        yield item
        yield from flatten(item.get('children',[]))


def disks():
    result=run(['/usr/bin/lsblk','--json','--paths','--output','NAME,TYPE,FSTYPE,UUID,MOUNTPOINTS,SIZE,MODEL'],8)
    rows=[]
    for disk in json.loads(result.stdout)['blockdevices']:
        descendants=list(flatten([disk]))
        # Exclude the whole system disk, including its other partitions.
        if any(p in ('/','/boot','/boot/efi','/usr','/var')
               for item in descendants for p in (item.get('mountpoints') or [])):
            continue
        for item in descendants:
            if item.get('fstype')=='ext4' and item.get('uuid') and item.get('type') in ('disk','part'):
                rows.append(dict(item,model=item.get('model') or disk.get('model')))
    return rows


def smtp_setup(path):
    print('Use your mail provider\'s SMTP settings and, if required, an app password. Password input is hidden.')
    while True:
        security=ask('TLS mode: starttls (usually 587) or tls (usually 465)','starttls').lower()
        if security in ('starttls', 'tls'):
            break
        print('Enter starttls or tls; unencrypted SMTP is not supported.')
    value={'version':1,'security':security,'host':ask('SMTP server'),
           'port':integer('SMTP port',465 if security=='tls' else 587,1,65535),
           'username':ask('SMTP login'),'password':getpass.getpass('SMTP password (hidden): '),
           'sender':ask('Sender email address'),'recipient':ask('Recipient email address')}
    n.validate_config(value); save(path,value)


def setup():
    stopped()
    path=s.CONFIG
    c=s.read(path) if path.exists() else s.default()
    print('USB Storage Watch setup. This does not mount disks, reset ports, restart containers or start the service.')
    rows=disks()
    if not rows: raise ValueError('No eligible ext4 data disk found. Attach the intended ext4 disk and wait for device discovery. System disks are excluded.')
    for index,row in enumerate(rows,1):
        print(f"{index}. {row['name']}  {row.get('size')}  {row.get('model') or ''}  UUID={row['uuid']}  mounted={row.get('mountpoints')}")
    index=integer('Select the disk number','',1,len(rows))-1
    selected=rows[index]
    mounted=[x for x in selected.get('mountpoints',[]) if x]
    old_target=(c['disk']['uuid'],c['disk']['mountpoint'])
    c['disk'].update(uuid=selected['uuid'],mountpoint=ask('Permanent mountpoint',mounted[0] if mounted else '/mnt/storage'),label=ask('Email label','USB storage'))
    if old_target[0] and old_target!=(c['disk']['uuid'],c['disk']['mountpoint']):
        raise ValueError('Changing the watched disk requires archiving old state first; see maintenance documentation')
    c['notifications']['enabled']=yes('Configure email notifications?',True)
    if c['notifications']['enabled']:
        if not s.SMTP.exists() or not yes('Keep the existing protected SMTP settings?',True):
            smtp_setup(s.SMTP)
        else: n.load_config()
    c['recovery']['mount']=yes('Enable automatic guarded normal mounts? Requires a reviewed /etc/fstab entry',False)
    if c['recovery']['mount']:
        c['disk']['fstab_options']=ask('Exact comma-separated options from the disk fstab entry','defaults,nofail,x-systemd.device-timeout=10s')
    else: c['disk']['fstab_options']=''
    c['dependent']['enabled']=yes('Monitor an existing dependent ext4 loop image?',False)
    if c['dependent']['enabled']:
        c['dependent'].update(uuid=ask('Loop filesystem UUID'),mountpoint=ask('Loop mountpoint under the primary disk'),image=ask('Backing image path under the primary disk'),fstab_options=ask('Exact loop fstab options','loop,nosuid,nodev,noexec,nofail'))
    c['usb']['enabled']=False
    print('USB resets remain disabled. Qualification on this hardware is a separate advanced procedure.')
    c['docker']['enabled']=yes('Restart selected Docker containers after this drive recovers?',False)
    c['docker']['containers']=[]
    if c['docker']['enabled']:
        while True:
            name=ask('Container name (empty to finish)')
            if not name: break
            c['docker']['containers'].append({'name':name,'source':'','destination':'',
                'container_id':'','images':[],
                'grace':integer('Graceful shutdown timeout in seconds',30,5,120)})
        c['docker']['enabled']=bool(c['docker']['containers'])
        print('Choose optional virtual images in Docker & Applications. Storage paths do not restrict restart selection.')
    if yes('Customize monitoring/recovery timing?',False):
        for group,key,prompt,low,high in [('monitor','interval','Monitoring interval seconds',5,3600),('monitor','observations','Consecutive observations',1,10),('recovery','wait','Wait before each attempt seconds',15,86400),('recovery','attempts','Maximum attempts',1,2)]:
            c[group][key]=integer(prompt,c[group][key],low,high)
    s.validate(c)
    w.configure(c)
    if c['recovery']['mount']: w.fstab_check(w.MOUNT)
    if c['dependent']['enabled'] and c['recovery']['mount']: w.fstab_check(w.DEPENDENT)
    print(f"Disk: {c['disk']['uuid']} at {c['disk']['mountpoint']}; automatic mounts={c['recovery']['mount']}, USB=False, Docker={c['docker']['enabled']}")
    if not yes('Save this configuration?',True): return
    save(path,c)
    print('Saved. Run: sudo usb-storage-watch validate; sudo usb-storage-watch diagnose')
    print('Then test email and explicitly start: sudo systemctl enable --now '+SERVICE)


def candidate():
    c=s.read(); w.configure(c)
    dev=w.verify_main()
    real=(Path('/sys/dev/block')/dev).resolve(strict=True)
    device=next((p for p in real.parents if (p/'idVendor').is_file() and (p/'idProduct').is_file()),None)
    if device is None or not re.fullmatch(r'\d+-\d+',device.name):
        raise ValueError('Only a directly attached USB root port is supported; hubs are unsupported')
    bus,port=device.name.split('-'); controller=device.parent.parent
    portpath=Path(f'/sys/bus/usb/devices/{bus}-0:1.0/usb{bus}-port{port}')
    peer = w.usb.peer_diagnostic(portpath)
    if peer:
        raise ValueError(peer['message'])
    if not (portpath/'firmware_node').exists():
        raise ValueError('USB port has no stable firmware identity; port recovery is unsupported. Keep USB resets disabled.')
    root=Path('/sys/bus/usb/devices')/('usb'+bus)
    def values(path,keys): return {key:(path/key).read_text().strip() for key in keys}
    p={'controller':'/sys/bus/pci/devices/'+controller.name,'controller_real':str(controller),
       'controller_ids':values(controller,('vendor','device','subsystem_vendor','subsystem_device','class','revision')),
       'root_hub':str(root),'root_hub_ids':values(root,('idVendor','idProduct','serial')),
       'port':str(portpath),'canonical':str(portpath.resolve(strict=True)),'device':'/sys/bus/usb/devices/'+device.name,
       'device_real':str(device),'firmware':str((portpath/'firmware_node').resolve(strict=True)),
       'vid':(device/'idVendor').read_text().strip(),'pid':(device/'idProduct').read_text().strip(),
       'disk_serial':w.udev(dev).get('ID_SERIAL',''),'qualified':False,'qualification':None}
    s.usb_profile(p)
    # Read-only binding verification. This does not qualify or enable recovery.
    probe=copy.deepcopy(p); probe['qualified']=True
    w.usb.configure(probe)
    try: w.usb.healthy_binding(w.usb_context(),dev)
    finally: w.usb.configure(c['usb']['profile'])
    return p


def bounded_candidate():
    # Direct block proof is read-only but may block in the kernel. Supervise it.
    try:
        result=run([sys.executable,'-I',str(Path(__file__).resolve()),'_candidate'],30)
    except subprocess.CalledProcessError as exc:
        # Only relay our own bounded administration diagnostic, never raw device data.
        message=(exc.stderr or '').strip()
        if message.startswith('Operation stopped: '):
            raise ValueError(message.removeprefix('Operation stopped: ')[:500]) from None
        raise ValueError('USB candidate verification failed; keep USB resets disabled.') from None
    return json.loads(result.stdout)


def qualify(profile, evidence, date):
    stopped()
    c=s.read(); p=json.loads(Path(profile).read_text()); s.usb_profile(p)
    # Recollect while healthy; reject hardware moved since the independent test.
    current=bounded_candidate()
    unsigned=copy.deepcopy(p); unsigned.update(qualified=False,qualification=None)
    if unsigned!=current: raise ValueError('Candidate does not match the current healthy disk/controller/port')
    print('Only continue after an independent OFFLINE physical qualification documented in docs/USB-QUALIFICATION.md.')
    print('You attest isolated port behavior, successful re-enable, correct disk return and no other disconnections.')
    if ask('Type QUALIFIED to attest and enable one reset per outage')!='QUALIFIED': raise ValueError('Qualification cancelled')
    p.update(qualified=True,qualification={'date':date,'evidence':evidence,'isolated_port':True,'reenable_verified':True,'expected_disk_returned':True})
    c['usb'].update(profile=p,enabled=True); s.validate(c); save(s.CONFIG,c)
    print('Qualified profile saved. Restart the service explicitly after validation. No USB write was performed.')


def validate(root):
    config=root_path(root,s.CONFIG); c=s.read(config,protected=str(root)=='/')
    if c['notifications']['enabled']:
        path=root_path(root,s.SMTP)
        if str(root)=='/': n.load_config()
        else: n.validate_config(json.loads(path.read_text()))
    print('Configuration valid; credentials withheld. Automatic actions: '+json.dumps({k:c[k]['enabled'] for k in ('usb','docker')}|{'mount':c['recovery']['mount']}))
    return c


def diagnose(root):
    c=validate(root)
    print('Package version: '+s.VERSION)
    if str(root)!='/':
        print('Staged installation: no host device, service, SMTP or Docker probes performed.'); return 0
    w.configure(c); w.assert_internal_state()
    for program in ('/usr/bin/mount','/usr/sbin/blkid','/usr/sbin/losetup','/usr/bin/udevadm'):
        print(program+': '+('available' if Path(program).exists() else 'MISSING'))
    current=w.snapshot(); print(json.dumps(current,indent=2))
    w.load_state()
    if c['recovery']['mount']: w.fstab_check(w.MOUNT)
    if c['dependent']['enabled'] and c['recovery']['mount']: w.fstab_check(w.DEPENDENT)
    print('Persistent state and enabled fstab guards valid.')
    print('Docker bind/health preflight: sudo usb-storage-watch verify-apps (read-only; no restarts).')
    return 0 if current['healthy'] else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',action='version',version='USB Storage Watch '+s.VERSION)
    parser.add_argument('--root',default='/',help='staged root; validate/diagnose only, no host probes')
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('setup','smtp-setup','validate','diagnose','check','status','test-email','verify-apps','run','web-enable','web-disable'):
        sub.add_parser(command)
    sub.add_parser('_candidate',help=argparse.SUPPRESS)
    p=sub.add_parser('usb-candidate');p.add_argument('--output',required=True)
    p=sub.add_parser('qualify-usb');p.add_argument('--profile',required=True);p.add_argument('--evidence',required=True);p.add_argument('--date',required=True)
    args=parser.parse_args(); root=str(Path(args.root).absolute())
    if root!='/' and args.command not in ('validate','diagnose'):
        parser.error('--root supports only validate/diagnose; no host actions')
    if root=='/' and os.geteuid()!=0: parser.error('Use sudo for administration')
    os.umask(0o077)
    if args.command=='validate': validate(root)
    elif args.command=='diagnose': return diagnose(root)
    elif args.command=='setup': setup()
    elif args.command=='smtp-setup': stopped();smtp_setup(s.SMTP)
    elif args.command in ('web-enable','web-disable'): module('web_install').main(args.command.removeprefix('web-'))
    elif args.command=='_candidate': print(json.dumps(candidate()))
    elif args.command=='usb-candidate': save(Path(args.output).absolute(),bounded_candidate());print('Unqualified candidate saved; contains private hardware identity. USB recovery remains disabled.')
    elif args.command=='qualify-usb': qualify(args.profile,args.evidence,args.date)
    else:
        command={'test-email':'test','verify-apps':'_verify-apps'}.get(args.command,args.command)
        if command=='run': os.execv(sys.executable,[sys.executable,'-I',str(Path(__file__).with_name('engine.py')),command])
        # Diagnostics that touch storage run in a bounded child.
        result=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('engine.py')),command],timeout=30)
        return result.returncode
    return 0

if __name__=='__main__':
    try: raise SystemExit(main())
    except (Exception,KeyboardInterrupt) as exc:
        # SMTP exception text is never relayed.
        print('Operation stopped: '+(str(exc) if isinstance(exc,(ValueError,w.Unsafe)) else type(exc).__name__),file=sys.stderr)
        raise SystemExit(1)
