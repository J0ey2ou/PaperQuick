"""Recent reading persistence and navigation, using only withdrawn windows."""
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from library_core import Library
from reader_ui import ReaderPage
import ui_theme


class RecentReadingTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / 'build' / 'recent-reading-tests'
        test_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=test_root)
        self.directory = Path(self.tmp.name) / 'store'
        self.lib = Library(self.directory)

    def tearDown(self):
        self.lib.close()
        self.tmp.cleanup()

    def test_persisted_unique_history_uses_read_time_and_excludes_unread(self):
        self.assertEqual(self.lib.recent_read(), [])
        first = self.lib.save({'title': 'Earlier', 'last_read': 100})
        second = self.lib.save({'title': 'Later', 'last_read': 200})
        self.lib.save({'title': 'Unread'})
        self.lib.save({'notes': 'Editing is not reading'}, rid=first)
        self.assertEqual([r['id'] for r in self.lib.recent_read()], [second, first])
        self.lib.save({'last_read': 300}, rid=first)
        self.lib.close()
        self.lib = Library(self.directory)
        self.assertEqual([r['id'] for r in self.lib.recent_read()], [first, second])
        self.assertEqual(len(self.lib.recent_read(1)), 1)
        with self.lib.db:
            self.lib.db.execute('DELETE FROM papers WHERE id=?', (first,))
        self.assertEqual([r['id'] for r in self.lib.recent_read()], [second])

    def test_hidden_reader_lists_history_and_click_opens_document(self):
        source = Path(self.tmp.name) / 'fixture.txt'
        source.write_text('Recent reading navigation fixture.', encoding='utf-8')
        rid = self.lib.import_document(source, self.lib.projects()[0]['id'])
        self.lib.save({'last_read': 100}, rid=rid)
        missing = self.lib.save({'title': 'Missing document', 'last_read': 50})
        root = tk.Tk()
        root.withdraw()
        with patch('ui_theme.window_chrome'):
            try:
                ui_theme.install_theme(root)
                reader = ReaderPage(root, self.directory, lambda _: None, lambda _: None)
                reader.toggle_recent_reading()
                self.assertEqual(reader.recent_tree.get_children(), (rid, missing))
                # A single row click follows the same open path as other reader routes.
                with patch.object(reader.recent_tree, 'identify_row', return_value=rid):
                    reader.open_recent_reading(SimpleNamespace(y=12))
                self.assertEqual(reader.rid, rid)
                self.assertEqual(reader.recent_panel.winfo_manager(), '')
                deadline = time.monotonic() + 5
                while reader.loading and time.monotonic() < deadline:
                    reader.poll()
                    time.sleep(.01)
                self.assertFalse(reader.loading)
                self.assertIn('Recent reading navigation fixture.', reader.text_view.get('1.0', 'end'))
                self.assertGreater(self.lib.get(rid)['last_read'], 100)
                reader.toggle_recent_reading()
                reader.recent_tree.selection_set(missing)
                reader.open_recent_reading()
                self.assertIn('无法打开', reader.status.get())
                self.assertEqual(reader.recent_panel.winfo_manager(), 'pack')
                self.assertEqual(reader.rid, rid)
                reader.close()
            finally:
                root.destroy()


if __name__ == '__main__':
    unittest.main()
