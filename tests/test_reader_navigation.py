import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfWriter
from reader_navigation import pdf_outline, text_headings, translate

class NavigationTests(unittest.TestCase):
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
