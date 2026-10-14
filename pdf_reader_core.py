"""Local PDF rendering and text extraction using bundled PDFium."""
from pathlib import Path
import sys
import threading
_LOCK=threading.RLock()

def pdfium():
    try:import pypdfium2
    except ImportError:
        sys.path.insert(0,str(Path(__file__).parent/'build'/'vendor'));import pypdfium2
    return pypdfium2

def document_info(path):
    with _LOCK,pdfium().PdfDocument(path) as document:
        return len(document)

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

def extract_text(path):
    texts=[]
    with _LOCK,pdfium().PdfDocument(path) as document:
        # Include the tail of very long documents, where references normally occur.
        indices=range(len(document)) if len(document)<=100 else sorted(set(range(8))|set(range(len(document)-60,len(document))))
        for i in indices:
            page=document[i]
            try:
                textpage=page.get_textpage()
                try:texts.append(textpage.get_text_range()[:35000])
                finally:textpage.close()
            finally:page.close()
    combined='\n'.join(texts)
    return combined if len(combined)<=2_000_000 else combined[:800_000]+'\n'+combined[-1_200_000:]


def page_sizes(path):
    with _LOCK,pdfium().PdfDocument(path) as document:
        sizes=[]
        for i in range(len(document)):
            page=document[i]
            try:sizes.append(page.get_size())
            finally:page.close()
        return sizes


def _device_rect(page, rect):
    import ctypes
    points=[]
    for x,y in ((rect[0],rect[1]),(rect[2],rect[3])):
        px=ctypes.c_int();py=ctypes.c_int()
        pdfium().raw.FPDF_PageToDevice(page,0,0,10000,10000,0,float(x),float(y),ctypes.byref(px),ctypes.byref(py))
        points.append((px.value/10000,py.value/10000))
    return [min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]


def render_page_data(path, page_number, scale=1.3):
    """Return an image and per-character geometry, aligned after PDF rotation."""
    with _LOCK,pdfium().PdfDocument(path) as document:
        page=document[page_number]
        try:
            width,height=page.get_size();scale=min(scale,math_sqrt_limit(width,height))
            bitmap=page.render(scale=scale,draw_annots=True)
            try:image=bitmap.to_pil().copy()
            finally:bitmap.close()
            chars=[];tp=page.get_textpage()
            try:
                for i in range(min(tp.count_chars(),80000)):
                    code=pdfium().raw.FPDFText_GetUnicode(tp,i)
                    if not code:continue
                    try:box=_device_rect(page,tp.get_charbox(i))
                    except Exception:box=[0,0,0,0]
                    chars.append({'index':i,'text':chr(code),'rect':box})
            finally:tp.close()
            return image,chars
        finally:page.close()


def original_pdf_annotations(path):
    """Expose PDF popup contents and native highlights, not just their artwork."""
    from pypdf import PdfReader
    result=[];reader=PdfReader(path)
    with _LOCK,pdfium().PdfDocument(path) as document:
        for i,p in enumerate(reader.pages):
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
