"""Integration check in an isolated, hidden Word process using owned fixtures."""
from pathlib import Path
import sys,zipfile,xml.etree.ElementTree as ET,json
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE));sys.path.insert(0,str(BASE/'build/vendor'));sys.path.insert(0,str(BASE/'tests'))
from test_reader import text_pdf
from document_conversion import convert_document,health,preview_pdf
from reading_documents import word_content,edit_word_copy,docx_comments
from library_core import digest
from pdf_reader_core import extract_text

folder=BASE/'build/word-reader-upgrade';folder.mkdir(exist_ok=True);pdf=folder/'fixture.pdf';source=folder/'source.docx';edited=folder/'edited.docx'
text_pdf(pdf)
if source.exists():source.unlink()
if edited.exists():edited.unlink()
convert_document(pdf,source)
w='http://schemas.openxmlformats.org/wordprocessingml/2006/main';rel='http://schemas.openxmlformats.org/package/2006/relationships';ct='http://schemas.openxmlformats.org/package/2006/content-types'
with zipfile.ZipFile(source) as z:files={name:z.read(name) for name in z.namelist()}
document=ET.fromstring(files['word/document.xml']);p=next(document.iter('{'+w+'}p'));p.insert(0,ET.Element('{'+w+'}commentRangeStart',{'{'+w+'}id':'0'}));p.append(ET.Element('{'+w+'}commentRangeEnd',{'{'+w+'}id':'0'}));r=ET.SubElement(p,'{'+w+'}r');ET.SubElement(r,'{'+w+'}commentReference',{'{'+w+'}id':'0'})
files['word/document.xml']=ET.tostring(document,encoding='utf-8',xml_declaration=True)
rels=ET.fromstring(files['word/_rels/document.xml.rels']);ET.SubElement(rels,'{'+rel+'}Relationship',{'Id':'reader-comments','Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments','Target':'comments.xml'});files['word/_rels/document.xml.rels']=ET.tostring(rels,encoding='utf-8',xml_declaration=True)
types=ET.fromstring(files['[Content_Types].xml']);ET.SubElement(types,'{'+ct+'}Override',{'PartName':'/word/comments.xml','ContentType':'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml'});files['[Content_Types].xml']=ET.tostring(types,encoding='utf-8',xml_declaration=True)
files['word/comments.xml']=f'<w:comments xmlns:w="{w}"><w:comment w:id="0" w:author="Fixture researcher"><w:p><w:r><w:t>Original Word comment preserved.</w:t></w:r></w:p></w:comment></w:comments>'.encode()
with zipfile.ZipFile(source,'w') as z:
 for name,data in files.items():z.writestr(name,data)
before=digest(source);print('WORD',health(),flush=True);original=word_content(source);assert original['comments'] and 'Original Word comment' in original['comments'][0]['text'];print('COMMENT READ',flush=True)
changed=original['text'].replace('Local literature reading demo','Edited literature reading demo',1);assert changed!=original['text'];edit_word_copy(source,original['text'],changed,edited)
after=word_content(edited);assert 'Edited literature reading demo' in after['text'];assert after['comments'];assert digest(source)==before;assert docx_comments(edited)
preview=preview_pdf(edited,folder/'previews');assert 'Edited literature reading demo' in extract_text(preview)
report={'passed':True,'checks':['Word original comment read','in-reader text edit transport','comment preserved after edit','original source unchanged','edited Word PDF preview'],'source':source.name,'edited':edited.name}
(folder/'check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)
