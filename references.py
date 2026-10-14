"""Heuristic reference extraction from local PDF text; never invent missing data."""
import hashlib
import re
import unicodedata
from paper_finder import extract_dois

def parse_references(text):
    text=unicodedata.normalize('NFKC',str(text)).replace('\r\n','\n').replace('\r','\n').replace('\ufffe','-').replace('\u00ad','-')
    # BMJ wraps DOI suffixes at a hyphen/slash, sometimes onto a digits-only
    # line. Join those pieces before deciding which digits are reference labels.
    for _ in range(6):
        repaired=re.sub(r'(10\.\d{4,9}/(?:[^\s<>"\n]*[-/])?)\s*\n\s*([A-Za-z0-9][A-Za-z0-9./_():+-]*)',r'\1\2',text)
        if repaired==text:break
        text=repaired
    headings=list(re.finditer(r'(?im)^[ \t]*(?:\d+(?:\.\d+)*[.)、]?[ \t]*)?(?:references(?:\s+and\s+notes)?|bibliography|literature cited|参\s*考\s*文\s*献)(?:[ \t]*\([^\n)]{0,30}\))?[ \t]*[:：]?[ \t]*(?:\n|$|(?=\[\d+\]))',text))
    section=text[headings[-1].end():] if headings else text
    marker_pattern=r'(?m)^[ \t]*(?:[\[【〔](\d{1,4})[\]】〕]|\((\d{1,4})\)|(\d{1,4})[.)、]|(\d{1,4})[ \t]+(?=[A-Z\u4e00-\u9fff]))[ \t]*'
    markers=[m for m in re.finditer(marker_pattern,section) if int(next(g for g in m.groups() if g))<1900]
    if not headings:
        # A missing/combined heading is recoverable only with consecutive numbers
        # and strong bibliographic evidence, never an arbitrary numbered body list.
        sequences=[]
        for i,m in enumerate(markers):
            number=int(next(g for g in m.groups() if g));end=markers[i+1].start() if i+1<len(markers) else len(section)
            raw=section[m.end():end]
            strong=bool(re.search(r'10\.\d{4,9}/|\[(?:J|M|R|D|DB/OL|EB/OL|C)(?:/OL)?\]|\b(?:19|20)\d{2}\s*[;,]\s*\d',raw,re.I))
            sequences.append((number,strong))
        starts=[]
        for i in range(len(sequences)-2):
            if not all(sequences[j+1][0]==sequences[j][0]+1 for j in (i,i+1)) or sum(s for _,s in sequences[i:i+3])<2:continue
            first=i
            while first and sequences[first-1][0]+1==sequences[first][0]:first-=1
            end=i+2
            while end+1<len(sequences) and sequences[end+1][0]==sequences[end][0]+1:end+=1
            starts.append((end-first+1,sequences[first][0]==1,first))
        if not starts:return []
        start=max(starts)[2]
        section=section[markers[start].start():]
    section=re.split(r'(?im)^\s*(?:web appendix|appendix|supporting information|supplementary information|附录)\s*(?:[:：].*)?$',section)[0]
    markers=[m for m in re.finditer(marker_pattern,section) if int(next(g for g in m.groups() if g))<1900]
    if markers:chunks=[(next(g for g in m.groups() if g),section[m.end():markers[i+1].start() if i+1<len(markers) else len(section)]) for i,m in enumerate(markers)]
    else:
        # Unnumbered bibliography: only split at plausible author-year starts.
        chunks=[('',c) for c in re.split(r'(?m)(?=^(?:[A-Z][a-zA-Z\-]{2,},|[\u4e00-\u9fff]{2,8}[,，])[^\n]{0,200}\b(?:19|20)\d{2}\b)',section)]
        if len(chunks)==1:
            lines=section.splitlines();chunks=[];current=[]
            for line in lines:
                if current and re.search(r'\[(?:J|M|R|D|DB/OL|EB/OL|C)(?:/OL)?\]',line,re.I) and re.search(r'(?:19|20)\d{2}',line):chunks.append(('', '\n'.join(current)));current=[]
                current.append(line)
            if current:chunks.append(('', '\n'.join(current)))
    result=[];seen=set()
    for number,chunk in chunks[:500]:
        raw=re.sub(r'\s+',' ',chunk).strip()
        if len(raw)<15:continue
        dois=extract_dois(raw);doi=dois[0] if dois else ''
        year=re.search(r'\b(?:19|20)\d{2}\b',raw)
        cleaned=re.sub(r'https?://\S+|doi:\s*\S+','',raw,flags=re.I).strip()
        parts=re.split(r'\.\s+(?=[A-Z\u4e00-\u9fff])',cleaned)
        candidates=[p.strip(' .') for p in (parts[1:] if len(parts)>1 else parts) if len(p.strip())>=8 and not re.match(r'^(?:doi|https?|protected by copyright|copyright|downloaded)',p,re.I)]
        chinese=re.search(r'^[^.。]+[.。]\s*(.+?)\s*\[(?:J|M|R|D|DB/OL|EB/OL|C)(?:/OL)?\]',cleaned,re.I)
        title=chinese.group(1)[:240] if chinese else candidates[0][:240] if candidates else cleaned[:240]
        title=re.sub(r'^.*?\((?:19|20)\d{2}[a-z]?\)\.?\s*','',title)
        if not title.strip():title=next((p for p in candidates[1:] if p.strip()),cleaned[:240])
        key=doi or re.sub(r'\W+','',title).lower()
        if not key or (key in seen and not number):continue
        seen.add(key)
        result.append({'id':'candidate-'+hashlib.sha256(key.encode()).hexdigest()[:20], 'title':title,
                       'doi':doi,'year':year.group() if year else '', 'raw':raw[:2500],
                       'query':doi or title,'number':number,'confidence':'DOI 已提取，标题需核对' if doi else '标题为启发式提取，需核对'})
    return result
