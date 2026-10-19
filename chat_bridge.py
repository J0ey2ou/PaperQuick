"""User-initiated ChatGPT handoffs. No browser, clipboard or service at import time."""
import base64
import io
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from library_core import Library, digest, display_name

MAX_FILE = 24 * 1024 * 1024
CHUNK = 384 * 1024
TTL = 30 * 60


def conversation_url(value):
    """Only personal ChatGPT conversation URLs; never persist fragments/tokens."""
    try:
        url = urlsplit(value)
        if url.scheme == 'https' and url.netloc == 'chatgpt.com' and re.fullmatch(r'/c/[a-zA-Z0-9-]{8,100}', url.path):
            return 'https://chatgpt.com' + url.path
    except (ValueError, TypeError):
        pass
    return ''


class ChatBridge:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.lock = threading.RLock()
        self.requests = {}
        self.server = None

    def _library(self):
        return Library(self.directory)

    def prepare(self, rid, quote='', image=None, page=0):
        if not quote.strip() and image is None:
            raise ValueError('请先选中文字，或使用“框选图片供 ChatGPT 讨论”。')
        if len(quote) > 100000:
            raise ValueError('选中文字过长，请缩小选区。')
        with self.lock:
            lib = self._library()
            try:
                record = lib.get(rid)
                attachment = lib.primary_attachment(rid)
                if not attachment:
                    raise ValueError('请先为这篇文献添加正文。')
                path = (self.directory / attachment['path']).resolve()
                if not path.is_relative_to(self.directory) or not path.is_file():
                    raise ValueError('正文文件不存在或不在文献库内。')
                if path.suffix.lower() not in ('.pdf', '.docx', '.txt', '.md'):
                    raise ValueError('请先将正文转换为 PDF 或 DOCX，再交给 ChatGPT。')
                if path.stat().st_size > MAX_FILE:
                    raise ValueError('网页接入目前支持 24 MB 以内的正文，请先压缩文件。')
                fingerprint = digest(path)
                namespace = lib.setting('chatgpt_library_id')
                if not namespace:
                    namespace = secrets.token_hex(16)
                    lib.set_setting('chatgpt_library_id', namespace)
                saved = lib.setting('chatgpt:' + rid, {})
                if not isinstance(saved, dict):saved = {}
                target = conversation_url(saved.get('url', ''))
                files = []
                if not target or saved.get('fingerprint') != fingerprint:
                    files.append({'name': path.name, 'path': path, 'size': path.stat().st_size,
                                  'fingerprint': fingerprint, 'primary': True})
                if image is not None:
                    buffer = io.BytesIO()
                    image.save(buffer, format='PNG')
                    data = buffer.getvalue()
                    if not data or len(data) > MAX_FILE:
                        raise ValueError('选区图片过大，请缩小选框。')
                    files.append({'name': f'选区-第{page + 1}页.png', 'data': data,
                                  'size': len(data), 'primary': False})
                prompt = f'文献：{display_name(record)}\n第 {page + 1} 页\n\n'
                prompt += quote.strip() if quote.strip() else '请结合文献讨论所附选区图片。'
                token = secrets.token_urlsafe(32)
                now = time.monotonic()
                self.requests = {k: v for k, v in self.requests.items() if now - v['created'] < TTL and not v.get('completed')}
                if len(self.requests) >= 16:
                    raise ValueError('待处理选区过多，请先完成已打开的 ChatGPT 对话。')
                self.requests[token] = {'rid': rid, 'key': namespace + ':' + rid,
                                        'url': target, 'prompt': prompt, 'files': files,
                                        'created': now, 'fingerprint': fingerprint}
                try:
                    self._start()
                except Exception:
                    self.requests.pop(token, None)
                    raise
                return (target or 'https://chatgpt.com/') + f'#paperquick={self.server.server_port}.{token}'
            finally:
                lib.close()

    def _request(self, token):
        item = self.requests.get(token)
        if not item or time.monotonic() - item['created'] >= TTL:
            self.requests.pop(token, None)
            raise ValueError('选区已过期，请回阅读页重新右键打开。')
        return item

    def payload(self, token):
        with self.lock:
            item = self._request(token)
            return {'key': item['key'], 'url': item['url'], 'prompt': item['prompt'],
                    'files': [{'name': f['name'], 'size': f['size'], 'primary': f['primary'],
                               'chunks': (f['size'] + CHUNK - 1) // CHUNK} for f in item['files']]}

    def file_chunk(self, token, index, part):
        with self.lock:
            item = self._request(token)
            if not 0 <= index < len(item['files']):
                raise ValueError('附件不存在。')
            file = item['files'][index]
            if not 0 <= part < (file['size'] + CHUNK - 1) // CHUNK:
                raise ValueError('附件分块不存在。')
            if 'path' in file:
                path = file['path'].resolve()
                if not path.is_relative_to(self.directory) or not path.is_file():
                    raise ValueError('附件已移动，请重新打开选区。')
                # Reject edits between the click and upload; never send a different file.
                stat = path.stat()
                stamp = (stat.st_mtime_ns, stat.st_size)
                if file.get('checked') != stamp:
                    if digest(path) != file['fingerprint']:
                        raise ValueError('正文已修改，请重新打开选区。')
                    file['checked'] = stamp
                with path.open('rb') as stream:
                    stream.seek(part * CHUNK)
                    data = stream.read(CHUNK)
            else:
                data = file['data'][part * CHUNK:(part + 1) * CHUNK]
            return {'data': base64.b64encode(data).decode('ascii')}

    def bind(self, token, url, primary_attached=False):
        url = conversation_url(url)
        if not url:
            raise ValueError('请在普通 ChatGPT 对话中发送，临时聊天不能绑定。')
        with self.lock:
            item = self._request(token)
            if item['url'] and item['url'] != url:
                raise ValueError('当前对话与这篇文献已绑定的对话不同。')
            lib = self._library()
            try:
                saved = lib.setting('chatgpt:' + item['rid'], {})
                existing = conversation_url(saved.get('url', ''))
                if existing and existing != url:
                    raise ValueError('这篇文献已绑定另一对话，请重新打开选区。')
                saved['url'] = url
                if primary_attached is True:
                    saved['fingerprint'] = item['fingerprint']
                lib.set_setting('chatgpt:' + item['rid'], saved)
                for pending in self.requests.values():
                    if pending['rid'] == item['rid']:pending['url'] = url
                item['completed'] = True
            finally:
                lib.close()
            return {'ok': True}

    def reset(self, rid):
        with self.lock:
            lib = self._library()
            try:
                lib.set_setting('chatgpt:' + rid, {})
            finally:
                lib.close()
            self.requests = {k: v for k, v in self.requests.items() if v['rid'] != rid}

    def _start(self):
        if self.server:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Do not log capability tokens or document contents.

            def handle_request(self):
                origin = self.headers.get('Origin', '')
                if (self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or
                        self.headers.get('X-PaperQuick') != '1' or
                        (origin and not re.fullmatch(r'chrome-extension://[a-p]{32}', origin))):
                    self.send_error(403)
                    return
                match = re.fullmatch(r'/handoff/([A-Za-z0-9_-]{43})(?:/file/(\d+)/(\d+)|/bind)?', self.path)
                if not match:
                    self.send_error(404)
                    return
                token, index, part = match.groups()
                try:
                    if self.command == 'GET' and index is not None:
                        result = bridge.file_chunk(token, int(index), int(part))
                    elif self.command == 'GET' and not self.path.endswith('/bind'):
                        result = bridge.payload(token)
                    elif self.command == 'POST' and self.path.endswith('/bind'):
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 < length <= 2048:
                            raise ValueError('无效请求。')
                        body = json.loads(self.rfile.read(length))
                        result = bridge.bind(token, body['url'], body.get('primaryAttached', False))
                    else:
                        raise ValueError('无效请求。')
                    status = 200
                except (ValueError, OSError, KeyError, TypeError, IndexError):
                    result, status = {'error': '请求未完成，选区可能已过期或文件已改变；请回阅读页重新打开。'}, 400
                raw = json.dumps(result, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(raw)

            do_GET = handle_request
            do_POST = handle_request

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True, name='paperquick-chat').start()

    def close(self):
        with self.lock:
            server, self.server = self.server, None
            self.requests.clear()
        if server:
            server.shutdown()
            server.server_close()
