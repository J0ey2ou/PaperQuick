import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_core import Library, filename, validate_template, digest, download_pdf
import endnote_sync
from graph_view import write_graph

def pdf(path, title='Test'):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'/'vendor'))
    from pypdf import PdfWriter
    w=PdfWriter();w.add_blank_page(100,100);w.add_metadata({'/Title':title,'/Author':'Tester'})
    with open(path,'wb') as f:w.write(f)

def endnote(path):
    cols=','.join(f'{column} TEXT NOT NULL DEFAULT ""' for column in endnote_sync.MAP.values())
    schema=f'CREATE TABLE {{table}}(id INTEGER PRIMARY KEY AUTOINCREMENT,trash_state INTEGER DEFAULT 0,{cols},record_last_updated INTEGER DEFAULT 0)'
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(schema.format(table='enl_refs'));db.execute('INSERT INTO enl_refs(title,author,electronic_resource_number) VALUES(?,?,?)',('Original','Writer','10.1000/example'))
    support=path.with_suffix('.Data')/'sdb'/'sdb.eni';support.parent.mkdir(parents=True)
    with closing(sqlite3.connect(support)) as db, db:
        db.execute(schema.format(table='refs'));db.execute('INSERT INTO refs(title,author,electronic_resource_number) VALUES(?,?,?)',('Original','Writer','10.1000/example'))
        db.execute('CREATE TABLE file_res(refs_id INTEGER,file_path TEXT,file_type INTEGER,file_pos INTEGER)')

class LibraryTests(unittest.TestCase):
    def setUp(self):
        temp_root=Path(__file__).resolve().parents[1]/'build'/'library-tests';temp_root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=temp_root);self.base=Path(self.tmp.name);self.lib=Library(self.base/'store');self.project=self.lib.create_project('课题A')
    def tearDown(self):self.lib.close();self.tmp.cleanup()
    def test_names_dedup_no_overwrite_and_move(self):
        source=self.base/'original.pdf';pdf(source);original=digest(source)
        rid=self.lib.import_pdf(source,self.project);again=self.lib.import_pdf(source,self.lib.projects()[0]['id'])
        self.assertEqual(rid,again);self.assertEqual(len(self.lib.get(rid)['attachments']),1)
        other=self.lib.save({'title':'Test','authors':'Tester'},self.project)
        dest=self.lib.attach(other,source);self.assertIn('(2)',dest.name)
        self.lib.set_setting('template','{课题}_{标题}')
        self.lib.rename(rid);path=self.lib.root/self.lib.get(rid)['attachments'][0]['path'];self.assertTrue(path.exists());self.assertEqual(digest(source),original)
        new=self.lib.create_project('课题B');self.lib.assign(rid,new,True);self.assertIn('课题B',self.lib.get(rid)['attachments'][0]['path']);self.assertTrue(source.exists())
    def test_templates(self):
        with self.assertRaises(ValueError):validate_template('{title.__class__}')
        with self.assertRaises(ValueError):validate_template('{年份:99}')
        self.assertNotIn('/',filename({'title':'a/b:c?','authors':'CON'},'a'))
    def test_doi_identity(self):
        a=self.lib.save({'title':'A','doi':'https://doi.org/10.1000/AB'},self.project)
        b=self.lib.save({'title':'B','doi':'10.1000/ab'},self.project)
        self.assertEqual(a,b)
        self.lib.save({'notes':'test note'},rid=a)
        self.assertEqual(self.lib.get(a)['doi'],'10.1000/ab')
    def test_endnote_duplicate_ids_preserved(self):
        source=self.base/'Source.enl';endnote(source)
        with closing(sqlite3.connect(source)) as db,db:db.execute('INSERT INTO enl_refs(title,author,electronic_resource_number) SELECT title,author,electronic_resource_number FROM enl_refs')
        plan=endnote_sync.preview(self.lib,source);self.assertEqual(endnote_sync.import_only(self.lib,plan),2)
        self.assertEqual(len(self.lib.records()),2);self.assertEqual(len({e['paper'] for e in endnote_sync.preview(self.lib,source)['entries']}),2)
    def test_graph_citations_and_escape(self):
        a=self.lib.save({'title':'Protein structure prediction','doi':'10.1000/aaa','abstract':'protein structure prediction'},self.project)
        b=self.lib.save({'title':'Protein structure predictions','text':'References\nhttps://doi.org/10.1000/aaa\n','notes':'</script>'},self.project)
        g=self.lib.graph();self.assertTrue(any(e['kind']=='citation' and e['source']==b and e['target']==a for e in g['edges']))
        self.lib.save({'title':'</script><img src=https://evil.example/>'},self.project)
        output=write_graph(self.lib).read_text('utf-8');payload=output.split('type="application/json">')[1].split('</script>')[0];self.assertNotIn('<img',payload);json.loads(payload)
    def test_sync_three_way_and_source_unchanged(self):
        source=self.base/'Original.enl';endnote(source);before=digest(source)
        p=endnote_sync.preview(self.lib,source);self.assertEqual(endnote_sync.import_only(self.lib,p),1)
        rid=self.lib.records()[0]['id'];self.lib.save({'notes':'Local note','title':'Local title'},rid=rid)
        with closing(sqlite3.connect(source)) as db, db:db.execute('UPDATE enl_refs SET title="EndNote title",abstract="Remote abstract" WHERE id=1')
        before=digest(source);p=endnote_sync.preview(self.lib,source);e=p['entries'][0];self.assertEqual(e['conflicts'],['title'])
        with self.assertRaises(ValueError):endnote_sync.export_exchange(self.lib,p,self.base/'Blocked',{})
        self.assertFalse((self.base/'Blocked').exists())
        path=endnote_sync.export_exchange(self.lib,p,self.base/'Exchange',{(1,'title'):'endnote'})
        self.assertEqual(digest(source),before)
        tree=ET.parse(path/'完整文献库.xml');self.assertEqual(tree.findtext('.//notes'),'Local note')
        self.assertEqual(self.lib.get(rid)['title'],'EndNote title');self.assertEqual(self.lib.get(rid)['abstract'],'Remote abstract')
        # A pending local push stays visible until EndNote really contains the reviewed value.
        self.assertEqual(endnote_sync.preview(self.lib,source)['entries'][0]['action'],'export')
        with closing(sqlite3.connect(source)) as db,db:db.execute('UPDATE enl_refs SET notes="Local note"')
        self.assertEqual(endnote_sync.preview(self.lib,source)['entries'][0]['action'],'unchanged')
        with self.assertRaises(ValueError):endnote_sync.export_exchange(self.lib,endnote_sync.preview(self.lib,source),path,{})
    def test_sync_projects_and_new_attachments(self):
        source=self.base/'Source.enl';endnote(source);p=endnote_sync.preview(self.lib,source);endnote_sync.import_only(self.lib,p)
        rid=self.lib.save({'title':'New local','doi':'10.1000/new'},self.project);f=self.base/'file.pdf';pdf(f);self.lib.attach(rid,f)
        p=endnote_sync.preview(self.lib,source);out=endnote_sync.export_exchange(self.lib,p,self.base/'Exchange',{})
        tree=ET.parse(out/'仅新增文献.xml');self.assertEqual(len(tree.findall('.//record')),1)
        self.assertEqual(tree.findtext('.//keywords/keyword'),'PaperQuick课题:课题A');self.assertTrue(tree.findtext('.//pdf-urls/url').startswith('file:///'))
    def test_stale_preview(self):
        source=self.base/'Source.enl';endnote(source);p=endnote_sync.preview(self.lib,source)
        with closing(sqlite3.connect(source)) as db, db:db.execute('UPDATE enl_refs SET notes="changed"')
        with self.assertRaises(ValueError):endnote_sync.export_exchange(self.lib,p,self.base/'No',{})
        self.assertFalse((self.base/'No').exists())
    def test_invalid_download_does_not_archive(self):
        source=self.base/'web.pdf';source.write_text('<html>Login</html>')
        rid=self.lib.save({'title':'X'})
        with self.assertRaises(ValueError):self.lib.attach(rid,source)
        self.assertFalse(self.lib.get(rid)['attachments'])
    def test_download_pdf_archives_and_cleans_staging(self):
        import io
        source=self.base/'real.pdf';pdf(source)
        rid=self.lib.save({'title':'Downloaded','doi':'10.1000/download'},self.project)
        fake=io.BytesIO(source.read_bytes())
        with patch('paper_finder.public_url'),patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=fake
            output=download_pdf(self.lib,rid,'https://example.org/a.pdf')
        self.assertTrue(output.is_file());self.assertFalse(list((self.lib.root/'staging').iterdir()))
        self.assertEqual(self.lib.get(rid)['doi'],'10.1000/download')
    def test_source_changes_after_preview_are_rejected(self):
        source=self.base/'Source.enl';endnote(source);endnote_sync.import_only(self.lib,endnote_sync.preview(self.lib,source))
        plan=endnote_sync.preview(self.lib,source);rid=self.lib.records()[0]['id'];self.lib.save({'notes':'later edit'},rid=rid)
        with self.assertRaises(ValueError):endnote_sync.export_exchange(self.lib,plan,self.base/'No',{})

if __name__=='__main__':unittest.main()
