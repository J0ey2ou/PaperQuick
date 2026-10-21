"""User-initiated ChatGPT handoffs. No browser, clipboard or service at import time."""
import base64
import io
import html
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from library_core import Library, digest, display_name
from ai_providers import PROVIDERS, web_route

MAX_FILE = 24 * 1024 * 1024
CHUNK = 384 * 1024
TTL = 30 * 60
REPLY_TTL = 24 * 60 * 60


def conversation_url(value, provider='chatgpt'):
    """Only personal ChatGPT conversation URLs; never persist fragments/tokens."""
    return web_route(value, provider, conversation=True)


class ChatBridge:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.lock = threading.RLock()
        self.requests = {}
        self.reply_sessions = {}
        self.server = None

    def _library(self):
        return Library(self.directory)

    def prepare(self, rid, quote='', image=None, page=0, whole_document=False, anchor=None,
                provider='chatgpt', include_document=True, attachment_id=None, reply_mode='annotation'):
        if provider not in PROVIDERS or not PROVIDERS[provider]['web']:raise ValueError('请选择支持的 AI 网页。')
        if not quote.strip() and image is None:
            raise ValueError('请先选中文字，或使用“框选图片供 ChatGPT 讨论”。')
        if len(quote) > 100000:
            raise ValueError('选中文字过长，请缩小选区。')
        with self.lock:
            lib = self._library()
            try:
                record = lib.get(rid)
                attachment = next((a for a in record['attachments'] if a['id']==attachment_id),None) if attachment_id else lib.primary_attachment(rid)
                if not attachment:
                    raise ValueError('请先为这篇文献添加正文。')
                path = (self.directory / attachment['path']).resolve()
                if not path.is_relative_to(self.directory) or not path.is_file():
                    raise ValueError('正文文件不存在或不在文献库内。')
                if path.suffix.lower() not in ('.pdf', '.docx', '.txt', '.md'):
                    raise ValueError('请先将正文转换为 PDF 或 DOCX，再交给 ChatGPT。')
                if include_document and path.stat().st_size > MAX_FILE:
                    raise ValueError('网页接入目前支持 24 MB 以内的正文，请先压缩文件。')
                fingerprint = digest(path)
                namespace = lib.setting('chatgpt_library_id')
                if not namespace:
                    namespace = secrets.token_hex(16)
                    lib.set_setting('chatgpt_library_id', namespace)
                saved = lib.setting(provider + ':' + rid, {})
                if not isinstance(saved, dict):saved = {}
                target = conversation_url(saved.get('url', ''), provider)
                files = []
                if include_document and (not target or saved.get('fingerprint') != fingerprint):
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
                prompt = f'文献：{display_name(record)}\n' + ('通篇解读\n\n' if whole_document else f'第 {page + 1} 页\n\n')
                prompt += quote.strip() if quote.strip() else '请结合文献讨论所附选区图片。'
                token = secrets.token_urlsafe(32)
                now = time.monotonic()
                self.requests = {k: v for k, v in self.requests.items() if now - v['created'] < TTL and not v.get('completed')}
                if len(self.requests) >= 16:
                    raise ValueError('待处理选区过多，请先完成已打开的 ChatGPT 对话。')
                anchor=anchor or {'page':page,'rect':[.06,.06,.06,.06],'quote':quote[:10000]}
                rect=anchor.get('rect',[.06,.06,.06,.06])
                if len(rect)!=4 or any(not isinstance(v,(int,float)) or not 0<=v<=1 for v in rect):raise ValueError('选区位置无效。')
                if not isinstance(page,int) or not 0<=page<100000:raise ValueError('选区页码无效。')
                self.reply_sessions={k:v for k,v in self.reply_sessions.items() if now-v['created']<REPLY_TTL}
                if len(self.reply_sessions)>=64:raise ValueError('回存连接过多，请重新启动软件后重试。')
                self.reply_sessions[token]={'rid':rid,'attachment':attachment['id'],'attachment_sha':attachment['sha'],'created':now,'url':target,
                    'provider':provider,'reply_mode':reply_mode,
                    'anchor':{'page':page,'rect':list(rect),'quote':str(anchor.get('quote',quote))[:20000], 'attachment':attachment['id'],
                              'title':record['title'], 'question':str(anchor.get('question',''))[:10000], 'regions':anchor.get('regions',[])}}
                self.requests[token] = {'rid': rid, 'provider':provider, 'reply_mode':reply_mode, 'key': namespace + ':' + rid + (':' + provider if provider!='chatgpt' else ''),
                                        'url': target, 'prompt': prompt, 'files': files,
                                        'created': now, 'fingerprint': fingerprint,
                                        'state': 'waiting-extension', 'detail': ''}
                try:
                    self._start()
                except Exception:
                    self.requests.pop(token, None)
                    raise
                return (target or PROVIDERS[provider]['web']) + f'#paperquick={self.server.server_port}.{token}'
            finally:
                lib.close()

    def open_url(self, chat_url):
        """Start on a local connection page so a missing extension is visible."""
        parsed=urlsplit(chat_url)
        match=re.fullmatch(r'paperquick=(\d+)\.([A-Za-z0-9_-]{43})',parsed.fragment)
        if not match or not web_route(chat_url):raise ValueError('无效的 AI 选区地址。')
        port,token=match.groups()
        if not self.server or int(port)!=self.server.server_port:raise ValueError('本地连接已关闭，请重新打开选区。')
        self._request(token)
        return f'http://127.0.0.1:{port}/handoff/{token}/open'

    def status(self, token):
        with self.lock:
            item=self._request(token)
            return {'state':item.get('state','waiting-extension'),'detail':item.get('detail','')}

    def update_status(self, token, state, detail=''):
        allowed={'extension-connected','waiting-composer','text-ready','uploading','ready','upload-error','error','bound'}
        if state not in allowed or not isinstance(detail,str) or len(detail)>600:raise ValueError('无效的连接状态。')
        with self.lock:
            item=self._request(token);item['state']=state;item['detail']=detail
        return {'ok':True}

    def connection_page(self,token):
        with self.lock:
            item=self._request(token)
            target=(item['url'] or PROVIDERS[item['provider']]['web'])+f'#paperquick={self.server.server_port}.{token}'
            import sys
            extension=(Path(getattr(sys,'_MEIPASS',Path(__file__).parent)) if sys.platform=='darwin' else Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent)/'browser-extension'
            page=('''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="paperquick-handoff" content="1"><title>文献直达 · 连接 ChatGPT</title>
<style>body{max-width:760px;margin:55px auto;padding:0 24px;color:#19314b;font:16px/1.7 system-ui;background:#f5f8fc}section{padding:22px;background:white;border:1px solid #d6e2ef;border-radius:12px;margin:18px 0}code{overflow-wrap:anywhere}textarea{box-sizing:border-box;width:100%;min-height:140px;padding:12px}a{color:#1767c5}</style>
<h1>连接 ChatGPT</h1><section><p id="status">正在检测浏览器扩展；连接后自动进入 ChatGPT 并准备选区。</p>
<div id="setup"><p>首次使用需要在当前浏览器加载文献直达扩展。仅打开 ChatGPT 网站不能让其他程序直接填写内容或附加文献。</p>
<ol><li>在地址栏打开 <code>edge://extensions</code>（Chrome 使用 <code>chrome://extensions</code>）。</li>
<li>开启开发人员模式，点击“加载解压缩的扩展”，选择下面的文件夹。</li>
<li>如果已有旧扩展，先重新加载，并允许访问 ChatGPT 与本机地址；随后刷新本页。</li></ol>
<p><code>'''+html.escape(str(extension))+'''</code></p></div></section>
<section><p>本次选中文字已在本机准备好；扩展只会在这次主动操作后交给 ChatGPT。</p><textarea readonly>__PAPERQUICK_PROMPT__</textarea>
<p><a href="'''+html.escape(target,quote=True)+'''">手动打开 ChatGPT</a> · 需要保持文献直达运行，连接 30 分钟内有效。</p></section>
<script>setTimeout(()=>{document.querySelector('#status').textContent='尚未连接扩展，请完成下面的首次设置后刷新本页。'},7000);</script></html>''')
            return page.replace('ChatGPT',html.escape(PROVIDERS[item['provider']]['name'])).replace('__PAPERQUICK_PROMPT__',html.escape(item['prompt'])).encode('utf-8')

    def _request(self, token):
        item = self.requests.get(token)
        if not item or time.monotonic() - item['created'] >= TTL:
            self.requests.pop(token, None)
            raise ValueError('选区已过期，请回阅读页重新右键打开。')
        return item

    def payload(self, token):
        with self.lock:
            item = self._request(token)
            return {'key': item['key'], 'url': item['url'], 'provider':item['provider'], 'home':PROVIDERS[item['provider']]['web'], 'replyMode':item['reply_mode'], 'prompt': item['prompt'],
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
        with self.lock:
            item = self._request(token)
            provider=item['provider'];url=conversation_url(url,provider)
            if not url:raise ValueError('请先在普通对话中发送消息，再绑定文献。')
            if item['url'] and item['url'] != url:
                raise ValueError('当前对话与这篇文献已绑定的对话不同。')
            lib = self._library()
            try:
                saved = lib.setting(provider + ':' + item['rid'], {})
                existing = conversation_url(saved.get('url', ''),provider)
                if existing and existing != url:
                    raise ValueError('这篇文献已绑定另一对话，请重新打开选区。')
                saved['url'] = url
                if primary_attached is True:
                    saved['fingerprint'] = item['fingerprint']
                lib.set_setting(provider + ':' + item['rid'], saved)
                for pending in self.requests.values():
                    if pending['rid'] == item['rid'] and pending['provider']==provider:pending['url'] = url
                self.reply_sessions[token]['url']=url
                item['completed'] = True
                item['state']='bound'
            finally:
                lib.close()
            return {'ok': True}

    def reset(self, rid, provider='chatgpt'):
        with self.lock:
            lib = self._library()
            try:
                lib.set_setting(provider + ':' + rid, {})
            finally:
                lib.close()
            self.requests = {k: v for k, v in self.requests.items() if v['rid'] != rid or v['provider']!=provider}
            self.reply_sessions={k:v for k,v in self.reply_sessions.items() if v['rid']!=rid or v['provider']!=provider}

    def require_document_upload(self,rid):
        """Keep the existing conversation but prepare the main file again."""
        lib=self._library()
        try:
            saved=lib.setting('chatgpt:'+rid,{})
            if not isinstance(saved,dict):saved={}
            saved.pop('fingerprint',None);lib.set_setting('chatgpt:'+rid,saved)
        finally:lib.close()

    def reply(self,token,url,text,message_id=''):
        if not isinstance(text,str) or not text.strip() or len(text)>100000:raise ValueError('回复内容或对话地址无效。')
        if not isinstance(message_id,str) or len(message_id)>200:raise ValueError('回复标识无效。')
        with self.lock:
            session=self.reply_sessions.get(token)
            if not session or time.monotonic()-session['created']>=REPLY_TTL:raise ValueError('回存连接已过期，请回阅读器重新连接 ChatGPT。')
            provider=session['provider'];url=conversation_url(url,provider)
            if not url:raise ValueError('回复对话地址无效。')
            lib=self._library()
            try:
                saved=lib.setting(provider+':'+session['rid'],{})
                if url!=session['url'] or conversation_url(saved.get('url',''),provider)!=url:raise ValueError('该对话与文献不匹配，请重新连接。')
                attachment=next((a for a in lib.get(session['rid'])['attachments'] if a['id']==session['attachment']),None)
                if not attachment or attachment['sha']!=session['attachment_sha']:raise ValueError('文献正文已改变，请重新连接以确认批注位置。')
                if session['reply_mode']=='ai':
                    import hashlib,uuid
                    key=hashlib.sha256((url+'\n'+message_id+'\n'+text+'\n'+json.dumps(session['anchor'],sort_keys=True)).encode()).hexdigest()
                    setting='ai-web-replies:'+session['rid']+':'+provider
                    with lib.db:
                        lib.db.execute('BEGIN IMMEDIATE');turns=lib.setting(setting,[])
                        if any(t['id']==key for t in turns):return {'ok':True,'duplicate':True}
                        turn={'id':key,'answer':text.strip(),'anchor':session['anchor'],'provider':provider,'question':session['anchor']['question'],'url':url}
                        turns.append(turn)
                        if len(json.dumps(turns,ensure_ascii=False))>2000000:raise ValueError('网页回答历史过长，请整理后重试。')
                        lib.db.execute('INSERT OR REPLACE INTO config VALUES(?,?)',(setting,json.dumps(turns,ensure_ascii=False)))
                    return {'ok':True,'duplicate':False}
                return lib.append_chat_reply(session['rid'],session['attachment'],session['anchor'],text.strip(),url,message_id)
            finally:lib.close()

    def _start(self):
        if self.server:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Do not log capability tokens or document contents.

            def handle_request(self):
                origin = self.headers.get('Origin', '')
                opening=re.fullmatch(r'/handoff/([A-Za-z0-9_-]{43})/open',self.path)
                if opening and self.command=='GET' and self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}' and not origin:
                    try:raw=bridge.connection_page(opening.group(1))
                    except ValueError:self.send_error(410);return
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
                    self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
                    self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
                    self.end_headers();self.wfile.write(raw);return
                if (self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or
                        self.headers.get('X-PaperQuick') != '1' or
                        (origin and not re.fullmatch(r'chrome-extension://[a-p]{32}', origin))):
                    self.send_error(403)
                    return
                match = re.fullmatch(r'/handoff/([A-Za-z0-9_-]{43})(?:/file/(\d+)/(\d+)|/bind|/status|/reply)?', self.path)
                if not match:
                    self.send_error(404)
                    return
                token, index, part = match.groups()
                try:
                    if self.command == 'GET' and index is not None:
                        result = bridge.file_chunk(token, int(index), int(part))
                    elif self.command=='GET' and self.path.endswith('/status'):
                        result=bridge.status(token)
                    elif self.command == 'GET' and not self.path.endswith('/bind'):
                        result = bridge.payload(token)
                    elif self.command == 'POST' and self.path.endswith('/bind'):
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 < length <= 2048:
                            raise ValueError('无效请求。')
                        body = json.loads(self.rfile.read(length))
                        result = bridge.bind(token, body['url'], body.get('primaryAttached', False))
                    elif self.command=='POST' and self.path.endswith('/status'):
                        length=int(self.headers.get('Content-Length','0'))
                        if not 0<length<=4096:raise ValueError('无效请求。')
                        body=json.loads(self.rfile.read(length));result=bridge.update_status(token,body['state'],body.get('detail',''))
                    elif self.command=='POST' and self.path.endswith('/reply'):
                        length=int(self.headers.get('Content-Length','0'))
                        if not 0<length<=420000:raise ValueError('回复过长。')
                        body=json.loads(self.rfile.read(length));result=bridge.reply(token,body['url'],body['text'],body.get('messageId',''))
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
            self.reply_sessions.clear()
        if server:
            server.shutdown()
            server.server_close()
