"""Explicit provider routes and OpenAI-compatible API presets; no network at import."""
import re
from urllib.parse import urlsplit

PROVIDERS = {
    'chatgpt': {'name': 'ChatGPT', 'web': 'https://chatgpt.com/', 'api': 'https://api.openai.com/v1', 'paths': [r'/c/[A-Za-z0-9-]{8,100}']},
    'doubao': {'name': '豆包', 'web': 'https://www.doubao.com/chat/', 'api': 'https://ark.cn-beijing.volces.com/api/v3', 'paths': [r'/chat/[A-Za-z0-9_-]{4,150}']},
    'deepseek': {'name': 'DeepSeek', 'web': 'https://chat.deepseek.com/', 'api': 'https://api.deepseek.com/v1', 'paths': [r'/a/chat/s/[A-Za-z0-9_-]{4,150}']},
    'gemini': {'name': 'Gemini', 'web': 'https://gemini.google.com/app', 'api': 'https://generativelanguage.googleapis.com/v1beta/openai', 'paths': [r'/app/[A-Za-z0-9_-]{4,150}']},
    'qwen': {'name': '千问 / Qwen', 'web': 'https://chat.qwen.ai/', 'api': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'paths': [r'/c/[A-Za-z0-9_-]{4,150}']},
    'kimi': {'name': 'Kimi', 'web': 'https://www.kimi.com/', 'api': 'https://api.moonshot.cn/v1', 'paths': [r'/chat/[A-Za-z0-9_-]{4,150}']},
    'custom': {'name': '自定义兼容 API', 'web': '', 'api': '', 'paths': []},
}


def web_route(value, provider=None, conversation=False):
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):return ''
        for key, info in PROVIDERS.items():
            if provider and key != provider:continue
            home = urlsplit(info['web'])
            if parsed.netloc != home.netloc or not home.netloc:continue
            if (not conversation and parsed.path == home.path) or any(re.fullmatch(p, parsed.path) for p in info['paths']):
                return 'https://' + parsed.netloc + parsed.path
    except (TypeError, ValueError):pass
    return ''


def api_endpoint(value):
    """HTTPS everywhere except explicit local servers. Never send keys across redirects."""
    value = str(value).strip().rstrip('/')
    try:
        u = urlsplit(value)
        local = u.hostname in ('127.0.0.1', 'localhost', '::1')
        if (u.scheme != 'https' and not (u.scheme == 'http' and local)) or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError()
        if any(c.isspace() or ord(c) < 32 for c in value):raise ValueError()
        u.port
    except ValueError:raise ValueError('API 地址需为 HTTPS；本机服务可使用 http://127.0.0.1:端口/v1。') from None
    return value if value.endswith('/chat/completions') else value + '/chat/completions'
