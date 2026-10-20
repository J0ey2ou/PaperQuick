"""Loopback and persistence checks; no browser, desktop or clipboard access."""
import base64
import json
from pathlib import Path
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from PIL import Image
from chat_bridge import ChatBridge, CHUNK, TTL, conversation_url
from library_core import Library


class ChatBridgeTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'build' / 'chat-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.tmp.name)
        self.lib = Library(self.root / 'store')
        source = self.root / 'paper.txt'
        source.write_text('Fictional research paper.\n' * 30000, encoding='utf-8')
        self.rid = self.lib.import_document(source)
        other = self.root / 'other.txt'
        other.write_text('Other paper', encoding='utf-8')
        self.other = self.lib.import_document(other)
        self.bridge = ChatBridge(self.lib.root)

    def tearDown(self):
        self.bridge.close()
        self.lib.close()
        self.tmp.cleanup()

    def prepare(self, rid=None, **kwargs):
        url = self.bridge.prepare(rid or self.rid, quote=kwargs.pop('quote', 'Selected text'), **kwargs)
        descriptor = url.split('#paperquick=')[1]
        return url, descriptor.split('.', 1)[1]

    def test_first_handoff_is_scoped_and_reassembles_document_and_image(self):
        self.assertIsNone(self.bridge.server)
        url, token = self.prepare(image=Image.new('RGB', (80, 60), '#2389e8'), page=2)
        self.assertTrue(url.startswith('https://chatgpt.com/#paperquick='))
        self.assertNotIn('Selected text', url)
        payload = self.bridge.payload(token)
        self.assertIn('第 3 页', payload['prompt'])
        self.assertEqual(len(payload['files']), 2)
        self.assertNotIn('path', json.dumps(payload))
        for index, file in enumerate(payload['files']):
            chunks = [base64.b64decode(self.bridge.file_chunk(token, index, part)['data'])
                      for part in range(file['chunks'])]
            self.assertEqual(sum(map(len, chunks)), file['size'])
            if index == 0:
                self.assertGreater(len(chunks), 1)
                self.assertEqual(b''.join(chunks), (self.lib.root / self.lib.primary_attachment(self.rid)['path']).read_bytes())
            else:
                self.assertTrue(chunks[0].startswith(b'\x89PNG'))

    def test_binding_persists_per_paper_skips_uploaded_primary_and_survives_restart(self):
        _, token = self.prepare()
        target = 'https://chatgpt.com/c/12345678-abcd-1234'
        self.bridge.bind(token, target + '?ignored=1#secret', True)
        self.bridge.close()
        self.bridge = ChatBridge(self.lib.root)
        url, token = self.prepare()
        self.assertTrue(url.startswith(target + '#'))
        self.assertEqual(self.bridge.payload(token)['files'], [])
        other_url, other_token = self.prepare(self.other)
        self.assertTrue(other_url.startswith('https://chatgpt.com/#'))
        self.assertEqual(len(self.bridge.payload(other_token)['files']), 1)
        self.assertNotEqual(self.bridge.payload(other_token)['key'], self.bridge.payload(token)['key'])

    def test_unconfirmed_attachment_and_edited_document_are_not_skipped(self):
        _, token = self.prepare()
        target = 'https://chatgpt.com/c/12345678-abcd'
        self.bridge.bind(token, target, False)
        _, next_token = self.prepare()
        self.assertEqual(len(self.bridge.payload(next_token)['files']), 1)
        self.bridge.bind(next_token, target, True)
        path = self.lib.root / self.lib.primary_attachment(self.rid)['path']
        path.write_text('Changed document', encoding='utf-8')
        _, changed_token = self.prepare()
        self.assertEqual(len(self.bridge.payload(changed_token)['files']), 1)
        with self.assertRaises(ValueError): self.bridge.file_chunk(next_token, 0, 0)

    def test_bad_urls_conflicting_binding_expiry_and_reset(self):
        for url in ['https://evil.test/c/12345678', 'https://chatgpt.com.evil.test/c/12345678',
                    'http://chatgpt.com/c/12345678', 'https://chatgpt.com/',
                    'https://chatgpt.com/g/custom', 'https://user@chatgpt.com/c/12345678']:
            self.assertEqual(conversation_url(url), '')
        _, first = self.prepare()
        _, pending = self.prepare()
        target = 'https://chatgpt.com/c/12345678-abcd'
        self.bridge.bind(first, target, True)
        self.assertEqual(self.bridge.payload(pending)['url'], target)
        with self.assertRaises(ValueError): self.bridge.bind(pending, 'https://chatgpt.com/c/98765432-abcd', True)
        self.bridge.requests[first]['created'] = time.monotonic() - TTL - 1
        with self.assertRaises(ValueError): self.bridge.payload(first)
        self.bridge.reset(self.rid)
        with self.assertRaises(ValueError): self.bridge.payload(pending)
        url, _ = self.prepare()
        self.assertTrue(url.startswith('https://chatgpt.com/#'))

    def test_http_requires_capability_host_and_non_simple_request_header(self):
        _, token = self.prepare()
        port = self.bridge.server.server_port
        self.assertEqual(self.bridge.server.server_address[0], '127.0.0.1')
        opener = build_opener(ProxyHandler({}))
        url = f'http://127.0.0.1:{port}/handoff/{token}'
        for headers in [{}, {'X-PaperQuick': '1', 'Origin': 'https://chatgpt.com'},
                        {'X-PaperQuick': '1', 'Host': 'evil.test'}]:
            with self.assertRaises(HTTPError) as error: opener.open(Request(url, headers=headers), timeout=3)
            self.assertEqual(error.exception.code, 403)
        with opener.open(Request(url, headers={'X-PaperQuick': '1'}), timeout=3) as response:
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertIn('Selected text', json.load(response)['prompt'])
        raw = json.dumps({'url': 'https://chatgpt.com/c/12345678-abcd', 'primaryAttached': True}).encode()
        with opener.open(Request(url + '/bind', data=raw, headers={'X-PaperQuick': '1'}), timeout=3) as response:
            self.assertTrue(json.load(response)['ok'])
        with self.assertRaises(ValueError): self.bridge.file_chunk(token, -1, 0)
        with self.assertRaises(ValueError): self.bridge.file_chunk(token, 0, 100)

    def test_completed_handoffs_do_not_exhaust_pending_capacity(self):
        target='https://chatgpt.com/c/12345678-abcd'
        for _ in range(20):
            _,token=self.prepare()
            self.bridge.bind(token,target,True)
        self.assertLessEqual(len(self.bridge.requests),1)

    def test_connection_page_shows_setup_and_escapes_selected_text(self):
        url,token=self.prepare(quote='Selected </textarea><script>bad()</script>')
        local=self.bridge.open_url(url)
        self.assertEqual(local,f'http://127.0.0.1:{self.bridge.server.server_port}/handoff/{token}/open')
        page=self.bridge.connection_page(token).decode('utf-8')
        self.assertIn('paperquick-handoff',page)
        self.assertIn('加载解压缩的扩展',page)
        self.assertNotIn('<script>bad()</script>',page)
        self.assertIn('&lt;script&gt;bad()',page)
        self.assertEqual(self.bridge.status(token)['state'],'waiting-extension')
        self.bridge.update_status(token,'text-ready')
        self.assertEqual(self.bridge.status(token)['state'],'text-ready')
        with self.assertRaises(ValueError):self.bridge.update_status(token,'anything')
        with self.assertRaises(ValueError):self.bridge.open_url(url.replace('chatgpt.com','evil.test'))


if __name__ == '__main__': unittest.main()
