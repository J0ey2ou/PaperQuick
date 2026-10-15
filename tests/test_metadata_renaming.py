from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from library_core import Library, digest, filename, validate_template
from metadata_renaming import extract_article_metadata, prepare_renames, apply_renames
from test_library_documents import docx


class MetadataRenamingTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / 'build' / 'metadata-rename-tests'
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.base = Path(self.tmp.name)
        self.lib = Library(self.base / 'store')
        self.lib.set_setting('template', '{年份}_{第一作者}_{期刊}_{标题}')

    def tearDown(self):
        self.lib.close(); self.tmp.cleanup()

    def article(self, name='wrong-filename.docx'):
        source = self.base / name
        docx(source, title='Wrong filename title', author='wxz', paragraphs=[
            '标题：An evidence based study of primary care', '作者：Alice Smith; Bob Jones',
            '期刊：Journal of Primary Care', '年份：2025', 'Main body.'])
        rid = self.lib.import_document(source)
        return source, rid

    def test_reads_body_before_preview_and_confirms_exact_name_preserving_notes(self):
        source, rid = self.article()
        original = digest(source)
        before = self.lib.get(rid)
        plans = prepare_renames(self.lib, [rid])
        self.assertFalse(plans[0]['error'])
        self.assertEqual(plans[0]['fields']['authors'], 'Alice Smith; Bob Jones')
        self.assertEqual(self.lib.get(rid), before)  # Cancellation requires no rollback.
        self.assertIn('2025_Alice Smith_Journal of Primary Care_An evidence', plans[0]['files'][0]['new'])
        self.lib.save({'notes': 'Edited while preview was open', 'annotations': [{'page': 1}]}, rid=rid)
        result = apply_renames(self.lib, plans)
        self.assertEqual(result, {'count': 1, 'errors': []})
        after = self.lib.get(rid)
        self.assertEqual(after['attachments'][0]['path'], plans[0]['files'][0]['new'])
        self.assertEqual(after['venue'], 'Journal of Primary Care')
        self.assertEqual(after['notes'], 'Edited while preview was open')
        self.assertEqual(after['annotations'], [{'page': 1}])
        self.assertEqual(digest(source), original)
        self.assertEqual(digest(self.lib.root / after['attachments'][0]['path']), original)

    def test_supplement_and_office_creator_are_not_article_metadata(self):
        source = self.base / 'supplement.docx'
        docx(source, title='', author='wxz', paragraphs=['Figures',
             'Figure S1. Weekly cases in Beijing, 2020-2021.', 'Tables', 'Table S1. Criteria.'])
        rid = self.lib.import_document(source)
        fields = extract_article_metadata(source)['fields']
        self.assertNotIn('title', fields)
        self.assertNotIn('authors', fields)
        self.assertNotIn('year', fields)
        before = self.lib.get(rid)
        plans = prepare_renames(self.lib, [rid])
        self.assertIn('缺少可靠', plans[0]['error'])
        self.assertEqual(apply_renames(self.lib, plans)['count'], 0)
        self.assertEqual(self.lib.get(rid), before)

    def test_duplicate_batch_names_match_the_preview_and_never_overwrite(self):
        first_source, one = self.article('one.docx')
        second_source, two = self.article('two.docx')
        # Identical file import deduplicates; make a separate independent record.
        two = self.lib.save({'title': 'Different old title'})
        self.lib.add_attachment(two, second_source, role='primary')
        plans = prepare_renames(self.lib, [one, two])
        self.assertNotEqual(plans[0]['files'][0]['new'], plans[1]['files'][0]['new'])
        self.assertIn('(2)', plans[1]['files'][0]['new'])
        self.assertEqual(apply_renames(self.lib, plans), {'count': 2, 'errors': []})
        for plan in plans:
            self.assertEqual(self.lib.get(plan['id'])['attachments'][0]['path'], plan['files'][0]['new'])

    def test_changed_document_metadata_or_rule_requires_new_preview(self):
        source, rid = self.article()
        for change in ('metadata', 'rule', 'file', 'occupied'):
            with self.subTest(change=change):
                plans = prepare_renames(self.lib, [rid])
                if change == 'metadata': self.lib.save({'title': 'Manual corrected title'}, rid=rid)
                elif change == 'rule': self.lib.set_setting('title_length', 75)
                elif change == 'file':
                    managed = self.lib.root / self.lib.primary_attachment(rid)['path']
                    managed.write_bytes(managed.read_bytes() + b'changed')
                else:
                    target = self.lib.root / plans[0]['files'][0]['new']
                    target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(b'do not overwrite')
                result = apply_renames(self.lib, plans)
                self.assertEqual(result['count'], 0)
                self.assertTrue(result['errors'])
                if change == 'occupied': self.assertEqual(target.read_bytes(), b'do not overwrite')

    def test_journal_rule_aliases(self):
        for token in ('期刊', 'journal', 'venue'):
            validate_template('{' + token + '}_{title}')
            self.assertTrue(filename({'title': 'Example', 'venue': 'Journal A'}, 'P', '{'+token+'}_{title}').startswith('Journal A_'))

    def test_reader_information_is_prepared_before_any_confirmation(self):
        from library_ui import LibraryWindow
        source, rid = self.article()
        window = SimpleNamespace(library=self.lib, status=Mock(), preview_renames=Mock())
        window.run = lambda title, work, done: done(work(self.lib))
        before = self.lib.get(rid)
        LibraryWindow.rename_records(window, [rid])
        plans = window.preview_renames.call_args.args[0]
        self.assertEqual(plans[0]['fields']['venue'], 'Journal of Primary Care')
        self.assertEqual(self.lib.get(rid), before)

    def test_pdf_body_overrides_stale_properties(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        source = self.base / 'article.pdf'
        writer = PdfWriter(); page = writer.add_blank_page(600, 800)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 12 Tf 50 740 Td (Title: A verified primary care research paper) Tj 0 -20 Td (Authors: Alice Smith; Bob Jones) Tj 0 -20 Td (Journal: Journal of Medicine) Tj 0 -20 Td (Year: 2024) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(content)
        writer.add_metadata({'/Title': 'Stale old title', '/Author': 'wxz'})
        with source.open('wb') as stream: writer.write(stream)
        fields = extract_article_metadata(source)['fields']
        self.assertEqual(fields['title'], 'A verified primary care research paper')
        self.assertEqual(fields['authors'], 'Alice Smith; Bob Jones')
        self.assertEqual(fields['venue'], 'Journal of Medicine')
        self.assertEqual(fields['year'], '2024')


if __name__ == '__main__': unittest.main()
