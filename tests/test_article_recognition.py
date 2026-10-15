from pathlib import Path
import tempfile
import unittest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from metadata_renaming import extract_article_metadata,author_line


def article_pdf(path, title=None):
    writer=PdfWriter();page=writer.add_blank_page(600,800)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    lines=[(30,780,'Downloaded from a publisher by guest'),(28,750,'+ Supplemental content'),
           (10,720,'Original Investigation'),(18,680,'Regional factors and avoidable'),(18,655,'hospital admissions in older adults'),
           (11,620,'Alice Smith1, PhD; Bob Jones2, MPH'),(10,590,'Department of Public Health'),(14,550,'Abstract'),
           (10,520,'This is a synthetic article body.'),(20,60,'An update to this article is included at the end')]
    text='\n'.join(f'BT /F1 1 Tf {size} 0 0 {size} 50 {y} Tm ({line}) Tj ET' for size,y,line in lines)
    stream=DecodedStreamObject();stream.set_data(text.encode('ascii'));page[NameObject('/Contents')]=writer._add_object(stream)
    if title:writer.add_metadata({'/Title':title,'/Author':'Office User'})
    with path.open('wb') as out:writer.write(out)


class ArticleRecognitionTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'build'/'recognition-tests';root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root);self.path=Path(self.tmp.name)/'random.pdf'
    def tearDown(self):self.tmp.cleanup()

    def test_scaled_fonts_multiline_title_and_byline_ignore_large_watermarks(self):
        article_pdf(self.path,'Unrelated metadata from conversion')
        fields=extract_article_metadata(self.path)['fields']
        self.assertEqual(fields['title'],'Regional factors and avoidable hospital admissions in older adults')
        self.assertEqual(fields['authors'],'Alice Smith; Bob Jones')

    def test_real_pdf_title_metadata_is_preserved_when_it_matches_the_body(self):
        title='Regional factors and avoidable hospital admissions in older adults'
        article_pdf(self.path,title)
        self.assertEqual(extract_article_metadata(self.path)['fields']['title'],title)

    def test_byline_handles_initials_degrees_chinese_names_and_superscripts(self):
        self.assertEqual(author_line('S. Purdy; T. Griffin'),'S. Purdy; T. Griffin')
        self.assertEqual(author_line('Alice Smith¹, PhD; Bob Jones², MPH'),'Alice Smith; Bob Jones')
        self.assertEqual(author_line('张三 李四 王五'),'张三; 李四; 王五')
        self.assertEqual(author_line('Department of Public Health'),'')


if __name__=='__main__':unittest.main()
