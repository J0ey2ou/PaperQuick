import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paper_finder as finder

DOI = "10.1038/s41586-021-03819-2"
TITLE = "Highly accurate protein structure prediction with AlphaFold"
CR = {"DOI": DOI, "title": [TITLE], "author": [{"given": "John", "family": "Jumper"}], "published": {"date-parts": [[2021, 7, 15]]}, "container-title": ["Nature"], "link": [{"URL": "https://publisher.test/paper.pdf", "content-type": "application/pdf"}]}
PMC = {"title": TITLE, "doi": DOI, "pubYear": "2021", "pmcid": "PMC8371605", "isOpenAccess": "Y", "fullTextUrlList": {"fullTextUrl": [{"availabilityCode": "OA", "documentStyle": "pdf", "url": "https://example.org/open.pdf"}, {"availabilityCode": "S", "documentStyle": "pdf", "url": "https://example.org/paywall.pdf"}]}}
ATOM = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1706.03762v7</id><title>Attention Is All You Need</title><published>2017-06-12T00:00:00Z</published><author><name>Ashish Vaswani</name></author></entry></feed>'''


class FinderTests(unittest.TestCase):
    def test_doi_citation_punctuation_and_encoded_link(self):
        self.assertEqual(finder.extract_dois("DOI: https://doi.org/10.1038%2Fs41586-021-03819-2。"), [DOI])
        self.assertEqual(finder.extract_dois("(10.1002/(SICI)1234)."), ["10.1002/(SICI)1234"])

    def test_doi_case_deduplication(self):
        self.assertEqual(finder.extract_dois("10.1000/ABC 10.1000/abc"), ["10.1000/ABC"])

    def test_doi_url_tracking_parameters_not_part_of_identifier(self):
        self.assertEqual(finder.extract_dois("https://doi.org/" + DOI + "?utm_source=wechat#references"), [DOI])

    @patch("paper_finder.search_arxiv", return_value=[finder.Paper("Attention Is All You Need")])
    def test_arxiv_registered_doi_resolves_via_arxiv(self, _):
        with patch("paper_finder.get_json", side_effect=AssertionError("Crossref not required")):
            paper, note = finder.lookup_doi("10.48550/arXiv.1706.03762")
        self.assertEqual(paper.title, "Attention Is All You Need")
        self.assertEqual(paper.doi, "10.48550/arXiv.1706.03762")
        self.assertFalse(note)

    def test_title_html_normalization(self):
        self.assertEqual(finder.similarity("A &amp; B: <i>paper</i>.", "a & b paper"), 1)
        self.assertEqual(finder.similarity("", "paper"), 0)

    def test_dangerous_protocol_not_a_link(self):
        for url in ["javascript:alert(1)", "file:///D:/secret", "https://user:password@example.com"]:
            self.assertFalse(finder.safe_link(url))

    @patch("paper_finder.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))])
    def test_local_page_rejected(self, _):
        with self.assertRaises(finder.LookupError):
            finder.public_url("http://localhost/article")

    @patch("paper_finder.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.1.2.3", 80))])
    def test_redirect_into_private_network_rejected(self, _):
        with self.assertRaises(finder.LookupError):
            finder.PublicRedirect().redirect_request(None, None, 302, "", {}, "http://example.com/private")

    def test_parser_ignores_script_dois(self):
        parser = finder.ArticleParser()
        parser.feed('<script>var doi="10.1000/wrong";</script><meta property="og:title" content="推送"><p>10.1000/right</p>')
        self.assertEqual(parser.title, "推送")
        self.assertEqual(finder.extract_dois(" ".join(parser.text)), ["10.1000/right"])

    def test_crossref_pdf_not_claimed_open(self):
        paper = finder.crossref_paper(CR)
        self.assertTrue(paper.links)
        self.assertTrue(all(link.kind == "publisher" for link in paper.links))
        self.assertEqual((paper.title, paper.year, paper.authors), (TITLE, "2021", "John Jumper"))

    def test_pmc_only_open_access_links(self):
        paper = finder.pmc_paper(PMC)
        self.assertTrue(any(link.kind == "pdf" for link in paper.links))
        self.assertFalse(any("paywall" in link.url for link in paper.links))
        self.assertTrue(any("PMC8371605" in link.url for link in paper.links))

    @patch("paper_finder.fetch", return_value=(ATOM, "", "application/atom+xml"))
    def test_arxiv_preprint_labeled(self, _):
        with patch("paper_finder._arxiv_last", 0):
            papers = finder.search_arxiv(ident="1706.03762")
        self.assertEqual(papers[0].title, "Attention Is All You Need")
        self.assertEqual(papers[0].links[0].url, "https://arxiv.org/pdf/1706.03762v7")
        self.assertIn("预印本", papers[0].links[0].note)

    def test_candidate_rank_dedup_and_no_false_exact_match(self):
        a = finder.crossref_paper(CR)
        b = finder.pmc_paper(PMC)
        c = finder.Paper("Unrelated title", "10.1000/x")
        papers = finder.merge_papers([c, b, a], TITLE)
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0].doi, DOI)
        self.assertIn("请核对", papers[0].match)
        self.assertTrue(any(link.url == "https://publisher.test/paper.pdf" for link in papers[0].links))

    @patch("paper_finder.enrich", return_value=[])
    @patch("paper_finder.get_json", return_value={"message": CR})
    def test_direct_doi_does_not_fetch_publisher_page(self, _, __):
        with patch("paper_finder.fetch", side_effect=AssertionError("not required")):
            result = finder.find_papers("https://doi.org/" + DOI)
        self.assertEqual(result.papers[0].title, TITLE)
        self.assertEqual(result.papers[0].match, "标识符匹配")

    @patch("paper_finder.enrich", return_value=[])
    @patch("paper_finder.get_json", return_value={"message": CR})
    def test_page_citation_metadata_precedes_references(self, _, __):
        page = '<meta name="citation_doi" content="' + DOI + '"><p>References: 10.1000/another</p>'
        with patch("paper_finder.fetch", return_value=(page, "https://example.org/article", "text/html")):
            result = finder.find_papers("https://example.org/article")
        self.assertEqual(len(result.papers), 1)
        self.assertEqual(result.papers[0].doi, DOI)

    def test_wechat_verification_gives_actionable_error(self):
        with patch("paper_finder.fetch", return_value=("<p>环境异常，完成验证后继续</p>", "", "text/html")):
            with self.assertRaisesRegex(finder.LookupError, "英文论文标题"):
                finder.find_papers("https://mp.weixin.qq.com/s/test")

    def test_wechat_recovery_keeps_original_url(self):
        url = "https://mp.weixin.qq.com/s/test"
        with patch("paper_finder.fetch", return_value=("<p>环境异常</p>", url, "text/html")):
            with self.assertRaises(finder.BrowserPageRequired) as caught:
                finder.find_papers(url)
        self.assertEqual(caught.exception.url, url)

    @patch("paper_finder.enrich", return_value=[])
    @patch("paper_finder.get_json", return_value={"message": CR})
    def test_real_article_mentioning_verification_is_not_blocked(self, *_):
        page = '<meta property="og:title" content="科学论文"><div id="js_content"><p>文章讨论“环境异常”的验证情境。</p><p>' + ('正文说明 ' * 40) + DOI + '</p></div><aside>10.1000/unrelated</aside>'
        with patch("paper_finder.fetch", return_value=(page, "https://mp.weixin.qq.com/s/test", "text/html")):
            result = finder.find_papers("https://mp.weixin.qq.com/s/test")
        self.assertEqual(len(result.papers), 1)
        self.assertEqual(result.papers[0].doi, DOI)

    def test_auto_open_prefers_open_pdf_for_unique_exact_title(self):
        p = finder.crossref_paper(CR)
        p.add_link("开放 PDF", "https://example.org/open.pdf", "pdf", "test")
        self.assertEqual(finder.automatic_target(finder.Result(TITLE, [p])), "https://example.org/open.pdf")

    def test_auto_open_does_not_choose_ambiguous_or_approximate_titles(self):
        a = finder.crossref_paper(CR)
        b = finder.crossref_paper(dict(CR, DOI="10.1000/another"))
        self.assertEqual(len(finder.merge_papers([a, b], TITLE)), 2)
        self.assertEqual(finder.automatic_target(finder.Result(TITLE, [a, b])), "")
        self.assertEqual(finder.automatic_target(finder.Result("AlphaFold protein structure", [a])), "")

    def test_auto_open_does_not_choose_reference_extracted_from_push(self):
        self.assertEqual(finder.automatic_target(finder.Result("https://example.org/news", [finder.crossref_paper(CR)])), "")

    @patch("paper_finder.enrich", return_value=[])
    @patch("paper_finder.search_crossref", return_value=[finder.crossref_paper(CR)])
    @patch("paper_finder.search_pmc", side_effect=finder.LookupError("连接失败或超时"))
    @patch("paper_finder.search_arxiv", side_effect=finder.LookupError("服务暂时限流（429）"))
    def test_one_service_down_preserves_results(self, *_):
        result = finder.find_papers(TITLE)
        self.assertEqual(result.papers[0].doi, DOI)
        self.assertTrue(any("Europe PMC" in note for note in result.notes))

    @patch("paper_finder.get_json", side_effect=finder.LookupError("服务未收录该标识符（404）。"))
    def test_non_crossref_doi_still_has_resolver(self, _):
        paper, note = finder.lookup_doi("10.5555/unindexed")
        self.assertEqual(paper.links[0].url, "https://doi.org/10.5555/unindexed")
        self.assertTrue(note)

    @patch("paper_finder.search_pmc", return_value=[PMC])
    def test_unpaywall_optional_and_pdf_priority(self, _):
        requested = []
        def response(url):
            requested.append(url)
            if "unpaywall" in url:
                return {"best_oa_location": {"url_for_pdf": "https://repo.org/accepted.pdf", "version": "acceptedVersion"}}
            return {"openAccessPdf": {"url": "javascript:bad"}}
        with patch("paper_finder.get_json", side_effect=response):
            paper = finder.crossref_paper(CR)
            finder.enrich(paper, email="research@example.org", semantic=True)
        self.assertTrue(any("email=research%40example.org" in url for url in requested))
        self.assertTrue(any(link.source == "Unpaywall" and link.kind == "pdf" for link in paper.links))
        self.assertFalse(any(link.url.startswith("javascript") for link in paper.links))

    @patch("paper_finder.search_pmc", return_value=[])
    def test_no_email_does_not_contact_unpaywall(self, _):
        with patch("paper_finder.get_json") as request:
            finder.enrich(finder.crossref_paper(CR))
        request.assert_not_called()

    def test_bad_input_is_actionable(self):
        for value in ["", "a", "x" * 20001]:
            with self.assertRaises(finder.LookupError):
                finder.find_papers(value)


if __name__ == "__main__":
    unittest.main()
