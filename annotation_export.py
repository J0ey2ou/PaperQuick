"""Export a PDF copy with popup comments and remote PDF position links."""
from pathlib import Path


def pdf_point(page,point):
    x,y=point;box=page.cropbox;w,h=float(box.width),float(box.height)
    rotation=int(page.get('/Rotate',0))%360
    if rotation==90:px,py=y*w,x*h
    elif rotation==180:px,py=(1-x)*w,y*h
    elif rotation==270:px,py=(1-y)*w,(1-x)*h
    else:px,py=x*w,(1-y)*h
    return float(box.left)+px,float(box.bottom)+py


def export_pdf(library,rid,attachment_id,output):
    from pypdf import PdfReader,PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,ArrayObject,FloatObject,TextStringObject,NumberObject,BooleanObject,NullObject
    record=library.get(rid);attachment=next(a for a in record['attachments'] if a['id']==attachment_id)
    if attachment.get('kind')!='pdf':raise ValueError('请在 PDF 正文中导出批注。')
    source=library._managed_path(attachment['path']);output=Path(output).resolve()
    if output.suffix.lower()!='.pdf':raise ValueError('请选择 PDF 输出文件。')
    if output.is_relative_to(library.root):raise ValueError('请将导出副本保存在文献库之外，以保留归档原文件。')
    comments=links=0
    with source.open('rb') as stream:
        reader=PdfReader(stream);writer=PdfWriter();writer.append(reader)
        for item in record.get('annotations',[]):
            if item.get('attachment')!=attachment_id or not 0<=item.get('page',-1)<len(writer.pages):continue
            page=writer.pages[item['page']];x,y=pdf_point(page,item.get('rect',[.05,.05])[:2])
            rect=ArrayObject([FloatObject(x),FloatObject(y-20),FloatObject(x+20),FloatObject(y)])
            comment=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Text'),
                NameObject('/Rect'):rect,NameObject('/Contents'):TextStringObject('\n\n'.join(v for v in [item.get('quote',''),item.get('text',''),item.get('chat_url','')] if v)),
                NameObject('/T'):TextStringObject('PaperQuick'),NameObject('/Name'):NameObject('/Comment')})
            if item.get('target') and 'target_page' in item:
                from document_links import destination
                target=destination(library,item['target'],item['target_page'],item.get('target_point',[.05,.05]),item.get('target_attachment'))
                target_record=library.get(target['target']);a=next(a for a in target_record['attachments'] if a['id']==target['target_attachment'])
                path=library._managed_path(a['path'])
                with path.open('rb') as target_stream:
                    target_reader=PdfReader(target_stream);tx,ty=pdf_point(target_reader.pages[target['target_page']],target['target_point'])
                comment[NameObject('/Subtype')]=NameObject('/Link')
                comment[NameObject('/Border')]=ArrayObject([NumberObject(0),NumberObject(0),NumberObject(1)])
                comment[NameObject('/A')]=DictionaryObject({NameObject('/S'):NameObject('/GoToR'),NameObject('/F'):TextStringObject(str(path)),
                    NameObject('/D'):ArrayObject([NumberObject(target['target_page']),NameObject('/XYZ'),FloatObject(tx),FloatObject(ty),NullObject()]),NameObject('/NewWindow'):BooleanObject(True)})
                links+=1
            else:comments+=1
            writer.add_annotation(item['page'],comment)
        temporary=output.with_name(output.name+'.partial')
        try:
            with temporary.open('wb') as result:writer.write(result)
            temporary.replace(output)
        finally:temporary.unlink(missing_ok=True)
    return {'comments':comments,'links':links,'path':str(output)}
