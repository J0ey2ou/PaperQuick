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

FIELDS = ('title', 'authors', 'year', 'doi', 'venue', 'abstract', 'keywords', 'notes', 'status')
DEFAULT_TEMPLATE = '{年份}_{第一作者}_{标题}'
TOKENS = {'年份', '第一作者', '标题', 'DOI', '课题', 'year', 'author', 'title', 'doi', 'project'}
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
        raise ValueError('使用 {年份}、{第一作者}、{标题}、{DOI}、{课题}，不支持格式代码。')
    return template

def filename(record, project, template=DEFAULT_TEMPLATE, title_length=80):
    validate_template(template)
    author = re.split(r'\n|;|；| 等| et al', record.get('authors', ''))[0].strip() or '未知作者'
    values = {'年份': record.get('year') or '未知年份', '第一作者': author,
              '标题': (record.get('title') or '未命名')[:title_length], 'DOI': record.get('doi') or '无DOI', '课题': project}
    values.update(dict(zip(('year', 'author', 'title', 'doi', 'project'), (values[k] for k in ('年份', '第一作者', '标题', 'DOI', '课题')))))
    return clean_name(template.format(**values), 150) + '.pdf'

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

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
    meta = reader.metadata or {}
    texts = []
    indices=sorted(set(range(min(12,len(reader.pages))))|set(range(max(0,len(reader.pages)-12),len(reader.pages))))
    for index in indices:
        page=reader.pages[index]
        # Avoid processing enormous content streams in unexpectedly large PDFs.
        texts.append((page.extract_text() or '')[:30000])
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

class Library:
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
        if not self.projects():
            self.create_project('未分类')

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

    def create_project(self, name):
        name = name.strip()
        if not name:
            raise ValueError('请填写课题名称。')
        old = self.db.execute('SELECT id FROM projects WHERE name=?', (name,)).fetchone()
        if old:
            return old[0]
        pid = uuid.uuid4().hex
        folder = clean_name(name, 60) + '_' + pid[:6]
        (self.root / 'papers' / folder).mkdir(parents=True, exist_ok=True)
        with self.db:
            self.db.execute('INSERT INTO projects(id,name,folder) VALUES(?,?,?)', (pid, name, folder))
        return pid

    def records(self, project=None):
        query = 'SELECT p.* FROM papers p'
        args = ()
        if project:
            query += ' JOIN memberships m ON m.paper=p.id WHERE m.project=?'
            args = (project,)
        return [self._record(row) for row in self.db.execute(query + ' ORDER BY p.updated DESC', args)]

    def _record(self, row):
        data = json.loads(row['data'])
        data.update(id=row['id'], primary_project=row['primary_project'])
        data['projects'] = [r[0] for r in self.db.execute('SELECT project FROM memberships WHERE paper=?', (row['id'],))]
        data['attachments'] = [dict(r) for r in self.db.execute('SELECT * FROM attachments WHERE paper=?', (row['id'],))]
        return data

    def get(self, rid):
        row = self.db.execute('SELECT * FROM papers WHERE id=?', (rid,)).fetchone()
        if not row:
            raise ValueError('文献不存在。')
        return self._record(row)

    def save(self, data, project=None, rid=None, deduplicate=True):
        data = dict(data)
        if 'doi' in data:
            data['doi'] = normalize_doi(data['doi'])
        if not rid and deduplicate and data.get('doi'):
            rid = next((r['id'] for r in self.records() if r.get('doi') == data['doi']), None)
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
            self.log('save', {'paper': rid})
        return rid

    def assign(self, rid, project, primary=False):
        self.project(project)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO memberships VALUES(?,?)', (rid, project))
            if primary:
                self.db.execute('UPDATE papers SET primary_project=? WHERE id=?', (project, rid))
        if primary:
            self.rename(rid)

    def template(self, project):
        return self.project(project)['template'] or self.setting('template', DEFAULT_TEMPLATE)

    def target(self, record):
        project = self.project(record['primary_project'])
        return self.root / 'papers' / project['folder'] / filename(record, project['name'], self.template(project['id']), self.setting('title_length', 80))

    def attach(self, rid, source, extract=True):
        source = Path(source).resolve()
        metadata = pdf_metadata(source) if extract else {}
        with source.open('rb') as stream:
            if b'%PDF-' not in stream.read(1024):
                raise ValueError('文件不是 PDF。')
        sha = digest(source)
        existing = self.db.execute('SELECT * FROM attachments WHERE paper=? AND sha=?', (rid, sha)).fetchone()
        if existing:
            return self.root / existing['path']
        record = self.get(rid)
        if metadata.get('text'):
            self.save({'text': metadata['text'],'references':metadata.get('references',[])}, rid=rid)
        target = self.target(record)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental overwrite even for concurrent imports.
        index = 1
        while True:
            try:
                dest = target if index == 1 else target.with_stem(target.stem + f' ({index})')
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
                self.db.execute('INSERT INTO attachments VALUES(?,?,?,?,?)', (uuid.uuid4().hex, rid, str(dest.relative_to(self.root)), sha, str(source)))
                self.log('attach', {'paper': rid, 'source': str(source), 'path': str(dest)})
        except Exception:
            dest.unlink()
            raise
        return dest

    def import_pdf(self, source, project):
        sha = digest(source)
        old = self.db.execute('SELECT paper FROM attachments WHERE sha=?', (sha,)).fetchone()
        if old:
            self.assign(old[0], project)
            return old[0]
        metadata = pdf_metadata(source)
        rid = self.save(metadata, project)
        self.attach(rid, source, extract=False)
        return rid

    def rename(self, rid):
        record = self.get(rid)
        changed = []
        for attachment in record['attachments']:
            old = self.root / attachment['path']
            base = self.target(record)
            base.parent.mkdir(parents=True, exist_ok=True)
            new = base
            index = 2
            while new.exists() and new.resolve() != old.resolve():
                new = base.with_stem(base.stem + f' ({index})')
                index += 1
            if new.resolve() == old.resolve():
                continue
            # Copy then update database; unlink only after the durable new path is recorded.
            with new.open('xb') as output, old.open('rb') as input_file:
                shutil.copyfileobj(input_file, output)
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
        nodes = [{'id': r['id'], 'title': r['title'], 'year': r['year'], 'status': r['status'],
                  'doi': r['doi'], 'pdf': bool(r['attachments']), 'in_library':True,'read_count':r.get('read_count',0),
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
            # Only DOI matches inside the extracted References section count as citations.
            text = r.get('text', '')
            section = re.split(r'\bReferences\b|\bBibliography\b|参考文献', text, flags=re.I)
            if len(section) < 2:
                continue
            refs = section[-1].lower()
            for doi, target in dois.items():
                if target != r['id'] and re.search(re.escape(doi) + r'(?=$|[\s\]<>".,;)])', refs):
                    citations.append({'source': r['id'], 'target': target, 'kind': 'citation', 'weight': 1})
        if include_candidates:
            from references import parse_references
            existing_titles={re.sub(r'\W+','',r['title']).lower() for r in records}
            candidates={};candidate_edges=[]
            for r in records:
                refs=r.get('references') or parse_references(r.get('text',''))
                for ref in refs:
                    if ref['doi'] in dois or re.sub(r'\W+','',ref['title']).lower() in existing_titles:continue
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
        return {'nodes':nodes,'edges':edges_list,
                'summary':{'total':len(records),'pdf':sum(bool(r['attachments']) for r in records),
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
