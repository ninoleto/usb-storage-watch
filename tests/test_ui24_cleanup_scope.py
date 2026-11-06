# SPDX-License-Identifier: MIT
"""Incident-scoped cleanup receipts; simulated mount/Docker boundaries only."""
import copy
import json
import unittest
import uuid

from test_ui20_lifecycle import Machine, MAIN, BOOT


class CleanupScopeTests(unittest.TestCase):
    def setUp(self):
        m = self.m = Machine(self)
        m.establish()
        m.disconnect()
        m.returned(90)
        self.old_tree = copy.deepcopy(m.rows)
        self.assertTrue(m.recover()['main'])
        self.path = m.directory/'retained-mount-cleanup.json'
        self.receipt = json.loads(self.path.read_text())
        self.old_incident = self.receipt['incident']
        self.request = dict(incident=str(uuid.uuid4()), boot=BOOT, allow_mount=True,
                            check_only=False, blocked=[])
        m.rows = copy.deepcopy(self.old_tree)
        m.loop, m.loop_backing, m.loop_attached = '7:8', '240:17', True
        m.events.clear()
        self.notes = []

    def save(self, receipt):
        self.path.write_text(json.dumps(receipt, indent=2)+'\n')
        return self.path.read_text()

    def cleanup(self, request=None):
        self.m.w.cleanup_failed_main(request or self.request, lambda *args: self.notes.append(args))

    def archives(self):
        return list((self.m.directory/'cleanup-history').glob('*.json'))

    def test_settled_older_incident_with_reused_ids_is_archived_without_carry(self):
        raw = self.path.read_text()
        self.assertTrue(self.m.w.valid_settled_cleanup_receipt(self.receipt))
        self.cleanup()
        self.assertEqual(self.m.events, ['unmount:image', 'unmount:disk'])
        current = json.loads(self.path.read_text())
        self.assertEqual(current['incident'], self.request['incident'])
        self.assertEqual(len(current['commands']), 2)
        self.assertEqual([path.read_text() for path in self.archives()], [raw])

    def test_ui23_boot_wide_history_absent_from_latest_capture_is_still_archivable(self):
        receipt = copy.deepcopy(self.receipt)
        historical = copy.deepcopy(receipt['commands'][-1])
        historical['mount'].update(id='991', parent='990', dev='8:49', source='/dev/sdd1')
        detach = dict(target='/dev/loop99', action='loop-detach', phase='returned', finished_at='earlier')
        receipt['commands'] = [historical, detach] + receipt['commands']
        self.assertNotIn(historical['mount'], receipt['capture']['tree'])
        self.assertNotIn('/dev/loop99', [item['name'] for item in receipt['capture']['loops']])
        raw = self.save(receipt)
        self.assertTrue(self.m.w.valid_settled_cleanup_receipt(receipt))
        self.cleanup()
        self.assertEqual(len(json.loads(self.path.read_text())['commands']), 2)
        self.assertEqual([path.read_text() for path in self.archives()], [raw])

    def test_same_incident_completed_cleanup_cannot_repeat(self):
        raw = self.path.read_text()
        with self.assertRaisesRegex(self.m.w.Unsafe, 'already completed'):
            self.cleanup(self.request | dict(incident=self.old_incident))
        self.assertEqual(self.m.events, [])
        self.assertEqual(self.path.read_text(), raw)
        self.assertEqual(self.archives(), [])

    def test_same_incident_changed_boot_does_not_reuse_completed_commands(self):
        receipt = copy.deepcopy(self.receipt)
        receipt['capture']['boot'] = 'earlier-boot'
        raw = self.save(receipt)
        with self.assertRaisesRegex(self.m.w.Unsafe, 'boot or storage configuration changed'):
            self.cleanup(self.request | dict(incident=self.old_incident))
        self.assertEqual(self.m.events, [])
        self.assertEqual(self.path.read_text(), raw)
        self.assertEqual(self.archives(), [])

    def test_malformed_or_unknown_older_receipt_never_archives_or_allows_cleanup(self):
        variants = []
        for field, value in (('incident', None), ('version', True), ('phase', 'intent')):
            changed = copy.deepcopy(self.receipt); changed[field] = value; variants.append(changed)
        for field, value in (('boot', ''), ('uuid', 'bad-uuid'), ('target', '/'), ('loops', {})):
            changed = copy.deepcopy(self.receipt); changed['capture'][field] = value; variants.append(changed)
        changed = copy.deepcopy(self.receipt); changed['capture']['tree'][0]['id'] = 'bad'; variants.append(changed)
        changed = copy.deepcopy(self.receipt); changed['capture']['loops'][0]['back_inode'] = False; variants.append(changed)
        for changes in (dict(phase='intent'), dict(sent=False, removed=True), dict(attempt=3),
                        dict(target=MAIN+'/different'), dict(finished_at=None)):
            changed = copy.deepcopy(self.receipt); changed['commands'][-1].update(changes); variants.append(changed)
        for receipt in variants:
            with self.subTest(receipt=receipt):
                raw = self.save(receipt)
                with self.assertRaises(self.m.w.Unsafe):
                    self.cleanup()
                self.assertEqual(self.path.read_text(), raw)
                self.assertEqual(self.m.events, [])
                self.assertEqual(self.archives(), [])
        self.path.write_text('{ unreadable json')
        with self.assertRaisesRegex(self.m.w.Unsafe, 'unreadable'):
            self.cleanup()
        self.assertEqual(self.path.read_text(), '{ unreadable json')
        self.assertEqual(self.m.events, [])
        self.assertEqual(self.archives(), [])

    def test_ui23_completed_no_action_failure_gets_one_fresh_generation_and_keeps_usb_budget(self):
        m = self.m
        state = copy.deepcopy(m.monitor.state)
        old = state['incident']
        old.update(recovery_generation=23, phase='done', notified=True, usb_resets=1,
                   result=m.w.failed_result('A previously removed mount identity appeared again; cleanup stopped.'))
        old['attempts'][-1].update(status='failed', actions=[], reason=old['result']['reason'])
        old_id = old['id']
        m.monitor.commit(state)
        m.sample(105)
        fresh = m.monitor.state['incident']
        self.assertNotEqual(fresh['id'], old_id)
        self.assertEqual(fresh['recovery_generation'], 24)
        self.assertEqual(fresh['usb_resets'], 1)
        self.assertEqual(fresh['legacy_recovery_resume'], old_id)
        self.assertTrue((m.directory/'incidents'/(old_id+'.json')).exists())
        m.sample(120)
        self.assertEqual(m.monitor.state['incident']['id'], fresh['id'])


if __name__ == '__main__':
    unittest.main()
