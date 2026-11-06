# SPDX-License-Identifier: MIT
"""Real settings locks and engine mount routing, with device I/O stubbed."""
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui_fixture import load


class ImageConfigurationLocks(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        profile=dict(id='legacy',config_root=str(self.root/'config'),state_root=str(self.root/'state'))
        self.b=load('web_broker',profile)
        self.w=self.b.w
        # File ownership is separately tested; this fixture runs without root.
        for settings in (self.b.s,self.w.settings):
            read=settings.read
            self.patch(settings,'read',lambda path=None,protected=True,read=read,settings=settings:
                       read(path or settings.CONFIG,protected=False))
        self.b.s.STATE_DIR.mkdir(mode=0o700,parents=True)
        mount=self.root/'disk'
        mount.mkdir()
        target=mount/'image'
        target.mkdir()
        backing=mount/'backups.img'
        backing.write_bytes(b'synthetic image; no filesystem is formatted')
        self.item=dict(name='backups',uuid='22222222-2222-4222-8222-222222222222',
                       image=str(backing),mountpoint=str(target),enabled=False,
                       fstab_options='loop,noauto,nofail,nodev,nosuid,noexec')
        self.config=self.b.s.default()
        self.config['disk'].update(uuid='11111111-1111-4111-8111-111111111111',
                                  mountpoint=str(mount),fstab_options='defaults')
        self.config['images']=[self.item]
        self.config['recovery']['mount']=False
        self.b.cli.save(self.b.s.CONFIG,self.config)
        self.w.configure(self.config)
        self.rows=[dict(target=str(mount),dev='240:1',id='2')]
        self.commands=[]
        self.active=False
        self.patch(self.b,'service_state',lambda:dict(ActiveState='active' if self.active else 'inactive'))
        self.patch(self.b,'command',self.service_command)
        self.patch(self.b.cli,'stopped',Mock())
        self.patch(self.w,'assert_internal_state',Mock())
        self.patch(self.w,'verify_main',Mock(return_value='240:1'))
        self.patch(self.w,'read_rows',lambda:list(self.rows))
        self.patch(self.w,'visible_mount',lambda rows,path:next((r for r in reversed(rows) if self.w.covers(r['target'],path)),None))
        self.patch(self.w,'safe_path',lambda path,*args,**kwargs:Path(path).stat())
        self.patch(self.w,'fstab_check',Mock())
        self.patch(self.w,'disk_proof',Mock())
        self.patch(self.w,'verify_dependent',self.verify_image)
        self.patch(self.w,'Path',lambda value:SimpleNamespace(glob=lambda pattern:[]) if str(value)=='/sys/class/block' else Path(value))
        self.patch(self.w.subprocess,'run',self.disk_command)

    def patch(self,target,name,value):
        return self.stack.enter_context(patch.object(target,name,value))

    def verify_image(self,item):
        self.assertTrue(any(row['target']==item['mountpoint'] for row in self.rows))

    def disk_command(self,argv,**kwargs):
        self.assertEqual(argv,['/usr/bin/mount','--',self.item['mountpoint']])
        self.assertTrue(self.w.MANUAL_MOUNT)
        self.commands.append(list(argv))
        self.rows.append(dict(target=self.item['mountpoint'],dev='240:2',id='3'))
        return SimpleNamespace(returncode=0,stdout='',stderr='')

    def service_command(self,argv,timeout=10):
        self.assertEqual(argv[0],'/usr/bin/systemctl')
        self.assertEqual(argv[2],self.b.cli.SERVICE)
        if argv[1]=='start':
            # A newly started monitor is another process/open-file description.
            # It must be able to take the settings lock before start returns.
            path=self.b.s.STATE_DIR/'shared-locks'/'configuration.lock'
            with path.open('a') as other:
                fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.flock(other,fcntl.LOCK_UN)
            self.active=True
        elif argv[1]=='stop':
            self.active=False
        else:
            self.fail('Unexpected service command '+str(argv))
        return ''

    def test_nested_engine_read_uses_same_lock_registry(self):
        self.assertIs(self.b.cli.drives,self.w.drives)
        with self.b.cli.drives.configuration_lock(self.b.s):
            loaded=self.w.config_load()
        self.assertFalse(loaded['automatic_recovery'])

    def test_real_manual_image_mount_while_recovery_off(self):
        result=self.b.images.manage(self.b.image_context(),dict(uuid=self.item['uuid'],action='mount'))
        self.assertIn('mounted and verified',result['message'])
        self.assertEqual(len(self.commands),1)
        self.assertFalse(self.w.MANUAL_MOUNT)
        saved=self.b.configuration()
        self.assertFalse(saved['recovery']['mount'])
        self.assertFalse(saved['images'][0]['enabled'])

    def test_monitor_starts_after_settings_lock_release(self):
        self.active=True
        self.test_real_manual_image_mount_while_recovery_off()
        self.assertTrue(self.active)

    def test_competing_settings_owner_still_refused(self):
        directory=self.b.s.STATE_DIR/'shared-locks'
        directory.mkdir(mode=0o700,exist_ok=True)
        path=directory/'configuration.lock'
        fd=os.open(path,os.O_RDWR|os.O_CREAT,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch.object(self.w.time,'monotonic',side_effect=[0,3]),patch.object(self.w.time,'sleep'):
                with self.assertRaisesRegex(self.w.Unsafe,'Settings are being saved'):
                    self.w.config_load()
        finally:
            os.close(fd)

    def test_manual_override_restored_after_mount_failure(self):
        with patch.object(self.w.subprocess,'run',side_effect=OSError('synthetic mount failure')):
            with self.assertRaisesRegex(OSError,'synthetic mount failure'):
                self.b.images.manage(self.b.image_context(),dict(uuid=self.item['uuid'],action='mount'))
        self.assertFalse(self.w.MANUAL_MOUNT)
        self.assertEqual(self.commands,[])

    def test_automatic_mount_still_obeys_disabled_recovery(self):
        with self.assertRaisesRegex(self.w.Unsafe,'Mount recovery disabled'):
            self.w.command(['/usr/bin/mount','--',self.item['mountpoint']])
        self.assertEqual(self.commands,[])


if __name__=='__main__':
    unittest.main()
