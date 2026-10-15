from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch, Mock
from PIL import Image
import ui_theme
from icon_toolbar import IconToolbar, icon_image
from preferences import load_preferences,save_preferences
from library_core import Library
import app


class CompactReaderTests(unittest.TestCase):
    def test_toolbar_single_row_and_overflow_at_small_widths_and_dpi(self):
        root=tk.Tk();root.withdraw()
        try:
            with patch('ui_theme.window_chrome'):
                ui_theme.install_theme(root)
                for scaling in (1.,1.5,2.):
                    root.tk.call('tk','scaling',scaling)
                    bar=IconToolbar(root);calls=[]
                    for n in range(24):bar.add('notes',f'Tool {n}',lambda n=n:calls.append(n))
                    page=tk.StringVar(value='2');status=tk.StringVar(value='2 / 12 · 100%')
                    bar.add_page(page,lambda:None,status)
                    for width in (240,380,700,1100):
                        bar.place(x=0,y=0,width=width,height=40);root.update_idletasks();bar.arrange(width)
                        visible=[x for x in bar.items if x['widget'].winfo_manager()]
                        self.assertTrue(visible)
                        self.assertTrue(all(int(x['widget'].place_info()['y'])==3 for x in visible))
                        self.assertTrue(all(not x['widget'].cget('text') for x in visible))
                        self.assertEqual(len(visible)+len(bar.hidden),24)
                        if bar.hidden:
                            bar.hidden[-1]['command']();self.assertEqual(calls[-1],23)
                        self.assertLessEqual(bar.winfo_height(),40)
                    bar.items[0]['widget'].help.show()
                    self.assertIsNone(bar.items[0]['widget'].help.window)
                    for skin in ui_theme.SKINS:
                        ui_theme.apply_skin(root,skin);bar.refresh_icons()
                        self.assertEqual(bar._theme_key[0],skin)
                    bar.destroy()
        finally:root.destroy()

    def test_reader_and_attachment_keep_all_tools_in_one_row(self):
        from reader_ui import ReaderPage
        from attachment_ui import AttachmentPreview
        with tempfile.TemporaryDirectory() as tmp:
            root=tk.Tk();root.withdraw()
            with patch('ui_theme.window_chrome'):
                try:
                    ui_theme.install_theme(root)
                    reader=ReaderPage(root,Path(tmp)/'store',lambda _:None,lambda _:None)
                    preview=AttachmentPreview(root,Path(tmp)/'store',lambda:None)
                    labels={item['label'] for item in reader.toolbar.items}
                    self.assertTrue({'正文与附件','保存笔记','嵌入参考文献','连续阅读 / 单页阅读','截图到笔记'}<=labels)
                    self.assertEqual(len(reader.note_toolbar.items),8)
                    self.assertEqual(len(preview.toolbar.items),7)
                    root.update_idletasks()
                    self.assertLessEqual(reader.toolbar.winfo_reqheight(),40)
                    self.assertLessEqual(preview.toolbar.winfo_reqheight(),40)
                    preview.close();reader.close()
                finally:
                    for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
                    root.destroy()

    def test_settings_survive_exit_and_keep_existing_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);save_preferences(folder/'settings.json',{'future_option':'keep'})
            lib=Library(folder/'本地文献库');rid=lib.save({'title':'Existing paper','notes':'Existing notes'})
            lib.close()
            with patch('app.app_dir',return_value=folder),patch('ui_theme.window_chrome'),patch('desktop_runtime.startup_enabled',return_value=False),patch('desktop_runtime.configure_startup') as startup,patch.object(app.App,'start_selection_helper') as helper,patch('webbrowser.open') as browser:
                root=tk.Tk();root.withdraw();first=app.App(root);first.settings()
                first.settings_vars['skin'].set('极简浅色');first.settings_vars['marker_size'].set('28')
                first.settings_vars['continuous'].set(False);first.settings_vars['email'].set('reader@example.org')
                first.settings_vars['shortcut'].set('Ctrl + Alt + J')
                first.settings_template.delete('1.0','end');first.settings_template.insert('1.0','My research template')
                # Exit before the debounce callback: the close path must flush edits.
                first.close()
                root=tk.Tk();root.withdraw();second=app.App(root);second.settings()
                self.assertEqual(second.skin,'极简浅色')
                self.assertEqual(second.settings_vars['marker_size'].get(),'28')
                self.assertFalse(second.settings_vars['continuous'].get())
                self.assertEqual(second.settings_vars['shortcut'].get(),'Ctrl + Alt + J')
                self.assertEqual(second.settings_template.get('1.0','end-1c'),'My research template')
                self.assertEqual(second.preferences['future_option'],'keep')
                second.settings_vars['skin'].set('深空蓝');second.settings_vars['marker_size'].set('')
                second.show_page('query')
                self.assertEqual(load_preferences(folder/'settings.json')['skin'],'深空蓝')
                lib=Library(folder/'本地文献库')
                self.assertEqual(lib.setting('reader_marker_size'),28)
                self.assertEqual(lib.get(rid)['notes'],'Existing notes')
                # Leaving settings must not overwrite subsequent reader choices on exit.
                lib.set_setting('continuous_reading',True);lib.close();second.close()
                lib=Library(folder/'本地文献库');self.assertTrue(lib.setting('continuous_reading'));lib.close()
                helper.assert_not_called();browser.assert_not_called();startup.assert_not_called()

    def test_atomic_preferences_keep_previous_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json';save_preferences(path,{'skin':'深空蓝','other':7})
            with patch('preferences.os.replace',side_effect=OSError('busy')):
                with self.assertRaises(OSError):save_preferences(path,{'skin':'极简浅色'})
            self.assertEqual(load_preferences(path),{'skin':'深空蓝','other':7})
            self.assertEqual(list(path.parent.glob('*.tmp')),[])


if __name__=='__main__':unittest.main()
