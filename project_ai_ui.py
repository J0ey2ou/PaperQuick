"""Explicit, preview-first cross-document AI using the existing API profiles."""
import queue
import copy
import tkinter as tk
from tkinter import ttk, messagebox
from library_core import Library, display_name
from ai_providers import PROVIDERS
from project_ai import retrieve_sources, build_prompt, ask, history, location_label
from ai_reading import load_profile
from ui_theme import FONT, style_dialog
from ui_widgets import flow_bar


class ProjectAIWindow:
    def __init__(self,parent,directory,project=None,manager=None,on_location=None):
        from workspace_tasks import TaskManager
        self.directory=directory;self.manager=manager or TaskManager(directory);self.owns_manager=manager is None
        self.on_location=on_location;self.closed=False;self.task_id=None;self.prepared=None;self.sources=[];self.events=queue.Queue();self.poll_job=None;self.search_scope=None
        self.win=tk.Toplevel(parent);self.win.title('跨文献 AI · 原文与来源');self.win.geometry('1080x780');self.win.minsize(880,650);style_dialog(self.win)
        self.win.protocol('WM_DELETE_WINDOW',self.close)
        body=ttk.Frame(self.win,padding=18);body.pack(fill='both',expand=True)
        ttk.Label(body,text='跨文献提问',font=(FONT,18,'bold')).pack(anchor='w')
        ttk.Label(body,text='先检索并选择原文片段，再预览发送。仅发送所选片段与问题到你配置的 API；不会发送整库。',style='Muted.TLabel',wraplength=950).pack(anchor='w',pady=(5,12))
        controls=ttk.Frame(body);controls.pack(fill='x');flow_bar(controls)
        library=Library(directory)
        try:self.projects=[{'id':None,'name':'全部文献'},*library.projects()]
        finally:library.close()
        self.project_var=tk.StringVar(value=next((p['name'] for p in self.projects if p['id']==project),'全部文献'))
        combo=ttk.Combobox(controls,textvariable=self.project_var,values=[p['name'] for p in self.projects],state='readonly',width=28);combo.pack(side='left',padx=(0,8));combo.bind('<<ComboboxSelected>>',lambda _:self.load_papers())
        self.provider=tk.StringVar(value='deepseek');ttk.Combobox(controls,textvariable=self.provider,values=list(PROVIDERS),state='readonly',width=12).pack(side='left',padx=(0,8))
        ttk.Button(controls,text='API 设置',command=self.settings).pack(side='left')
        self.tabs=ttk.Notebook(body);self.tabs.pack(fill='both',expand=True,pady=(12,8))
        scope=ttk.Frame(self.tabs,padding=12);preview=ttk.Frame(self.tabs,padding=12);answer=ttk.Frame(self.tabs,padding=12)
        self.tabs.add(scope,text='1 选择原文');self.tabs.add(preview,text='2 发送预览');self.tabs.add(answer,text='3 回答与历史')
        self.scope_tab=scope;self.preview_tab=preview;self.answer_tab=answer
        querybar=ttk.Frame(scope);querybar.pack(fill='x')
        ttk.Label(querybar,text='检索关键词').pack(side='left');self.query=tk.StringVar()
        ttk.Entry(querybar,textvariable=self.query).pack(side='left',fill='x',expand=True,padx=8)
        self.search_button=ttk.Button(querybar,text='检索所选文献',command=self.search);self.search_button.pack(side='right')
        ttk.Label(scope,text='多个关键词用空格分隔；需先在全文检索中建立索引。Ctrl / Shift 多选，默认选中本课题全部文献。',style='Muted.TLabel').pack(anchor='w',pady=8)
        split=ttk.Panedwindow(scope,orient='horizontal');split.pack(fill='both',expand=True)
        papers_frame=ttk.Frame(split);sources_frame=ttk.Frame(split);split.add(papers_frame,weight=1);split.add(sources_frame,weight=2)
        self.papers=self.tree(papers_frame,('title',),('范围内文献',),(320,));self.papers.bind('<<TreeviewSelect>>',lambda _:self.invalidate(clear_sources=True))
        self.source_tree=self.tree(sources_frame,('title','where','origin'),('命中来源（最多24项）','位置','提取方式'),(300,150,70))
        self.source_tree.bind('<<TreeviewSelect>>',lambda _:self.invalidate());self.source_tree.bind('<Double-1>',lambda _:self.open_source())
        ttk.Label(scope,text='你的研究问题').pack(anchor='w',pady=(10,4));self.question=self.textbox(scope,3,expand=False)
        ttk.Button(scope,text='预览所选片段',command=self.preview,style='Accent.TButton').pack(anchor='e',pady=(8,0))
        self.preview_text=self.textbox(preview,18)
        self.send_button=ttk.Button(preview,text='发送预览中的选文',command=self.send,state='disabled',style='Accent.TButton');self.send_button.pack(anchor='e',pady=(8,0))
        historybar=ttk.Frame(answer);historybar.pack(fill='x')
        self.history_combo=ttk.Combobox(historybar,state='readonly');self.history_combo.pack(side='left',fill='x',expand=True);self.history_combo.bind('<<ComboboxSelected>>',lambda _:self.show_history())
        ttk.Button(historybar,text='刷新历史',command=self.load_history).pack(side='right',padx=(8,0))
        self.answer_text=self.textbox(answer,16)
        self.answer_sources=self.tree(answer,('id','title','where'),('来源','文献','位置'),(60,420,180),height=4)
        self.answer_sources.bind('<Double-1>',lambda _:self.open_answer_source())
        footer=ttk.Frame(body);footer.pack(fill='x')
        self.status=tk.StringVar(value='准备就绪');ttk.Label(footer,textvariable=self.status,style='Muted.TLabel',wraplength=850).pack(side='left',fill='x',expand=True)
        ttk.Button(footer,text='取消当前任务',command=self.cancel).pack(side='right')
        self.provider.trace_add('write',lambda *_:self.invalidate())
        self.query.trace_add('write',lambda *_:self.invalidate(clear_sources=True))
        def question_changed(_):
            if self.question.edit_modified():self.invalidate();self.question.edit_modified(False)
        self.question.bind('<<Modified>>',question_changed)
        self.load_papers();self.poll_job=self.win.after(150,self.poll)

    @staticmethod
    def tree(parent,columns,titles,widths,height=6):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=columns,show='headings',selectmode='extended',height=height)
        for key,title,width in zip(columns,titles,widths):tree.heading(key,text=title);tree.column(key,width=width,minwidth=45)
        scroll=ttk.Scrollbar(frame,command=tree.yview);tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');tree.pack(fill='both',expand=True)
        return tree

    @staticmethod
    def textbox(parent,height,expand=True):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=expand,pady=5)
        widget=tk.Text(frame,height=height,wrap='word',font=(FONT,10),exportselection=False)
        scroll=ttk.Scrollbar(frame,command=widget.yview);widget.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');widget.pack(fill='both',expand=True)
        return widget

    @property
    def project(self):return next((p['id'] for p in self.projects if p['name']==self.project_var.get()),None)

    def settings(self):
        from ai_reading_ui import AISettings
        AISettings(self.win,self.directory)

    def invalidate(self,clear_sources=False):
        self.prepared=None;self.send_button.configure(state='disabled')
        if clear_sources:
            self.sources=[];self.search_scope=None;self.source_tree.delete(*self.source_tree.get_children())

    def scope_signature(self):
        return (self.project,tuple(sorted(self.papers.selection())),self.query.get().strip())

    def load_papers(self):
        if self.task_id:
            self.project_var.set(next(p['name'] for p in self.projects if p['id']==self.loaded_project));return
        self.loaded_project=self.project
        self.invalidate();self.papers.delete(*self.papers.get_children());self.source_tree.delete(*self.source_tree.get_children());self.sources=[]
        library=Library(self.directory)
        try:
            for r in library.records(self.project,summary=True):self.papers.insert('','end',iid=r['id'],values=(display_name(r),))
        finally:library.close()
        self.papers.selection_set(self.papers.get_children());self.load_history()
        self.current_answer=None;self.answer_sources.delete(*self.answer_sources.get_children())
        self.set_text(self.answer_text,'选择本课题历史记录，或先检索原文并预览发送。')
        self.set_text(self.preview_text,'请重新选择原文片段并生成发送预览。')

    def search(self):
        if self.task_id:return
        papers=list(self.papers.selection());query=self.query.get().strip();project=self.project
        if not query or not papers:self.status.set('请填写关键词并选择至少一篇文献。');return
        self.invalidate(clear_sources=True);self.mode='search';self.search_button.configure(state='disabled');self.active_scope=self.scope_signature()
        def work(context):
            try:return {'sources':retrieve_sources(self.directory,query,project,papers,context.event)}
            except Exception:
                context.check_cancelled();raise
        try:self.task_id=self.manager.submit('research-retrieval','跨文献原文检索',work,metadata={'project':project,'papers':len(papers),'retryable':False})
        except Exception as exc:self.search_button.configure(state='normal');self.status.set('检索任务未提交：'+str(exc));return
        self.status.set('正在检索选定范围…')

    def preview(self):
        if self.task_id:return
        if self.search_scope!=self.scope_signature():self.invalidate();self.status.set('文献范围或关键词已改变，请重新检索后预览。');return
        sources=[s for s in self.sources if s['id'] in self.source_tree.selection()]
        question=self.question.get('1.0','end-1c').strip()
        try:build_prompt(question,sources)
        except ValueError as exc:self.status.set(str(exc));return
        try:profile=load_profile(self.directory,self.provider.get())
        except Exception as exc:self.status.set('读取 API 配置失败：'+str(exc));return
        self.prepared={'question':question,'sources':copy.deepcopy(sources),'project':self.project,'provider':self.provider.get(),
                       'profile':(profile['endpoint'],profile['model']),'scope':self.scope_signature()}
        text=f"接收服务：{PROVIDERS[self.provider.get()]['name']}\nAPI 地址：{profile['endpoint']}\n模型：{profile['model'] or '尚未设置'}\n\n问题："+question+'\n\n'
        for s in sources:text+=f"[{s['id']}] {s['title']} · {location_label(s)} · {'OCR 待核对' if s['origin']=='ocr' else '原文提取'}\n{s['excerpt']}\n\n"
        self.set_text(self.preview_text,text);self.send_button.configure(state='normal');self.tabs.select(self.preview_tab)
        self.status.set(f'准备发送 {len(sources)} 个片段，共 {sum(len(s["excerpt"]) for s in sources)} 字。长页只包含显示的摘录范围。')

    def send(self):
        if self.task_id or not self.prepared:return
        data=self.prepared;provider=self.provider.get()
        if (data['provider']!=provider or data['scope']!=self.scope_signature() or data['question']!=self.question.get('1.0','end-1c').strip()
                or {s['id'] for s in data['sources']}!=set(self.source_tree.selection())):
            self.invalidate();self.status.set('问题、来源或接收服务已改变，请重新预览。');return
        try:profile=load_profile(self.directory,provider)
        except Exception as exc:self.status.set('读取 API 配置失败：'+str(exc));return
        if (profile['endpoint'],profile['model'])!=data['profile']:
            self.invalidate();self.status.set('API 地址或模型已改变，请重新确认发送预览。');return
        self.mode='ask';self.received=0
        while not self.events.empty():self.events.get_nowait()
        self.send_button.configure(state='disabled');self.search_button.configure(state='disabled');self.tabs.select(self.answer_tab)
        self.set_text(self.answer_text,'正在接收并校验回答…');self.answer_sources.delete(*self.answer_sources.get_children())
        def work(context):
            try:return ask(self.directory,data['project'],provider,data['question'],data['sources'],context,on_delta=lambda text:self.events.put(len(text)),expected_profile=data['profile'])
            except Exception:
                context.check_cancelled();raise
        try:self.task_id=self.manager.submit('project-ai','跨文献 AI · '+PROVIDERS[provider]['name'],work,metadata={'project':data['project'],'source_count':len(data['sources']),'retryable':False})
        except Exception as exc:
            self.search_button.configure(state='normal');self.send_button.configure(state='normal');self.status.set('AI 任务未提交：'+str(exc))

    @staticmethod
    def set_text(widget,text):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',text);widget.configure(state='disabled')

    def show_answer(self,result):
        text='接收服务：'+PROVIDERS.get(result.get('provider'),{}).get('name',result.get('provider','历史记录'))+' · 模型：'+result.get('model','')+'\n\n'+result['answer']+'\n\n—— 原文引文 ——\n'
        for c in result['citations']:text+=f"[{c['id']}] {c['quote']}\n\n"
        text+='来源编号和原文引文已通过程序校验；研究结论仍需人工核对。'
        self.set_text(self.answer_text,text);self.answer_sources.delete(*self.answer_sources.get_children());self.current_answer=result
        for s in result['sources']:self.answer_sources.insert('','end',iid=s['id'],values=(s['id'],s['title'],location_label(s)))

    def load_history(self):
        self.histories=history(self.directory,self.project)
        self.history_combo.configure(values=[r['question'][:80] for r in self.histories])
        if self.histories:self.history_combo.current(0)
        else:self.history_combo.set('暂无历史')

    def show_history(self):
        index=self.history_combo.current()
        if 0<=index<len(self.histories):self.show_answer(self.histories[index])

    def open_source(self):
        if self.source_tree.selection() and self.on_location:self.on_location(next(s for s in self.sources if s['id']==self.source_tree.selection()[0]))

    def open_answer_source(self):
        if self.answer_sources.selection() and self.on_location:self.on_location(next(s for s in self.current_answer['sources'] if s['id']==self.answer_sources.selection()[0]))

    def poll(self):
        self.poll_job=None
        if self.closed:return
        while not self.events.empty():self.received=getattr(self,'received',0)+self.events.get_nowait()
        if self.task_id:
            task=self.manager.get_task(self.task_id)
            if task is None:
                self.task_id=None;self.search_button.configure(state='normal');self.status.set('任务记录已不可用，请重新操作。');self.poll_job=self.win.after(150,self.poll);return
            self.status.set(task['message']+(f' · 已接收 {self.received} 字，校验后显示' if getattr(self,'received',0) and task['status']=='running' else ''))
            if task['status'] not in self.manager.ACTIVE:
                self.task_id=None;self.search_button.configure(state='normal')
                if task['status']=='succeeded':
                    if self.mode=='search':
                        if self.active_scope!=self.scope_signature():
                            self.invalidate(clear_sources=True);self.status.set('检索期间文献范围或关键词已改变，结果已丢弃；请重新检索。')
                            self.poll_job=self.win.after(150,self.poll);return
                        self.search_scope=self.active_scope;self.sources=task['result']['sources'];self.source_tree.delete(*self.source_tree.get_children())
                        for s in self.sources:self.source_tree.insert('','end',iid=s['id'],values=(s['title'],location_label(s),'OCR' if s['origin']=='ocr' else '文字'))
                        self.source_tree.selection_set(self.source_tree.get_children());self.status.set(f'找到 {len(self.sources)} 个原文片段；选择后填写问题并预览。' if self.sources else '未找到可用原文；请建立索引、缩小关键词或对扫描页运行 OCR。')
                    else:
                        if task['result'].get('project')==self.project:self.show_answer(task['result'])
                        self.load_history();self.status.set('引用校验通过，回答已保存到提交时的课题；请人工核对结论。')
                else:
                    self.status.set(task.get('error') or task['message'])
                    if self.mode=='ask':self.set_text(self.answer_text,task.get('error') or task['message'])
                if self.prepared:self.send_button.configure(state='normal')
        self.poll_job=self.win.after(150,self.poll)

    def cancel(self):
        if self.task_id:self.manager.cancel(self.task_id)

    def close(self):
        if self.closed:return
        self.cancel();self.closed=True
        if self.poll_job:self.win.after_cancel(self.poll_job);self.poll_job=None
        if self.owns_manager:self.manager.close(wait=False)
        self.win.destroy()
