"""Hidden integration checks for workspace drafts, scopes and explicit AI consent."""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import app
from library_core import Library
from workspace_state import WorkspaceStore
from workspace_ui import WorkspacePage
from project_ai_ui import ProjectAIWindow
import ui_theme


class FakeManager:
    ACTIVE = {'queued','running'}
    def __init__(self):self.jobs={};self.cancelled=[]
    def submit(self,kind,label,worker,metadata=None):
        ident=str(len(self.jobs)+1);self.jobs[ident]={'status':'running','message':'Running','result':None,'metadata':metadata,'worker':worker};return ident
    def get_task(self,ident):return self.jobs.get(ident)
    def cancel(self,ident):self.cancelled.append(ident);return True


class WorkspaceUITests(unittest.TestCase):
    def fixture(self,base):
        directory=Path(base)/'本地文献库';library=Library(directory)
        first=library.create_project('First project');second=library.create_project('Second project')
        one=library.save({'title':'First paper','status':'未读','year':'2025'},first)
        two=library.save({'title':'Second paper','status':'已读','year':'2024'},second)
        library.close();return directory,first,second,one,two

    def test_draft_survives_refresh_and_failed_scope_switch(self):
        with tempfile.TemporaryDirectory() as temp:
            directory,first,second,one,two=self.fixture(temp)
            root=tk.Tk();root.withdraw();ui_theme.install_theme(root)
            page=WorkspacePage(root,directory,{})
            try:
                page.project=first;page.refresh();page.question.insert('1.0','Draft before refresh');page.refresh()
                self.assertEqual(page.store.question(first),'Draft before refresh')
                page.question.insert('end',' unsaved')
                page.project_combo.current(next(i for i,p in enumerate(page.project_rows) if p['id']==second))
                with patch.object(page.store,'set_question',side_effect=OSError('disk full')):
                    page.change_project()
                self.assertEqual(page.project,first);self.assertEqual(page.project_var.get(),'First project')
                self.assertEqual(page.question.get('1.0','end-1c'),'Draft before refresh unsaved')
            finally:page.close();root.destroy()

    def test_full_app_workbench_smart_view_evidence_and_cancelled_close(self):
        with tempfile.TemporaryDirectory() as temp:
            directory,first,second,one,two=self.fixture(temp)
            with patch('app.app_dir',return_value=Path(temp)),patch.object(app.App,'start_selection_helper'),patch('desktop_runtime.startup_enabled',return_value=False),patch('desktop_runtime.configure_startup'):
                root=tk.Tk();root.withdraw();instance=app.App(root)
                try:
                    instance.show_page('workspace');instance.workspace_page.project=first;instance.workspace_page.refresh()
                    instance.workspace_page.question.insert('1.0','Question for the project')
                    window=instance.open_library()
                    window.apply_view({'project':first,'status':'未读','columns':['title','status'],'filters':{'year':{'values':['2025'],'contains':''}}})
                    self.assertEqual(window.tree.get_children(),(one,));self.assertEqual(tuple(window.tree['displaycolumns']),('title','status'))
                    self.assertEqual(instance.workspace_page.store.question(first),'Question for the project')
                    research=instance.open_research(first);editor=research.new_section();editor.fields['title'].set('Unsaved outline')
                    with patch('research_ui.messagebox.askyesno',return_value=False):
                        self.assertFalse(instance.can_close_workspace())
                    self.assertFalse(research.closed)
                    with patch.object(instance.workspace_page.store,'set_question',side_effect=OSError('disk full')),patch('workspace_app.messagebox.showerror'):
                        instance.workspace_page.question.insert('end',' edit');self.assertFalse(instance.can_close_workspace())
                    self.assertEqual(root.state(),'withdrawn')
                finally:
                    with patch('research_ui.messagebox.askyesno',return_value=True):instance.close()

    def test_ai_discards_stale_search_and_preview_binds_question_provider_and_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            directory,first,second,one,two=self.fixture(temp)
            root=tk.Tk();root.withdraw();ui_theme.install_theme(root);manager=FakeManager()
            window=ProjectAIWindow(root,directory,first,manager=manager)
            profile={'endpoint':'https://example.invalid/v1','model':'test','stream':False}
            source={'id':'S1','paper':one,'attachment':'fixture','locator_kind':'paragraph','paragraph':0,'page':None,
                    'title':'First paper','excerpt':'A long enough original source passage.','origin':'text','source':'正文'}
            try:
                root.update_idletasks();window.query.set('original');window.search();job=window.task_id
                window.query.set('changed')
                manager.jobs[job].update(status='succeeded',result={'sources':[source]})
                window.poll();self.assertEqual(window.sources,[]);self.assertIn('结果已丢弃',window.status.get())
                window.query.set('original');window.search();job=window.task_id
                manager.jobs[job].update(status='succeeded',result={'sources':[source]});window.poll();root.update_idletasks()
                window.question.insert('1.0','What does the source say?');root.update_idletasks()
                with patch('project_ai_ui.load_profile',return_value=profile):
                    window.preview();self.assertIsNotNone(window.prepared)
                    self.assertIn(profile['endpoint'],window.preview_text.get('1.0','end'))
                    # Synchronous comparison protects even before queued Tk
                    # modified events have invalidated the preview.
                    window.question.insert('end',' revised');window.send();self.assertIsNone(window.task_id)
                    root.update_idletasks();window.preview();window.provider.set('custom');window.send();self.assertIsNone(window.task_id)
                    window.preview();window.send();self.assertIsNotNone(window.task_id)
                    self.assertFalse(manager.jobs[window.task_id]['metadata']['retryable'])
                window.close();self.assertTrue(manager.cancelled);self.assertIsNone(window.poll_job)
                self.assertEqual(root.state(),'withdrawn')
            finally:
                if not window.closed:window.close()
                root.destroy()

    def test_nested_smart_view_rules_and_import_are_validated_atomically(self):
        with tempfile.TemporaryDirectory() as temp:
            directory,first,second,one,two=self.fixture(temp);store=WorkspaceStore(directory)
            try:
                for criteria in ({'filters':{'year':[]}}, {'filters':{'year':{'values':'2024'}}}, {'descending':'yes'}, {'rating':'x星及以上'}):
                    with self.assertRaises(ValueError):store.validate_view(criteria)
                normalized=store.validate_view({'columns':['year','year']})
                self.assertEqual(normalized['columns'],['title','year'])
                payload={'schema':1,'projects':[{'project':'source','question':'Must roll back','todos':[],'queue':[]}],
                         'views':[{'name':'Invalid scope','criteria':{'project':'unmapped'}}]}
                with self.assertRaises(ValueError):store.import_project(payload,{'source':first},{})
                self.assertEqual(store.question(first),'');self.assertEqual(store.views(),[])
            finally:store.close()


if __name__=='__main__':unittest.main()
