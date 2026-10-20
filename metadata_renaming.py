"""Read local article information before previewing an explicit rename operation."""
from pathlib import Path
import re
import string
import zipfile
import xml.etree.ElementTree as ET
import math
import unicodedata
from collections import Counter

from library_core import document_metadata, digest, readable_attachments, local_attachments


LABELS = {
    'title': r'(?:论文标题|文章标题|文献标题|标题|题名|题目|article\s+title|title)',
    'authors': r'(?:作者|authors?)',
    'venue': r'(?:期刊名称|期刊|刊名|发表刊物|journal(?:\s+name)?|published\s+in)',
    'year': r'(?:出版年份|发表年份|出版年|年份|publication\s+year|year)',
    'doi': r'DOI',
}
NAMES = {'title': '标题', 'authors': '作者', 'venue': '期刊', 'year': '年份', 'doi': 'DOI'}
PLACEHOLDERS = {'unknown', 'untitled', 'microsoft word', 'administrator', 'admin', 'user',
                'lenovo', 'dell', 'hp', 'wxz', 'cnki', '未知作者', '未知年份', '未知期刊'}


def meaningful(value):
    value = str(value or '').strip()
    return bool(value and value.casefold() not in PLACEHOLDERS)


def article_title(value):
    value = str(value or '').strip().lstrip('+*—–- ')
    return (meaningful(value) and 5 <= len(value) <= 350 and
            not re.match(r'(?i)^(?:figures?\b|tables?\b|supplement(?:ary|al)?\b|references?\b|'
                         r'appendix\b|abstract\b|keywords?\b|https?://|doi\s*[:：]|'
                         r'journal\b|authors?\s*[:：]|year\s*[:：]|received\b|accepted\b|copyright\b|'
                         r'downloaded\b|an update to this article\b|original (?:paper|investigation|research)\b|research article\b|open access\b|'
                         r'图\s*\d|表\s*\d|补充材料|附件|参考文献|摘要|关键词|期刊|作者\s*[:：]|年份\s*[:：])', value) and
            not value.casefold().startswith(('microsoft ', 'untitled')))


def author_line(value):
    value=unicodedata.normalize('NFKC',value)
    value=re.sub(r'(?i),?\s*\b(?:PhD|MPH|MD|MSc|BSc|MM|MBBS|MA|BA)\b\.?','',value)
    value = re.sub(r'\s*\d+(?:\s*[,，]\s*\d+)*\s*[*†‡]?', '', value)
    value = value.strip(' *†‡,，')
    if not meaningful(value) or len(value) > 250:
        return ''
    if re.search(r'(?i)\b(university|department|hospital|institute|abstract|copyright|received|'
                 r'accepted|published|journal|correspond|figure|table)\b|[。！？@]|大学|医院|学院', value):
        return ''
    value=re.sub(r'[¹²³⁴⁵⁶⁷⁸⁹⁰*†‡]+','',value)
    parts = re.split(r'\s*[;；、]\s*|\s+and\s+|\s*[，,]\s*|(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', value)
    if parts and all(re.fullmatch(r'[\u4e00-\u9fff]{2,4}', p) or
                     re.fullmatch(r"[A-Z][a-zA-Z.’'\-]*(?:\s+[A-Z][a-zA-Z.’'\-]*){1,4}", p)
                     for p in parts):
        return '; '.join(parts)
    return ''


def pdf_title_candidate(path):
    """Read first-page typography so ordinary unlabelled article titles work."""
    from pypdf import PdfReader
    fragments=[]
    reader=PdfReader(path)
    if not reader.pages:return ''
    def visit(text, cm, tm, font, size):
        effective=float(size or 0)*max(.001,math.hypot(tm[0],tm[1]))*max(.001,math.hypot(cm[0],cm[1]))
        for line in text.splitlines():
            line=unicodedata.normalize('NFKC',re.sub(r'\s+',' ',line).strip())
            if line:fragments.append((line,effective))
    reader.pages[0].extract_text(visitor_text=visit)
    generic={'research article','original article','open access','article','research','review','review article','original research'}
    candidates=[(i,text,size) for i,(text,size) in enumerate(fragments[:120]) if article_title(text) and text.lower() not in generic and not author_line(text) and len(text)>10]
    if not candidates:return ''
    index,text,size=max(candidates,key=lambda item:(item[2],-item[0]))
    if index and abs(fragments[index-1][1]-size)<.5 and len(fragments[index-1][0])<=8:
        previous=fragments[index-1][0]
        text=previous+('' if len(previous)>2 and previous[-1].islower() and text[0].islower() else ' ')+text
    sizes=Counter(round(v,1) for _,v in fragments if v>0)
    baseline=max(sizes,key=lambda v:(sizes[v],-v)) if sizes else size
    if size<baseline*1.12:return ''
    parts=[text]
    for following,next_size in fragments[index+1:index+5]:
        if abs(next_size-size)>.5 or not article_title(following) or author_line(following):break
        parts.append(following)
    candidate=' '.join(parts)
    return candidate if article_title(candidate) else ''


def extract_article_metadata(path):
    """Read the file without launching Word, a viewer, a browser, or a network call."""
    path = Path(path)
    if path.suffix.lower() == '.doc':
        raise ValueError('旧版 DOC 暂不能直接识别正文信息，请另存为 DOCX 后重试，或编辑文献信息。')
    raw = document_metadata(path)
    text = re.split(r'(?im)^\s*(?:\d+[.)]?\s*)?(?:references|bibliography|参考文献)\s*[:：]?\s*$',
                    raw.get('text', ''), maxsplit=1)[0]
    lines = [unicodedata.normalize('NFKC',re.sub(r'\s+', ' ', line).strip()) for line in text[:14000].splitlines() if line.strip()]
    fields, sources = {}, {}
    for field, label in LABELS.items():
        for index, line in enumerate(lines[:50]):
            match = re.match(r'^\s*' + label + r'\s*[:：]\s*(.*)$', line, re.I)
            if match:
                value = match.group(1).strip()
                if not value and index + 1 < len(lines):
                    value = lines[index + 1]
                if meaningful(value):
                    fields[field], sources[field] = value, '正文标注'
                break
    if fields.get('title') and not article_title(fields['title']):
        fields.pop('title'); sources.pop('title')
    # Use actual title text, never the original or archived filename.
    candidate = raw.get('title', '')
    if path.suffix.lower()=='.pdf':
        visual_title=pdf_title_candidate(path)
        metadata_in_body=re.sub(r'\W+','',unicodedata.normalize('NFKC',candidate)).casefold() in re.sub(r'\W+','',unicodedata.normalize('NFKC',text[:8000])).casefold()
        if visual_title and (not article_title(candidate) or candidate==path.stem or not metadata_in_body):candidate=visual_title
    if path.suffix.lower() == '.docx':
        # document_metadata already checks archive/XML limits and entity declarations.
        # Distinguish an actual title property/style from its filename fallback.
        with zipfile.ZipFile(path) as archive:
            candidate = ''
            if 'docProps/core.xml' in archive.namelist():
                props = ET.fromstring(archive.read('docProps/core.xml'))
                candidate = props.findtext('{http://purl.org/dc/elements/1.1/}title', '')
            root = ET.fromstring(archive.read('word/document.xml'))
            ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            for para in list(root.iter(ns + 'p'))[:40]:
                style = para.find(ns + 'pPr/' + ns + 'pStyle')
                if style is not None and style.get(ns + 'val', '').lower() in ('title', '标题'):
                    styled = ''.join(t.text or '' for t in para.iter(ns + 't')).strip()
                    if article_title(styled):
                        candidate = styled; break
    if 'title' not in fields and article_title(candidate) and candidate != path.stem:
        fields['title'], sources['title'] = candidate, '文件题名 / 标题样式'
    if 'title' not in fields:
        for i, line in enumerate(lines[:15]):
            if article_title(line) and (i + 1 < len(lines) and author_line(lines[i + 1])):
                fields['title'], sources['title'] = line, '正文标题与署名'
                break
    if 'authors' not in fields and fields.get('title'):
        normalized=re.sub(r'\W+','',fields['title']).casefold()
        index = next((i for i, line in enumerate(lines[:40]) if re.sub(r'\W+','',line).casefold()==normalized), None)
        if index is None:
            for start in range(min(30,len(lines))):
                for count in range(2,5):
                    if re.sub(r'\W+','',''.join(lines[start:start+count])).casefold()==normalized:
                        index=start+count-1;break
                if index is not None:break
        if index is not None:
            byline=[]
            for line in lines[index+1:index+14]:
                if re.search(r'(?i)\b(school|university|department|abstract|corresponding|institute|hospital)\b|摘要|大学|学院',line):break
                if re.fullmatch(r'[\d,;*†‡\s]+',line):continue
                byline.append(line)
            for line in [' '.join(byline),*byline,*lines[index + 1:index + 4]]:
                authors = author_line(line)
                if authors:
                    fields['authors'], sources['authors'] = authors, '正文署名'; break
    # A Word creator is frequently an office username, not an article's author.
    if path.suffix.lower() == '.pdf' and 'authors' not in fields and meaningful(raw.get('authors')):
        authors = author_line(raw['authors'])
        if authors:
            fields['authors'], sources['authors'] = authors, 'PDF 作者属性（需核对）'
    if fields.get('year') and not re.fullmatch(r'(?:18|19|20)\d{2}', fields['year']):
        fields.pop('year'); sources.pop('year')
    if fields.get('venue'):
        match = re.search(r'\b((?:18|19|20)\d{2})\b', fields['venue'])
        if match and 'year' not in fields:
            fields['year'], sources['year'] = match.group(1), '正文期刊信息'
    if 'venue' not in fields:
        for line in lines[:12]:
            match = re.match(r'^(.+?(?:Journal\s+of\s+.+?|杂志|学报))\s+((?:19|20)\d{2})\s*[;,，；]', line, re.I)
            if match:
                fields['venue'], sources['venue'] = match.group(1), '正文期刊与年份'
                fields.setdefault('year', match.group(2)); sources.setdefault('year', '正文期刊与年份')
                break
    if 'doi' not in fields and raw.get('doi'):
        fields['doi'], sources['doi'] = raw['doi'], '正文 DOI'
    return {'fields': fields, 'sources': sources}


def prepare_renames(library, ids):
    """Read first, build previews second, and leave all files and metadata untouched."""
    plans = []
    reserved = set()
    for rid in ids:
        record = library.get(rid)
        plan = {'id': rid, 'before': record, 'fields': {}, 'sources': {}, 'files': [], 'warnings': [], 'error': ''}
        plan['template'] = library.template(record['primary_project'])
        plan['title_length'] = library.setting('title_length', 80)
        plans.append(plan)
        primary = next((a for a in readable_attachments(record) if a.get('role') == 'primary'), None)
        if not primary:
            plan['error'] = '没有可识别的正文附件，请先指定正文。'; continue
        source = library.root / primary['path']
        try:
            # Digests also guard against an attachment changing during extraction.
            before_digest = digest(source)
            extracted = extract_article_metadata(source)
            if digest(source) != before_digest:
                raise ValueError('正文已变化，请重新预览。')
            plan.update(extracted)
            plan['primary'] = {'id': primary['id'], 'path': primary['path'], 'digest': before_digest}
            merged = dict(record, **extracted['fields'])
            for key in ('authors', 'year', 'venue', 'doi', 'title'):
                if key not in extracted['fields']:
                    plan['warnings'].append(NAMES[key] + '未从文件识别' + ('，沿用库中信息' if meaningful(merged.get(key)) else ''))
            bad_titles = {Path(a.get('original') or a['path']).stem for a in record['attachments'] if a.get('path')}
            if 'title' not in extracted['fields'] and (merged.get('title') in bad_titles or not article_title(merged.get('title'))):
                merged['title'] = ''
            aliases = {'年份': 'year', 'year': 'year', '第一作者': 'authors', 'author': 'authors',
                       '标题': 'title', 'title': 'title', '期刊': 'venue', 'journal': 'venue', 'venue': 'venue', 'DOI': 'doi', 'doi': 'doi'}
            required = {'title'}
            missing = [NAMES[k] for k in sorted(required) if not meaningful(merged.get(k))]
            if missing:
                raise ValueError('缺少可靠的' + '、'.join(missing) + '；请先“编辑信息”补全，或关联含题名和署名的正文。')
            for attachment in local_attachments(record):
                old = library.root / attachment['path']
                if not old.is_file():
                    plan['warnings'].append('附件缺失：' + old.name); continue
                base = library.target(merged, attachment)
                target, index = base, 2
                while (str(target).casefold() in reserved or
                       (target.exists() and target.resolve() != old.resolve()) or
                       library.db.execute('SELECT id FROM attachments WHERE path=? COLLATE NOCASE AND id<>?',
                                          (str(target.relative_to(library.root)), attachment['id'])).fetchone()):
                    target = base.with_stem(base.stem + f' ({index})'); index += 1
                reserved.add(str(target).casefold())
                plan['files'].append({'id': attachment['id'], 'old': attachment['path'],
                                      'new': str(target.relative_to(library.root)), 'digest': digest(old)})
        except Exception as exc:
            plan['error'] = str(exc)
    return plans


def apply_renames(library, plans):
    """Validate confirmed previews before committing metadata and existing safe renames."""
    count, errors = 0, []
    for plan in plans:
        if plan['error']:
            errors.append(plan['before']['title'] + '：' + plan['error']); continue
        try:
            current = library.get(plan['id'])
            before = plan['before']
            # Ignore notes edits; never overwrite them with the preview's snapshot.
            for key in ('title', 'authors', 'year', 'venue', 'doi', 'primary_project', 'attachments'):
                if current.get(key) != before.get(key):
                    raise ValueError('文献信息或附件已变化，请重新预览。')
            if (library.template(current['primary_project']) != plan['template'] or
                    library.setting('title_length', 80) != plan['title_length']):
                raise ValueError('命名规则已变化，请重新预览。')
            primary = plan['primary']
            if digest(library.root / primary['path']) != primary['digest']:
                raise ValueError('正文已变化，请重新预览。')
            for item in plan['files']:
                old, new = library.root / item['old'], library.root / item['new']
                if digest(old) != item['digest'] or (new.exists() and new.resolve() != old.resolve()):
                    raise ValueError('文件或目标名称已变化，请重新预览。')
            # Save only fields read from the document, retaining notes and annotations.
            library.save(plan['fields'], rid=plan['id'])
            count += len(library.rename(plan['id'], destinations={item['id']: item['new'] for item in plan['files']}))
        except Exception as exc:
            errors.append(plan['before']['title'] + '：' + str(exc))
    return {'count': count, 'errors': errors}
