"""Validated, attachment-scoped destinations inside local PDF documents."""
def destination(library,rid,page=0,point=(.05,.05),attachment_id=None,quote=''):
    record=library.get(rid)
    attachment=next((a for a in record['attachments'] if a['id']==attachment_id),None) if attachment_id else library.primary_attachment(rid)
    if not attachment or attachment.get('kind')!='pdf':raise ValueError('请选择已归档的 PDF 正文作为位置链接目标。')
    path=library._managed_path(attachment['path'])
    from pdf_reader_core import document_info
    count=document_info(path)
    if not isinstance(page,int) or isinstance(page,bool) or not 0<=page<count:raise ValueError(f'目标页码应在 1–{count} 页之间。')
    if len(point)!=2 or any(not isinstance(v,(int,float)) or not 0<=v<=1 for v in point):raise ValueError('目标位置无效。')
    return {'target':rid,'target_attachment':attachment['id'],'target_page':page,
            'target_point':list(point),'target_quote':str(quote)[:10000],'title':record['title']}
