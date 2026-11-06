# SPDX-License-Identifier: MIT
"""Cross-drive legacy edits cannot add an app owned by an active incident."""
import unittest
from unittest.mock import patch
import test_ui30_controls as previous
import test_ui28_apps as fixtures


class NewSelections(unittest.TestCase):
    setUp=fixtures.AppSettings.setUp

    def test_legacy_editor_cannot_add_affected_identity_to_previously_unselected_drive(self):
        child=self.f.second.b;before=self.f.second.config.read_bytes()
        self.f.second.patch(child,'container_rows',lambda *_:[dict(id=fixtures.IDENTITY,name='folder-app',binds=[])])
        previous.incident(self.f.main,ids=[fixtures.IDENTITY])
        with self.assertRaisesRegex(ValueError,previous.MESSAGE):
            child.application_settings(dict(revision=child.s.digest(child.configuration()),containers=[dict(id=fixtures.IDENTITY)]))
        self.assertEqual(before,self.f.second.config.read_bytes());self.assertEqual(self.docker.updates,[])

    def test_setup_wizard_cannot_bypass_with_a_new_identity_selection(self):
        child=self.f.second.b;before=self.f.second.config.read_bytes()
        previous.incident(self.f.main,ids=[fixtures.IDENTITY])
        # Refuse before the wizard can perform any configuration/storage action.
        with patch.object(child,'_save_configuration') as save:
            with self.assertRaisesRegex(ValueError,previous.MESSAGE):
                child.save_configuration(dict(containers=[dict(id=fixtures.IDENTITY)]))
            save.assert_not_called()
        self.assertEqual(before,self.f.second.config.read_bytes())

    def test_incident_starting_during_discovery_is_rechecked_before_write(self):
        child=self.f.second.b;before=self.f.second.config.read_bytes()
        def discover(*_):
            previous.incident(self.f.main,ids=[fixtures.IDENTITY])
            return [dict(id=fixtures.IDENTITY,name='folder-app',binds=[])]
        self.f.second.patch(child,'container_rows',discover)
        with self.assertRaisesRegex(ValueError,previous.MESSAGE):
            child.application_settings(dict(revision=child.s.digest(child.configuration()),containers=[dict(id=fixtures.IDENTITY)]))
        self.assertEqual(before,self.f.second.config.read_bytes());self.assertEqual(self.docker.updates,[])

    def test_unrelated_identity_can_still_be_added(self):
        child=self.f.second.b;identity='f'*64
        self.f.second.patch(child,'container_rows',lambda *_:[dict(id=identity,name='unrelated',binds=[])])
        previous.incident(self.f.main,ids=[fixtures.IDENTITY])
        child.application_settings(dict(revision=child.s.digest(child.configuration()),containers=[dict(id=identity)]))
        self.assertEqual(child.configuration()['docker']['containers'][0]['container_id'],identity)
        self.assertEqual(self.docker.updates,[])


if __name__=='__main__':unittest.main()
