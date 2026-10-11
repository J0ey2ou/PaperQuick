"""Conservative local-library to CSL mapping and explicit DOI metadata lookup.

Nothing in this module writes to a library or sends metadata automatically.
Crossref endpoint: https://api.crossref.org/works/{doi}
CSL data model: https://github.com/citation-style-language/schema
"""
from __future__ import annotations

from datetime import date
import hashlib
from html.parser import HTMLParser
import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen


_MAX_RESPONSE = 4 * 1024 * 1024
_TYPE_MAP = {
    'journal-article': 'article-journal', 'article': 'article-journal',
    'journal article': 'article-journal', 'journal': 'article-journal',
    'proceedings-article': 'paper-conference', 'conference-paper': 'paper-conference',
    'book-chapter': 'chapter', 'book-part': 'chapter', 'book-section': 'chapter',
    'book': 'book', 'monograph': 'book', 'edited-book': 'book',
    'reference-book': 'book', 'proceedings': 'book',
    'dissertation': 'thesis', 'doctoral thesis': 'thesis',
    'report': 'report', 'report-series': 'report', 'dataset': 'dataset',
    'posted-content': 'article', 'preprint': 'article',
    'web-page': 'webpage', 'website': 'webpage', 'standard': 'standard',
}
_CSL_TYPES = {
    'article', 'article-journal', 'article-magazine', 'article-newspaper',
    'bill', 'book', 'broadcast', 'chapter', 'classic', 'collection', 'dataset',
    'document', 'entry', 'entry-dictionary', 'entry-encyclopedia', 'event',
    'figure', 'graphic', 'hearing', 'interview', 'legal_case', 'legislation',
    'manuscript', 'map', 'motion_picture', 'musical_score', 'pamphlet',
    'paper-conference', 'patent', 'performance', 'periodical',
    'personal_communication', 'post', 'post-weblog', 'regulation', 'report',
    'review', 'review-book', 'software', 'song', 'speech', 'standard',
    'thesis', 'treaty', 'webpage',
}
_NAME_FIELDS = ('family', 'given', 'literal', 'suffix', 'dropping-particle',
                'non-dropping-particle')


class MetadataError(ValueError):
    """A DOI lookup cannot safely provide metadata for the requested paper."""


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag.split(':')[-1] in ('p', 'sec', 'title', 'br', 'div'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag.split(':')[-1] in ('p', 'sec', 'title', 'div'):
            self.parts.append(' ')


def _text(value):
    if value is None:
        return ''
    if isinstance(value, (list, tuple)):
        return _text(value[0]) if value else ''
    if not isinstance(value, (str, int, float)):
        return ''
    parser = _PlainText()
    parser.feed(str(value))
    parser.close()
    return re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()


def _doi(value):
    value = str(value or '').strip()
    if re.match(r'^https?://(?:dx\.)?doi\.org/', value, re.I):
        value = unquote(urlsplit(value).path.lstrip('/'))
    else:
        value = re.sub(r'^doi\s*:\s*', '', value, flags=re.I)
    if len(value) > 2048 or not re.fullmatch(r'10\.\d{4,9}/[^\s<>"\\]+', value):
        return ''
    return value.lower()


def _name(item):
    if not isinstance(item, dict):
        return {'literal': _text(item)} if _text(item) else None
    result = {key: _text(item[key]) for key in _NAME_FIELDS if _text(item.get(key))}
    if not result and _text(item.get('name')):
        result = {'literal': _text(item['name'])}
    if result.get('literal'):
        return {'literal': result['literal']}
    return result if result.get('family') or result.get('given') else None


def _authors(record):
    structured = record.get('authors_structured') or record.get('author')
    if isinstance(structured, (tuple, list)):
        names = [name for item in structured if (name := _name(item))]
        if names:
            return names, False
    raw = str(record.get('authors') or '').strip()
    if not raw:
        return [], False
    # A comma could separate people (search results) or surname/given name
    # (EndNote). Only explicit person separators make that distinction safe.
    explicit = bool(re.search(r'[;；\r\n]', raw))
    entries = [s.strip() for s in re.split(r'[;；\r\n]+', raw) if s.strip()]
    names = []
    ambiguous = not explicit
    for entry in entries:
        if explicit and entry.count(',') == 1:
            family, given = [part.strip() for part in entry.split(',', 1)]
            if family and given:
                names.append({'family': _text(family), 'given': _text(given)})
                continue
        names.append({'literal': _text(entry)})
        ambiguous = True
    return names, ambiguous


def _issued(record):
    value = record.get('issued')
    if isinstance(value, dict) and isinstance(value.get('date-parts'), list):
        rows = value['date-parts']
        if rows and isinstance(rows[0], (list, tuple)) and rows[0]:
            parts = rows[0][:3]
            try:
                if any(isinstance(v, bool) or not re.fullmatch(r'\d+', str(v)) for v in parts):
                    raise ValueError
                parts = [int(v) for v in parts]
                date(parts[0], parts[1] if len(parts) > 1 else 1,
                     parts[2] if len(parts) > 2 else 1)
                return {'date-parts': [parts]}
            except (ValueError, TypeError, OverflowError):
                pass
    year = str(record.get('year') or '').strip()
    if re.fullmatch(r'\d{4}', year) and 0 < int(year) <= 9999:
        return {'date-parts': [[int(year)]]}
    return None


def _kind(record):
    value = _text(record.get('type') or record.get('reference_type')).lower()
    return _TYPE_MAP.get(value, value if value in _CSL_TYPES else 'article-journal')


def to_csl(record):
    """Return a new CSL-JSON item; unresolved personal names remain literal."""
    doi = _doi(record.get('doi') or record.get('DOI'))
    rid = record.get('id')
    if rid is None or str(rid) == '':
        identity = json.dumps({k: record.get(k) for k in ('title', 'authors', 'year')},
                              ensure_ascii=False, sort_keys=True, default=str)
        rid = 'doi:' + doi if doi else 'local:' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
    result = {'id': str(rid), 'type': _kind(record)}
    fields = {
        'title': ('title',), 'container-title': ('venue', 'container-title', 'journal'),
        'volume': ('volume',), 'issue': ('issue',), 'page': ('pages', 'page', 'article_number', 'article-number'),
        'publisher': ('publisher',), 'publisher-place': ('publisher_place', 'publisher-place'),
        'edition': ('edition',), 'ISBN': ('isbn', 'ISBN'), 'ISSN': ('issn', 'ISSN'),
        'URL': ('url', 'URL'), 'abstract': ('abstract',), 'language': ('language',),
        'collection-title': ('series', 'collection-title'),
        'number': ('number',),
    }
    for target, candidates in fields.items():
        value = next((_text(record[k]) for k in candidates if _text(record.get(k))), '')
        if value:
            result[target] = value
    if doi:
        result['DOI'] = doi
        result.setdefault('URL', 'https://doi.org/' + quote(doi, safe='/'))
    authors, _ = _authors(record)
    if authors:
        result['author'] = authors
    issued = _issued(record)
    if issued:
        result['issued'] = issued
    editors = record.get('editors_structured') or record.get('editor')
    if isinstance(editors, list):
        result['editor'] = [n for value in editors if (n := _name(value))]
    return result


def quality_warnings(record):
    """Return reader-facing completeness hints; these do not block citation."""
    item = to_csl(record)
    warnings = []
    if not item.get('title'):
        warnings.append('缺少文献标题，建议补全后再引用。')
    authors, ambiguous = _authors(record)
    if not authors:
        warnings.append('缺少作者信息，引用中可能无法显示作者。')
    elif ambiguous:
        warnings.append('作者姓名尚未区分姓与名，目前按原文保留；可通过 DOI 补全后核对。')
    if re.search(r'\bet\s+al\b|(?:等|…|\.\.\.)\s*$', str(record.get('authors') or ''), re.I):
        warnings.append('作者列表可能不完整，请核对全部作者。')
    if not item.get('issued'):
        warnings.append('缺少出版年份，部分格式会显示为无日期。')
    if item['type'] in ('article-journal', 'article-magazine', 'article-newspaper', 'paper-conference', 'chapter'):
        if not item.get('container-title'):
            warnings.append('缺少期刊或来源名称。')
        if not item.get('page') and not item.get('number'):
            warnings.append('尚未填写页码或文章编号；部分网络首发文献可能没有此信息。')
    if item['type'] == 'article-journal' and not item.get('volume'):
        warnings.append('尚未填写卷号；网络首发文献可能暂未分配。')
    if item['type'] in ('book', 'chapter') and not item.get('publisher'):
        warnings.append('缺少出版社名称。')
    if (record.get('doi') or record.get('DOI')) and not item.get('DOI'):
        warnings.append('DOI 格式需要核对，暂未加入引用。')
    return warnings


def _from_crossref(item, expected_doi):
    if not isinstance(item, dict) or _doi(item.get('DOI')) != expected_doi:
        raise MetadataError('返回的文献信息与这个 DOI 不一致，请稍后重试或手动补全。')
    title = _text(item.get('title'))
    if not title:
        raise MetadataError('这条 DOI 记录没有文献标题，请手动核对。')
    authors = [n for value in item.get('author', []) if (n := _name(value))] if isinstance(item.get('author'), list) else []
    result = {'doi': expected_doi, 'DOI': expected_doi, 'title': title}
    kind = item.get('type')
    if kind in _TYPE_MAP or kind in _CSL_TYPES:
        result['type'] = _TYPE_MAP.get(kind, kind)
    # Omit absent fields so a Library.save(..., rid=...) merge does not erase
    # the user's existing metadata. In particular, never return notes or id.
    for dest, source in (('venue', 'container-title'), ('volume', 'volume'),
                         ('issue', 'issue'), ('pages', 'page'),
                         ('article_number', 'article-number'), ('publisher', 'publisher'),
                         ('abstract', 'abstract'), ('url', 'URL'),
                         ('isbn', 'ISBN'), ('issn', 'ISSN'), ('language', 'language')):
        if value := _text(item.get(source)):
            result[dest] = value
    if authors:
        result['authors_structured'] = authors
        result['authors'] = '; '.join(n.get('literal') or ', '.join(filter(None, [n.get('family'), n.get('given')])) for n in authors)
    for key in ('issued', 'published-print', 'published-online', 'published'):
        issued = _issued({'issued': item.get(key)})
        if issued:
            result['issued'] = issued
            result['year'] = str(issued['date-parts'][0][0])
            break
    return result


def fetch_doi_metadata(doi, timeout=12):
    """Read the exact Crossref DOI record, returning only available fields.

    Call only after a user requests metadata completion. The caller chooses
    whether to save the returned data. No title search or other-paper fallback.
    """
    normalized = _doi(doi)
    if not normalized:
        raise MetadataError('请填写完整的 DOI，例如 10.1038/s41586-021-03819-2。')
    request = Request('https://api.crossref.org/works/' + quote(normalized, safe=''), headers={
        'Accept': 'application/json',
        'User-Agent': 'PaperQuick-Citations/1.0 (https://github.com/J0ey2ou/PaperQuick)',
    })
    try:
        with urlopen(request, timeout=max(1, min(float(timeout), 30))) as response:
            raw = response.read(_MAX_RESPONSE + 1)
        if len(raw) > _MAX_RESPONSE:
            raise MetadataError('这条文献记录过大，请手动补全或稍后重试。')
        payload = json.loads(raw.decode('utf-8'))
        if not isinstance(payload, dict) or payload.get('status') != 'ok':
            raise MetadataError('暂时无法读取这条文献的信息，请稍后重试。')
        return _from_crossref(payload.get('message'), normalized)
    except HTTPError as exc:
        if exc.code == 404:
            raise MetadataError('Crossref 尚未收录这个 DOI，请核对 DOI 或手动补全文献信息。') from exc
        if exc.code == 429:
            raise MetadataError('文献信息服务正忙，请稍后再试。') from exc
        raise MetadataError('暂时无法连接文献信息服务，请稍后重试。') from exc
    except (URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
        raise MetadataError('文献信息查询未完成，请检查网络后重试。') from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetadataError('文献信息暂时无法读取，请稍后重试。') from exc
