"""Regression checks for progressive results and bounded waits, without real network."""
import threading
import time
import unittest
from unittest.mock import patch

import paper_finder as finder
from test_finder import DOI, TITLE, CR, PMC


class SpeedTests(unittest.TestCase):
    def test_no_early_candidate_allows_slow_title_source_to_finish(self):
        def delayed_title(query):
            time.sleep(.07)
            return [finder.crossref_paper(CR)]

        with patch.object(finder, 'search_crossref', side_effect=delayed_title), \
             patch.object(finder, 'search_pmc', return_value=[]), \
             patch.object(finder, 'search_arxiv', return_value=[]), \
             patch.object(finder, 'get_json', return_value={}), \
             patch.object(finder, 'SEARCH_BUDGET', .02), \
             patch.object(finder, 'BACKGROUND_BUDGET', .4):
            result = finder.find_papers(TITLE)
        self.assertEqual(result.papers[0].title, TITLE)

    def test_doi_pdf_arrives_while_metadata_is_blocked_and_snapshots_stay_fixed(self):
        release = threading.Event()
        finished = threading.Event()
        snapshots = []

        def slow_metadata(doi):
            try:
                release.wait(2)
                return finder.crossref_paper(CR), ""
            finally:
                finished.set()

        with patch.object(finder, "lookup_doi", side_effect=slow_metadata), \
             patch.object(finder, "search_pmc", return_value=[PMC]), \
             patch.object(finder, "get_json", return_value={}), \
             patch.object(finder, "BACKGROUND_BUDGET", .15):
            start = time.monotonic()
            try:
                result = finder.find_papers(DOI, on_result=lambda r: snapshots.append((time.monotonic() - start, r)))
                elapsed = time.monotonic() - start
                self.assertLess(elapsed, .8)
                self.assertLess(snapshots[0][0], .1)
                self.assertEqual(snapshots[0][1].papers[0].title, DOI)
                self.assertEqual(finder.automatic_target(snapshots[0][1]), 'https://doi.org/' + DOI)
                self.assertTrue(any(finder.automatic_target(r) == 'https://example.org/open.pdf' for _, r in snapshots))
                self.assertTrue(any('响应较慢' in note for note in result.notes))
                delivered = result.to_dict()
            finally:
                release.set()
                self.assertTrue(finished.wait(2))
        self.assertEqual(result.to_dict(), delivered)
        self.assertEqual(snapshots[0][1].papers[0].title, DOI)

    def test_title_partial_cannot_auto_open_before_other_candidates_arrive(self):
        seen = []
        with patch.object(finder, 'search_crossref', return_value=[finder.crossref_paper(CR)]), \
             patch.object(finder, 'search_pmc', return_value=[dict(PMC, doi='10.1000/other')]), \
             patch.object(finder, 'search_arxiv', return_value=[]), \
             patch.object(finder, 'get_json', return_value={}):
            result = finder.find_papers(TITLE, on_result=seen.append)
        self.assertTrue(seen)
        self.assertTrue(all(not finder.automatic_target(r) for r in seen))
        self.assertEqual(len(result.papers), 2)
        self.assertFalse(finder.automatic_target(result))

    def test_existing_oa_result_skips_repeated_doi_queries(self):
        with patch.object(finder, 'search_crossref', return_value=[finder.crossref_paper(CR)]), \
             patch.object(finder, 'search_pmc', return_value=[PMC]) as pmc, \
             patch.object(finder, 'search_arxiv', return_value=[]), \
             patch.object(finder, 'get_json') as extra:
            result = finder.find_papers(TITLE)
        self.assertEqual(pmc.call_count, 1)
        extra.assert_not_called()
        self.assertEqual(finder.automatic_target(result), 'https://example.org/open.pdf')

    def test_arxiv_pdf_available_before_metadata(self):
        seen = []
        with patch.object(finder, 'search_arxiv', return_value=[]), \
             patch.object(finder, 'get_json') as other:
            result = finder.find_papers('arXiv:1706.03762', on_result=seen.append)
        self.assertEqual(finder.automatic_target(seen[0]), 'https://arxiv.org/pdf/1706.03762')
        self.assertEqual(finder.automatic_target(result), 'https://arxiv.org/pdf/1706.03762')
        other.assert_not_called()


if __name__ == '__main__':
    unittest.main()
