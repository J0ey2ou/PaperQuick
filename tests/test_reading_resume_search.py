"""Hidden reader restoration, explicit search anchors and evidence callbacks."""
from pathlib import Path
import tempfile
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from library_core import Library
from reading_resume import ReadingResumeStore
from reader_ui import ReaderPage
from search_ui import SearchWindow, location_label
from workspace_tasks import TaskManager
from test_fulltext_index import make_pdf
import ui_theme


class ReadingResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.lib = Library(self.base / 'store')
        self.root = tk.Tk();self.root.withdraw()
        ui_theme.install_theme(self.root)
        self.reader = None

    def tearDown(self):
        if self.reader:self.reader.close()
        self.lib.close();self.root.destroy();self.temp.cleanup()

    def build_reader(self):
        self.reader = ReaderPage(self.root, self.lib.root, lambda _: None, lambda _: None)
        self.reader.frame.place(x=0, y=0, width=1100, height=800)
        self.root.update_idletasks()
        return self.reader

    def open_now(self, reader, *args, **kwargs):
        # Rendering and restoration are tested with real PDFium and event data;
        # thread scheduling itself belongs to the task/runtime tests.
        with patch('reader_ui.threading.Thread', side_effect=lambda *, target, daemon: SimpleNamespace(start=target)):
            reader.open(*args, **kwargs)
            reader.poll()
        self.root.update_idletasks()

    def test_restores_last_attachment_page_scale_and_layout_but_explicit_anchor_wins(self):
        first, second = self.base / 'primary.pdf', self.base / 'supplement.pdf'
        make_pdf(first, ['Primary'] * 2);make_pdf(second, ['Supplement'] * 5)
        rid = self.lib.save({'title': 'Resume fixture'})
        self.lib.add_attachment(rid, first, role='primary');self.lib.add_attachment(rid, second)
        attachment = self.lib.get(rid)['attachments'][1]
        store = ReadingResumeStore(self.lib.root)
        store.save(rid, attachment['id'], page=3, fraction=.25, scale=1.8, continuous=True, notes_visible=False, split=.65)
        reader = self.build_reader()
        self.open_now(reader, rid)
        self.assertEqual(reader.attachment_id, attachment['id'])
        self.assertEqual(reader.page, 3)
        self.assertAlmostEqual(reader.scale, 1.8)
        self.assertFalse(reader.notes_visible)
        reader.save_reading_position(force=True)
        self.assertEqual(store.last()['attachment'], attachment['id'])
        self.assertEqual(store.last()['page'], 3)
        self.open_now(reader, rid, attachment_id=attachment['id'], anchor={'page': 1, 'fraction': 0})
        self.assertEqual(reader.page, 1)
        self.assertEqual(self.root.state(), 'withdrawn')

    def test_logical_search_does_not_invent_pdf_pages_and_evidence_keeps_locator(self):
        source = self.base / 'notes.txt'
        source.write_text('first paragraph\nfindneedle original evidence\nlast paragraph', encoding='utf-8')
        rid = self.lib.import_document(source)
        attachment = self.lib.primary_attachment(rid)
        reader = self.build_reader()
        result = dict(paper=rid, attachment=attachment['id'], locator_kind='paragraph', paragraph=1,
                      page=None, query='findneedle', snippet='findneedle original evidence')
        with patch('reader_ui.threading.Thread', side_effect=lambda *, target, daemon: SimpleNamespace(start=target)):
            reader.open_search_result(result);reader.poll()
        self.assertIsNone(reader.path)
        self.assertTrue(reader._logical_document)
        self.assertIn('第 2 段', reader.page_label.get())
        self.assertIn('非页码', location_label(result))
        reader.text_view.tag_add('sel', '2.0', '2.end')
        reader.on_evidence = Mock()
        reader.capture_evidence()
        data = reader.on_evidence.call_args.args[0]
        self.assertEqual(data['quote'], 'findneedle original evidence')
        self.assertEqual(data['paragraph'], 1)
        self.assertIsNone(data['page'])
        self.assertEqual(data['attachment'], attachment['id'])

    def test_deleted_attachment_does_not_restore_a_different_file(self):
        source = self.base / 'text.txt';source.write_text('source', encoding='utf-8')
        rid = self.lib.import_document(source);attachment = self.lib.primary_attachment(rid)
        store = ReadingResumeStore(self.lib.root)
        store.save(rid, attachment['id'], page=100, scale=float('nan'), fraction=10)
        saved = store.get(attachment['id'])
        self.assertEqual(saved['scale'], 1.2)
        self.assertEqual(saved['fraction'], 1)
        with self.lib.db:self.lib.db.execute('DELETE FROM attachments WHERE id=?', (attachment['id'],))
        self.assertIsNone(store.last())
        self.assertIsNone(store.for_paper(rid))

    def test_search_window_indexes_in_task_manager_and_opens_exact_logical_result(self):
        source = self.base / 'text.txt';source.write_text('first\nlocalneedle second', encoding='utf-8')
        rid = self.lib.import_document(source);attachment = self.lib.primary_attachment(rid)
        manager = TaskManager(self.lib.root)
        callback = Mock()
        window = SearchWindow(self.root, self.lib.root, rid=rid, attachment_id=attachment['id'],
                              manager=manager, on_location=callback, query='localneedle')
        try:
            self.root.update_idletasks()
            deadline = time.monotonic() + 5
            while not window.results and time.monotonic() < deadline:
                self.root.update();time.sleep(.01)
            self.assertEqual(len(window.results), 1)
            self.assertEqual(window.results[0]['paragraph'], 1)
            window.tree.selection_set('0');window.open_selected()
            callback.assert_called_once()
            self.assertIsNone(callback.call_args.args[0]['page'])
            self.assertEqual(callback.call_args.args[0]['attachment'], attachment['id'])
            self.assertTrue(any(task['kind'] == 'fulltext-index' and task['status'] == 'succeeded' for task in manager.list_tasks()))
            self.assertEqual(self.root.state(), 'withdrawn')
        finally:window.close();manager.close(wait=True)


if __name__ == '__main__':unittest.main()
