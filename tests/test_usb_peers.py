# SPDX-License-Identifier: MIT
"""Read-only USB2/USB3 peer topology assessment; no real sysfs is accessed."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gui_fixture import load


class USBPeerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.u = load('usb')
        self.controller = self.root / '0000:00:14.0'
        self.hs = self.port(self.controller, 2, 3, '480')
        self.ss = self.port(self.controller, 3, 7, '10000')
        (self.hs / 'peer').symlink_to(self.ss); (self.ss / 'peer').symlink_to(self.hs)

    def port(self, controller, bus, number, speed):
        root = controller / ('usb' + str(bus)); root.mkdir(parents=True, exist_ok=True)
        (root / 'speed').write_text(speed)
        p = root / f'{bus}-0:1.0' / f'usb{bus}-port{number}'; p.mkdir(parents=True)
        (p / 'disable').write_text('0\n')
        return p

    def test_valid_peer_is_not_claimed_to_prove_impossible_isolation(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(self.u.os, 'write', side_effect=AssertionError('No port writes allowed')):
            result = self.u.peer_diagnostic(self.ss)
        self.assertEqual(result['kind'], 'paired-software')
        self.assertTrue(result['supported']); self.assertTrue(result['paired'])
        self.assertIn('companion is empty', result['message'])
        self.assertIn('Electrical power cycling is not verified', result['message'])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_no_peer_keeps_existing_single_port_path(self):
        (self.hs / 'peer').unlink()
        self.assertIsNone(self.u.peer_diagnostic(self.hs))

    def test_dangling_peer_is_unknown_not_a_hardware_impossibility_claim(self):
        (self.ss / 'peer').unlink(); (self.ss / 'peer').symlink_to(self.root / 'absent')
        result = self.u.peer_diagnostic(self.ss)
        self.assertFalse(result['paired']); self.assertIn('unreadable/dangling', result['message'])

    def test_nonreciprocal_pair_is_rejected(self):
        (self.hs / 'peer').unlink(); (self.hs / 'peer').symlink_to(self.hs)
        self.assertIn('not reciprocal', self.u.peer_diagnostic(self.ss)['message'])

    def test_different_controller_pair_is_rejected(self):
        other = self.port(self.root / '0000:00:15.0', 4, 1, '480')
        (self.ss / 'peer').unlink(); (self.ss / 'peer').symlink_to(other); (other / 'peer').symlink_to(self.ss)
        self.assertIn('same PCI controller', self.u.peer_diagnostic(self.ss)['message'])

    def test_shared_hub_port_is_rejected(self):
        child = self.controller / 'usb2' / '2-1' / '2-1:1.0' / '2-1-port1'; child.mkdir(parents=True)
        (self.ss / 'peer').unlink(); (self.ss / 'peer').symlink_to(child); (child / 'peer').symlink_to(self.ss)
        self.assertIn('shared hubs', self.u.peer_diagnostic(self.ss)['message'])

    def test_missing_control_and_wrong_speed_fail_closed(self):
        (self.hs / 'disable').unlink()
        self.assertIn('one is missing', self.u.peer_diagnostic(self.ss)['message'])
        (self.hs / 'disable').write_text('0')
        (self.hs.parent.parent / 'speed').write_text('10000')
        self.assertIn('not a verified USB2/USB3', self.u.peer_diagnostic(self.ss)['message'])

    def test_attached_peer_device_is_not_assumed_to_be_the_disk(self):
        device = self.root / 'unknown-device'; device.mkdir()
        (self.hs / 'device').symlink_to(device)
        self.assertIn('must not be disconnected', self.u.peer_diagnostic(self.ss)['message'])

    def test_runtime_allows_empty_peer_but_rejects_occupied_peer_and_cleanup_enables(self):
        from types import SimpleNamespace
        class Unsafe(Exception): pass
        firmware = self.root / 'firmware'; firmware.mkdir(); (self.ss / 'firmware_node').symlink_to(firmware)
        with patch.object(self.u, 'controller_identity'), patch.object(self.u, 'PORT', self.ss), \
                patch.object(self.u, 'CANONICAL', str(self.ss)), patch.object(self.u, 'FIRMWARE', str(firmware)), \
                patch.object(self.u.os, 'write') as write:
            self.u.port_identity(SimpleNamespace(Unsafe=Unsafe))
            (self.hs / 'device').symlink_to(self.root)
            with self.assertRaisesRegex(Unsafe, 'must not be disconnected'):
                self.u.port_identity(SimpleNamespace(Unsafe=Unsafe))
            self.u.port_identity(SimpleNamespace(Unsafe=Unsafe), enabling=True)
            write.assert_not_called()


if __name__ == '__main__': unittest.main()
