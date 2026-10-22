"""Portable project handoffs, imported only into a new, isolated library.

JSON carries explicit project data; no source SQLite pages, private configuration,
AI account material, caches, or unrelated project records enter an export.
"""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import math
import os
import sqlite3
import tempfile
import time
import uuid
import zipfile

from library_backup import _safe_name, _regular, _read_manifest, _check, _report, _load_json, _check_space, CHUNK, MAX_TOTAL_BYTES
from library_core import Library, clean_name
from research_store import ResearchStore
from workspace_state import WorkspaceStore

MANIFEST = 'handoff-manifest.json'
KIND = 'PaperQuickProjectHandoff'
PUBLIC_CONFIG = frozenset(('reader_marker_size', 'continuous_reading', 'research_note_template'))
POSITION_FIELDS = frozenset(('paper', 'attachment', 'page', 'fraction', 'x_fraction', 'scale', 'continuous',
                            'notes_visible', 'split', 'logical', 'paragraph', 'updated'))


def _public_config(rows, papers, attachments):
    result = {}
    for row in rows:
        key, value = row['key'], json.loads(row['value'])
        if key == 'reader_marker_size' and type(value) is int and 8 <= value <= 48:
            result[key] = value
        elif key == 'continuous_reading' and type(value) is bool:
            result[key] = value
        elif key == 'research_note_template' and isinstance(value, str) and len(value) <= 12000:
            result[key] = value
        elif key == 'reading-last' and isinstance(value, dict):
            if value.get('paper') in papers and value.get('attachment') in attachments:
                result[key] = {field: value[field] for field in ('paper', 'attachment')}
        elif key.startswith('reading-position:') and key.split(':', 1)[1] in attachments and isinstance(value, dict):
            if value.get('paper') in papers and value.get('attachment') in attachments:
                position = {field: value[field] for field in ('paper', 'attachment')}
                for field, item in value.items():
                    if field in ('continuous', 'notes_visible', 'logical') and type(item) is bool:
                        position[field] = item
                    elif field in ('page', 'paragraph') and type(item) is int and 0 <= item < 1000000:
                        position[field] = item
                    elif field in ('fraction', 'x_fraction', 'split', 'scale', 'updated') and type(item) in (int, float) and math.isfinite(item):
                        limit = 1 if field in ('fraction', 'x_fraction', 'split') else 20 if field == 'scale' else 10 ** 15
                        if 0 <= item <= limit:
                            position[field] = item
                result[key] = position
        elif key.startswith('reading-paper-last:') and key.split(':', 1)[1] in papers and isinstance(value, str) and value in attachments:
            result[key] = value
    return result


def _rows(db, table):
    return [dict(row) for row in db.execute('SELECT * FROM ' + table)]


def _remap(value, mapping):
    if isinstance(value, dict):
        return {mapping.get(key, key): _remap(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap(item, mapping) for item in value]
    return mapping.get(value, value) if isinstance(value, str) else value


def _gather(library, project):
    scope = library.project_descendants(project)
    records = {record['id']: record for record in library.records(project)}
    original_ids = set(records)
    research = ResearchStore(library.root)
    workspace = WorkspaceStore(library.root)
    try:
        evidence = research.export_project(project)
        workbench = workspace.export_project(project)
    finally:
        research.close()
        workspace.close()
    wanted = {card['paper'] for card in evidence['cards']}
    wanted |= {item['paper'] for item in evidence['decisions']}
    wanted |= {cell['paper'] for matrix in evidence['matrices'] for cell in matrix['cells']}
    for record in records.values():
        wanted |= {item['target'] for item in record.get('annotations', []) if isinstance(item, dict) and item.get('target')}
    relations = _rows(library.db, 'paper_relations')
    for relation in relations:
        if relation['source'] in original_ids or relation['target'] in original_ids:
            wanted.update((relation['source'], relation['target']))
    missing = []
    for rid in wanted - set(records):
        if library.db.execute('SELECT 1 FROM papers WHERE id=?', (rid,)).fetchone():
            records[rid] = library.get(rid)
        else:
            missing.append({'kind': 'paper', 'id': rid, 'message': '来源文献已不存在'})
    selected = set(records)
    selected_attachments = {item['id']: item for record in records.values() for item in record['attachments']}
    for card in evidence['cards']:
        if card.get('attachment') and card['attachment'] not in selected_attachments:
            missing.append({'kind': 'evidence_attachment', 'id': card['id'], 'message': '证据卡来源附件已不存在'})
    groups = _rows(library.db, 'graph_groups')
    members = [row for row in _rows(library.db, 'graph_group_members') if row['paper'] in selected]
    group_ids = {row['group_id'] for row in members}
    payload = dict(schema=1, kind=KIND, title=library.project(project)['name'], root_project=project,
                   projects=[row for row in library.projects() if row['id'] in scope],
                   records=list(records.values()), external_papers=sorted(selected - original_ids),
                   relations=[row for row in relations if row['source'] in selected and row['target'] in selected],
                   graph_groups=[row for row in groups if row['id'] in group_ids], graph_group_members=members,
                   tag_rules=[row for row in _rows(library.db, 'project_tag_rules') if row['project'] in scope],
                   tag_memberships=[row for row in _rows(library.db, 'tag_memberships') if row['project'] in scope and row['paper'] in selected],
                   reading_sessions=[row for row in _rows(library.db, 'reading_sessions') if row['paper'] in selected],
                   config=_public_config(_rows(library.db, 'config'), selected,
                                         {item['id'] for record in records.values() for item in record['attachments']}),
                   research=evidence, workspace=workbench, missing_sources=missing)
    return payload


def export_project_handoff(directory, project, output, context=None):
    root, output = Path(directory).resolve(), Path(output).resolve()
    if not output.parent.is_dir() or output.exists() or output.is_relative_to(root):
        raise ValueError('请选择文献库之外的新 ZIP 文件，不覆盖已有文件。')
    with tempfile.TemporaryDirectory(prefix='.paperquick-handoff-', dir=output.parent) as temporary:
        stage = Path(temporary)
        snapshot_root = stage / 'snapshot'
        snapshot_root.mkdir()
        with closing(sqlite3.connect((root / 'library.sqlite').as_uri() + '?mode=ro', uri=True)) as source:
            version = source.execute('PRAGMA data_version').fetchone()[0]
            with closing(sqlite3.connect(snapshot_root / 'library.sqlite')) as target:
                source.backup(target, pages=256, progress=lambda *_: _check(context), sleep=.05)
            library = Library(snapshot_root)
            try:
                payload = _gather(library, project)
            finally:
                library.close()
            files, sources = [], {}
            for record in payload['records']:
                for attachment in record['attachments']:
                    attachment['original'] = Path(str(attachment.get('original', '')).replace('\\', '/')).name
                    relative = attachment.pop('path', '')
                    attachment['file'] = ''
                    if attachment.get('kind') == 'link':
                        continue
                    if not relative:
                        payload['missing_sources'].append({'kind': 'attachment', 'id': attachment['id'], 'message': '附件路径缺失'})
                        continue
                    relative = _safe_name(str(relative).replace('\\', '/'))
                    path = (root / relative).resolve()
                    if not path.is_relative_to(root):
                        raise ValueError('附件路径超出文献库。')
                    if not path.is_file():
                        payload['missing_sources'].append({'kind': 'attachment', 'id': attachment['id'], 'message': '附件文件缺失', 'path': relative})
                        continue
                    archive_name = f"files/attachments/{len(sources):06d}_{clean_name(path.name, 100)}"
                    attachment['file'] = archive_name
                    sources[archive_name] = path
                for note in record.get('note_images', []):
                    relative = _safe_name(str(note.get('path', '')).replace('\\', '/'))
                    path = (root / relative).resolve()
                    note['path'] = ''
                    if not path.is_relative_to(root):
                        raise ValueError('笔记图片路径超出文献库。')
                    if path.is_file():
                        archive_name = f"files/notes/{len(sources):06d}_{clean_name(path.name, 100)}"
                        note['file'] = archive_name
                        sources[archive_name] = path
                    else:
                        note['file'] = ''
                        payload['missing_sources'].append({'kind': 'note_image', 'id': note.get('id', ''), 'message': '笔记图片缺失', 'path': relative})
            total = sum(path.stat().st_size for path in sources.values())
            done = 0
            copied_states = {}
            archive = stage / 'handoff.zip'
            with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
                for relative, path in sources.items():
                    _check(context)
                    if not _regular(path):
                        raise ValueError('交接文件不能是符号链接。')
                    before = path.stat()
                    digest, size = hashlib.sha256(), 0
                    with path.open('rb') as incoming, bundle.open(relative, 'w', force_zip64=True) as outgoing:
                        while chunk := incoming.read(CHUNK):
                            _check(context)
                            outgoing.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                            done += len(chunk)
                            _report(context, done, total, '正在打包课题文件：' + path.name)
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or size != before.st_size:
                        raise RuntimeError('附件在交接时发生变化，请重试。')
                    copied_states[path] = (after.st_size, after.st_mtime_ns)
                    files.append(dict(path=relative, size=size, sha256=digest.hexdigest()))
                for path, state in copied_states.items():
                    current = path.stat()
                    if (current.st_size, current.st_mtime_ns) != state or not _regular(path):
                        raise RuntimeError('附件在交接时发生变化，请重试。')
                if source.execute('PRAGMA data_version').fetchone()[0] != version:
                    raise RuntimeError('文献库在交接时发生变化，本次未发布，请重试。')
                hashes = {entry['path']: entry['sha256'] for entry in files}
                for record in payload['records']:
                    for attachment in record['attachments']:
                        if attachment['file']:
                            attachment['sha'] = hashes[attachment['file']]
                content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
                bundle.writestr('handoff.json', content)
                files.append(dict(path='handoff.json', size=len(content), sha256=hashlib.sha256(content).hexdigest()))
                bundle.writestr(MANIFEST, json.dumps(dict(schema=1, type=KIND, created=time.time(), files=files), ensure_ascii=False).encode('utf-8'))
            _check(context)
            if os.name == 'nt':
                os.rename(archive, output)
            else:
                os.link(archive, output)
            return dict(path=str(output), papers=len(payload['records']), projects=len(payload['projects']),
                        external_papers=len(payload['external_papers']), missing_sources=payload['missing_sources'],
                        warnings=[item['message'] + '：' + str(item.get('path') or item.get('id')) for item in payload['missing_sources']])


def _read_package(archive, context=None, destination=None):
    with zipfile.ZipFile(archive) as bundle:
        _, entries, total = _read_manifest(bundle, MAX_TOTAL_BYTES, expected_type=KIND,
                                           required_files=('handoff.json',), manifest_name=MANIFEST)
        if entries['handoff.json']['size'] > 256 * 1024 * 1024:
            raise ValueError('课题数据清单过大。')
        if destination:
            _check_space(destination, total * 2)
        payload_bytes, done = bytearray(), 0
        for relative, entry in entries.items():
            _check(context)
            if relative != 'handoff.json' and not relative.startswith('files/'):
                raise ValueError('交接包包含不支持的文件。')
            target = None
            try:
                if destination and relative != 'handoff.json':
                    path = destination / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    target = path.open('xb')
                digest, size = hashlib.sha256(), 0
                with bundle.open(relative) as stream:
                    while chunk := stream.read(CHUNK):
                        _check(context)
                        size += len(chunk)
                        if size > entry['size']:
                            raise ValueError('交接文件超过声明大小。')
                        digest.update(chunk)
                        done += len(chunk)
                        if relative == 'handoff.json':
                            payload_bytes.extend(chunk)
                        elif target:
                            target.write(chunk)
                        _report(context, done, total, '正在校验课题交接包')
                if size != entry['size'] or digest.hexdigest() != entry['sha256'].lower():
                    raise ValueError('交接包校验失败：' + relative)
            finally:
                if target:
                    target.close()
        payload = _load_json(payload_bytes)
        try:
            _validate_payload(payload, entries)
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise ValueError('课题交接数据字段类型不正确。') from exc
        return payload, entries, hashlib.sha256(bundle.read(MANIFEST)).hexdigest()


def _validate_payload(payload, entries):
    if not isinstance(payload, dict) or type(payload.get('schema')) is not int or payload['schema'] != 1 or payload.get('kind') != KIND:
        raise ValueError('课题交接数据格式不支持。')
    for key in ('projects', 'records', 'relations', 'graph_groups', 'graph_group_members', 'tag_rules', 'tag_memberships', 'reading_sessions', 'external_papers', 'missing_sources'):
        if not isinstance(payload.get(key), list) or len(payload[key]) > 100000:
            raise ValueError('课题交接列表格式或大小不正确。')
    project_ids, paper_ids, attachment_ids = set(), set(), set()
    for rows, seen in ((payload['projects'], project_ids), (payload['records'], paper_ids)):
        for row in rows:
            ident = row.get('id') if isinstance(row, dict) else None
            if not isinstance(ident, str) or not ident or len(ident) > 200 or ident in seen:
                raise ValueError('课题交接包含缺失或重复的标识。')
            seen.add(ident)
    if payload.get('root_project') not in project_ids or set(payload['external_papers']) - paper_ids:
        raise ValueError('课题范围不正确。')
    if not isinstance(payload.get('title'), str) or not isinstance(payload.get('research'), dict) or not isinstance(payload.get('workspace'), dict):
        raise ValueError('课题标题、研究或工作台数据不正确。')
    missing_attachments = {item.get('id') for item in payload['missing_sources'] if isinstance(item, dict) and item.get('kind') == 'attachment'}
    for record in payload['records']:
        if not isinstance(record.get('attachments'), list) or not isinstance(record.get('note_images', []), list):
            raise ValueError('附件或笔记图片格式不正确。')
        for attachment in record['attachments']:
            if not isinstance(attachment, dict):
                raise ValueError('附件条目格式不正确。')
            ident = attachment.get('id')
            if not isinstance(ident, str) or not ident or len(ident) > 200 or ident in attachment_ids:
                raise ValueError('附件标识缺失或重复。')
            attachment_ids.add(ident)
            file = attachment.get('file', '')
            if attachment.get('kind') != 'link' and not file and ident not in missing_attachments:
                raise ValueError('交接包缺少附件，且没有缺失来源说明。')
            if file and (file not in entries or str(attachment.get('sha', '')).lower() != entries[file]['sha256'].lower()):
                raise ValueError('附件摘要与文件清单不一致。')
        for item in [*record['attachments'], *record.get('note_images', [])]:
            if not isinstance(item, dict):
                raise ValueError('附件或笔记图片条目格式不正确。')
            path = item.get('file', '')
            if path and (_safe_name(path) not in entries or not path.startswith('files/')):
                raise ValueError('附件或笔记图片不在交接清单中。')
    if not isinstance(payload.get('config'), dict):
        raise ValueError('交接包含有非公开配置，不能导入。')
    public = _public_config([{'key': key, 'value': json.dumps(value)} for key, value in payload['config'].items()], paper_ids, attachment_ids)
    if payload['config'] != public:
        raise ValueError('交接包含非公开配置或无效的阅读现场。')


def _duplicates(payload, existing_directory=None):
    by_doi, by_sha = {}, {}
    if existing_directory:
        database = Path(existing_directory).resolve() / 'library.sqlite'
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            for rid, data in db.execute('SELECT id,data FROM papers'):
                doi = str(json.loads(data).get('doi', '')).strip().casefold()
                if doi:
                    by_doi.setdefault(doi, []).append('当前文献库：' + rid)
            for aid, sha in db.execute('SELECT id,sha FROM attachments'):
                if sha:
                    by_sha.setdefault(sha.lower(), []).append('当前文献库：' + aid)
    duplicate_papers, duplicate_files = [], []
    for record in payload['records']:
        doi = str(record.get('doi', '')).strip().casefold()
        if doi:
            if doi in by_doi:
                duplicate_papers.append(dict(id=record['id'], title=record.get('title', ''), doi=doi, matches=by_doi[doi][:20]))
            by_doi.setdefault(doi, []).append('交接包：' + record['id'])
        for attachment in record['attachments']:
            sha = str(attachment.get('sha', '')).lower()
            if sha:
                if sha in by_sha:
                    duplicate_files.append(dict(id=attachment['id'], sha256=sha, matches=by_sha[sha][:20]))
                by_sha.setdefault(sha, []).append('交接包：' + attachment['id'])
    return duplicate_papers, duplicate_files


def inspect_project_handoff(archive, existing_directory=None, context=None):
    payload, entries, manifest_digest = _read_package(Path(archive), context)
    duplicates, files = _duplicates(payload, existing_directory)
    return dict(path=str(Path(archive).resolve()), title=payload['title'], projects=len(payload['projects']),
                papers=len(payload['records']), external_papers=len(payload['external_papers']),
                files=len(entries) - 1, duplicate_papers=duplicates, duplicate_files=files,
                missing_sources=payload['missing_sources'], preserve_every_record=True, manifest_sha256=manifest_digest,
                warnings=[item['message'] for item in payload['missing_sources']])


def _copy_asset(source, target, context, progress):
    """Copy staged assets with bounded cancellation latency and visible progress."""
    _check(context)
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        while True:
            _check(context)
            chunk = incoming.read(CHUNK)
            if not chunk:
                break
            outgoing.write(chunk)
            progress[0] += len(chunk)
            _report(context, progress[0], progress[1], '正在写入新文献库：' + source.name)
    _check(context)


def import_project_handoff(archive, destination, context=None, expected_manifest=None):
    destination = Path(destination).resolve()
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('请选择尚不存在的新文件夹，当前文献库不会被改动。')
    with tempfile.TemporaryDirectory(prefix='.paperquick-handoff-import-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        payload, entries, manifest_digest = _read_package(Path(archive), context, stage)
        if expected_manifest is not None and manifest_digest != expected_manifest:
            raise ValueError('交接包在预览后发生变化，请重新校验并预览。')
        copy_total = sum(entries[item['file']]['size'] for record in payload['records']
                         for item in [*record['attachments'], *record.get('note_images', [])] if item.get('file'))
        copy_progress = [0, copy_total]
        _report(context, 0, copy_total, '正在整理新文献库')
        library_root = stage / 'library'
        library = Library(library_root)
        project_map, paper_map, attachment_map = {}, {}, {}
        try:
            with library.db:
                library.db.execute('DELETE FROM projects')  # Remove only the new, empty default project.
            pending = list(payload['projects'])
            all_projects = {row['id'] for row in pending}
            while pending:
                ready = [row for row in pending if row.get('parent') not in all_projects or row.get('parent') in project_map]
                if not ready:
                    raise ValueError('课题层级包含循环。')
                for row in ready:
                    _check(context)
                    new_id = library.create_project(row['name'], project_map.get(row.get('parent')))
                    project_map[row['id']] = new_id
                    with library.db:
                        library.db.execute('UPDATE projects SET template=? WHERE id=?', (row.get('template', ''), new_id))
                    pending.remove(row)
            external_project = None
            if payload['external_papers']:
                name, number = '交接来源文献', 1
                existing_names = {row['name'] for row in library.projects()}
                while name in existing_names:
                    number += 1
                    name = f'交接来源文献 ({number})'
                external_project = library.create_project(name)
            paper_map = {record['id']: uuid.uuid4().hex for record in payload['records']}
            attachment_map = {item['id']: uuid.uuid4().hex for record in payload['records'] for item in record['attachments']}
            mapping = project_map | paper_map | attachment_map
            with library.db:
                for record in payload['records']:
                    _check(context)
                    rid = paper_map[record['id']]
                    projects = [project_map[pid] for pid in record.get('projects', []) if pid in project_map]
                    primary = project_map.get(record.get('primary_project')) or (projects[0] if projects else external_project)
                    if primary is None:
                        raise ValueError('文献未归属交接课题。')
                    data = _remap({key: value for key, value in record.items() if key not in ('id', 'projects', 'primary_project', 'attachments')}, mapping)
                    for note in data.get('note_images', []):
                        file = note.pop('file', '')
                        note['path'] = ''
                        if file:
                            relative = f"note-assets/{rid}/{uuid.uuid4().hex}{Path(file).suffix}"
                            target = library_root / relative
                            target.parent.mkdir(parents=True, exist_ok=True)
                            _copy_asset(stage / file, target, context, copy_progress)
                            note['path'] = relative
                    library.db.execute('INSERT INTO papers VALUES(?,?,?,?)', (rid, json.dumps(data, ensure_ascii=False), primary, time.time()))
                    for pid in set(projects + [primary]):
                        library.db.execute('INSERT INTO memberships VALUES(?,?)', (rid, pid))
                    for attachment in record['attachments']:
                        aid = attachment_map[attachment['id']]
                        file = attachment.get('file', '')
                        relative = f"papers/{rid}/{aid}{Path(file).suffix if file else ''}"
                        if file:
                            target = library_root / relative
                            target.parent.mkdir(parents=True, exist_ok=True)
                            _copy_asset(stage / file, target, context, copy_progress)
                        kind = attachment.get('kind', 'pdf')
                        library.db.execute('INSERT INTO attachments(id,paper,path,sha,original,label,role,kind,url) VALUES(?,?,?,?,?,?,?,?,?)',
                                           (aid, rid, 'links/' + aid + '.url' if kind == 'link' else relative, entries[file]['sha256'] if file else attachment.get('sha', ''),
                                            Path(str(attachment.get('original', '')).replace('\\', '/')).name,
                                            attachment.get('label', ''), attachment.get('role', 'supplement'), kind, attachment.get('url', '')))
                for relation in payload['relations']:
                    if relation['source'] in paper_map and relation['target'] in paper_map:
                        library.db.execute('INSERT INTO paper_relations VALUES(?,?,?,?,?)', (uuid.uuid4().hex, paper_map[relation['source']], paper_map[relation['target']], relation['label'], relation.get('created', time.time())))
                group_map = {row['id']: uuid.uuid4().hex for row in payload['graph_groups']}
                for row in payload['graph_groups']:
                    library.db.execute('INSERT INTO graph_groups VALUES(?,?,?,?)', (group_map[row['id']], row['label'], row['shape'], row.get('created', time.time())))
                for row in payload['graph_group_members']:
                    library.db.execute('INSERT INTO graph_group_members VALUES(?,?)', (group_map[row['group_id']], paper_map[row['paper']]))
                for row in payload['tag_rules']:
                    library.db.execute('INSERT INTO project_tag_rules VALUES(?,?)', (project_map[row['project']], row['tag']))
                for row in payload['tag_memberships']:
                    library.db.execute('INSERT INTO tag_memberships VALUES(?,?)', (paper_map[row['paper']], project_map[row['project']]))
                for row in payload['reading_sessions']:
                    library.db.execute('INSERT INTO reading_sessions(paper,start,end) VALUES(?,?,?)', (paper_map[row['paper']], row['start'], row['end']))
                for key, value in payload['config'].items():
                    if key.startswith(('reading-position:', 'reading-paper-last:')):
                        prefix, ident = key.split(':', 1)
                        key = prefix + ':' + mapping[ident]
                    library.db.execute('INSERT OR REPLACE INTO config VALUES(?,?)', (key, json.dumps(_remap(value, mapping), ensure_ascii=False)))
            library.close()
            library = None
            research = ResearchStore(library_root)
            try:
                imported = research.import_project(payload['research'], project_map, paper_map, attachment_map)
            finally:
                research.close()
            workspace = WorkspaceStore(library_root)
            try:
                workspace.import_project(payload['workspace'], project_map, paper_map)
            finally:
                workspace.close()
            _check(context)
            if destination.exists():
                raise FileExistsError('目标文件夹已存在。')
            os.rename(library_root, destination)
            return dict(path=str(destination), papers=len(paper_map), projects=len(project_map),
                        project_map=project_map, paper_map=paper_map, attachment_map=attachment_map,
                        missing_sources=payload['missing_sources'], research_issues=imported['issues'],
                        warnings=[item['message'] for item in payload['missing_sources']], preserve_every_record=True)
        finally:
            if library is not None:
                library.close()
