"""Heuristic reference extraction from local PDF text; never invent missing data."""
import hashlib
import re
from paper_finder import extract_dois

def parse_references(text):
    headings=list(re.finditer(r'(?im)^\s*(?:\d+[.)]?\s*)?(?:references|bibliography|literature cited|参考文献)\s*[:：]?\s*$',text))
    if not headings:return []
    section=text[headings[-1].end():]
    section=re.split(r'(?im)^\s*(?:appendix|supporting information|supplementary information|附录)\s*$',section)[0]
    markers=list(re.finditer(r'(?m)^\s*(?:\[(\d{1,4})\]|(\d{1,4})[.)]|(\d{1,4})\s+(?=[A-Z]))\s*',section))
    if markers:chunks=[(next(g for g in m.groups() if g),section[m.end():markers[i+1].start() if i+1<len(markers) else len(section)]) for i,m in enumerate(markers)]
    else:
        # Unnumbered bibliography: only split at plausible author-year starts.
        chunks=[('',c) for c in re.split(r'(?m)(?=^[A-Z][a-zA-Z\-]{2,},[^\n]{0,100}\b(?:19|20)\d{2}\b)',section)]
    result=[];seen=set()
    for number,chunk in chunks[:500]:
        raw=re.sub(r'\s+',' ',chunk).strip()
        if len(raw)<15:continue
        dois=extract_dois(raw);doi=dois[0] if dois else ''
        year=re.search(r'\b(?:19|20)\d{2}\b',raw)
        cleaned=re.sub(r'https?://\S+|doi:\s*\S+','',raw,flags=re.I).strip()
        parts=re.split(r'\.\s+(?=[A-Z\u4e00-\u9fff])',cleaned)
        candidates=[p.strip(' .') for p in parts if len(p.split())>=5 and not re.match(r'^(?:doi|https?)',p,re.I)]
        title=max(candidates,key=len)[:240] if candidates else cleaned[:240]
        title=re.sub(r'^.*?\((?:19|20)\d{2}[a-z]?\)\.?\s*','',title)
        key=doi or re.sub(r'\W+','',title).lower()
        if not key or (key in seen and not number):continue
        seen.add(key)
        result.append({'id':'candidate-'+hashlib.sha256(key.encode()).hexdigest()[:20], 'title':title,
                       'doi':doi,'year':year.group() if year else '', 'raw':raw[:2500],
                       'query':doi or title,'number':number,'confidence':'DOI 已提取，标题需核对' if doi else '标题为启发式提取，需核对'})
    return result
