# SPDX-License-Identifier: MIT
"""Isolated GUI fixture: real HTTP, sessions, validation and private file writes.

Only OS boundaries (PAM, discovery, mount observations and systemd) are synthetic.
An optional installed payload root allows the same browser suite to test a deb.
No host configuration, services, mounts, USB or Docker are accessed.
"""
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

UUID = '11111111-1111-4111-8111-111111111111'
DESKTOP = '/run/media/test/USW_TEST'
if os.environ.get('USW_GUI_FIXTURE'):
    # Private real-world identity supplied at runtime, never bundled in releases.
    fixture = json.loads(Path(os.environ['USW_GUI_FIXTURE']).read_text())
    UUID, DESKTOP = fixture['uuid'], fixture['mountpoint']
STABLE = '/mnt/usb-storage-watch-' + UUID


def load(name,profile=None):
    root = Path(os.environ.get('USW_GUI_PAYLOAD', Path(__file__).resolve().parents[1] / 'src/usb_storage_watch'))
    spec = importlib.util.spec_from_file_location('gui_' + name, root / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    if profile is not None:module.PROFILE=profile
    spec.loader.exec_module(module)
    return module


class Machine:
    def __init__(self,root=None,identifier='legacy',uuid=UUID,mountpoint=DESKTOP,model='External test disk',dev='240:1'):
        self.stack = ExitStack()
        self.root = Path(root) if root else Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='usw-gui-')))
        self.uuid,self.model,self.dev=uuid,model,dev
        profile=dict(id=identifier,config_root=str(self.root/'config'),state_root=str(self.root/'state'))
        self.b = load('web_broker',profile)
        self.web = load('web')
        self.active = False
        self.environment = dict(kind='physical', name='')
        self.current = mountpoint
        self.present = True
        self.calls = []
        self.fstab = self.root / 'fstab'
        self.original = '# Existing system configuration must remain byte-for-byte intact.\n'
        if not self.fstab.exists():self.fstab.write_text(self.original)
        self.config = self.b.s.CONFIG
        self.state = self.b.s.STATE_DIR
        self.state.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.disk_data = self.root / ('disk-data-'+identifier)
        self.disk_data.mkdir()
        (self.disk_data / 'sentinel').write_bytes(b'Existing filesystem contents\x00preserve me')
        b = self.b
        real_uid=b.pwd.getpwuid
        self.patch(b.pwd,'getpwuid',lambda uid:Mock(pw_name='admin',pw_uid=1000,pw_gid=1000) if uid==1000 else real_uid(uid))
        real_account=b.pwd.getpwnam
        self.patch(b.pwd,'getpwnam',lambda name:Mock(pw_uid=1000,pw_gid=1000) if name=='admin' else real_account(name))
        self.patch(b, 'FSTAB', self.fstab)
        self.patch(b.s, 'CONFIG', self.config)
        self.patch(b.s, 'SMTP', self.root/'config'/'smtp.json')
        self.patch(b.n, 'load_config', lambda: b.n.validate_config(json.loads(b.s.SMTP.read_text())))
        self.patch(b.s, 'STATE_DIR', self.state)
        self.patch(b.w, 'STATE_DIR', self.state)
        original_read = b.s.read
        self.patch(b.s, 'read', lambda *args, **kwargs: original_read(self.config, protected=False))
        self.patch(b.common, 'WEB_DIR', self.root)
        self.network = self.root / 'web-config.json'
        if not self.network.exists():self.network.write_text(json.dumps(b.common.DEFAULT))
        self.patch(b.common, 'WEB_CONFIG', self.network)
        self.patch(b, 'disks', self.disks)
        self.patch(b,'drive_metadata',lambda _:dict(model=self.model,manufacturer='Test manufacturer',size=32*1024**3,filesystem='ext4',cached=not self.present))
        self.patch(b, 'virtualization', lambda: self.environment)
        self.patch(b, 'command', self.command)
        self.patch(b.cli, 'stopped', self.stopped)
        original_path = b.cli.root_path
        self.patch(b.cli, 'root_path', lambda root, path: original_path('/', self.root / 'mounts' / str(path).lstrip('/'))
                   if str(path).startswith(('/mnt/', '/run/media/', '/media/')) else original_path(root, path))
        original_write = b.w.atomic_write
        def write(path, value, *args, **kwargs):
            assert Path(path).is_relative_to(self.root), 'Fixture blocked host write'
            return original_write(path, value, *args, **kwargs)
        self.patch(b.w, 'atomic_write', write)
        self.patch(b.w, 'read_rows', self.mount_rows)
        self.patch(b.w, 'fstab_check', self.fstab_check)
        self.patch(b.w, 'snapshot', self.snapshot)
        self.patch(b.w, 'device_number', lambda path: self.dev)
        self.patch(b.w.drives,'hardware',Mock(side_effect=FileNotFoundError('No synthetic hardware cache')))
        self.patch(b.w, 'block_checks', Mock(return_value='synthetic1'))
        self.patch(b.w, 'mount_available', Mock())
        self.patch(b.w, 'protected_mount_directory', self.directory)
        self.patch(b.w, 'load_state', lambda *args: {})
        self.patch(b, 'container_rows', Mock(return_value=[]))
        self.patch(b.cli, 'bounded_candidate', Mock(side_effect=ValueError('USB2/USB3 peer link detected. A peer can represent the same physical connector; it does not prove isolation is impossible. Reciprocal root-port pair found. This release has only single-port reset/cleanup support. Paired electrical isolation is unqualified; keep resets off. See USB-PEER-QUALIFICATION.md for offline assessment.')))
        sessions = b.auth.Sessions(lambda u, p: u == 'admin' and p == 'synthetic')
        self.broker = b.Broker(Mock(events=lambda: []), sessions)

    def management_token(self):
        self.patch(self.b.auth,'administrator',lambda name:Mock(pw_name=name,pw_uid=1000,pw_gid=1000))
        token,record=self.b.auth.new_management_token('admin')
        self.b.cli.save(self.config.with_name('management-token.json'),record)
        return token

    def patch(self, target, name, value):
        return self.stack.enter_context(patch.object(target, name, value))

    def close(self):
        self.stack.close()

    def disks(self):
        return [dict(uuid=self.uuid, mountpoint=self.current, eligible=True, device='/dev/synthetic1',
                     model=self.model, size=32 * 1024**3, filesystem='ext4', transport='usb', reason='')] if self.present else []

    def mount_rows(self):
        return self.b.w.parse_mounts('1 0 240:0 / / rw - ext4 /dev/system rw\n'
                                    '2 1 0:17 / /run rw - tmpfs tmpfs rw\n' + (
                                        f'3 {2 if self.current.startswith("/run/") else 1} {self.dev} / {self.current} rw - ext4 /dev/synthetic1 rw\n' if self.current else ''))

    def directory(self, target, backing, mounted=False, create=False):
        if create:
            self.b.cli.root_path('/', target).mkdir(mode=0o755, parents=True, exist_ok=True)

    def snapshot(self):
        healthy = self.present and self.current == self.b.w.MOUNT
        return dict(healthy=healthy, detected=self.present, detail='Mounted read/write.' if healthy else 'Waiting for the configured mountpoint.', mounts=self.mount_rows())

    def stopped(self):
        if self.active:
            raise ValueError('Stop monitoring before changing its configuration')

    def command(self, args, timeout=10):
        self.calls.append(args)
        if args[:2] == ['/usr/sbin/ip', '-j']: return '[]'
        if args[:2] == ['/usr/bin/systemctl', 'show']:
            return 'ActiveState=' + ('active' if self.active else 'inactive') + '\nSubState=' + ('running' if self.active else 'dead') + '\nUnitFileState=' + ('enabled' if self.active else 'disabled')
        if args[:2] == ['/usr/bin/systemctl', 'stop']:
            self.active = False
            return ''
        if args[:2] == ['/usr/bin/systemctl', 'start']:
            self.active = True
            return ''
        if args[:2] == ['/usr/bin/systemctl', 'enable']:
            self.active = True
            return ''
        if args[:2] == ['/usr/bin/systemctl', 'disable']:
            self.active = False
            return ''
        if args == ['/usr/bin/systemctl', 'daemon-reload']:
            return ''
        if args[0] == '/usr/bin/journalctl':
            return ''
        raise AssertionError('Fixture blocked unexpected command: ' + str(args))

    def fstab_check(self, target):
        c = self.b.w.SETTINGS
        expected = ['UUID=' + c['disk']['uuid'], target, 'ext4', c['disk']['fstab_options']]
        entries = [line.split() for line in self.fstab.read_text().splitlines() if line.startswith('UUID=') and line.split()[1] == target]
        if len(entries) != 1 or entries[0][:4] != expected:
            raise self.b.w.Unsafe('Existing fstab identity/options changed or are ambiguous; refusing mount.')

    def payload(self, **values):
        c = self.b.configuration()
        return dict(revision=self.b.s.digest(c), uuid=UUID, label='USB test', mount=True,
                    usb=False, docker=False, notifications=False, confirmations=['mount', 'fstab'], **values)
