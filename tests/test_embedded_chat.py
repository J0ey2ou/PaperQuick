"""Native WebView2 in an unmapped Tk parent; all web resources are local fixtures."""
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from chat_bridge import ChatBridge
from library_core import Library


class EmbeddedUiTests(unittest.TestCase):
    def test_reveal_preserves_draft_and_rejected_handoff_keeps_current_url(self):
        from embedded_chat import EmbeddedChat
        root=tk.Tk();root.withdraw()
        try:
            notebook=ttk.Notebook(root);frame=ttk.Frame(notebook);notebook.add(frame,text='AI')
            bridge=Mock();bridge.open_url.side_effect=lambda url:url
            view=EmbeddedChat(SimpleNamespace(reader=SimpleNamespace(notebook=notebook,chat_bridge=lambda:bridge),frame=frame))
            process=Mock();process.poll.return_value=None;view.process=process
            view.url='https://chatgpt.com/#accepted';view.pending_url='https://chatgpt.com/#rejected'
            view.events.put({'state':'error','detail':'已有草稿'});view.poll();view.reveal()
            process.stdin.write.assert_called_once_with('{"type":"sync-host"}\n')
            with patch('webbrowser.open') as browser:view.external();browser.assert_called_once_with(view.url)
            view.events.put({'state':'opened','detail':'已打开','url':'https://chatgpt.com/#next'});view.poll()
            self.assertEqual(view.url,'https://chatgpt.com/#next')
            view.close();self.assertEqual(notebook.tab(view.tab,'state'),'hidden')
        finally:root.destroy()


@unittest.skipUnless(os.name=='nt','Native Windows component')
class EmbeddedTests(unittest.TestCase):
    def test_hidden_native_roundtrip_upload_bind_reply_and_reuse(self):
        self.run_provider('chatgpt')

    def test_hidden_generic_adapter_roundtrip(self):
        self.run_provider('deepseek')

    def run_provider(self,provider):
        root_path=Path(__file__).resolve().parents[1]
        base=root_path/'build/embedded-tests';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            folder=Path(temporary);source=folder/'fixture.txt';source.write_text('Isolated fixture paper','utf-8')
            lib=Library(folder/'store');rid=lib.import_document(source);bridge=ChatBridge(lib.root)
            fixture=folder/'fixture.html';fixture.write_text('''<!doctype html><main><form><div id="prompt-textarea" class="ProseMirror" contenteditable="true" role="textbox" style="min-height:40px"></div><div id="attachments"></div></form><input type="file">
<script>const editor=document.querySelector('[contenteditable]');document.querySelector('input').onchange=e=>{for(const file of e.target.files){const chip=document.createElement('div');chip.dataset.testid='attachment';chip.dataset.uploadState='complete';chip.textContent=file.name;document.querySelector('#attachments').append(chip);}};
window.pqFixtureSubmit=()=>{const turn=document.createElement('article');turn.dataset.testid='conversation-turn-1';const user=document.createElement('div');user.dataset.messageAuthorRole='user';user.textContent=editor.innerText;turn.append(user,...document.querySelector('#attachments').children);document.querySelector('main').prepend(turn);editor.replaceChildren();history.pushState(null,'','/c/12345678-native-fixture');const answer=document.createElement('div');answer.dataset.messageAuthorRole='assistant';answer.innerHTML='<div class="markdown">Native fixture answer</div>';turn.append(answer);};</script></main>'''.replace('/c/12345678-native-fixture','/a/chat/s/12345678-native-fixture' if provider=='deepseek' else '/c/12345678-native-fixture'),'utf-8')
            root=tk.Tk();root.withdraw();parent=tk.Frame(root);parent.place(x=0,y=0,width=900,height=750);root.update_idletasks()
            events=queue.Queue();process=None
            try:
                environment=dict(os.environ,PAPERQUICK_EMBEDDED_FIXTURE=str(fixture),WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--disable-background-networking --disable-component-update --no-first-run')
                process=subprocess.Popen([str(root_path/'embedded-browser/EmbeddedChat.exe'),str(parent.winfo_id()),str(folder/'profile'),str(root_path/'browser-extension')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW,env=environment)
                def read():
                    for line in process.stdout:events.put(json.loads(line))
                threading.Thread(target=read,daemon=True).start()
                def send(value):process.stdin.write(json.dumps(value)+'\n');process.stdin.flush()
                def mounted_children():
                    # Inspect only our hidden fixture's HWNDs. No screen capture,
                    # input simulation, foreground operations or real AI account.
                    import ctypes
                    from ctypes import wintypes
                    user=ctypes.WinDLL('user32',use_last_error=True)
                    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
                    user.GetParent.argtypes=[wintypes.HWND];user.GetParent.restype=wintypes.HWND
                    direct=[];renderers=[]
                    def child(hwnd,_):
                        name=ctypes.create_unicode_buffer(256);user.GetClassNameW(hwnd,name,256)
                        if user.GetParent(hwnd)==parent.winfo_id():direct.append(hwnd)
                        if name.value=='Chrome_RenderWidgetHostHWND':renderers.append(hwnd)
                        return True
                    user.EnumChildWindows(parent.winfo_id(),callback(child),0)
                    return direct,renderers
                def wait(predicate):
                    deadline=time.monotonic()+35
                    while time.monotonic()<deadline:
                        root.update();
                        if predicate():return
                        while not events.empty():
                            event=events.get_nowait()
                            if event['state']=='error':self.fail(event['detail'])
                        if process.poll() is not None:
                            time.sleep(.2)
                            self.fail('Native component exited: '+str(process.returncode)+' '+str(list(events.queue))+' '+process.stderr.read())
                        time.sleep(.03)
                    self.fail('Hidden native fixture timed out: '+str(bridge.status(token)))
                url=bridge.prepare(rid,quote='Selected native evidence',reply_mode='ai',provider=provider);token=url.split('#paperquick=')[1].split('.',1)[1]
                send({'type':'navigate','url':url})
                wait(lambda:bool(mounted_children()[1]))
                self.assertEqual(len(mounted_children()[0]),1,'Native form must be attached to the Tk host, not the invisible WinForms parking window')
                wait(lambda:bridge.status(token)['state']=='ready')
                # Repair display and resize without navigating or losing draft.
                parent.place_configure(width=640,height=480);root.update()
                send({'type':'sync-host'});send({'type':'navigate','url':url})
                def resized():
                    import ctypes
                    from ctypes import wintypes
                    rectangle=wintypes.RECT()
                    ctypes.windll.user32.GetClientRect(mounted_children()[0][0],ctypes.byref(rectangle))
                    return (rectangle.right,rectangle.bottom)==(640,480)
                wait(resized)
                self.assertEqual(bridge.status(token)['state'],'ready')
                blocked=bridge.prepare(rid,quote='Do not overwrite unsent evidence',reply_mode='ai',provider=provider)
                send({'type':'navigate','url':blocked})
                deadline=time.monotonic()+8;protected=False
                while time.monotonic()<deadline and not protected:
                    root.update()
                    try:protected='草稿' in events.get(timeout=.1)['detail']
                    except queue.Empty:pass
                self.assertTrue(protected,'Unsent native draft must remain intact')
                self.assertFalse(root.winfo_ismapped());send({'type':'fixture-submit'})
                if provider!='chatgpt':time.sleep(.3);send({'type':'fixture-bind'})
                wait(lambda:bridge.status(token)['state']=='bound')
                time.sleep(.5);send({'type':'fixture-reply'});wait(lambda:bool(lib.setting('ai-web-replies:'+rid+':'+provider,[])))
                self.assertIn('Native fixture answer',lib.setting('ai-web-replies:'+rid+':'+provider)[0]['answer'])
                url=bridge.prepare(rid,quote='Second native evidence',reply_mode='ai',provider=provider);token=url.split('#paperquick=')[1].split('.',1)[1]
                self.assertFalse(bridge.payload(token)['files']);send({'type':'navigate','url':url});wait(lambda:bridge.status(token)['state']=='ready')
            finally:
                if process:
                    if process.poll() is None:
                        try:process.stdin.write('{"type":"close"}\n');process.stdin.flush();process.stdin.close()
                        except (OSError,ValueError):pass
                        # A cross-process child sends teardown messages to its
                        # Tk owner. Keep that hidden owner's message loop alive.
                        deadline=time.monotonic()+20
                        while process.poll() is None and time.monotonic()<deadline:
                            root.update();time.sleep(.02)
                        process.wait(timeout=1)
                    process.stdout.close()
                    process.stderr.close()
                root.destroy();bridge.close();lib.close()
