from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from library_core import Library
from workspace_state import WorkspaceStore


class WorkspaceStateTests(unittest.TestCase):
    def test_smart_view_is_live_and_preserves_sort_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=WorkspaceStore(tmp);lib=store.library
            try:
                parent=lib.create_project('Project');child=lib.create_project('Child',parent)
                first=lib.save({'title':'A','year':'2024','status':'未读'},child)
                view=store.save_view('近期未读',{'project':parent,'status':'未读','year_from':'2020','sort_key':'year','descending':True,'columns':['title','year']})
                criteria=store.views()[0]['criteria'];self.assertEqual([first],[r['id'] for r in store.view_records(criteria)])
                second=lib.save({'title':'B','year':'2026','status':'未读'},parent)
                self.assertEqual([second,first],[r['id'] for r in store.view_records(criteria)])
                lib.save({'status':'已读'},rid=second)
                self.assertEqual([first],[r['id'] for r in store.view_records(criteria)])
                store.set_question(parent,'What predicts outcomes?');task=store.save_todo(parent,'Read A','2026-12-01')
                store.enqueue(parent,[first,first]);self.assertEqual(len(store.queue(parent)),1)
                data=store.export_project(parent);self.assertEqual(data['schema'],1);self.assertTrue(data['views'])
                store.delete_todo(task);store.delete_view(view);self.assertFalse(store.views());self.assertFalse(store.todos(parent))
            finally:store.close()

    def test_concurrent_field_updates_and_doi_dedup_keep_latest_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Library(tmp);rid=base.save({'title':'Original'});base.close()
            barrier=threading.Barrier(2)
            def write(field):
                library=Library(tmp)
                try:
                    barrier.wait(timeout=10)
                    for i in range(15):library.save({field:f'{field}-{i}'},rid=rid)
                    barrier.wait(timeout=10)
                    return library.save({'title':field,'doi':'10.1000/concurrent-paper'})
                finally:library.close()
            with ThreadPoolExecutor(2) as workers:
                a=workers.submit(write,'notes');b=workers.submit(write,'abstract');self.assertEqual(a.result(30),b.result(30))
            library=Library(tmp)
            try:
                record=library.get(rid);self.assertEqual(record['notes'],'notes-14');self.assertEqual(record['abstract'],'abstract-14')
                self.assertEqual(len(library.records()),2)
            finally:library.close()

    def test_queue_rejects_out_of_scope_and_invalid_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=WorkspaceStore(tmp)
            try:
                project=store.library.create_project('Empty');rid=store.library.save({'title':'Outside'})
                with self.assertRaises(ValueError):store.enqueue(project,[rid])
                self.assertFalse(store.queue(project))
                with self.assertRaises(ValueError):store.save_view('Bad',{'year_from':'2026','year_to':'2020'})
            finally:store.close()
