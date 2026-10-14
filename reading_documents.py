"""Local text reading, original Word comments, and source-preserving text edits."""
from pathlib import Path
import hashlib
import json
import zipfile
import xml.etree.ElementTree as ET

DEFAULT_NOTE_TEMPLATE='研究问题：\n\n方法与数据：\n\n主要发现：\n\n局限与疑问：\n\n与我的课题的联系：\n'


def read_text_file(path):
    raw=Path(path).read_bytes()
    if len(raw)>12*1024*1024:raise ValueError('文本超过 12 MB，请拆分后导入。')
    if raw.startswith((b'\xff\xfe',b'\xfe\xff')):return raw.decode('utf-16')
    for encoding in ('utf-8-sig','gb18030'):
        try:return raw.decode(encoding)
        except UnicodeDecodeError:pass
    raise ValueError('无法识别文本编码，请另存为 UTF-8 后导入。')


def word_content(path):
    from document_conversion import _call
    return _call({'action':'read','source':str(Path(path).resolve())})


def edit_word_copy(path, raw_text, edited_text, destination):
    from document_conversion import _call
    import difflib
    edited_text=edited_text.replace('\r\n','\n').replace('\n','\r')
    if not edited_text.endswith('\r'):edited_text+='\r'
    changes=[]
    for tag,a,b,c,d in difflib.SequenceMatcher(None,raw_text,edited_text,autojunk=False).get_opcodes():
        if tag=='equal':continue
        if '\x07' in raw_text[a:b] or '\x07' in edited_text[c:d]:raise ValueError('请保留表格分隔符；修改单元格文字即可。')
        changes.append({'start':len(raw_text[:a].encode('utf-16-le'))//2,'end':len(raw_text[:b].encode('utf-16-le'))//2,'text':edited_text[c:d]})
    return _call({'action':'edit','source':str(Path(path).resolve()),'destination':str(Path(destination).absolute()),
                  'original_text':raw_text,'changes':changes})


def docx_comments(path):
    """Fast OOXML fallback, including comments anchored inside table paragraphs."""
    if Path(path).suffix.lower()!='.docx':return []
    w='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with zipfile.ZipFile(path) as archive:
        if 'word/comments.xml' not in archive.namelist():return []
        def xml(name):
            info=archive.getinfo(name)
            if info.file_size>24*1024*1024:raise ValueError('批注内容过大。')
            raw=archive.read(name);checked=raw.replace(b'\x00',b'').upper()
            if b'<!DOCTYPE' in checked or b'<!ENTITY' in checked:raise ValueError('批注包含不支持的 XML 定义。')
            return ET.fromstring(raw)
        comments=xml('word/comments.xml');document=xml('word/document.xml')
    active=set();quotes={}
    for element in document.iter():
        if element.tag==w+'commentRangeStart':active.add(element.get(w+'id'))
        elif element.tag==w+'commentRangeEnd':active.discard(element.get(w+'id'))
        elif element.tag==w+'t':
            for cid in active:quotes[cid]=quotes.get(cid,'')+(element.text or '')
    return [{'id':'original-word-'+c.get(w+'id',''),'kind':'原文件批注','original':True,'page':None,'rect':[.92,.05,.95,.08],
             'text':'\n'.join(''.join(t.text or '' for t in p.iter(w+'t')) for p in c.iter(w+'p')),
             'quote':quotes.get(c.get(w+'id'),''),'author':c.get(w+'author',''),'color':'#db9447','created':0} for c in comments.iter(w+'comment')]


def locate_word_comments(comments, path):
    """Recover comment pages from the selectable preview, without changing it."""
    from pdf_reader_core import pdfium,_LOCK
    import re
    clean=lambda s:re.sub(r'\s+','',s)
    unmatched=[c for c in comments if c.get('page') is None];texts=[]
    with _LOCK,pdfium().PdfDocument(path) as document:
        for i in range(len(document)):
            page=document[i]
            try:
                tp=page.get_textpage()
                try:text=tp.get_text_range()
                finally:tp.close()
            finally:page.close()
            texts.append(clean(text))
    for c in unmatched:
        q=clean(c.get('quote',''))
        c['page']=next((i for i,t in enumerate(texts) if q and q in t),0)
        c['location_verified']=bool(q and q in texts[c['page']])
    return comments


def valid_hyperlink(value):
    from urllib.parse import urlsplit
    value=str(value).strip()
    parsed=urlsplit(value)
    if parsed.scheme.lower() in ('http','https') and parsed.hostname and not any(ord(c)<33 for c in value):return ('url',value)
    if not parsed.scheme or (len(parsed.scheme)==1 and len(value)>2 and value[1]==':'):
        path=Path(value).expanduser().resolve()
        if path.is_file() and path.suffix.lower() in ('.pdf','.doc','.docx','.txt','.md'):return ('file',str(path))
    raise ValueError('请选择本地 PDF、Word、TXT 文档，或填写完整的 http:// / https:// 网址。')
