"""Offline library, managed PDF files and deterministic relationship analysis."""
from __future__ import annotations
import collections
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import string
import sys
import tempfile
import time
import uuid
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from library_workflow import LibraryWorkflow
from library_organization import LibraryOrganization, normalize_tags
from naming_rules import optional_name

FIELDS = ('title', 'authors', 'year', 'doi', 'venue', 'abstract', 'keywords', 'notes', 'status')
DEFAULT_TEMPLATE = '{年份}_{第一作者}_{标题}'


def display_name(record):
    return str(record.get('display_name') or record.get('title') or '未命名文献')

TOKENS = {'年份', '第一作者', '标题', 'DOI', '课题', '期刊', 'year', 'author', 'title', 'doi', 'project', 'journal', 'venue'}
STOPWORDS = set('the and for with from this that into are was were study using analysis results of in to a an on by is as or at be we our based'.split())

def clean_name(value, limit=100):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', value, re.I):
        value = '_' + value
    return value[:limit].rstrip(' .') or '未命名'

def normalize_doi(value):
    return re.sub(r'^https?://(?:dx\.)?doi\.org/|^doi:\s*', '', str(value).strip(), flags=re.I).lower().rstrip(' .')

def validate_template(template):
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise ValueError('命名模板的大括号不匹配。') from exc
    fields = [name for _, name, _, _ in parts if name is not None]
    if not fields or any(name not in TOKENS or spec or conversion for _, name, spec, conversion in parts if name is not None):
        raise ValueError('使用 {年份}、{第一作者}、{标题}、{期刊}、{DOI}、{课题}，不支持格式代码。')
    return template

def filename(record, project, template=DEFAULT_TEMPLATE, title_length=80):
    validate_template(template)
    author = re.split(r'\n|;|；| 等| et al', record.get('authors', ''))[0].strip()
    values = {'年份': record.get('year') or '', '第一作者': author,
              '标题': (record.get('title') or '')[:title_length], 'DOI': record.get('doi') or '', '课题': project}
    values['期刊'] = record.get('venue') or ''
    values.update(dict(zip(('year', 'author', 'title', 'doi', 'project'), (values[k] for k in ('年份', '第一作者', '标题', 'DOI', '课题')))))
    values.update(journal=values['期刊'], venue=values['期刊'])
    return clean_name(optional_name(template, values, record.get('title') or '未命名文献'), 150) + '.pdf'

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def attachment_kind(attachment):
    """Read both migrated rows and older attachment dictionaries."""
    if attachment.get('url') or attachment.get('kind') == 'link':
        return 'link'
    suffix = Path(attachment.get('path') or attachment.get('original') or '').suffix.lower().lstrip('.')
    return suffix if suffix in ('pdf', 'docx', 'doc', 'txt', 'md', 'html') else 'other'

def local_attachments(record):
    return [a for a in record.get('attachments', []) if a.get('path') and attachment_kind(a) != 'link']

def readable_attachments(record):
    return [a for a in local_attachments(record) if attachment_kind(a) in ('pdf', 'docx', 'doc', 'txt', 'md')]

def has_pdf(record):
    """Whether the paper's main document is a PDF, not merely a supplement."""
    attachments = readable_attachments(record)
    return any(attachment_kind(a) == 'pdf' and a.get('role', 'primary' if i == 0 else 'supplement') == 'primary'
               for i, a in enumerate(attachments))

def document_metadata(path):
    """Read Word metadata without starting Word or extracting archive members."""
    path = Path(path)
    if path.suffix.lower() in ('.txt','.md'):
        from reading_documents import read_text_file
        text=read_text_file(path)
        from references import parse_references
        return {'title':path.stem,'authors':'','year':'','doi':'','text':text,'references':parse_references(text)}
    if path.suffix.lower() == '.pdf':
        return pdf_metadata(path)
    if path.suffix.lower() == '.doc':
        with path.open('rb') as stream:
            if stream.read(8) != b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
                raise ValueError('文件不是有效的 Word DOC 文档，请在 Word 中另存为 DOCX 后导入。')
        return {'title': path.stem, 'authors': '', 'year': '', 'doi': '', 'text': '', 'references': []}
    if path.suffix.lower() != '.docx':
        raise ValueError('请选择 PDF、DOCX 或 DOC 文件。')
    try:
        with zipfile.ZipFile(path) as archive:
            def read_xml(name, limit):
                entry = archive.getinfo(name)
                if entry.file_size > limit:
                    raise ValueError('Word 文档内容过大，请精简文档后重新导入。')
                with archive.open(entry) as stream:
                    raw = stream.read(limit + 1)
                if len(raw) > limit:
                    raise ValueError('Word 文档内容过大，请精简文档后重新导入。')
                checked = raw.replace(b'\x00', b'').upper()
                if b'<!DOCTYPE' in checked or b'<!ENTITY' in checked:
                    raise ValueError('此 Word 文档包含不支持的 XML 定义。')
                return ET.fromstring(raw)
            document = read_xml('word/document.xml', 24 * 1024 * 1024)
            core = read_xml('docProps/core.xml', 1024 * 1024) if 'docProps/core.xml' in archive.namelist() else None
    except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError) as exc:
        raise ValueError('无法读取 Word 文档，请检查文件是否完整，或在 Word 中另存为 DOCX。') from exc
    namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    # Only w:t is visible body text; relationship URLs, formatting and field codes are not prose.
    paragraphs = [''.join(t.text or '' for t in p.iter(namespace + 't')).strip()
                  for p in document.iter(namespace + 'p')]
    text = '\n'.join(p for p in paragraphs if p)[:500000]
    props = {child.tag.rsplit('}', 1)[-1]: (child.text or '').strip() for child in core} if core is not None else {}
    title = props.get('title') or next((p for p in paragraphs[:5] if 8 <= len(p) <= 300), '') or path.stem
    if title.lower().startswith(('microsoft', 'untitled')):
        title = path.stem
    body = re.split(r'(?im)^\s*(?:\d+[.)]?\s*)?(?:references|bibliography|literature cited|参考文献)\s*[:：]?\s*$', text, maxsplit=1)[0]
    # References may contain many DOIs; identity comes from the document's opening only.
    doi = re.search(r'10\.\d{4,9}/[^\s<>"\u3000]+', body[:8000])
    year = re.search(r'\b(?:19|20)\d{2}\b', body[:5000] + ' ' + props.get('created', ''))
    from references import parse_references
    return {'title': title, 'authors': props.get('creator', ''), 'year': year.group() if year else '',
            'doi': normalize_doi(doi.group().rstrip('.,;)')) if doi else '', 'text': text,
            'references': parse_references(text)}

def pdf_metadata(path):
    """Extract locally; scanned PDFs need manual metadata (no OCR service)."""
    if not str(path).lower().endswith('.pdf'):
        raise ValueError('请选择 PDF 文件。')
    with open(path, 'rb') as stream:
        if b'%PDF-' not in stream.read(1024):
            raise ValueError('文件不是有效 PDF；网页下载请先完成登录并另存 PDF。')
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent / 'build' / 'vendor'))
        from pypdf import PdfReader
    reader = PdfReader(path, strict=False)
    if reader.is_encrypted and not reader.decrypt(''):
        raise ValueError('PDF 需要打开密码，请先另存为无需密码的副本后导入。')
    meta = reader.metadata or {}
    texts = []
    indices=sorted(set(range(min(12,len(reader.pages))))|set(range(max(0,len(reader.pages)-12),len(reader.pages))))
    try:
        # Native extraction avoids Python layout analysis of every glyph in dense
        # PDFs. Reuse the renderer's lock; PDFium is not thread-safe.
        from pdf_reader_core import pdfium,_LOCK
        with _LOCK,pdfium().PdfDocument(path) as document:
            for index in indices:
                page=document[index]
                try:
                    textpage=page.get_textpage()
                    try:texts.append(textpage.get_text_range(count=min(30000,textpage.count_chars())))
                    finally:textpage.close()
                except Exception:texts.append('')
                finally:page.close()
    except Exception:
        for index in indices:
            try:texts.append((reader.pages[index].extract_text() or '')[:30000])
            except Exception:texts.append('')
    text = '\n'.join(texts)[:500000]
    title = str(meta.get('/Title') or '').strip()
    if not title or title.lower().startswith(('microsoft', 'untitled')):
        title = Path(path).stem
    body=re.split(r'(?im)^\s*(?:references|bibliography|参考文献)\s*$',text,maxsplit=1)[0]
    # Do not mistake a bibliography DOI for the identity of the imported paper.
    doi = re.search(r'10\.\d{4,9}/[^\s<>"\u3000]+',str(meta.get('/doi') or meta.get('/DOI') or '')+' '+body[:8000])
    year = re.search(r'\b(?:19|20)\d{2}\b', str(meta.get('/CreationDate', '')) + ' ' + text[:5000])
    from references import parse_references
    return {'title': title, 'authors': str(meta.get('/Author') or ''), 'year': year.group() if year else '',
            'doi': normalize_doi(doi.group()) if doi else '', 'text': text,'references':parse_references(text)}

class Library(LibraryWorkflow, LibraryOrganization):
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'library.sqlite', timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT UNIQUE,folder TEXT UNIQUE,template TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS papers(id TEXT PRIMARY KEY,data TEXT,primary_project TEXT,updated REAL);
        CREATE TABLE IF NOT EXISTS memberships(paper TEXT,project TEXT,PRIMARY KEY(paper,project));
        CREATE TABLE IF NOT EXISTS attachments(id TEXT PRIMARY KEY,paper TEXT,path TEXT UNIQUE,sha TEXT,original TEXT);
        CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS events(at REAL,action TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS sync_map(source TEXT,external_id INTEGER,paper TEXT,baseline TEXT,PRIMARY KEY(source,external_id));
        CREATE TABLE IF NOT EXISTS reading_sessions(id INTEGER PRIMARY KEY,paper TEXT,start REAL,end REAL);
        CREATE INDEX IF NOT EXISTS reading_sessions_time ON reading_sessions(start,end);
        ''')
        self.db.commit()
        self._migrate_attachments()
        self.workflow_schema()
        self.organization_schema()
        if not self.projects():
            self.create_project('未分类')

    def _migrate_attachments(self):
        # Serialize schema inspection and ALTERs across reader/background connections.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            columns = {row['name'] for row in self.db.execute('PRAGMA table_info(attachments)')}
            legacy = 'role' not in columns
            for name, default in (('label', ''), ('role', 'supplement'), ('kind', 'pdf'), ('url', '')):
                if name not in columns:
                    self.db.execute(f"ALTER TABLE attachments ADD COLUMN {name} TEXT DEFAULT '{default}'")
            if legacy:
                self.db.execute("UPDATE attachments SET role='primary' WHERE rowid IN (SELECT MIN(rowid) FROM attachments GROUP BY paper)")
                for row in self.db.execute('SELECT id,path FROM attachments').fetchall():
                    kind = attachment_kind(dict(row))
                    self.db.execute('UPDATE attachments SET kind=? WHERE id=?', (kind, row['id']))
            self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS attachments_primary ON attachments(paper) WHERE role='primary'")

    def close(self):
        self.db.close()

    def log(self, action, detail):
        self.db.execute('INSERT INTO events VALUES(?,?,?)', (time.time(), action, json.dumps(detail, ensure_ascii=False)))

    def setting(self, key, default=None):
        row = self.db.execute('SELECT value FROM config WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO config VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def projects(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM projects ORDER BY rowid')]

    def project(self, pid):
        row = self.db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
        if not row:
            raise ValueError('课题不存在。')
        return dict(row)

    def create_project(self, name, parent=None):
        name = name.strip()
        if not name:
            raise ValueError('请填写课题名称。')
        if parent:
            name = self.project(parent)['name'] + ' / ' + name
        old = self.db.execute('SELECT id,parent FROM projects WHERE name=?', (name,)).fetchone()
        if old:
            if (old['parent'] or '') != (parent or ''):
                raise ValueError('该名称已被其他课题使用，请换一个名称。')
            return old[0]
        pid = uuid.uuid4().hex
        folder = clean_name(name, 60) + '_' + pid[:6]
        (self.root / 'papers' / folder).mkdir(parents=True, exist_ok=True)
        with self.db:
            self.db.execute('INSERT INTO projects(id,name,folder,parent) VALUES(?,?,?,?)', (pid, name, folder, parent or ''))
        return pid

    def records(self, project=None, summary=False):
        # List pages never load full document text, images, or long annotations.
        data="json_remove(p.data,'$.text','$.notes','$.references','$.annotations','$.note_images','$.note_styles') AS data" if summary else 'p.data'
        query = 'SELECT p.id,p.primary_project,p.updated,'+data+' FROM papers p'
        args = ()
        if project:
            args = tuple(self.project_descendants(project))
            query += ' WHERE p.id IN (SELECT paper FROM memberships WHERE project IN (' + ','.join('?' for _ in args) + '))'
        rows=self.db.execute(query + ' ORDER BY p.updated DESC', args).fetchall()
        memberships=collections.defaultdict(list);attachments=collections.defaultdict(list)
        for item in self.db.execute('SELECT * FROM memberships'):memberships[item['paper']].append(item['project'])
        for item in self.db.execute('SELECT * FROM attachments ORDER BY rowid'):attachments[item['paper']].append(dict(item))
        return [self._record(row,memberships,attachments) for row in rows]

    def recent_read(self, limit=50):
        """Unique papers in last-opened order, without loading document bodies."""
        return [dict(row) for row in self.db.execute('''
            SELECT id, COALESCE(NULLIF(json_extract(data, '$.display_name'), ''), json_extract(data, '$.title')) AS title,
                   CAST(json_extract(data, '$.last_read') AS REAL) AS last_read
            FROM papers WHERE CAST(json_extract(data, '$.last_read') AS REAL)>0
            ORDER BY last_read DESC, id LIMIT ?
        ''', (max(0, int(limit)),))]

    def _record(self, row, memberships=None, attachments=None):
        data = json.loads(row['data'])
        data.update(id=row['id'], primary_project=row['primary_project'])
        data['projects'] = memberships[row['id']] if memberships is not None else [r[0] for r in self.db.execute('SELECT project FROM memberships WHERE paper=?', (row['id'],))]
        data['attachments'] = attachments[row['id']] if attachments is not None else [dict(r) for r in self.db.execute('SELECT * FROM attachments WHERE paper=? ORDER BY rowid', (row['id'],))]
        data.setdefault('tags', [])
        data.setdefault('rating', 0)
        return data

    def get(self, rid):
        row = self.db.execute('SELECT * FROM papers WHERE id=?', (rid,)).fetchone()
        if not row:
            raise ValueError('文献不存在。')
        return self._record(row)

    def save(self, data, project=None, rid=None, deduplicate=True):
        data = dict(data)
        if 'tags' in data:
            data['tags'] = normalize_tags(data['tags'])
        if 'rating' in data:
            if str(data['rating']) not in ('0', '1', '2', '3', '4', '5'):
                raise ValueError('评分请选择 0–5 星，0 表示未评分。')
            data['rating'] = int(data['rating'])
        if 'doi' in data:
            data['doi'] = normalize_doi(data['doi'])
        if not rid and deduplicate and data.get('doi'):
            row=self.db.execute("SELECT id FROM papers WHERE json_extract(data,'$.doi')=? LIMIT 1",(data['doi'],)).fetchone()
            rid=row[0] if row else None
        if getattr(self,'_import_observer',None):self._import_observer(rid)
        if rid:
            old = self.get(rid)
            merged = {k: v for k, v in old.items() if k not in ('id', 'projects', 'attachments', 'primary_project')}
            merged.update(data)
            data = merged
            additional_project = project
            project = old['primary_project']
        else:
            rid = uuid.uuid4().hex
        project = project or self.projects()[0]['id']
        self.project(project)
        for field in FIELDS:
            data.setdefault(field, '未读' if field == 'status' else '')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO papers VALUES(?,?,?,?)', (rid, json.dumps(data, ensure_ascii=False), project, time.time()))
            self.db.execute('INSERT OR IGNORE INTO memberships VALUES(?,?)', (rid, project))
            if rid and 'additional_project' in locals() and additional_project:
                self.project(additional_project)
                self.db.execute('INSERT OR IGNORE INTO memberships VALUES(?,?)', (rid, additional_project))
                self.db.execute('DELETE FROM tag_memberships WHERE paper=? AND project=?',(rid,additional_project))
            self.log('save', {'paper': rid})
            self.sync_tag_memberships(rid, data.get('tags', []), project)
        return rid

    def assign(self, rid, project, primary=False):
        self.get(rid)
        self.project(project)
        with self.db:
            self.db.execute('DELETE FROM tag_memberships WHERE paper=? AND project=?', (rid, project))
            self.db.execute('INSERT OR IGNORE INTO memberships VALUES(?,?)', (rid, project))
            if primary:
                self.db.execute('UPDATE papers SET primary_project=? WHERE id=?', (project, rid))
        if primary:
            self.rename(rid)

    def template(self, project):
        return self.project(project)['template'] or self.setting('template', DEFAULT_TEMPLATE)

    def target(self, record, attachment=None, template=None, title_length=None):
        project = self.project(record['primary_project'])
        base = self.root / 'papers' / project['folder'] / filename(record, project['name'],
                 self.template(project['id']) if template is None else template,
                 self.setting('title_length', 80) if title_length is None else title_length)
        if attachment is None:
            return base
        if attachment_kind(attachment) == 'link':
            raise ValueError('链接附件不需要重命名文件。')
        original = Path(attachment.get('original') or attachment.get('path') or '')
        suffix = original.suffix
        if attachment.get('role', 'primary') == 'primary':
            return base.with_suffix(suffix)
        label = clean_name(attachment.get('label') or original.stem or '附件', 32)
        return base.with_name(base.stem[:100] + '__' + label + '_' + attachment['id'][:8] + suffix)

    def primary_attachment(self, rid):
        return next((a for a in readable_attachments(self.get(rid)) if a.get('role') == 'primary'), None)

    def set_primary_attachment(self, rid, aid):
        record = self.get(rid)
        attachment = next((a for a in readable_attachments(record) if a['id'] == aid), None)
        if not attachment:
            raise ValueError('请选择这篇文献中的 PDF 或 Word 文件作为正文。')
        source = self.root / attachment['path']
        if not source.is_file():
            raise ValueError('这份附件已不在原来的归档位置，请重新关联文件后再设为正文。')
        metadata = document_metadata(source)
        with self.db:
            self.db.execute("UPDATE attachments SET role='supplement' WHERE paper=? AND role='primary'", (rid,))
            self.db.execute("UPDATE attachments SET role='primary' WHERE paper=? AND id=?", (rid, aid))
            # Read the latest stored notes after obtaining the write lock, then replace only
            # text belonging to the old primary. Attachment-scoped annotations stay intact.
            data = json.loads(self.db.execute('SELECT data FROM papers WHERE id=?', (rid,)).fetchone()[0])
            data.update(text=metadata.get('text', ''), references=metadata.get('references', []))
            self.db.execute('UPDATE papers SET data=?,updated=? WHERE id=?', (json.dumps(data, ensure_ascii=False), time.time(), rid))
            self.log('attachment-primary', {'paper': rid, 'attachment': aid})

    def rename_attachment_label(self, rid, aid, label):
        self.get(rid)
        label = str(label).strip()[:200]
        with self.db:
            cursor = self.db.execute('UPDATE attachments SET label=? WHERE paper=? AND id=?', (label, rid, aid))
            if cursor.rowcount != 1:
                raise ValueError('附件不存在或不属于当前文献。')
            self.log('attachment-label', {'paper': rid, 'attachment': aid, 'label': label})

    def add_attachment_link(self, rid, url, label=''):
        self.get(rid)
        url = str(url).strip()
        try:
            parsed = urllib.parse.urlsplit(url)
            valid = parsed.scheme.lower() in ('http', 'https') and parsed.hostname and parsed.port != 0
        except ValueError:
            valid = False
        if not valid or re.search(r'[\x00-\x20\x7f]', url):
            raise ValueError('请输入完整的 http:// 或 https:// 附件链接。')
        old = self.db.execute('SELECT id FROM attachments WHERE paper=? AND url=?', (rid, url)).fetchone()
        if old:
            if str(label).strip():
                self.rename_attachment_label(rid, old['id'], label)
            return old['id']
        aid = uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO attachments(id,paper,path,sha,original,label,role,kind,url) VALUES(?,?,?,?,?,?,?,?,?)',
                            (aid, rid, 'links/' + aid + '.url', '', url, str(label).strip()[:200], 'supplement', 'link', url))
            self.log('attachment-link', {'paper': rid, 'attachment': aid, 'url': url})
        return aid

    def add_attachment(self, rid, source, label='', role='supplement'):
        return self._add_attachment(rid, source, label, role, extract=False)

    def _restore_attachment(self, attachment, source):
        """Reimport restores a missing managed copy without changing its identity."""
        source = Path(source).resolve()
        target = (self.root / attachment['path']).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError('附件记录不在本地文献库内，请重新关联文件。')
        if target.is_file() and digest(target) == attachment['sha']:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        index = 1
        while True:
            dest = target if index == 1 else target.with_stem(target.stem + f' ({index})')
            reserved = self.db.execute('SELECT id FROM attachments WHERE path=? COLLATE NOCASE AND id<>?',
                                       (str(dest.relative_to(self.root)), attachment['id'])).fetchone()
            if reserved:
                index += 1
                continue
            created = False
            try:
                with source.open('rb') as input_file, dest.open('xb') as output:
                    created = True
                    shutil.copyfileobj(input_file, output)
                break
            except FileExistsError:
                index += 1
            except Exception:
                if created:
                    dest.unlink(missing_ok=True)
                raise
        try:
            with self.db:
                self.db.execute('UPDATE attachments SET path=? WHERE id=?', (str(dest.relative_to(self.root)), attachment['id']))
                self.log('attachment-restored', {'paper': attachment['paper'], 'attachment': attachment['id'], 'path': str(dest)})
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        return dest

    def attach(self, rid, source, extract=True):
        if Path(source).suffix.lower() != '.pdf':
            raise ValueError('请选择 PDF 文件；Word 和补充文件请使用导入文档或关联附件。')
        primary = self.primary_attachment(rid)
        role = 'supplement' if primary and (self.root / primary['path']).is_file() else 'primary'
        return self._add_attachment(rid, source, '', role, extract=extract)

    def _add_attachment(self, rid, source, label, role, extract=False):
        if role not in ('primary', 'supplement', 'note'):
            raise ValueError('附件类型必须为正文或补充附件。')
        record = self.get(rid)
        source = Path(source).resolve()
        if not source.is_file():
            raise ValueError('附件文件不存在。')
        kind = attachment_kind({'path': str(source)})
        if role == 'primary' and kind not in ('pdf', 'docx', 'doc', 'txt', 'md'):
            raise ValueError('请选择 PDF、Word 或 TXT 文档作为正文。')
        metadata = {}
        if kind == 'pdf':
            with source.open('rb') as stream:
                if b'%PDF-' not in stream.read(1024):
                    raise ValueError('文件不是有效 PDF。')
            if extract and role == 'primary':
                metadata = pdf_metadata(source)
        elif kind in ('docx', 'doc', 'txt', 'md'):
            metadata = document_metadata(source)
        sha = digest(source)
        existing = self.db.execute('SELECT * FROM attachments WHERE paper=? AND sha=?', (rid, sha)).fetchone()
        if existing:
            restored = self._restore_attachment(dict(existing), source)
            if role == 'primary' and existing['role'] != 'primary':
                self.set_primary_attachment(rid, existing['id'])
            if str(label).strip():
                self.rename_attachment_label(rid, existing['id'], label)
            return restored
        aid = uuid.uuid4().hex
        attachment = {'id': aid, 'role': role, 'kind': kind, 'label': str(label).strip()[:200], 'original': str(source)}
        target = self.target(record, attachment)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental overwrite even for concurrent imports.
        index = 1
        while True:
            try:
                dest = target if index == 1 else target.with_stem(target.stem + f' ({index})')
                # Missing files still reserve their attachment path so a new version
                # cannot reuse the old file identity or its annotation association.
                if self.db.execute('SELECT id FROM attachments WHERE path=? COLLATE NOCASE',
                                   (str(dest.relative_to(self.root)),)).fetchone():
                    index += 1
                    continue
                with dest.open('xb') as output, source.open('rb') as input_file:
                    shutil.copyfileobj(input_file, output)
                break
            except FileExistsError:
                index += 1
            except Exception:
                if 'dest' in locals() and dest.exists():
                    dest.unlink()
                raise
        try:
            with self.db:
                if role == 'primary':
                    self.db.execute("UPDATE attachments SET role='supplement' WHERE paper=? AND role='primary'", (rid,))
                self.db.execute('INSERT INTO attachments(id,paper,path,sha,original,label,role,kind,url) VALUES(?,?,?,?,?,?,?,?,?)',
                                (aid, rid, str(dest.relative_to(self.root)), sha, str(source), attachment['label'], role, kind, ''))
                self.log('attach', {'paper': rid, 'source': str(source), 'path': str(dest)})
        except Exception:
            dest.unlink()
            raise
        if metadata.get('text') and role == 'primary':
            self.save({'text': metadata['text'], 'references': metadata.get('references', [])}, rid=rid)
        return dest

    def import_pdf(self, source, project=None):
        project = project or self.projects()[0]['id']
        sha = digest(source)
        old = self.db.execute('SELECT * FROM attachments WHERE sha=? ORDER BY rowid', (sha,)).fetchone()
        if old:
            if getattr(self,'_import_observer',None):self._import_observer(old['paper'])
            self._restore_attachment(dict(old), source)
            self.assign(old['paper'], project)
            return old['paper']
        metadata = pdf_metadata(source)
        self._preserve_primary_text(metadata)
        rid = self.save(metadata, project)
        self.attach(rid, source, extract=False)
        return rid

    def import_document(self, source, project=None):
        source = Path(source).resolve()
        if source.suffix.lower() == '.pdf':
            return self.import_pdf(source, project)
        metadata = document_metadata(source)
        project = project or self.projects()[0]['id']
        sha = digest(source)
        old = self.db.execute('SELECT * FROM attachments WHERE sha=? ORDER BY rowid', (sha,)).fetchone()
        if old:
            if getattr(self,'_import_observer',None):self._import_observer(old['paper'])
            self._restore_attachment(dict(old), source)
            self.assign(old['paper'], project)
            return old['paper']
        self._preserve_primary_text(metadata)
        rid = self.save(metadata, project)
        self.add_attachment(rid, source, role='supplement' if self.primary_attachment(rid) else 'primary')
        return rid

    def _preserve_primary_text(self, metadata):
        if metadata.get('doi'):
            row=self.db.execute("SELECT id FROM papers WHERE json_extract(data,'$.doi')=? LIMIT 1",(normalize_doi(metadata['doi']),)).fetchone()
            old=self.get(row[0]) if row else None
            if old and self.primary_attachment(old['id']):
                metadata.pop('text', None)
                metadata.pop('references', None)

    def rename(self, rid, destinations=None):
        record = self.get(rid)
        changed = []
        for attachment in local_attachments(record):
            if destinations is not None and attachment['id'] not in destinations:
                continue
            old = self.root / attachment['path']
            if not old.is_file():
                with self.db:
                    self.log('rename-missing-attachment', {'paper': rid, 'attachment': attachment['id'], 'path': str(old)})
                continue
            base = (self._managed_path(destinations[attachment['id']]) if destinations is not None
                    else self.target(record, attachment))
            base.parent.mkdir(parents=True, exist_ok=True)
            new = base
            index = 2
            while ((new.exists() and new.resolve() != old.resolve()) or
                   self.db.execute('SELECT id FROM attachments WHERE path=? COLLATE NOCASE AND id<>?',
                                   (str(new.relative_to(self.root)), attachment['id'])).fetchone()):
                if destinations is not None:
                    raise ValueError('预览中的目标文件名已被占用，请重新预览。')
                new = base.with_stem(base.stem + f' ({index})')
                index += 1
            if new.resolve() == old.resolve():
                continue
            # Copy then update database; unlink only after the durable new path is recorded.
            created = False
            try:
                with old.open('rb') as input_file, new.open('xb') as output:
                    created = True
                    shutil.copyfileobj(input_file, output)
            except Exception:
                if created:
                    new.unlink(missing_ok=True)
                raise
            try:
                with self.db:
                    self.db.execute('UPDATE attachments SET path=? WHERE id=?', (str(new.relative_to(self.root)), attachment['id']))
                    self.log('rename', {'old': str(old), 'new': str(new), 'paper': rid})
            except Exception:
                new.unlink()
                raise
            try:old.unlink()
            except PermissionError:
                with self.db:self.log('rename-old-copy-retained',{'path':str(old),'reason':'file in use'})
            changed.append((str(old), str(new)))
        return changed

    def graph(self, project=None, include_candidates=True):
        records = self.records(project)
        nodes = [{'id': r['id'], 'title': display_name(r), 'article_title': r['title'], 'year': r['year'], 'status': r['status'],
                  'doi': r['doi'], 'pdf': any(a.get('role') == 'primary' for a in readable_attachments(r)), 'in_library':True,'read_count':r.get('read_count',0),
                  'projects': [self.project(p)['name'] for p in r['projects']]} for r in records]
        texts, df = {}, collections.Counter()
        for r in records:
            words = re.findall(r'[a-z][a-z0-9-]{2,}|[\u4e00-\u9fff]{2,4}', (' '.join(str(r.get(k, '')) for k in ('title', 'abstract', 'keywords'))).lower())
            counts = collections.Counter(w for w in words if w not in STOPWORDS)
            texts[r['id']] = counts
            df.update(counts.keys())
        vectors = {}
        for rid, counts in texts.items():
            vec = {w: (1 + math.log(n)) * math.log(1 + len(records) / df[w]) for w, n in counts.items()}
            norm = math.sqrt(sum(v*v for v in vec.values())) or 1
            vectors[rid] = {w: v / norm for w, v in vec.items()}
        edges = {}
        # Posting lists avoid comparing unrelated papers and keep larger libraries responsive.
        postings = collections.defaultdict(list)
        for rid, vec in vectors.items():
            for word in vec:
                if df[word] <= max(20, len(records) * .3):
                    postings[word].append(rid)
        scores = collections.Counter()
        for word, ids in postings.items():
            for i, first in enumerate(ids):
                for second in ids[i+1:]:
                    pair = tuple(sorted((first, second)))
                    scores[pair] += vectors[first][word] * vectors[second][word]
        nearest = collections.defaultdict(list)
        for (a, b), score in scores.items():
            if score >= .18:
                nearest[a].append((score, b)); nearest[b].append((score, a))
        for a, matches in nearest.items():
            for score, b in sorted(matches, reverse=True)[:4]:
                pair = tuple(sorted((a, b)))
                edges[pair] = {'source': pair[0], 'target': pair[1], 'kind': 'similarity', 'weight': round(score, 3)}
        dois = {r['doi']: r['id'] for r in records if r['doi']}
        citations = []
        for r in records:
            from references import parse_references
            for ref in r.get('references') or parse_references(r.get('text','')):
                target=dois.get(normalize_doi(ref.get('doi','')))
                if target and target!=r['id'] and not any(e['source']==r['id'] and e['target']==target for e in citations):citations.append({'source':r['id'],'target':target,'kind':'citation','weight':1})
        if include_candidates:
            from references import parse_references
            existing_titles={re.sub(r'\W+','',r['title']).lower() for r in records}
            candidates={};candidate_edges=[]
            for r in records:
                refs=r.get('references') or parse_references(r.get('text',''))
                for ref in refs:
                    if normalize_doi(ref['doi']) in dois or re.sub(r'\W+','',ref['title']).lower() in existing_titles:continue
                    cid=ref['id']
                    if cid not in candidates and len(candidates)>=400:continue
                    if cid not in candidates:
                        candidates[cid]={'id':cid,'title':ref['title'],'year':ref['year'],'status':'未入库','doi':ref['doi'],
                                         'pdf':False,'in_library':False,'read_count':0,'projects':[],
                                         'query':ref['query'],'evidence':ref['confidence'],'raw':ref['raw']}
                    for pid in r['projects']:
                        pname=self.project(pid)['name']
                        if pname not in candidates[cid]['projects']:candidates[cid]['projects'].append(pname)
                    candidate_edges.append({'source':r['id'],'target':cid,'kind':'candidate','weight':1,'evidence':ref['confidence']})
            nodes.extend(candidates.values());edges_list=list(edges.values())+citations+candidate_edges
        else:edges_list=list(edges.values())+citations
        incoming=collections.Counter(e['target'] for e in citations)
        for n in nodes:n['citation_count']=incoming[n['id']]
        edges_list.extend(self.relation_edges({r['id'] for r in records}))
        for r in records:
            for a in r['attachments']:
                if a.get('role')!='note':continue
                nid='note-'+a['id'];nodes.append({'id':nid,'kind':'note','paper_id':r['id'],'attachment_id':a['id'],
                    'title':a.get('label') or '阅读笔记','year':r['year'],'status':'笔记','doi':'','pdf':False,'in_library':True,
                    'read_count':0,'citation_count':0,'projects':[self.project(p)['name'] for p in r['projects']],'path':a['path']})
                edges_list.append({'source':r['id'],'target':nid,'kind':'note','weight':1,'label':'阅读笔记'})
        # Supplements are visible documents, connected to their owning paper.
        # If the identical file is already another paper's primary, connect those
        # paper nodes instead of producing a duplicate document node.
        primaries = collections.defaultdict(list)
        for r in records:
            for a in readable_attachments(r):
                if a.get('role') == 'primary' and a.get('sha'):
                    primaries[a['sha']].append(r['id'])
        attachment_pairs = set()
        for r in records:
            for a in readable_attachments(r):
                if a.get('role') in ('primary', 'note'):
                    continue
                targets = [rid for rid in primaries.get(a.get('sha'), []) if rid != r['id']]
                if not targets:
                    nid = 'attachment-' + a['id']
                    nodes.append({'id': nid, 'kind': 'attachment', 'paper_id': r['id'], 'attachment_id': a['id'],
                        'title': a.get('label') or Path(a.get('original') or a['path']).stem,
                        'year': '', 'status': '附件', 'doi': '', 'pdf': attachment_kind(a) == 'pdf',
                        'in_library': True, 'read_count': 0, 'citation_count': 0,
                        'projects': [self.project(p)['name'] for p in r['projects']], 'path': a['path']})
                    targets = [nid]
                for target in targets:
                    pair = tuple(sorted((r['id'], target)))
                    if pair not in attachment_pairs:
                        attachment_pairs.add(pair)
                        edges_list.append({'source': r['id'], 'target': target, 'kind': 'attachment',
                                           'weight': 1, 'label': '附件关联'})
        return {'nodes':nodes,'edges':edges_list,'groups':self.graph_groups({r['id'] for r in records}),
                'summary':{'total':len(records),'pdf':sum(any(a.get('role') == 'primary' for a in readable_attachments(r)) for r in records),
                           'read':sum(r['status']=='已读' for r in records),'citations':len(citations),
                           'candidates':sum(not n['in_library'] for n in nodes)}}

def download_pdf(library, rid, url):
    import urllib.request
    from paper_finder import public_url, PublicRedirect
    public_url(url)
    stage = library.root / 'staging'
    stage.mkdir(exist_ok=True)
    fd, name = tempfile.mkstemp(suffix='.pdf', dir=stage)
    os.close(fd)
    try:
        opener = urllib.request.build_opener(PublicRedirect())
        request = urllib.request.Request(url, headers={'User-Agent': 'PaperQuick/3.0', 'Accept': 'application/pdf'})
        with opener.open(request, timeout=20) as response, open(name, 'wb') as output:
            total = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                total += len(chunk)
                if total > 100 * 1024 * 1024:
                    raise ValueError('PDF 超过 100 MB，请手动下载后关联。')
                output.write(chunk)
        return library.attach(rid, name)
    finally:
        Path(name).unlink(missing_ok=True)
