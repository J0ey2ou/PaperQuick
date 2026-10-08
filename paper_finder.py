"""文献直达：只使用 Python 标准库的文献解析与原文入口查找。"""
from __future__ import annotations

import concurrent.futures
import copy
import difflib
import html
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from typing import Callable

USER_AGENT = "PaperQuick/1.0 (local desktop literature lookup)"
TIMEOUT = 12
SEARCH_BUDGET = 5.0
ENRICH_BUDGET = 6.0
BACKGROUND_BUDGET = 14.0
# Reuse a bounded pool; slow requests cannot make later searches spawn unlimited threads.
_network_pool = concurrent.futures.ThreadPoolExecutor(max_workers=16)
MAX_BYTES = 3 * 1024 * 1024
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s<>\"\u3000\u3001\u3002\uff0c\uff1b\uff09]+", re.I)
ARXIV_RE = re.compile(r"(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)", re.I)


class LookupError(Exception):
    pass


class BrowserPageRequired(LookupError):
    """网页需在用户浏览器中打开，再通过扩展读取当前页面。"""
    def __init__(self, url, reason="推送页面要求验证，暂时无法直接读取正文。"):
        self.url = url
        super().__init__(reason + " 请在浏览器打开推送，完成验证后选中英文论文标题 / DOI，通过浏览器右键或全局快捷键查询；安装浏览器扩展后也可右键“查找当前页面中的论文”。")


@dataclass
class Link:
    label: str
    url: str
    kind: str  # pdf, fulltext, publisher
    source: str
    note: str = ""


@dataclass
class Paper:
    title: str
    doi: str = ""
    authors: str = ""
    year: str = ""
    venue: str = ""
    origin: str = ""
    match: str = "标识符匹配"
    score: float = 1.0
    links: list[Link] = field(default_factory=list)

    def add_link(self, label, url, kind, source, note=""):
        if safe_link(url) and not any(x.url == url for x in self.links):
            self.links.append(Link(label, url, kind, source, note))


@dataclass
class Result:
    query: str
    papers: list[Paper]
    notes: list[str] = field(default_factory=list)
    extracted_title: str = ""
    complete: bool = True
    matches_ready: bool = True

    def to_dict(self):
        return asdict(self)


def safe_link(url):
    if not isinstance(url, str):
        return False
    try:
        p = urllib.parse.urlsplit(url)
        return p.scheme in ("https", "http") and bool(p.hostname) and not p.username and not p.password
    except ValueError:
        return False


def public_url(url):
    """粘贴的网页及其重定向只允许公开 HTTP(S) 地址。"""
    if not safe_link(url):
        raise LookupError("请输入 http 或 https 网页链接。")
    p = urllib.parse.urlsplit(url)
    try:
        if p.port not in (None, 80, 443):
            raise LookupError("只支持常规的网页端口。")
        addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
        if not addresses or any(not ipaddress.ip_address(x[4][0].split("%")[0]).is_global for x in addresses):
            raise LookupError("请使用公开网页链接，暂不读取本机或内网地址。")
    except (socket.gaierror, ValueError) as exc:
        raise LookupError("网页地址无法解析，请检查链接。") from exc


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, *, webpage=False):
    if webpage:
        public_url(url)
    agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36" if webpage else USER_AGENT
    request = urllib.request.Request(url, headers={"User-Agent": agent, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8" if webpage else "application/json, application/atom+xml;q=0.9, */*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    opener = urllib.request.build_opener(PublicRedirect()) if webpage else urllib.request.build_opener()
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            # 不拉取任意大文件；压缩响应未被请求，也不自动解压。
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise LookupError("网页内容过大，请直接粘贴论文标题或 DOI。")
            charset = response.headers.get_content_charset()
            if not charset:
                encoding = re.search(br"charset\s*=\s*['\"]?([a-zA-Z0-9_-]+)", data[:8192])
                charset = encoding.group(1).decode("ascii") if encoding else "utf-8"
            try:
                text = data.decode(charset, errors="replace")
            except LookupError:
                raise
            except Exception:
                text = data.decode("utf-8", errors="replace")
            return text, response.geturl(), response.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise LookupError("服务未收录该标识符（404）。") from exc
        if exc.code == 429:
            raise LookupError("服务暂时限流（429），请稍后重试。") from exc
        raise LookupError(f"服务暂时不可用（HTTP {exc.code}）。") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LookupError("连接失败或超时，请检查网络后重试。") from exc


def get_json(url):
    try:
        return json.loads(fetch(url)[0])
    except (ValueError, TypeError) as exc:
        raise LookupError("服务返回的内容无法解析，请稍后重试。") from exc


def api_url(base, **params):
    return base + "?" + urllib.parse.urlencode(params)


def extract_dois(text):
    found = []
    text = html.unescape(text)
    # DOI 网页链接中的追踪参数不属于 DOI；正文中的标识符不做此转换。
    text = re.sub(r"https?://[^\s<>\"]+", lambda m: urllib.parse.unquote(urllib.parse.urlsplit(m.group()).path) if re.search(r"10\.\d{4,9}/", urllib.parse.unquote(m.group())) else m.group(), text)
    for raw in DOI_RE.findall(urllib.parse.unquote(text)):
        value = raw.rstrip(".,;:!?]}，。；：！？”’")
        while value.endswith(")") and value.count(")") > value.count("("):
            value = value[:-1]
        if value.lower() not in [x.lower() for x in found]:
            found.append(value)
    return found


def clean_title(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKC", clean_title(value)).casefold() if c.isalnum())


def similarity(a, b):
    a, b = normalized(a), normalized(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.text = []
        self.links = []
        self.title_parts = []
        self.skip = 0
        self.in_title = False
        self.containers = []
        self.article_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"):
            active = attrs.get("id") == "js_content" or tag == "article" or (self.containers and self.containers[-1][1])
            self.containers.append((tag, bool(active)))
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = (attrs.get("name") or attrs.get("property") or "").lower()
            if key and attrs.get("content"):
                self.meta.setdefault(key, []).append(attrs["content"])
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        for i in range(len(self.containers) - 1, -1, -1):
            if self.containers[i][0] == tag:
                del self.containers[i:]
                break
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag == "title":
            self.in_title = False
        if tag in ("p", "div", "br", "h1", "h2", "li"):
            self.text.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)
            if self.containers and self.containers[-1][1]:
                self.article_text.append(data)
            if self.in_title:
                self.title_parts.append(data)

    def values(self, key):
        return self.meta.get(key, [])

    def first(self, key):
        return next(iter(self.values(key)), "")

    @property
    def title(self):
        return clean_title(self.first("citation_title") or self.first("og:title") or self.first("twitter:title") or " ".join(self.title_parts))


def crossref_paper(item):
    title = clean_title(next(iter(item.get("title", [])), ""))
    doi = item.get("DOI", "")
    authors = ", ".join(" ".join(filter(None, [x.get("given"), x.get("family")])) for x in item.get("author", [])[:3])
    if len(item.get("author", [])) > 3:
        authors += " 等"
    year = ""
    for key in ("published", "published-print", "published-online", "issued"):
        parts = item.get(key, {}).get("date-parts", [[]])
        if parts and parts[0]:
            year = str(parts[0][0])
            break
    paper = Paper(title or doi, doi, authors, year, next(iter(item.get("container-title", [])), ""), "Crossref")
    paper.add_link("出版社 / DOI", "https://doi.org/" + urllib.parse.quote(doi, safe="/():;"), "publisher", "Crossref", "可能需要机构订阅或购买")
    for link in item.get("link", []):
        if link.get("content-type") == "application/pdf":
            paper.add_link("出版社 PDF", link.get("URL", ""), "publisher", "Crossref", "出版社登记的 PDF 地址，可能需要订阅")
    return paper


def pmc_paper(item):
    paper = Paper(clean_title(item.get("title", "")), item.get("doi", ""), item.get("authorString", ""), item.get("pubYear", ""), item.get("journalTitle") or item.get("journalInfo", {}).get("journal", {}).get("title", ""), "Europe PMC")
    add_pmc_links(paper, item)
    if paper.doi:
        paper.add_link("出版社 / DOI", "https://doi.org/" + urllib.parse.quote(paper.doi, safe="/():;"), "publisher", "Europe PMC", "可能需要机构订阅或购买")
    return paper


def add_pmc_links(paper, item):
    for entry in item.get("fullTextUrlList", {}).get("fullTextUrl", []):
        if entry.get("availabilityCode") == "OA" or entry.get("availability") == "Open access":
            is_pdf = str(entry.get("documentStyle", "")).lower() == "pdf"
            paper.add_link("开放 PDF" if is_pdf else "开放原文", entry.get("url", ""), "pdf" if is_pdf else "fulltext", "Europe PMC", "服务标注的开放获取版本")
    if item.get("pmcid") and item.get("isOpenAccess") == "Y":
        paper.add_link("PMC 原文 / 下载", "https://pmc.ncbi.nlm.nih.gov/articles/" + item["pmcid"] + "/", "fulltext", "Europe PMC", "打开后可使用页面内的 PDF 下载入口")


def search_crossref(query):
    data = get_json(api_url("https://api.crossref.org/works", **{"query.title": query, "rows": 10,
                    "select": "DOI,title,author,published,container-title,link"}))
    return [crossref_paper(x) for x in data.get("message", {}).get("items", [])]


def search_pmc(query):
    data = get_json(api_url("https://www.ebi.ac.uk/europepmc/webservices/rest/search", query=query, format="json", resultType="core", pageSize=5))
    return data.get("resultList", {}).get("result", [])


_arxiv_lock = threading.Lock()
_arxiv_last = 0.0


def search_arxiv(query="", ident=""):
    global _arxiv_last
    # arXiv 建议同一客户端间隔至少三秒。
    with _arxiv_lock:
        delay = 3 - (time.monotonic() - _arxiv_last)
        if delay > 0:
            time.sleep(delay)
        _arxiv_last = time.monotonic()
        params = {"id_list": ident} if ident else {"search_query": 'ti:"' + query.replace('"', " ") + '"', "max_results": 3}
        text = fetch(api_url("https://export.arxiv.org/api/query", **params))[0]
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise LookupError("arXiv 返回内容无法解析。") from exc
    ns = {"a": "http://www.w3.org/2005/Atom", "ar": "http://arxiv.org/schemas/atom"}
    papers = []
    for entry in root.findall("a:entry", ns):
        title = clean_title(entry.findtext("a:title", "", ns))
        url = entry.findtext("a:id", "", ns).replace("http://", "https://", 1)
        if "arxiv.org/abs/" not in url:
            continue
        paper = Paper(title, entry.findtext("ar:doi", "", ns), ", ".join(x.findtext("a:name", "", ns) for x in entry.findall("a:author", ns)[:3]), entry.findtext("a:published", "", ns)[:4], "arXiv", "arXiv")
        paper.add_link("arXiv PDF", url.replace("/abs/", "/pdf/"), "pdf", "arXiv", "预印本版本，可能与正式发表版本不同")
        paper.add_link("arXiv 原文页", url, "fulltext", "arXiv", "预印本")
        papers.append(paper)
    return papers


def completed_jobs(jobs, budget, notes, has_result=None):
    """Collect until the stage deadline. Late workers only own their return values."""
    futures = {_network_pool.submit(job): name for name, job in jobs.items()}
    pending = set(futures)
    started = time.monotonic()
    deadline = started + budget
    try:
        while pending:
            done, pending = concurrent.futures.wait(pending, timeout=max(0, deadline - time.monotonic()),
                                                     return_when=concurrent.futures.FIRST_COMPLETED)
            if not done:
                if has_result is not None and not has_result() and deadline < started + BACKGROUND_BUDGET:
                    deadline = started + BACKGROUND_BUDGET
                    continue
                break
            for future in done:
                name = futures[future]
                label = name[1] if isinstance(name, tuple) else name
                label = "Crossref" if label == "metadata" else label
                try:
                    value = future.result()
                except Exception as exc:
                    notes.append(f"{label}：{friendly_error(exc)}")
                else:
                    yield name, value
    finally:
        for future in pending:
            future.cancel()
            name = futures[future]
            label = name[1] if isinstance(name, tuple) else name
            label = "Crossref" if label == "metadata" else label
            notes.append(f"{label}：响应较慢，本次已跳过；可再次查询补充。")


def oa_jobs(paper, email="", semantic=False):
    doi = paper.doi
    if not doi:
        return {}
    jobs = {"Europe PMC": lambda: search_pmc('DOI:"' + doi + '"')}
    if semantic:
        jobs["Semantic Scholar"] = lambda: get_json("https://api.semanticscholar.org/graph/v1/paper/DOI:" + urllib.parse.quote(doi, safe="") + "?fields=title,openAccessPdf,externalIds")
    if email:
        jobs["Unpaywall"] = lambda: get_json(api_url("https://api.unpaywall.org/v2/" + urllib.parse.quote(doi, safe=""), email=email))
    return jobs


def apply_oa(paper, name, data, notes):
    try:
        _apply_oa(paper, name, data)
    except Exception as exc:
        notes.append(f"{name}：{friendly_error(exc)}")


def _apply_oa(paper, name, data):
    if name == "Europe PMC":
        for item in data:
            if item.get("doi", "").lower() == paper.doi.lower():
                add_pmc_links(paper, item)
                if paper.title == paper.doi and item.get("title"):
                    paper.title = clean_title(item["title"])
                    paper.authors = item.get("authorString", "")
                    paper.year = item.get("pubYear", "")
    elif name == "Semantic Scholar":
        oa = data.get("openAccessPdf") or {}
        if oa.get("url"):
            paper.add_link("开放 PDF", oa["url"], "pdf", name, "索引提供的开放版本；预印本或作者稿可能与正式版不同")
        arxiv_id = (data.get("externalIds") or {}).get("ArXiv")
        if arxiv_id and re.fullmatch(r"\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}", arxiv_id, re.I):
            paper.add_link("arXiv PDF", "https://arxiv.org/pdf/" + arxiv_id, "pdf", name, "预印本版本")
        if paper.title == paper.doi and data.get("title"):
            paper.title = clean_title(data["title"])
    else:
        locations = data.get("oa_locations") or []
        if data.get("best_oa_location"):
            locations = [data["best_oa_location"]] + locations
        for loc in locations[:5]:
            version = loc.get("version") or "开放版本"
            paper.add_link("开放 PDF", loc.get("url_for_pdf"), "pdf", name, version)
            paper.add_link("开放原文", loc.get("url_for_landing_page"), "fulltext", name, version)


def enrich(paper, email="", semantic=False):
    notes = []
    for name, data in completed_jobs(oa_jobs(paper, email, semantic), ENRICH_BUDGET, notes):
        apply_oa(paper, name, data, notes)
    return notes


def identifier_paper(doi="", ident=""):
    if ident:
        paper = Paper("arXiv:" + ident, doi, origin="arXiv", match="arXiv 编号入口 · 请核对")
        paper.add_link("arXiv PDF", "https://arxiv.org/pdf/" + ident, "pdf", "arXiv", "预印本版本；入口由编号生成")
        paper.add_link("arXiv 原文页", "https://arxiv.org/abs/" + ident, "fulltext", "arXiv", "预印本")
    else:
        paper = Paper(doi, doi, origin="DOI", match="DOI 入口 · 元数据待核对")
        paper.add_link("出版社 / DOI", "https://doi.org/" + urllib.parse.quote(doi, safe="/():;"), "publisher", "DOI", "由 DOI 生成的入口；请核对论文信息")
    return paper


def has_open(paper):
    return any(link.kind in ("pdf", "fulltext") for link in paper.links)


def update_metadata(paper, fresh):
    # The collector alone mutates papers; late network responses cannot change a delivered result.
    if fresh.title and fresh.title != fresh.doi:
        for field_name in ("title", "authors", "year", "venue", "origin", "match"):
            setattr(paper, field_name, getattr(fresh, field_name))
    for link in fresh.links:
        paper.add_link(link.label, link.url, link.kind, link.source, link.note)



def friendly_error(exc):
    return str(exc) if isinstance(exc, LookupError) else "返回内容暂时不可用，请稍后重试。"


def lookup_doi(doi):
    arxiv_doi = re.fullmatch(r"10\.48550/arxiv\.(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)", doi, re.I)
    if arxiv_doi:
        try:
            papers = search_arxiv(ident=arxiv_doi.group(1))
            if papers:
                papers[0].doi = doi
                return papers[0], ""
        except Exception:
            pass
    try:
        return crossref_paper(get_json("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe=""))["message"]), ""
    except Exception as exc:
        # 注册于其他机构的 DOI 仍保留有效的解析入口，并继续查开放版本。
        paper = Paper(doi, doi, origin="DOI")
        paper.match = "DOI 元数据未核验 · 请核对"
        paper.add_link("出版社 / DOI", "https://doi.org/" + urllib.parse.quote(doi, safe="/():;"), "publisher", "DOI", "元数据未确认；请打开 DOI 页面核对")
        return paper, "Crossref：" + friendly_error(exc)


def merge_papers(papers, query):
    merged = []
    for paper in papers:
        if not paper.title:
            continue
        paper.score = similarity(query, paper.title)
        existing = next((p for p in merged if (p.doi and paper.doi and p.doi.lower() == paper.doi.lower()) or ((not p.doi or not paper.doi) and normalized(p.title) == normalized(paper.title) and (not p.authors or not paper.authors or normalized(p.authors) == normalized(paper.authors)))), None)
        if existing:
            for link in paper.links:
                existing.add_link(link.label, link.url, link.kind, link.source, link.note)
        else:
            merged.append(paper)
    merged.sort(key=lambda p: p.score, reverse=True)
    for paper in merged:
        paper.match = "标题高度相似 · 请核对" if paper.score >= 0.88 else "检索候选 · 请核对标题和作者"
    return merged[:5]


def automatic_target(result):
    """只对单一标识符或唯一完全匹配的标题自动打开。"""
    if not result.matches_ready:
        return ""
    direct = extract_dois(result.query)
    arxiv = ARXIV_RE.search(result.query)
    paper = None
    if (len(direct) == 1 or arxiv) and len(result.papers) == 1:
        paper = result.papers[0]
    else:
        exact = [p for p in result.papers if normalized(p.title) == normalized(result.query)]
        if len(exact) == 1:
            paper = exact[0]
    if not paper:
        return ""
    links = sorted(paper.links, key=lambda x: {"pdf": 0, "fulltext": 1, "publisher": 2}[x.kind])
    return next((x.url for x in links if safe_link(x.url) and (result.complete or len(direct) == 1 or x.kind in ("pdf", "fulltext"))), "")


def find_papers(raw: str, email="", progress: Callable[[str], None] = lambda _: None,
                on_result: Callable[[Result], None] = lambda _: None) -> Result:
    raw = raw.strip()
    if not raw:
        raise LookupError("请粘贴论文标题、DOI 或推送链接。")
    if len(raw) > 20000:
        raise LookupError("输入内容太长，请只粘贴文献段落或链接。")
    notes, extracted_title = [], ""
    page = None
    base_url = ""
    dois = extract_dois(raw)
    arxiv = ARXIV_RE.search(raw)
    # DOI 链接不必先读取出版社；普通网页读取正文和引用元数据。
    urls = re.findall(r"https?://[^\s<>\"\u3000]+", raw)
    if not dois and not arxiv and urls:
        progress("正在读取推送 / 网页中的文献信息…")
        url = html.unescape(urls[0]).rstrip("，。；）.,)")
        try:
            content, base_url, content_type = fetch(url, webpage=True)
        except LookupError as exc:
            if urllib.parse.urlsplit(url).hostname == "mp.weixin.qq.com":
                raise BrowserPageRequired(url, "公众号暂时无法直接读取（网络、访问限制或验证）。") from exc
            raise LookupError(f"无法读取这个网页：{exc} 可以复制推送里的英文论文标题或 DOI 再查找。") from exc
        if content_type not in ("text/html", "application/xhtml+xml", "text/plain"):
            raise LookupError("这个链接不是可解析的推送网页，请粘贴论文标题或 DOI。")
        page = ArticleParser()
        page.feed(content)
        text = " ".join(page.article_text or page.text)
        blocked = any(x in text for x in ("环境异常", "访问过于频繁", "请在微信客户端打开", "完成验证后"))
        if blocked and not (len("".join(page.article_text).strip()) >= 80 or page.first("citation_title")):
            raise BrowserPageRequired(url)
        if urllib.parse.urlsplit(url).hostname == "mp.weixin.qq.com" and not page.article_text and not page.first("og:title"):
            raise BrowserPageRequired(url, "公众号没有返回可识别的文章正文。")
        # citation_doi / dc.identifier 比正文中的参考文献优先。
        meta_dois = extract_dois(" ".join(page.values("citation_doi") + page.values("dc.identifier") + page.values("dc.identifier.doi")))
        dois = meta_dois or extract_dois(text + " " + " ".join(page.links))
        arxiv = ARXIV_RE.search(text + " " + " ".join(page.links))
        extracted_title = page.title
        if len(dois) > 1:
            notes.append("网页含多个 DOI，可能包含参考文献；请核对结果是否为推送介绍的论文。")
        if len(dois) > 5:
            notes.append(f"识别到 {len(dois)} 个 DOI，本次展示前 5 个；可粘贴具体 DOI 单独查询。")
    papers = []
    matches_ready = bool(dois or arxiv)

    def publish():
        if papers:
            on_result(copy.deepcopy(Result(raw, papers, list(dict.fromkeys(notes)), extracted_title,
                                           complete=False, matches_ready=matches_ready)))

    identifiers = bool(dois or arxiv)
    if identifiers:
        progress("已生成原文入口，正在并行补充论文信息和开放版本…")
        jobs = {}
        identifiers_to_check = dois[:5] if dois else [""]
        for index, doi in enumerate(identifiers_to_check):
            arxiv_doi = re.fullmatch(r"10\.48550/arxiv\.(.+)", doi, re.I)
            ident = arxiv_doi.group(1) if arxiv_doi else (arxiv.group(1) if not dois else "")
            paper = identifier_paper(doi, ident)
            papers.append(paper)
            if ident:
                jobs[(index, "arXiv")] = lambda ident=ident: search_arxiv(ident=ident)
            else:
                jobs[(index, "metadata")] = lambda doi=doi: lookup_doi(doi)
                for name, job in oa_jobs(paper, email, index == 0).items():
                    jobs[(index, name)] = job
        publish()
        for (index, name), data in completed_jobs(jobs, BACKGROUND_BUDGET, notes):
            paper = papers[index]
            if name == "metadata":
                fresh, note = data
                update_metadata(paper, fresh)
                if note:
                    notes.append(note)
            elif name == "arXiv":
                if data:
                    update_metadata(paper, data[0])
            else:
                apply_oa(paper, name, data, notes)
            publish()
        if len(dois) > 5 and not page:
            notes.append("输入含多个 DOI，本次展示前 5 个。")
    else:
        query = extracted_title or raw
        if page:
            notes.append("网页未发现 DOI，正在用网页标题检索候选。若不匹配，请粘贴正文中的英文论文标题。")
        if len(query) < 5 or len(query) > 1000:
            raise LookupError("请粘贴具体的论文标题或 DOI，避免整篇推送正文。")
        progress("正在并行检索标题，结果到达即可打开…")
        all_papers = []
        jobs = {"Crossref": lambda: search_crossref(query), "Europe PMC": lambda: [pmc_paper(x) for x in search_pmc('TITLE:"' + query.replace('"', " ") + '"')], "arXiv": lambda: search_arxiv(query=query)}
        for source, found in completed_jobs(jobs, SEARCH_BUDGET, notes, has_result=lambda: bool(papers)):
            all_papers.extend(found)
            papers = merge_papers(all_papers, query)
            publish()
        # Automatic title opening waits for the discovery window to avoid choosing a same-title DOI prematurely.
        matches_ready = True
        publish()
    if not papers:
        if any("连接失败" in x or "限流" in x or "响应较慢" in x for x in notes):
            raise LookupError("检索服务连接失败、响应较慢或限流。可点击“直接学术搜索”继续，或改用 DOI 查询。")
        raise LookupError("未找到文献。请尝试完整英文标题或 DOI；中文推送标题可能与论文标题不同。")
    # citation_pdf_url 只绑定已确认的论文，不绑定未知推送标题。
    if page and len(papers) == 1 and (page.first("citation_title") or page.first("citation_doi")):
        paper = papers[0]
        if similarity(page.first("citation_title"), paper.title) >= 0.88 or (dois and page.first("citation_doi").lower() == paper.doi.lower()):
            for value in page.values("citation_pdf_url"):
                paper.add_link("网页提供的 PDF", urllib.parse.urljoin(base_url, value), "publisher", "网页元数据", "网页提供的下载入口，可能需要订阅")
    if not identifiers:
        progress("已有结果可直接打开，正在补充开放原文…")
        jobs = {}
        for index, paper in enumerate(papers[:3]):
            if has_open(paper):
                continue
            for name, job in oa_jobs(paper, email, index == 0).items():
                jobs[(index, name)] = job
        for (index, name), data in completed_jobs(jobs, ENRICH_BUDGET, notes):
            apply_oa(papers[index], name, data, notes)
            publish()
    for paper in papers:
        paper.links.sort(key=lambda x: {"pdf": 0, "fulltext": 1, "publisher": 2}[x.kind])
    return Result(raw, papers, list(dict.fromkeys(notes)), extracted_title)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="文献直达命令行检索")
    parser.add_argument("query", help="标题、DOI 或推送链接")
    parser.add_argument("--email", default="", help="可选：Unpaywall API 联系邮箱")
    args = parser.parse_args()
    try:
        print(json.dumps(find_papers(args.query, args.email).to_dict(), ensure_ascii=False, indent=2))
    except LookupError as exc:
        parser.exit(1, str(exc) + "\n")
