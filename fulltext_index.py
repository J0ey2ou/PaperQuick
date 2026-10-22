"""Local, page-complete search index. Files never leave the machine."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

from library_core import Library, display_name

EXTRACTOR_VERSION = 'fulltext-1'
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


class IndexCancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()):
        raise IndexCancelled('全文索引已取消，已完成的附件仍可搜索。')


@contextmanager
def cancellable_lock(lock, cancel=None):
    while not lock.acquire(timeout=.1):
        check_cancel(cancel)
    try:
        check_cancel(cancel)
        yield
    finally:
        lock.release()


def file_sha(path, cancel=None):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        while True:
            check_cancel(cancel)
            block = source.read(1024 * 1024)
            if not block:break
            digest.update(block)
    return digest.hexdigest()


def local_source(root, relative):
    path = (Path(root) / relative).resolve()
    if path == Path(root) or Path(root) not in path.parents:
        raise ValueError('附件路径不在本地文献库内。')
    if not path.is_file():raise FileNotFoundError('归档文件缺失，请重新关联文件。')
    return path


def logical_paragraphs(path):
    """Return logical paragraphs, never pretend DOCX/TXT has physical PDF pages."""
    path = Path(path)
    if path.suffix.lower() == '.docx':
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > 64 * 1024 * 1024:raise ValueError('Word 正文 XML 超过 64 MB，无法安全索引。')
            raw = archive.read(info)
        checked = raw.replace(b'\x00', b'').upper()
        if b'<!DOCTYPE' in checked or b'<!ENTITY' in checked:raise ValueError('Word 包含不支持的 XML 定义。')
        namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        tree = ET.fromstring(raw)
        parts = []
        for paragraph in tree.iter(namespace + 'p'):
            text = ''.join(element.text or '' if element.tag == namespace + 't' else '\t' if element.tag == namespace + 'tab' else '\n' if element.tag in (namespace + 'br', namespace + 'cr') else '' for element in paragraph.iter())
            parts.append(text)
        return parts
    from reading_documents import read_text_file
    return read_text_file(path).replace('\r\n', '\n').replace('\r', '\n').split('\n')


class LocalOCR:
    """Explicitly configured local Tesseract; no shell, downloads, or network."""
    def __init__(self, executable='', languages='eng'):
        self.executable = str(executable or shutil.which('tesseract') or '')
        self.languages = str(languages or 'eng').strip()
        if not re.fullmatch(r'[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*', self.languages):
            raise ValueError('OCR 语言格式例如 eng 或 chi_sim+eng。')

    def _executable(self):
        path = Path(self.executable).expanduser() if self.executable else None
        if not path or not path.is_file():
            raise ValueError('未找到本地 Tesseract。请在 OCR 设置中选择已安装的可执行文件；软件不会下载引擎或上传文献。')
        return str(path.resolve())

    def _run(self, arguments, cancel=None, timeout=120):
        check_cancel(cancel)
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        process = subprocess.Popen([self._executable(), *arguments], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        started = time.monotonic()
        try:
            while True:
                check_cancel(cancel)
                if time.monotonic() - started > timeout:raise ValueError('本地 OCR 超时，可取消任务后检查引擎和语言包。')
                try:
                    output, error = process.communicate(timeout=.15)
                    break
                except subprocess.TimeoutExpired:pass
            if process.returncode:
                detail = error.decode('utf-8', 'replace').strip()[:500]
                raise ValueError('本地 OCR 未完成：' + (detail or f'退出码 {process.returncode}'))
            return output.decode('utf-8', 'replace')
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def probe(self, cancel=None):
        output = self._run(['--list-langs'], cancel, timeout=15)
        languages = [line.strip() for line in output.splitlines() if re.fullmatch(r'[A-Za-z0-9_]+', line.strip())]
        missing = sorted(set(self.languages.split('+')) - set(languages))
        if missing:raise ValueError('本地 OCR 缺少语言包：' + '、'.join(missing) + '。请自行安装语言包或修改语言设置。')
        return {'executable': self._executable(), 'languages': languages, 'selected': self.languages}

    def recognize(self, image, directory, cancel=None):
        with tempfile.TemporaryDirectory(prefix='ocr-', dir=directory) as temporary:
            source = Path(temporary) / 'page.png'
            image.save(source)
            return self._run([str(source), 'stdout', '-l', self.languages, '--psm', '3'], cancel).strip()


def pdf_segments(path, cancel=None, ocr=None, scratch=None, progress=None):
    """Extract every PDF page; PDFium calls share the reader's process-wide lock."""
    from pdf_reader_core import _LOCK, pdfium, render_page
    with cancellable_lock(_LOCK, cancel):document = pdfium().PdfDocument(path)
    try:
        with cancellable_lock(_LOCK, cancel):total = len(document)
        for number in range(total):
            check_cancel(cancel)
            with cancellable_lock(_LOCK, cancel):
                page = document[number]
                try:
                    textpage = page.get_textpage()
                    try:text = textpage.get_text_range()
                    finally:textpage.close()
                finally:page.close()
            origin = 'text'
            if not text.strip():
                origin = 'empty'
                if ocr:
                    with cancellable_lock(_LOCK, cancel):image = render_page(path, number, 2)
                    try:
                        check_cancel(cancel)
                        text = ocr.recognize(image, scratch, cancel)
                    finally:image.close()
                    origin = 'ocr' if text.strip() else 'empty'
            if progress:progress(number + 1, total, f'第 {number + 1} / {total} 页')
            yield {'locator_kind': 'page', 'page': number, 'paragraph': None, 'text': text, 'origin': origin}
    finally:
        with _LOCK:document.close()


class FulltextIndex:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.cache = self.root / 'cache' / 'fulltext'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.path = self.cache / 'index.sqlite'
        with _LOCKS_GUARD:self.lock = _LOCKS.setdefault(str(self.root).casefold(), threading.RLock())
        with self._db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents(
                    key TEXT PRIMARY KEY,paper TEXT NOT NULL,attachment TEXT,title TEXT,label TEXT,path TEXT,
                    sha TEXT,signature TEXT,status TEXT,total INTEGER DEFAULT 0,text_units INTEGER DEFAULT 0,
                    empty_units INTEGER DEFAULT 0,ocr_units INTEGER DEFAULT 0,locator_kind TEXT,error TEXT DEFAULT '',
                    size INTEGER,mtime INTEGER,updated REAL);
                CREATE INDEX IF NOT EXISTS documents_paper ON documents(paper);
                CREATE TABLE IF NOT EXISTS segments(id INTEGER PRIMARY KEY,document TEXT NOT NULL,source TEXT,
                    locator_kind TEXT,page INTEGER,paragraph INTEGER,origin TEXT,text TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS segments_document ON segments(document);
            ''')
            try:
                db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(text,content='segments',content_rowid='id',tokenize='trigram')")
                db.executescript('''
                    CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
                        INSERT INTO segments_fts(rowid,text) VALUES(new.id,new.text); END;
                    CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
                        INSERT INTO segments_fts(segments_fts,rowid,text) VALUES('delete',old.id,old.text); END;
                ''')
                self.fts = True
            except sqlite3.OperationalError:self.fts = False

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def ocr_config(self):
        lib = Library(self.root)
        try:return lib.setting('local_ocr', {'executable': '', 'languages': 'eng'})
        finally:lib.close()

    def save_ocr_config(self, executable, languages):
        engine = LocalOCR(executable, languages)
        values = {'executable': engine.executable, 'languages': engine.languages}
        lib = Library(self.root)
        try:lib.set_setting('local_ocr', values)
        finally:lib.close()
        return values

    def _inventory(self, project=None, rid=None, attachment_id=None):
        lib = Library(self.root)
        try:
            records = lib.records(project, summary=True)
            if rid:records = [record for record in records if record['id'] == rid]
            result = []
            for record in records:
                for attachment in record['attachments']:
                    if attachment_id and attachment['id'] != attachment_id:continue
                    if attachment.get('url') or not attachment.get('path'):continue
                    result.append(dict(key=attachment['id'], paper=record['id'], attachment=attachment['id'],
                                       title=display_name(record), label=attachment.get('label') or Path(attachment['path']).name,
                                       path=attachment['path'], source='正文' if attachment.get('role') == 'primary' else '笔记附件' if attachment.get('role') == 'note' else '附件'))
                if attachment_id:continue
                row = lib.db.execute("SELECT json_extract(data,'$.notes'),json_extract(data,'$.annotations') FROM papers WHERE id=?", (record['id'],)).fetchone()
                annotations = json.loads(row[1] or '[]')
                segments = [{'text': ' '.join(str(record.get(field) or '') for field in ('title', 'authors', 'year', 'doi', 'venue', 'abstract', 'keywords', 'tags')), 'source': '书目信息', 'locator_kind': 'record', 'page': None, 'paragraph': None, 'origin': 'record'},
                            {'text': row[0] or '', 'source': '笔记', 'locator_kind': 'note', 'page': None, 'paragraph': None, 'origin': 'note'}]
                for annotation in annotations:
                    segments.append({'text': '\n'.join(str(annotation.get(field) or '') for field in ('quote', 'text')), 'source': '批注', 'locator_kind': 'annotation', 'page': annotation.get('page'), 'paragraph': None, 'origin': annotation.get('attachment') or ''})
                result.append(dict(key='record:' + record['id'], paper=record['id'], attachment=None,
                                   title=display_name(record), label='书目信息 / 笔记 / 批注', path='', source='笔记', segments=segments))
            return result
        finally:lib.close()

    def _state(self, db, item, status, error='', **fields):
        values = dict(item)
        values.update(status=status, error=error, updated=time.time(), **fields)
        keys = ('key', 'paper', 'attachment', 'title', 'label', 'path', 'sha', 'signature', 'status', 'total', 'text_units', 'empty_units', 'ocr_units', 'locator_kind', 'error', 'size', 'mtime', 'updated')
        db.execute('INSERT OR REPLACE INTO documents(' + ','.join(keys) + ') VALUES(' + ','.join('?' for _ in keys) + ')', tuple(values.get(key) for key in keys))

    def update(self, project=None, rid=None, attachment_id=None, cancel=None, progress=None, ocr=False):
        engine = LocalOCR(**self.ocr_config()) if ocr else None
        if engine:engine.probe(cancel)
        signature = EXTRACTOR_VERSION + (':' + json.dumps(self.ocr_config(), sort_keys=True) if ocr else ':text')
        result = {'updated': 0, 'unchanged': 0, 'errors': 0, 'files': 0}
        with cancellable_lock(self.lock, cancel), self._db() as db:
            inventory = self._inventory(project, rid, attachment_id)
            # Remove deleted items only within the requested scope; unrelated indices stay intact.
            live = {item['key'] for item in self._inventory()}
            for row in db.execute('SELECT key FROM documents').fetchall():
                if row['key'] not in live:
                    db.execute('DELETE FROM segments WHERE document=?', (row['key'],))
                    db.execute('DELETE FROM documents WHERE key=?', (row['key'],))
            db.commit()
            for number, item in enumerate(inventory):
                check_cancel(cancel)
                result['files'] += bool(item['attachment'])
                if progress:progress(number, len(inventory), '正在索引：' + item['label'])
                try:
                    stat = None
                    if item['attachment']:
                        path = local_source(self.root, item['path'])
                        if path.suffix.lower() not in ('.pdf', '.docx', '.txt', '.md'):
                            raise ValueError('此附件格式暂不提供全文索引；DOC 请先转换为 DOCX 或 PDF。')
                        stat = path.stat()
                        sha = file_sha(path, cancel)
                    else:sha = hashlib.sha256(json.dumps(item['segments'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                    old = db.execute('SELECT * FROM documents WHERE key=?', (item['key'],)).fetchone()
                    if old and old['sha'] == sha and (old['signature'] == signature or not ocr and old['signature'].startswith(EXTRACTOR_VERSION + ':')) and old['status'] in ('complete', 'partial', 'empty'):
                        db.execute('UPDATE documents SET title=?,label=?,path=?,size=?,mtime=? WHERE key=?', (item['title'], item['label'], item['path'], stat.st_size if stat else None, stat.st_mtime_ns if stat else None, item['key']))
                        db.commit();result['unchanged'] += 1
                        continue
                    self._state(db, item, 'indexing', sha=sha, signature=signature)
                    db.commit()
                    if not item['attachment']:segments = item['segments']
                    elif path.suffix.lower() == '.pdf':
                        def page_progress(done, total, message):
                            if progress:progress(number, len(inventory), item['label'] + ' · ' + message)
                        segments = list(pdf_segments(path, cancel, engine, self.cache, page_progress))
                    else:
                        segments = []
                        for paragraph, text in enumerate(logical_paragraphs(path)):
                            check_cancel(cancel)
                            segments.append(dict(locator_kind='paragraph', page=None, paragraph=paragraph, text=text, origin='text' if text.strip() else 'empty'))
                    check_cancel(cancel)
                    if stat and (stat.st_size, stat.st_mtime_ns) != (path.stat().st_size, path.stat().st_mtime_ns):
                        raise ValueError('文件在索引期间发生变化，请重新建立索引。')
                    count = sum(bool(segment['text'].strip()) for segment in segments)
                    empty = len(segments) - count
                    status = 'complete' if not empty else 'partial' if count else 'empty'
                    with db:
                        db.execute('DELETE FROM segments WHERE document=?', (item['key'],))
                        for segment in segments:
                            db.execute('INSERT INTO segments(document,source,locator_kind,page,paragraph,origin,text) VALUES(?,?,?,?,?,?,?)', (item['key'], segment.get('source', item['source']), segment['locator_kind'], segment.get('page'), segment.get('paragraph'), segment['origin'], segment['text']))
                        self._state(db, item, status, sha=sha, signature=signature, total=len(segments), text_units=count,
                                    empty_units=empty, ocr_units=sum(segment['origin'] == 'ocr' for segment in segments),
                                    locator_kind=segments[0]['locator_kind'] if segments else 'paragraph',
                                    size=stat.st_size if stat else None, mtime=stat.st_mtime_ns if stat else None)
                    result['updated'] += 1
                except IndexCancelled:
                    self._state(db, item, 'interrupted', '已取消；此附件尚未建立完整索引。')
                    db.commit();raise
                except Exception as exc:
                    self._state(db, item, 'missing' if isinstance(exc, FileNotFoundError) else 'error', str(exc))
                    db.commit();result['errors'] += 1
            if progress:progress(len(inventory), len(inventory), '全文索引完成')
        return result

    def coverage(self, project=None, rid=None, attachment_id=None):
        inventory = self._inventory(project, rid, attachment_id)
        with self._db() as db:states = {row['key']: dict(row) for row in db.execute('SELECT * FROM documents')}
        results = []
        for item in inventory:
            if not item['attachment']:continue
            state = states.get(item['key'], dict(status='pending', total=0, text_units=0, empty_units=0, ocr_units=0, error='尚未建立索引'))
            entry = dict(state, paper=item['paper'], attachment=item['attachment'], title=item['title'], label=item['label'])
            try:
                stat = local_source(self.root, item['path']).stat()
                if entry['status'] in ('complete', 'partial', 'empty') and (stat.st_size, stat.st_mtime_ns) != (state.get('size'), state.get('mtime')):
                    entry.update(status='stale', error='文件已改变，请更新索引。')
            except (ValueError, OSError) as exc:entry.update(status='missing', error=str(exc))
            results.append(entry)
        return results

    def search(self, query, project=None, rid=None, attachment_id=None, limit=100, include_text=False, cancel=None):
        terms = str(query).strip().split()
        if not terms:return []
        if len(terms) > 12 or len(query) > 500:raise ValueError('请输入不超过 500 字、12 个关键词。')
        inventory = self._inventory(project, rid, attachment_id)
        live = {item['key']: item for item in inventory}
        allowed = {item['attachment'] for item in self.coverage(project, rid, attachment_id) if item['status'] in ('complete', 'partial', 'empty')}
        arguments = []
        where = ["d.status IN ('complete','partial','empty')"]
        if self.fts and all(len(term) >= 3 for term in terms):
            where.append('s.id IN (SELECT rowid FROM segments_fts WHERE segments_fts MATCH ?)')
            arguments.append(' AND '.join('"' + term.replace('"', '""') + '"' for term in terms))
        else:
            for term in terms:
                where.append("s.text LIKE ? ESCAPE '\\'")
                arguments.append('%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
        if rid:where.append('d.paper=?');arguments.append(rid)
        if attachment_id:where.append('d.attachment=?');arguments.append(attachment_id)
        sql = 'SELECT s.*,d.paper,d.attachment,d.title,d.label,d.path,d.sha FROM segments s JOIN documents d ON d.key=s.document WHERE ' + ' AND '.join(where) + ' ORDER BY d.title,s.page,s.paragraph,s.id'
        results = []
        with self._db() as db:
            for row in db.execute(sql, arguments):
                check_cancel(cancel)
                item = dict(row)
                if item['document'] not in live or item['attachment'] and item['attachment'] not in allowed:continue
                folded = item['text'].casefold()
                if not all(term.casefold() in folded for term in terms):continue
                start = max(0, min(folded.find(term.casefold()) for term in terms) - 65)
                item['snippet'] = ('…' if start else '') + item['text'][start:start + 240].replace('\n', ' ') + ('…' if start + 240 < len(item['text']) else '')
                item['query'] = query
                if item['locator_kind'] == 'annotation':item['attachment'] = item['origin'] or None
                if not include_text:item.pop('text')
                results.append(item)
                if len(results) >= max(1, min(int(limit), 1000)):break
        return results
