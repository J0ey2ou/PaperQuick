"""Display-only naming. This workflow never renames or writes any attachment file."""
from library_core import display_name, readable_attachments,validate_template
from metadata_renaming import extract_article_metadata, meaningful
from naming_rules import optional_name

FIELDS=('title','authors','venue','year','doi')


def display_template(library, project):
    return library.setting('display_name_template:'+project,library.setting('display_name_template','{标题}'))


def display_name_from_rule(fields, project_name, template='{标题}', title_length=500):
    validate_template(template)
    author=str(fields.get('authors') or '').split(';')[0].split('；')[0].split('\n')[0].strip()
    values={'title':str(fields.get('title') or '')[:title_length], 'author':author,
            'year':str(fields.get('year') or ''),'doi':str(fields.get('doi') or ''),
            'project':project_name,'journal':str(fields.get('venue') or '')}
    values.update(标题=values['title'],第一作者=author,年份=values['year'],DOI=values['doi'],课题=project_name,期刊=values['journal'],venue=values['journal'])
    return optional_name(template, values, fields.get('title') or '未命名文献')[:500]


def prepare_display_names(library, ids):
    plans=[]
    for rid in dict.fromkeys(ids):
        record=library.get(rid)
        fields={key:str(record.get(key) or '') for key in FIELDS}
        plan={'id':rid,'before':record,'fields':fields,'sources':{},'warnings':[],
              'display_name':display_name(record),'sync_metadata':False}
        primary=next((a for a in readable_attachments(record) if a.get('role')=='primary'),None)
        if primary:
            try:
                extracted=extract_article_metadata(library._managed_path(primary['path']))
                for key,value in extracted['fields'].items():
                    if key in FIELDS and meaningful(value):fields[key]=value
                plan['sources']=extracted['sources']
                if extracted['fields'].get('title'):plan['display_name']=extracted['fields']['title']
                if not extracted['fields'].get('title'):plan['warnings'].append('未可靠识别标题，可直接编辑显示名称。')
                if not extracted['fields'].get('authors'):plan['warnings'].append('未可靠识别作者，请核对或手动修正。')
            except Exception as exc:plan['warnings'].append('文件识别未完成：'+str(exc)+'；仍可手动修改显示名称。')
        else:plan['warnings'].append('没有正文附件，可直接手动修改显示名称。')
        plans.append(plan)
    return plans


def apply_display_names(library, plans):
    changed=0;errors=[]
    for plan in plans:
        try:
            name=str(plan['display_name']).strip()
            if not name or len(name)>500:raise ValueError('显示名称须为 1–500 字。')
            current=library.get(plan['id']);before=plan['before']
            if current.get('display_name')!=before.get('display_name'):
                raise ValueError('显示名称已被其他操作修改，请重新预览。')
            changes={'display_name':name}
            if plan.get('sync_metadata'):
                for key in FIELDS:
                    if current.get(key)!=before.get(key):raise ValueError('论文信息已变化，请重新预览。')
                    changes[key]=str(plan['fields'].get(key) or '').strip()
                if not changes['title']:raise ValueError('论文标题不能为空。')
            library.save(changes,rid=plan['id']);changed+=1
        except Exception as exc:errors.append(display_name(plan['before'])+'：'+str(exc))
    return {'count':changed,'errors':errors}
