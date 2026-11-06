# SPDX-License-Identifier: MIT
"""Real engine _manual process; only host privilege/storage observations are fake."""
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gui_fixture import load

root = Path(sys.argv[1]).resolve()
assert root.name.startswith('usw-gui-') and root.is_dir()
w = load('engine', dict(id='legacy', config_root=str(root/'config'), state_root=str(root/'state')))
sys.modules[w.__name__] = w
read = w.settings.read
w.settings.read = lambda *args, **kwargs: read(w.settings.CONFIG, protected=False)
w.os = SimpleNamespace(**(vars(os) | dict(geteuid=lambda: 0)))  # Engine entry check only; real locks retain the real UID.
w.assert_internal_state = lambda: None
w.usb.ensure_enabled = lambda *_: True
w.read_rows = lambda: json.loads((root/'rows.json').read_text())
w.device_number = lambda _: '240:1'
w.standby.identity = lambda *_: {}
w.snapshot = lambda: dict(healthy=bool(w.read_rows()), dependent=True)

def event(value):
    with (root/'worker-events').open('a') as stream: stream.write(value+'\n')

def mounted(rows, target, dev, uuid):
    assert uuid == w.DISK_UUID and dev == '240:1'
    return next(v for v in rows if v['target'] == target and v['dev'] == dev)

def users(*_):
    runtime = json.loads((root/'runtime.json').read_text())
    assert all(not runtime[v['container_id']]['running'] for v in w.SETTINGS['docker']['containers'])
    assert len(w.WORKER_LOCK_FDS) >= 4  # Broker app/drive plus worker storage locks.
    event('users')
    (root/'worker-ready').write_text(str(os.getpid()))
    deadline = time.monotonic()+10
    while (root/'pause-worker').exists():
        if time.monotonic() > deadline: raise w.Unsafe('Fixture gate timed out')
        time.sleep(.02)
    if (root/'busy-storage').exists(): raise w.Unsafe('An unrelated process holds this disk open.')

def command(argv, **kwargs):
    assert argv[0] in ('/usr/bin/umount', '/usr/bin/sync'), argv
    # Deliberately no subprocess/real mount operation at this boundary.
    if argv[0].endswith('/umount'):
        event('unmount:image' if argv[-1].endswith('/files') else 'unmount:disk')
        (root/'rows.json').write_text(json.dumps([v for v in w.read_rows() if v['target'] != argv[-1]]))
    else: event('sync')

w.mounted_checks = mounted
w.standby.users = users
w.verify_dependent = lambda *_: event('verify:image')
w.mount_available = lambda rows, target, dev: None if not any(v['target']==target for v in rows) else (_ for _ in ()).throw(w.Unsafe('Still mounted'))
w.command = command
sys.argv = [str(Path(w.__file__)), '_manual']
try:
    raise SystemExit(w.main())
except Exception:
    import traceback
    (root/'worker-error').write_text(traceback.format_exc())
    raise
