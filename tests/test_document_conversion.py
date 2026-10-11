import concurrent.futures
import csv
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

import document_conversion as conversion


def docx_fixture(path):
    """A fictional, two-page OOXML fixture; not a user's manuscript."""
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>PaperQuick conversion fixture</w:t></w:r></w:p><w:p><w:r><w:t>A fictional study of healthy reading habits. Source files remain unchanged.</w:t></w:r></w:p><w:p><w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Microsoft YaHei"/></w:rPr><w:t>中文文献对照阅读 α β</w:t></w:r></w:p><w:p><w:r><w:br w:type="page"/></w:r></w:p><w:p><w:r><w:t>Supplementary results</w:t></w:r></w:p><w:p><w:r><w:t>Page two contains a comparison and a reproducible result.</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>')


def pdf_fixture(path):
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with open(path, 'wb') as stream:
        writer.write(stream)


def unicode_pdf_fixture(path):
    """Small text fixture with an explicit Unicode map, no downloaded font."""
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    text = '中文文献 ABC αβ'
    codes = sorted(set(text))
    mappings = '\n'.join('<%04X> <%04X>' % (ord(c), ord(c)) for c in codes)
    cmap = DecodedStreamObject()
    cmap.set_data(('/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def /CMapName /UnicodeMap def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange %d beginbfchar\n%s\nendbfchar endcmap CMapName currentdict /CMap defineresource pop end end' % (len(codes), mappings)).encode())
    cid = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/CIDFontType2'), NameObject('/BaseFont'): NameObject('/Arial'), NameObject('/CIDSystemInfo'): DictionaryObject({NameObject('/Registry'): TextStringObject('Adobe'), NameObject('/Ordering'): TextStringObject('Identity'), NameObject('/Supplement'): NumberObject(0)})})
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type0'), NameObject('/BaseFont'): NameObject('/Arial'), NameObject('/Encoding'): NameObject('/Identity-H'), NameObject('/DescendantFonts'): ArrayObject([writer._add_object(cid)]), NameObject('/ToUnicode'): writer._add_object(cmap)})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F0'): writer._add_object(font)})})
    content = DecodedStreamObject()
    content.set_data(('BT /F0 12 Tf 40 800 Td <' + text.encode('utf-16be').hex() + '> Tj ET').encode())
    page[NameObject('/Contents')] = writer._add_object(content)
    with open(path, 'wb') as stream:
        writer.write(stream)
    return text


class DocumentConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='PaperQuickConversionTest-')
        self.root = Path(self.temp.name)
        self.source = self.root / '虚构文献.docx'
        docx_fixture(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def fake_convert(self, request, timeout=120):
        pdf_fixture(request['destination'])
        return {'path': request['destination']}

    def test_supported_directions_only(self):
        for source in ('a.doc', 'a.docx', 'a.DOCX'):
            self.assertTrue(conversion.can_convert(source, '.PDF'))
        self.assertTrue(conversion.can_convert('a.pdf', 'docx'))
        for source, suffix in [('a.pdf', '.doc'), ('a.docx', '.docx'), ('a.docm', '.pdf'), ('a.txt', '.pdf')]:
            self.assertFalse(conversion.can_convert(source, suffix))

    def test_existing_target_never_overwritten(self):
        target = self.root / 'existing.pdf'
        target.write_bytes(b'valuable existing file')
        with patch.object(conversion, '_call') as call, self.assertRaisesRegex(conversion.DocumentConversionError, '已有同名'):
            conversion.convert_document(self.source, target)
        call.assert_not_called()
        self.assertEqual(target.read_bytes(), b'valuable existing file')

    def test_failed_or_incomplete_conversion_leaves_no_target(self):
        target = self.root / 'out.pdf'
        def incomplete(request, **kwargs):
            Path(request['destination']).write_bytes(b'%PDF-incomplete')
            return {}
        with patch.object(conversion, '_call', side_effect=incomplete), self.assertRaises(conversion.DocumentConversionError):
            conversion.convert_document(self.source, target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.paperquick-convert-*')))

    def test_publication_race_preserves_other_file(self):
        target = self.root / 'race.pdf'
        def race(request, **kwargs):
            pdf_fixture(request['destination'])
            target.write_bytes(b'another writer won')
            return {}
        with patch.object(conversion, '_call', side_effect=race), self.assertRaisesRegex(conversion.DocumentConversionError, '已有同名'):
            conversion.convert_document(self.source, target)
        self.assertEqual(target.read_bytes(), b'another writer won')
        self.assertFalse(list(self.root.glob('.paperquick-convert-*')))

    def test_cache_is_content_based_and_reuses_existing(self):
        before = self.source.read_bytes()
        with patch.object(conversion, '_call', side_effect=self.fake_convert) as call:
            first = conversion.preview_pdf(self.source, self.root / 'cache')
            second = conversion.preview_pdf(self.source, self.root / 'cache')
            alias = self.root / 'renamed.docx'
            alias.write_bytes(before)
            self.assertEqual(first, conversion.preview_pdf(alias, self.root / 'cache'))
            self.assertEqual(call.call_count, 1)
            self.assertEqual(first, second)
            with zipfile.ZipFile(self.source, 'a') as archive:
                archive.writestr('a-change.xml', '<changed/>')
            third = conversion.preview_pdf(self.source, self.root / 'cache')
            self.assertNotEqual(first, third)
            self.assertEqual(call.call_count, 2)

    def test_parallel_previews_share_one_conversion(self):
        def delayed(request, **kwargs):
            time.sleep(.15)
            return self.fake_convert(request)
        with patch.object(conversion, '_call', side_effect=delayed) as call:
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                results = list(pool.map(lambda _: conversion.preview_pdf(self.source, self.root / 'cache'), range(3)))
            self.assertEqual(len(set(results)), 1)
            self.assertEqual(call.call_count, 1)

    def test_pdf_preview_does_not_launch_word(self):
        source = self.root / 'original.pdf'
        pdf_fixture(source)
        with patch.object(conversion, '_call') as call:
            self.assertEqual(conversion.preview_pdf(source, self.root / 'cache'), source)
        call.assert_not_called()

    def test_source_change_refuses_publication(self):
        def changed(request, **kwargs):
            result = self.fake_convert(request)
            self.source.write_bytes(b'externally changed input')
            return result
        target = self.root / 'out.pdf'
        with patch.object(conversion, '_call', side_effect=changed), self.assertRaisesRegex(conversion.DocumentConversionError, '发生了变化'):
            conversion.convert_document(self.source, target)
        self.assertFalse(target.exists())

    def test_invalid_timeout_does_not_launch(self):
        for timeout in (0, -1, float('nan'), float('inf'), 'bad'):
            with self.subTest(timeout=timeout), patch.object(conversion, '_call') as call, self.assertRaises(conversion.DocumentConversionError):
                conversion.convert_document(self.source, self.root / 'out.pdf', timeout)
            call.assert_not_called()

    def test_frozen_converter_path(self):
        with patch.object(conversion.sys, '_MEIPASS', 'D:/bundle', create=True):
            self.assertEqual(conversion.converter_path(), Path('D:/bundle/word-integration/DocumentConverter.exe'))

    def test_editable_pdf_to_word_preserves_unicode_without_word(self):
        source = self.root / '中文及希腊文.pdf'
        expected = unicode_pdf_fixture(source)
        before = source.read_bytes()
        target = self.root / '文字可编辑.docx'
        with patch.object(conversion, '_call') as call:
            conversion.convert_document(source, target, mode='text')
        call.assert_not_called()
        with zipfile.ZipFile(target) as archive:
            text = ''.join(ET.fromstring(archive.read('word/document.xml')).itertext())
        self.assertIn(expected, text)
        self.assertEqual(source.read_bytes(), before)

    def test_scanned_or_blank_pdf_requires_appearance_mode(self):
        source = self.root / 'scan.pdf'
        pdf_fixture(source)
        target = self.root / 'scan.docx'
        with self.assertRaisesRegex(conversion.DocumentConversionError, '保留页面外观'):
            conversion.convert_document(source, target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.paperquick-convert-*')))
        with patch.object(conversion, '_call') as call:
            conversion.convert_document(source, target, mode='appearance')
        call.assert_not_called()
        with zipfile.ZipFile(target) as archive:
            self.assertIn('word/media/page-1.png', archive.namelist())
            root = ET.fromstring(archive.read('word/document.xml'))
            self.assertEqual(len(root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing')), 1)

    def test_mixed_text_and_scanned_pages_keep_scan_as_image(self):
        from pypdf import PdfReader, PdfWriter
        source = self.root / 'text.pdf'
        expected = unicode_pdf_fixture(source)
        writer = PdfWriter()
        writer.add_page(PdfReader(source).pages[0])
        writer.add_blank_page(width=595, height=842)
        mixed = self.root / 'mixed.pdf'
        with mixed.open('wb') as stream:
            writer.write(stream)
        target = self.root / 'mixed.docx'
        conversion.convert_document(mixed, target)
        with zipfile.ZipFile(target) as archive:
            self.assertIn(expected, ''.join(ET.fromstring(archive.read('word/document.xml')).itertext()))
            self.assertIn('word/media/page-2.png', archive.namelist())

    def test_encrypted_pdf_is_not_silently_decrypted(self):
        from pypdf import PdfWriter
        source = self.root / 'encrypted.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt('private-password')
        with source.open('wb') as stream:
            writer.write(stream)
        with self.assertRaisesRegex(conversion.DocumentConversionError, '已加密'):
            conversion.convert_document(source, self.root / 'encrypted.docx', mode='appearance')

    def test_appearance_uses_visible_crop_and_rotation(self):
        from pypdf import PdfWriter
        from pypdf.generic import RectangleObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=100, height=200)
        page.cropbox = RectangleObject([10, 20, 80, 180])
        page.rotate(90)
        source = self.root / 'crop.pdf'
        with source.open('wb') as stream:
            writer.write(stream)
        target = self.root / 'crop.docx'
        conversion.convert_document(source, target, mode='appearance')
        with zipfile.ZipFile(target) as archive:
            root = ET.fromstring(archive.read('word/document.xml'))
        w = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        size = root.find('.//' + w + 'pgSz')
        self.assertEqual((size.get(w + 'w'), size.get(w + 'h')), ('3200', '1400'))

    @unittest.skipUnless(os.name == 'nt' and os.environ.get('PAPERQUICK_DOCUMENT_CONVERSION_TEST') == '1', 'Explicit isolated Microsoft Word conversion test')
    def test_real_word_roundtrip_preview_and_process_cleanup(self):
        from pypdf import PdfReader
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        target = self.root / '导出文献.pdf'
        real_call = conversion._call
        owned_pids = []
        def observed(request, **kwargs):
            try:
                result = real_call(request, **kwargs)
            except conversion.DocumentConversionError as error:
                self.fail(str(error) + '\n' + getattr(error, 'detail', ''))
            if 'owned_pid' in result:
                owned_pids.append(result['owned_pid'])
            return result
        self.assertTrue(conversion.health()['installed'])
        with patch.object(conversion, '_call', side_effect=observed) as call:
            self.assertEqual(conversion.convert_document(self.source, target), target)
            pdf = PdfReader(target)
            self.assertEqual(len(pdf.pages), 2)
            text = '\n'.join(page.extract_text() for page in pdf.pages)
            self.assertIn('PaperQuick conversion fixture', text)
            self.assertIn('Supplementary results', text)
            self.assertIn('中文文献对照阅读', text)
            pdf_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            restored = self.root / '恢复文献.docx'
            conversion.convert_document(target, restored)
            with zipfile.ZipFile(restored) as archive:
                xml = ET.fromstring(archive.read('word/document.xml'))
            doc_text = ''.join(xml.itertext())
            self.assertIn('PaperQuick conversion fixture', doc_text)
            self.assertIn('Supplementary results', doc_text)
            self.assertIn('中文文献对照阅读', doc_text)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), pdf_hash)
            self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_hash)
            preview = conversion.preview_pdf(self.source, self.root / 'cache')
            self.assertTrue(preview.is_file())
            calls = call.call_count
            self.assertEqual(conversion.preview_pdf(self.source, self.root / 'cache'), preview)
            self.assertEqual(call.call_count, calls)
            with self.assertRaises(conversion.DocumentConversionError):
                conversion.convert_document(self.source, target)
        output = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq WINWORD.EXE', '/FO', 'CSV', '/NH'], creationflags=subprocess.CREATE_NO_WINDOW)
        current_pids = {int(row[1]) for row in csv.reader(io.StringIO(output.decode(errors='replace'))) if len(row) > 1 and row[0].upper() == 'WINWORD.EXE'}
        self.assertFalse(current_pids.intersection(owned_pids), 'The converter left its Word process running')


if __name__ == '__main__':
    unittest.main()
