# SPDX-License-Identifier: MIT
"""UI7: bounded safety inspection, truthful USB outcomes, no real hardware."""
from unittest import mock
import test_usb_recovery as fixture


class ReconnectOutcomes(fixture.Temp):
    def child(self, done_at=None):
        child = mock.Mock(returncode=0)
        child.poll.side_effect = lambda: 0 if done_at is not None and self.clock.now >= done_at else None
        return child

    def run_child(self, child, sleep=None):
        with mock.patch.object(fixture.u.subprocess, 'Popen', return_value=child), \
                mock.patch.object(fixture.u.time, 'monotonic', side_effect=self.clock.read), \
                mock.patch.object(fixture.u.time, 'sleep', side_effect=sleep or self.clock.sleep):
            fixture.u.bounded_io(self.ctx, 'disable', self.request['incident'])

    def test_inspection_can_exceed_three_seconds_before_a_short_write(self):
        fixture.u.reserve(self.ctx, self.request)
        child = self.child(done_at=6)
        def sleep(seconds):
            self.clock.sleep(seconds)
            if self.clock.now >= 5 and not fixture.u.load(self.ctx).get('disable_write_started_at'):
                fixture.u.update(self.ctx, disable_write_started_at=self.ctx.timestamp(), io_stage='disable sysfs write')
        self.run_child(child, sleep)
        self.assertGreaterEqual(self.clock.now, 6)
        child.kill.assert_not_called()

    def test_incomplete_inspection_is_bounded_and_never_claims_a_disconnect(self):
        fixture.u.reserve(self.ctx, self.request)
        fixture.u.update(self.ctx, io_stage='final isolation checks before USB write: process 123 open handles')
        child = self.child()
        with self.assertRaisesRegex(fixture.w.Unsafe, 'No USB disconnect write was started'):
            self.run_child(child)
        child.kill.assert_called_once()
        self.assertGreaterEqual(self.clock.now, fixture.u.CHECK_TIMEOUT)
        self.assertLess(self.clock.now, fixture.u.CHECK_TIMEOUT + .1)
        self.assertNotIn('disable_write_started_at', fixture.u.load(self.ctx))

    def test_write_timeout_does_not_reset_with_progress_updates(self):
        fixture.u.reserve(self.ctx, self.request)
        child = self.child()
        def sleep(seconds):
            self.clock.sleep(seconds)
            if self.clock.now >= 14:
                fixture.u.update(self.ctx, disable_write_started_at=self.ctx.timestamp(), io_stage='disable sysfs write')
        with self.assertRaisesRegex(fixture.w.Unsafe, 'write completion is uncertain'):
            self.run_child(child, sleep)
        self.assertGreaterEqual(self.clock.now, 17)
        self.assertLess(self.clock.now, 17.2)
        child.kill.assert_called_once()

    def test_failure_before_write_reports_no_reconnect_and_still_verifies_enabled(self):
        original = self.fake_io
        def io(ctx, action, incident):
            if action == 'disable':
                raise fixture.w.Unsafe('Safety checks timed out. No USB disconnect write was started.')
            original(ctx, action, incident)
        with self.simulation(), mock.patch.object(fixture.u, 'bounded_io', side_effect=io):
            with self.assertRaisesRegex(fixture.w.Unsafe, 'USB reconnect was not performed') as error:
                fixture.u.cycle(self.ctx, self.request)
        self.assertEqual(self.actions, ['enable'])
        self.assertEqual(fixture.u.load(self.ctx)['phase'], 'enabled')
        self.assertNotIn('port re-enabled', str(error.exception).lower())

    def test_interrupt_after_write_never_claims_no_write(self):
        original = self.fake_io
        def io(ctx, action, incident):
            original(ctx, action, incident)
            if action == 'disable':
                fixture.u.update(ctx, disable_write_started_at=ctx.timestamp())
                raise KeyboardInterrupt()
        with self.simulation(), mock.patch.object(fixture.u, 'bounded_io', side_effect=io):
            with self.assertRaisesRegex(fixture.w.Unsafe, 'interrupted after a disconnect write started'):
                fixture.u.cycle(self.ctx, self.request)
        self.assertEqual(self.actions, ['disable', 'enable'])

    def test_success_never_certifies_electrical_power_cut(self):
        with self.simulation(0):
            result = fixture.u.cycle(self.ctx, self.request)
        self.assertTrue(result['ready'])
        self.assertFalse(result['electrical_power_cut_verified'])
        self.assertEqual(result['operation'], 'software_reconnect')
        self.assertIn('Electrical power removal is not verified', result['reason'])

