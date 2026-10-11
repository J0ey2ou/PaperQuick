"""Local CSL citation formatting, with portable Node/citeproc-js assets.

``citations`` and ``bibliography`` returned by ``format_document`` are COMPLETE
RTF documents, not fragments. ``plain_*`` contain independently rendered text.
No function in this module accesses the network.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

NS = {"c": "http://purl.org/net/xbiblio/csl"}
MAX_STYLE_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_BYTES = 28 * 1024 * 1024


class CitationStyleError(ValueError):
    """A missing, incompatible or invalid citation format."""


def asset_directory() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "word-integration"


def _parse_style(path: Path):
    if not path.is_file():
        raise CitationStyleError("未找到这个引用格式，请重新选择或导入 CSL 文件。")
    if path.stat().st_size > MAX_STYLE_BYTES:
        raise CitationStyleError("这个格式文件过大，请选择标准 CSL 文件。")
    raw = path.read_bytes()
    # Decode before scanning: UTF-16 files must not bypass the DTD/entity check.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw[:80]:
        raise CitationStyleError("请使用 UTF-8 编码的 CSL 格式文件。")
    try:
        xml = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CitationStyleError("请使用 UTF-8 编码的 CSL 格式文件。") from exc
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", xml, flags=re.I):
        raise CitationStyleError("这个文件包含不受支持的外部定义，请选择标准 CSL 文件。")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise CitationStyleError("这个 CSL 文件内容不完整，暂时无法使用。") from exc
    if root.tag != "{http://purl.org/net/xbiblio/csl}style":
        raise CitationStyleError("请选择 Citation Style Language（.csl）格式文件。")
    if len(list(root.iter())) > 20000:
        raise CitationStyleError("这个格式文件过于复杂，暂时无法使用。")
    stack = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > 80:
            raise CitationStyleError("这个格式文件过于复杂，暂时无法使用。")
        stack.extend((child, depth + 1) for child in node)
    title = root.findtext("c:info/c:title", namespaces=NS)
    uri = root.findtext("c:info/c:id", namespaces=NS)
    if not title or not title.strip() or not uri or not uri.strip():
        raise CitationStyleError("这个格式文件缺少名称或标识，请重新下载完整文件。")
    parent = next((link.get("href", "") for link in root.findall("c:info/c:link", NS)
                   if link.get("rel") == "independent-parent"), "")
    style_class = root.get("class", "")
    if not parent and style_class not in ("in-text", "note"):
        raise CitationStyleError("这个格式文件没有指定有效的引用方式。")
    if not parent and root.find("c:citation/c:layout", NS) is None:
        raise CitationStyleError("这个格式文件缺少引文排版规则。")
    category = next((c.get("citation-format") for c in root.findall("c:info/c:category", NS)
                     if c.get("citation-format")), "author-date")
    return {"id": path.stem, "title": title.strip(), "uri": uri.strip(),
            "category": category, "style_class": style_class, "parent": parent,
            "locale": root.get("default-locale", ""), "path": path,
            "xml": xml, "root": root}


def _catalog(custom_dir=None):
    styles = {}
    directories = [asset_directory() / "styles"]
    if custom_dir:
        directories.append(Path(custom_dir))
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.csl")):
            try:
                info = _parse_style(path)
                # Custom imports receive hash IDs and cannot override bundled styles.
                if info["id"] not in styles:
                    info["custom"] = directory == Path(custom_dir) if custom_dir else False
                    styles[info["id"]] = info
            except (CitationStyleError, OSError):
                continue
    return styles


def _resolve(info, catalog):
    current = info
    seen = set()
    locale = info.get("locale", "")
    while current.get("parent"):
        if current["uri"] in seen:
            raise CitationStyleError("这个格式的依赖关系有重复，请重新下载完整文件。")
        seen.add(current["uri"])
        parent_uri = current["parent"].rstrip("/")
        target = next((entry for entry in catalog.values()
                       if entry["uri"].rstrip("/") == parent_uri), None)
        if target is None:
            raise CitationStyleError("这个格式需要基础样式，请先导入：" + parent_uri.rsplit("/", 1)[-1])
        current = target
        if not locale:
            locale = current.get("locale", "")
    return current, locale


def list_styles(custom_dir=None) -> list[dict]:
    """List installed user-selectable formats; note formats carry style_class=note."""
    catalog = _catalog(custom_dir)
    manifest_path = asset_directory() / "vendor" / "manifest.json"
    try:
        selected = json.loads(manifest_path.read_text(encoding="utf-8"))["styles"]
    except (OSError, ValueError, KeyError):
        selected = list(catalog)
    order = {value: index for index, value in enumerate(selected)}
    output = []
    for style_id, info in catalog.items():
        if style_id not in order and not info["custom"]:
            continue
        try:
            effective, _locale = _resolve(info, catalog)
        except CitationStyleError:
            continue
        output.append({"id": style_id, "title": info["title"],
                       "category": effective["category"],
                       "style_class": effective["style_class"],
                       "custom": info["custom"]})
    return sorted(output, key=lambda info: (info["custom"], order.get(info["id"], 9999), info["title"].casefold()))


def import_style(path, custom_dir) -> str:
    """Validate and copy a CSL file; dependencies must already be installed."""
    source = Path(path)
    if source.suffix.lower() != ".csl":
        raise CitationStyleError("请选择 .csl 格式文件。")
    info = _parse_style(source)
    catalog = _catalog(custom_dir)
    _resolve(info, catalog)
    style_id = "custom-" + hashlib.sha256(info["xml"].encode("utf-8")).hexdigest()[:20]
    target_dir = Path(custom_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (style_id + ".csl")
    temporary = target.with_suffix(".csl.tmp")
    temporary.write_bytes(info["xml"].encode("utf-8"))
    os.replace(temporary, target)
    return style_id


def _node_executable() -> Path:
    bundled = asset_directory() / "vendor" / "node.exe"
    if bundled.is_file():
        return bundled
    # Development fallback only; production builds must include their own runtime.
    available = shutil.which("node") if not getattr(sys, "frozen", False) else None
    if available:
        return Path(available)
    raise CitationStyleError("引用组件不完整，请重新安装完整版文献直达。")


def _normalize(items, citations):
    if not isinstance(items, dict) or not isinstance(citations, list):
        raise CitationStyleError("文献资料不完整，请重新选择文献。")
    normalized_items = {}
    for item_id, item in items.items():
        if not isinstance(item, dict):
            raise CitationStyleError("文献资料不完整，请核对文献条目。")
        normalized_items[str(item_id)] = dict(item, id=str(item_id))
        normalized_items[str(item_id)].setdefault("type", "article-journal")
    seen_ids = set()
    normalized_citations = []
    for citation in citations:
        if not isinstance(citation, dict) or not citation.get("id"):
            raise CitationStyleError("文档中的一处引文缺少标识，请重新插入该引文。")
        citation_id = str(citation["id"])
        if citation_id in seen_ids:
            raise CitationStyleError("文档中的引文标识重复，请重新插入复制出的引文。")
        seen_ids.add(citation_id)
        cluster = []
        seen_items = set()
        for item in citation.get("items", []):
            if not isinstance(item, dict) or str(item.get("id")) not in normalized_items:
                raise CitationStyleError("一处引文对应的文献资料已缺失，请重新选择文献。")
            normalized = {key: item[key] for key in
                          ("id", "locator", "label", "prefix", "suffix", "suppress-author", "author-only")
                          if key in item}
            normalized["id"] = str(normalized["id"])
            if normalized.get("locator") and not normalized.get("label"):
                normalized["label"] = "page"
            identity = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
            if identity not in seen_items:
                cluster.append(normalized)
                seen_items.add(identity)
        if not cluster:
            raise CitationStyleError("一处引文没有包含文献，请删除后重新插入。")
        normalized_citations.append({"id": citation_id, "items": cluster,
                                     "noteIndex": int(citation.get("noteIndex") or 0)})
    return normalized_items, normalized_citations


def format_document(items: dict, citations: list, style_id: str, custom_dir=None) -> dict:
    """Render every document citation in order, including disambiguation updates.

    Returns complete RTF documents, plain-text previews, bibliography IDs in style
    order, style metadata and warnings. An empty citation list yields an empty RTF
    bibliography. Calls are stateless, so deleting/moving citations re-numbers them.
    """
    catalog = _catalog(custom_dir)
    info = catalog.get(style_id)
    if info is None:
        raise CitationStyleError("未找到这个引用格式，请重新选择或导入 CSL 文件。")
    effective, locale = _resolve(info, catalog)
    normalized_items, normalized_citations = _normalize(items, citations)
    request = {"items": normalized_items, "citations": normalized_citations,
               "style_xml": effective["xml"], "locale": locale or "en-US",
               "force_locale": bool(info.get("parent") and info.get("locale"))}
    encoded = json.dumps(request, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise CitationStyleError("这份文档的文献资料较多，请先减少未使用的文献资料。")
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in ("NODE_OPTIONS", "NODE_PATH")}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.run([str(_node_executable()), str(asset_directory() / "cite_runner.js")],
                                 input=encoded, capture_output=True, timeout=45,
                                 creationflags=flags, env=env)
    except subprocess.TimeoutExpired as exc:
        raise CitationStyleError("这个格式排版耗时较长，请减少一次插入的文献数量或更换格式。") from exc
    except OSError as exc:
        raise CitationStyleError("引用组件暂时无法启动，请重新打开软件后再试。") from exc
    try:
        result = json.loads(process.stdout.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise CitationStyleError("这个格式暂时无法完成排版，请换用其他格式或重新导入。") from exc
    if process.returncode or result.get("error"):
        raise CitationStyleError("这个格式暂时无法完成排版，请检查文献信息或重新导入格式。")
    result.update(style=style_id, title=info["title"], style_class=effective["style_class"])
    return result
