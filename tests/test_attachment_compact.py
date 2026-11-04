"""Withdrawn attachment layout and editing checks; no Word/browser/desktop input."""
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from attachment_ui import AttachmentReader
from library_core import Library,digest
from reader_ui import ReaderPage
from test_reader import text_pdf
from test_library_documents import docx
import ui_theme


class CompactAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.lib=Library(self.base/'store');self.pdf=self.base/'primary.pdf';text_pdf(self.pdf)
        self.rid=self.lib.import_pdf(self.pdf)
        extra=self.base/'supplement.pdf';extra.write_bytes(self.pdf.read_bytes()+b'\n% supplement\n')
        self.lib.add_attachment(self.rid,extra,label='Very long attachment title '*8)
        word=self.base/'supplement.docx';docx(word,paragraphs=['Original Word text'])
        self.lib.add_attachment(self.rid,word,label='Editable supplement')
        self.items=self.lib.get(self.rid)['attachments']
        self.pdf_item=next(a for a in self.items if a.get('label','').startswith('Very long'))
        self.word_item=next(a for a in self.items if a.get('label')=='Editable supplement')
        self.root=tk.Tk();self.root.withdraw();ui_theme.install_theme(self.root)
        self.owner=ReaderPage(self.root,self.lib.root,lambda _:None,lambda _:None)
        self.owner.rid=self.rid
        self.pane=AttachmentReader(self.root,self.owner,lambda:None)
        self.pane.frame.place(x=0,y=0,width=390,height=640)
        self.pane.set_items(self.items,self.pdf_item['id']);self.root.update_idletasks()

    def tearDown(self):
        self.pane.reader.editor_dirty=False;self.pane.close();self.owner.close()
        self.root.destroy();self.lib.close();self.temp.cleanup()

    def wait(self,predicate):
        until=time.monotonic()+10
        while not predicate() and time.monotonic()<until:self.root.update();time.sleep(.01)
        self.assertTrue(predicate());self.root.update_idletasks()

    def test_compact_pdf_uses_height_and_fits_narrow_panes(self):
        r=self.pane.reader
        for width in (260,390,700):
            self.pane.frame.place_configure(width=width);self.root.update_idletasks()
            self.pane.open(self.pdf_item);self.wait(lambda:not r.loading and bool(r.document_canvas.layout))
            self.assertTrue(r.compact)
            self.assertFalse(r.header.winfo_manager());self.assertFalse(r.header.winfo_children())
            self.assertFalse(r.reading_actions_bar.winfo_manager())
            self.assertFalse(r.recent_panel.winfo_manager())
            self.assertFalse(r.notes_visible)
            top=r.frame.winfo_y()+r.body.winfo_y()
            self.assertLess(top,160,(width,top))
            self.assertGreater(r.body.winfo_height(),440,(width,r.body.winfo_height()))
            self.assertLessEqual(r.document_canvas.layout[0][2]+36,r.canvas.winfo_width()+2)
            self.assertEqual(len(r.splitter.panes()),1)
            self.assertLessEqual(self.pane.combo.winfo_x()+self.pane.combo.winfo_width(),self.pane.header.winfo_width())
            for item in r.toolbar.items:
                widget=item['widget']
                if widget.winfo_manager():self.assertLessEqual(widget.winfo_x()+widget.winfo_width(),r.toolbar.winfo_width())
        labels={item['label'] for item in r.toolbar.items}
        self.assertNotIn('附件比对',labels);self.assertNotIn('正文与附件',labels);self.assertNotIn('专注阅读',labels)
        r.toggle_comparison();r.compare_attachment(self.word_item);self.assertIsNone(r.comparison)
        r.toggle_focus();self.root.update_idletasks();self.assertFalse(r.header.winfo_manager())
        self.assertEqual(str(r.splitter.cget('orient')),'vertical')
        self.assertTrue(r.notes_visible)

    def test_cancelled_switch_and_edit_preview_keep_draft_notes_and_selection(self):
        r=self.pane.reader;source_digest=digest(self.pdf)
        self.pane.frame.place_configure(width=260);self.root.update_idletasks()
        with patch('document_conversion.preview_pdf',return_value=self.pdf),patch('reader_workflow_ui.word_content',return_value={'text':'Original Word text\r','comments':[]}):
            self.pane.open(self.word_item);self.wait(lambda:not r.loading)
            r.edit_document();self.wait(lambda:r.word_editing and not r.document_job)
            r.text_view.insert('1.0','Unsaved draft ');r.document_changed()
            r.notes.insert('end','Attachment notes kept.');r.dirty=True;r.save_notes()
            self.assertFalse(r.canvas.winfo_manager())
            self.assertFalse(r.vertical_scroll.winfo_manager());self.assertFalse(r.horizontal_scroll.winfo_manager())
            self.assertTrue(r.text_scroll.winfo_manager())
            self.assertLessEqual(r.document_edit_bar.winfo_height(),r.toolbar.winfo_height()+2)
            index=next(i for i,a in enumerate(self.pane.items) if a['id']==self.pdf_item['id'])
            self.pane.combo.current(index)
            with patch('reader_ui.messagebox.askyesno',return_value=False):self.pane.choose()
            self.assertEqual(self.pane.items[self.pane.combo.current()]['id'],self.word_item['id'])
            self.assertTrue(r.editor_dirty);self.assertIn('Unsaved draft',r.text_view.get('1.0','end'))
            with patch('reader_workflow_ui.messagebox.askyesno',return_value=False):r.show_paged_view()
            self.assertTrue(r.editor_dirty);self.assertTrue(r.word_editing)
            with patch('reader_workflow_ui.messagebox.askyesno',return_value=True):r.show_paged_view()
            self.wait(lambda:not r.loading and not r.word_editing)
            self.assertTrue(r.canvas.winfo_manager());self.assertFalse(r.text_panel.winfo_manager())
            self.assertFalse(r.notes_visible)
            self.pane.open(self.pdf_item);self.wait(lambda:not r.loading)
            self.assertEqual(r.attachment_id,self.pdf_item['id'])
            self.assertIn('Attachment notes kept.',r.notes.get('1.0','end'))
            self.assertIn('Attachment notes kept.',self.owner.notes.get('1.0','end'))
        self.assertEqual(digest(self.pdf),source_digest)
        self.assertEqual(self.root.state(),'withdrawn')

    def test_programmatic_insert_preserves_unsaved_notes_from_other_reader(self):
        from PIL import Image
        r=self.pane.reader
        self.pane.open(self.pdf_item);self.wait(lambda:not r.loading)
        for marker,insert in [('Parent before page.',r.insert_page),('Parent before image.',lambda:r.insert_note_image(Image.new('RGB',(10,10),'red'))),('Parent before citation.',r.insert_note_citation)]:
            self.owner.notes.insert('end',marker);self.owner.dirty=True
            insert();r.save_notes()
            self.assertIn(marker,self.lib.get(self.rid)['notes'])
            self.assertIn(marker,r.notes.get('1.0','end'))
        # Simulate another committed note writer while both views are clean.
        record=self.lib.get(self.rid);self.lib.save({'notes':record['notes']+'\nExternal AI note.'},rid=self.rid)
        self.owner.prepare_note_edit();self.owner.notes.insert('end','Later parent note.');self.owner.dirty=True;self.owner.save_notes()
        self.assertIn('External AI note.',self.lib.get(self.rid)['notes'])

    def test_paged_view_during_save_keeps_edit_state_and_draft(self):
        r=self.pane.reader
        with patch('document_conversion.preview_pdf',return_value=self.pdf),patch('reader_workflow_ui.word_content',return_value={'text':'Original Word text\r','comments':[]}):
            self.pane.open(self.word_item);self.wait(lambda:not r.loading)
            r.edit_document();self.wait(lambda:r.word_editing and not r.document_job)
            r.text_view.insert('1.0','Saving draft ');r.document_changed();r.document_job=True
            try:
                r.show_paged_view()
                self.assertTrue(r.word_editing);self.assertTrue(r.editor_dirty)
                self.assertIn('Saving draft ',r.text_view.get('1.0','end'))
                self.assertTrue(r.text_panel.winfo_manager());self.assertFalse(r.canvas.winfo_manager())
            finally:r.document_job=False;r.editor_dirty=False


if __name__=='__main__':unittest.main()
