"""Import recovery, rich note linkage, and BMJ-style bibliography regressions."""
from pathlib import Path
import sys,tempfile,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_core import Library,digest,readable_attachments,document_metadata
from references import parse_references
from reading_documents import read_text_file,docx_comments,edit_word_copy,valid_hyperlink
from pdf_reader_core import render_page_data,original_pdf_annotations
from test_reader import text_pdf


class ReaderUpgradeTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[1]/'build'/'reader-upgrade-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.base=Path(self.temp.name);self.lib=Library(self.base/'store');self.pid=self.lib.projects()[0]['id']
    def tearDown(self):self.lib.close();self.temp.cleanup()
    def test_bmj_no_heading_and_doi_wraps_without_year_nodes(self):
        text='Research body\nFunding: example\n1 World Organization. Public report. 2025.\n2 Lee A. A fictional population study. Lancet 2025;405:1-8. doi:10.1016/S0140-\n6736(25)00151-\n5.\n3 Doe J. Cohort example. BMJ 2026;393:e00001. doi:10.1136/bmj\ufffe2025-00001\n4 Roe T. Data research. J Epidemiol 2021;53:1-3. doi:10.1016/\nS2214-109X(14)70280-3.\nWeb appendix: Supplementary appendix'
        refs=parse_references(text);self.assertEqual([r['number'] for r in refs],['1','2','3','4'])
        self.assertEqual(len(parse_references('Web appendix: Earlier body mention\nSome methods\n'+text)),4)
        self.assertEqual(len(parse_references('References\n14 Riffle T, Lima E. Riffe T, Lima E (2017). DDM: Registration coverage. R package version 1.0. 2017.')),1)
        self.assertEqual(refs[1]['doi'],'10.1016/S0140-6736(25)00151-5');self.assertEqual(refs[2]['doi'],'10.1136/bmj-2025-00001');self.assertEqual(refs[3]['doi'],'10.1016/S2214-109X(14)70280-3')
        self.assertEqual(parse_references('1. First instruction in 2024\n2. Second instruction in 2025\n3. Third instruction in 2026'),[])
    def test_chinese_spaced_heading_and_full_width_numbers(self):
        refs=parse_references('参 考 文 献\n［1］ 张三,李四. 饮食模式与研究方法[J]. 示例期刊,2024.\n［2］ 王五. 人群研究的新资料[J]. 示例期刊,2025.')
        self.assertEqual(len(refs),2);self.assertEqual(refs[0]['number'],'1');self.assertEqual(refs[0]['title'],'饮食模式与研究方法')
    def test_undo_batch_keeps_subsequently_edited_paper_and_original_sources(self):
        a=self.base/'a.txt';b=self.base/'b.txt';a.write_text('First paper',encoding='utf-8');b.write_text('Second paper',encoding='utf-8')
        batch=self.lib.import_batch([a,b],self.pid);self.assertEqual(batch['count'],2)
        records=self.lib.records();keep=next(r for r in records if r['title']=='a');self.lib.save({'notes':'New research notes'},rid=keep['id'])
        result=self.lib.undo_import(batch['batch']);self.assertEqual(result,{'restored':1,'kept':1});self.assertEqual(len(self.lib.records()),1);self.assertEqual(self.lib.get(keep['id'])['notes'],'New research notes');self.assertTrue(a.is_file() and b.is_file())
        self.assertTrue(list((self.lib.root/'trash').rglob('*.txt')))
    def test_undo_duplicate_restores_original_membership(self):
        source=self.base/'a.txt';source.write_text('First paper',encoding='utf-8');rid=self.lib.import_document(source,self.pid)
        other=self.lib.create_project('Another project');batch=self.lib.import_batch([source,source],other)
        self.assertIn(other,self.lib.get(rid)['projects']);self.lib.undo_import(batch['batch']);self.assertEqual(self.lib.get(rid)['projects'],[self.pid]);self.assertTrue((self.lib.root/self.lib.primary_attachment(rid)['path']).is_file())
    def test_remove_restore_keeps_notes_files_and_relations(self):
        source=self.base/'a.txt';source.write_text('First paper',encoding='utf-8');rid=self.lib.import_document(source)
        target=self.lib.save({'title':'Related paper'});self.lib.relate(rid,target);self.lib.save({'notes':'Preserve me'},rid=rid);path=self.lib.root/self.lib.primary_attachment(rid)['path']
        self.assertEqual(self.lib.remove_papers([rid]),1);self.assertFalse(path.exists());self.assertTrue(source.exists());self.assertEqual(len(self.lib.records()),1)
        self.assertEqual(self.lib.restore_removed(),1);self.assertTrue(path.exists());self.assertEqual(self.lib.get(rid)['notes'],'Preserve me');self.assertEqual(len(self.lib.relation_edges({rid,target})),1)
    def test_note_nodes_and_bmj_citations_are_distinct(self):
        rid=self.lib.save({'title':'Source','text':'1 Doe A. First reference. J Med 2024;1:2. doi:10.1234/one\n2 Roe B. Second reference. J Med 2025;2:3. doi:10.1234/two\n3 Ray C. Third reference. J Med 2026;3:4. doi:10.1234/three'})
        target=self.lib.save({'title':'Target','doi':'10.1234/two'});self.lib.relate(rid,target)
        note=self.base/'note.md';note.write_text('Reading notes',encoding='utf-8');self.lib._add_attachment(rid,note,'笔记',role='note')
        graph=self.lib.graph();self.assertEqual(graph['summary']['total'],2);self.assertEqual(sum(n.get('kind')=='note' for n in graph['nodes']),1)
        self.assertTrue(any(e['kind']=='citation' and e['target']==target for e in graph['edges']));self.assertTrue(any(e['kind']=='note' for e in graph['edges']));self.assertTrue(any(e['kind']=='related' for e in graph['edges']))
    def test_recovery_keeps_new_reading_sessions_when_ids_were_reused(self):
        rid=self.lib.save({'title':'Removed paper'});other=self.lib.save({'title':'Reading paper'})
        with self.lib.db:self.lib.db.execute('INSERT INTO reading_sessions VALUES(1,?,?,?)',(rid,10,20))
        self.lib.remove_papers([rid])
        with self.lib.db:self.lib.db.execute('INSERT INTO reading_sessions VALUES(1,?,?,?)',(other,30,40))
        self.lib.restore_removed();rows=self.lib.db.execute('SELECT paper,start FROM reading_sessions ORDER BY start').fetchall();self.assertEqual([(r['paper'],r['start']) for r in rows],[(rid,10),(other,30)])
    def test_txt_encodings_and_readable_primary(self):
        for encoding in ('utf-8','utf-16','gb18030'):
            source=self.base/(encoding+'.txt');source.write_bytes('中文研究笔记'.encode(encoding));self.assertEqual(read_text_file(source),'中文研究笔记');rid=self.lib.import_document(source);self.assertTrue(readable_attachments(self.lib.get(rid)))
    def test_word_comments_preserve_scope_and_author(self):
        source=self.base/'comments.docx';w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        with zipfile.ZipFile(source,'w') as z:
            z.writestr('word/document.xml',f'<w:document xmlns:w="{w}"><w:body><w:p><w:commentRangeStart w:id="7"/><w:r><w:t>Original passage</w:t></w:r><w:commentRangeEnd w:id="7"/></w:p></w:body></w:document>')
            z.writestr('word/comments.xml',f'<w:comments xmlns:w="{w}"><w:comment w:id="7" w:author="Researcher"><w:p><w:r><w:t>Original comment</w:t></w:r></w:p></w:comment></w:comments>')
        item=docx_comments(source)[0];self.assertEqual(item['quote'],'Original passage');self.assertEqual(item['text'],'Original comment');self.assertEqual(item['author'],'Researcher')
    def test_pdf_glyph_geometry_and_native_comment(self):
        source=self.base/'page.pdf';text_pdf(source);image,chars=render_page_data(source,0,1)
        self.assertIn('Local literature',''.join(c['text'] for c in chars));self.assertTrue(any(0<c['rect'][0]<c['rect'][2]<1 for c in chars));self.assertEqual(image.width,612)
        from pypdf import PdfReader,PdfWriter
        from pypdf.annotations import Text
        writer=PdfWriter(clone_from=source);writer.add_annotation(0,Text(rect=(80,600,100,620),text='Existing PDF comment'));out=self.base/'commented.pdf'
        with out.open('wb') as f:writer.write(f)
        self.assertEqual(original_pdf_annotations(out)[0]['text'],'Existing PDF comment')
    def test_word_edit_uses_utf16_ranges_and_rejects_table_markers(self):
        with patch('document_conversion._call',return_value={}) as call:
            edit_word_copy('source.docx','A😀 old\r','A😀 new\n','result.docx');request=call.call_args.args[0]
            self.assertEqual(request['changes'][0]['start'],4);self.assertEqual(request['changes'][0]['text'],'new')
        with self.assertRaises(ValueError):edit_word_copy('source.docx','cell\x07\r','cell\n','result.docx')
    def test_document_edit_preserves_source_and_previous_managed_version(self):
        source=self.base/'source.txt';source.write_text('Original',encoding='utf-8');rid=self.lib.import_document(source);a=self.lib.primary_attachment(rid);managed=self.lib.root/a['path'];staged=self.base/'edited.txt';staged.write_text('Edited',encoding='utf-8')
        self.lib.replace_document(rid,a['id'],staged,digest(managed));self.assertEqual(source.read_text('utf-8'),'Original');self.assertEqual(managed.read_text('utf-8'),'Edited');self.assertEqual(next((self.lib.root/'versions').rglob('*.txt')).read_text('utf-8'),'Original')
        with self.assertRaises(ValueError):self.lib.replace_document(rid,a['id'],staged,'old-hash')
    def test_links_reject_executables_and_unsafe_schemes(self):
        self.assertEqual(valid_hyperlink('https://example.org/paper')[0],'url')
        for value in ('javascript:alert(1)','file:///C:/bad.exe','https://example.org/\n'):
            # Whitespace at the end is normalized, but control bytes inside URLs are rejected.
            if value.endswith('/\n'):value='https://example.org/a\nb'
            with self.assertRaises(ValueError):valid_hyperlink(value)

if __name__=='__main__':unittest.main()
