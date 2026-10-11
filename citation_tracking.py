"""Find papers along a publication's open reference and citation links.

Europe PMC's references/citations endpoints are documented at
https://europepmc.org/RestfulWebService . Coverage is the open citation network,
not the complete citation indexes of subscription databases.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re
import urllib.parse
import urllib.request

from literature_tracking import _TrustedRedirect, _doi, _error_message, _metadata, _text, _title, TrackingStore

BASE = 'https://www.ebi.ac.uk/europepmc/webservices/rest/'
LABELS = {'reference': '它引用的文献', 'citing': '引用它的文献'}


def _get_json(path, **params):
    url = BASE + path + '?' + urllib.parse.urlencode(dict(format='json', **params))
    request = urllib.request.Request(url, headers={'User-Agent': 'PaperQuick/3.2 (citation discovery)', 'Accept': 'application/json'})
    opener = urllib.request.build_opener(_TrustedRedirect())
    with opener.open(request, timeout=12) as response:
        raw = response.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError('response too large')
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError('unexpected response')
    return payload


def _quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _identity(row):
    source, identifier = str(row.get('source') or ''), str(row.get('id') or '')
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,15}', source) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', identifier):
        return source, identifier
    return None


def _find_seed(record):
    doi, title = _doi(record.get('doi')), _text(record.get('title'))
    query = 'DOI:' + _quote(doi) if doi else 'TITLE:' + _quote(title)
    payload = _get_json('search', query=query, resultType='core', pageSize=20)
    candidates = payload.get('resultList', {}).get('result', [])
    matched = []
    for row in candidates:
        if not isinstance(row, dict) or not _identity(row):
            continue
        if doi:
            if _doi(row.get('doi')) == doi:
                matched.append(row)
        elif title and _title(row.get('title')) == _title(title):
            if record.get('year') and str(row.get('pubYear', '')) != str(record['year']):
                continue
            matched.append(row)
    if not matched:
        return None
    if not doi:
        # Identical titles can be used by different publications. Never follow
        # an arbitrary paper's links merely because its search rank is first.
        known_dois = {_doi(row.get('doi')) for row in matched if row.get('doi')}
        if len(known_dois) > 1:
            return None
        identifiers = {_identity(row) for row in matched}
        if not known_dois and len(identifiers) > 1:
            return None
    return sorted(matched, key=lambda row: row.get('source') != 'MED')[0]


def _direction_rows(seed, relation, limit):
    source, identifier = _identity(seed)
    endpoint = 'references' if relation == 'reference' else 'citations'
    payload = _get_json('/'.join((source, identifier, endpoint)), pageSize=limit, page=1)
    singular = 'reference' if relation == 'reference' else 'citation'
    rows = payload.get(singular + 'List', {}).get(singular, [])
    if not isinstance(rows, list) or 'hitCount' not in payload:
        raise ValueError('unexpected citation list')
    rows = [dict(row, relation=relation) for row in rows if isinstance(row, dict)]
    return rows, int(payload['hitCount']) > len(rows)


def _enrich(rows):
    """Resolve identifier batches because reference lists often omit DOI fields."""
    identities = list(dict.fromkeys(key for row in rows if (key := _identity(row))))
    chunks = [identities[i:i + 50] for i in range(0, len(identities), 50)]
    metadata, incomplete = {}, False
    def fetch(chunk):
        query = ' OR '.join('(EXT_ID:' + _quote(identifier) + ' AND SRC:' + source + ')' for source, identifier in chunk)
        payload = _get_json('search', query=query, resultType='core', pageSize=len(chunk))
        return payload.get('resultList', {}).get('result', [])
    if chunks:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(fetch, chunk) for chunk in chunks]
            for future in futures:
                try:
                    for row in future.result():
                        if isinstance(row, dict) and _identity(row):
                            metadata[_identity(row)] = row
                except Exception:
                    incomplete = True
    enriched = []
    for row in rows:
        merged = dict(row)
        merged.update(metadata.get(_identity(row), {}))
        merged['relation'] = row['relation']
        enriched.append(merged)
    return enriched, incomplete


def find_related(record, records, direction='both', limit=50):
    """Return related papers absent from records without changing the library.

    relation is reference/citing; relations preserves both directions if a
    publication appears in both. Customer-facing failures are returned in
    message, with any successful direction's items retained.
    """
    result = {'items': [], 'message': '', 'truncated': False, 'source': 'Europe PMC'}
    if direction not in ('both', 'reference', 'citing'):
        result['message'] = '请选择想查找的引用方向。'
        return result
    try:
        limit = min(200, max(1, int(limit)))
    except (TypeError, ValueError):
        limit = 50
    if not _doi(record.get('doi')) and not _text(record.get('title')):
        result['message'] = '请先补充这篇文献的标题或 DOI，再查找相关文献。'
        return result
    try:
        seed = _find_seed(record)
    except Exception as exc:
        result['message'] = _error_message(exc)
        return result
    if seed is None:
        result['message'] = '暂时未能在 Europe PMC 中确认这篇文献。请检查标题或 DOI；部分学科的文献尚未收录。'
        return result
    directions = ['reference', 'citing'] if direction == 'both' else [direction]
    groups, errors = {}, []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {kind: executor.submit(_direction_rows, seed, kind, limit) for kind in directions}
        for kind, future in futures.items():
            try:
                groups[kind], truncated = future.result()
                result['truncated'] |= truncated
            except Exception as exc:
                groups[kind] = []
                errors.append(LABELS[kind] + '暂未查完：' + _error_message(exc))
    # Interleave both directions so a popular seed's reference list cannot hide
    # its citing papers merely by filling the shared display limit first.
    rows = []
    for i in range(max((len(group) for group in groups.values()), default=0)):
        rows.extend(groups[kind][i] for kind in directions if i < len(groups[kind]))
    rows, incomplete_metadata = _enrich(rows)
    collected = list(records) + [record, seed]
    found = []
    for raw in rows:
        item = _metadata(raw)
        item['venue'] = item['venue'] or _text(raw.get('journalAbbreviation'))
        if not item['title'] or TrackingStore._match(item, collected):
            continue
        old = TrackingStore._match(item, found)
        if old:
            if raw['relation'] not in old['relations']:
                old['relations'].append(raw['relation'])
            continue
        item.update(relation=raw['relation'], relations=[raw['relation']],
                    seed_title=_text(record.get('title') or seed.get('title')),
                    seed_doi=_doi(record.get('doi') or seed.get('doi')),
                    seed_id=':'.join(_identity(seed)), source='Europe PMC')
        identity = _identity(raw)
        if identity:
            item['europepmc_id'] = ':'.join(identity)
        found.append(item)
    if len(found) > limit:
        result['truncated'] = True
    result['items'] = found[:limit]
    result['message'] = f'沿引用关系找到 {len(result["items"])} 篇尚未收藏的文献。' if result['items'] else '本次没有找到尚未收藏的关联文献。'
    if errors:
        result['message'] += ' ' + ' '.join(errors)
    if incomplete_metadata:
        result['message'] += ' 部分文献暂未补全 DOI，可先按标题查看。'
    if result['truncated']:
        result['message'] += ' 还有更多关联文献，本次显示其中一部分。'
    result['message'] += ' 引用关系来自 Europe PMC 已收录的公开数据。'
    return result
