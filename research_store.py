"""Local evidence, comparison, outline and single-reviewer screening records.

Research tables share the library database, so library backups include them.  The
schema-1 JSON interchange deliberately contains no files, secrets or AI calls.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid
import zipfile
from xml.sax.saxutils import escape

from library_core import Library, display_name, digest

STANCES = ('support', 'oppose', 'mixed', 'neutral')
DECISIONS = ('include', 'exclude', 'uncertain')
STAGES = ('title_abstract', 'full_text')
DEFAULT_COLUMNS = ['研究问题', '研究设计', '样本 / 数据', '主要结果', '局限']
SCHEMA = 1


def source_location(card):
    kind = card.get('locator_kind', 'page')
    value = card.get('paragraph') if kind == 'paragraph' else card.get('page')
    return f"第 {value+1 if value is not None else '?'} {'段（逻辑段落）' if kind == 'paragraph' else '页'}"


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _text(value, limit=100000):
    if not isinstance(value, str):
        raise ValueError('文字字段必须为字符串。')
    if len(value) > limit:
        raise ValueError(f'文字最多 {limit} 字。')
    return value.strip()


def _ids(values):
    if not isinstance(values, list) or len(values) > 10000 or not all(isinstance(v, str) and v for v in values):
        raise ValueError('证据引用列表不正确。')
    return list(dict.fromkeys(values))


def _rect(value):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in value):
        raise ValueError('原文区域必须为四个 0–1 之间的坐标。')
    if value[0] > value[2] or value[1] > value[3]:
        raise ValueError('原文区域坐标顺序不正确。')
    return list(value)


def write_export(path, data, overwrite=False):
    """Complete content first; replace an existing file only after explicit consent."""
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError('目标文件已存在，请确认覆盖或更换名称。')
    fd, temporary = tempfile.mkstemp(prefix='.research-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data.encode('utf-8') if isinstance(data, str) else data)
            stream.flush(); os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            # Windows rename refuses an existing destination; POSIX hard links
            # provide the same exclusive publication without a partial file.
            if os.name == 'nt':
                os.rename(temporary, path)
            else:
                os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


class ResearchStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        library = Library(self.directory)
        library.close()
        self.db = sqlite3.connect(self.directory / 'library.sqlite', timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS research_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_cards(id TEXT PRIMARY KEY,project TEXT NOT NULL,paper TEXT NOT NULL,data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS research_cards_project ON research_cards(project);
            CREATE TABLE IF NOT EXISTS research_matrices(id TEXT PRIMARY KEY,project TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_cells(matrix_id TEXT NOT NULL,paper TEXT NOT NULL,column_id TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(matrix_id,paper,column_id));
            CREATE TABLE IF NOT EXISTS research_sections(id TEXT PRIMARY KEY,project TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_decisions(project TEXT NOT NULL,paper TEXT NOT NULL,stage TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(project,paper,stage));
            CREATE TABLE IF NOT EXISTS research_audit(id TEXT PRIMARY KEY,project TEXT NOT NULL,at REAL NOT NULL,action TEXT NOT NULL,data TEXT NOT NULL);
        ''')
        row = self.db.execute("SELECT value FROM research_meta WHERE key='schema'").fetchone()
        if row and row[0] != str(SCHEMA):
            self.db.close(); raise ValueError('研究数据来自更新版本，请升级软件后再打开。')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO research_meta VALUES('schema',?)", (str(SCHEMA),))

    def close(self):
        self.db.close()

    def projects(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM projects ORDER BY rowid')]

    def _project(self, project):
        if not isinstance(project, str) or not self.db.execute('SELECT 1 FROM projects WHERE id=?', (project,)).fetchone():
            raise ValueError('请选择现有课题。')
        return project

    def _scope(self, project):
        if project is None:
            return None
        self._project(project)
        projects = self.projects(); found = {project}
        while True:
            children = {p['id'] for p in projects if p.get('parent') in found}
            if children <= found:
                return found
            found |= children

    def papers(self, project=None):
        scope = self._scope(project)
        rows = self.db.execute("SELECT id,data FROM papers ORDER BY updated DESC").fetchall()
        allowed = None if scope is None else {r['paper'] for r in self.db.execute('SELECT paper,project FROM memberships') if r['project'] in scope}
        result = []
        for row in rows:
            if allowed is not None and row['id'] not in allowed:
                continue
            data = json.loads(row['data'])
            result.append({'id': row['id'], 'title': display_name(data), 'doi': data.get('doi', ''), 'year': data.get('year', ''), 'authors': data.get('authors', '')})
        return result

    def attachments(self, paper):
        return [dict(row) for row in self.db.execute('SELECT * FROM attachments WHERE paper=? ORDER BY rowid', (paper,))]

    def _items(self, table, project=None):
        scope = self._scope(project)
        return [json.loads(row['data']) for row in self.db.execute(f'SELECT project,data FROM {table} ORDER BY rowid') if scope is None or row['project'] in scope]

    def cards(self, project=None):
        return self._items('research_cards', project)

    def card(self, ident):
        row = self.db.execute('SELECT data FROM research_cards WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('证据卡不存在。')
        return json.loads(row[0])

    def _log(self, project, action, data):
        self.db.execute('INSERT INTO research_audit VALUES(?,?,?,?,?)', (uuid.uuid4().hex, project, time.time(), action, _json(data)))

    def history(self, project=None):
        scope = self._scope(project)
        return [dict(row) | {'data': json.loads(row['data'])} for row in self.db.execute('SELECT * FROM research_audit ORDER BY at,id') if scope is None or row['project'] in scope]

    def _source_issues(self, card, hashes=None):
        issues = []
        row = self.db.execute('SELECT data FROM papers WHERE id=?', (card.get('paper'),)).fetchone()
        if not row:
            issues.append(('missing_paper', '来源文献已不存在'))
        attachment = card.get('attachment')
        if attachment:
            item = self.db.execute('SELECT paper,path,kind,sha FROM attachments WHERE id=?', (attachment,)).fetchone()
            if not item:
                issues.append(('missing_attachment', '来源附件已不存在'))
            elif item['paper'] != card.get('paper'):
                issues.append(('wrong_attachment', '来源附件不属于该文献'))
            elif item['kind'] != 'link':
                path = (self.directory / item['path']).resolve()
                if not path.is_relative_to(self.directory) or not path.is_file():
                    issues.append(('missing_file', '来源附件文件缺失或位置异常'))
                elif card.get('source_sha'):
                    current_sha = item['sha']
                    if hashes is not None:
                        try:
                            if path not in hashes:
                                hashes[path] = digest(path)
                            current_sha = hashes[path]
                        except OSError:
                            issues.append(('unreadable_file', '来源文件无法读取，请稍后重试'))
                    if current_sha != card['source_sha']:
                        issues.append(('changed_file', '来源文件版本与保存证据时不同，请重新核对'))
        elif card.get('quote'):
            issues.append(('no_attachment', '原文摘录尚未关联具体附件'))
        if card.get('locator_kind', 'page') == 'paragraph':
            if card.get('paragraph') is None:
                issues.append(('no_paragraph', '尚未记录来源逻辑段落'))
        elif card.get('page') is None:
            issues.append(('no_page', '尚未记录来源页码'))
        if not card.get('quote'):
            issues.append(('no_quote', '尚未填写原文摘录'))
        if not card.get('verified'):
            issues.append(('unverified', '尚未人工核对原文'))
        return issues

    def save_card(self, value):
        value = dict(value); project = self._project(value.get('project'))
        paper = _text(value.get('paper', ''), 200)
        if not self.db.execute('SELECT 1 FROM papers WHERE id=?', (paper,)).fetchone():
            raise ValueError('来源文献不存在，请重新选择。')
        attachment = _text(value.get('attachment') or '', 200)
        if attachment and not self.db.execute('SELECT 1 FROM attachments WHERE id=? AND paper=?', (attachment, paper)).fetchone():
            raise ValueError('来源附件不属于所选文献。')
        page = value.get('page')
        if page is not None and (type(page) is not int or not 0 <= page < 100000):
            raise ValueError('页码必须为从 0 开始的非负整数。')
        locator_kind = value.get('locator_kind', 'page'); paragraph = value.get('paragraph')
        if locator_kind not in ('page', 'paragraph') or (paragraph is not None and (type(paragraph) is not int or not 0 <= paragraph < 1000000)):
            raise ValueError('来源位置类型或段落编号不正确。')
        if locator_kind == 'paragraph':
            page = None
        stance = value.get('stance', 'neutral')
        if stance not in STANCES:
            raise ValueError('请选择支持、反对、混合或中性立场。')
        if type(value.get('verified', False)) is not bool:
            raise ValueError('核对状态不正确。')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.card(value['id']) if value.get('id') else None
            if old and value.get('revision', old['revision']) != old['revision']:
                raise ValueError('证据卡已在其他窗口修改，请重新载入。')
            now = time.time()
            data = dict(id=old['id'] if old else uuid.uuid4().hex, project=project, paper=paper,
                        attachment=attachment, page=page, stance=stance, verified=value.get('verified', False),
                        created=old['created'] if old else now, updated=now, revision=old['revision']+1 if old else 1)
            data['rect'] = _rect(value.get('rect', old.get('rect') if old else None))
            data.update(locator_kind=locator_kind, paragraph=paragraph if locator_kind == 'paragraph' else None)
            if locator_kind == 'paragraph':
                data['rect'] = None
            source = self.db.execute('SELECT sha FROM attachments WHERE id=?', (attachment,)).fetchone() if attachment else None
            data['source_sha'] = source['sha'] if source else ''
            for key in ('quote', 'interpretation', 'claim'):
                data[key] = _text(value.get(key, ''))
            if not any(data[key] for key in ('quote', 'interpretation', 'claim')):
                raise ValueError('请至少填写原文摘录、解释或研究论点。')
            if data['verified'] and any(code != 'unverified' for code, _ in self._source_issues(data, {})):
                raise ValueError('标记已核对前，请填写摘录、具体附件和来源位置，并确认来源文件可用。')
            if old and (old['project'] != project or old['paper'] != paper):
                linked = any(old['id'] in json.loads(r[0]).get('evidence', []) for r in self.db.execute('SELECT data FROM research_cells'))
                if linked:
                    raise ValueError('此证据已用于比较矩阵，不能更换课题或来源文献；请新建证据卡。')
            self.db.execute('INSERT OR REPLACE INTO research_cards VALUES(?,?,?,?)', (data['id'], project, paper, _json(data)))
            self._log(project, 'card_updated' if old else 'card_created', {'before': old, 'after': data})
        return data

    def delete_card(self, ident):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE'); old = self.card(ident)
            for row in self.db.execute('SELECT rowid,data FROM research_cells').fetchall():
                data = json.loads(row['data'])
                if ident in data['evidence']:
                    data['evidence'].remove(ident)
                    self.db.execute('UPDATE research_cells SET data=? WHERE rowid=?', (_json(data), row['rowid']))
            for row in self.db.execute('SELECT id,data FROM research_sections').fetchall():
                data = json.loads(row['data'])
                if ident in data['evidence']:
                    data['evidence'].remove(ident)
                    self.db.execute('UPDATE research_sections SET data=? WHERE id=?', (_json(data), row['id']))
            self.db.execute('DELETE FROM research_cards WHERE id=?', (ident,))
            self._log(old['project'], 'card_deleted', {'before': old, 'linked_references_removed': True})

    def matrices(self, project=None):
        return self._items('research_matrices', project)

    def matrix(self, ident):
        row = self.db.execute('SELECT data FROM research_matrices WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('比较矩阵不存在。')
        return json.loads(row[0])

    def save_matrix(self, value):
        project = self._project(value.get('project')); name = _text(value.get('name', ''), 200)
        if not name:
            raise ValueError('请填写矩阵名称。')
        columns = value.get('columns', DEFAULT_COLUMNS)
        if not isinstance(columns, list) or not 1 <= len(columns) <= 40:
            raise ValueError('矩阵需要 1–40 个比较列。')
        normalized = []
        for column in columns:
            title = _text(column if isinstance(column, str) else column.get('title', ''), 100)
            if not title:
                raise ValueError('比较列名称不能为空。')
            normalized.append({'id': uuid.uuid4().hex if isinstance(column, str) else _text(column.get('id') or uuid.uuid4().hex, 200), 'title': title})
        if len({c['id'] for c in normalized}) != len(normalized):
            raise ValueError('比较列标识不能重复。')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE'); old = self.matrix(value['id']) if value.get('id') else None
            if old and old['project'] != project:
                raise ValueError('已有矩阵不能移到其他课题。')
            data = {'id': old['id'] if old else uuid.uuid4().hex, 'project': project, 'name': name, 'columns': normalized, 'updated': time.time()}
            if old:
                removed = {c['id'] for c in old['columns']} - {c['id'] for c in normalized}
                if removed and any(row[0] in removed for row in self.db.execute('SELECT column_id FROM research_cells WHERE matrix_id=?', (old['id'],))):
                    raise ValueError('要删除的列含有比较内容，请先清空这些单元格。')
            self.db.execute('INSERT OR REPLACE INTO research_matrices VALUES(?,?,?)', (data['id'], project, _json(data)))
            self._log(project, 'matrix_saved', data)
        return data

    def cells(self, matrix_id):
        self.matrix(matrix_id)
        return [json.loads(row[0]) for row in self.db.execute('SELECT data FROM research_cells WHERE matrix_id=? ORDER BY paper,column_id', (matrix_id,))]

    def _evidence(self, evidence, project, paper=None):
        evidence = _ids(evidence); scope = self._scope(project)
        for ident in evidence:
            card = self.card(ident)
            if card['project'] not in scope or (paper is not None and card['paper'] != paper):
                raise ValueError('证据必须属于此课题范围，矩阵单元格的证据还须来自该行文献。')
        return evidence

    def save_cell(self, matrix_id, paper, column_id, text='', evidence=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE'); matrix = self.matrix(matrix_id)
            if column_id not in {c['id'] for c in matrix['columns']}:
                raise ValueError('比较列不存在。')
            if paper not in {r['id'] for r in self.papers(matrix['project'])}:
                raise ValueError('所选文献不属于矩阵课题。')
            data = {'matrix': matrix_id, 'paper': paper, 'column': column_id, 'text': _text(text),
                    'evidence': self._evidence(evidence or [], matrix['project'], paper), 'updated': time.time()}
            self.db.execute('INSERT OR REPLACE INTO research_cells VALUES(?,?,?,?)', (matrix_id, paper, column_id, _json(data)))
            self._log(matrix['project'], 'cell_saved', data)
        return data

    def delete_cell(self, matrix_id, paper, column_id):
        with self.db:
            matrix = self.matrix(matrix_id)
            self.db.execute('DELETE FROM research_cells WHERE matrix_id=? AND paper=? AND column_id=?', (matrix_id, paper, column_id))
            self._log(matrix['project'], 'cell_deleted', {'matrix': matrix_id, 'paper': paper, 'column': column_id})

    def delete_matrix(self, ident):
        with self.db:
            data = self.matrix(ident)
            self.db.execute('DELETE FROM research_cells WHERE matrix_id=?', (ident,))
            self.db.execute('DELETE FROM research_matrices WHERE id=?', (ident,)); self._log(data['project'], 'matrix_deleted', data)

    def sections(self, project=None):
        return sorted(self._items('research_sections', project), key=lambda item: (item['position'], item['id']))

    def save_section(self, value):
        project = self._project(value.get('project')); title = _text(value.get('title', ''), 300)
        if not title:
            raise ValueError('请填写提纲小节标题。')
        position = value.get('position', 0)
        if type(position) is not int or not 0 <= position < 100000:
            raise ValueError('提纲序号必须为非负整数。')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if value.get('id') and not self.db.execute('SELECT 1 FROM research_sections WHERE id=?', (value['id'],)).fetchone():
                raise ValueError('提纲小节已不存在。')
            data = {'id': value.get('id') or uuid.uuid4().hex, 'project': project, 'title': title, 'body': _text(value.get('body', '')),
                    'position': position, 'evidence': self._evidence(value.get('evidence', []), project), 'updated': time.time()}
            self.db.execute('INSERT OR REPLACE INTO research_sections VALUES(?,?,?)', (data['id'], project, _json(data)))
            self._log(project, 'section_saved', data)
        return data

    def delete_section(self, ident):
        with self.db:
            row = self.db.execute('SELECT project,data FROM research_sections WHERE id=?', (ident,)).fetchone()
            if row:
                self.db.execute('DELETE FROM research_sections WHERE id=?', (ident,)); self._log(row['project'], 'section_deleted', json.loads(row['data']))

    def save_decision(self, project, paper, stage, decision, reason='', reviewer='本地评审'):
        self._project(project)
        if stage not in STAGES or decision not in DECISIONS:
            raise ValueError('请选择正确的筛选阶段和结论。')
        reason = _text(reason, 4000)
        if decision in ('exclude', 'uncertain') and not reason:
            raise ValueError('排除或待定时请填写原因。')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if paper not in {p['id'] for p in self.papers(project)}:
                raise ValueError('所选文献不属于当前课题。')
            first = self.db.execute('SELECT data FROM research_decisions WHERE project=? AND paper=? AND stage=?', (project, paper, STAGES[0])).fetchone()
            if stage == STAGES[1] and (not first or json.loads(first[0])['decision'] != 'include'):
                raise ValueError('题录 / 摘要阶段须先纳入，才能进入全文筛选。')
            old = self.db.execute('SELECT data FROM research_decisions WHERE project=? AND paper=? AND stage=?', (project, paper, stage)).fetchone()
            data = {'project': project, 'paper': paper, 'stage': stage, 'decision': decision, 'reason': reason,
                    'reviewer': _text(reviewer, 120) or '本地评审', 'at': time.time()}
            self.db.execute('INSERT OR REPLACE INTO research_decisions VALUES(?,?,?,?)', (project, paper, stage, _json(data)))
            # A changed eligibility decision invalidates the current second-stage
            # conclusion, but the previous conclusion remains in audit history.
            if stage == STAGES[0] and decision != 'include':
                self.db.execute('DELETE FROM research_decisions WHERE project=? AND paper=? AND stage=?', (project, paper, STAGES[1]))
            self._log(project, 'screening_decision', {'before': json.loads(old[0]) if old else None, 'after': data})
        return data

    def decisions(self, project=None):
        return self._items('research_decisions', project)

    def screening_rows(self, project):
        self._project(project)
        decisions = {(d['paper'], d['stage']): d for d in self.decisions(project) if d['project'] == project}
        return [paper | {stage: decisions.get((paper['id'], stage)) for stage in STAGES} for paper in self.papers(project)]

    def screening_counts(self, project):
        rows = self.screening_rows(project)
        result = {'total': len(rows), 'review_mode': 'single_reviewer', 'title_abstract': {}, 'full_text': {}}
        for stage in STAGES:
            eligible = rows if stage == STAGES[0] else [r for r in rows if r[STAGES[0]] and r[STAGES[0]]['decision'] == 'include']
            result[stage] = {key: sum(bool(r[stage] and r[stage]['decision'] == key) for r in eligible) for key in DECISIONS}
            result[stage].update(total=len(eligible), pending=sum(r[stage] is None for r in eligible))
        return result

    def validate_sources(self, project=None, verify_files=False):
        issues = []
        hashes = {} if verify_files else None
        cards = {c['id']: c for c in self.cards(project)}
        projects = {p['id'] for p in self.projects()}
        for card in cards.values():
            if card['project'] not in projects:
                issues.append({'kind': 'card', 'id': card['id'], 'paper': card['paper'], 'code': 'missing_project', 'message': '证据所属课题已不存在'})
            for code, message in self._source_issues(card, hashes):
                issues.append({'kind': 'card', 'id': card['id'], 'paper': card['paper'], 'code': code, 'message': message})
        all_cards = {r['id'] for r in self.db.execute('SELECT id FROM research_cards')}
        for matrix in self.matrices(project):
            for cell in self.cells(matrix['id']):
                if not self.db.execute('SELECT 1 FROM papers WHERE id=?', (cell['paper'],)).fetchone():
                    issues.append({'kind': 'cell', 'id': matrix['id'], 'paper': cell['paper'], 'code': 'missing_paper', 'message': '矩阵行文献已不存在'})
                for ident in cell['evidence']:
                    if ident not in all_cards:
                        issues.append({'kind': 'cell', 'id': matrix['id'], 'paper': cell['paper'], 'code': 'missing_evidence', 'message': '矩阵引用了不存在的证据：'+ident})
        for section in self.sections(project):
            if not section['evidence']:
                issues.append({'kind': 'section', 'id': section['id'], 'paper': '', 'code': 'no_evidence', 'message': '提纲小节尚未关联证据'})
            for ident in section['evidence']:
                if ident not in all_cards:
                    issues.append({'kind': 'section', 'id': section['id'], 'paper': '', 'code': 'missing_evidence', 'message': '提纲引用了不存在的证据：'+ident})
        for decision in self.decisions(project):
            if not self.db.execute('SELECT 1 FROM papers WHERE id=?', (decision['paper'],)).fetchone():
                issues.append({'kind': 'decision', 'id': decision['paper'], 'paper': decision['paper'], 'code': 'missing_paper', 'message': '筛选记录的文献已不存在'})
        return issues

    def export_project(self, project=None):
        # One read snapshot keeps interlinked cards/cells/sections consistent
        # even if another window saves evidence while a handoff is prepared.
        with self.db:
            self.db.execute('BEGIN')
            scope = self._scope(project)
            return {'schema': SCHEMA, 'kind': 'paperquick-research', 'exported_at': time.time(),
                    'projects': [p for p in self.projects() if scope is None or p['id'] in scope],
                    'cards': self.cards(project), 'matrices': [m | {'cells': self.cells(m['id'])} for m in self.matrices(project)],
                    'sections': self.sections(project), 'decisions': self.decisions(project), 'audit': self.history(project)}

    def import_project(self, payload, project_map=None, paper_map=None, attachment_map=None):
        """Import schema-1 data transactionally; never overwrite existing research.

        Existing source IDs may be retained if a mapping is absent. Missing
        source records are preserved as explicit audit findings, not fabricated.
        """
        if not isinstance(payload, dict) or payload.get('schema') != SCHEMA or payload.get('kind') != 'paperquick-research':
            raise ValueError('研究数据格式或版本不支持。')
        for key in ('cards', 'matrices', 'sections', 'decisions', 'audit'):
            if not isinstance(payload.get(key, []), list) or len(payload.get(key, [])) > 100000:
                raise ValueError('研究数据列表格式或大小不正确。')
        project_map, paper_map, attachment_map = project_map or {}, paper_map or {}, attachment_map or {}
        mapping = {key: {} for key in ('cards', 'matrices', 'sections')}
        def project(value):
            return self._project(project_map.get(value, value))
        def remap(values):
            ids = _ids(values)
            if any(ident not in mapping['cards'] for ident in ids):
                raise ValueError('研究包引用了未包含的证据卡。')
            return [mapping['cards'][ident] for ident in ids]
        def required_id(data, kind):
            ident = _text(data.get('id', ''), 200)
            if not ident or ident in mapping[kind]:
                raise ValueError('研究包包含缺失或重复的标识。')
            mapping[kind][ident] = uuid.uuid4().hex
            return mapping[kind][ident]
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            for source in payload.get('cards', []):
                data = dict(source); data['id'] = required_id(data, 'cards'); data['project'] = project(data.get('project'))
                data['paper'] = paper_map.get(data.get('paper'), data.get('paper'))
                data['attachment'] = attachment_map.get(data.get('attachment'), data.get('attachment')) or ''
                if not isinstance(data['paper'], str) or not data['paper'] or data.get('stance') not in STANCES or type(data.get('verified')) is not bool:
                    raise ValueError('证据卡来源或状态格式不正确。')
                if data.get('page') is not None and (type(data['page']) is not int or not 0 <= data['page'] < 100000):
                    raise ValueError('证据卡页码不正确。')
                kind = data.get('locator_kind', 'page'); paragraph = data.get('paragraph')
                if kind not in ('page', 'paragraph') or (paragraph is not None and (type(paragraph) is not int or not 0 <= paragraph < 1000000)):
                    raise ValueError('证据卡定位格式不正确。')
                data.update(locator_kind=kind, paragraph=paragraph if kind == 'paragraph' else None)
                if kind == 'paragraph':
                    data['page'] = None
                for key in ('quote', 'interpretation', 'claim'):
                    data[key] = _text(data.get(key, ''))
                data['rect'] = _rect(data.get('rect'))
                source_sha = data.get('source_sha', '')
                if not isinstance(source_sha, str) or (source_sha and (len(source_sha) != 64 or any(c not in '0123456789abcdef' for c in source_sha))):
                    raise ValueError('来源文件校验值不正确。')
                data.update(revision=1, updated=time.time()); data.setdefault('created', time.time())
                # A verification in another installation is provenance, not a
                # claim that a new owner has personally checked the local file.
                data['imported_verified'] = data['verified']; data['verified'] = False
                self.db.execute('INSERT INTO research_cards VALUES(?,?,?,?)', (data['id'], data['project'], data['paper'], _json(data)))
            for source in payload.get('matrices', []):
                data = dict(source); cells = data.pop('cells', []); data['id'] = required_id(data, 'matrices'); data['project'] = project(data.get('project'))
                if not isinstance(data.get('columns'), list) or not 1 <= len(data['columns']) <= 40 or not isinstance(cells, list):
                    raise ValueError('比较矩阵格式不正确。')
                data['name'] = _text(data.get('name', ''), 200)
                columns = set()
                for column in data['columns']:
                    if not isinstance(column, dict) or not _text(column.get('id', ''), 200) or not _text(column.get('title', ''), 100) or column['id'] in columns:
                        raise ValueError('比较列缺失或重复。')
                    columns.add(column['id'])
                self.db.execute('INSERT INTO research_matrices VALUES(?,?,?)', (data['id'], data['project'], _json(data)))
                for cell_source in cells:
                    cell = dict(cell_source); cell['matrix'] = data['id']; cell['paper'] = paper_map.get(cell.get('paper'), cell.get('paper'))
                    if not isinstance(cell['paper'], str) or not cell['paper'] or cell.get('column') not in columns:
                        raise ValueError('矩阵单元格来源或列不正确。')
                    cell['text'] = _text(cell.get('text', '')); cell['evidence'] = remap(cell.get('evidence', []))
                    self._evidence(cell['evidence'], data['project'], cell['paper'])
                    self.db.execute('INSERT INTO research_cells VALUES(?,?,?,?)', (data['id'], cell['paper'], cell['column'], _json(cell)))
            for source in payload.get('sections', []):
                data = dict(source); data['id'] = required_id(data, 'sections'); data['project'] = project(data.get('project'))
                data['evidence'] = remap(data.get('evidence', []))
                self._evidence(data['evidence'], data['project'])
                data['title'] = _text(data.get('title', ''), 300); data['body'] = _text(data.get('body', ''))
                if not data['title'] or type(data.get('position')) is not int or not 0 <= data['position'] < 100000:
                    raise ValueError('提纲小节格式不正确。')
                self.db.execute('INSERT INTO research_sections VALUES(?,?,?)', (data['id'], data['project'], _json(data)))
            seen = set()
            for source in payload.get('decisions', []):
                data = dict(source); data['project'] = project(data.get('project')); data['paper'] = paper_map.get(data.get('paper'), data.get('paper'))
                key = (data['project'], data['paper'], data.get('stage'))
                if not isinstance(data['paper'], str) or not data['paper'] or data.get('stage') not in STAGES or data.get('decision') not in DECISIONS or key in seen:
                    raise ValueError('筛选记录格式或唯一性不正确。')
                seen.add(key); data['reason'] = _text(data.get('reason', ''), 4000)
                if data['decision'] != 'include' and not data['reason']:
                    raise ValueError('筛选记录缺少排除 / 待定原因。')
                # Never silently replace a local review decision on reimport.
                if self.db.execute('SELECT 1 FROM research_decisions WHERE project=? AND paper=? AND stage=?', key).fetchone():
                    raise ValueError('目标课题已有此文献的筛选记录；请选择新的交接课题。')
                self.db.execute('INSERT INTO research_decisions VALUES(?,?,?,?)', (*key, _json(data)))
            for data in payload.get('decisions', []):
                if data['stage'] == STAGES[1]:
                    first = self.db.execute('SELECT data FROM research_decisions WHERE project=? AND paper=? AND stage=?', (project(data['project']), paper_map.get(data['paper'], data['paper']), STAGES[0])).fetchone()
                    if not first or json.loads(first[0])['decision'] != 'include':
                        raise ValueError('全文筛选记录缺少题录阶段纳入结论。')
            for entry in payload.get('audit', []):
                self._log(project(entry.get('project')), 'imported_history', {'original': entry})
            for pid in {project(p['id']) for p in payload.get('projects', [])}:
                self._log(pid, 'research_imported', {'counts': {k: len(v) for k, v in mapping.items()}})
        return {'id_maps': mapping, 'counts': {k: len(v) for k, v in mapping.items()}, 'issues': self.validate_sources()}

    def matrix_csv(self, ident):
        matrix = self.matrix(ident); cells = {(c['paper'], c['column']): c for c in self.cells(ident)}
        out = io.StringIO(newline=''); writer = csv.writer(out)
        writer.writerow(['文献', 'DOI'] + [c['title'] for c in matrix['columns']])
        papers = {p['id']: p for p in self.papers(matrix['project'])}
        for paper in {key[0] for key in cells}:
            papers.setdefault(paper, {'id': paper, 'title': '[来源文献缺失] '+paper, 'doi': ''})
        for paper in papers.values():
            values = []
            for column in matrix['columns']:
                cell = cells.get((paper['id'], column['id']), {})
                references = []
                for cid in cell.get('evidence', []):
                    card = self.card(cid); references.append(f"证据 {cid[:8]} / {source_location(card)} / {'已核对' if card['verified'] else '待核对'}")
                values.append(cell.get('text', '') + ('\n'+'；'.join(references) if references else ''))
            # Spreadsheet formula prefixes are escaped in every user-controlled cell.
            writer.writerow([("'"+str(v)) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v for v in [paper['title'], paper['doi'], *values]])
        return '\ufeff'+out.getvalue()

    def outline_markdown(self, project):
        name = next(p['name'] for p in self.projects() if p['id'] == self._project(project))
        lines = ['# '+name+' · 综述提纲', '', '> 本文由人工整理的提纲与证据组成；未核对的证据会明确标注。', '']
        papers = {p['id']: p for p in self.papers()}
        for section in self.sections(project):
            lines += ['## '+section['title'], '', section['body'], '']
            if not section['evidence']:
                lines += ['**待补充支持证据。**', '']
            for cid in section['evidence']:
                try:
                    card = self.card(cid)
                except ValueError:
                    lines += ['- [证据缺失] '+cid, '']; continue
                paper = papers.get(card['paper'], {'title': '[来源文献缺失]', 'doi': ''})
                issues = self._source_issues(card)
                label = '已人工核对' if not issues else '待核对：'+'；'.join(m for _, m in issues)
                lines += [f"- **{paper['title']}** · {source_location(card)} · {label}",
                          f"  - 证据：{cid}；附件：{card['attachment'] or '未关联'}；DOI：{paper['doi'] or '未填写'}",
                          '  - 原文：'+card['quote'].replace('\n', '\n    '), '  - 解释：'+card['interpretation'].replace('\n', '\n    '),
                          '  - 论点：'+card['claim'].replace('\n', '\n    '), '  - 立场：'+card['stance'], '']
        return '\n'.join(lines)

    def outline_docx(self, project):
        """Small editable OOXML document; no Word automation or external library."""
        paragraphs = []
        for line in self.outline_markdown(project).splitlines():
            heading = 1 if line.startswith('# ') else 2 if line.startswith('## ') else 0
            text = line[heading+1:] if heading else line
            prop = f'<w:pPr><w:pStyle w:val="Heading{heading}"/></w:pPr>' if heading else ''
            # XML 1.0 excludes control characters that may appear in extracted PDFs.
            text = ''.join(c for c in text if ord(c) >= 32 or c in '\t\n\r')
            paragraphs.append(f'<w:p>{prop}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')
        body = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+''.join(paragraphs)+'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'
        styles = '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:eastAsia="Microsoft YaHei"/><w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style></w:styles>'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
            archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
            archive.writestr('word/_rels/document.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
            archive.writestr('word/document.xml', body); archive.writestr('word/styles.xml', styles)
        return buffer.getvalue()

    def screening_csv(self, project):
        out = io.StringIO(newline=''); writer = csv.writer(out)
        writer.writerow(['文献', 'DOI', '题录 / 摘要结论', '题录原因', '全文结论', '全文原因', '评审方式'])
        for row in self.screening_rows(project):
            first, second = row[STAGES[0]] or {}, row[STAGES[1]] or {}
            values = [row['title'], row['doi'], first.get('decision', 'pending'), first.get('reason', ''), second.get('decision', 'pending'), second.get('reason', ''), '单人本地筛选']
            writer.writerow(["'"+str(v) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v for v in values])
        return '\ufeff'+out.getvalue()
