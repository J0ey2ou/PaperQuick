"""Resolve and archive full text without selecting an approximate title match."""
from dataclasses import asdict
import re
import unicodedata
from urllib.parse import quote, urljoin
import urllib.request

from library_core import download_pdf, normalize_doi
from paper_finder import find_papers, safe_link, public_url, PublicRedirect, ArticleParser


def download_page(record, links):
    """Follow the article landing page and its own citation PDF, never guess a URL."""
    direct = next((x['url'] for x in links if x.get('kind') == 'pdf'), '')
    if direct:return direct
    landing = next((x['url'] for kind in ('fulltext','publisher') for x in links if x.get('kind') == kind), '')
    doi = normalize_doi(record.get('doi',''))
    if not landing and doi:landing = 'https://doi.org/' + quote(doi,safe='/')
    if not landing:return ''
    try:
        public_url(landing)
        request=urllib.request.Request(landing,headers={'User-Agent':'PaperQuick/3.0','Accept':'text/html,application/pdf'})
        with urllib.request.build_opener(PublicRedirect()).open(request,timeout=4) as response:
            final=response.geturl()
            if response.headers.get_content_type()=='application/pdf':return final
            data=response.read(1024*1024).decode(response.headers.get_content_charset() or 'utf-8',errors='replace')
        page=ArticleParser();page.feed(data)
        page_doi=normalize_doi(page.first('citation_doi'))
        title=page.first('citation_title')
        matched=(doi and page_doi==doi) or (not page_doi and title_key(title)==title_key(record.get('title','')) and bool(title))
        pdf=urljoin(final,page.first('citation_pdf_url')) if page.first('citation_pdf_url') else ''
        if matched and safe_link(pdf):return pdf
        return final if safe_link(final) else landing
    except Exception:return landing


def title_key(title):
    return ''.join(c for c in unicodedata.normalize('NFKC', title).casefold() if c.isalnum())


def matched_paper(record, papers):
    doi = normalize_doi(record.get('doi', ''))
    if doi:
        matches = [p for p in papers if normalize_doi(p.doi) == doi]
    else:
        key = title_key(record.get('title', ''))
        matches = [p for p in papers if key and title_key(p.title) == key]
    # Different DOI candidates with the same title require the user's review.
    identities = {normalize_doi(p.doi) or title_key(p.title) for p in matches}
    return matches[0] if matches and len(identities) == 1 else None


def resolve_download(library, rid, preferred_url=None, lookup=False, email='', open_page=False):
    record = library.get(rid)
    if record['attachments'] and not open_page:
        return {'kind': 'existing', 'path': str(library.root / record['attachments'][0]['path'])}
    links = [x for x in record.get('links', []) if safe_link(x.get('url'))]
    pdfs = [x for x in links if x.get('kind') == 'pdf']
    if open_page and (links or record.get('doi')):
        return {'kind':'browser','url':download_page(record,links),'issue':''}
    issue = ''
    if not pdfs and lookup:
        try:
            result = find_papers(record.get('doi') or record['title'], email=email)
            paper = matched_paper(record, result.papers)
            if paper:
                fresh = asdict(paper)
                # Keep user annotations and curated metadata; replace identifier placeholders.
                patch = {key: fresh[key] for key in ('title', 'doi', 'authors', 'year', 'venue')
                         if fresh[key] and (not record.get(key) or
                         (key == 'title' and normalize_doi(record['title']) == record.get('doi') and
                          bool(re.match(r'^(?:https?://doi.org/)?10\.\d+/', record['title']))))}
                patch['links'] = fresh['links']
                library.save(patch, rid=rid)
                links = [x for x in fresh['links'] if safe_link(x.get('url'))]
                pdfs = [x for x in links if x.get('kind') == 'pdf']
            else:
                issue = '检索候选未能唯一匹配，请在查询页核对。'
        except Exception as exc:
            issue = '查找开放版本未完成：' + str(exc)
    if preferred_url:
        pdfs.sort(key=lambda x: x['url'] != preferred_url)
    if open_page:
        url=download_page(dict(record,doi=(paper.doi if 'paper' in locals() and paper else record.get('doi',''))),links)
        return {'kind':'browser' if url else 'missing','url':url,'issue':issue}
    if pdfs:
        try:
            path = download_pdf(library, rid, pdfs[0]['url'])
            return {'kind': 'downloaded', 'path': str(path)}
        except Exception as exc:
            issue = '自动下载未完成：' + str(exc)
    fallback = next((x['url'] for kind in ('fulltext', 'publisher') for x in links
                     if x.get('kind') == kind), '')
    doi = normalize_doi(record.get('doi', ''))
    if not fallback and doi:
        fallback = 'https://doi.org/' + quote(doi, safe='/')
    if not fallback and pdfs:
        fallback = pdfs[0]['url']
    return {'kind': 'browser' if fallback else 'missing', 'url': fallback, 'issue': issue}
