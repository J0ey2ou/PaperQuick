from pathlib import Path
import json
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from citation_styles import (CitationStyleError, asset_directory, format_document,
                             import_style, list_styles)


def article(title, family="Smith", year=2021, given="Alice"):
    return {"type": "article-journal", "title": title,
            "author": [{"family": family, "given": given}],
            "issued": {"date-parts": [[year]]}, "container-title": "Journal of Research",
            "volume": "12", "issue": "3", "page": "14-28", "DOI": "10.1000/example"}


def cluster(name, *ids, **extra):
    return {"id": name, "items": [{"id": item_id, **extra} for item_id in ids]}


class CitationStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root = Path(__file__).resolve().parents[1] / "build" / "citation-style-tests"
        cls.temp_root.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.items = {"a": article("Zinc nutrition", "Smith"),
                      "b": article("Animal nutrition", "Jones", 2020),
                      "c": article("Adolescent nutrition", "Smith")}

    def test_numbering_uses_document_order_and_changes_when_moved_or_removed(self):
        first = format_document(self.items, [cluster("c1", "b"), cluster("c2", "a"),
                                             cluster("c3", "b")], "ieee")
        self.assertEqual(first["plain_citations"], {"c1": "[1]", "c2": "[2]", "c3": "[1]"})
        self.assertEqual(first["bibliography_ids"], ["b", "a"])
        reordered = format_document(self.items, [cluster("c2", "a"), cluster("c1", "b")], "ieee")
        self.assertEqual(reordered["plain_citations"]["c2"], "[1]")
        self.assertEqual(reordered["bibliography_ids"], ["a", "b"])
        removed = format_document(self.items, [cluster("c1", "b")], "ieee")
        self.assertEqual(removed["bibliography_ids"], ["b"])
        self.assertNotIn("Zinc nutrition", removed["plain_bibliography"])

    def test_multisource_citation_is_sorted_deduplicated_and_reused(self):
        result = format_document(self.items, [cluster("c1", "a"), cluster("c2", "b"),
                                              cluster("c3", "b", "a", "a")], "ieee")
        self.assertEqual(result["bibliography_ids"], ["a", "b"])
        self.assertEqual(result["plain_citations"]["c3"], "[1], [2]")
        self.assertEqual(result["plain_bibliography"].count("Zinc nutrition"), 1)

    def test_author_year_and_disambiguation_update_earlier_citations(self):
        result = format_document(self.items, [cluster("old", "a"), cluster("new", "c")], "apa")
        self.assertEqual(result["plain_citations"]["old"], "(Smith, 2021b)")
        self.assertEqual(result["plain_citations"]["new"], "(Smith, 2021a)")
        self.assertEqual(result["bibliography_ids"], ["c", "a"])
        self.assertIn("\\li720\\fi-720", result["bibliography"])
        self.assertIn("{\\i{}Journal of Research}", result["bibliography"])

    def test_locator_prefix_suffix_and_narrative_omission(self):
        result = format_document(self.items, [{"id": "c1", "items": [
            {"id": "a", "locator": "14-16", "label": "page", "prefix": "see ", "suffix": "; discussion"}]}], "apa")
        rendered = result["plain_citations"]["c1"]
        self.assertIn("see Smith, 2021", rendered)
        self.assertIn("pp. 14", rendered)
        self.assertIn("discussion", rendered)
        narrative = format_document(self.items, [{"id": "c1", "items": [
            {"id": "a", "suppress-author": True}]}], "apa")
        self.assertEqual(narrative["plain_citations"]["c1"], "(2021)")

    def test_superscript_and_unicode_are_complete_rtf_documents(self):
        result = format_document(self.items, [cluster("c1", "a")], "nature")
        rich = result["citations"]["c1"]
        self.assertTrue(rich.startswith("{\\rtf1"))
        self.assertTrue(rich.endswith("}"))
        self.assertIn("\\super 1\\nosupersub", rich)
        chinese = {"zh": {"type": "article-journal", "title": "儿童营养与健康",
                           "author": [{"literal": "张三"}], "language": "zh-CN",
                           "issued": {"date-parts": [[2023]]}, "container-title": "中华医学杂志"}}
        gb = format_document(chinese, [cluster("first", "zh")],
                             "china-national-standard-gb-t-7714-2015-numeric")
        self.assertIn("张三", gb["plain_bibliography"])
        self.assertIn("儿童营养与健康", gb["plain_bibliography"])
        self.assertIn("[J]", gb["plain_bibliography"])
        self.assertIn("\\u24352", gb["bibliography"])
        self.assertTrue(gb["bibliography"].isascii())

    def test_empty_citations_clears_bibliography(self):
        result = format_document(self.items, [], "apa")
        self.assertEqual(result["citations"], {})
        self.assertEqual(result["bibliography_ids"], [])
        self.assertEqual(result["plain_bibliography"], "")
        self.assertTrue(result["bibliography"].startswith("{\\rtf1"))

    def test_missing_or_duplicated_citations_fail_before_rendering(self):
        with self.assertRaises(CitationStyleError):
            format_document(self.items, [cluster("c1", "missing")], "apa")
        with self.assertRaises(CitationStyleError):
            format_document(self.items, [cluster("c1", "a"), cluster("c1", "b")], "apa")
        with self.assertRaises(CitationStyleError):
            format_document(self.items, [], "../../not-installed")

    def test_bundled_styles_work_offline_and_dependent_vancouver_resolves(self):
        styles = list_styles()
        self.assertGreaterEqual(len(styles), 30)
        self.assertTrue(all(style["style_class"] == "in-text" for style in styles))
        self.assertNotIn("nlm-citation-sequence", [style["id"] for style in styles])
        for style in styles:
            with self.subTest(style=style["id"]):
                result = format_document(self.items, [cluster("c1", "a", "b")], style["id"])
                self.assertEqual(set(result["bibliography_ids"]), {"a", "b"})
                self.assertTrue(result["plain_citations"]["c1"])
                self.assertNotRegex(result["bibliography"], r"(?<!\\)\\(?:object|pict|field|filetbl)\b")

    def test_import_preserves_original_style_and_exposes_note_class(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as directory:
            root = Path(directory)
            original = (asset_directory() / "styles" / "apa.csl").read_text(encoding="utf-8")
            source = root / "style.csl"
            source.write_text(original, encoding="utf-8")
            imported = import_style(source, root / "custom")
            self.assertEqual(imported, import_style(source, root / "custom"))
            self.assertEqual((root / "custom" / (imported + ".csl")).read_text(encoding="utf-8"), original)
            self.assertTrue(next(style for style in list_styles(root / "custom") if style["id"] == imported)["custom"])
            result = format_document(self.items, [cluster("c1", "a")], imported, root / "custom")
            self.assertEqual(result["plain_citations"]["c1"], "(Smith, 2021)")
            source.write_text(original.replace('class="in-text"', 'class="note"'), encoding="utf-8")
            note_id = import_style(source, root / "custom")
            note = next(style for style in list_styles(root / "custom") if style["id"] == note_id)
            self.assertEqual(note["style_class"], "note")

    def test_import_validates_xml_entities_and_parent_without_network(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as directory:
            root = Path(directory)
            source = root / "untrusted.csl"
            for data in [b'<!DOCTYPE style [<!ENTITY x SYSTEM "file:///C:/private.txt">]><style/>',
                         b'<not-a-style/>', b'<style', '<!DOCTYPE style><style/>'.encode('utf-16')]:
                source.write_bytes(data)
                with self.assertRaises(CitationStyleError):
                    import_style(source, root / "custom")
            missing = (asset_directory() / "styles" / "vancouver-nlm.csl").read_text(encoding="utf-8").replace(
                'http://www.zotero.org/styles/nlm-citation-sequence', 'http://www.zotero.org/styles/missing-test-parent')
            source.write_text(missing, encoding="utf-8")
            with self.assertRaisesRegex(CitationStyleError, "missing-test-parent"):
                import_style(source, root / "custom")
            source.write_bytes((asset_directory() / "styles" / "vancouver-nlm.csl").read_bytes())
            imported = import_style(source, root / "custom")
            result = format_document(self.items, [cluster("c1", "a")], imported, root / "custom")
            self.assertEqual(result["plain_citations"]["c1"], "(1)")


if __name__ == "__main__":
    unittest.main()
