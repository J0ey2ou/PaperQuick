"""Cross-module checks for attachment types, download routing and exports."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from library_core import Library
from download_actions import resolve_download
from endnote_sync import export_xml
from reading_stats import foreground_reader
from test_library_documents import pdf,docx


class DocumentWorkflowTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[1]/'build'/'document-workflow-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.temp.name);self.lib=Library(self.root/'store')
        self.rid=self.lib.save({'title':'Fictional paper','links':[{'kind':'pdf','url':'https://example.org/main.pdf'}]})
    def tearDown(self):self.lib.close();self.temp.cleanup()

    def test_supplement_does_not_satisfy_main_text_download(self):
        extra=self.root/'supplement.pdf';pdf(extra,'Extra material')
        main=self.root/'main.pdf';pdf(main,'Main paper')
        self.lib.add_attachment(self.rid,extra)
        self.lib.add_attachment_link(self.rid,'https://example.org/supplement','Supplement website')
        with patch('download_actions.download_pdf',side_effect=lambda lib,rid,url:lib.attach(rid,main)) as fetch:
            result=resolve_download(self.lib,self.rid)
        self.assertEqual(result['kind'],'downloaded');fetch.assert_called_once()
        self.assertIsNotNone(self.lib.primary_attachment(self.rid))
        self.assertEqual(len(self.lib.get(self.rid)['attachments']),3)

    def test_word_main_is_opened_without_redownload(self):
        source=self.root/'main.docx';docx(source)
        stored=self.lib.add_attachment(self.rid,source,role='primary')
        with patch('download_actions.download_pdf') as fetch:
            result=resolve_download(self.lib,self.rid)
        self.assertEqual(result,{'kind':'existing','path':str(stored)});fetch.assert_not_called()

    def test_endnote_pdf_urls_do_not_contain_word_or_website(self):
        source=self.root/'main.docx';docx(source)
        extra=self.root/'supplement.pdf';pdf(extra)
        self.lib.add_attachment(self.rid,source,role='primary');pdf_path=self.lib.add_attachment(self.rid,extra)
        self.lib.add_attachment_link(self.rid,'https://example.org/extra','Link')
        output=self.root/'exchange.xml';export_xml([self.lib.get(self.rid)],output,self.lib)
        urls=[e.text for e in ET.parse(output).findall('.//pdf-urls/url')]
        self.assertEqual(urls,[pdf_path.resolve().as_uri()])

    def test_unavailable_preview_does_not_count_as_reading(self):
        app=SimpleNamespace(current_page='reader',reader_page=SimpleNamespace(rid='example',loading=False,path=None,count=0))
        self.assertFalse(foreground_reader(app))


if __name__=='__main__':unittest.main()
