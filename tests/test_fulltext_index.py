"""Whole-file local search coverage, incremental indexing and isolated OCR behavior."""
from pathlib import Path
import os
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from library_core import Library
from fulltext_index import FulltextIndex, LocalOCR, IndexCancelled


def make_pdf(path, texts):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    font_id = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(600, 800)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font_id})})
        stream = DecodedStreamObject()
        escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        stream.set_data(f'BT /F1 12 Tf 40 750 Td ({escaped}) Tj ET'.encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    with Path(path).open('wb') as output:writer.write(output)


class FulltextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.lib = Library(self.base / 'store')
        self.index = FulltextIndex(self.lib.root)

    def tearDown(self):
        self.lib.close();self.temp.cleanup()

    def add(self, path, title='Fixture', project=None):
        rid = self.lib.save({'title': title}, project)
        self.lib.add_attachment(rid, path, role='primary')
        return rid, self.lib.primary_attachment(rid)

    def test_all_pdf_pages_are_indexed_and_blank_page_is_reported(self):
        source = self.base / 'long.pdf'
        texts = [f'Page {n} ordinary research' for n in range(125)]
        texts[42] = 'MiddleNeedle clinical prediction evidence'
        texts.append('')
        make_pdf(source, texts)
        rid, attachment = self.add(source)
        result = self.index.update()
        self.assertEqual(result['errors'], 0)
        matches = self.index.search('MiddleNeedle', include_text=True)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['page'], 42)
        self.assertEqual(matches[0]['attachment'], attachment['id'])
        self.assertIn('clinical prediction', matches[0]['text'])
        self.assertEqual(matches[0]['locator_kind'], 'page')
        coverage = self.index.coverage()[0]
        self.assertEqual((coverage['total'], coverage['text_units'], coverage['empty_units']), (126, 125, 1))
        self.assertEqual(coverage['status'], 'partial')

    def test_incremental_sha_changes_missing_files_and_project_scope(self):
        project = self.lib.create_project('Included')
        other = self.lib.create_project('Other')
        a, b = self.base / 'one.txt', self.base / 'two.txt'
        a.write_text('sharedneedle first version', encoding='utf-8');b.write_text('sharedneedle other project', encoding='utf-8')
        rid, attachment = self.add(a, 'One', project)
        self.add(b, 'Two', other)
        self.index.update()
        with patch('fulltext_index.logical_paragraphs', side_effect=AssertionError('unchanged file must reuse index')):
            self.assertEqual(self.index.update()['updated'], 0)
        matches = self.index.search('sharedneedle', project=project)
        self.assertEqual({item['paper'] for item in matches}, {rid})
        managed = self.lib.root / attachment['path']
        managed.write_text('replacementneedle second version is different', encoding='utf-8')
        self.assertEqual(self.index.coverage(project)[0]['status'], 'stale')
        self.assertFalse(self.index.search('sharedneedle', project=project))
        self.index.update(project)
        self.assertEqual(len(self.index.search('replacementneedle', project=project)), 1)
        managed.unlink()
        self.assertEqual(self.index.coverage(project)[0]['status'], 'missing')
        self.assertFalse(self.index.search('replacementneedle', project=project))

    def test_docx_and_chinese_text_report_logical_paragraphs_and_literal_queries(self):
        source = self.base / 'paragraphs.docx'
        with zipfile.ZipFile(source, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>第一段方法</w:t></w:r></w:p><w:p><w:r><w:t>研究结果流感预测 50% _test</w:t></w:r></w:p></w:body></w:document>')
        rid, attachment = self.add(source)
        self.lib.save({'notes': '仅存在于研究笔记的结论', 'annotations': [{'attachment': attachment['id'], 'page': 3, 'quote': '批注摘录', 'text': '批注想法'}]}, rid=rid)
        self.index.update()
        match = self.index.search('流感预测')[0]
        self.assertEqual((match['locator_kind'], match['paragraph'], match['page']), ('paragraph', 1, None))
        self.assertEqual(len(self.index.search('50%')), 1)
        self.assertEqual(self.index.search('仅存在于')[0]['source'], '笔记')
        annotation = self.index.search('批注想法')[0]
        self.assertEqual(annotation['attachment'], attachment['id'])
        self.assertEqual(annotation['source'], '批注')
        self.assertFalse(self.index.search('" OR 1=1 --'))

    def test_cancellation_does_not_publish_partial_attachment_or_poison_retry(self):
        source = self.base / 'cancel.pdf'
        make_pdf(source, ['findneedle'] * 5)
        rid, attachment = self.add(source)
        cancel = threading.Event()
        def progress(done, total, message):
            if '第 2 / 5 页' in message:cancel.set()
        with self.assertRaises(IndexCancelled):self.index.update(cancel=cancel, progress=progress)
        self.assertEqual(self.index.coverage()[0]['status'], 'interrupted')
        self.assertFalse(self.index.search('findneedle'))
        self.index.update()
        self.assertEqual(len(self.index.search('findneedle')), 5)

    def test_local_ocr_marks_origin_and_keeps_original_pdf(self):
        source = self.base / 'scan.pdf'
        make_pdf(source, [''])
        rid, attachment = self.add(source)
        before = (self.lib.root / attachment['path']).read_bytes()
        with patch.object(LocalOCR, 'probe', return_value={'languages': ['eng']}), patch.object(LocalOCR, 'recognize', return_value='OCRneedle local recognized evidence'):
            self.index.update(ocr=True)
        result = self.index.search('OCRneedle')[0]
        self.assertEqual(result['origin'], 'ocr')
        self.assertEqual(self.index.coverage()[0]['ocr_units'], 1)
        self.assertEqual((self.lib.root / attachment['path']).read_bytes(), before)
        with patch('fulltext_index.pdf_segments', side_effect=AssertionError('text-only refresh must preserve existing OCR')):
            self.index.update()

    def test_ocr_unavailable_and_cancel_only_own_hidden_process(self):
        with patch('fulltext_index.shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, '未找到本地'):LocalOCR().probe()
        executable = self.base / 'tesseract.exe';executable.write_bytes(b'fixture')
        process = Mock()
        cancel = threading.Event()
        def communicate(**kwargs):
            if kwargs:
                cancel.set()
                raise subprocess.TimeoutExpired('fixture', .15)
            return b'', b''
        process.communicate.side_effect = communicate
        process.poll.return_value = None
        with patch('fulltext_index.subprocess.Popen', return_value=process) as launch:
            with self.assertRaises(IndexCancelled):LocalOCR(executable).probe(cancel)
        process.kill.assert_called_once()
        args, kwargs = launch.call_args
        self.assertEqual(args[0], [str(executable.resolve()), '--list-langs'])
        self.assertEqual(kwargs['creationflags'], subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertNotIn('shell', kwargs)


if __name__ == '__main__':unittest.main()
