from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock,patch
from library_core import Library
from display_renaming import prepare_display_names,apply_display_names
from display_name_ui import DisplayNameDialog
import ui_theme


class DisplayNameDialogTests(unittest.TestCase):
    def test_footer_stays_visible_in_a_small_hidden_layout_at_multiple_dpi_scales(self):
        # A placed Frame exercises real Tk geometry without mapping a desktop window.
        class HiddenWindow(ttk.Frame):
            def title(self,*_):pass
            def geometry(self,value):
                width,height=map(int,value.split('x'));self.place(x=0,y=0,width=width,height=height)
            def minsize(self,*_):pass
            def protocol(self,*_):pass
        base=Path(__file__).resolve().parents[1]/'build'/'display-dialog-tests';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            lib=Library(Path(tmp)/'store');rid=lib.save({'title':'A full recognized article title'})
            try:
                for scaling in (1.,1.5,2.):
                    with self.subTest(scaling=scaling):
                        root=tk.Tk();root.withdraw();root.tk.call('tk','scaling',scaling)
                        with patch('ui_theme.window_chrome'):
                            ui_theme.install_theme(root)
                            with patch('display_name_ui.tk.Toplevel',side_effect=HiddenWindow),patch('display_name_ui.style_dialog'):
                                dialog=DisplayNameDialog(root,lib,prepare_display_names(lib,[rid]),Mock())
                        try:
                            dialog.win.geometry('820x480');root.update_idletasks()
                            bottom=dialog.footer.winfo_y()+dialog.footer.winfo_height()
                            self.assertEqual(bottom,480)
                            save_y=dialog.save_button.winfo_rooty()-dialog.win.winfo_rooty()
                            self.assertGreater(dialog.save_button.winfo_height(),10)
                            self.assertGreaterEqual(save_y,0)
                            self.assertLessEqual(save_y+dialog.save_button.winfo_height(),480)
                            self.assertGreater(dialog.viewport.winfo_height(),100)
                            self.assertGreater(dialog.panel.winfo_reqheight(),dialog.viewport.winfo_height())
                            dialog.from_rule()
                            self.assertIn('相同',dialog.feedback.get())
                            self.assertIn('确认保存',dialog.feedback.get())
                        finally:
                            dialog.close()
                            for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
                            root.destroy()
            finally:lib.close()

    def test_save_button_applies_the_recognized_name_to_the_library(self):
        base=Path(__file__).resolve().parents[1]/'build'/'display-dialog-tests';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            lib=Library(Path(tmp)/'store');rid=lib.save({'title':'Old title'})
            plans=prepare_display_names(lib,[rid]);plans[0]['fields']['title']='Recognized full article title'
            result=[];root=tk.Tk();root.withdraw()
            with patch('ui_theme.window_chrome'):
                ui_theme.install_theme(root)
                dialog=DisplayNameDialog(root,lib,plans,lambda confirmed:result.append(apply_display_names(lib,confirmed)));dialog.win.withdraw()
                try:
                    dialog.from_title()
                    self.assertIn('预览已更新',dialog.feedback.get())
                    self.assertNotIn('display_name',lib.get(rid))
                    dialog.save_button.invoke()
                    self.assertEqual(result,[{'count':1,'errors':[]}])
                    self.assertEqual(lib.get(rid)['display_name'],'Recognized full article title')
                    self.assertEqual(lib.get(rid)['title'],'Old title')
                finally:
                    dialog.close()
                    for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
                    root.destroy();lib.close()

    def test_hidden_dialog_keeps_per_paper_edits_and_saves_only_when_confirmed(self):
        base=Path(__file__).resolve().parents[1]/'build'/'display-dialog-tests';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            lib=Library(Path(tmp)/'store');one=lib.save({'title':'First original'});two=lib.save({'title':'Second original'})
            root=tk.Tk();root.withdraw()
            with patch('ui_theme.window_chrome'):
                ui_theme.install_theme(root)
                callback=Mock();dialog=DisplayNameDialog(root,lib,prepare_display_names(lib,[one,two]),callback);dialog.win.withdraw()
                try:
                    dialog.name.set('Edited first / name?');dialog.vars['authors'].set('Alice Smith')
                    dialog.tree.selection_set(two);dialog.select();dialog.name.set('Edited second')
                    dialog.tree.selection_set(one);dialog.select()
                    self.assertEqual(dialog.name.get(),'Edited first / name?')
                    self.assertEqual(dialog.vars['authors'].get(),'Alice Smith')
                    self.assertEqual(lib.get(one)['title'],'First original');callback.assert_not_called()
                    dialog.accept()
                    result=callback.call_args.args[0]
                    self.assertEqual([p['display_name'] for p in result],['Edited first / name?','Edited second'])
                    self.assertTrue(all(not p['sync_metadata'] for p in result))
                finally:
                    dialog.close()
                    for job in root.tk.splitlist(root.tk.call('after','info')):root.after_cancel(job)
                    root.destroy();lib.close()


if __name__=='__main__':unittest.main()
