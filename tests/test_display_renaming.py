from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace
from library_core import Library,digest,display_name
from display_renaming import prepare_display_names,apply_display_names,display_name_from_rule
from metadata_renaming import extract_article_metadata
from test_library_documents import docx


class DisplayRenamingTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'build'/'display-name-tests';root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root);self.base=Path(self.tmp.name);self.lib=Library(self.base/'store')
        self.source=self.base/'random.docx';docx(self.source,title='Old internal title',author='wxz',paragraphs=['标题：Correct full article title','作者：Alice Smith; Bob Jones','期刊：A Journal','年份：2025'])
        self.rid=self.lib.import_document(self.source)

    def tearDown(self):self.lib.close();self.tmp.cleanup()

    def test_only_display_name_changes_and_every_filename_and_byte_is_preserved(self):
        before=self.lib.get(self.rid);paths={a['path']:digest(self.lib.root/a['path']) for a in before['attachments']};source_hash=digest(self.source)
        plans=prepare_display_names(self.lib,[self.rid])
        self.assertEqual(self.lib.get(self.rid),before)
        self.assertEqual(plans[0]['display_name'],'Correct full article title')
        plans[0]['display_name']='My readable label: primary care / China?'
        with patch.object(self.lib,'rename',side_effect=AssertionError('File rename forbidden')):
            result=apply_display_names(self.lib,plans)
        self.assertEqual(result,{'count':1,'errors':[]})
        after=self.lib.get(self.rid)
        self.assertEqual(after['title'],before['title']);self.assertEqual(after['authors'],before['authors'])
        self.assertEqual(after['attachments'],before['attachments'])
        self.assertEqual(display_name(after),'My readable label: primary care / China?')
        self.assertEqual({a['path']:digest(self.lib.root/a['path']) for a in after['attachments']},paths)
        self.assertEqual(digest(self.source),source_hash)
        node=next(n for n in self.lib.graph()['nodes'] if n['id']==self.rid)
        self.assertEqual(node['title'],display_name(after));self.assertEqual(node['article_title'],before['title'])
        self.lib.save({'last_read':100},rid=self.rid)
        self.assertEqual(self.lib.recent_read()[0]['title'],display_name(after))

    def test_recognition_failure_and_no_attachment_do_not_block_manual_names(self):
        nofile=self.lib.save({'title':'No file'})
        with patch('display_renaming.extract_article_metadata',side_effect=ValueError('Unreadable')):
            plans=prepare_display_names(self.lib,[self.rid,nofile])
        for plan in plans:
            self.assertTrue(plan['warnings']);plan['display_name']='Manual '+plan['id'][:8]
        self.assertEqual(apply_display_names(self.lib,plans),{'count':2,'errors':[]})

    def test_optional_metadata_save_is_explicit_and_preserves_new_notes(self):
        plans=prepare_display_names(self.lib,[self.rid]);plans[0]['sync_metadata']=True
        self.lib.save({'notes':'New note while preview was open'},rid=self.rid)
        self.assertFalse(apply_display_names(self.lib,plans)['errors'])
        saved=self.lib.get(self.rid)
        self.assertEqual(saved['title'],'Correct full article title');self.assertEqual(saved['authors'],'Alice Smith; Bob Jones')
        self.assertEqual(saved['notes'],'New note while preview was open')

    def test_stale_display_name_is_not_overwritten(self):
        plans=prepare_display_names(self.lib,[self.rid])
        self.lib.save({'display_name':'Another edit'},rid=self.rid)
        result=apply_display_names(self.lib,plans)
        self.assertEqual(result['count'],0);self.assertTrue(result['errors'])
        self.assertEqual(display_name(self.lib.get(self.rid)),'Another edit')

    def test_display_rules_preserve_punctuation_and_do_not_append_extension(self):
        name=display_name_from_rule({'title':'Why A/B? A: B','authors':'Alice Smith; Bob Jones','year':'2025'},'P','{年份} · {第一作者} · {标题}')
        self.assertEqual(name,'2025 · Alice Smith · Why A/B? A: B')

    def test_classification_uses_display_only_workflow(self):
        from library_ui import LibraryWindow
        window=SimpleNamespace(library=self.lib,preview_renames=Mock())
        window.run=lambda title,work,done:done(work(self.lib))
        LibraryWindow.rename_records(window,[self.rid])
        plan=window.preview_renames.call_args.args[0][0]
        self.assertIn('display_name',plan);self.assertNotIn('files',plan)


if __name__=='__main__':unittest.main()
