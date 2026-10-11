import copy
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from citation_tracking import find_related


SEED = {'source': 'MED', 'id': '101', 'doi': '10.1234/seed', 'title': 'Seed publication', 'pubYear': '2026'}


class CitationTests(unittest.TestCase):
    def reply(self, references=(), citing=(), extra=(), fail=None, total=None):
        def api(path, **params):
            if path == 'search' and params['query'].startswith(('DOI:', 'TITLE:')):
                return {'hitCount': 1, 'resultList': {'result': [SEED]}}
            if path == 'search':
                return {'hitCount': len(extra), 'resultList': {'result': list(extra)}}
            if fail and path.endswith(fail):
                raise urllib.error.HTTPError('https://www.ebi.ac.uk/', 429, 'Too many', {}, None)
            if path.endswith('references'):
                return {'hitCount': total if total is not None else len(references), 'referenceList': {'reference': list(references)}}
            if path.endswith('citations'):
                return {'hitCount': total if total is not None else len(citing), 'citationList': {'citation': list(citing)}}
            raise AssertionError(path)
        return api

    def test_both_directions_filter_library_and_keep_provenance(self):
        references = [{'source': 'MED', 'id': '201', 'title': 'Already have this', 'doi': '10.1234/old'},
                      {'source': 'MED', 'id': '202', 'title': 'New background work', 'doi': '10.1234/ref'}]
        citing = [{'source': 'MED', 'id': '301', 'title': 'New followup work', 'doi': '10.1234/cite'}]
        library = [{'title': 'Edited existing title', 'doi': 'https://doi.org/10.1234/OLD', 'notes': 'Keep'}]
        original = copy.deepcopy(library)
        with patch('citation_tracking._get_json', side_effect=self.reply(references, citing)):
            result = find_related(SEED, library)
        self.assertEqual(len(result['items']), 2)
        self.assertEqual({row['relation'] for row in result['items']}, {'reference', 'citing'})
        self.assertTrue(all(row['seed_doi'] == SEED['doi'] for row in result['items']))
        self.assertTrue(all(row['source'] == 'Europe PMC' for row in result['items']))
        self.assertEqual(library, original)

    def test_duplicate_in_both_directions_has_both_provenances(self):
        item = {'source': 'MED', 'id': '201', 'title': 'Shared work', 'doi': '10.1234/shared'}
        with patch('citation_tracking._get_json', side_effect=self.reply([item], [item])):
            result = find_related(SEED, [])
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['relations'], ['reference', 'citing'])

    def test_distinct_dois_with_same_title_are_not_filtered(self):
        item = {'source': 'MED', 'id': '201', 'title': 'Same title', 'doi': '10.1234/new'}
        with patch('citation_tracking._get_json', side_effect=self.reply([item])):
            result = find_related(SEED, [{'title': 'Same title', 'doi': '10.1234/old'}])
        self.assertEqual(len(result['items']), 1)

    def test_missing_doi_uses_title_deduplication(self):
        item = {'source': 'MED', 'id': '201', 'title': 'Shared title.'}
        with patch('citation_tracking._get_json', side_effect=self.reply([item])):
            result = find_related(SEED, [{'title': 'shared TITLE', 'doi': ''}])
        self.assertEqual(result['items'], [])

    def test_identifier_enrichment_matches_doi_despite_edited_title(self):
        basic = {'source': 'MED', 'id': '201', 'title': 'Original title'}
        core = dict(basic, doi='10.1234/collected', abstractText='An abstract')
        with patch('citation_tracking._get_json', side_effect=self.reply([basic], extra=[core])):
            result = find_related(SEED, [{'title': 'Completely edited title', 'doi': '10.1234/collected'}])
        self.assertEqual(result['items'], [])

    def test_one_direction_failure_preserves_other_results(self):
        item = {'source': 'MED', 'id': '201', 'title': 'Background work'}
        with patch('citation_tracking._get_json', side_effect=self.reply([item], fail='citations')):
            result = find_related(SEED, [])
        self.assertEqual(len(result['items']), 1)
        self.assertIn('引用它的文献暂未查完', result['message'])
        self.assertIn('较忙', result['message'])
        self.assertNotIn('HTTPError', result['message'])

    def test_limits_are_visible_and_directions_are_balanced(self):
        references = [{'title': f'Background {i}', 'doi': f'10.1234/r{i}'} for i in range(4)]
        citing = [{'title': f'Followup {i}', 'doi': f'10.1234/c{i}'} for i in range(4)]
        with patch('citation_tracking._get_json', side_effect=self.reply(references, citing, total=200)):
            result = find_related(SEED, [], limit=4)
        self.assertEqual(len(result['items']), 4)
        self.assertEqual([item['relation'] for item in result['items']], ['reference', 'citing', 'reference', 'citing'])
        self.assertTrue(result['truncated'])
        self.assertIn('更多', result['message'])

    def test_no_cover_and_wrong_doi_never_use_approximate_paper(self):
        wrong = dict(SEED, doi='10.1234/different')
        with patch('citation_tracking._get_json', return_value={'resultList': {'result': [wrong]}}) as api:
            result = find_related(SEED, [])
        self.assertEqual(api.call_count, 1)
        self.assertEqual(result['items'], [])
        self.assertIn('未能', result['message'])

    def test_ambiguous_title_requires_confirmed_identity(self):
        first = dict(SEED, doi='10.1234/first')
        second = dict(SEED, id='102', doi='10.1234/second')
        with patch('citation_tracking._get_json', return_value={'resultList': {'result': [first, second]}}):
            result = find_related({'title': SEED['title']}, [])
        self.assertEqual(result['items'], [])

    def test_network_failure_is_customer_facing(self):
        with patch('citation_tracking._get_json', side_effect=urllib.error.URLError('debug socket detail')):
            result = find_related(SEED, [])
        self.assertEqual(result['items'], [])
        self.assertIn('网络', result['message'])
        self.assertNotIn('socket', result['message'])

    def test_enrichment_failure_keeps_title_and_article_page(self):
        normal = self.reply([{'source': 'MED', 'id': '201', 'title': 'Useful paper'}])
        def api(path, **params):
            if path == 'search' and params['query'].startswith('(EXT_ID:'):
                raise TimeoutError('enrichment timed out')
            return normal(path, **params)
        with patch('citation_tracking._get_json', side_effect=api):
            result = find_related(SEED, [])
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['url'], 'https://europepmc.org/article/MED/201')
        self.assertIn('暂未补全', result['message'])


if __name__ == '__main__':
    unittest.main()
