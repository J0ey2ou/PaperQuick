"""Background-only coverage for theme previews and saved appearance choices."""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import app
from preferences import load_preferences, save_preferences
import ui_theme as theme


class SkinPaletteTests(unittest.TestCase):
    def test_new_skins_preview_immediately_and_survive_reopening(self):
        original_skin = theme.CURRENT_SKIN
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            save_preferences(folder / 'settings.json', {'future_option': 'keep'})
            with (patch('app.app_dir', return_value=folder),
                  patch('ui_theme.window_chrome'),
                  patch('desktop_runtime.startup_enabled', return_value=False),
                  patch('desktop_runtime.configure_startup') as startup,
                  patch.object(app.App, 'start_selection_helper') as helper,
                  patch('webbrowser.open') as browser):
                root = tk.Tk()
                root.withdraw()
                instance = app.App(root)
                try:
                    instance.settings()
                    for name in ('奶油暖砂', '雾松绿', '暮色玫瑰', '夜读黑'):
                        with self.subTest(skin=name):
                            instance.settings_vars['skin'].set(name)
                            self.assertEqual(instance.skin, name)
                            self.assertEqual(theme.CURRENT_SKIN, name)
                            self.assertEqual(instance.settings_skin_preview.cget('background'),
                                             theme.SKINS[name]['PANEL'])
                            self.assertEqual(instance.settings_skin_preview.cget('highlightbackground'),
                                             theme.SKINS[name]['LINE'])
                            self.assertEqual(instance.settings_skin_hint.get(), theme.SKIN_DESCRIPTIONS[name])
                            self.assertEqual(root.state(), 'withdrawn')
                    # Leaving settings flushes the debounce before the root is destroyed.
                    instance.show_page('query')
                    saved = load_preferences(folder / 'settings.json')
                    self.assertEqual(saved['skin'], '夜读黑')
                    self.assertEqual(saved['future_option'], 'keep')
                finally:
                    instance.close()

                root = tk.Tk()
                root.withdraw()
                reopened = app.App(root)
                try:
                    reopened.settings()
                    self.assertEqual(reopened.settings_vars['skin'].get(), '夜读黑')
                    self.assertEqual(reopened.settings_skin_preview.cget('background'),
                                     theme.SKINS['夜读黑']['PANEL'])
                    self.assertEqual(root.state(), 'withdrawn')
                    theme.apply_skin(root, original_skin)
                finally:
                    reopened.close()
                helper.assert_not_called()
                browser.assert_not_called()
                startup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
