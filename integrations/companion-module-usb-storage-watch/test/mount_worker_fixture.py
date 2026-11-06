# SPDX-License-Identifier: MIT
"""Real manual worker ownership; disk discovery/mounting stays synthetic."""
import json,os,sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tests'))
from gui_fixture import load
root=Path(sys.argv[1]).resolve();assert root.name.startswith('usw-gui-') and root.is_dir()
w=load('engine',dict(id='legacy',config_root=str(root/'config'),state_root=str(root/'state')));sys.modules[w.__name__]=w
read=w.settings.read;w.settings.read=lambda *a,**k:read(w.settings.CONFIG,protected=False)
w.os=SimpleNamespace(**(vars(os)|dict(geteuid=lambda:0)));w.assert_internal_state=lambda:None
w.usb.ensure_enabled=lambda *_:True
class FixturePath(type(Path())):
 def exists(self):return True if str(self)=='/dev/disk/by-uuid/'+w.DISK_UUID else super().exists()
w.controls.Path=FixturePath;w.controls.request=lambda *_:dict(manual=True)
def mount(request,receipt):
 assert w.MANUAL_MOUNT and request['allow_usb'] is False and request['usb_resets']==0
 assert len(w.WORKER_LOCK_FDS)==2
 (root/'rows.json').write_text((root/'original-rows.json').read_text())
 with (root/'mount-events').open('a') as f:f.write('mount:disk\nmount:image\nverify:storage\n')
 return dict(main=True,dependent=True)
w.recovery_work=mount;w.snapshot=lambda:dict(healthy=bool(json.loads((root/'rows.json').read_text())),dependent=True)
sys.argv=[w.__file__,'_manual'];raise SystemExit(w.main())
