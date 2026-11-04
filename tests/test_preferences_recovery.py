"""Settings corruption must not silently overwrite a user's library path."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from preferences import load_preferences,save_preferences


class PreferencesRecoveryTests(unittest.TestCase):
    def test_corrupt_settings_recover_library_path_and_preserve_damaged_content(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            save_preferences(path,{'library_directory':'custom/library','future_key':{'value':7},'skin':'A'})
            save_preferences(path,{'skin':'B'})
            path.write_bytes(b'{partial write')
            values=load_preferences(path)
            self.assertEqual(values['library_directory'],'custom/library')
            self.assertEqual(values['future_key'],{'value':7})
            self.assertTrue(values.warning)
            save_preferences(path,{'skin':'C'})
            self.assertEqual(load_preferences(path)['library_directory'],'custom/library')
            self.assertEqual(load_preferences(path)['skin'],'C')
            damaged=list(Path(folder).glob('settings.json.corrupt-*'))
            self.assertEqual(len(damaged),1);self.assertEqual(damaged[0].read_bytes(),b'{partial write')

    def test_unrecoverable_settings_are_never_replaced_with_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json';path.write_text('[]',encoding='utf-8')
            values=load_preferences(path)
            self.assertEqual(values,{});self.assertIn('没有有效备份',values.warning)
            with self.assertRaisesRegex(OSError,'未覆盖'):save_preferences(path,{'skin':'new'})
            self.assertEqual(path.read_text('utf-8'),'[]')

    def test_missing_settings_can_recover_the_first_successful_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            self.assertFalse(load_preferences(path).warning)
            save_preferences(path,{'library_directory':'custom/library'})
            path.unlink()
            self.assertEqual(load_preferences(path)['library_directory'],'custom/library')
            save_preferences(path,{'skin':'new'})
            self.assertEqual(json.loads(path.read_text('utf-8'))['library_directory'],'custom/library')

    def test_repair_failure_keeps_original_and_last_good_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json';save_preferences(path,{'library_directory':'custom/library'})
            path.write_bytes(b'broken')
            with patch('preferences.os.replace',side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError):save_preferences(path,{'skin':'new'})
            self.assertEqual(path.read_bytes(),b'broken')
            self.assertEqual(load_preferences(path)['library_directory'],'custom/library')


if __name__=='__main__':unittest.main()
