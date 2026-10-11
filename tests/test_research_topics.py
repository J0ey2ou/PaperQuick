from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_topics import extract_topics, build_search_queries, topic_overview


class ResearchTopicsTests(unittest.TestCase):
    def test_explicit_keywords_and_phrases_lead(self):
        records = [
            {'id': '1', 'title': 'Dietary patterns and childhood obesity: a cohort study',
             'keywords': 'Dietary patterns; childhood obesity; 儿童营养',
             'abstract': 'Our research study analyzed dietary patterns among children.'},
            {'id': '2', 'title': 'Dietary patterns in adolescent health', 'keywords': ['Dietary patterns', 'Nutrition']},
        ]
        topics = extract_topics(records)
        self.assertEqual(topics[0]['term'], 'dietary patterns')
        self.assertEqual(topics[0]['papers'], 2)
        self.assertIn('文献关键词', topics[0]['source'])
        self.assertIn('儿童营养', [item['term'] for item in topics])
        self.assertNotIn('research', [item['term'] for item in topics])
        self.assertNotIn('cohort study', [item['term'] for item in topics])

    def test_repeated_papers_and_metadata_noise_do_not_inflate_topics(self):
        first = {'id': '1', 'doi': 'https://doi.org/10.1000/A', 'title': 'Dietary patterns and nutrition',
                 'notes': 'Times Cited:999; Artificial contaminant; DOI 10.1000/pollution',
                 'year': '2026', 'keywords': 'Dietary patterns; 2026; DOI:10.1000/other'}
        second = {'id': '2', 'doi': '10.1000/a', 'title': first['title'], 'keywords': 'Dietary patterns; 儿童营养'}
        overview = topic_overview([first, second, dict(first)])
        self.assertEqual(overview['paper_count'], 1)
        self.assertTrue(all(item['papers'] == 1 for item in overview['keywords']))
        labels = ' '.join(item['term'] for item in overview['keywords'])
        self.assertIn('儿童营养', labels)
        for forbidden in ('artificial', 'contaminant', 'cited', '2026', 'pollution', 'doi'):
            self.assertNotIn(forbidden, labels)

    def test_repetition_inside_one_abstract_has_no_extra_weight(self):
        record = {'title': 'Nutrition', 'abstract': 'Dietary patterns. '}
        once = extract_topics([record])
        repeated = extract_topics([{**record, 'abstract': record['abstract'] * 40}])
        self.assertEqual(once, repeated)

    def test_phrases_do_not_join_across_punctuation_or_stop_words(self):
        terms = {item['term'] for item in extract_topics([{'title': 'Obesity. Nutrition and diabetes'}], 30)}
        self.assertIn('obesity', terms)
        self.assertNotIn('obesity nutrition', terms)
        self.assertNotIn('nutrition diabetes', terms)

    def test_missing_information_is_a_natural_empty_state(self):
        self.assertEqual(extract_topics([{'notes': 'Times Cited: 100'}]), [])
        self.assertEqual(topic_overview([])['paper_count'], 0)
        self.assertTrue(all(not value for value in build_search_queries([]).values()))
        self.assertIn('补充标题', topic_overview([{'title': 'Study analysis 2026'}])['description'])
        self.assertEqual(extract_topics([{'title': 'Nutrition'}], 0), [])

    def test_query_fields_use_all_user_selected_terms(self):
        terms = ['Dietary patterns', 'childhood obesity', 'nutrition', 'diabetes']
        queries = build_search_queries(terms)
        self.assertEqual(queries['pubmed'], '(' + ' OR '.join(f'"{term}"[Title/Abstract]' for term in terms) + ')')
        self.assertEqual(queries['wos'], 'TS=("Dietary patterns" OR "childhood obesity" OR "nutrition" OR "diabetes")')
        self.assertEqual(queries['europepmc'].count('TITLE_ABS:'), 4)
        self.assertIn('"diabetes"', queries['scholar'])

    def test_queries_ignore_invalid_labels_and_cannot_add_operators(self):
        queries = build_search_queries(['', '  ', '2026', '"obesity") OR TITLE_ABS:(cancer*',
                                        'children[All Fields] NOT adults', '肥胖；糖尿病'])
        self.assertNotIn('All Fields', queries['pubmed'])
        self.assertNotIn('NOT', queries['pubmed'])
        self.assertNotIn('*', queries['europepmc'])
        self.assertEqual(queries['europepmc'].count('('), 1)
        self.assertEqual(queries['europepmc'].count(')'), 1)
        self.assertIn('"obesity cancer"', queries['scholar'])
        self.assertNotIn('"2026"', queries['scholar'])

    def test_queries_deduplicate_limit_and_keep_full_words(self):
        terms = ['Dietary patterns', 'dietary PATTERNS'] + [f'keyword{i}' for i in range(15)]
        queries = build_search_queries(terms)
        self.assertEqual(queries['pubmed'].count('[Title/Abstract]'), 12)
        self.assertEqual(queries['scholar'].count('Dietary patterns'), 1)
        self.assertTrue(all(not value for value in build_search_queries(['x' * 200]).values()))
        self.assertEqual(build_search_queries('obesity; diabetes')['scholar'], '"obesity" OR "diabetes"')

    def test_automatic_overview_starts_with_three_terms_only(self):
        overview = topic_overview([{'title': 'Nutrition and health', 'keywords': 'obesity; diabetes; asthma; nutrition; metabolism'}])
        self.assertGreaterEqual(len(overview['keywords']), 4)
        self.assertEqual(overview['queries']['pubmed'].count('[Title/Abstract]'), 3)
        self.assertNotIn('AI', overview['description'])


if __name__ == '__main__':
    unittest.main()
