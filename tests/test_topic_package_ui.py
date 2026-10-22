from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from library_core import Library
from library_ui import LibraryWindow
from topic_package_ui import TopicPackageWindow
import ui_theme


class HiddenWindow(ttk.Frame):
    """Exercise real geometry inside an unmapped root without a desktop window."""
    def title(self, *_): pass
    def minsize(self, *_): pass
    def transient(self, *_): pass
    def protocol(self, *_): pass
    def geometry(self, value):
        width, height = map(int, value.split('x'))
        self.place(x=0, y=0, width=width, height=height)


class PackageDialogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.lib = Library(self.base / 'store')
        self.project = self.lib.create_project('父课题')
        self.child = self.lib.create_project('子课题', self.project)
        self.one = self.lib.save({'title': '研究一'}, self.project)
        self.two = self.lib.save({'title': '研究二'}, self.child)
        self.empty = self.lib.save({'title': '未下载文献'}, self.project)
        for i, rid in enumerate((self.one, self.two)):
            source = self.base / f'{i}.txt'
            source.write_text(f'正文 {i}', 'utf-8')
            self.lib.add_attachment(rid, source, role='primary')
        extra = self.base / 'extra.csv'
        extra.write_bytes(b'1,2,3')
        self.lib.add_attachment(self.one, extra)
        self.root = tk.Tk()
        self.root.withdraw()
        ui_theme.install_theme(self.root)
        self.dialog = TopicPackageWindow(self.root, self.lib, self.project)

    def tearDown(self):
        if self.dialog.busy:
            self.dialog.cancel.set()
            self.wait_done()
        if not self.dialog.closed:
            self.dialog.close()
        self.root.destroy()
        self.lib.close()
        self.tmp.cleanup()

    def wait_done(self):
        deadline = time.monotonic() + 8
        while self.dialog.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.dialog.busy)

    def test_default_scope_all_selected_nested_documents_and_attachment_toggling(self):
        dialog = self.dialog
        self.assertFalse(dialog.win.winfo_ismapped())
        self.assertEqual(set(dialog.selection), {self.one, self.two, self.empty})
        self.assertIn('3 / 3 篇', dialog.summary.get())
        child = next(key for key, (paper, attachment) in dialog.rows.items() if paper.id == self.one and attachment and attachment.role != 'primary')
        paper_key = dialog.tree.parent(child)
        dialog.toggle(child)
        self.assertEqual(len(dialog.selection[self.one]), 1)
        self.assertTrue(dialog.tree.item(paper_key, 'text').startswith('◩'))
        dialog.toggle(paper_key)
        self.assertEqual(len(dialog.selection[self.one]), 2)
        dialog.toggle(paper_key)
        self.assertNotIn(self.one, dialog.selection)
        dialog.select_all(False)
        self.assertEqual(dialog.selection, {})
        self.assertTrue(dialog.start_button.instate(['disabled']))
        dialog.select_all(True)
        self.assertEqual(len(dialog.selection), 3)
        dialog.scope.current(dialog.project_ids.index(self.child))
        dialog.load_scope()
        self.assertEqual(set(dialog.selection), {self.two})

    def test_background_export_reports_completion_and_keeps_options_usable(self):
        dialog = self.dialog
        dialog.directory.set(str(self.base))
        dialog.name.set('导出课题')
        dialog.format.set('folder')
        dialog.start()
        self.assertTrue(dialog.busy)
        self.assertTrue(dialog.scope.instate(['disabled']))
        self.assertTrue(dialog.start_button.instate(['disabled']))
        self.wait_done()
        self.assertEqual(dialog.result['files'], 3)
        self.assertTrue((dialog.result['path'] / '文献目录.csv').is_file())
        self.assertEqual(float(dialog.progress['value']), 100)
        self.assertTrue(dialog.scope.instate(['readonly']))
        self.assertFalse(dialog.start_button.instate(['disabled']))
        self.assertIn('完成', dialog.status.get())

    def test_error_remains_in_dialog_and_does_not_claim_success(self):
        self.dialog.directory.set(str(self.lib.root))
        self.dialog.start()
        self.wait_done()
        self.assertIsNone(self.dialog.result)
        self.assertIn('打包未完成', self.dialog.status.get())
        self.assertIn('文献库之外', self.dialog.status.get())

    def test_library_export_ignores_filters_and_selection_state_has_no_stale_details(self):
        owner = LibraryWindow(self.root, self.lib.root, embedded=True)
        try:
            owner.current_project = self.project
            owner.search.set('不存在的词')
            owner.refresh_records()
            self.assertEqual(owner.tree.get_children(), ())
            owner.package_topic()
            self.assertEqual(set(owner.package_window.selection), {self.one, self.two, self.empty})
            owner.search.set('')
            owner.refresh_records()
            owner.tree.selection_set(self.one)
            owner.detail()
            self.assertIn('1', owner.selection_summary.get())
            self.assertTrue(all(not b.instate(['disabled']) for b in owner.selection_controls))
            owner.tree.selection_remove(self.one)
            owner.detail()
            self.assertIn('0', owner.selection_summary.get())
            self.assertIn('选择文献', owner.details.get())
            self.assertTrue(all(b.instate(['disabled']) for b in owner.selection_controls))
            self.assertFalse(owner.detail_card.winfo_manager())
            owner.toggle_details()
            self.assertEqual(owner.detail_card.winfo_manager(), 'pack')
        finally:
            owner.close()

    def test_save_controls_remain_visible_in_hidden_small_layouts_and_dpi(self):
        self.dialog.close()
        for scale in (1., 1.5, 2.):
            with self.subTest(scale=scale):
                self.root.tk.call('tk', 'scaling', scale)
                with patch('topic_package_ui.tk.Toplevel', side_effect=HiddenWindow), patch('topic_package_ui.style_dialog'):
                    self.dialog = TopicPackageWindow(self.root, self.lib, self.project)
                self.dialog.win.geometry('760x600')
                self.root.update_idletasks()
                self.assertFalse(self.dialog.win.winfo_ismapped())
                bottom = self.dialog.start_button.winfo_rooty() - self.dialog.win.winfo_rooty() + self.dialog.start_button.winfo_height()
                self.assertGreater(self.dialog.start_button.winfo_height(), 10)
                self.assertLessEqual(bottom, 600)
                self.assertGreater(self.dialog.tree.winfo_height(), 80, [(c.winfo_class(), c.winfo_reqheight(), c.winfo_height()) for c in self.dialog.tree.master.master.winfo_children()])
                self.dialog.close()

    def test_main_page_keeps_navigation_and_document_list_visible_in_hidden_layout(self):
        long_project = self.lib.create_project('包含很长中文名称与研究方向的课题标题以及子课题说明' * 2)
        for scale in (1., 1.5, 2.):
            with self.subTest(scale=scale):
                self.root.tk.call('tk', 'scaling', scale)
                owner = LibraryWindow(self.root, self.lib.root, embedded=True)
                try:
                    owner.win.place(x=0, y=0, width=1120, height=800)
                    owner.current_project = long_project
                    owner.refresh_records()
                    self.root.update_idletasks()
                    self.assertFalse(owner.win.winfo_ismapped())
                    self.assertGreater(owner.projects.winfo_height(), 80)
                    self.assertGreater(owner.tree.winfo_height(), 100)
                    self.assertLessEqual(owner.package_button.winfo_x() + owner.package_button.winfo_width(), owner.package_button.master.winfo_width())
                    self.assertLessEqual(owner.status_label.winfo_y() + owner.status_label.winfo_height(), owner.status_label.master.winfo_height())
                finally:
                    owner.close()

    def test_application_exit_waits_for_running_package(self):
        from app import App
        app = App.__new__(App)
        app.root = Mock()
        app.flush_settings = Mock()
        app.library_window = Mock(busy=False, word_citations=None, attachment_window=None, conversion_window=None, package_window=self.dialog)
        self.dialog.busy = True
        try:
            App.close(app)
            app.root.destroy.assert_not_called()
            self.assertFalse(self.dialog.closed)
        finally:
            self.dialog.busy = False
