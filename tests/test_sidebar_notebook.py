"""Hidden sidebar geometry and lifecycle checks; no native browser or input."""
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import ui_theme
from sidebar_notebook import SidebarNotebook
from embedded_chat import EmbeddedChat


class SidebarNotebookTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw()
        with patch('ui_theme.window_chrome'):ui_theme.install_theme(self.root)

    def tearDown(self):
        for job in self.root.tk.splitlist(self.root.tk.call('after','info')):
            self.root.tk.call('after','cancel',job)
        self.root.destroy()

    def make_notebook(self, width=390):
        parent=ttk.Frame(self.root);parent.place(x=0,y=0,width=width,height=600)
        notebook=SidebarNotebook(parent);notebook.pack(fill='both',expand=True)
        for title in ('笔记编辑','高亮 / 批注','文档链接','AI 阅读','目录 / 标签','翻译','聊天网页'):
            notebook.add(ttk.Frame(notebook),text=title)
        self.root.update_idletasks()
        return parent,notebook

    def test_narrow_selector_preserves_every_page_and_selected_tab_on_resize(self):
        parent,book=self.make_notebook()
        tabs=book.tabs();book.select(tabs[-1]);self.root.update_idletasks()
        for width in (260,390,1100,390):
            parent.place_configure(width=width);self.root.update_idletasks()
            self.assertEqual(book.select(),tabs[-1])
            self.assertEqual(tuple(book.selector.cget('values')),tuple(book.tab(t,'text') for t in tabs))
            self.assertEqual(book.selector.get(),'聊天网页')
            compact=width<1100
            self.assertEqual(book.cget('style'),book.compact_style if compact else 'TNotebook')
            self.assertEqual(book.navigation.winfo_manager(),'pack' if compact else '')
            if compact:
                self.assertLessEqual(book.selector.winfo_x()+book.selector.winfo_width(),book.navigation.winfo_width())
        self.assertEqual(self.root.state(),'withdrawn')

    def test_hide_restore_and_programmatic_selection_update_narrow_navigation(self):
        _,book=self.make_notebook();last=book.tabs()[-1]
        book.select(last);book.hide(last);self.root.update_idletasks()
        self.assertNotIn('聊天网页',book.selector.cget('values'))
        book.add(last,text='聊天网页');self.root.update_idletasks()
        book.selector.current(len(book._visible_tabs)-1);book._choose();self.root.update_idletasks()
        self.assertEqual(book.select(),last)
        book.tab(last,text='当前对话');self.root.update_idletasks()
        self.assertEqual(book.selector.get(),'当前对话')
        book.tab(last,state='disabled');book.select(book.tabs()[0]);self.root.update_idletasks()
        book.selector.current(len(book._visible_tabs)-1);book._choose();self.root.update_idletasks()
        self.assertNotEqual(book.select(),last)

    def test_embedded_view_visibility_follows_tab_and_ancestor_without_navigation(self):
        _,book=self.make_notebook();panel=book.nametowidget(book.tabs()[3])
        reader=SimpleNamespace(notebook=book,rid='paper',chat_bridge=Mock())
        view=EmbeddedChat(SimpleNamespace(reader=reader,frame=panel))
        view.rid='paper';process=Mock();process.poll.return_value=None;view.process=process
        book.select(view.tab);self.root.update_idletasks()
        process.stdin.write.reset_mock();view._visible=None
        with patch.object(view.host,'winfo_viewable',return_value=True):
            view.sync_visibility();view.sync_visibility()
            self.assertEqual(process.stdin.write.call_count,1)
            self.assertIn('"visible": true',process.stdin.write.call_args.args[0])
            book.select(panel);view.sync_visibility()
            self.assertIn('"visible": false',process.stdin.write.call_args.args[0])
            book.select(view.tab);view.sync_visibility()
            self.assertIn('"visible": true',process.stdin.write.call_args.args[0])
            reader.rid='other-paper';view.sync_visibility()
            self.assertIn('"visible": false',process.stdin.write.call_args.args[0])
        reader.rid='paper'
        with patch.object(view.host,'winfo_viewable',return_value=False):
            view.sync_visibility(force=True)
            self.assertIn('"visible": false',process.stdin.write.call_args.args[0])
        self.assertTrue(all('host-visibility' in call.args[0] for call in process.stdin.write.call_args_list))
        view.close();self.assertEqual(self.root.state(),'withdrawn')

    def test_chat_toolbar_wraps_in_narrow_sidebar(self):
        _,book=self.make_notebook(260)
        view=EmbeddedChat(SimpleNamespace(reader=SimpleNamespace(notebook=book),frame=book.nametowidget(book.tabs()[0])))
        book.select(view.tab);self.root.update_idletasks()
        buttons=view.host.master.winfo_children()[0].winfo_children()[1]
        actions=[child for child in buttons.winfo_children() if isinstance(child,(ttk.Button,ttk.Menubutton))]
        self.assertEqual(len(actions),5)
        self.assertGreater(len({str(child.grid_info()['in']) for child in actions}),1)
        for child in actions:
            self.assertLessEqual(child.winfo_x()+child.winfo_width(),buttons.winfo_width())


if __name__=='__main__':unittest.main()
