"""Conservative local DOI extraction; truncated prefixes are never identities."""
import re
import unicodedata


def complete_doi(value):
    value=str(value or '').strip()
    return bool(re.fullmatch(r'10\.\d{4,9}/[^\s<>"\x00-\x1f]+',value,re.I) and not value.endswith(('-', '/', '.', '_', ':')))


def extract_document_doi(metadata_value,body):
    from paper_finder import extract_dois
    for value in (metadata_value,body):
        text=unicodedata.normalize('NFKC',str(value or ''))
        text=text.replace('\r\n','\n').replace('\r','\n').replace('\ufffe','-').replace('\u00ad','-')
        def join(match):
            continuation=match[2]
            # An ordinary following heading/word is not evidence of a DOI suffix.
            return match[1]+continuation if re.search(r'[0-9./_():+-]',continuation) else match[0]
        for _ in range(8):
            joined=re.sub(r'(10\.\d{4,9}/(?:[^\s<>"\n]*[-/])?)\s*\n[ \t]*([A-Za-z0-9][A-Za-z0-9./_():+-]*)',join,text)
            if joined==text:break
            text=joined
        candidates=[doi.lower() for doi in extract_dois(text) if complete_doi(doi)]
        if candidates:return next((doi for doi in candidates if not any(other.startswith(doi) and other!=doi for other in candidates)),candidates[0])
    return ''
