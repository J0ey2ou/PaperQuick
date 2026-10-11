"""Local topic watchlists and reversible discovery batches.

Europe PMC documents FIRST_PDATE, sort_date:y, cursorMark and core metadata at
https://europepmc.org/Help and https://europepmc.org/RestfulWebService .
No credentials, language model, or local document upload is involved.
"""
from __future__ import annotations

import datetime as dt
import html
import ipaddress
import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid

from library_core import normalize_doi

_SESSION = uuid.uuid4().hex
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
ENDPOINT = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'
MAX_RESULTS = 50


def _day(value=None):
    if value is None:
        return dt.date.today()
    if isinstance(value, dt.datetime):
        return value.date()
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))


def _text(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))).strip()


def _doi(value):
    return normalize_doi(urllib.parse.unquote(str(value or '')))


def _title(value):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', _text(value)).casefold())


def _safe_url(value):
    """Accept ordinary public web links, never scripts, file paths or credentials."""
    value = str(value or '').strip()
    if any(ord(char) < 32 for char in value):
        return ''
    try:
        parts = urllib.parse.urlsplit(value)
        host = (parts.hostname or '').lower()
        if parts.scheme not in ('http', 'https') or not host or parts.username or parts.password:
            return ''
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')) or '.' not in host:
            return ''
        try:
            if not ipaddress.ip_address(host).is_global:
                return ''
        except ValueError:
            pass
        return value
    except ValueError:
        return ''


def _metadata(item):
    """Support Europe PMC core records and the documented injected fetcher shape."""
    doi = _doi(item.get('doi'))
    title = _text(item.get('title'))
    published = _text(item.get('published') or item.get('firstPublicationDate'))
    authors = item.get('authors') or item.get('authorString') or ''
    if isinstance(authors, list):
        authors = '; '.join(_text(a.get('fullName') if isinstance(a, dict) else a) for a in authors)
    journal_info = item.get('journalInfo') or {}
    journal = journal_info.get('journal') or {}
    source = _text(item.get('source') or 'Europe PMC')
    identifier = _text(item.get('id'))
    url = _safe_url(item.get('url'))
    if not url and doi:
        url = 'https://doi.org/' + urllib.parse.quote(doi, safe='/():;.-_')
    if not url and identifier:
        url = 'https://europepmc.org/article/' + urllib.parse.quote(source, safe='') + '/' + urllib.parse.quote(identifier, safe='')
    links = [{'label': '文献页面', 'url': url, 'kind': 'publisher', 'source': 'Europe PMC'}] if url else []
    return {'title': title, 'doi': doi, 'year': _text(item.get('year') or item.get('pubYear') or published[:4]),
            'authors': _text(authors), 'venue': _text(item.get('venue') or journal.get('title') or item.get('journalTitle')),
            'abstract': _text(item.get('abstract') or item.get('abstractText')),
            'published': published, 'url': url, 'source': source, 'links': links}


class _TrustedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme != 'https' or parts.hostname not in {'www.ebi.ac.uk', 'ebi.ac.uk', 'europepmc.org', 'www.europepmc.org'}:
            raise urllib.error.URLError('unexpected redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_europepmc(query, start_date, end_date, limit=MAX_RESULTS):
    """Return up to 50 newest publications, with an explicit completeness flag.

    The date interval is inclusive. Two cursor pages are sufficient for the
    normal 50-result batch. hitCount, not merely nextCursorMark, detects overflow.
    """
    limit = min(MAX_RESULTS, max(1, int(limit)))
    effective = f'({query}) AND FIRST_PDATE:[{_day(start_date).isoformat()} TO {_day(end_date).isoformat()}] sort_date:y'
    opener = urllib.request.build_opener(_TrustedRedirect())
    cursor, items, total = '*', [], 0
    while len(items) < limit:
        params = urllib.parse.urlencode({'query': effective, 'format': 'json', 'resultType': 'core',
                                        'pageSize': min(25, limit - len(items)), 'cursorMark': cursor})
        request = urllib.request.Request(ENDPOINT + '?' + params,
                                         headers={'User-Agent': 'PaperQuick/3.2 (literature watchlist)', 'Accept': 'application/json'})
        with opener.open(request, timeout=12) as response:
            content = response.read(4 * 1024 * 1024 + 1)
            if len(content) > 4 * 1024 * 1024:
                raise ValueError('response too large')
        payload = json.loads(content)
        if not isinstance(payload, dict) or 'hitCount' not in payload:
            raise ValueError('unexpected search response')
        total = int(payload['hitCount'])
        rows = payload.get('resultList', {}).get('result', [])
        if not isinstance(rows, list):
            raise ValueError('unexpected result list')
        items.extend(_metadata(row) for row in rows if isinstance(row, dict))
        next_cursor = payload.get('nextCursorMark')
        if not rows or not next_cursor or next_cursor == cursor or len(items) >= total:
            break
        cursor = next_cursor
    return {'items': items[:limit], 'total': total, 'truncated': total > len(items), 'query': effective}


def _error_message(exc):
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (400, 422):
            return '检索条件暂时无法识别，请检查括号、引号和关键词后重试。'
        if exc.code == 429:
            return '文献服务当前较忙，请稍后再试。'
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, OSError)):
        return '暂时未能连接文献服务，请检查网络后重试。'
    return '这次检查未能完成，请稍后再试；已有发现和收藏已保留。'


class TrackingStore:
    def __init__(self, lib):
        self.lib, self.db = lib, lib.db
        with _LOCKS_GUARD:
            self.lock = _LOCKS.setdefault(str(lib.root).casefold(), threading.RLock())
        with self.lock:
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS tracking_topics(
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, query TEXT NOT NULL,
                project TEXT, automatic INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL, updated REAL NOT NULL,
                last_checked TEXT, last_attempt TEXT, last_error TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS tracking_runs(
                id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL, created REAL NOT NULL,
                query TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                status TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0, truncated INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS tracking_one_active
                ON tracking_runs(topic_id) WHERE status='running';
            CREATE TABLE IF NOT EXISTS tracking_results(
                id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, topic_id INTEGER NOT NULL,
                data TEXT NOT NULL, doi TEXT NOT NULL, title_key TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS tracking_results_topic ON tracking_results(topic_id);
            ''')
            with self.db:
                # App single-instance ownership makes a different launch token an
                # interrupted previous launch, not a competing active process.
                self.db.execute("UPDATE tracking_runs SET status='failed',error=? WHERE status='running' AND owner<>?",
                                ('上次检查尚未完成，已有发现已保留，可重新检查。', _SESSION))

    def save_topic(self, name, query, project=None, topic_id=None, automatic=False):
        name, query = str(name or '').strip(), str(query or '').strip()
        if not name:
            raise ValueError('请为关注主题起个名字。')
        if not query:
            raise ValueError('请先填写检索条件。')
        if len(query) > 3000:
            raise ValueError('检索条件过长，请保留最重要的关键词。')
        if project:
            self.lib.project(project)
        with self.lock, self.db:
            now = time.time()
            if topic_id is None:
                return self.db.execute('INSERT INTO tracking_topics(name,query,project,automatic,created,updated) VALUES(?,?,?,?,?,?)',
                                       (name, query, project, bool(automatic), now, now)).lastrowid
            row = self.db.execute('SELECT * FROM tracking_topics WHERE id=?', (topic_id,)).fetchone()
            if not row:
                raise ValueError('这个关注主题已不存在。')
            if self.db.execute("SELECT 1 FROM tracking_runs WHERE topic_id=? AND status='running'", (topic_id,)).fetchone():
                raise ValueError('这个主题正在检查新文献，请完成后再修改。')
            reset = row['query'] != query
            self.db.execute('UPDATE tracking_topics SET name=?,query=?,project=?,automatic=?,updated=?,last_checked=?,last_attempt=?,last_error=? WHERE id=?',
                            (name, query, project, bool(automatic), now, None if reset else row['last_checked'],
                             None if reset else row['last_attempt'], '' if reset else row['last_error'], topic_id))
            return int(topic_id)

    def topics(self):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM tracking_topics ORDER BY updated DESC,id DESC')]

    def due_topics(self, today=None):
        day = _day(today).isoformat()
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM tracking_topics t WHERE automatic=1 AND (last_attempt IS NULL OR last_attempt<?) AND NOT EXISTS(SELECT 1 FROM tracking_runs r WHERE r.topic_id=t.id AND r.status='running') ORDER BY t.id", (day,))]

    def runs(self, topic_id=None):
        with self.lock:
            query = 'SELECT * FROM tracking_runs'
            args = ()
            if topic_id is not None:
                query += ' WHERE topic_id=?'
                args = (topic_id,)
            return [dict(r) for r in self.db.execute(query + ' ORDER BY id DESC', args)]

    @staticmethod
    def _match(record, records):
        doi, title = _doi(record.get('doi')), _title(record.get('title'))
        for old in records:
            old_doi = _doi(old.get('doi'))
            if (doi and doi == old_doi) or (title and title == _title(old.get('title')) and (not doi or not old_doi)):
                return old
        return None

    def results(self, run_id, include_hidden=False):
        with self.lock:
            run = self.db.execute('SELECT status FROM tracking_runs WHERE id=?', (run_id,)).fetchone()
            if not run or (run[0] != 'complete' and not include_hidden):
                return []
            collected = self.lib.records()
            result = []
            for row in self.db.execute('SELECT * FROM tracking_results WHERE run_id=? ORDER BY id', (run_id,)):
                item = json.loads(row['data'])
                old = self._match(item, collected)
                item.update(id=row['id'], run_id=run_id, already_collected=bool(old), paper_id=old['id'] if old else None)
                result.append(item)
            return result

    def rollback(self, run_id):
        with self.lock, self.db:
            return bool(self.db.execute("UPDATE tracking_runs SET status='rolled_back' WHERE id=? AND status='complete'", (run_id,)).rowcount)

    def restore(self, run_id):
        with self.lock, self.db:
            return bool(self.db.execute("UPDATE tracking_runs SET status='complete' WHERE id=? AND status='rolled_back'", (run_id,)).rowcount)

    def add_result_to_library(self, result_id, project=None):
        with self.lock:
            row = self.db.execute('SELECT r.data,t.project FROM tracking_results r JOIN tracking_topics t ON t.id=r.topic_id WHERE r.id=?', (result_id,)).fetchone()
            if not row:
                raise ValueError('这条发现已不存在，请刷新后重试。')
            project = project or row['project']
            item = json.loads(row['data'])
            old = self._match(item, self.lib.records())
            if old:
                if project:
                    self.lib.assign(old['id'], project)
                return old['id']
            return self.lib.save(item, project, deduplicate=False)


def run_check(store, topic_id, fetcher=None, today=None):
    """Run in a worker; reads/writes share Library.db, network runs outside lock.

    An injected fetcher receives (query, start_date, end_date, limit=50), and
    returns {items: [...], total: int, truncated: bool}. Failed or truncated
    batches never advance the last complete check date. Withdrawal only hides
    a discovery batch and leaves library records, files and dates untouched.
    """
    day = _day(today)
    with store.lock, store.db:
        topic = store.db.execute('SELECT * FROM tracking_topics WHERE id=?', (topic_id,)).fetchone()
        if not topic:
            raise ValueError('这个关注主题已不存在。')
        active = store.db.execute("SELECT id FROM tracking_runs WHERE topic_id=? AND status='running'", (topic_id,)).fetchone()
        if active:
            return {'run_id': active[0], 'count': 0, 'status': 'running', 'truncated': False, 'message': '这个主题正在检查新文献，请稍候。'}
        start = _day(topic['last_checked']) - dt.timedelta(days=7) if topic['last_checked'] else day - dt.timedelta(days=29)
        start = min(start, day)
        query = topic['query']
        run_id = store.db.execute("INSERT INTO tracking_runs(topic_id,created,query,start_date,end_date,status,owner) VALUES(?,?,?,?,?,'running',?)",
                                  (topic_id, time.time(), query, start.isoformat(), day.isoformat(), _SESSION)).lastrowid
        store.db.execute('UPDATE tracking_topics SET last_attempt=? WHERE id=?', (day.isoformat(), topic_id))
    try:
        payload = (fetcher or fetch_europepmc)(query, start, day, limit=MAX_RESULTS)
        if not isinstance(payload, dict) or not isinstance(payload.get('items'), list):
            raise ValueError('unexpected result format')
        total = int(payload.get('total', len(payload['items'])))
        truncated = bool(payload.get('truncated') or total > len(payload['items']) or len(payload['items']) > MAX_RESULTS)
        with store.lock, store.db:
            existing = [json.loads(r[0]) for r in store.db.execute('SELECT data FROM tracking_results WHERE topic_id=?', (topic_id,))]
            count = 0
            for raw in payload['items'][:MAX_RESULTS]:
                item = _metadata(raw)
                if not item['title'] or store._match(item, existing):
                    continue
                store.db.execute('INSERT INTO tracking_results(run_id,topic_id,data,doi,title_key) VALUES(?,?,?,?,?)',
                                 (run_id, topic_id, json.dumps(item, ensure_ascii=False), item['doi'], _title(item['title'])))
                existing.append(item)
                count += 1
            store.db.execute("UPDATE tracking_runs SET status='complete',count=?,total=?,truncated=? WHERE id=?", (count, total, truncated, run_id))
            if truncated:
                store.db.execute("UPDATE tracking_topics SET last_error='' WHERE id=?", (topic_id,))
            else:
                store.db.execute("UPDATE tracking_topics SET last_checked=?,last_error='' WHERE id=?", (day.isoformat(), topic_id))
        message = f'找到 {count} 篇新发现。' if count else '这次没有发现新的文献。'
        if truncated:
            message += f' 本次展示检索结果中的前 {min(MAX_RESULTS, len(payload["items"]))} 篇，仍有更多结果；请缩小关键词范围后再检查。'
        return {'run_id': run_id, 'count': count, 'status': 'complete', 'truncated': truncated, 'total': total, 'message': message}
    except Exception as exc:
        message = _error_message(exc)
        with store.lock, store.db:
            store.db.execute("UPDATE tracking_runs SET status='failed',error=? WHERE id=?", (message, run_id))
            store.db.execute('UPDATE tracking_topics SET last_error=? WHERE id=?', (message, topic_id))
        return {'run_id': run_id, 'count': 0, 'status': 'failed', 'truncated': False, 'message': message}
