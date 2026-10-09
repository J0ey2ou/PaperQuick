from dataclasses import asdict
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from library_core import Library
from download_actions import resolve_download,download_page
from email.message import Message
from unittest.mock import MagicMock
from paper_finder import Paper, Link, Result
from test_library import pdf


class DownloadActionTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'build' / 'download-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.lib = Library(Path(self.temp.name) / 'store')
        self.project = self.lib.create_project('课题下载')
        self.pdf = Path(self.temp.name) / 'sample.pdf'
        pdf(self.pdf)

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def save(self, paper):
        return self.lib.save(asdict(paper), self.project)

    def test_collect_pdf_immediately_archives_with_naming(self):
        rid = self.save(Paper('Research title', '10.1000/a', year='2026', links=[Link('PDF', 'https://example.org/a.pdf', 'pdf', 'test')]))
        with patch('download_actions.find_papers') as lookup, patch('download_actions.download_pdf', side_effect=lambda lib, r, u: lib.attach(r, self.pdf)) as download:
            result = resolve_download(self.lib, rid)
        self.assertEqual(result['kind'], 'downloaded')
        self.assertEqual(download.call_args.args[2], 'https://example.org/a.pdf')
        lookup.assert_not_called()
        self.assertIn('课题下载', result['path'])
        self.assertTrue(Path(result['path']).is_file())
        self.assertEqual(self.lib.get(rid)['primary_project'], self.project)

    def test_publisher_only_opens_immediately_without_lookup(self):
        rid = self.save(Paper('Title', '10.1000/a', links=[Link('Publisher', 'https://example.org/paper', 'publisher', 'test')]))
        with patch('download_actions.find_papers') as lookup:
            result = resolve_download(self.lib, rid)
        self.assertEqual(result['url'], 'https://example.org/paper')
        self.assertEqual(result['kind'], 'browser')
        lookup.assert_not_called()

    def test_right_click_doi_lookup_preserves_notes_and_record_identity(self):
        rid = self.save(Paper('10.1000/a', '10.1000/a'))
        self.lib.save({'notes': 'User notes', 'status': '已读'}, rid=rid)
        fresh = Paper('Full research title', '10.1000/a', year='2026', links=[Link('PDF', 'https://example.org/b.pdf', 'pdf', 'test')])
        with patch('download_actions.find_papers', return_value=Result('doi', [fresh])), patch('download_actions.download_pdf', side_effect=lambda lib, r, u: lib.attach(r, self.pdf)):
            result = resolve_download(self.lib, rid, lookup=True)
        record = self.lib.get(rid)
        self.assertEqual(result['kind'], 'downloaded')
        self.assertEqual(record['title'], fresh.title)
        self.assertEqual(record['notes'], 'User notes')
        self.assertEqual(record['status'], '已读')
        self.assertEqual(len(self.lib.records()), 1)

    def test_mismatch_never_downloads_or_replaces_metadata(self):
        rid = self.save(Paper('Original title', '10.1000/a'))
        wrong = Paper('Original title', '10.1000/b', links=[Link('PDF', 'https://example.org/wrong.pdf', 'pdf', 'test')])
        with patch('download_actions.find_papers', return_value=Result('doi', [wrong])), patch('download_actions.download_pdf') as download:
            result = resolve_download(self.lib, rid, lookup=True)
        download.assert_not_called()
        self.assertEqual(result['url'], 'https://doi.org/10.1000/a')
        self.assertEqual(self.lib.get(rid)['doi'], '10.1000/a')

    def test_ambiguous_same_title_dois_require_review(self):
        rid = self.save(Paper('Shared title'))
        with patch('download_actions.find_papers', return_value=Result('title', [Paper('Shared title', '10.1000/a'), Paper('Shared title', '10.1000/b')])), patch('download_actions.download_pdf') as download:
            result = resolve_download(self.lib, rid, lookup=True)
        self.assertEqual(result['kind'], 'missing')
        download.assert_not_called()

    def test_download_failure_returns_publisher_for_manual_download(self):
        rid = self.save(Paper('Title', '10.1000/a', links=[Link('PDF', 'https://example.org/a.pdf', 'pdf', 'test')]))
        with patch('download_actions.download_pdf', side_effect=ValueError('Login required')):
            result = resolve_download(self.lib, rid)
        self.assertEqual(result['kind'], 'browser')
        self.assertEqual(result['url'], 'https://doi.org/10.1000/a')
        self.assertIn('Login required', result['issue'])

    def test_existing_pdf_is_reused(self):
        rid = self.save(Paper('Title'))
        self.lib.attach(rid, self.pdf)
        with patch('download_actions.find_papers') as lookup, patch('download_actions.download_pdf') as download:
            result = resolve_download(self.lib, rid, lookup=True)
        self.assertEqual(result['kind'], 'existing')
        lookup.assert_not_called()
        download.assert_not_called()

    def test_selected_pdf_link_has_priority(self):
        rid = self.save(Paper('Title', links=[Link('one', 'https://example.org/one.pdf', 'pdf', 'test'), Link('two', 'https://example.org/two.pdf', 'pdf', 'test')]))
        with patch('download_actions.download_pdf', return_value=self.pdf) as download:
            resolve_download(self.lib, rid, preferred_url='https://example.org/two.pdf')
        self.assertEqual(download.call_args.args[2], 'https://example.org/two.pdf')

    def test_browser_download_opens_pdf_even_when_already_archived(self):
        rid=self.save(Paper('Title','10.1000/a',links=[Link('PDF','https://example.org/direct.pdf','pdf','test')]))
        self.lib.attach(rid,self.pdf)
        with patch('download_actions.download_pdf') as download,patch('download_actions.find_papers') as lookup:
            result=resolve_download(self.lib,rid,lookup=True,open_page=True)
        self.assertEqual(result['url'],'https://example.org/direct.pdf')
        self.assertEqual(result['kind'],'browser');download.assert_not_called();lookup.assert_not_called()

    def test_article_metadata_resolves_real_pdf_but_rejects_wrong_doi(self):
        headers=Message();headers['Content-Type']='text/html; charset=utf-8'
        response=MagicMock();response.__enter__.return_value=response;response.headers=headers
        response.geturl.return_value='https://publisher.example/article/a'
        opener=MagicMock();opener.open.return_value=response
        for doi,expected in [('10.1000/a','https://publisher.example/article/download.pdf'),('10.1000/wrong','https://publisher.example/article/a')]:
            response.read.return_value=f'<meta name="citation_doi" content="{doi}"><meta name="citation_pdf_url" content="download.pdf">'.encode()
            with patch('download_actions.public_url'),patch('download_actions.urllib.request.build_opener',return_value=opener):
                result=download_page({'doi':'10.1000/a'},[])
            self.assertEqual(result,expected)


if __name__ == '__main__':
    unittest.main()
