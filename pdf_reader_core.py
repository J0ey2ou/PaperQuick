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
