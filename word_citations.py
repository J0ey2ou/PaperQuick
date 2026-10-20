"""Plan complete CSL reformatting before making a single Word edit."""
from copy import deepcopy
import uuid
from citation_metadata import to_csl


def citation_label(field):
    items=field.get('payload',{}).get('items',[])
    return '; '.join(item.get('itemData',{}).get('title',item.get('id','未命名')) for item in items)


def plan_changes(snapshot,records,style_id,action='refresh',selected=None,target_id=None,locator='',formatter=None,custom_dir=None,auto_bibliography=True):
    """Create only PaperQuick field changes; document order determines numbering."""
    if formatter is None:
        from citation_styles import format_document
        formatter=format_document
    fields=deepcopy(snapshot.get('fields',[]));selected=selected or []
    citations=[f for f in fields if f['kind']=='citation'];bibliographies=[f for f in fields if f['kind']=='bibliography']
    ids=[f['id'] for f in fields]
    if len(ids)!=len(set(ids)):raise ValueError('文档中有重复复制的引文标记。请删除重复引文，再通过文献直达重新插入。')
    for field in citations:
        if not field.get('payload',{}).get('items'):raise ValueError('有一处引文信息不完整。请在 Word 中删除该引文，再重新插入。')
    insertion=None;removed=[]
    if action in ('insert','replace'):
        if not selected:raise ValueError('请先选择至少一篇要引用的文献。')
        if len(selected)>50:raise ValueError('一次最多合并引用 50 篇文献。')
        items=[]
        for record in selected:
            data=to_csl(record)
            if not any(item['id']==data['id'] for item in items):
                item={'id':data['id'],'itemData':data}
                if locator.strip():item.update(locator=locator.strip(),label='page')
                items.append(item)
        if action=='replace':
            target=next((field for field in citations if field['id']==target_id),None)
            if target is None:raise ValueError('这处引文已发生变化，请重新读取 Word 文档。')
            target['payload']['items']=items
        else:
            point=snapshot['selection']['start']
            if any(f['start']<=point<f['end'] for f in fields):raise ValueError('光标位于已有引文或参考文献表中。请移到正文空白处，或使用“替换这处引文”。')
            payload={'version':1,'id':uuid.uuid4().hex,'style_id':style_id,'items':items}
            insertion={'kind':'citation','id':payload['id'],'payload':payload,'start':point}
            citations.append(insertion)
    elif action=='remove':
        target=next((field for field in citations if field['id']==target_id),None)
        if target is None:raise ValueError('请先选择文档中要删除的引文。')
        citations.remove(target);removed=[target_id]
    elif action not in ('refresh','bibliography'):raise ValueError('未知引用操作。')
    citations.sort(key=lambda field:field['start'])
    current={}
    for record in records:
        value=to_csl(record);current[value['id']]=value
    items={};clusters=[]
    for field in citations:
        cluster=[]
        for item in field['payload']['items']:
            identifier=item['id'];data=current.get(identifier) or item.get('itemData')
            if not data:raise ValueError('部分引文缺少文献信息。请从文献库重新选择并替换。')
            item['itemData']=deepcopy(data);items[identifier]=deepcopy(data)
            cluster.append({key:value for key,value in item.items() if key in ('id','locator','label','prefix','suffix','suppress-author','author-only')})
        field['payload']['style_id']=style_id
        clusters.append({'id':field['id'],'items':cluster,'noteIndex':0})
    if not clusters and action=='bibliography':raise ValueError('先在正文插入至少一处引文，再生成参考文献表。')
    formatted=formatter(items,clusters,style_id,custom_dir=custom_dir)
    if formatted.get('style_class')=='note':raise ValueError('这个样式使用脚注。当前版本支持正文引文，请选择作者年份或数字编号样式。')
    operations={'updates':[],'remove':removed}
    for field in citations:
        change={'id':field['id'],'payload':field['payload'],'result_rtf':formatted['citations'][field['id']]}
        if field is insertion:operations['insert']=dict(change,kind='citation')
        else:operations['updates'].append(change)
    for field in bibliographies:
        if not citations:
            removed.append(field['id']);continue
        payload=dict(field.get('payload',{}),version=1,id=field['id'],style_id=style_id)
        operations['updates'].append({'id':field['id'],'payload':payload,'result_rtf':formatted['bibliography']})
    if action=='bibliography' and not bibliographies:
        point=snapshot['selection']['start']
        if any(f['start']<=point<f['end'] for f in fields):raise ValueError('请将 Word 光标移到正文引文之外，作为参考文献表的位置。')
        payload={'version':1,'id':uuid.uuid4().hex,'style_id':style_id}
        operations['insert']={'kind':'bibliography','id':payload['id'],'payload':payload,'result_rtf':formatted['bibliography']}
    elif auto_bibliography and citations and not bibliographies:
        payload={'version':1,'id':uuid.uuid4().hex,'style_id':style_id}
        operations['append_bibliography']={'kind':'bibliography','id':payload['id'],'payload':payload,'result_rtf':formatted['bibliography']}
    return operations,formatted
