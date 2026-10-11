"""Local, evidence-based topic terms and editable literature search expressions.

Only title, abstract and author keywords are used. Notes, citation counts, PDFs
and references are deliberately excluded: a term is a reading aid, not a claim
about a paper's findings. No network or additional dependency is required.

Search field references:
https://pubmed.ncbi.nlm.nih.gov/help/#using-search-field-tags
https://webofscience.zendesk.com/hc/en-us/articles/26916347018257
https://europepmc.org/searchsyntax
"""
from __future__ import annotations

from collections import defaultdict
import html
import math
import re
import unicodedata


_STOPWORDS = set('''a an the and or not of to in on at for by from with without
into through between among within across during after before above below over
under is are was were be been being can could would should may might must will
do does did done have has had having it its their them they our we us you your
he she his her this that these those such other each any all both neither
also more most less than then so as if but yet because about against via per
research study studies analysis analyses analyzed analysed result results
method methods methodology objective objectives background conclusion conclusions
discussion introduction abstract aim aims purpose findings finding showed show
shows shown found examined examine examines assessed assess investigate
investigated investigation evaluate evaluated evaluation determine determined
using used use based associated association associations significant significantly
including included include includes among respectively furthermore however
therefore moreover suggest suggests suggested observed observation reported
report reports article articles paper papers review reviews systematic
meta-analysis data dataset datasets evidence effect effects relationship
relationships impact impacts comparison compared compare comparing differences
difference different relevant additional available total respectively several
participants participant sample samples subjects subject group groups controls
control ci confidence interval intervals ratio ratios odds hazard hazards
statistical statistically statistics multivariable multivariate adjusted
adjustment baseline mean median value values higher lower high low increased
decreased increase decrease prospective retrospective cross-sectional cohort
longitudinal randomized randomised trial trials follow-up followup year years
month months day days time times cited citation citations doi pmid pmcid issn
isbn copyright reserved rights publisher published publication publications
http https www com org et al near same null none untitled keywords keyword
title table tables figure figures supplement supplementary version vol pp
age ages aged earlier early later late greater smaller larger first second
third last major minor identify identified identification independent
independently dependent dependence three two one four five six seven eight
nine ten respective particularly mainly commonly overall generally obtained
obtain provided provide provides assessing investigating prospectively
retrospectively approximately nearly although
'''.split())
_OPERATORS = re.compile(r'\b(?:AND|OR|NOT|NEAR|SAME|TO)\b', re.I)
_WORDS = re.compile(r"[a-zA-Z][a-zA-Z0-9]*(?:[-'][a-zA-Z0-9]+)*|[0-9]+(?:\.[0-9]+)?|[^\w\s]+")
_NOISE = re.compile(r'https?://\S+|\b10\.\d{4,9}/\S+|\b(?:doi|pmid|pmcid|issn|isbn)\s*[:=]?\s*\S+|\btimes\s+cited\s*:\s*\d*', re.I)
_QUERY_KEYS = ('pubmed', 'wos', 'scholar', 'europepmc')


def _text(value):
    if isinstance(value, (list, tuple, set)):
        return '; '.join(str(item) for item in value if item is not None)
    return str(value or '')


def _plain(value):
    value = unicodedata.normalize('NFKC', html.unescape(_text(value)))
    value = re.sub(r'<[^>]+>', ' ', value)
    return _NOISE.sub(' ', value)


def _unique_records(records):
    """Merge repeated identities without counting a paper more than once."""
    groups = []
    aliases = {}
    for source in records:
        if not isinstance(source, dict):
            continue
        doi = re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', _text(source.get('doi')).strip(), flags=re.I).lower().rstrip(' .')
        title = re.sub(r'\W+', ' ', _plain(source.get('title')).lower()).strip()
        identities = []
        if doi:
            identities.append(('doi', doi))
        if source.get('id'):
            identities.append(('id', str(source['id'])))
        if len(title) > 4:
            identities.append(('title', title))
        # Different known DOIs can legitimately have the same brief title.
        matches = [aliases[key] for key in identities if key in aliases]
        group = next((item for item in matches if not doi or not item['dois'] or doi in item['dois']), None)
        if group is None:
            group = {'dois': set(), 'title': set(), 'abstract': set(), 'keywords': set()}
            groups.append(group)
        if doi:
            group['dois'].add(doi)
        for field in ('title', 'abstract', 'keywords'):
            value = _text(source.get(field)).strip()
            if value:
                group[field].add(value)
        for key in identities:
            aliases[key] = group
    return [{field: '\n'.join(sorted(group[field])) for field in ('title', 'abstract', 'keywords')} for group in groups]


def _valid_term(term):
    """Keep short topic labels, including explicitly supplied Chinese labels."""
    term = re.sub(r'\s+', ' ', term).strip(' -\'.,:;').lower()
    if not 2 <= len(term) <= 90 or len(term.split()) > 8:
        return ''
    if not re.search(r'[a-z\u3400-\u9fff]', term) or term in _STOPWORDS:
        return ''
    if not re.search(r'\b[a-z][a-z]+|[\u3400-\u9fff]{2}', term):
        return ''
    if re.fullmatch(r'[\W\d_]+', term):
        return ''
    return term


def _explicit_terms(value):
    value = _plain(value)
    for part in re.split(r'[;,；，、|\n\r]+', value):
        part = re.sub(r'^(?:key\s*words?|关键词|主题词)\s*[:：]\s*', '', part.strip(), flags=re.I)
        part = re.sub(r'[^a-zA-Z0-9\u3400-\u9fff\s\-\']', ' ', part)
        term = _valid_term(part)
        if term:
            yield term


def _candidates(value):
    """Collect contiguous English words/phrases, never bridge punctuation."""
    segments = []
    segment = []
    for token in _WORDS.findall(_plain(value)[:24000].lower()):
        if token in _STOPWORDS or not re.match(r'^[a-z][a-z0-9-\']*$', token) or len(token) < 3:
            if segment:
                segments.append(segment)
                segment = []
        else:
            segment.append(token)
    if segment:
        segments.append(segment)
    terms = set()
    for segment in segments:
        for size in (1, 2, 3):
            for start in range(len(segment) - size + 1):
                term = _valid_term(' '.join(segment[start:start + size]))
                if term:
                    terms.add(term)
    return terms


def _extract_unique(records, limit):
    counts = defaultdict(set)
    weights = defaultdict(float)
    origins = defaultdict(set)
    explicit = set()
    for index, record in enumerate(records):
        for field, weight, label in (('keywords', 7.0, '文献关键词'), ('title', 3.0, '标题'), ('abstract', 1.0, '摘要')):
            terms = set(_explicit_terms(record[field])) if field == 'keywords' else _candidates(record[field])
            for term in terms:
                counts[term].add(index)
                weights[term] += weight
                origins[term].add(label)
                if field == 'keywords':
                    explicit.add(term)
    ranked = []
    for term, papers in counts.items():
        length = len(term.split())
        # Author labels lead; recurrence and phrases then distinguish useful
        # subjects from isolated words. Repeated prose in one paper adds nothing.
        score = weights[term] * (1 + math.log1p(len(papers))) * (1 + .22 * min(2, length - 1))
        if term in explicit:
            score += 12
        ranked.append((term, score))
    ranked.sort(key=lambda item: (-item[1], -len(counts[item[0]]), -len(item[0].split()), item[0]))
    selected = []
    for term, score in ranked:
        words = term.split()
        # Do not fill every slot with nested fragments of the same phrase.
        # Keep explicit author keywords even when they overlap.
        if term not in explicit:
            if any((' ' + term + ' ') in (' ' + item['term'] + ' ') and counts[term] == counts[item['term']] for item in selected):
                continue
            if len(words) > 1 and any((' ' + item['term'] + ' ') in (' ' + term + ' ') and len(item['term'].split()) > 1 and counts[term] == counts[item['term']] for item in selected):
                continue
        selected.append({'term': term, 'papers': len(counts[term]), 'score': round(score, 3),
                         'source': '、'.join(label for label in ('文献关键词', '标题', '摘要') if label in origins[term])})
        if len(selected) >= limit:
            break
    return selected


def extract_topics(records, limit=10):
    """Return distinct topic suggestions and the count of supporting papers."""
    limit = max(0, min(50, int(limit)))
    return _extract_unique(_unique_records(records), limit) if limit else []


def _query_terms(terms):
    cleaned = []
    if isinstance(terms, str):
        terms = re.split(r'[;；\n]+', terms)
    for term in terms:
        value = _plain(term)
        # Users edit topic labels, not raw database expressions. Remove field
        # syntax/quotes and Boolean words so an input cannot change grouping.
        value = re.sub(r'\[[^]]*\]', ' ', value)
        value = re.sub(r'\b(?:TITLE_ABS|TITLE|ABSTRACT|TS|TI|AB|DOI|PMID)\s*[:=]', ' ', value, flags=re.I)
        value = _OPERATORS.sub(' ', value)
        value = re.sub(r'[^a-zA-Z0-9\u00c0-\u024f\u0370-\u03ff\u3400-\u9fff\s\-]', ' ', value)
        value = re.sub(r'\s+', ' ', value).strip(' -')
        # Keep complete words within bounds rather than creating a truncated term.
        words = value.split()[:8]
        while words and len(' '.join(words)) > 90:
            words.pop()
        value = ' '.join(words)
        if not value or not re.search(r'[a-zA-Z\u00c0-\u024f\u0370-\u03ff\u3400-\u9fff]', value):
            continue
        if value.casefold() not in {item.casefold() for item in cleaned}:
            cleaned.append(value)
        if len(cleaned) == 12:
            break
    return cleaned


def build_search_queries(terms):
    """Build broad OR queries for all supplied valid labels (up to twelve).

    These are editable search starting points, not validated systematic-review
    strategies; no synonyms, MeSH headings or unsupported findings are invented.
    """
    terms = _query_terms(terms)
    if not terms:
        return dict.fromkeys(_QUERY_KEYS, '')
    quoted = [f'"{term}"' for term in terms]
    return {
        'pubmed': '(' + ' OR '.join(f'{term}[Title/Abstract]' for term in quoted) + ')',
        'wos': 'TS=(' + ' OR '.join(quoted) + ')',
        'scholar': ' OR '.join(quoted),
        'europepmc': '(' + ' OR '.join(f'TITLE_ABS:{term}' for term in quoted) + ')',
    }


def topic_overview(records, limit=10):
    """Summarise topics present in the selected papers, with three starter terms."""
    records = _unique_records(records)
    limit = max(0, min(50, int(limit)))
    keywords = _extract_unique(records, limit) if limit else []
    count = len(records)
    if keywords:
        labels = '、'.join('“' + item['term'] + '”' for item in keywords[:3])
        description = f'这 {count} 篇文献中，{labels}是值得留意的主题词。可从这些词开始，继续寻找相关研究。'
    elif count:
        description = '这些文献的主题信息还不充分。补充标题、摘要或关键词后，可以更方便地找到相关研究。'
    else:
        description = '选一些感兴趣的文献，就可以在这里梳理主题、继续寻找相关研究。'
    return {'keywords': keywords, 'queries': build_search_queries([item['term'] for item in keywords[:3]]),
            'paper_count': count, 'description': description}
