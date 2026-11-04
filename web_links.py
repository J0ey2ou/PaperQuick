"""HTTP(S) links opened only by an explicit user action."""
import re
from urllib.parse import urlsplit


def safe_web_url(value):
    if not isinstance(value,str) or not value or len(value)>8192 or '\\' in value or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in value):return ''
    try:
        parsed=urlsplit(value)
        if parsed.scheme.lower() not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:return ''
        parsed.port
    except (ValueError,TypeError):return ''
    return value


def answer_links(text):
    """Find plain/Markdown URL spans while retaining balanced DOI parentheses."""
    for match in re.finditer(r'https?://[^\s<>"\[\]{}]+',text,re.I):
        url=match.group().rstrip('.,;:!?，。；：！？、”’')
        while url.endswith(')') and url.count(')')>url.count('('):url=url[:-1]
        if safe_web_url(url):yield match.start(),match.start()+len(url),url


def open_web_link(url):
    checked=safe_web_url(url)
    if not checked:raise ValueError('仅支持打开有效的 HTTP / HTTPS 网页链接。')
    import webbrowser
    if not webbrowser.open(checked):raise OSError('默认浏览器未能打开，请检查浏览器设置。')
    return True
