# SPDX-License-Identifier: MIT
"""Focused regressions; all disk and port operations are synthetic."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from gui_fixture import Machine, UUID, DESKTOP, STABLE, load
from fixtures import configuration


class PortBindingTests(unittest.TestCase):
    def setUp(self):
        self.w = load('engine'); self.u = self.w.usb
        self.c = configuration(self.w); self.c['usb']['profile'] = None
        self.w.configure(self.c)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.ctx = self.w.usb_context(Path(self.tmp.name))
        self.ctx.boot_id = lambda: 'test-boot'
        self.ctx.device_number = Mock(return_value='240:17')
        self.ctx.udev = Mock(return_value=dict(ID_BUS='usb', ID_SERIAL='SYNTHETIC-TEST-DISK', ID_FS_UUID=UUID, ID_FS_TYPE='ext4'))
        self.profile = configuration(self.w)['usb']['profile'] | dict(mode='software', qualified=False, qualification=None)
        self.live = self.enterContext(patch.object(self.u, 'discover', return_value=self.profile))
        self.enterContext(patch.object(self.u, 'healthy_binding', side_effect=lambda w, dev: self.u.binding_signature(w) | dict(main_dev=dev, sources=['/dev/synthetic1'], observed_at='test')))

    def test_software_profile_does_not_require_physical_power_attestation(self):
        self.w.settings.usb_profile(self.profile, qualified=True)
        self.u.bind_current(self.ctx, '240:17')
        self.assertTrue(self.u.HOST_VERIFIED)
        self.assertFalse(self.u.PROFILE['qualified'])

    def test_move_then_absence_uses_only_new_port_and_same_hardware(self):
        first = self.u.select_current(self.ctx, {'known_devs':[]})
        moved = copy.deepcopy(self.profile)
        for key in ('port','canonical','device','device_real','firmware'):
            moved[key] = moved[key].replace('port2', 'port3').replace('9-2','9-3').replace('PORT2','PORT3')
        self.live.return_value = moved
        second = self.u.select_current(self.ctx, first)
        self.assertNotEqual(second['known_binding']['port'], first['known_binding']['port'])
        self.ctx.device_number.side_effect = FileNotFoundError()
        self.u.configure(None)  # A new worker starts without a manually saved profile.
        absent = self.u.select_current(self.ctx, first)
        self.assertEqual(absent['known_binding'], second['known_binding'])
        self.assertEqual(self.u.PROFILE, moved)
        self.u.validate_saved_binding(self.ctx, absent)

    def test_hub_or_changed_serial_revokes_old_port_even_after_disappearance(self):
        for failure in ('hub', 'serial'):
            with self.subTest(failure=failure):
                self.live.side_effect = None; self.live.return_value = self.profile
                self.u.bind_current(self.ctx, '240:17')
                if failure == 'hub':
                    self.live.side_effect = self.w.Unsafe('intermediate USB hub')
                else:
                    self.live.return_value = self.profile | dict(disk_serial='UNRELATED')
                with self.assertRaises(self.w.Unsafe): self.u.bind_current(self.ctx, '240:17')
                self.assertIsNone(self.u.current_record(self.ctx)['profile'])
                with patch.object(self.ctx, 'device_number', side_effect=FileNotFoundError()), self.assertRaises(self.w.Unsafe):
                    self.u.select_current(self.ctx, {'known_devs':[]})

    def test_manual_reconnect_accepts_verified_unmounted_drive_without_saved_profile(self):
        ctx=self.ctx
        ctx.usb_context=lambda:ctx
        ctx.assert_internal_state=Mock();ctx.load_state=lambda _:{}
        ctx.read_rows=lambda:[]
        ctx.recovery_work=Mock(return_value=dict(main=True,dependent=True))
        with patch.object(ctx.manual_usb,'unmounted'), patch.object(ctx.manual_usb,'capabilities',return_value={}), patch.object(self.u,'load',return_value=None), patch.object(self.u,'port_identity'), patch.object(self.u,'cycle',return_value=dict(ready=True)) as cycle:
            self.assertIn('remains unmounted',self.w.controls.perform(ctx,'reconnect'))
            ctx.recovery_work.assert_not_called()
        cycle.assert_called_once()
        self.assertEqual(cycle.call_args.args[1]['known_binding']['port'],self.profile['canonical'])
        self.assertIsNone(ctx.SETTINGS['usb']['profile'])

    def test_reboot_or_corrupt_record_cannot_authorize_missing_port(self):
        self.u.bind_current(self.ctx, '240:17')
        self.ctx.device_number.side_effect = FileNotFoundError()
        self.ctx.boot_id = lambda: 'different-boot'
        with self.assertRaises(self.w.Unsafe): self.u.select_current(self.ctx, {})
        (self.ctx.STATE_DIR / 'usb-binding.json').write_text('[]')
        with self.assertRaises(ValueError): self.u.select_current(self.ctx, {})

    def test_connection_change_after_reservation_never_disables_old_port(self):
        req = self.u.select_current(self.ctx, dict(known_devs=[], incident='test', number=1))
        self.u.reserve(self.ctx, req)
        moved = copy.deepcopy(self.profile)
        for key in ('port','canonical','device','device_real','firmware'):
            moved[key] = moved[key].replace('port2','port3').replace('9-2','9-3').replace('PORT2','PORT3')
        self.live.return_value = moved
        with patch.object(self.u.os, 'write') as write, self.assertRaisesRegex(self.w.Unsafe, 'changed after reservation'):
            self.u.io_worker(self.ctx, dict(action='disable', incident='test'))
        write.assert_not_called()


class PassiveStandbyTests(unittest.TestCase):
    def test_unknown_active_idle_confirmed_standby_and_flash_without_power_queries(self):
        w = load('engine'); s = w.standby
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'queue').mkdir(); (root / 'queue/rotational').write_text('1')
            binding = dict(sys=directory, serial='synthetic', boot='test', devs=['240:1'])
            ctx = w.usb_context(root); ctx.clock_now = Mock(return_value=0);ctx.udev=lambda _:dict(ID_ATA_ROTATION_RATE_RPM='5400')
            with patch.object(s, 'identity', return_value=binding), patch.object(s, 'activity', return_value=([0]*8, 0)) as counters, \
                    patch.object(s, 'power_command', side_effect=AssertionError('No power probe')), \
                    patch.object(s.subprocess, 'run', side_effect=AssertionError('No commands')):
                self.assertEqual(s.status(ctx)['state'], 'unknown')
                ctx.clock_now.return_value = 10
                self.assertEqual(s.status(ctx)['state'], 'idle')
                counters.return_value = ([1]*8, 0); ctx.clock_now.return_value = 20
                self.assertEqual(s.status(ctx)['state'], 'active')
                s.save(ctx, binding, 'confirmed', sleeping=True, counters=[1]*8)
                self.assertEqual(s.status(ctx)['state'], 'standby')
                counters.return_value = ([2]*8, 0)
                self.assertFalse(s.status(ctx)['sleeping'])
                (root / 'queue/rotational').write_text('0')
                self.assertEqual(s.status(ctx)['state'], 'not-applicable')


class SettingsWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.m = Machine(); self.addCleanup(self.m.close); self.b = self.m.b
        self.session = self.m.broker.sessions.login('admin','synthetic')

    def post(self, action, data):
        return self.m.broker.dispatch(dict(drive='legacy',action=action, write=True, token=self.session['token'], csrf=self.session['csrf'], data=data))

    def test_smtp_edit_while_monitoring_preserves_blank_password_and_test_uses_saved(self):
        smtp = dict(host='smtp.example.test',port=587,security='starttls',username='test',password='DUMMY-TEST-SECRET',sender='test@example.test',recipient='test@example.test')
        self.m.active = True
        self.post('smtp', smtp)
        self.post('smtp', smtp | dict(password='', recipient='new@example.test'))
        self.assertEqual(self.b.n.load_config()['password'], smtp['password'])
        self.assertNotIn('password', self.b.smtp_public())
        self.assertTrue(self.m.active); self.assertEqual(self.m.calls, [])
        with patch.object(self.b.n, 'bounded_send', return_value=(True,'SMTP accepted')):
            self.assertTrue(self.post('test-email', {})['accepted'])

    def test_custom_location_reuses_transaction_and_mount_without_changing_other_entries(self):
        options = 'defaults,nofail,nodev,nosuid,x-systemd.device-timeout=10s'
        original = self.m.original + f'UUID={UUID} {DESKTOP} ext4 {options} 0 0\n'
        self.m.fstab.write_text(original)
        c = self.b.s.default(); c['disk'].update(uuid=UUID,mountpoint=DESKTOP,fstab_options=options)
        c['recovery']['mount'] = True; self.b.cli.save(self.m.config,c)
        self.m.current = ''
        plan = self.b.migration.plan(self.b.migration_context(), UUID, '/mnt/MyData')
        request = dict(uuid=UUID,mountpoint='/mnt/MyData',token=plan['token'],revision=self.b.s.digest(c),confirm=True)
        with patch.object(self.b, 'disk_operation', return_value=dict(ok=True,message='Mounted')) as mount:
            self.assertTrue(self.post('change-mount-location', request)['ok'])
            mount.assert_called_once_with(dict(action='mount',uuid=UUID))
        self.assertEqual(self.m.fstab.read_text(), original.replace(DESKTOP,'/mnt/MyData'))
        self.assertEqual(self.b.configuration()['disk']['mountpoint'], '/mnt/MyData')
        self.assertEqual((self.m.disk_data/'sentinel').read_bytes(), b'Existing filesystem contents\x00preserve me')

    def test_location_consent_binds_destination_and_mounted_disk_is_refused(self):
        options = 'defaults,nofail,nodev,nosuid,x-systemd.device-timeout=10s'
        self.m.fstab.write_text(f'UUID={UUID} {DESKTOP} ext4 {options} 0 0\n')
        c = self.b.s.default();c['disk'].update(uuid=UUID,mountpoint=DESKTOP,fstab_options=options)
        self.b.cli.save(self.m.config,c)
        plan = self.b.migration.plan(self.b.migration_context(),UUID,'/mnt/first')
        data = dict(uuid=UUID,mountpoint='/mnt/second',token=plan['token'],revision=self.b.s.digest(c),confirm=True)
        with self.assertRaisesRegex(ValueError,'Unmount safely'): self.post('change-mount-location',data)
        self.m.current = ''
        with self.assertRaisesRegex(ValueError,'changed'): self.post('change-mount-location',data)
        self.assertIsNone(self.b.migration.journal(self.b.migration_context()))

    def test_actual_mount_location_is_shown_even_outside_configured_folder(self):
        c=self.b.s.default();c['disk'].update(uuid=UUID,mountpoint=STABLE)
        self.b.cli.save(self.m.config,c)
        value=self.b.status()
        self.assertTrue(value['mounted']);self.assertEqual(value['mount_locations'],[DESKTOP])
        self.assertFalse(value['health']['healthy'])


class USBDiscoveryTests(unittest.TestCase):
    def test_direct_root_topology_is_derived_and_intermediate_hub_is_refused(self):
        w=load('engine');u=w.usb;w.configure(configuration(w));ctx=w.usb_context()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            controller=root/'sys/devices/pci0000:00/0000:00:14.0'
            hub=controller/'usb2';device=hub/'2-3';port=hub/'2-0:1.0/usb2-port3'
            part=device/'host0/target0/block/synthetic/synthetic1'
            part.mkdir(parents=True);port.mkdir(parents=True)
            ids={'vendor':'0xffff','device':'0xffff','subsystem_vendor':'0xffff','subsystem_device':'0xffff','class':'0x0c0330','revision':'0x00'}
            for key,value in ids.items():(controller/key).write_text(value)
            for base in (hub,device):
                (base/'idVendor').write_text('ffff');(base/'idProduct').write_text('ffff')
            (hub/'serial').write_text('0000:00:14.0')
            block=root/'sys/dev/block';block.mkdir(parents=True);(block/'240:17').symlink_to(part)
            bus=root/'sys/bus/usb/devices';bus.mkdir(parents=True);(bus/'usb2').symlink_to(hub);(bus/'2-0:1.0').symlink_to(port.parent)
            ctx.block_checks=Mock();ctx.udev=lambda _:dict(ID_BUS='usb',ID_SERIAL='SYNTHETIC-TEST-DISK')
            validate=ctx.settings.usb_profile
            def normalized(profile, **kwargs):
                clean={k:v.removeprefix(directory) if isinstance(v,str) else v for k,v in profile.items()}
                validate(clean,**kwargs)
                return profile
            with patch.object(u,'SYS_DEV_BLOCK',block), \
                    patch.object(u,'USB_DEVICES',bus),patch.object(ctx.settings,'usb_profile',side_effect=normalized), \
                    patch.object(u,'hub_power',return_value='individual') as power:
                profile=u.discover(ctx,'240:17')
                self.assertEqual(profile['canonical'],str(port));self.assertEqual(profile['controller_ids'],ids)
                self.assertEqual(profile['mode'],'software');self.assertFalse(profile['qualified'])
                power.return_value='ganged'
                with self.assertRaisesRegex(w.Unsafe,'shared power switching'):u.discover(ctx,'240:17')
                nested=device/'2-3.1';newpart=nested/'host1/block/synthetic/synthetic1';newpart.mkdir(parents=True)
                (nested/'idVendor').write_text('ffff');(nested/'idProduct').write_text('ffff')
                (block/'240:17').unlink();(block/'240:17').symlink_to(newpart)
                with self.assertRaisesRegex(w.Unsafe,'intermediate USB hub'):u.discover(ctx,'240:17')

    def test_hardware_power_descriptor_queries_only_root_hub_and_is_cached(self):
        u=load('usb')
        with tempfile.TemporaryDirectory() as directory:
            hub=Path(directory);(hub/'busnum').write_text('9');(hub/'devnum').write_text('1')
            with patch.object(u.subprocess,'run',return_value=SimpleNamespace(stdout='wHubCharacteristic 0x0009\n',returncode=0)) as command:
                self.assertEqual(u.hub_power(hub),'individual');self.assertEqual(u.hub_power(hub),'individual')
                self.assertEqual(command.call_count,1)
                self.assertEqual(command.call_args.args[0],['/usr/bin/lsusb','-v','-s','9:1'])
