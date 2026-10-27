"""Word editing UI and save pipeline, with the Word helper replaced in memory."""
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET

from library_core import Library,digest
from reader_ui import ReaderPage
from reading_documents import edit_word_copy
from test_library_documents import docx
from test_reader import text_pdf


class WordInlineEditingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.lib=Library(self.base/'store');self.source=self.base/'original.docx'
        docx(self.source,paragraphs=['Existing original words','Second paragraph'])
        self.rid=self.lib.import_document(self.source)
        self.root=tk.Tk();self.root.withdraw()
        self.reader=ReaderPage(self.root,self.lib.root,lambda _:None,lambda _:None)
        self.reader.frame.place(x=0,y=0,width=1100,height=760)

    def tearDown(self):
        self.reader.editor_dirty=False;self.reader.close();self.root.destroy();self.lib.close();self.temp.cleanup()

    def wait(self,predicate):
        deadline=time.monotonic()+12
        while not predicate() and time.monotonic()<deadline:self.root.update();time.sleep(.01)
        self.assertTrue(predicate())

    def content(self,path):
        with zipfile.ZipFile(path) as archive:
            xml=ET.fromstring(archive.read('word/document.xml'))
        w='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        return {'text':'\r'.join(''.join(t.text or '' for t in p.iter(w+'t')) for p in xml.iter(w+'p'))+'\r','comments':[]}

    def open_editable(self):
        self.reader.open(self.rid)
        self.wait(lambda:not self.reader.loading and self.reader.word_editing)

    def test_word_opens_existing_text_editable_and_saves_additions_and_deletions(self):
        original=digest(self.source)
        def save_copy(path,raw,edited,destination):
            self.assertEqual(raw,self.content(path)['text'])
            docx(destination,paragraphs=edited.splitlines())
        with patch('reading_documents.word_content',side_effect=self.content),patch('reader_workflow_ui.edit_word_copy',side_effect=save_copy) as edit,patch('document_conversion.preview_pdf') as preview:
            self.open_editable();view=self.reader.text_view
            self.assertEqual(str(view.cget('state')),'normal')
            self.assertIn('Existing original words',view.get('1.0','end'))
            self.assertTrue(self.reader.document_edit_bar.winfo_manager())
            view.delete('1.0','1.9');view.insert('1.0','Revised ')
            view.insert('2.end',' plus added text')
            # Saving immediately must see edits even before <<Modified>> runs.
            self.reader.save_document()
            self.wait(lambda:not self.reader.document_job and not self.reader.loading and self.reader.word_editing)
            edit.assert_called_once();preview.assert_not_called()
            self.assertIn('Revised original words',self.reader.text_view.get('1.0','end'))
            self.assertIn('Second paragraph plus added text',self.reader.text_view.get('1.0','end'))
            managed=self.lib.root/self.lib.primary_attachment(self.rid)['path']
            self.assertIn('Revised original words',self.content(managed)['text'])
            self.assertEqual(digest(self.source),original)
            self.assertEqual(len(list((self.lib.root/'versions').rglob('*.docx'))),1)
            self.assertFalse(self.reader.editor_dirty)
            self.assertEqual(self.root.state(),'withdrawn')

    def test_repeat_edit_button_preserves_changes_and_undo_redo_work(self):
        with patch('reading_documents.word_content',side_effect=self.content):
            self.open_editable();view=self.reader.text_view
            view.insert('1.0','Added ');view.edit_separator();self.reader.document_changed()
            self.reader.edit_document();self.assertTrue(view.get('1.0','end').startswith('Added '))
            self.reader.undo_document();self.assertFalse(view.get('1.0','end').startswith('Added '))
            self.reader.undo_document(True);self.assertTrue(view.get('1.0','end').startswith('Added '))
            self.assertFalse(self.reader.can_close())

    def test_word_attachment_is_editable_without_changing_main_pdf(self):
        pdf=self.base/'primary.pdf';text_pdf(pdf);rid=self.lib.import_pdf(pdf)
        self.lib.add_attachment(rid,self.source)
        item=next(a for a in self.lib.get(rid)['attachments'] if a['kind']=='docx')
        self.reader.open(rid);self.wait(lambda:not self.reader.loading)
        main=self.reader.attachment_id
        with patch('reading_documents.word_content',side_effect=self.content):
            self.reader.compare_attachment(item)
            self.wait(lambda:self.reader.comparison.word_editing and not self.reader.comparison.loading)
            self.assertIn('Existing original words',self.reader.comparison.text_view.get('1.0','end'))
            self.assertEqual(self.reader.attachment_id,main)

    def test_paged_preview_stays_paged_and_preserves_unsaved_edits_when_cancelled(self):
        pdf=self.base/'preview.pdf';text_pdf(pdf)
        with patch('reading_documents.word_content',side_effect=self.content):
            self.open_editable();self.reader.text_view.insert('1.0','Unsaved ');self.reader.document_changed()
            with patch('reader_workflow_ui.messagebox.askyesno',return_value=False):self.reader.show_paged_view()
            self.assertTrue(self.reader.word_editing);self.assertTrue(self.reader.editor_dirty)
            with patch('reader_workflow_ui.messagebox.askyesno',return_value=True),patch('document_conversion.preview_pdf',return_value=pdf):
                self.reader.show_paged_view();self.wait(lambda:not self.reader.loading)
            self.assertFalse(self.reader.word_editing);self.assertIsNotNone(self.reader.path)
            self.assertFalse(self.reader._logical_document)

    def test_edit_ranges_preserve_existing_text_and_account_for_unicode(self):
        with patch('document_conversion._call',return_value={}) as helper:
            edit_word_copy('a.docx','A😀 delete keep\r','A😀 keep added\n','b.docx')
        request=helper.call_args.args[0]
        text=request['original_text'].encode('utf-16-le')
        for change in sorted(request['changes'],key=lambda c:c['start'],reverse=True):
            text=text[:change['start']*2]+change['text'].encode('utf-16-le')+text[change['end']*2:]
        self.assertEqual(text.decode('utf-16-le'),'A😀 keep added\r')

    def test_legacy_doc_also_opens_existing_text_directly(self):
        source=self.base/'legacy.doc';source.write_bytes(bytes.fromhex('d0cf11e0a1b11ae1')+b'legacy document fixture')
        rid=self.lib.save({'title':'Legacy Word'})
        self.lib.add_attachment(rid,source,role='primary')
        with patch('reading_documents.word_content',return_value={'text':'Existing legacy Word text\r','comments':[]}):
            self.reader.open(rid);self.wait(lambda:not self.reader.loading)
        self.assertTrue(self.reader.word_editing)
        self.assertIn('Existing legacy Word text',self.reader.text_view.get('1.0','end'))

    def test_save_failure_keeps_user_draft_and_does_not_replace_word(self):
        with patch('reading_documents.word_content',side_effect=self.content),patch('reader_workflow_ui.edit_word_copy',side_effect=ValueError('Word save refused')),patch('reader_workflow_ui.messagebox.showerror') as error:
            self.open_editable();managed=self.lib.root/self.lib.primary_attachment(self.rid)['path'];before=digest(managed)
            self.reader.text_view.insert('1.0','Unsaved draft ');self.reader.save_document()
            self.wait(lambda:not self.reader.document_job)
            self.assertTrue(self.reader.editor_dirty);self.assertEqual(str(self.reader.text_view.cget('state')),'normal')
            self.assertIn('Unsaved draft ',self.reader.text_view.get('1.0','end'))
            self.assertEqual(digest(managed),before);error.assert_called_once()


if __name__=='__main__':unittest.main()
