"""Isolated research data: provenance, atomic handoff and real export content."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from library_core import Library
from research_store import ResearchStore, STAGES, write_export


class ResearchStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / 'library'
        self.lib = Library(self.directory)
        self.project = self.lib.create_project('研究课题')
        self.child = self.lib.create_project('子课题', self.project)
        self.one = self.lib.save({'title': '=Important study', 'doi': '10.1000/one'}, self.project)
        self.two = self.lib.save({'title': 'Second study'}, self.child)
        source = Path(self.temp.name) / 'source.txt'; source.write_text('Original source text', encoding='utf-8')
        self.lib.add_attachment(self.one, source, role='primary')
        self.attachment = self.lib.primary_attachment(self.one)
        self.store = ResearchStore(self.directory)

    def tearDown(self):
        self.store.close(); self.lib.close(); self.temp.cleanup()

    def card(self, **changes):
        return self.store.save_card(dict(project=self.project, paper=self.one, attachment=self.attachment['id'], page=0,
                                         quote='Original source text', interpretation='A possible interpretation', claim='A bounded claim',
                                         stance='support', verified=True, rect=[.1, .2, .8, .3]) | changes)

    def test_card_scope_source_identity_and_revision_conflict(self):
        card = self.card()
        self.assertEqual(card['source_sha'], self.attachment['sha'])
        self.assertEqual(card['rect'], [.1, .2, .8, .3])
        self.assertEqual(self.store.validate_sources(self.project, verify_files=True), [])
        self.card(project=self.child, verified=False)
        self.assertEqual(len(self.store.cards(self.project)), 2)
        updated = self.store.save_card(card | {'claim': 'Revised claim'})
        self.assertEqual(updated['revision'], 2)
        with self.assertRaisesRegex(ValueError, '其他窗口'):
            self.store.save_card(card | {'claim': 'Stale claim'})
        with self.assertRaises(ValueError):
            self.card(paper=self.two)
        with self.assertRaises(ValueError):
            self.card(page=-1)
        with self.assertRaises(ValueError):
            self.card(rect=[0, 0, float('nan'), 1])
        self.assertEqual(self.store.card(card['id'])['claim'], 'Revised claim')

    def test_changes_missing_files_and_orphan_sources_are_explicit(self):
        card = self.card()
        path = self.directory / self.attachment['path']; path.write_text('Changed externally', encoding='utf-8')
        codes = {i['code'] for i in self.store.validate_sources(self.project, verify_files=True)}
        self.assertIn('changed_file', codes)
        with self.assertRaises(ValueError):
            self.store.save_card(card)
        path.unlink()
        self.assertIn('missing_file', {i['code'] for i in self.store.validate_sources(self.project)})
        with self.lib.db:
            self.lib.db.execute('DELETE FROM papers WHERE id=?', (self.one,))
        self.assertIn('missing_paper', {i['code'] for i in self.store.validate_sources(self.project)})

    def test_matrix_evidence_constraints_column_deletion_and_card_cleanup(self):
        card = self.card(); matrix = self.store.save_matrix({'project': self.project, 'name': 'Comparison', 'columns': ['方法', '结果']})
        column = matrix['columns'][0]['id']
        self.store.save_cell(matrix['id'], self.one, column, '=malicious formula', [card['id']])
        with self.assertRaises(ValueError):
            self.store.save_cell(matrix['id'], self.two, column, 'wrong source', [card['id']])
        with self.assertRaises(ValueError):
            self.store.save_matrix(matrix | {'columns': matrix['columns'][1:]})
        section = self.store.save_section({'project': self.project, 'title': 'Evidence section', 'body': 'Text', 'position': 1, 'evidence': [card['id']]})
        csv = self.store.matrix_csv(matrix['id'])
        self.assertIn("'=Important study", csv); self.assertIn("'=malicious formula", csv)
        self.assertIn(card['id'][:8], csv)
        self.store.delete_card(card['id'])
        self.assertEqual(self.store.cells(matrix['id'])[0]['evidence'], [])
        self.assertEqual(self.store.sections(self.project)[0]['evidence'], [])
        self.assertEqual(self.store.history(self.project)[-1]['action'], 'card_deleted')
        self.assertIn('no_evidence', {i['code'] for i in self.store.validate_sources(self.project)})

    def test_two_stage_screening_counts_and_audit_retain_changed_decisions(self):
        with self.assertRaises(ValueError):
            self.store.save_decision(self.project, self.one, STAGES[1], 'include')
        with self.assertRaises(ValueError):
            self.store.save_decision(self.project, self.one, STAGES[0], 'exclude')
        self.store.save_decision(self.project, self.one, STAGES[0], 'include')
        self.store.save_decision(self.project, self.one, STAGES[1], 'exclude', '不同人群')
        self.store.save_decision(self.project, self.two, STAGES[0], 'uncertain', '摘要信息不足')
        counts = self.store.screening_counts(self.project)
        self.assertEqual(counts['total'], 2); self.assertEqual(counts['review_mode'], 'single_reviewer')
        self.assertEqual(counts['full_text']['total'], 1); self.assertEqual(counts['full_text']['exclude'], 1)
        self.store.save_decision(self.project, self.one, STAGES[0], 'exclude', '重新判断不满足设计要求')
        self.assertEqual(self.store.screening_counts(self.project)['full_text']['total'], 0)
        self.assertEqual(len(self.store.history(self.project)), 4)
        self.assertTrue(any(e['data']['after'].get('reason') == '不同人群' for e in self.store.history(self.project)))
        self.assertIn('单人本地筛选', self.store.screening_csv(self.project))

    def test_handoff_remaps_all_live_links_and_rolls_back_bad_payload(self):
        card = self.card(); matrix = self.store.save_matrix({'project': self.project, 'name': '矩阵', 'columns': ['结果']})
        self.store.save_cell(matrix['id'], self.one, matrix['columns'][0]['id'], 'Result', [card['id']])
        self.store.save_section({'project': self.project, 'title': '综述', 'position': 0, 'body': 'Draft', 'evidence': [card['id']]})
        self.store.save_decision(self.project, self.one, STAGES[0], 'include')
        self.store.save_decision(self.project, self.one, STAGES[1], 'include')
        payload = json.loads(json.dumps(self.store.export_project(self.project)))
        target = self.lib.create_project('交接课题'); target_child = self.lib.create_project('子课题', target)
        project_map = {self.project: target, self.child: target_child}
        before = len(self.store.cards())
        invalid = copy.deepcopy(payload); invalid['sections'][0]['evidence'] = ['missing-card']
        with self.assertRaises(ValueError):
            self.store.import_project(invalid, project_map)
        self.assertEqual(len(self.store.cards()), before)
        result = self.store.import_project(payload, project_map)
        imported = self.store.cards(target)[0]
        self.assertNotEqual(imported['id'], card['id']); self.assertFalse(imported['verified']); self.assertTrue(imported['imported_verified'])
        mapped = result['id_maps']['matrices'][matrix['id']]
        self.assertEqual(self.store.cells(mapped)[0]['evidence'], [imported['id']])
        self.assertEqual(self.store.sections(target)[0]['evidence'], [imported['id']])
        self.assertEqual(len(self.store.decisions(target)), 2)
        with self.assertRaisesRegex(ValueError, '已有'):
            self.store.import_project(payload, project_map)
        self.assertEqual(len(self.store.cards()), before+1)

    def test_orphan_handoff_is_preserved_and_invalid_second_stage_rolls_back(self):
        card = self.card(); payload = self.store.export_project(self.project)
        payload['cards'][0]['paper'] = 'no-such-paper'; payload['cards'][0]['attachment'] = 'no-such-attachment'
        result = self.store.import_project(payload)
        self.assertTrue(any(i['code'] == 'missing_paper' for i in result['issues']))
        malformed = copy.deepcopy(payload)
        malformed['decisions'] = [{'project': self.project, 'paper': self.one, 'stage': STAGES[1], 'decision': 'include', 'reason': ''}]
        count = len(self.store.cards())
        with self.assertRaises(ValueError):
            self.store.import_project(malformed)
        self.assertEqual(len(self.store.cards()), count)

    def test_outline_word_and_safe_export_preserve_source_details(self):
        card = self.card()
        self.store.save_section({'project': self.project, 'title': '研究发现 & 限制', 'position': 1, 'body': '人工撰写正文', 'evidence': [card['id']]})
        markdown = self.store.outline_markdown(self.project)
        self.assertIn('第 1 页', markdown); self.assertIn(card['id'], markdown); self.assertIn('Original source text', markdown)
        content = self.store.outline_docx(self.project)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml = ET.fromstring(archive.read('word/document.xml'))
            text = ''.join(xml.itertext())
            self.assertIn('人工撰写正文', text); self.assertIn('研究发现 & 限制', text); self.assertIn(card['id'], text)
            ET.fromstring(archive.read('word/styles.xml'))
        path = Path(self.temp.name)/'outline.docx'; write_export(path, content)
        with self.assertRaises(FileExistsError):
            write_export(path, b'wrong')
        self.assertEqual(path.read_bytes(), content)
        write_export(path, b'approved replacement', overwrite=True)
        self.assertEqual(path.read_bytes(), b'approved replacement')

    def test_logical_paragraph_provenance_is_not_exported_as_a_page(self):
        card = self.card(locator_kind='paragraph', paragraph=3, page=None, rect=None)
        self.assertIsNone(card['page']);self.assertEqual(card['paragraph'],3)
        self.assertEqual(self.store.validate_sources(self.project),[])
        self.store.save_section({'project':self.project,'title':'段落证据','position':0,'evidence':[card['id']]})
        text=self.store.outline_markdown(self.project)
        self.assertIn('第 4 段（逻辑段落）',text);self.assertNotIn('第 1 页',text)


if __name__ == '__main__':
    unittest.main()
