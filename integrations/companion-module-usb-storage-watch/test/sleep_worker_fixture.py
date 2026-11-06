# SPDX-License-Identifier: MIT
"""Real manual engine/standby sequence against synthetic block users and writes."""
import json,os,sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tests'))
from gui_fixture import load
root=Path(sys.argv[1]).resolve();mode=sys.argv[2];assert root.name.startswith('usw-gui-') and root.is_dir()
w=load('engine',dict(id='legacy',config_root=str(root/'config'),state_root=str(root/'state')));sys.modules[w.__name__]=w
read=w.settings.read;w.settings.read=lambda *a,**k:read(w.settings.CONFIG,protected=False)
w.os=SimpleNamespace(**(vars(os)|dict(geteuid=lambda:0)));w.assert_internal_state=lambda:None
w.usb.load=lambda *_:None;w.snapshot=lambda:dict(healthy=True,dependent=True)
path=root/'synthetic-disk';path.touch();sysdir=root/'sysdisk';sysdir.mkdir(exist_ok=True);(sysdir/'dev').write_text('240:1')
binding=dict(path=str(path),sys=str(sysdir));w.standby.identity=lambda *_:binding;w.device_number=lambda _:'240:1'
def event(v):
 with (root/'sleep-events').open('a') as f:f.write(v+'\n')
def users(*_):
 event('users')
 if mode=='sleep-busy':raise w.standby.refusal(w,'busy','Synthetic writer PID 123 holds the drive.')
w.standby.users=users;w.standby.storage_kind=lambda *_:'mechanical';w.standby.status=lambda *_:dict(sleeping=False)
w.standby.filesystems=lambda *_:([],[str(root/'mounted')]);w.standby.subprocess=SimpleNamespace(run=lambda *a,**k:SimpleNamespace(returncode=1,stdout='',stderr=''))
now=[0];w.standby.time=SimpleNamespace(monotonic=lambda:now[0],sleep=lambda secs:now.__setitem__(0,now[0]+secs))
w.standby.activity=lambda _:([now[0] if mode=='sleep-writes' else 1],0)
def command(argv,**kwargs):
 assert argv[:3]==['/usr/bin/sync','-f','--'];event('sync')
w.command=command
def power(ctx,flag,pinned):
 assert flag in ('-y','-C') and pinned.startswith('/proc/self/fd/');event(flag)
 return 'drive state is: standby'
w.standby.power_command=power
sys.argv=[w.__file__,'_manual'];raise SystemExit(w.main())
