"""Performance contracts that also exercise data integrity, without UI or network."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import library_core
from library_core import Library
from fulltext_index import FulltextIndex


class RowDiffTests(unittest.TestCase):
    def test_unchanged_rows_keep_identity_and_only_changed_values_update(self):
        from library_table import sync_rows
        class Tree:
            def __init__(self):self.rows=[];self.calls=[]
            def get_children(self):return tuple(self.rows)
            def delete(self,*ids):
                self.calls.append(('delete',ids));self.rows=[rid for rid in self.rows if rid not in ids]
            def insert(self,parent,index,iid,**kw):self.rows.insert(index,iid);self.calls.append(('insert',iid))
            def item(self,rid,**kw):self.calls.append(('item',rid))
            def move(self,rid,parent,index):self.rows.remove(rid);self.rows.insert(index,rid);self.calls.append(('move',rid))
        tree=Tree();rows=[('a',('A',),()),('b',('B',),()),('c',('C',),())]
        cached=sync_rows(tree,rows,{})
        tree.calls.clear();cached=sync_rows(tree,rows,cached)
        self.assertEqual(tree.calls,[])
        changed=[('c',('Changed',),()),('a',('A',),()),('d',('D',),())]
        sync_rows(tree,changed,cached)
        self.assertEqual(tree.rows,['c','a','d'])
        self.assertEqual([call for call in tree.calls if call[0]=='item'],[('item','c')])
        self.assertEqual([call for call in tree.calls if call[0]=='insert'],[('insert','d')])


class LibraryPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.lib = Library(self.base / 'store')
        self.project = self.lib.projects()[0]['id']

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def test_summary_projection_tracks_other_connection_writes_and_rollback(self):
        rid = self.lib.save({'title':'Original', 'text':'large body', 'notes':'private note'})
        other = Library(self.lib.root)
        try:
            with other.db:
                other.db.execute('UPDATE papers SET data=? WHERE id=?',
                                 (json.dumps({'title':'Changed', 'text':'body', 'annotations':[{'text':'note'}]}), rid))
            result = self.lib.records(summary=True, rid=rid)[0]
            self.assertEqual(result['title'], 'Changed')
            self.assertNotIn('text', result)
            self.assertNotIn('annotations', result)
            with self.assertRaises(RuntimeError):
                with other.db:
                    other.db.execute('DELETE FROM papers WHERE id=?', (rid,))
                    raise RuntimeError('rollback')
            self.assertEqual(self.lib.records(summary=True, rid=rid)[0]['title'], 'Changed')
            with other.db:other.db.execute('DELETE FROM papers WHERE id=?', (rid,))
            self.assertEqual(self.lib.records(summary=True, rid=rid), [])
        finally:other.close()

    def test_existing_library_backfills_summary_without_changing_document(self):
        rid = self.lib.save({'title':'Old library', 'text':'Keep full body', 'notes':'Keep note'})
        with self.lib.db:
            self.lib.db.execute("DELETE FROM config WHERE key='paper_summary_schema'")
            self.lib.db.execute('DELETE FROM paper_summaries')
        reopened = Library(self.lib.root)
        try:
            self.assertEqual(reopened.records(summary=True)[0]['title'], 'Old library')
            self.assertEqual(reopened.get(rid)['text'], 'Keep full body')
            self.assertEqual(reopened.get(rid)['notes'], 'Keep note')
        finally:reopened.close()

    def test_first_projection_migration_serializes_concurrent_open_and_write(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        rid = self.lib.save({'title':'Before migration', 'text':'Keep original'})
        with self.lib.db:
            for name in ('insert','update','delete'):
                self.lib.db.execute('DROP TRIGGER paper_summaries_'+name)
            self.lib.db.execute('DROP TABLE paper_summaries')
            self.lib.db.execute("DELETE FROM config WHERE key='paper_summary_schema'")
        barrier=threading.Barrier(4)
        def writer(number):
            barrier.wait()
            connection=Library(self.lib.root)
            try:
                new_id=connection.save({'title':'Concurrent '+str(number),'text':'Body'})
                connection.save({'title':'Updated '+str(number)},rid=new_id)
                if number%2:
                    with connection.db:connection.db.execute('DELETE FROM papers WHERE id=?',(new_id,))
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(writer,range(4)))
        full={record['id']:record['title'] for record in self.lib.records()}
        summary={record['id']:record['title'] for record in self.lib.records(summary=True)}
        self.assertEqual(summary,full)
        self.assertEqual(len(summary),3)
        self.assertEqual(self.lib.get(rid)['text'],'Keep original')

    def test_search_builds_inventory_once_and_skips_note_payload_loading(self):
        rid = self.lib.save({'title':'Target', 'notes':'SpecialNeedle'})
        other = self.lib.save({'title':'Other', 'notes':'OtherNeedle'})
        index = FulltextIndex(self.lib.root)
        index.update()
        with patch.object(index, '_inventory', wraps=index._inventory) as inventory:
            found = index.search('SpecialNeedle', rid=rid)
        self.assertEqual([r['paper'] for r in found], [rid])
        self.assertEqual(inventory.call_count, 1)
        self.assertFalse(inventory.call_args.kwargs['include_segments'])
        self.assertEqual(index.search('OtherNeedle', rid=rid), [])
        self.assertEqual([r['id'] for r in self.lib.records(summary=True, rid=other)], [other])

    def test_import_reuses_metadata_and_checks_copy_content(self):
        source = self.base / 'paper.txt'
        source.write_text('Source text for performance fixture', encoding='utf-8')
        with patch.object(library_core, 'document_metadata', wraps=library_core.document_metadata) as metadata, \
             patch.object(library_core, 'digest', wraps=library_core.digest) as digest:
            rid = self.lib.import_document(source)
        self.assertEqual(metadata.call_count, 1)
        self.assertEqual(digest.call_count, 3)  # source before/after parsing + destination re-read
        saved = self.lib.root / self.lib.primary_attachment(rid)['path']
        self.assertEqual(saved.read_bytes(), source.read_bytes())
        self.assertEqual(self.lib.get(rid)['text'], source.read_text(encoding='utf-8'))

    def test_source_changed_after_metadata_validation_cannot_enter_library(self):
        source = self.base / 'changing.txt'
        source.write_text('Original source', encoding='utf-8')
        original = self.lib._add_attachment
        def changed(*args, **kwargs):
            source.write_text('Changed before copy', encoding='utf-8')
            return original(*args, **kwargs)
        with patch.object(self.lib, '_add_attachment', side_effect=changed):
            with self.assertRaises(ValueError):self.lib.import_document(source)
        self.assertEqual(self.lib.records(), [])
        self.assertFalse(list((self.lib.root / 'papers').rglob('*.txt')))

    def test_batch_journal_appends_snapshots_and_undo_handles_repeated_file(self):
        source = self.base / 'batch.txt'
        source.write_text('A large body ' * 1000, encoding='utf-8')
        result = self.lib.import_batch([source, source], self.project)
        stored = self.lib.db.execute('SELECT data FROM import_batches WHERE id=?',(result['batch'],)).fetchone()[0]
        self.assertEqual(json.loads(stored), {'entries':'rows-v1'})
        self.assertEqual(self.lib.db.execute('SELECT COUNT(*) FROM import_batch_entries WHERE batch=?',(result['batch'],)).fetchone()[0], 2)
        self.assertEqual(len(json.loads(self.lib.latest_import()['data'])), 2)
        self.assertEqual(self.lib.undo_import(result['batch'])['kept'], 0)
        self.assertEqual(self.lib.records(), [])


if __name__ == '__main__':unittest.main()
