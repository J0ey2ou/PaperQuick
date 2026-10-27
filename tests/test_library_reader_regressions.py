"""Hidden-only regressions for classification actions and editable attachments."""
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from library_core import Library, digest
from library_ui import LibraryWindow
from citation_ui import CitationView
from reader_ui import ReaderPage
from test_reader import text_pdf


class LibraryReaderRegressions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name);self.lib=Library(self.base/'store')
        self.source=self.base/'main.pdf';text_pdf(self.source)
        self.rid=self.lib.import_pdf(self.source)
        extra=self.base/'extra.pdf';extra.write_bytes(self.source.read_bytes()+b'\n% supplement\n')
        self.lib.add_attachment(self.rid,extra,label='Supplement')
        self.item=next(a for a in self.lib.get(self.rid)['attachments'] if a.get('label')=='Supplement')
        self.root=tk.Tk();self.root.withdraw()

    def tearDown(self):
        self.root.destroy();self.lib.close();self.temp.cleanup()

    def wait(self,predicate):
        deadline=time.monotonic()+12
        while not predicate() and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertTrue(predicate())

    def test_import_and_footer_buttons_stack_above_wrapping_rows(self):
        window=LibraryWindow(self.root,self.lib.root,embedded=True)
        try:
            window.win.place(x=0,y=0,width=1040,height=740)
            for width in (1040,700,1280,1040):
                window.win.place_configure(width=width);self.root.update_idletasks()
                for bar in (window.toolbar,window.detail_button.master):
                    stack=bar.winfo_children()
                    buttons=[child for child in stack if isinstance(child,(ttk.Button,ttk.Menubutton))]
                    self.assertTrue(buttons)
                    for button in buttons:
                        row=button.grid_info()['in']
                        self.assertLess(stack.index(row),stack.index(button),'row container covers its action button')
                        self.assertGreater(button.winfo_height(),20)
                self.assertLess(window.toolbar.winfo_y()+window.toolbar.winfo_height(),740)
            button=next(b for b in window.controls if b.cget('text')=='导入文档')
            with patch('library_ui.filedialog.askopenfilenames',return_value=()) as chooser:
                button.invoke();chooser.assert_called_once()
            self.assertEqual(self.root.state(),'withdrawn')
        finally:window.close()

    def test_wrong_seed_can_be_deleted_and_restored_without_original_file_loss(self):
        changed=Mock();view=CitationView(self.root,self.lib.root,on_collected=changed)
        try:
            before=digest(self.source)
            with patch('citation_ui.messagebox.askyesno',return_value=False):view.remove_seed()
            self.assertEqual(len(self.lib.records()),1)
            view.before_remove=Mock(return_value=False)
            with patch('citation_ui.messagebox.askyesno',return_value=True):view.remove_seed()
            self.assertEqual(len(self.lib.records()),1)
            view.before_remove.return_value=True
            with patch('citation_ui.messagebox.askyesno',return_value=True):view.remove_seed()
            self.assertFalse(self.lib.records());self.assertFalse(view.seed_rows)
            view.restore_removed();self.assertEqual(self.lib.get(self.rid)['id'],self.rid)
            self.assertEqual(digest(self.source),before);self.assertEqual(changed.call_count,2)
            view.items=[{'title':'Wrong result'},{'title':'Good result'}];view._render_results();view.remove_result()
            self.assertEqual([i['title'] for i in view.items],['Good result'])
            self.assertEqual(len(self.lib.records()),1)
        finally:view.close();view.frame.destroy()

    def test_attachment_has_full_context_editing_and_independent_annotations(self):
        reader=ReaderPage(self.root,self.lib.root,lambda _:None,lambda _:None)
        reader.frame.place(x=0,y=0,width=1200,height=780)
        try:
            reader.open(self.rid);self.wait(lambda:not reader.loading and reader.count==2)
            main_id=reader.attachment_id;main_page=reader.page;before=digest(self.source)
            reader.notes.insert('end','Main note.');reader.dirty=True;reader.save_notes()
            reader.compare_attachment(self.item)
            preview=reader.comparison;editor=preview.reader
            self.wait(lambda:not editor.loading and editor.count==2)
            labels={editor.reading_menu.entrycget(i,'label') for i in range(editor.reading_menu.index('end')+1) if editor.reading_menu.type(i)!='separator'}
            self.assertTrue({'在此处添加批注','高亮选中文字','关联已收集文献…','修改 Word 原文','插入引用到笔记（自动页码）'}<=labels)
            self.assertTrue(editor.canvas.bind('<Button-3>'))
            editor.last_selection={'attachment':self.item['id'],'page':0,'rect':[.1,.1,.3,.2],'quote':'Evidence'}
            editor.context_page=0;editor.highlight_selection()
            saved=self.lib.get(self.rid)
            self.assertTrue(any(a['attachment']==self.item['id'] and a['quote']=='Evidence' for a in saved['annotations']))
            self.assertFalse(any(a['attachment']==main_id for a in saved['annotations']))
            self.assertEqual((reader.page,reader.attachment_id),(main_page,main_id))
            editor.notes.insert('end','Attachment note.');editor.dirty=True;editor.save_notes()
            self.assertIn('Attachment note.',reader.notes.get('1.0','end'))
            reader.notes.insert('end','More main notes.');reader.dirty=True;editor.prepare_note_edit()
            self.assertIn('More main notes.',editor.notes.get('1.0','end'))
            editor.editor_dirty=True;self.assertFalse(reader.can_close());self.assertFalse(reader.hide_comparison())
            with self.assertRaises(ValueError):reader.open(self.rid)
            self.assertEqual(reader.attachment_id,main_id)
            editor.editor_dirty=False;reader.hide_comparison();self.assertIsNone(reader.comparison)
            for job in self.root.tk.splitlist(self.root.tk.call('after','info')):
                command=self.root.tk.splitlist(self.root.tk.call('after','info',job)[0])[0]
                self.assertTrue(self.root.tk.call('info','commands',command))
            self.assertFalse(reader.note_peers);self.assertEqual(digest(self.source),before)
            self.assertEqual(self.root.state(),'withdrawn')
        finally:
            reader.close();reader.frame.destroy()


if __name__=='__main__':unittest.main()
