# SPDX-License-Identifier: MIT
"""USB-SATA ATA-passthrough acceptance: isolated sysfs, no block operations."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import Mock, patch
from gui_fixture import load

u=load('usb')
w=load('engine')
p=load('web_prepare')
broker=load('web_broker')


class Topology(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='usw-ui6-sysfs-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.controller=self.root/'pci0000:00'/'0000:00:01.0'
        self.hub=self.controller/'usb3'
        self.port=self.hub/'3-2'
        self.disk=self.port/'host5'/'target5:0:0'/'5:0:0:0'/'block'/'sdc'
        self.disk.mkdir(parents=True)
        for parent in (self.hub,self.port):
            (parent/'idVendor').write_text('1234')
            (parent/'idProduct').write_text('5678')
        (self.disk/'dev').write_text('240:0')
        (self.disk/'size').write_text(str(976773168))
        (self.disk/'ro').write_text('0')
        (self.disk/'diskseq').write_text('42')
        (self.disk/'queue').mkdir()
        (self.disk/'queue'/'rotational').write_text('1')
        self.sysblock=self.root/'devblock'
        self.sysblock.mkdir()
        (self.sysblock/'240:0').symlink_to(self.disk,target_is_directory=True)
        self.props={'ID_BUS':'ata','ID_SERIAL':'EXAMPLE_SATA_DISK_SYNTH9876',
                    'ID_SERIAL_SHORT':'SYNTH9876', 'ID_WWN':'0x5000039000000001',
                    'ID_ATA':'1','ID_ATA_ROTATION_RATE_RPM':'7200'}

    def test_ata_passthrough_has_verified_usb_transport(self):
        self.assertEqual(u.physical_usb_device(self.disk), self.port)
        self.assertTrue(u.is_verified_usb_block(self.disk,self.props))
        self.assertEqual(broker.media_kind(self.props,'1'),'hdd')

    def test_missing_serial_or_fake_usb_metadata_cannot_authorize(self):
        self.assertFalse(u.is_verified_usb_block(self.disk,self.props|{'ID_SERIAL':''}))
        self.assertFalse(u.is_verified_usb_block(self.disk,self.props|{'ID_SERIAL':None}))
        self.assertFalse(u.is_verified_usb_block(self.root,self.props))
        self.assertFalse(u.is_verified_usb_block(self.root/'nonexistent',self.props))
        # Physically SATA: even spoofed ID_BUS=usb may not bypass sysfs.
        sata=self.root/'pci0000:00'/'0000:00:03.0'/'ata1'/'host1'/'block'/'sda'
        sata.mkdir(parents=True)
        self.assertFalse(u.is_verified_usb_block(sata,self.props|{'ID_BUS':'usb'}))

    def test_usb_hub_does_not_fake_a_direct_root_port(self):
        nested=self.port/'3-2.1'/'block'/'sdd'
        nested.mkdir(parents=True)
        (self.port/'3-2.1'/'idVendor').write_text('abcd')
        (self.port/'3-2.1'/'idProduct').write_text('ef12')
        self.assertEqual(u.physical_usb_device(nested),self.port/'3-2.1')
        self.assertFalse(bool(__import__('re').fullmatch(r'\d+-\d+',u.physical_usb_device(nested).name)))

    def context(self):
        details={'device':'/dev/disk/by-id/ata-EXAMPLE_SATA_DISK_SYNTH9876',
                 'model':'EXAMPLE SATA DISK','serial':'SYNTH9876','size':976773168*512,'reason':''}
        return (SimpleNamespace(w=SimpleNamespace(
            device_number=Mock(return_value='240:0'),udev=Mock(return_value=self.props),usb=u,boot_id=lambda:'test-boot')),
            details)

    def test_inventory_accepts_ata_byid_link_for_an_lsblk_usb_disk(self):
        # An unmounted NTFS USB HDD can be *reviewed* for destructive ext4
        # preparation. The listing itself never formats or reads its content.
        target=self.root/'host-device';target.touch()
        byid=self.root/'by-id-inventory';byid.mkdir()
        (byid/'ata-EXAMPLE_SATA_DISK_SYNTH9876').symlink_to(target)
        rows=[dict(type='disk',tran='usb',name=str(target),model='EXAMPLE SATA DISK',
                   serial='SYNTH9876',size=976773168*512,ro=False,mountpoints=[],
                   children=[dict(type='part',fstype='ntfs',mountpoints=[],children=[])])]
        b=SimpleNamespace(cli=SimpleNamespace(flatten=lambda rows: (item for row in rows for item in (row,*row.get('children',[])))))
        with patch.object(p,'BY_ID_DIR',byid),patch.object(p,'run',return_value=SimpleNamespace(stdout=__import__('json').dumps({'blockdevices':rows}))):
            result=p.inventory(b)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['device'],str(byid/'ata-EXAMPLE_SATA_DISK_SYNTH9876'))
        self.assertEqual(result[0]['serial'],'SYNTH9876')
        self.assertEqual(result[0]['reason'],'')

    def test_inventory_still_refuses_true_sata_transport(self):
        target=self.root/'sata-device';target.touch()
        byid=self.root/'by-id-inventory';byid.mkdir()
        (byid/'ata-EXAMPLE_SATA_DISK_SYNTH9876').symlink_to(target)
        rows=[dict(type='disk',tran='sata',name=str(target),model='EXAMPLE SATA DISK',
                   serial='SYNTH9876',size=976773168*512,ro=False,mountpoints=[],children=[])]
        b=SimpleNamespace(cli=SimpleNamespace(flatten=lambda rows: iter(rows)))
        with patch.object(p,'BY_ID_DIR',byid),patch.object(p,'run',return_value=SimpleNamespace(stdout=__import__('json').dumps({'blockdevices':rows}))):
            self.assertEqual(p.inventory(b),[])

    def test_usb_root_port_discovery_accepts_verified_ata_passthrough(self):
        bus=self.root/'bus-usb';bus.mkdir()
        (bus/'usb3').symlink_to(self.hub,target_is_directory=True)
        (bus/'3-2').symlink_to(self.port,target_is_directory=True)
        port=(bus/'3-0:1.0'/'usb3-port2');port.mkdir(parents=True)
        (port/'disable').write_text('0')
        (self.hub/'serial').write_text('SYNTH-ROOT-HUB')
        for key in ('vendor','device','subsystem_vendor','subsystem_device','class','revision'):
            (self.controller/key).write_text('0001')
        c=SimpleNamespace(DISK_UUID='11111111-1111-4111-8111-111111111111',
                          block_checks=Mock(),udev=Mock(return_value=self.props),
                          settings=SimpleNamespace(usb_profile=Mock()),Unsafe=RuntimeError)
        with patch.object(u,'USB_DEVICES',bus),patch.object(u,'SYS_DEV_BLOCK',self.sysblock),patch.object(u,'hub_power',return_value='individual'):
            binding=u.discover(c,'240:0')
        self.assertEqual(binding['disk_serial'],self.props['ID_SERIAL'])
        self.assertEqual(binding['device_real'],str(self.port))
        self.assertEqual(binding['mode'],'software')

    def test_prepare_accepts_verified_usb_transport_with_ata_disk_identity(self):
        b,row=self.context()
        with patch.object(p,'inventory',return_value=[row]),patch.object(p,'SYS_DEV_BLOCK',self.sysblock):
            resolved=p.binding(b,row['device'])
        self.assertEqual(resolved['dev'],'240:0')
        self.assertEqual(resolved['serial'],'SYNTH9876')
        self.assertEqual(resolved['sequence'],'42')
        self.assertEqual(resolved['device'],row['device'])

    def test_prepare_refuses_wrong_serial_duplicate_identity_or_sata_transport(self):
        b,row=self.context()
        with patch.object(p,'SYS_DEV_BLOCK',self.sysblock):
            with patch.object(p,'inventory',return_value=[row,row]):
                with self.assertRaisesRegex(ValueError,'ambiguous'):p.binding(b,row['device'])
            with patch.object(p,'inventory',return_value=[row]):
                b.w.udev.return_value=self.props|{'ID_SERIAL_SHORT':'WRONG'}
                with self.assertRaisesRegex(ValueError,'matching unique serial'):p.binding(b,row['device'])
                b.w.udev.return_value=self.props
                with patch.object(u,'is_verified_usb_block',return_value=False):
                    with self.assertRaisesRegex(ValueError,'verified USB'):p.binding(b,row['device'])

    def test_prepare_refuses_a_target_not_in_the_verified_inventory(self):
        b,row=self.context()
        with patch.object(p,'inventory',return_value=[row]):
            for path in ('/dev/sdc','/dev/disk/by-id/ata-Other',
                         '/dev/disk/by-id/wwn-Outside','/dev/disk/by-id/ata-TEST-part1'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    p.binding(b,path)

    def test_standby_only_accepts_ata_usb_when_real_attachment(self):
        ctx=SimpleNamespace(device_number=Mock(return_value='240:0'),
                            DISK_UUID='11111111-1111-4111-8111-111111111111',
                            block_checks=Mock(),udev=Mock(return_value=self.props),
                            read_rows=lambda:[], Unsafe=RuntimeError, boot_id=lambda:'test-boot',usb=u)
        # The hardware test is isolated. No real disk will be read or slept.
        with patch.object(w.standby,'SYS_DEV_BLOCK',self.sysblock),patch.object(w.standby,'BY_ID_DIR',self.root/'by-id'),patch.object(w.standby,'DEV_DIR',self.root/'dev'):
            byid=self.root/'by-id';byid.mkdir()
            dev=self.root/'dev';dev.mkdir();(dev/'sdc').touch()
            (byid/'ata-EXAMPLE_SATA_DISK_SYNTH9876').symlink_to(dev/'sdc')
            result=w.standby.identity(ctx)
            self.assertEqual(result['serial'],self.props['ID_SERIAL'])
            self.assertEqual(result['path'],str(byid/'ata-EXAMPLE_SATA_DISK_SYNTH9876'))
            self.assertEqual(w.standby.storage_kind(ctx,result),'mechanical')
        # A flash drive that falsely reports rotational=1 must not become HDD.
        ctx.udev.return_value={'ID_SERIAL':'USB_Flash_Drive_123','ID_BUS':'usb'}
        self.assertEqual(w.standby.storage_kind(ctx,result),'unknown')

    def test_non_usb_disk_cannot_run_standby(self):
        ctx=SimpleNamespace(device_number=Mock(return_value='240:0'),
                            DISK_UUID='11111111-1111-4111-8111-111111111111',
                            block_checks=Mock(),udev=Mock(return_value=self.props),
                            read_rows=lambda:[], Unsafe=RuntimeError, boot_id=lambda:'test-boot',usb=u)
        with patch.object(w.standby,'SYS_DEV_BLOCK',self.sysblock),patch.object(u,'is_verified_usb_block',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'real USB-attached'):
                w.standby.identity(ctx)


if __name__=='__main__':main()
