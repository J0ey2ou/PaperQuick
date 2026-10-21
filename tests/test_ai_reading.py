"""Isolated AI API, web-bridge and hidden-widget checks; never call real providers."""
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from ai_providers import PROVIDERS, api_endpoint, web_route
from ai_reading import AIHistory, Cancelled, complete, context_prompt, protect_secret, load_profile, save_profile, get_key, read_context, save_note_snapshot
from chat_bridge import ChatBridge
from library_core import Library


class APIProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));cls.requests.append((self.path,body))
                if '/redirect/' in self.path:
                    self.send_response(307);self.send_header('Location','/json/chat/completions');self.end_headers();return
                if '/denied/' in self.path:
                    self.send_response(401);self.end_headers();self.wfile.write(b'Never expose service body or keys');return
                self.send_response(200)
                self.send_header('Content-Type','text/event-stream' if '/stream' in self.path else 'application/json');self.end_headers()
                if '/stream' not in self.path:
                    self.wfile.write(json.dumps({'choices':[{'message':{'content':'Fixture answer'}}]}).encode());return
                events=[{'choices':[{'delta':{'reasoning_content':'hidden reasoning'}}]}, {'choices':[{'delta':{'content':'First '}}]}, {'choices':[{'delta':{'content':'answer'}}]}]
                if '/stream-cut/' not in self.path:events.append({'choices':[{'delta':{},'finish_reason':'length' if '/stream-length/' in self.path else 'stop'}]})
                try:
                    for event in events:self.wfile.write(b'data: '+json.dumps(event).encode()+b'\n\n')
                    if '/stream-cut/' not in self.path:self.wfile.write(b'data: [DONE]\n\n')
                except (BrokenPipeError,ConnectionResetError):pass  # Expected client cancellation.
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()

    def request(self,path,**kwargs):return complete(self.base+path,'fixture-key','fixture-model',[{'role':'user','content':'fixture question'}],**kwargs)

    def test_json_fallback_and_stream_content(self):
        self.assertEqual(self.request('/json',stream=False),'Fixture answer')
        chunks=[];self.assertEqual(self.request('/stream',on_delta=chunks.append),'First answer');self.assertEqual(chunks,['First ','answer'])

    def test_redirect_never_receives_auth_and_errors_are_safe(self):
        before=len(self.requests)
        with self.assertRaisesRegex(ValueError,'307'):self.request('/redirect')
        self.assertEqual(len(self.requests),before+1)
        with self.assertRaisesRegex(ValueError,'密钥无效'):self.request('/denied')

    def test_incomplete_and_length_limited_streams_are_not_success(self):
        with self.assertRaisesRegex(ValueError,'未完成'):self.request('/stream-cut')
        with self.assertRaisesRegex(ValueError,'长度限制'):self.request('/stream-length')

    def test_cancel_before_and_during_stream(self):
        cancel=threading.Event();cancel.set();before=len(self.requests)
        with self.assertRaises(Cancelled):self.request('/stream',cancel=cancel)
        self.assertEqual(len(self.requests),before)
        cancel.clear()
        with self.assertRaises(Cancelled):self.request('/stream',cancel=cancel,on_delta=lambda _:cancel.set())

    def test_invalid_model_key_and_payload_do_not_call_service(self):
        before=len(self.requests)
        for model,key in [('', 'x'),('m','x\ninjected')]:
            with self.assertRaises(ValueError):complete(self.base,key,model,[])
        self.assertEqual(len(self.requests),before)


class AIStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.lib=Library(self.base/'store')
        self.source=self.base/'fixture.txt';self.source.write_text('Selected evidence. Other context.','utf-8')
        self.rid=self.lib.import_document(self.source);self.attachment=self.lib.primary_attachment(self.rid)
        self.anchor={'page':0,'rect':[.1,.1,.4,.3],'quote':'Selected evidence','attachment':self.attachment['id'],'title':'Fixture','question':'Explain'}
        self.bridge=ChatBridge(self.lib.root)

    def tearDown(self):self.bridge.close();self.lib.close();self.tmp.cleanup()

    def test_provider_routes_and_endpoints_reject_impostors(self):
        targets={'chatgpt':'/c/12345678','doubao':'/chat/12345678','deepseek':'/a/chat/s/12345678','gemini':'/app/12345678','qwen':'/c/12345678','kimi':'/chat/12345678'}
        from urllib.parse import urlsplit
        for name,path in targets.items():
            origin='https://'+urlsplit(PROVIDERS[name]['web']).netloc
            self.assertEqual(web_route(origin+path+'#private',name,True),origin+path)
            self.assertFalse(web_route(origin+'.evil.test'+path,name,True))
            self.assertTrue(api_endpoint(PROVIDERS[name]['api']).endswith('/chat/completions'))
        for address in ['http://remote.test/v1','https://key@host.test/v1','https://host.test/v1?token=x','https://host.test/v1#x']:
            with self.assertRaises(ValueError):api_endpoint(address)

    def test_secret_encrypted_bound_to_provider_and_exact_endpoint(self):
        encrypted=protect_secret('fixture-private-key');self.assertNotIn('fixture-private-key',encrypted)
        self.assertEqual(protect_secret(encrypted,True),'fixture-private-key')
        save_profile(self.lib.root,'deepseek','https://api.deepseek.com/v1','fixture-model','fixture-private-key')
        self.assertEqual(get_key(self.lib.root,'deepseek','https://api.deepseek.com/v1'),'fixture-private-key')
        self.assertNotIn('fixture-private-key',self.lib.db.execute("SELECT value FROM config WHERE key LIKE 'ai-secret:%'").fetchone()[0])
        with self.assertRaises(ValueError):get_key(self.lib.root,'deepseek','https://other.test/v1')
        save_profile(self.lib.root,'deepseek','https://api.deepseek.com/v1','new-model',None)
        self.assertEqual(get_key(self.lib.root,'deepseek','https://api.deepseek.com/v1'),'fixture-private-key')
        save_profile(self.lib.root,'deepseek','https://api.deepseek.com/v1','new-model','')
        with self.assertRaises(ValueError):get_key(self.lib.root,'deepseek','https://api.deepseek.com/v1')

    def test_history_is_scoped_and_old_requests_cannot_overwrite_new_chat(self):
        store=AIHistory(self.lib.root,self.rid,'deepseek','https://api.deepseek.com/v1','m');old=store.load()
        store.append(old,'p','answer',self.anchor,'deepseek','Explain')
        self.assertEqual(len(store.load()['turns']),1)
        with self.assertRaisesRegex(ValueError,'另一处更新'):store.append(old,'p','stale',self.anchor,'deepseek','Explain')
        store.reset()
        with self.assertRaises(ValueError):store.append(old,'p','stale',self.anchor,'deepseek','Explain')
        self.assertFalse(AIHistory(self.lib.root,self.rid,'kimi','https://api.moonshot.cn/v1','m').load()['turns'])

    def test_web_reply_inbox_all_six_provider_bindings_stay_separate(self):
        targets={'chatgpt':'https://chatgpt.com/c/12345678','doubao':'https://www.doubao.com/chat/12345678','deepseek':'https://chat.deepseek.com/a/chat/s/12345678','gemini':'https://gemini.google.com/app/12345678','qwen':'https://chat.qwen.ai/c/12345678','kimi':'https://www.kimi.com/chat/12345678'}
        for provider,url in targets.items():
            link=self.bridge.prepare(self.rid,quote='Explain',anchor=self.anchor,provider=provider,reply_mode='ai',include_document=False)
            token=link.split('#paperquick=')[1].split('.',1)[1]
            self.assertFalse(self.bridge.payload(token)['files']);self.assertEqual(self.bridge.payload(token)['provider'],provider)
            self.bridge.bind(token,url)
            self.assertTrue(self.bridge.reply(token,url,'Answer from '+provider)['ok'])
            self.assertTrue(self.bridge.reply(token,url,'Answer from '+provider)['duplicate'])
            self.assertEqual(len(self.lib.setting('ai-web-replies:'+self.rid+':'+provider)),1)
        self.assertFalse(self.lib.get(self.rid).get('annotations'))
        self.bridge.reset(self.rid,'deepseek')
        self.assertTrue(self.lib.setting('chatgpt:'+self.rid)['url'])

    def test_notes_and_source_marker_commit_once_and_retain_other_annotations(self):
        original={'id':'other','attachment':self.attachment['id'],'page':0,'rect':[0,0,0,0],'text':'Keep'}
        self.lib.merge_annotations(self.rid,[original])
        marker={'id':'ai','ai_note_key':'stable','attachment':self.attachment['id'],'page':0,'rect':[.1,.1,.4,.3],'text':'Answer'}
        result,added=save_note_snapshot(self.lib,self.rid,marker,'Original notes\nAI answer',[],{})
        self.assertTrue(added);self.assertEqual(len(result),2)
        _,added=save_note_snapshot(self.lib,self.rid,marker,'Duplicated!',[],{})
        self.assertFalse(added);self.assertEqual(self.lib.get(self.rid)['notes'],'Original notes\nAI answer')
        marker['attachment']='removed';marker['ai_note_key']='new'
        with self.assertRaises(ValueError):save_note_snapshot(self.lib,self.rid,marker,'Should rollback',[],{})
        self.assertEqual(self.lib.get(self.rid)['notes'],'Original notes\nAI answer')

    def test_prompt_validation_full_text_and_context(self):
        self.assertIn('第 3 页',context_prompt('Title','quote','Explain',2))
        with self.assertRaises(ValueError):context_prompt('Title','quote','Explain',2,'','整篇文本')
        with self.assertRaises(ValueError):context_prompt('Title','quote','Explain',2,'x'*100001,'整篇文本')
        self.assertIn('Other context',read_context(self.source,[0],True))

    def test_pdf_context_keeps_middle_pages_and_cross_page_sources(self):
        from test_reader import text_pdf
        from pypdf import PdfReader,PdfWriter
        short=self.base/'short.pdf';text_pdf(short);reader=PdfReader(short);writer=PdfWriter()
        for i in range(101):writer.add_page(reader.pages[0] if i!=50 else reader.pages[1])
        long=self.base/'long.pdf'
        with long.open('wb') as out:writer.write(out)
        whole=read_context(long,[0],True)
        self.assertIn('[阅读器第 51 页]',whole);self.assertIn('References',whole)
        selected=read_context(long,[49,50],False);self.assertIn('[阅读器第 50 页]',selected);self.assertIn('[阅读器第 51 页]',selected)


class AIHiddenUITests(unittest.TestCase):
    def setUp(self):
        AIStorageTests.setUp(self);self.root=tk.Tk();self.root.withdraw()
        from reader_ui import ReaderPage
        self.reader=ReaderPage(self.root,self.lib.root,lambda *args:None,lambda *args:None)
        self.reader.open(self.rid)
        self.panel=self.reader.ai_panel
        self.reader.last_selection=dict(self.anchor,regions=[{'page':0,'rect':self.anchor['rect']}]);self.reader.context_page=0

    def tearDown(self):
        self.reader.close();self.root.destroy();AIStorageTests.tearDown(self)

    def wait(self,predicate):
        deadline=time.monotonic()+8
        while not predicate() and time.monotonic()<deadline:self.root.update();time.sleep(.01)
        self.assertTrue(predicate())

    def test_api_question_answer_note_and_dedup_end_to_end(self):
        p=self.panel;p.mode.set('API');p.provider.set('DeepSeek');p.scope.set('仅选文');p.select('解释这段')
        profile={'endpoint':'https://fixture.invalid/v1','model':'fixture','stream':True}
        with patch('ai_reading_ui.load_profile',return_value=profile),patch('ai_reading_ui.get_key',return_value='fixture-key'),patch('ai_reading_ui.complete',return_value='Completed fixture answer'):
            p.send();self.wait(lambda:not p.active)
            self.assertIn('Completed fixture answer',p.answer.get('1.0','end'))
            p.save_note();p.save_note()
        record=self.lib.get(self.rid);self.assertEqual(record['notes'].count('Completed fixture answer'),1)
        self.assertEqual(len([a for a in record['annotations'] if a.get('kind')=='AI 笔记']),1)

    def test_cancel_does_not_save_partial_or_allow_cross_document_notes(self):
        p=self.panel;p.mode.set('API');p.scope.set('仅选文');p.select()
        finish=threading.Event()
        def blocked(*args,**kwargs):finish.wait(2);return 'Should not persist'
        profile={'endpoint':'https://fixture.invalid/v1','model':'fixture','stream':True}
        with patch('ai_reading_ui.load_profile',return_value=profile),patch('ai_reading_ui.get_key',return_value='fixture-key'),patch('ai_reading_ui.complete',side_effect=blocked):
            p.send();p.stop();finish.set();self.wait(lambda:not p.active)
            self.assertIsNone(p.answer_turn);self.assertFalse(p.history_store().load()['turns'])
        self.assertFalse(self.lib.get(self.rid)['notes'])

    def test_web_handoff_waits_for_user_and_returns_to_panel(self):
        p=self.panel;p.mode.set('网页账号');p.provider.set('Gemini');p.scope.set('仅选文');p.select('总结要点')
        with patch('webbrowser.open',return_value=True) as browser:
            p.send();self.wait(lambda:not p.active);browser.assert_called_once()
        bridge=self.reader.chat_bridge();token=next(reversed(bridge.requests))
        self.assertEqual(bridge.payload(token)['provider'],'gemini')
        url='https://gemini.google.com/app/12345678';bridge.bind(token,url);bridge.reply(token,url,'Web fixture answer')
        p.last_inbox_check=0;self.wait(lambda:p.answer_turn is not None)
        p.save_note();self.assertIn('Web fixture answer',self.lib.get(self.rid)['notes'])
