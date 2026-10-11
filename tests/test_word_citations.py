"""Word change planning tests: no Word process or CSL runtime is required."""
from copy import deepcopy
import unittest

from citation_metadata import to_csl
from word_citations import citation_label, plan_changes


PAPERS = [
    {'id': 'a', 'title': 'Alpha study', 'authors_structured': [{'family': 'Alpha', 'given': 'Ann'}], 'year': '2020'},
    {'id': 'b', 'title': 'Beta study', 'authors_structured': [{'family': 'Beta', 'given': 'Bob'}], 'year': '2021'},
    {'id': 'c', 'title': 'Gamma study', 'authors_structured': [{'family': 'Gamma', 'given': 'Gail'}], 'year': '2022'},
]


def citation(identifier, start, *records):
    return {'id': identifier, 'kind': 'citation', 'start': start, 'end': start + 3,
            'payload': {'version': 1, 'id': identifier, 'style_id': 'old-style',
                        'items': [{'id': r['id'], 'itemData': to_csl(r)} for r in records]}}


def bibliography(identifier='bib', start=100):
    return {'id': identifier, 'kind': 'bibliography', 'start': start, 'end': start + 5,
            'payload': {'version': 1, 'id': identifier, 'style_id': 'old-style'}}


def snapshot(*fields, cursor=0):
    return {'document': {'name': 'Isolated test.docx', 'full_name': 'fixture'},
            'selection': {'start': cursor, 'end': cursor}, 'fields': list(fields)}


class NumberingFormatter:
    """An order-sensitive formatter spy, not a substitute for real CSL tests."""
    def __init__(self, style_class='in-text'):
        self.style_class = style_class
        self.calls = []

    def __call__(self, items, clusters, style_id, custom_dir=None):
        self.calls.append(deepcopy((items, clusters, style_id, custom_dir)))
        numbers = {}
        rendered = {}
        for cluster in clusters:
            parts = []
            for item in cluster['items']:
                numbers.setdefault(item['id'], len(numbers) + 1)
                part = str(numbers[item['id']])
                if item.get('locator'):
                    part += ': ' + item['locator']
                parts.append(part)
            rendered[cluster['id']] = '[' + ', '.join(parts) + ']'
        entries = [f"{number}. {items[rid]['title']}" for rid, number in numbers.items()]
        return {'style_class': self.style_class, 'citations': rendered,
                'bibliography': '\n'.join(entries), 'plain_citations': rendered,
                'plain_bibliography': '\n'.join(entries)}


class WordChangePlanningTests(unittest.TestCase):
    def setUp(self):
        self.formatter = NumberingFormatter()

    def plan(self, snap, action='refresh', selected=None, target_id=None, **kwargs):
        return plan_changes(snap, PAPERS, 'numeric-style', action, selected,
                            target_id, formatter=self.formatter, **kwargs)

    def test_reorder_and_insertion_recalculate_entire_document(self):
        snap = snapshot(citation('later', 40, PAPERS[0]), citation('earlier', 10, PAPERS[1]),
                        bibliography(), cursor=5)
        operations, _ = self.plan(snap, 'insert', [PAPERS[2]])
        self.assertEqual(operations['insert']['result_rtf'], '[1]')
        updated = {item['id']: item for item in operations['updates']}
        self.assertEqual(updated['earlier']['result_rtf'], '[2]')
        self.assertEqual(updated['later']['result_rtf'], '[3]')
        self.assertEqual(updated['bib']['result_rtf'], '1. Gamma study\n2. Beta study\n3. Alpha study')

    def test_deduplicate_selected_items_and_repeated_citations(self):
        snap = snapshot(citation('existing', 20, PAPERS[0]), bibliography(), cursor=5)
        operations, _ = self.plan(snap, 'insert', [PAPERS[0], PAPERS[1], PAPERS[0]])
        self.assertEqual(operations['insert']['result_rtf'], '[1, 2]')
        self.assertEqual(len(operations['insert']['payload']['items']), 2)
        updates = {item['id']: item for item in operations['updates']}
        self.assertEqual(updates['existing']['result_rtf'], '[1]')
        self.assertEqual(updates['bib']['result_rtf'].count('Alpha study'), 1)

    def test_replace_preserves_field_identity_and_rebuilds_bibliography(self):
        snap = snapshot(citation('first', 10, PAPERS[0]), citation('next', 30, PAPERS[1]), bibliography())
        operations, _ = self.plan(snap, 'replace', [PAPERS[2]], 'first', locator='12–14')
        self.assertNotIn('insert', operations)
        updates = {item['id']: item for item in operations['updates']}
        self.assertEqual(updates['first']['payload']['id'], 'first')
        self.assertEqual(updates['first']['payload']['items'][0]['id'], 'c')
        self.assertEqual(updates['first']['result_rtf'], '[1: 12–14]')
        self.assertEqual(updates['bib']['result_rtf'], '1. Gamma study\n2. Beta study')

    def test_remove_renumbers_and_excludes_unreferenced_paper(self):
        snap = snapshot(citation('first', 10, PAPERS[0]), citation('next', 30, PAPERS[1]), bibliography())
        operations, _ = self.plan(snap, 'remove', target_id='first')
        self.assertEqual(operations['remove'], ['first'])
        updates = {item['id']: item for item in operations['updates']}
        self.assertNotIn('first', updates)
        self.assertEqual(updates['next']['result_rtf'], '[1]')
        self.assertEqual(updates['bib']['result_rtf'], '1. Beta study')

    def test_remove_last_citation_clears_existing_bibliography(self):
        operations, _ = self.plan(snapshot(citation('only', 10, PAPERS[0]), bibliography()),
                                  'remove', target_id='only')
        self.assertEqual(operations['remove'], ['only', 'bib'])
        self.assertEqual(operations['updates'], [])
        self.assertEqual(self.formatter.calls[-1][0], {})
        self.assertEqual(self.formatter.calls[-1][1], [])

    def test_bibliography_insert_and_update_all_existing_lists(self):
        operations, _ = self.plan(snapshot(citation('only', 10, PAPERS[0]), cursor=80), 'bibliography')
        self.assertEqual(operations['insert']['kind'], 'bibliography')
        self.assertEqual(operations['insert']['result_rtf'], '1. Alpha study')
        operations, _ = self.plan(snapshot(citation('only', 10, PAPERS[0]), bibliography(), bibliography('bib2', 150)),
                                  'bibliography')
        self.assertNotIn('insert', operations)
        self.assertEqual({f['id'] for f in operations['updates']}, {'only', 'bib', 'bib2'})

    def test_external_embedded_metadata_and_locator_survive_refresh(self):
        external = {'id': 'external', 'title': 'From a collaborator', 'year': '2019'}
        field = citation('external-field', 12, external)
        field['payload']['items'][0].update(locator='25', label='page', prefix='see ', suffix=' for details', **{'suppress-author': True})
        operations, _ = self.plan(snapshot(field, bibliography()))
        items, clusters, _, _ = self.formatter.calls[-1]
        self.assertEqual(items['external']['title'], external['title'])
        self.assertEqual(clusters[0]['items'][0]['locator'], '25')
        self.assertEqual(clusters[0]['items'][0]['prefix'], 'see ')
        self.assertTrue(clusters[0]['items'][0]['suppress-author'])
        self.assertEqual(operations['updates'][0]['payload']['items'][0]['itemData']['id'], 'external')

    def test_local_metadata_refreshes_embedded_record(self):
        stale = {**PAPERS[0], 'title': 'Old title'}
        operations, _ = self.plan(snapshot(citation('only', 10, stale)))
        self.assertEqual(operations['updates'][0]['payload']['items'][0]['itemData']['title'], 'Alpha study')

    def test_planning_does_not_mutate_inputs_or_alias_embedded_data(self):
        snap = snapshot(citation('one', 10, PAPERS[0]), bibliography(), cursor=30)
        original = deepcopy(snap)
        records = deepcopy(PAPERS)
        before_records = deepcopy(records)
        operations, _ = plan_changes(snap, records, 'style', 'insert', [records[1]], formatter=self.formatter)
        self.assertEqual(snap, original)
        self.assertEqual(records, before_records)
        operations['updates'][0]['payload']['items'][0]['itemData']['title'] = 'Altered result'
        self.assertEqual(snap, original)
        self.assertEqual(records, before_records)

    def test_duplicate_field_ids_are_rejected_before_formatting(self):
        for fields in ((citation('same', 1, PAPERS[0]), citation('same', 20, PAPERS[1])),
                       (citation('same', 1, PAPERS[0]), bibliography('same'))):
            with self.assertRaisesRegex(ValueError, '重复'):
                self.plan(snapshot(*fields))
        self.assertEqual(self.formatter.calls, [])

    def test_missing_target_and_invalid_selection_are_rejected(self):
        snap = snapshot(citation('one', 10, PAPERS[0]))
        for action in ('insert', 'replace'):
            with self.assertRaisesRegex(ValueError, '选择至少'):
                self.plan(snap, action)
        with self.assertRaisesRegex(ValueError, '发生变化'):
            self.plan(snap, 'replace', [PAPERS[1]], 'missing')
        with self.assertRaisesRegex(ValueError, '选择文档'):
            self.plan(snap, 'remove', target_id='missing')

    def test_no_insertion_into_existing_field_or_empty_bibliography(self):
        snap = snapshot(citation('one', 10, PAPERS[0]), cursor=11)
        with self.assertRaisesRegex(ValueError, '光标'):
            self.plan(snap, 'insert', [PAPERS[1]])
        with self.assertRaisesRegex(ValueError, '光标'):
            self.plan(snap, 'bibliography')
        with self.assertRaisesRegex(ValueError, '至少一处'):
            self.plan(snapshot(), 'bibliography')

    def test_missing_embedded_information_rejected(self):
        field = citation('one', 10, PAPERS[0])
        field['payload']['items'] = []
        with self.assertRaisesRegex(ValueError, '信息不完整'):
            self.plan(snapshot(field))
        field['payload']['items'] = [{'id': 'unknown'}]
        with self.assertRaisesRegex(ValueError, '缺少文献信息'):
            self.plan(snapshot(field))

    def test_note_style_rejected_and_style_id_updated(self):
        self.formatter.style_class = 'note'
        with self.assertRaisesRegex(ValueError, '脚注'):
            self.plan(snapshot(citation('one', 10, PAPERS[0])))
        self.formatter.style_class = 'in-text'
        operations, _ = self.plan(snapshot(citation('one', 10, PAPERS[0]), bibliography()))
        self.assertTrue(all(item['payload']['style_id'] == 'numeric-style' for item in operations['updates']))

    def test_label_uses_embedded_title(self):
        self.assertEqual(citation_label(citation('one', 10, PAPERS[0], PAPERS[1])), 'Alpha study; Beta study')


if __name__ == '__main__':
    unittest.main()
