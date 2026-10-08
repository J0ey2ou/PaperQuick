import json
from pathlib import Path
import tempfile
import unittest

from shortcuts import load_shortcut, parse_shortcut, save_shortcut
TEST_TEMP = Path(__file__).resolve().parents[1] / 'build'
TEST_TEMP.mkdir(exist_ok=True)


class ShortcutTests(unittest.TestCase):
    def test_canonical_and_native_modifiers(self):
        self.assertEqual(parse_shortcut('Shift + Ctrl + j'), ('Ctrl + Shift + J', 6, 0x4A))
        self.assertEqual(parse_shortcut('Alt + Ctrl + F24'), ('Ctrl + Alt + F24', 3, 0x87))
        self.assertEqual(parse_shortcut('Alt + Shift + 9'), ('Alt + Shift + 9', 5, 0x39))

    def test_typing_and_system_combinations_are_not_accepted(self):
        for value in ['J', 'Ctrl + J', 'Ctrl + Ctrl + J', 'Win + Alt + J', 'Ctrl + Alt + F25', 'Ctrl + Alt + Enter', 'Ctrl + Alt + F01']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_shortcut(value)

    def test_settings_survive_restart_without_changing_email(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            config = Path(directory) / 'settings.json'
            config.write_text('{"email":"example@example.org"}', 'utf-8')
            save_shortcut(directory, 'Alt + Ctrl + j')
            self.assertEqual(load_shortcut(directory), 'Ctrl + Alt + J')
            self.assertEqual(json.loads(config.read_text('utf-8'))['email'], 'example@example.org')
            self.assertFalse((Path(directory) / 'shortcut.json.tmp').exists())

    def test_corrupt_or_missing_config_uses_default(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            self.assertEqual(load_shortcut(directory), 'Ctrl + Alt + F')
            path = Path(directory) / 'shortcut.json'
            for data in ['not json', '{"shortcut":"Ctrl + J"}', '{"shortcut":null}', '{}']:
                path.write_text(data, 'utf-8')
                self.assertEqual(load_shortcut(directory), 'Ctrl + Alt + F')
