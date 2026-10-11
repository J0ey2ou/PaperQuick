import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from citation_metadata import MetadataError, fetch_doi_metadata, quality_warnings, to_csl
from library_core import Library


DOI = '10.1038/s41586-021-03819-2'
WORK = {
    'DOI': DOI.upper(), 'type': 'journal-article',
    'title': ['Highly accurate <i>protein</i> structure prediction with AlphaFold'],
    'author': [{'given': 'John', 'family': 'Jumper'}, {'given': 'Richard', 'family': 'Evans'},
               {'name': 'Research Consortium'}],
    'container-title': ['Nature'], 'volume': '596', 'issue': '7873',
    'page': '583-589', 'publisher': 'Springer Science and Business Media LLC',
    'issued': {'date-parts': [[2021, 7, 15]]},
    'abstract': '<jats:p>A <jats:italic>protein</jats:italic> study &amp; example.</jats:p>',
    'URL': 'https://doi.org/' + DOI,
}


def response(work=WORK, **kwargs):
    return io.BytesIO(json.dumps({'status': 'ok', 'message': work, **kwargs}).encode())


class CSLMetadataTests(unittest.TestCase):
    def test_full_structured_metadata_and_stable_identity(self):
        record = {'id': 'paper-42', 'title': 'An example', 'authors': 'Wrong surname, et al',
                  'authors_structured': [{'family': 'van Gogh', 'given': 'Anna'}, {'literal': 'World Health Organization'}],
                  'doi': 'HTTPS://DOI.ORG/' + DOI.upper(), 'year': '2021', 'venue': 'Nature',
                  'pages': '583-589', 'volume': 596, 'issue': '7873', 'notes': 'Private notes',
                  'attachments': [{'path': 'private.pdf'}]}
        original = copy.deepcopy(record)
        item = to_csl(record)
        self.assertEqual(item['id'], 'paper-42')
        self.assertEqual(item['DOI'], DOI)
        self.assertEqual(item['author'], record['authors_structured'])
        self.assertEqual(item['issued'], {'date-parts': [[2021]]})
        self.assertEqual(item['volume'], '596')
        self.assertNotIn('notes', item)
        self.assertNotIn('attachments', item)
        self.assertEqual(record, original)
        record['title'] = 'Corrected title'
        self.assertEqual(to_csl(record)['id'], item['id'])

    def test_ambiguous_comma_search_authors_are_not_invented(self):
        raw = 'John Jumper, Richard Evans, Alexander Pritzel'
        item = to_csl({'authors': raw})
        self.assertEqual(item['author'], [{'literal': raw}])
        self.assertTrue(any('姓与名' in text for text in quality_warnings({'authors': raw})))

    def test_endnote_explicit_author_separators(self):
        record = {'authors': 'Jumper, John\nEvans, Richard; 王, 小明; World Health Organization,'}
        item = to_csl(record)
        self.assertEqual(item['author'][:3], [{'family': 'Jumper', 'given': 'John'},
                                             {'family': 'Evans', 'given': 'Richard'},
                                             {'family': '王', 'given': '小明'}])
        self.assertEqual(item['author'][3], {'literal': 'World Health Organization,'})

    def test_no_surname_guess_from_full_name_or_chinese(self):
        for raw in ('John van den Berg', '张三', 'World Health Organization', 'Smith, Jane'):
            self.assertEqual(to_csl({'authors': raw})['author'], [{'literal': raw}])

    def test_missing_metadata_is_not_fabricated(self):
        item = to_csl({'id': 0})
        self.assertEqual(item, {'id': '0', 'type': 'article-journal'})
        hints = quality_warnings({})
        self.assertTrue(any('标题' in w for w in hints))
        self.assertTrue(any('作者' in w for w in hints))
        self.assertTrue(any('年份' in w for w in hints))

    def test_article_number_dates_and_types(self):
        item = to_csl({'type': 'journal-article', 'article_number': 'e101234',
                       'issued': {'date-parts': [[2024, 2, 29]]}, 'year': '2023'})
        self.assertEqual(item['page'], 'e101234')
        self.assertEqual(item['issued']['date-parts'], [[2024, 2, 29]])
        self.assertFalse(any('页码' in w for w in quality_warnings({'article_number': 'e101234'})))
        self.assertEqual(to_csl({'type': 'book-chapter'})['type'], 'chapter')
        self.assertEqual(to_csl({'type': 'proceedings-article'})['type'], 'paper-conference')
        self.assertEqual(to_csl({'issued': {'date-parts': [[2024, 2, 31]]}, 'year': '2020'})['issued'],
                         {'date-parts': [[2020]]})
        self.assertNotIn('issued', to_csl({'year': 'in press'}))

    def test_fallback_id_is_deterministic_and_doi_normalized(self):
        record = {'title': 'Example', 'authors': 'Example, A', 'year': '2020'}
        self.assertEqual(to_csl(record)['id'], to_csl(dict(reversed(list(record.items()))))['id'])
        self.assertEqual(to_csl({'doi': DOI})['id'], to_csl({'DOI': DOI.upper()})['id'])

    def test_unsafe_doi_is_omitted_and_warned(self):
        record = {'doi': 'https://example.com/private'}
        self.assertNotIn('DOI', to_csl(record))
        self.assertTrue(any('DOI' in s for s in quality_warnings(record)))


class CrossrefMetadataTests(unittest.TestCase):
    @patch('citation_metadata.urlopen')
    def test_exact_lookup_complete_authors_and_markup(self, opener):
        opener.return_value = response()
        result = fetch_doi_metadata('https://doi.org/' + DOI.upper())
        self.assertEqual(result['doi'], DOI)
        self.assertEqual(result['title'], 'Highly accurate protein structure prediction with AlphaFold')
        self.assertEqual(len(result['authors_structured']), 3)
        self.assertIn('Jumper, John', result['authors'])
        self.assertEqual(result['abstract'], 'A protein study & example.')
        self.assertEqual(result['year'], '2021')
        self.assertNotIn('notes', result)
        self.assertNotIn('id', result)
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.crossref.org/works/10.1038%2Fs41586-021-03819-2')
        self.assertEqual(opener.call_args.kwargs['timeout'], 12)

    @patch('citation_metadata.urlopen')
    def test_wrong_doi_never_accepted(self, opener):
        opener.return_value = response({**WORK, 'DOI': '10.5555/wrong-paper'})
        with self.assertRaisesRegex(MetadataError, '不一致'):
            fetch_doi_metadata(DOI)

    @patch('citation_metadata.urlopen')
    def test_missing_metadata_does_not_erase_existing_library_fields(self, opener):
        opener.return_value = response({'DOI': DOI, 'title': ['Correct title']})
        result = fetch_doi_metadata(DOI)
        self.assertNotIn('authors', result)
        self.assertNotIn('type', result)
        self.assertNotIn('year', result)
        temp_root = Path(__file__).resolve().parents[1] / 'build' / 'citation-metadata-tests'
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            lib = Library(Path(directory))
            try:
                rid = lib.save({'doi': DOI, 'title': 'Old title', 'notes': 'My private notes',
                                'authors': 'Existing author', 'year': '2021', 'type': 'book'})
                lib.save(result, rid=rid)
                saved = lib.get(rid)
                self.assertEqual(saved['notes'], 'My private notes')
                self.assertEqual(saved['authors'], 'Existing author')
                self.assertEqual(saved['year'], '2021')
                self.assertEqual(saved['type'], 'book')
                self.assertEqual(saved['title'], 'Correct title')
            finally:
                lib.close()

    @patch('citation_metadata.urlopen')
    def test_invalid_inputs_do_not_request_network(self, opener):
        for value in ('', 'not-a-doi', 'http://localhost/private', '10.1234/bad space'):
            with self.assertRaises(MetadataError):
                fetch_doi_metadata(value)
        opener.assert_not_called()

    @patch('citation_metadata.urlopen')
    def test_bounded_response_and_invalid_json(self, opener):
        for body in (b'x' * (4 * 1024 * 1024 + 1), b'<html>error</html>', b'\xff', b'[]'):
            opener.return_value = io.BytesIO(body)
            with self.assertRaises(MetadataError):
                fetch_doi_metadata(DOI)

    @patch('citation_metadata.urlopen')
    def test_readable_network_errors(self, opener):
        for failure, hint in ((HTTPError('url', 404, 'missing', {}, None), '尚未收录'),
                              (HTTPError('url', 429, 'busy', {}, None), '正忙'),
                              (URLError('offline'), '检查网络'), (TimeoutError(), '检查网络')):
            opener.side_effect = failure
            with self.assertRaisesRegex(MetadataError, hint):
                fetch_doi_metadata(DOI)


if __name__ == '__main__':
    unittest.main()
