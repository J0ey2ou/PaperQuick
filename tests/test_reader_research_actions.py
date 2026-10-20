from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
from library_core import Library
from chat_prompt_ui import ChatPromptDialog,DEFAULT_CHAT_PROMPT,render_chat_prompt
from reader_workflow_ui import ReaderWorkflow


class ReaderResearchActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.lib=Library(self.base/'store')
        source=self.base/'paper.txt';source.write_text('Fictional research text.','utf-8');self.rid=self.lib.import_document(source)
        self.root=tk.Tk();self.root.withdraw()

    def tearDown(self):self.root.destroy();self.lib.close();self.tmp.cleanup()

    def test_template_is_editable_persistent_and_only_button_opens_handoff(self):
        bridge=Mock();bridge.prepare.return_value='https://chatgpt.com/#fixture';bridge.open_url.return_value='http://127.0.0.1/fixture'
        with patch('chat_prompt_ui.webbrowser.open',return_value=True) as browser:
            dialog=ChatPromptDialog(self.root,self.lib.root,self.rid,bridge)
            browser.assert_not_called();bridge.prepare.assert_not_called()
            dialog.replace('自定义阅读《{标题}》：请比较方法和局限。');dialog.open_chat()
            bridge.prepare.assert_called_once_with(self.rid,quote='自定义阅读《paper》：请比较方法和局限。',whole_document=True)
            browser.assert_called_once_with('http://127.0.0.1/fixture')
            dialog.win.destroy()
            saved=ChatPromptDialog(self.root,self.lib.root)
            self.assertIn('自定义阅读',saved.text.get('1.0','end'));saved.win.destroy()
        self.assertIn('不要补写事实',render_chat_prompt(DEFAULT_CHAT_PROMPT,{'title':'A'}))

    def test_cross_page_selection_sets_locator_and_persists_note_citation(self):
        notes=tk.Text(self.root)
        selection={'page':1,'quote':'Selected evidence','regions':[{'page':1},{'page':2}]}
        owner=SimpleNamespace(rid=self.rid,directory=self.lib.root,page=5,context_page=5,current_selection=lambda:selection,notes=notes,note_status=tk.StringVar(),dirty=False,save_notes=Mock())
        owner.citation_locator=lambda:ReaderWorkflow.citation_locator(owner)
        self.assertEqual(owner.citation_locator(),'2–3')
        ReaderWorkflow.insert_note_citation(owner)
        content=notes.get('1.0','end')
        self.assertIn('Selected evidence',content);self.assertIn('第 2–3 页',content);self.assertIn('《paper》',content)
        owner.save_notes.assert_called_once()
        with patch('word_citation_ui.WordCitationsWindow') as dialog:
            owner.frame=self.root;ReaderWorkflow.insert_word_citation(owner)
            self.assertEqual(dialog.call_args.kwargs['locator'],'2–3')
            self.assertEqual(dialog.call_args.kwargs['selected'],[self.rid])

    def test_classification_has_tags_ratings_state_filters_and_rules(self):
        from library_ui import LibraryWindow
        window=LibraryWindow(self.root,self.lib.root)
        self.lib.save({'tags':['统计'],'rating':4,'status':'在读'},rid=self.rid)
        window.refresh();self.assertIn('tags',window.tree['columns']);self.assertIn('rating',window.tree['columns'])
        window.rating_filter.set('5 星及以上');window.refresh_records();self.assertFalse(window.tree.get_children())
        window.rating_filter.set('全部评分');window.tag_filter.set('统计');window.refresh_records();self.assertEqual(window.tree.get_children(),(self.rid,))
        self.assertTrue(any(window.context_menu.entrycget(i,'label')=='打开已下载原文所在位置' for i in range(window.context_menu.index('end')+1) if window.context_menu.type(i)!='separator'))
        window.close()
