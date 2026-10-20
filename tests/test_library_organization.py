from pathlib import Path
import tempfile
import unittest
from library_core import Library,filename
from library_organization import normalize_tags
from display_renaming import display_name_from_rule


class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.lib=Library(self.base/'store')
        self.parent=self.lib.create_project('健康');self.child=self.lib.create_project('方法',self.parent)

    def tearDown(self):self.lib.close();self.tmp.cleanup()

    def test_tag_rules_nested_queries_and_manual_memberships_survive_tag_removal(self):
        self.lib.set_project_rules(self.child,'统计；Methods')
        rid=self.lib.save({'title':'A','tags':'methods,Methods；统计','rating':4})
        self.assertEqual(normalize_tags(' a；A\nb '),['a','b'])
        self.assertIn(self.child,self.lib.get(rid)['projects'])
        self.assertEqual([r['id'] for r in self.lib.records(self.parent)],[rid])
        self.lib.assign(rid,self.child)
        self.lib.save({'tags':[]},rid=rid)
        self.assertIn(self.child,self.lib.get(rid)['projects'])
        self.lib.close();self.lib=Library(self.base/'store')
        self.assertEqual(self.lib.get(rid)['rating'],4)
        self.assertEqual(self.lib.project(self.child)['parent'],self.parent)

    def test_replacing_rules_reclassifies_existing_records_without_moving_files(self):
        rid=self.lib.save({'title':'A','tags':['统计']})
        self.lib.set_project_rules(self.child,'统计')
        self.assertIn(self.child,self.lib.get(rid)['projects'])
        self.lib.set_project_rules(self.child,'其他')
        self.assertNotIn(self.child,self.lib.get(rid)['projects'])
        self.lib.save({'tags':['其他']},rid=rid)
        self.assertIn(self.child,self.lib.get(rid)['projects'])
        self.lib.save({'tags':[]},rid=rid)
        self.assertNotIn(self.child,self.lib.get(rid)['projects'])

    def test_nested_names_repeat_under_distinct_parents_and_do_not_duplicate_results(self):
        other=self.lib.create_project('教育');second=self.lib.create_project('方法',other)
        self.assertNotEqual(second,self.child)
        rid=self.lib.save({'title':'A'},self.parent);self.lib.assign(rid,self.child)
        self.assertEqual(len(self.lib.records(self.parent)),1)

    def test_rating_and_tags_validate_before_any_write(self):
        rid=self.lib.save({'title':'A','notes':'Keep'})
        for rating in (-1,6,3.5,'NaN'):
            with self.assertRaises(ValueError):self.lib.save({'rating':rating,'notes':'Bad'},rid=rid)
        with self.assertRaises(ValueError):self.lib.save({'tags':['a'*61]},rid=rid)
        self.assertEqual(self.lib.get(rid)['notes'],'Keep')

    def test_import_undo_and_trash_preserve_automatic_membership_provenance(self):
        source=self.base/'article.txt';source.write_text('A real local fixture body.','utf-8')
        self.lib.set_project_rules(self.child,'方法')
        batch=self.lib.import_batch([source],self.parent);rid=batch['new_paper_ids'][0]
        self.assertEqual(self.lib.document_location(rid).read_bytes(),source.read_bytes())
        self.lib.save({'tags':['方法']},rid=rid)
        self.lib.remove_papers([rid]);self.lib.restore_removed()
        self.lib.save({'tags':[]},rid=rid)
        self.assertNotIn(self.child,self.lib.get(rid)['projects'])
        self.assertTrue(source.exists())
        fresh=self.base/'other.txt';fresh.write_text('Different fixture body.','utf-8')
        result=self.lib.import_batch([fresh],self.parent);self.lib.undo_import(result['batch'])
        self.assertFalse(any(r['id'] in result['new_paper_ids'] for r in self.lib.records()))

    def test_optional_names_skip_absent_components_without_placeholders(self):
        record={'title':'Why A/B? A: B'}
        self.assertEqual(display_name_from_rule(record,'P','{年份} · {第一作者} · {标题} ({期刊})'),'Why A/B? A: B')
        self.assertEqual(filename({'title':'Article'},'P'), 'Article.pdf')
        self.assertEqual(filename({'title':'Article','year':'2025'},'P'), '2025_Article.pdf')
        self.assertEqual(display_name_from_rule({'title':'Article','authors':'Alice'},'P','{标题} ({年份}) {第一作者}'),'Article Alice')
        self.assertEqual(display_name_from_rule({'title':'Article'},'P','{年份}年_{标题}'),'Article')

    def test_import_journal_from_previous_version_remains_undoable(self):
        import json
        source=self.base/'legacy.txt';source.write_text('Legacy imported fixture','utf-8')
        result=self.lib.import_batch([source],self.parent)
        row=self.lib.latest_import();entries=json.loads(row['data'])
        for entry in entries:
            for key in ('before','after'):
                if entry[key]:entry[key].pop('tag_memberships',None)
        with self.lib.db:self.lib.db.execute('UPDATE import_batches SET data=? WHERE id=?',(json.dumps(entries),result['batch']))
        self.assertEqual(self.lib.undo_import(result['batch']),{'restored':1,'kept':0})

    def test_migration_preserves_an_existing_legacy_library(self):
        import sqlite3,json
        root=self.base/'legacy';root.mkdir()
        db=sqlite3.connect(root/'library.sqlite')
        db.executescript('CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT UNIQUE,folder TEXT UNIQUE,template TEXT DEFAULT "");CREATE TABLE papers(id TEXT PRIMARY KEY,data TEXT,primary_project TEXT,updated REAL);')
        db.execute('INSERT INTO projects VALUES(?,?,?,?)',('legacy-project','Old topic','Old folder',''))
        db.execute('INSERT INTO papers VALUES(?,?,?,?)',('legacy-paper',json.dumps({'title':'Original','notes':'Keep old notes','status':'已读'}),'legacy-project',1))
        db.commit();db.close()
        lib=Library(root)
        try:
            self.assertEqual(lib.get('legacy-paper')['notes'],'Keep old notes')
            self.assertEqual(lib.get('legacy-paper')['rating'],0)
            self.assertEqual(lib.project('legacy-project')['parent'],'')
        finally:lib.close()
