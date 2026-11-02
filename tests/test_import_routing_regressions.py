"""Document identity and re-import routes, using disposable local libraries."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from library_core import Library, digest
from test_library_documents import pdf, docx


class ImportRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.lib = Library(self.base / 'store')
        self.project = self.lib.projects()[0]['id']

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def test_supplement_can_be_imported_as_its_own_document_and_reimported(self):
        for suffix in ('pdf', 'docx'):
            with self.subTest(suffix=suffix):
                source = self.base / ('supplement.' + suffix)
                (pdf if suffix == 'pdf' else docx)(source, title='Independent ' + suffix)
                owner = self.lib.save({'title': 'Main ' + suffix})
                self.lib.add_attachment(owner, source)
                old = self.lib.get(owner)['attachments'][0]
                result = self.lib.import_batch([source], self.project)
                self.assertEqual(result['count'], 1)
                independent = result['paper_ids'][0]
                self.assertNotEqual(independent, owner)
                primary = self.lib.primary_attachment(independent)
                self.assertIsNotNone(primary)
                self.assertEqual(digest(self.lib.root / primary['path']), digest(source))
                self.assertEqual(self.lib.get(owner)['attachments'][0], old)
                self.assertEqual(self.lib.import_document(source), independent)

    def test_reimport_prefers_primary_over_an_older_supplement_of_another_paper(self):
        source = self.base / 'article.pdf'; pdf(source)
        owner = self.lib.save({'title': 'Other paper'})
        self.lib.add_attachment(owner, source)
        correct = self.lib.save({'title': 'Actual paper'})
        self.lib.add_attachment(correct, source, role='primary')
        self.assertEqual(self.lib.import_pdf(source), correct)
        self.assertEqual(len(self.lib.get(correct)['attachments']), 1)

    def test_ambiguous_doi_does_not_choose_an_arbitrary_existing_record(self):
        source = self.base / 'article.docx'; docx(source)
        a = self.lib.save({'title': 'One', 'doi': '10.1234/primary'}, deduplicate=False)
        b = self.lib.save({'title': 'Two', 'doi': '10.1234/primary'}, deduplicate=False)
        rid = self.lib.import_document(source)
        self.assertNotIn(rid, (a, b))
        self.assertEqual(self.lib.get(a)['title'], 'One')
        self.assertEqual(self.lib.get(b)['title'], 'Two')
        self.assertEqual(self.lib.import_document(source), rid)

    def test_import_failure_does_not_leave_a_phantom_paper(self):
        source = self.base / 'article.pdf'; pdf(source)
        with patch.object(self.lib, '_add_attachment', side_effect=OSError('disk full')):
            result = self.lib.import_batch([source], self.project)
        self.assertEqual(result['count'], 0)
        self.assertFalse(self.lib.records())
        self.assertEqual(self.lib.import_batch([source], self.project)['count'], 1)

    def test_wrong_record_doi_cannot_override_the_identity_of_its_primary(self):
        from test_import_identity import paper
        first, second = self.base / 'one.pdf', self.base / 'two.pdf'
        paper(first, 'First article', '001503');paper(second, 'Second article', '002007')
        owner = self.lib.import_pdf(first)
        self.lib.save({'doi':'10.1136/bmjopen-2012-002007'}, rid=owner)
        rid = self.lib.import_pdf(second)
        self.assertNotEqual(rid, owner)
        self.assertEqual(digest(self.lib.root / self.lib.primary_attachment(owner)['path']), digest(first))
        self.assertEqual(self.lib.import_pdf(second), rid)

    def test_changing_source_during_copy_never_archives_mismatched_bytes(self):
        import shutil
        source = self.base / 'article.pdf'; pdf(source)
        original_copy = shutil.copyfileobj
        def changed(input_file, output):
            original_copy(input_file, output)
            output.write(b'changed while being copied')
        with patch('library_core.shutil.copyfileobj', side_effect=changed):
            result = self.lib.import_batch([source], self.project)
        self.assertEqual(result['count'], 0)
        self.assertFalse(self.lib.records())
        self.assertFalse(list((self.lib.root / 'papers').rglob('*.pdf')))
        self.assertEqual(self.lib.import_batch([source], self.project)['count'], 1)

    def test_failed_existing_doi_import_preserves_reviewed_metadata(self):
        source = self.base / 'article.docx'; docx(source)
        rid = self.lib.save({'title':'Reviewed title','doi':'10.1234/primary','notes':'Keep notes'})
        before = self.lib._snapshot(rid)
        with patch.object(self.lib, '_add_attachment', side_effect=OSError('disk full')):
            result = self.lib.import_batch([source], self.project)
        self.assertEqual(result['count'], 0)
        self.assertEqual(self.lib._snapshot(rid), before)
        self.assertEqual(self.lib.import_document(source), rid)
        self.assertEqual(self.lib.get(rid)['title'], 'Reviewed title')

    def test_selected_file_identity_is_reported_for_repeat_import(self):
        source = self.base / 'article.pdf'; pdf(source)
        first = self.lib.import_document(source)
        second_project = self.lib.create_project('Second project')
        result = self.lib.import_batch([source, source], second_project)
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['paper_ids'], [first])
        for detail in result['details']:
            self.assertEqual(detail['attachment_id'], self.lib.primary_attachment(first)['id'])
            self.assertEqual(digest(self.lib.root / detail['path']), digest(source))
        self.assertIn(second_project, self.lib.get(first)['projects'])


if __name__ == '__main__': unittest.main()
