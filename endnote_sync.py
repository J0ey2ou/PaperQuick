"""Read-only offline EndNote adapter, three-way preview and XML exchange.
Project associations use portable keyword lines, not undocumented group blobs.
Existing EndNote updates remain manual; proprietary SQLite indices are never edited.
"""
from pathlib import Path
from contextlib import closing
import json
import shutil
import sqlite3
import time
import uuid
import html
import xml.etree.ElementTree as ET
from library_core import normalize_doi, FIELDS, digest

MAP = {'title': 'title', 'authors': 'author', 'year': 'year', 'doi': 'electronic_resource_number',
       'venue': 'secondary_title', 'abstract': 'abstract', 'keywords': 'keywords', 'notes': 'notes'}
PROJECT_PREFIX = 'PaperQuick课题:'

def connect_read(path):
    path = Path(path).resolve()
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    return db

def read_library(path):
    path = Path(path).resolve()
    with closing(connect_read(path)) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'enl_refs' not in tables:
            raise ValueError('该 EndNote 库不是受支持的 SQLite 格式；本版仅能读取 SQLite 格式的 .enl 库。')
        rows = db.execute('SELECT * FROM enl_refs WHERE trash_state=0').fetchall()
    records = {}
    for row in rows:
        data = {field: str(row[column] or '') for field, column in MAP.items()}
        data['doi'] = normalize_doi(data['doi'])
        lines = data['keywords'].splitlines()
        data['project_names'] = sorted(line[len(PROJECT_PREFIX):] for line in lines if line.startswith(PROJECT_PREFIX))
        data['keywords'] = '\n'.join(line for line in lines if not line.startswith(PROJECT_PREFIX))
        records[row['id']] = data
    attachments = {}
    support = path.with_suffix('.Data') / 'sdb' / 'sdb.eni'
    if support.exists():
        with closing(connect_read(support)) as db:
            for row in db.execute('SELECT refs_id,file_path FROM file_res'):
                raw = row['file_path'].replace('internal-pdf://', '').replace('\\', '/')
                base = (path.with_suffix('.Data') / 'PDF').resolve()
                candidate = (base / raw).resolve()
                if candidate.is_relative_to(base) and candidate.is_file() and candidate.suffix.lower() == '.pdf':
                    attachments.setdefault(row['refs_id'], []).append(candidate)
    return records, attachments

def local_data(library, record):
    data = {field: str(record.get(field, '')) for field in MAP}
    data['project_names'] = sorted(library.project(p)['name'] for p in record['projects'] if library.project(p)['name'] != '未分类')
    return data

def preview(library, source):
    source = str(Path(source).resolve())
    remote, attachments = read_library(source)
    mappings = {r['external_id']: dict(r) for r in library.db.execute('SELECT * FROM sync_map WHERE source=?', (source,))}
    local = {r['id']: r for r in library.records()}
    markers = {}
    with closing(connect_read(source)) as db:
        if 'label' in {r[1] for r in db.execute('PRAGMA table_info(enl_refs)')}:
            markers = {r['id']: r['label'].split('PaperQuick:',1)[1].strip() for r in db.execute('SELECT id,label FROM enl_refs') if str(r['label']).startswith('PaperQuick:')}
    entries, used = [], set()
    for external_id, data in remote.items():
        mapping = mappings.get(external_id)
        if not mapping:
            duplicate = local.get(markers.get(external_id)) or next((r for r in local.values() if data['doi'] and r['doi'] == data['doi']), None)
            if duplicate:
                rid = duplicate['id']; used.add(rid)
                # First-time linking cannot know who changed what; differing fields require a choice.
                here = local_data(library, duplicate)
                conflicts = [key for key in data if here.get(key) != data[key] and here.get(key)]
                merged = {key: here.get(key) or value for key, value in data.items()}
                entries.append(dict(external_id=external_id, paper=rid, action='link', conflicts=conflicts, merged=merged, local=here, remote=data))
            else:
                entries.append(dict(external_id=external_id, paper=None, action='import', conflicts=[], merged=data, local={}, remote=data))
            continue
        rid = mapping['paper']; used.add(rid)
        if rid not in local:
            entries.append(dict(external_id=external_id, paper=rid, action='missing-local', conflicts=[], merged=data, local={}, remote=data))
            continue
        baseline = json.loads(mapping['baseline']); here = local_data(library, local[rid])
        merged, conflicts = {}, []
        for key in data:
            l, r, b = here.get(key), data[key], baseline.get(key)
            if l != b and r != b and l != r:
                conflicts.append(key)
            merged[key] = l if l != b else r
        action = 'unchanged' if merged == data == here else ('both' if merged != data and merged != here else 'export' if merged != data else 'update-local')
        entries.append(dict(external_id=external_id, paper=rid, action=action, conflicts=conflicts, merged=merged, local=here, remote=data))
    for external_id, mapping in mappings.items():
        if external_id not in remote:
            used.add(mapping['paper'])
            entries.append(dict(external_id=external_id, paper=mapping['paper'], action='missing-endnote', conflicts=[], merged={}, local={}, remote={}))
    for rid, record in local.items():
        if rid not in used:
            data = local_data(library, record)
            entries.append(dict(external_id=None, paper=rid, action='export-new', conflicts=[], merged=data, local=data, remote={}))
    return {'source': source, 'entries': entries, 'attachments': attachments}

def import_only(library, plan, project=None):
    imported = 0
    for entry in plan['entries']:
        if entry['action'] != 'import':
            continue
        data = dict(entry['remote']); names = data.pop('project_names', [])
        rid = library.save(data, project, deduplicate=False)
        for name in names:
            library.assign(rid, library.create_project(name))
        for attachment in plan['attachments'].get(entry['external_id'], []):
            library.attach(rid, attachment)
        current = entry['remote']
        with library.db:
            library.db.execute('INSERT OR REPLACE INTO sync_map VALUES(?,?,?,?)', (plan['source'], entry['external_id'], rid, json.dumps(current, ensure_ascii=False)))
        imported += 1
    return imported

def copy_pair(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if target == source or target.exists() or target.with_suffix('.Data').exists():
        raise ValueError('同步副本必须使用新的文件名，不能覆盖已有库。')
    if not source.with_suffix('.Data').is_dir():
        raise ValueError('找不到配套 .Data 文件夹，请先在 EndNote 中保存完整文献库。')
    target.parent.mkdir(parents=True, exist_ok=True)
    target_data = target.with_suffix('.Data')
    try:
        shutil.copytree(source.with_suffix('.Data'), target_data)
        # Back up both databases using SQLite's consistent snapshot API.
        for old, new in ((source, target), (source.with_suffix('.Data') / 'sdb' / 'sdb.eni', target_data / 'sdb' / 'sdb.eni')):
            with closing(connect_read(old)) as src, closing(sqlite3.connect(new)) as dst:
                src.backup(dst)
        with closing(sqlite3.connect(target)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('EndNote 副本完整性检查失败。')
    except Exception:
        target.unlink(missing_ok=True)
        if target_data.exists():
            shutil.rmtree(target_data)
        raise
    return target

def resolve_plan(library, plan, choices):
    now, _ = read_library(plan['source'])
    expected = {e['external_id']: e['remote'] for e in plan['entries'] if e['remote']}
    if now != expected:
        raise ValueError('EndNote 库在预览后发生变化，请刷新同步预览。')
    merged = []
    for entry in plan['entries']:
        if entry['action'].startswith('missing-'):
            continue
        if entry['paper'] and entry['local'] and local_data(library, library.get(entry['paper'])) != entry['local']:
            raise ValueError('本地条目在预览后发生变化，请刷新同步预览。')
        data = dict(entry['merged'])
        for field in entry['conflicts']:
            choice = choices.get((entry['external_id'], field))
            if choice not in ('local', 'endnote'):
                raise ValueError('请先逐项选择冲突保留版本。')
            data[field] = entry['local'][field] if choice == 'local' else entry['remote'][field]
        merged.append((entry, data))
    return merged

def export_xml(records, destination, library=None):
    root = ET.Element('xml');container = ET.SubElement(root, 'records')
    for r in records:
        item = ET.SubElement(container, 'record')
        ET.SubElement(item, 'ref-type', {'name': 'Journal Article'}).text = '17'
        contributors = ET.SubElement(item, 'contributors');authors = ET.SubElement(contributors, 'authors')
        import re
        for author in re.split(r'\n|;|；', r.get('authors', '')):
            if author.strip():ET.SubElement(authors, 'author').text = author.strip()
        titles = ET.SubElement(item, 'titles');ET.SubElement(titles, 'title').text = r.get('title', '')
        ET.SubElement(titles, 'secondary-title').text = r.get('venue', '')
        dates = ET.SubElement(item, 'dates');ET.SubElement(dates, 'year').text = r.get('year', '')
        for local, tag in [('doi','electronic-resource-num'), ('abstract','abstract'), ('notes','notes')]:
            ET.SubElement(item,tag).text = r.get(local, '')
        keywords = ET.SubElement(item, 'keywords')
        for word in r.get('keywords', '').splitlines() + [PROJECT_PREFIX+p for p in r.get('project_names', [])]:
            if word.strip():ET.SubElement(keywords,'keyword').text = word.strip()
        if r.get('id'):
            ET.SubElement(item,'label').text = 'PaperQuick:' + r['id']
        if (library and r.get('id')) or r.get('pdf_paths'):
            urls=ET.SubElement(item,'urls');pdf_urls=ET.SubElement(urls,'pdf-urls')
            paths=list(r.get('pdf_paths', []))
            if library and r.get('id'):
                paths.extend(str(library.root/a['path']) for a in library.get(r['id'])['attachments'])
            for p in dict.fromkeys(paths):
                # Absolute local links; EndNote's import option controls copying into its .Data folder.
                ET.SubElement(pdf_urls,'url').text = Path(p).resolve().as_uri()
    ET.indent(root)
    ET.ElementTree(root).write(destination,encoding='utf-8',xml_declaration=True)

def export_exchange(library, plan, target, choices):
    """Export reviewed changes using the supported XML format and pull changes locally.
    Existing EndNote records require manual field updates; no unsafe SQLite writes.
    """
    merged = resolve_plan(library,plan,choices)
    target=Path(target).resolve()
    if target.exists():
        raise ValueError('请选择新的交换包文件夹，避免覆盖上一次记录。')
    target.mkdir(parents=True)
    all_records=[];new_records=[];updates=[]
    for entry,data in merged:
        data=dict(data);data['id']=entry['paper']
        data['pdf_paths']=[str(p) for p in plan['attachments'].get(entry['external_id'], [])] if not entry['paper'] else []
        all_records.append(data)
        if entry['action']=='export-new':new_records.append(data)
        elif entry['external_id'] is not None:
            changes={f:{'endnote':entry['remote'].get(f), 'reviewed':data.get(f)} for f in data if f not in ('id','pdf_paths') and data.get(f)!=entry['remote'].get(f)}
            if changes:updates.append({'external_id':entry['external_id'],'title':data['title'],'fields':changes})
    export_xml(all_records,target/'完整文献库.xml',library)
    export_xml(new_records,target/'仅新增文献.xml',library)
    (target/'修改清单.json').write_text(json.dumps({'source':plan['source'],'updates':updates},ensure_ascii=False,indent=2),'utf-8')
    rows=[]
    for update in updates:
        rows.append('<h3>EndNote #'+str(update['external_id'])+' · '+html.escape(update['title'])+'</h3>')
        for field,change in update['fields'].items():
            value=change['reviewed']
            if isinstance(value,list):value='\n'.join(PROJECT_PREFIX+p for p in value)
            rows.append('<p>'+html.escape(field)+'</p><textarea readonly>'+html.escape(str(value or ''))+'</textarea>')
    (target/'修改清单.html').write_text('<!doctype html><meta charset="utf-8"><title>EndNote 修改清单</title><style>body{font:15px Microsoft YaHei;max-width:900px;margin:35px auto;background:#f5f8fc;color:#18304a}textarea{width:100%;height:95px}h3{margin-top:30px}</style><h1>EndNote 字段修改清单</h1><p>本版不自动写回原库。请在 EndNote 中按记录号核对后手动更新字段；可选中文本复制。关键词中的课题标记可并入现有关键词。</p>'+''.join(rows),'utf-8')
    (target/'操作说明.txt').write_text('1. 仅新增文献.xml：EndNote 文件 > 导入 > 文件，导入选项 EndNote generated XML。先用测试库验证；选择丢弃重复项。\n2. 修改已有文献：按照 修改清单.html 中的记录号手动更新字段，勿导入完整库替代更新（会产生重复项）。\n3. 完整文献库.xml：用于导入新的空白测试库或备份主要字段，不保留原 EndNote 记录号、原生组及全部扩展字段。\n4. 附件使用本地绝对文件链接；在 EndNote 中核对 PDF，按需要复制到 .Data。\n5. 保存并关闭 EndNote 后，再次预览同步；已一致字段不再提示。\n6. 不自动删除条目、不写回 .enl、不访问网络、不调用 AI。','utf-8')
    # Local changes are applied only after a complete exchange package exists.
    for entry,data in merged:
        if entry['action']=='export-new':continue
        names=data['project_names'];payload={k:v for k,v in data.items() if k!='project_names'}
        rid=library.save(payload,rid=entry['paper'],deduplicate=False)
        projects=[library.create_project(p) for p in names] or [library.projects()[0]['id']]
        primary=library.get(rid)['primary_project']
        with library.db:
            library.db.execute('DELETE FROM memberships WHERE paper=?',(rid,))
            for pid in projects:library.db.execute('INSERT INTO memberships VALUES(?,?)',(rid,pid))
            library.db.execute('UPDATE papers SET primary_project=? WHERE id=?',(primary if primary in projects else projects[0],rid))
        for attachment in plan['attachments'].get(entry['external_id'],[]):library.attach(rid,attachment)
        with library.db:
            library.db.execute('INSERT OR REPLACE INTO sync_map VALUES(?,?,?,?)',(plan['source'],entry['external_id'],rid,json.dumps(entry['remote'],ensure_ascii=False)))
            library.log('endnote-exchange',{'source':plan['source'],'package':str(target),'paper':rid})
    return target
