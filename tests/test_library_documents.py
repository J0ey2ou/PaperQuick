"""Document import and attachment relationships only use temporary libraries."""
from pathlib import Path
from contextlib import closing
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from library_core import (Library, digest, document_metadata, has_pdf,
                          local_attachments, readable_attachments)


def docx(path, title='A document title', author='Researcher', paragraphs=None):
    paragraphs = paragraphs or ['A document title', '2025; doi: 10.1234/primary', 'Main document body.']
    body = ''.join('<w:p><w:r><w:t>' + escape(p) + '</w:t></w:r></w:p>' for p in paragraphs)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + '</w:body></w:document>')
        archive.writestr('docProps/core.xml', '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + escape(title) + '</dc:title><dc:creator>' + escape(author) + '</dc:creator></cp:coreProperties>')


def pdf(path, title='PDF article'):
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.add_metadata({'/Title': title})
    with path.open('wb') as stream:
        writer.write(stream)


class LibraryDocumentTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / 'build' / 'document-tests'
        test_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=test_root)
        self.base = Path(self.tmp.name)
        self.lib = Library(self.base / 'library')
        self.project = self.lib.create_project('课题示例')

    def tearDown(self):
        self.lib.close()
        self.tmp.cleanup()

    def test_docx_import_extracts_metadata_and_preserves_source(self):
        source = self.base / 'source.DOCX'
        docx(source, title='中文文献题名', author='张三; Jane Doe')
        before = source.read_bytes()
        rid = self.lib.import_document(source, self.project)
        record = self.lib.get(rid)
        self.assertEqual(record['title'], '中文文献题名')
        self.assertEqual(record['authors'], '张三; Jane Doe')
        self.assertEqual(record['doi'], '10.1234/primary')
        self.assertEqual(record['year'], '2025')
        self.assertIn('Main document body.', record['text'])
        attachment = self.lib.primary_attachment(rid)
        self.assertEqual(attachment['kind'], 'docx')
        self.assertEqual(Path(attachment['path']).suffix, '.DOCX')
        self.assertEqual((self.lib.root / attachment['path']).read_bytes(), before)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(self.lib.import_document(source), rid)
        self.assertEqual(len(self.lib.get(rid)['attachments']), 1)

    def test_reference_doi_is_not_the_document_identity(self):
        source = self.base / 'references.docx'
        for heading in ('References', '8. References:', 'LITERATURE CITED', '参考文献'):
            docx(source, paragraphs=['A study without a DOI', 'Main content 2024', heading,
                                    '1. Doe J. Dietary intake and cohort research. Journal 2020;12:10. doi:10.1234/reference'])
            metadata = document_metadata(source)
            self.assertEqual(metadata['doi'], '')
            self.assertTrue(metadata['references'])
            self.assertEqual(metadata['references'][0]['doi'], '10.1234/reference')

    def test_docx_without_properties_and_legacy_doc_fallback(self):
        source = self.base / 'minimal.docx'
        with zipfile.ZipFile(source, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>A useful first paragraph title</w:t></w:r></w:p></w:body></w:document>')
        self.assertEqual(document_metadata(source)['title'], 'A useful first paragraph title')
        legacy = self.base / 'Legacy article.doc'
        legacy.write_bytes(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + bytes(504))
        rid = self.lib.import_document(legacy, self.project)
        self.assertEqual(self.lib.get(rid)['title'], 'Legacy article')
        self.assertEqual(self.lib.primary_attachment(rid)['kind'], 'doc')

    def test_docx_rejects_entities_invalid_archives_and_keeps_library_clean(self):
        source = self.base / 'bad.docx'
        source.write_bytes(b'not a Word file')
        with self.assertRaises(ValueError):
            self.lib.import_document(source)
        for encoding in ('utf-8', 'utf-16'):
            with zipfile.ZipFile(source, 'w') as archive:
                content = '<?xml version="1.0" encoding="' + encoding + '"?><!DOCTYPE x [<!ENTITY e "hello">]><x>&e;</x>'
                archive.writestr('word/document.xml', content.encode(encoding))
            with self.assertRaises(ValueError):
                self.lib.import_document(source)
        self.assertEqual(self.lib.records(), [])
        self.assertFalse(list((self.lib.root / 'papers').rglob('*.docx')))

    def test_main_pdf_and_supplements_preserve_metadata_and_notes(self):
        main = self.base / 'main.pdf'; pdf(main)
        supplement = self.base / 'supplement.pdf'; pdf(supplement, 'Supplement')
        word = self.base / 'methods.docx'; docx(word)
        rid = self.lib.import_pdf(main, self.project)
        self.lib.save({'text': 'Original main text', 'references': [{'id': 'ref', 'title': 'Reference', 'doi': ''}],
                       'notes': 'My notes', 'annotations': [{'page': 2, 'text': 'Keep me'}]}, rid=rid)
        main_aid = self.lib.primary_attachment(rid)['id']
        path = self.lib.add_attachment(rid, supplement, label='补充材料')
        word_path = self.lib.add_attachment(rid, word, label='方法说明')
        record = self.lib.get(rid)
        self.assertEqual(self.lib.primary_attachment(rid)['id'], main_aid)
        self.assertTrue(has_pdf(record))
        self.assertIn('补充材料', path.name)
        self.assertEqual(word_path.suffix, '.docx')
        self.assertEqual(record['text'], 'Original main text')
        self.assertEqual(record['notes'], 'My notes')
        self.assertEqual(record['annotations'], [{'page': 2, 'text': 'Keep me'}])
        self.assertEqual(len(readable_attachments(record)), 3)
        self.assertEqual(self.lib.add_attachment(rid, supplement), path)
        self.assertEqual(len(self.lib.get(rid)['attachments']), 3)
        self.assertTrue(main.exists() and supplement.exists() and word.exists())

    def test_sha_dedup_is_per_paper_and_label_edit_does_not_rename_source(self):
        source = self.base / 'data.csv'; source.write_text('x,y\n1,2\n')
        one = self.lib.save({'title': 'One'}, self.project)
        two = self.lib.save({'title': 'Two'}, self.project)
        a = self.lib.add_attachment(one, source)
        b = self.lib.add_attachment(two, source)
        self.assertNotEqual(a, b)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        aid = self.lib.get(one)['attachments'][0]['id']
        self.lib.rename_attachment_label(one, aid, '原始数据')
        self.assertEqual(self.lib.get(one)['attachments'][0]['label'], '原始数据')
        with self.assertRaises(ValueError):
            self.lib.rename_attachment_label(two, aid, 'Not ours')
        with self.assertRaises(ValueError):
            self.lib.set_primary_attachment(one, aid)
        self.assertEqual(source.name, 'data.csv')

    def test_links_are_not_files_or_downloaded_full_text(self):
        rid = self.lib.save({'title': 'Link only'}, self.project)
        aid = self.lib.add_attachment_link(rid, 'https://example.org/supplement?download=1', 'Supplementary data')
        self.assertEqual(self.lib.add_attachment_link(rid, 'https://example.org/supplement?download=1'), aid)
        record = self.lib.get(rid)
        self.assertEqual(record['attachments'][0]['kind'], 'link')
        self.assertFalse((self.lib.root / record['attachments'][0]['path']).exists())
        self.assertEqual(local_attachments(record), [])
        self.assertEqual(readable_attachments(record), [])
        self.assertIsNone(self.lib.primary_attachment(rid))
        self.assertEqual(self.lib.rename(rid), [])
        self.assertFalse(self.lib.graph()['nodes'][0]['pdf'])
        for url in ('file:///C:/secret', 'javascript:alert(1)', 'https://', 'https://example.org/\nx', 'http://example.org:broken'):
            with self.assertRaises(ValueError):
                self.lib.add_attachment_link(rid, url)
        with self.assertRaises(ValueError):
            self.lib.set_primary_attachment(rid, aid)

    def test_supplement_pdf_does_not_mark_main_downloaded(self):
        source = self.base / 'supplement.pdf'; pdf(source)
        rid = self.lib.save({'title': 'Metadata only'}, self.project)
        self.lib.add_attachment(rid, source, label='Supplement')
        self.assertFalse(has_pdf(self.lib.get(rid)))
        self.assertIsNone(self.lib.primary_attachment(rid))
        self.assertFalse(self.lib.graph()['nodes'][0]['pdf'])
        aid = self.lib.get(rid)['attachments'][0]['id']
        self.lib.set_primary_attachment(rid, aid)
        self.assertTrue(has_pdf(self.lib.get(rid)))
        self.assertEqual(self.lib.primary_attachment(rid)['id'], aid)

    def test_one_primary_and_rename_preserves_extensions_ids_labels_annotations(self):
        source = self.base / 'main.pdf'; pdf(source)
        word = self.base / 'word.docx'; docx(word)
        data = self.base / 'values.csv'; data.write_text('1,2,3')
        rid = self.lib.import_pdf(source, self.project)
        self.lib.add_attachment(rid, word, label='Word 稿件')
        self.lib.add_attachment(rid, data, label='表格')
        link = self.lib.add_attachment_link(rid, 'https://example.org/supp', 'Online supplement')
        attachments = self.lib.get(rid)['attachments']
        word_aid = next(a['id'] for a in attachments if a['kind'] == 'docx')
        self.lib.save({'notes': 'Retain', 'annotations': [{'attachment': word_aid, 'page': 1}]}, rid=rid)
        self.lib.set_primary_attachment(rid, word_aid)
        self.lib.set_setting('template', '{课题}_{标题}')
        self.lib.save({'title': 'Updated title'}, rid=rid)
        original_hashes = {a['id']: digest(self.lib.root / a['path']) for a in local_attachments(self.lib.get(rid))}
        changes = self.lib.rename(rid)
        self.assertEqual(len(changes), 3)
        record = self.lib.get(rid)
        self.assertEqual(sum(a['role'] == 'primary' for a in record['attachments']), 1)
        self.assertEqual(record['notes'], 'Retain')
        self.assertEqual(record['annotations'], [{'attachment': word_aid, 'page': 1}])
        for a in local_attachments(record):
            self.assertEqual(Path(a['path']).suffix, Path(a['original']).suffix)
            self.assertEqual(digest(self.lib.root / a['path']), original_hashes[a['id']])
        self.assertEqual(next(a for a in record['attachments'] if a['id'] == word_aid)['label'], 'Word 稿件')
        self.assertEqual(next(a for a in record['attachments'] if a['id'] == link)['url'], 'https://example.org/supp')
        self.assertEqual(self.lib.rename(rid), [])
        self.assertTrue(source.exists() and word.exists() and data.exists())
        self.assertTrue(self.lib.graph()['nodes'][0]['pdf'])
        self.assertEqual(self.lib.graph()['summary']['pdf'], 1)

    def test_import_an_alternate_format_preserves_existing_main_text(self):
        source = self.base / 'version.docx'; docx(source)
        rid = self.lib.save({'title': 'Existing article', 'doi': '10.1234/primary', 'notes': 'Retain notes'}, self.project)
        primary = self.base / 'main.pdf'; pdf(primary)
        self.lib.attach(rid, primary, extract=False)
        self.lib.save({'text': 'Existing original text', 'references': []}, rid=rid)
        self.assertEqual(self.lib.import_document(source, self.project), rid)
        self.assertEqual(self.lib.get(rid)['text'], 'Existing original text')
        self.assertEqual(self.lib.get(rid)['notes'], 'Retain notes')
        self.assertEqual(self.lib.primary_attachment(rid)['kind'], 'pdf')

    def test_legacy_migration_is_idempotent_and_does_not_rewrite_paper_data(self):
        root = self.base / 'legacy'; root.mkdir()
        original = json.dumps({'title': 'Legacy', 'notes': 'Important notes', 'annotations': [{'page': 1}]}, ensure_ascii=False)
        with closing(sqlite3.connect(root / 'library.sqlite')) as db, db:
            db.execute('CREATE TABLE papers(id TEXT PRIMARY KEY,data TEXT,primary_project TEXT,updated REAL)')
            db.execute('CREATE TABLE attachments(id TEXT PRIMARY KEY,paper TEXT,path TEXT UNIQUE,sha TEXT,original TEXT)')
            db.execute('INSERT INTO papers VALUES(?,?,?,?)', ('paper', original, '', 123.0))
            db.execute('INSERT INTO attachments VALUES(?,?,?,?,?)', ('first', 'paper', 'papers/one.pdf', 'one', 'one.pdf'))
            db.execute('INSERT INTO attachments VALUES(?,?,?,?,?)', ('second', 'paper', 'papers/two.pdf', 'two', 'two.pdf'))
        for _ in range(2):
            lib = Library(root)
            try:
                record = lib.get('paper')
                self.assertEqual([a['role'] for a in record['attachments']], ['primary', 'supplement'])
                self.assertEqual(lib.primary_attachment('paper')['id'], 'first')
                raw = lib.db.execute('SELECT data,updated FROM papers WHERE id=?', ('paper',)).fetchone()
                self.assertEqual(raw['data'], original)
                self.assertEqual(raw['updated'], 123.0)
                self.assertEqual(record['notes'], 'Important notes')
            finally:
                lib.close()

    def test_reimport_restores_missing_primary_and_keeps_attachment_identity(self):
        for suffix in ('pdf', 'docx'):
            with self.subTest(suffix=suffix):
                source = self.base / ('missing.' + suffix)
                pdf(source) if suffix == 'pdf' else docx(source)
                rid = self.lib.import_document(source, self.project)
                attachment = self.lib.primary_attachment(rid)
                self.lib.rename_attachment_label(rid, attachment['id'], '保留标签')
                notes = {'notes': 'Keep notes', 'annotations': [{'attachment': attachment['id'], 'page': 1}]}
                self.lib.save(notes, rid=rid)
                managed = self.lib.root / attachment['path']
                managed.unlink()
                self.assertEqual(self.lib.import_document(source, self.project), rid)
                recovered = self.lib.primary_attachment(rid)
                self.assertEqual(recovered['id'], attachment['id'])
                self.assertEqual(recovered['label'], '保留标签')
                self.assertEqual(recovered['path'], attachment['path'])
                self.assertEqual(managed.read_bytes(), source.read_bytes())
                self.assertEqual(self.lib.get(rid)['notes'], notes['notes'])
                self.assertEqual(self.lib.get(rid)['annotations'], notes['annotations'])

    def test_reimport_changed_copy_keeps_conflicting_file_and_recovers_supplement(self):
        source = self.base / 'data.csv'; source.write_text('original data')
        rid = self.lib.save({'title': 'Paper'}, self.project)
        path = self.lib.add_attachment(rid, source, label='Data')
        aid = self.lib.get(rid)['attachments'][0]['id']
        path.write_text('user edited data')
        restored = self.lib.add_attachment(rid, source)
        self.assertNotEqual(restored, path)
        self.assertEqual(path.read_text(), 'user edited data')
        self.assertEqual(restored.read_text(), 'original data')
        record = self.lib.get(rid)
        self.assertEqual(len(record['attachments']), 1)
        self.assertEqual(record['attachments'][0]['id'], aid)
        self.assertEqual(record['attachments'][0]['role'], 'supplement')
        self.assertEqual(record['attachments'][0]['label'], 'Data')
        restored.unlink()
        again = self.lib.add_attachment(rid, source)
        self.assertEqual(again, restored)
        self.assertEqual(again.read_text(), 'original data')

    def test_new_download_replaces_missing_primary_even_with_different_hash(self):
        original = self.base / 'old.pdf'; pdf(original, 'Older download')
        replacement = self.base / 'new.pdf'; pdf(replacement, 'Fresh download')
        self.assertNotEqual(digest(original), digest(replacement))
        rid = self.lib.import_pdf(original, self.project)
        old = self.lib.primary_attachment(rid)
        self.lib.save({'notes': 'Keep the shared notes', 'annotations': [{'attachment': old['id'], 'page': 1}]}, rid=rid)
        (self.lib.root / old['path']).unlink()
        stored = self.lib.attach(rid, replacement)
        record = self.lib.get(rid)
        current = self.lib.primary_attachment(rid)
        self.assertNotEqual(current['id'], old['id'])
        self.assertEqual(self.lib.root / current['path'], stored)
        self.assertEqual(digest(stored), digest(replacement))
        self.assertEqual(sum(a['role'] == 'primary' for a in record['attachments']), 1)
        self.assertEqual(next(a for a in record['attachments'] if a['id'] == old['id'])['role'], 'supplement')
        self.assertEqual(record['notes'], 'Keep the shared notes')
        self.assertEqual(record['annotations'], [{'attachment': old['id'], 'page': 1}])
        self.assertTrue(original.is_file() and replacement.is_file())
        # The missing former version remains recoverable without blocking later naming.
        self.assertEqual(self.lib.rename(rid), [])
        self.lib.save({'title': 'A new managed name'}, rid=rid)
        self.assertEqual(len(self.lib.rename(rid)), 1)
        self.assertEqual(self.lib.primary_attachment(rid)['id'], current['id'])
        self.assertEqual(next(a for a in self.lib.get(rid)['attachments'] if a['id'] == old['id'])['path'], old['path'])


if __name__ == '__main__':
    unittest.main()
