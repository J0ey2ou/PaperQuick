import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfWriter
from reader_navigation import pdf_outline, text_headings, translate

class NavigationTests(unittest.TestCase):
    def test_outline_cache_uses_file_revision_and_returns_independent_items(self):
        from reader_navigation import clear_outline_cache
        clear_outline_cache()
        revision=('fixture.pdf',1,2,3,4,5)
        with patch('reader_navigation.file_version',return_value=revision),patch('reader_navigation._read_pdf_outline',return_value=[{'title':'Methods','page':0,'level':0}]) as read:
            first=pdf_outline('fixture.pdf');first[0]['title']='Changed locally'
            self.assertEqual(pdf_outline('fixture.pdf')[0]['title'],'Methods');self.assertEqual(read.call_count,1)
        with patch('reader_navigation.file_version',return_value=revision[:-1]+(6,)),patch('reader_navigation._read_pdf_outline',return_value=[]) as read:
            self.assertEqual(pdf_outline('fixture.pdf'),[]);self.assertEqual(pdf_outline('fixture.pdf'),[]);self.assertEqual(read.call_count,1)
        clear_outline_cache()

    def test_outline_does_not_cache_a_file_changed_during_read(self):
        from reader_navigation import clear_outline_cache, _outline_cache
        clear_outline_cache();revision=('changing.pdf',1,2,3,4,5)
        with patch('reader_navigation.file_version',side_effect=[revision,revision[:-1]+(6,)]),patch('reader_navigation._read_pdf_outline',return_value=[]):
            with self.assertRaisesRegex(ValueError,'读取时已改变'):pdf_outline('changing.pdf')
        self.assertEqual(len(_outline_cache),0)

    def test_cancelled_outline_never_reads_or_returns_cached_data(self):
        from reader_navigation import clear_outline_cache
        from pdf_reader_core import DocumentReadCancelled
        clear_outline_cache()
        with patch('reader_navigation.file_version',return_value=('fixture.pdf',1,2,3,4,5)),patch('reader_navigation._read_pdf_outline',return_value=[]) as read:
            pdf_outline('fixture.pdf')
            with self.assertRaises(DocumentReadCancelled):pdf_outline('fixture.pdf',cancelled=lambda:True)
            self.assertEqual(read.call_count,1)
        clear_outline_cache()

    def test_pdf_outline_targets_and_nesting(self):
        writer=PdfWriter()
        writer.add_blank_page(width=200,height=200);writer.add_blank_page(width=200,height=200)
        parent=writer.add_outline_item('Introduction',0);writer.add_outline_item('Methods',1,parent=parent)
        stream=io.BytesIO();writer.write(stream);stream.seek(0)
        self.assertEqual(pdf_outline(stream),[{'title':'Introduction','page':0,'level':0},{'title':'Methods','page':1,'level':1}])
    def test_headings_and_offsets(self):
        text='preface\n1 Introduction\nbody\n第二章 方法\n';items=text_headings(text)
        self.assertEqual([text[x['offset']:].splitlines()[0] for x in items],['1 Introduction','第二章 方法'])
    def test_translation_request_and_errors(self):
        response=io.BytesIO(json.dumps({'responseStatus':200,'responseData':{'translatedText':'你好'}}).encode())
        with patch('reader_navigation.urlopen',return_value=response) as call:
            self.assertEqual(translate('hello','en','zh-CN'),'你好')
            self.assertIn('langpair=en%7Czh-CN',call.call_args.args[0])
        with self.assertRaises(ValueError):translate('汉'*167,'en','zh-CN')
        response=io.BytesIO(json.dumps({'responseStatus':429,'responseDetails':'quota'}).encode())
        with patch('reader_navigation.urlopen',return_value=response),self.assertRaisesRegex(ValueError,'quota'):translate('hello','en','zh-CN')

class HiddenNavigationTests(unittest.TestCase):
    def test_text_directory_and_labels_persist_per_attachment(self):
        import tkinter as tk
        from library_core import Library
        from reader_ui import ReaderPage
        from types import SimpleNamespace
        import ui_theme
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);source=base/'a.txt';source.write_text('1 Introduction\nbody\n2 Methods\ntext',encoding='utf-8')
            lib=Library(base/'library');rid=lib.import_document(source);attachment=lib.primary_attachment(rid)
            root=tk.Tk();root.withdraw();ui_theme.install_theme(root)
            reader=ReaderPage(root,lib.root,lambda _:None,lambda _:None)
            try:
                with patch('reader_ui.threading.Thread',side_effect=lambda *,target,daemon:SimpleNamespace(start=target)):
                    reader.open(rid);reader.poll()
                self.assertEqual([x['title'] for x in reader.navigation.outline],['1 Introduction','2 Methods'])
                with patch('reader_navigation.simpledialog.askstring',return_value='重要位置'):reader.navigation.add_label()
                self.assertEqual(reader.navigation.labels[0]['name'],'重要位置')
                reader.navigation.labels=[];reader.navigation.open()
                self.assertEqual(reader.navigation.labels[0]['name'],'重要位置')
                self.assertEqual(reader.navigation.key(),'reader-page-labels:'+rid+':'+attachment['id'])
            finally:reader.close();root.destroy();lib.close()

if __name__=='__main__':unittest.main()
