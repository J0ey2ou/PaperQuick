import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from references import parse_references
from graph_style import validate_style,DEFAULT,score,appearance
from library_core import Library
from pdf_reader_core import document_info,render_page,extract_text

def text_pdf(path):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build'/'vendor'))
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    writer=PdfWriter()
    contents=[['Local literature reading demo','A fictional paper for testing the local PDF reader.','Notes are saved locally. No API or AI is used.'],
              ['References','[1] Doe, J. (2024). Protein structure prediction in health research.','Journal of Examples. DOI: 10.9999/not-collected',
               '[2] Roe, A. (2023). Population health prediction in cohort studies.','DOI: 10.9999/demo0']]
    for lines in contents:
        page=writer.add_blank_page(612,792)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();commands=['BT /F1 13 Tf 50 735 Td 24 TL']
        for i,line in enumerate(lines):
            escaped=line.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            commands.append(('T* ' if i else '')+f'({escaped}) Tj')
        commands.append('ET');stream.set_data('\n'.join(commands).encode('ascii'));page[NameObject('/Contents')]=writer._add_object(stream)
    writer.add_metadata({'/Title':'Local literature reading demo'})
    with open(path,'wb') as f:writer.write(f)

class ReaderTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[1]/'build'/'reader-tests';base.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=base);self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_render_and_extract_locally(self):
        path=self.base/'demo.pdf';text_pdf(path);self.assertEqual(document_info(path),2)
        image=render_page(path,0,.8);self.assertGreater(image.width,400);self.assertLess(image.height,1000)
        self.assertIn('References',extract_text(path));self.assertEqual(len(parse_references(extract_text(path))),2)
        with self.assertRaises(ValueError):render_page(path,2)
        from library_core import pdf_metadata
        self.assertEqual(pdf_metadata(path)['doi'],'')
    def test_references_are_not_invented(self):
        self.assertEqual(parse_references('This paper discusses references but has no bibliography.'),[])
        refs=parse_references('References\n[1] Doe, J. (2024). A long research paper title. DOI: 10.9999/example\n')
        self.assertEqual(refs[0]['doi'],'10.9999/example');self.assertIn('需核对',parse_references('References\n[1] Doe, J. (2024). A long research paper without a DOI.\n')[0]['confidence'])
    def test_candidates_are_separate_and_disappear_after_collection(self):
        lib=Library(self.base/'store')
        try:
            rid=lib.save({'title':'Source','text':'References\n[1] Doe, J. (2024). Long uncollected research paper title. DOI: 10.9999/missing\n'})
            graph=lib.graph();self.assertEqual(graph['summary']['total'],1);self.assertEqual(graph['summary']['candidates'],1)
            ghost=next(n for n in graph['nodes'] if not n['in_library']);self.assertFalse(ghost['pdf']);self.assertEqual(graph['edges'][-1]['kind'],'candidate')
            lib.save({'title':'Long uncollected research paper title','doi':'10.9999/missing'});graph=lib.graph();self.assertEqual(graph['summary']['candidates'],0);self.assertTrue(any(e['kind']=='citation' for e in graph['edges']))
        finally:lib.close()
    def test_highlight_validation_and_counters(self):
        node={'in_library':True,'read_count':4,'citation_count':8,'pdf':True}
        style=validate_style(dict(DEFAULT,mode='read_count'));self.assertGreater(score(node,style),0)
        color,radius=appearance(node,style,score(node,style));self.assertEqual(color,style['high']);self.assertEqual(radius,8)
        with self.assertRaises(ValueError):validate_style({'low':'oops'})
        with self.assertRaises(ValueError):validate_style({'read_weight':'nan'})

if __name__=='__main__':unittest.main()
