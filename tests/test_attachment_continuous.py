from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from pypdf import PdfWriter
from attachment_ui import AttachmentPreview
from library_core import Library, digest
import ui_theme


class AttachmentContinuousTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / 'build' / 'attachment-continuous-tests'
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.base = Path(self.tmp.name)
        self.lib = Library(self.base / 'store')
        source = self.base / 'multiple.pdf'
        writer = PdfWriter()
        for n in range(8): writer.add_blank_page(400 + n * 10, 600 + n * 10)
        writer.add_metadata({'/Title': 'Continuous attachment fixture'})
        with source.open('wb') as stream: writer.write(stream)
        self.rid = self.lib.import_pdf(source)
        self.item = self.lib.primary_attachment(self.rid)
        self.original = digest(source)
        self.root = tk.Tk(); self.root.withdraw()
        with patch('ui_theme.window_chrome'): ui_theme.install_theme(self.root)
        self.preview = AttachmentPreview(self.root, self.lib.root, lambda: None)

    def tearDown(self):
        if not self.preview.closed: self.preview.close()
        for job in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(job)
        self.root.destroy(); self.lib.close(); self.tmp.cleanup()

    def wait(self, predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.root.update()
            if predicate(): return
            time.sleep(.01)
        self.fail('Background attachment render timed out')

    def test_continuous_scroll_jump_zoom_and_paging_leave_paper_unchanged(self):
        before = self.lib.get(self.rid)
        self.preview.open(self.item)
        self.wait(lambda: not self.preview.loading and bool(self.preview.document_canvas.layout))
        self.assertTrue(self.preview.continuous.get())
        self.assertEqual(len(self.preview.document_canvas.layout), 8)
        self.assertLess(len(self.preview.document_canvas.photos), 8)
        self.preview.page_input.set('6'); self.preview.jump()
        self.assertEqual(self.preview.page, 5)
        self.preview.document_canvas.load_visible()
        self.wait(lambda: 5 in self.preview.document_canvas.cache)
        self.assertLess(len(self.preview.document_canvas.photos), 8)
        self.preview.continuous.set(False); self.preview.toggle_continuous()
        self.wait(lambda: not self.preview.loading and len(self.preview.document_canvas.layout) == 1)
        self.preview.change_page(1)
        self.wait(lambda: not self.preview.loading)
        self.assertEqual(self.preview.page, 6)
        self.preview.continuous.set(True); self.preview.toggle_continuous()
        self.wait(lambda: not self.preview.loading and len(self.preview.document_canvas.layout) == 8)
        self.preview.zoom(.85)
        self.wait(lambda: not self.preview.loading)
        self.assertEqual(len(self.preview.document_canvas.layout), 8)
        self.assertEqual(self.lib.get(self.rid), before)
        self.assertEqual(digest(self.base / 'multiple.pdf'), self.original)

    def test_switching_to_text_and_closing_discards_old_page_jobs(self):
        self.preview.open(self.item)
        self.wait(lambda: not self.preview.loading and bool(self.preview.path))
        text = self.base / 'note.txt'; text.write_text('A text attachment\n' * 80, 'utf-8')
        # A readable local text attachment uses the same independent pane.
        self.lib.add_attachment(self.rid, text)
        item = next(a for a in self.lib.get(self.rid)['attachments'] if a['kind'] == 'txt')
        self.preview.open(item)
        self.wait(lambda: not self.preview.loading and self.preview.text_display is not None)
        self.assertEqual(self.preview.document_canvas.layout, {})
        self.assertIn('A text attachment', self.preview.text_display.get('1.0', 'end'))
        self.preview.close()
        self.assertEqual(self.preview.document_canvas.pending, set())

    def test_word_attachment_uses_continuous_pages_after_background_conversion(self):
        from test_library_documents import docx
        source = self.base / 'article.docx'; docx(source)
        self.lib.add_attachment(self.rid, source)
        item = next(a for a in self.lib.get(self.rid)['attachments'] if a['kind'] == 'docx')
        pdf_path = self.lib.root / self.item['path']
        with patch('document_conversion.preview_pdf', return_value=pdf_path):
            self.preview.open(item)
            self.wait(lambda: not self.preview.loading and bool(self.preview.document_canvas.layout))
        self.assertEqual(self.preview.attachment_id, item['id'])
        self.assertEqual(len(self.preview.document_canvas.layout), 8)


if __name__ == '__main__': unittest.main()
