"""Reader AI sidebar and provider settings; workers never touch Tk widgets."""
import copy
import queue
import threading
import time
import uuid
import tkinter as tk
import os
from tkinter import ttk
from pathlib import Path

from ai_providers import PROVIDERS
from ai_reading import AIHistory, Cancelled, TEMPLATES, SYSTEM, complete, context_prompt, get_key, load_profile, save_profile, read_context, secret_id
from library_core import Library
from ui_theme import FONT, style_dialog


def text_box(parent, height):
    frame = ttk.Frame(parent);frame.pack(fill='both', expand=height > 6, pady=4)
    widget = tk.Text(frame, height=height, width=22, wrap='word', font=(FONT, 10), undo=True, exportselection=False)
    scroll = ttk.Scrollbar(frame, command=widget.yview);scroll.pack(side='right', fill='y')
    widget.configure(yscrollcommand=scroll.set);widget.pack(fill='both', expand=True)
    return widget


class AISettings:
    def __init__(self, parent, directory):
        self.directory = Path(directory);self.events = queue.Queue();self.closed = False;self.testing = False
        self.win = tk.Toplevel(parent);self.win.title('AI 阅读助手设置');self.win.geometry('700x620');style_dialog(self.win)
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        panel = ttk.Frame(self.win, padding=20);panel.pack(fill='both', expand=True)
        self.provider = tk.StringVar();self.endpoint = tk.StringVar();self.model = tk.StringVar();self.key = tk.StringVar();self.stream = tk.BooleanVar(value=True)
        self.name_to_id = {v['name']: k for k,v in PROVIDERS.items()}
        ttk.Label(panel, text='工具与 API 配置', font=(FONT, 15, 'bold')).pack(anchor='w')
        combo = ttk.Combobox(panel, textvariable=self.provider, values=list(self.name_to_id), state='readonly');combo.pack(fill='x', pady=12)
        combo.bind('<<ComboboxSelected>>', lambda _:self.load())
        for label, variable in [('API 地址（兼容 Chat Completions）', self.endpoint), ('模型 ID（按你的账号权限填写）', self.model), ('API Key（留空保留，使用系统加密存储）', self.key)]:
            ttk.Label(panel, text=label).pack(anchor='w', pady=(8, 4))
            ttk.Entry(panel, textvariable=variable, show='•' if variable is self.key else '').pack(fill='x')
        ttk.Checkbutton(panel, text='流式显示回答（接口不支持时可关闭）', variable=self.stream).pack(anchor='w', pady=12)
        row = ttk.Frame(panel);row.pack(fill='x')
        ttk.Button(row, text='保存配置', command=self.save).pack(side='left')
        ttk.Button(row, text='测试连接', command=self.test).pack(side='left', padx=8)
        ttk.Button(row, text='删除此地址的密钥', command=self.delete_key).pack(side='right')
        self.status = tk.StringVar(value='网页账号模式无需 API Key。API 调用使用独立的服务额度。')
        ttk.Label(panel, textvariable=self.status, wraplength=620, style='Muted.TLabel').pack(fill='x', pady=16)
        ttk.Label(panel, text='豆包的模型 ID 可填写已开通的模型名称或推理接入点 ID。千问可按账号地域修改地址。测试连接只发送一句测试问题，不读取文献。切换工具前请保存配置。', wraplength=620, style='Muted.TLabel').pack(fill='x')
        self.provider.set(PROVIDERS['chatgpt']['name']);self.load();self.win.after(100, self.poll)

    def load(self):
        profile = load_profile(self.directory, self.name_to_id[self.provider.get()])
        self.endpoint.set(profile['endpoint']);self.model.set(profile['model']);self.stream.set(profile.get('stream', True));self.key.set('')
        self.status.set('配置已载入；密钥不回显。填写新密钥可替换已保存的密钥。')

    def save(self):
        try:
            save_profile(self.directory, self.name_to_id[self.provider.get()], self.endpoint.get(), self.model.get(), self.key.get() if self.key.get().strip() else None, self.stream.get())
            self.key.set('');self.status.set('已保存。网页/API 模式可在阅读器 AI 页签切换。');return True
        except (ValueError, OSError) as exc:self.status.set(str(exc));return False

    def delete_key(self):
        try:
            lib = Library(self.directory)
            try:lib.set_setting(secret_id(self.name_to_id[self.provider.get()], self.endpoint.get()), None)
            finally:lib.close()
            self.key.set('');self.status.set('已删除当前工具、当前 API 地址的密钥。')
        except ValueError as exc:self.status.set(str(exc))

    def test(self):
        if self.testing or not self.save():return
        provider = self.name_to_id[self.provider.get()];profile = load_profile(self.directory, provider)
        try:key = get_key(self.directory, provider, profile['endpoint'])
        except ValueError as exc:self.status.set(str(exc));return
        self.testing = True;self.status.set('正在测试连接…')
        def job():
            try:
                complete(profile['endpoint'], key, profile['model'], [{'role':'user','content':'请只回复 OK。'}], stream=profile['stream'], timeout=30)
                result = '连接成功，接口已返回文本回答。'
            except Exception as exc:result = str(exc) if isinstance(exc, ValueError) else '连接失败，请检查 API 配置。'
            self.events.put(result)
        threading.Thread(target=job, daemon=True, name='paperquick-ai-test').start()

    def poll(self):
        if self.closed:return
        try:self.status.set(self.events.get_nowait());self.testing = False
        except queue.Empty:pass
        self.win.after(100, self.poll)

    def close(self):self.closed = True;self.key.set('');self.win.destroy()


class AIReadingPanel:
    def __init__(self, reader):
        self.reader = reader;self.directory = reader.directory;self.events = queue.Queue();self.active = None;self.cancel = None;self.job_id = 0;self.turns = [];self.answer_turn = None;self.closed = False;self.last_inbox_check = 0;self.bound_rid = None
        from ui_widgets import scrollable_page, install_scrolling, flow_bar
        self.frame, form = scrollable_page(reader.notebook, padding=6);reader.notebook.add(self.frame, text='AI 阅读');install_scrolling(reader.frame)
        lib = Library(self.directory)
        try:defaults = lib.setting('ai-default', {'provider':'chatgpt', 'mode':'内嵌网页' if os.name=='nt' else '网页账号'})
        finally:lib.close()
        self.names = {v['name']: k for k,v in PROVIDERS.items()}
        self.provider = tk.StringVar(value=PROVIDERS.get(defaults.get('provider'), PROVIDERS['chatgpt'])['name'])
        self.mode = tk.StringVar(value=defaults.get('mode', '网页账号'))
        modes=['内嵌网页','网页账号','API'] if os.name=='nt' else ['网页账号','API']
        for variable, values in [(self.provider, list(self.names)), (self.mode, modes)]:
            combo = ttk.Combobox(form, textvariable=variable, values=values, state='readonly');combo.pack(fill='x', pady=3);combo.bind('<<ComboboxSelected>>', self.change_provider)
        top = ttk.Frame(form);top.pack(fill='x', pady=4);flow_bar(top)
        ttk.Button(top, text='AI 设置', command=self.settings).pack(side='left')
        ttk.Button(top, text='保存模板', command=self.save_template).pack(side='left', padx=4)
        ttk.Button(top, text='新建对话', command=self.new_chat).pack(side='right')
        self.source = tk.StringVar(value='选中文字后右键询问 AI，或直接在下方粘贴文字。')
        ttk.Label(form, textvariable=self.source, wraplength=290, style='Muted.TLabel').pack(fill='x', pady=4)
        ttk.Button(form, text='使用当前选文', command=self.select).pack(fill='x', pady=2)
        ttk.Label(form, text='原文范围', style='Muted.TLabel').pack(anchor='w')
        self.quote = text_box(form, 3)
        self.scope = tk.StringVar(value='仅选文')
        ttk.Combobox(form, textvariable=self.scope, values=['仅选文', '选文及上下文', '整篇文本'], state='readonly').pack(fill='x', pady=3)
        self.upload = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text='同时上传正文文件（可选，受网页大小限制）', variable=self.upload).pack(anchor='w')
        ttk.Label(form, text='选择问题模板，也可直接修改问题', wraplength=290, style='Muted.TLabel').pack(anchor='w', pady=(5,0))
        self.template = tk.StringVar(value='解释这段')
        combo = ttk.Combobox(form, textvariable=self.template, values=list(TEMPLATES), state='readonly');combo.pack(fill='x', pady=3);combo.bind('<<ComboboxSelected>>', self.set_template)
        self.question = text_box(form, 3);self.set_template()
        controls = ttk.Frame(form);controls.pack(fill='x', pady=4);flow_bar(controls)
        self.send_button = ttk.Button(controls, text='提问 / 打开网页', command=self.send, style='Accent.TButton');self.send_button.pack(side='left')
        def button_label(*_):self.send_button.configure(text={'内嵌网页':'在此打开聊天','API':'发送提问','网页账号':'打开聊天网页'}.get(self.mode.get(),'提问'))
        self.mode.trace_add('write',button_label);button_label()
        ttk.Button(controls, text='停止', command=self.stop).pack(side='right')
        self.status = tk.StringVar(value='网页由你确认发送；API 回答显示在下方。')
        ttk.Label(form, textvariable=self.status, wraplength=290, style='Muted.TLabel').pack(fill='x', pady=4)
        self.history = ttk.Combobox(form, state='readonly');self.history.pack(fill='x', pady=3);self.history.bind('<<ComboboxSelected>>', self.select_answer)
        self.answer = text_box(form, 9)
        self.answer_links={};self._link_press=None;self._answer_links_job=None
        self.answer.tag_configure('answer-web-link',foreground='#2473b7',underline=True)
        self.answer.tag_bind('answer-web-link','<Button-1>',self.link_press)
        self.answer.tag_bind('answer-web-link','<ButtonRelease-1>',self.link_release)
        self.answer.tag_bind('answer-web-link','<Enter>',lambda _:self.answer.configure(cursor='hand2'))
        self.answer.tag_bind('answer-web-link','<Leave>',lambda _:self.answer.configure(cursor='xterm'))
        self.answer.edit_modified(False);self.answer.bind('<<Modified>>',self.schedule_answer_links,add='+')
        self.answer.bind('<Destroy>',lambda _:self.cancel_answer_links(),add='+')
        controls = ttk.Frame(form);controls.pack(fill='x', pady=4)
        self.note_button = ttk.Button(controls, text='回答 / 选中部分加入笔记', command=self.save_note);self.note_button.pack(fill='x')
        ttk.Button(controls, text='定位原选文', command=self.locate).pack(fill='x', pady=3)
        self.frame.after(100, self.poll)

    def settings(self):self.settings_window = AISettings(self.frame, self.directory)

    def set_template(self, _=None):
        lib = Library(self.directory)
        try:templates = lib.setting('ai-templates', TEMPLATES)
        finally:lib.close()
        self.question.delete('1.0', 'end');self.question.insert('1.0', templates.get(self.template.get(), TEMPLATES.get(self.template.get(), '')))

    def save_template(self):
        lib = Library(self.directory)
        try:
            templates = lib.setting('ai-templates', dict(TEMPLATES))
            templates[self.template.get()] = self.question.get('1.0', 'end-1c')
            lib.set_setting('ai-templates', templates)
            self.status.set('已保存当前模板，下次使用继续生效。')
        finally:lib.close()

    def change_provider(self, _=None):
        if self.active:
            self.stop();self.status.set('已停止当前显示，等待请求结束后再提问。')
        lib = Library(self.directory)
        try:lib.set_setting('ai-default', {'provider':self.names[self.provider.get()], 'mode':self.mode.get()})
        finally:lib.close()
        self.refresh_history()

    def document_changed(self):
        if getattr(self,'embedded',None) and getattr(self.embedded,'rid',None)!=self.reader.rid:
            self.reader.notebook.hide(self.embedded.tab)
        self.bound_rid = self.reader.rid;self.selection = None;self.quote.delete('1.0', 'end');self.source.set('选中文字后右键询问 AI，或直接在下方粘贴文字。');self.refresh_history()

    def select(self, question=None):
        r = self.reader
        if not r.rid:return
        if self.bound_rid != r.rid:self.document_changed()
        item = r.current_selection()
        if r.text_view and r.text_view.winfo_ismapped():
            try:item = {'quote':r.text_view.get('sel.first', 'sel.last'), 'page':r.page, 'rect':[.06,.06,.06,.06]}
            except tk.TclError:item = None
        if not item or not item.get('quote', '').strip():r.status.set('请先选中文字，再右键询问 AI。');return
        self.selection = copy.deepcopy(item);self.selection['attachment'] = r.attachment_id
        self.quote.delete('1.0', 'end');self.quote.insert('1.0', item['quote'])
        self.source.set(f'已选原文 · 第 {r.citation_locator()} 页')
        if question:
            self.template.set(question);self.set_template()
        r.show_notes();r.notebook.select(self.frame)

    def history_store(self):
        provider = self.names[self.provider.get()];profile = load_profile(self.directory, provider)
        endpoint = profile['endpoint'] or 'http://127.0.0.1/v1'
        return AIHistory(self.directory, self.reader.rid, provider, endpoint, profile['model'])

    def refresh_history(self):
        self.turns = [];self.answer_turn = None;self.answer.delete('1.0', 'end')
        if self.reader.rid:
            if self.mode.get() == 'API':self.turns = self.history_store().load()['turns']
            else:
                lib = Library(self.directory)
                try:self.turns = lib.setting('ai-web-replies:' + self.reader.rid + ':' + self.names[self.provider.get()], [])
                finally:lib.close()
        self.history.configure(values=[f'{i + 1} · {t.get("question", "网页回答")[:40]}' for i,t in enumerate(self.turns)])
        if self.turns:self.history.current(len(self.turns)-1);self.select_answer()
        else:self.history.set('暂无回答')

    def select_answer(self, _=None):
        index = self.history.current()
        if not 0 <= index < len(self.turns):return
        self.answer_turn = copy.deepcopy(self.turns[index]);self.answer_turn['rid'] = self.reader.rid
        self.answer.delete('1.0', 'end');self.answer.insert('1.0', self.answer_turn['answer'])
        self.refresh_answer_links()

    def refresh_answer_links(self):
        from web_links import answer_links
        self.cancel_answer_links()
        self.answer.tag_remove('answer-web-link','1.0','end');self.answer_links={}
        text=self.answer.get('1.0','end-1c')
        for start,end,url in answer_links(text):
            # Text's character arithmetic follows Unicode characters, unlike
            # Tcl 8.6 string length, which counts supplementary characters twice.
            first=self.answer.index(f'1.0+{start}c');last=self.answer.index(f'1.0+{end}c')
            self.answer.tag_add('answer-web-link',first,last);self.answer_links[(first,last)]=url

    def schedule_answer_links(self,event=None):
        if self.answer.edit_modified():
            self.answer.edit_modified(False)
            if self._answer_links_job is None:self._answer_links_job=self.answer.after(250,self.refresh_answer_links)

    def cancel_answer_links(self):
        if self._answer_links_job is not None:
            self.answer.after_cancel(self._answer_links_job);self._answer_links_job=None

    def link_press(self,event):
        self._link_press=(event.x,event.y)

    def link_release(self,event):
        point=self._link_press;self._link_press=None
        if point is None or abs(event.x-point[0])>4 or abs(event.y-point[1])>4 or self.answer.tag_ranges('sel'):return
        self.refresh_answer_links()
        index=self.answer.index(f'@{event.x},{event.y}')
        for (first,last),url in self.answer_links.items():
            if self.answer.compare(first,'<=',index) and self.answer.compare(index,'<',last):
                self.open_answer_link(url);return

    def open_answer_link(self,url):
        from web_links import open_web_link
        try:open_web_link(url);self.status.set('已在默认浏览器打开回答中的链接。')
        except (ValueError,OSError) as exc:self.status.set(str(exc))

    def new_chat(self):
        if not self.reader.rid:return
        if self.active:self.status.set('请先停止并等待当前回答结束。');return
        if self.mode.get() == 'API':self.history_store().reset();self.refresh_history()
        else:self.reader.chat_bridge().reset(self.reader.rid, self.names[self.provider.get()])
        self.status.set('已新建对话，已保存的阅读笔记会保留。')

    def send(self):
        r = self.reader
        if self.active:self.status.set('当前请求尚未结束，请稍候。');return
        if not r.rid:self.status.set('请先打开文献。');return
        provider = self.names[self.provider.get()];mode = self.mode.get();rid = r.rid
        if mode != 'API' and not PROVIDERS[provider]['web']:self.status.set('自定义服务请使用 API 模式。');return
        quote = self.quote.get('1.0', 'end-1c');question = self.question.get('1.0', 'end-1c');scope = self.scope.get()
        if not quote.strip() and scope != '整篇文本':self.status.set('请先选中文字或在原文框粘贴文字。');return
        anchor = copy.deepcopy(getattr(self, 'selection', None)) or {'page':r.page, 'rect':[.06,.06,.06,.06], 'attachment':r.attachment_id}
        if not question.strip():self.status.set('请填写问题。');return
        anchor['quote'] = quote;anchor['question'] = question;anchor['title'] = r.title.get()
        profile = load_profile(self.directory, provider);store = self.history_store();expected = store.load()
        if mode == 'API':
            try:key = get_key(self.directory, provider, profile['endpoint'])
            except ValueError as exc:self.status.set(str(exc));return
        else:key = ''
        pages = {region['page'] for region in anchor.get('regions', [])} or {anchor.get('page', r.page)}
        path = r.path or r.source_path;title = r.title.get();upload = self.upload.get()
        cancel = threading.Event();self.cancel = cancel;self.job_id += 1;job_id = self.job_id
        self.active = {'id':job_id, 'rid':rid, 'provider':provider, 'mode':mode};self.answer_turn = None;self.answer.delete('1.0', 'end');self.status.set('正在准备选文和文献资料…')
        def job():
            try:
                context = read_context(path, pages, scope == '整篇文本', cancel) if scope != '仅选文' else ''
                prompt = context_prompt(title, quote, question, min(pages), context, scope)
                if cancel.is_set():raise Cancelled('已停止。')
                if mode != 'API':
                    self.events.put((job_id, 'web', (prompt, anchor, provider, upload)));return
                messages = [{'role':'system', 'content':SYSTEM}]
                # Keep every prior turn or ask for a new conversation, never silently drop context.
                for turn in expected['turns']:messages.extend([{'role':'user','content':turn['prompt']}, {'role':'assistant','content':turn['answer']}])
                messages.append({'role':'user','content':prompt})
                answer = complete(profile['endpoint'], key, profile['model'], messages, lambda text:self.events.put((job_id, 'delta', text)), cancel, profile.get('stream', True))
                if cancel.is_set():raise Cancelled('已停止。')
                store.append(expected, prompt, answer, anchor, provider, question)
                self.events.put((job_id, 'done', None))
            except Exception as exc:self.events.put((job_id, 'error', str(exc) if isinstance(exc, (ValueError, OSError)) else '请求未完成，请检查配置和文献文件后重试。'))
        threading.Thread(target=job, daemon=True, name='paperquick-ai-reading').start()

    def stop(self):
        if self.cancel:self.cancel.set();self.status.set('已停止接收回答，等待当前连接结束；未完成内容不会入库。')
        self.answer_turn = None

    def poll(self):
        if self.closed or self.reader.closed:return
        if self.bound_rid != self.reader.rid:self.document_changed()
        for _ in range(200):
            try:job_id, kind, value = self.events.get_nowait()
            except queue.Empty:break
            active = self.active
            if not active or active['id'] != job_id:continue
            visible = active['rid'] == self.reader.rid and active['provider'] == self.names[self.provider.get()] and active['mode'] == self.mode.get()
            cancelled = self.cancel.is_set()
            if kind == 'delta':
                if visible and not cancelled:self.answer.insert('end', value);self.answer.see('end');self.status.set('正在回答…')
                continue
            self.active = None
            if not visible:continue
            if cancelled:self.status.set('已停止，未完成回答未写入历史。');continue
            if kind == 'web':
                prompt, anchor, provider, upload = value
                try:
                    bridge = self.reader.chat_bridge()
                    url = bridge.prepare(self.reader.rid, quote=prompt, page=anchor['page'], anchor=anchor, provider=provider, include_document=upload, attachment_id=anchor['attachment'], reply_mode='ai')
                    if active['mode']=='内嵌网页':
                        if not getattr(self,'embedded',None):
                            from embedded_chat import EmbeddedChat
                            self.embedded=EmbeddedChat(self)
                        self.embedded.open(url,provider)
                        self.status.set('已在软件内打开聊天。回答回存后，可在 AI 页签加入笔记。')
                    else:
                        import webbrowser
                        if not webbrowser.open(bridge.open_url(url)):raise ValueError('浏览器未能打开。')
                        self.status.set('已交给网页扩展准备。发送后，可在网页选中回答并回存到 AI 页签。')
                except (ValueError, OSError) as exc:self.status.set(str(exc))
            elif kind == 'done':self.refresh_history();self.status.set('回答已保存到本篇对话，可修改后加入笔记。')
            else:self.status.set(value);self.answer_turn = None
        if getattr(self,'embedded',None):self.embedded.poll()
        if self.mode.get() != 'API' and self.reader.rid and not self.active and time.monotonic()-self.last_inbox_check > 2:
            self.last_inbox_check = time.monotonic()
            lib = Library(self.directory)
            try:turns = lib.setting('ai-web-replies:' + self.reader.rid + ':' + self.names[self.provider.get()], [])
            finally:lib.close()
            if [t['id'] for t in turns] != [t['id'] for t in self.turns]:self.refresh_history();self.status.set('网页回答已回到软件，可选择加入笔记。')
        self.frame.after(100, self.poll)

    def save_note(self):
        turn = self.answer_turn;r = self.reader
        if not turn or turn.get('rid') != r.rid:self.status.set('请选择一条已完成的回答。');return
        try:text = self.answer.get('sel.first', 'sel.last').strip()
        except tk.TclError:text = self.answer.get('1.0', 'end-1c').strip()
        if not text:self.status.set('回答为空。');return
        anchor = turn['anchor']
        lib = Library(self.directory)
        try:
            record = lib.get(r.rid)
            if not any(a['id'] == anchor['attachment'] for a in record['attachments']):raise ValueError('原附件已移除，请先恢复文献附件。')
        except ValueError as exc:self.status.set(str(exc));return
        finally:lib.close()
        try:r.prepare_note_edit()
        except Exception:
            self.status.set('保存未完成，请先确认其他阅读页的笔记已保存。');return
        import hashlib
        note_key = hashlib.sha256((turn['id'] + '\n' + text).encode()).hexdigest()
        if any(a.get('ai_note_key') == note_key for a in r.annotations):self.status.set('这段回答已经加入笔记。');return
        pages=sorted({p['page'] for p in anchor.get('regions',[])} or {anchor['page']})
        locator=str(pages[0]+1) if len(pages)==1 else f'{pages[0]+1}–{pages[-1]+1}'
        source = f'《{anchor.get("title", record["title"])}》 · 阅读器第 {locator} 页'
        content = f'\n\nAI 阅读笔记 · {PROVIDERS[turn["provider"]]["name"]}\n{source}\n原文：{anchor.get("quote", "")}\n问题：{turn.get("question", "")}\n回答：\n{text}\n'
        start=r.notes.index('end-1c');was_dirty=r.dirty;was_modified=r.notes.edit_modified();r.notes.insert('end', content)
        try:
            from ai_reading import save_note_snapshot
            annotation={'id':uuid.uuid4().hex, 'attachment':anchor['attachment'], 'page':anchor['page'], 'rect':anchor.get('rect', [.06,.06,.06,.06]), 'quote':anchor.get('quote',''), 'text':text, 'kind':'AI 笔记', 'color':'#538a76', 'created':time.time(), 'ai_note_key':note_key}
            snapshot,images=r.note_snapshot();styles={tag:list(zip(*[iter(map(str,r.notes.tag_ranges(tag)))]*2)) for tag in ('bold','italic')}
            lib=Library(self.directory)
            try:r.annotations,added=save_note_snapshot(lib,r.rid,annotation,snapshot,images,styles)
            finally:lib.close()
        except Exception:
            r.notes.delete(start,'end-1c');r.dirty=was_dirty;r.notes.edit_modified(was_modified);self.status.set('保存未完成，请检查文献库是否可写。');return
        if not added:r.notes.delete(start,'end-1c');r.dirty=was_dirty;r.notes.edit_modified(was_modified)
        else:
            r.dirty=False;r.notes.edit_modified(False)
            r.sync_note_peers()
        r._annotation_ids={a['id'] for a in r.annotations};r.refresh_annotations();r.draw_annotations()
        r.notebook.select(r.note_tab);self.status.set('回答已加入笔记并标记原文位置。' if added else '这段回答已经加入笔记。')

    def locate(self):
        if not self.answer_turn:return
        anchor = self.answer_turn['anchor'];r = self.reader
        try:
            if r.attachment_id != anchor['attachment']:r.open(r.rid, attachment_id=anchor['attachment'])
            r._pending_location = {'target_page':anchor['page'], 'target_point':anchor.get('rect',[.06,.06])[:2]}
            if not r.loading:r.apply_link_location()
        except (ValueError, OSError) as exc:self.status.set(str(exc))
