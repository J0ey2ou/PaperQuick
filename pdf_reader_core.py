"""Local PDF rendering and text extraction using bundled PDFium."""
from pathlib import Path
from collections import OrderedDict
from copy import deepcopy
import sys
import threading
_LOCK=threading.RLock()
_CACHE_LOCK=threading.RLock()
_CACHE=OrderedDict()
_CACHE_BYTES=0
_CACHE_LIMIT=32*1024*1024


class DocumentReadCancelled(Exception):
    pass


class DocumentChangedError(ValueError):
    def __init__(self):
        super().__init__('文档在读取时已改变，请重新打开。')


def _check_cancel(cancelled):
    if cancelled is not None and cancelled():raise DocumentReadCancelled()


def file_version(path):
    """Identify the local file revision; streams remain usable without caching."""
    try:
        path=Path(path).resolve();stat=path.stat()
        return (str(path),stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
    except (TypeError,ValueError,OSError):return None


def clear_document_cache():
    global _CACHE_BYTES
    with _CACHE_LOCK:_CACHE.clear();_CACHE_BYTES=0


def _cached(key):
    with _CACHE_LOCK:
        entry=_CACHE.get(key)
        if entry is not None:_CACHE.move_to_end(key);return entry[0]
    return None


def _remember(path,version,kind,value,weight,page=None):
    global _CACHE_BYTES
    if version is None:return
    if file_version(path)!=version:raise DocumentChangedError()
    key=(kind,version,page)
    with _CACHE_LOCK:
        # Drop earlier revisions of this file, including their character layers.
        for old in list(_CACHE):
            if old[1][0]==version[0] and old[1]!=version:
                _CACHE_BYTES-=_CACHE.pop(old)[1]
        previous=_CACHE.pop(key,None)
        if previous:_CACHE_BYTES-=previous[1]
        if weight>_CACHE_LIMIT:return
        _CACHE[key]=(value,weight);_CACHE_BYTES+=weight
        while _CACHE_BYTES>_CACHE_LIMIT or len(_CACHE)>256:
            _,(_,size)=_CACHE.popitem(last=False);_CACHE_BYTES-=size

def pdfium():
    try:import pypdfium2
    except ImportError:
        sys.path.insert(0,str(Path(__file__).parent/'build'/'vendor'));import pypdfium2
    return pypdfium2

def document_info(path):
    version=file_version(path);cached=_cached(('count',version,None)) if version else None
    if cached is not None:return cached
    with _LOCK,pdfium().PdfDocument(path) as document:
        count=len(document)
    _remember(path,version,'count',count,64)
    return count

def render_page(path,page_number,scale=1.3):
    with _LOCK,pdfium().PdfDocument(path) as document:
        if not 0<=page_number<len(document):raise ValueError('页码超出范围。')
        page=document[page_number]
        try:
            width,height=page.get_size()
            scale=min(scale,math_sqrt_limit(width,height))
            bitmap=page.render(scale=scale)
            try:return bitmap.to_pil().copy()
            finally:bitmap.close()
        finally:page.close()

def math_sqrt_limit(width,height):
    import math
    return math.sqrt(12_000_000/max(1,width*height))

def extract_text(path,cancelled=None):
    _check_cancel(cancelled)
    version=file_version(path);cached=_cached(('text',version,None)) if version else None
    if cached is not None:return cached
    texts=[]
    with _LOCK:document=pdfium().PdfDocument(path);count=len(document)
    try:
        # Include the tail of very long documents, where references normally occur.
        indices=range(count) if count<=100 else sorted(set(range(8))|set(range(count-60,count)))
        for i in indices:
            _check_cancel(cancelled)
            # A document belongs to this worker, but every PDFium call remains
            # serialized. Release the lock between pages for visible rendering.
            with _LOCK:
                page=document[i]
                try:
                    textpage=page.get_textpage()
                    try:texts.append(textpage.get_text_range()[:35000])
                    finally:textpage.close()
                finally:page.close()
    finally:
        with _LOCK:document.close()
    combined='\n'.join(texts)
    combined=combined if len(combined)<=2_000_000 else combined[:800_000]+'\n'+combined[-1_200_000:]
    _remember(path,version,'text',combined,len(combined)*4+64)
    return combined


def page_sizes(path):
    version=file_version(path);cached=_cached(('sizes',version,None)) if version else None
    if cached is not None:return list(cached)
    with _LOCK,pdfium().PdfDocument(path) as document:
        # Page-tree metadata does not need to load/render each page's contents.
        sizes=tuple(document.get_page_size(i) for i in range(len(document)))
    _remember(path,version,'sizes',sizes,len(sizes)*96+64)
    _remember(path,version,'count',len(sizes),64)
    return list(sizes)


def _device_rect(page, rect):
    import ctypes
    points=[]
    for x,y in ((rect[0],rect[1]),(rect[2],rect[3])):
        px=ctypes.c_int();py=ctypes.c_int()
        pdfium().raw.FPDF_PageToDevice(page,0,0,10000,10000,0,float(x),float(y),ctypes.byref(px),ctypes.byref(py))
        points.append((px.value/10000,py.value/10000))
    return [min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]


def _page_characters(page):
    chars=[];tp=page.get_textpage()
    try:
        for i in range(min(tp.count_chars(),80000)):
            code=pdfium().raw.FPDFText_GetUnicode(tp,i)
            if not code:continue
            try:box=_device_rect(page,tp.get_charbox(i))
            except Exception:box=[0,0,0,0]
            chars.append((i,chr(code),tuple(box)))
    finally:tp.close()
    return tuple(chars)


def _copy_characters(chars):
    return [{'index':index,'text':text,'rect':list(rect)} for index,text,rect in chars]


def page_characters(path,page_number):
    """Scale-independent text geometry; no bitmap is needed for selection."""
    version=file_version(path);chars=_cached(('chars',version,page_number)) if version else None
    if chars is None:
        with _LOCK,pdfium().PdfDocument(path) as document:
            page=document[page_number]
            try:chars=_page_characters(page)
            finally:page.close()
        _remember(path,version,'chars',chars,len(chars)*256+64,page_number)
    return _copy_characters(chars)


def render_page_data(path, page_number, scale=1.3):
    """Return an image and per-character geometry, aligned after PDF rotation."""
    version=file_version(path);chars=_cached(('chars',version,page_number)) if version else None
    with _LOCK,pdfium().PdfDocument(path) as document:
        page=document[page_number]
        try:
            width,height=page.get_size();scale=min(scale,math_sqrt_limit(width,height))
            bitmap=page.render(scale=scale,draw_annots=True)
            try:image=bitmap.to_pil().copy()
            finally:bitmap.close()
            if chars is None:chars=_page_characters(page)
        finally:page.close()
    _remember(path,version,'chars',chars,len(chars)*256+64,page_number)
    return image,_copy_characters(chars)


def prepare_page(path,page_number,scale=1.3,fit_width=0,min_scale=.45):
    """Keep page geometry, bitmap and UI result tied to one file revision."""
    version=file_version(path);sizes=page_sizes(path);count=len(sizes)
    if not count:raise ValueError('文档没有可阅读的页面。')
    page=max(0,min(page_number,count-1))
    if fit_width:scale=max(min_scale,min(3,fit_width/sizes[page][0]))
    image,chars=render_page_data(path,page,scale)
    if version is not None and file_version(path)!=version:raise DocumentChangedError()
    return count,page,image,chars,sizes,scale,version


def original_pdf_annotations(path,cancelled=None):
    """Expose PDF popup contents and native highlights, not just their artwork."""
    _check_cancel(cancelled)
    version=file_version(path);cached=_cached(('annotations',version,None)) if version else None
    if cached is not None:return deepcopy(cached)
    from pypdf import PdfReader
    result=[];reader=PdfReader(path)
    with _LOCK:document=pdfium().PdfDocument(path)
    try:
        for i,p in enumerate(reader.pages):
            _check_cancel(cancelled)
            if not p.get('/Annots'):continue
            with _LOCK:
                page=document[i]
                try:
                    for j,ref in enumerate(p.get('/Annots',[])):
                        a=ref.get_object();subtype=str(a.get('/Subtype',''))
                        if subtype not in ('/Text','/FreeText','/Highlight','/Underline','/StrikeOut','/Link'):continue
                        rect=a.get('/Rect',[0,0,0,0]);uri=str((a.get('/A') or {}).get('/URI',''))
                        contents=str(a.get('/Contents','')).strip()
                        if not contents and not uri and subtype in ('/Text','/FreeText'):continue
                        result.append({'id':f'original-pdf-{i}-{j}','page':i,'rect':_device_rect(page,list(map(float,rect))),
                                       'kind':'原文件链接' if uri else '原文件批注','text':contents,'quote':'','author':str(a.get('/T','')),
                                       'color':'#db9447','original':True,'url':uri,'created':0})
                finally:page.close()
    finally:
        with _LOCK:document.close()
    _remember(path,version,'annotations',deepcopy(result),sum(512+len(a['text'])*4 for a in result)+64)
    return result


def region_text(path,page_number,rect):
    """Extract selected area in normalized rendered-page coordinates, including rotation."""
    import ctypes
    with _LOCK,pdfium().PdfDocument(path) as document:
        page=document[page_number]
        try:
            width,height=page.get_size();points=[]
            for x,y in ((rect[0],rect[1]),(rect[2],rect[3])):
                px=ctypes.c_double();py=ctypes.c_double()
                pdfium().raw.FPDF_DeviceToPage(page,0,0,round(width*10),round(height*10),0,round(x*width*10),round(y*height*10),ctypes.byref(px),ctypes.byref(py))
                points.append((px.value,py.value))
            textpage=page.get_textpage()
            try:return textpage.get_text_bounded(left=min(p[0] for p in points),bottom=min(p[1] for p in points),right=max(p[0] for p in points),top=max(p[1] for p in points)).strip()
            finally:textpage.close()
        finally:page.close()
