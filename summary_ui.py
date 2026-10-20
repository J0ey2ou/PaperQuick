"""Reading review, topic suggestions and discovery, together in one popup."""
from datetime import date,datetime,timedelta
from pathlib import Path
import re,webbrowser
from urllib.parse import quote
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from library_core import Library
from reading_stats import reading_recap,recap_text,recap_intro,duration
from research_topics import topic_overview,build_search_queries
from literature_tracking import TrackingStore
from ui_theme import FG,INPUT,FONT


class SummaryView:
    def __init__(self,parent,directory,on_read=None,on_query=None,coordinator=None):
        self.directory=directory;self.on_read=on_read;self.on_query=on_query;self.content='';self.data={};self.topic_id=None
        self.frame=ttk.Frame(parent,padding=(24,18));self.owns_coordinator=coordinator is None
        if coordinator is None:
            from tracking_runtime import TrackingCoordinator
            coordinator=TrackingCoordinator(parent,lambda:self.directory)
        self.coordinator=coordinator;coordinator.listeners.append(self._checked)
        self.frame.columnconfigure(0,weight=1);self.frame.rowconfigure(1,weight=1)
        header=ttk.Frame(self.frame);header.grid(row=0,column=0,sticky='ew',pady=(0,14))
        left=ttk.Frame(header);left.pack(side='left',fill='x',expand=True)
        ttk.Label(left,text='阅读总结',style='Hero.TLabel').pack(anchor='w')
        ttk.Label(left,text='回看读过的研究，找到下一篇值得读的文献。',style='Muted.TLabel').pack(anchor='w',pady=(5,0))
        self.project=tk.StringVar(value='全部课题');self.projects={}
        self.project_box=ttk.Combobox(header,textvariable=self.project,state='readonly',width=22);self.project_box.pack(side='right');self.project_box.bind('<<ComboboxSelected>>',lambda _:self.refresh())
        self.tabs=ttk.Notebook(self.frame);self.tabs.grid(row=1,column=0,sticky='nsew')
        from ui_widgets import scrollable_page
        review_host,self.review=scrollable_page(self.tabs);topics_host,self.topics_page=scrollable_page(self.tabs);watch_host,self.watch=scrollable_page(self.tabs)
        self.tabs.add(review_host,text='阅读回顾');self.tabs.add(topics_host,text='主题与检索')
        from citation_ui import CitationView
        self.citations=CitationView(self.tabs,directory,on_query=on_query,on_collected=self._collection_changed)
        self.tabs.add(self.citations.frame,text='引用与被引');self.tabs.add(watch_host,text='主题追踪')
        self._build_review();self._build_topics();self._build_watch()
        self.footer=tk.StringVar(value='阅读与主题整理保存在这台电脑上。')
        ttk.Label(self.frame,textvariable=self.footer,style='Muted.TLabel',wraplength=960).grid(row=2,column=0,sticky='w',pady=(8,0))

    def _library(self,action):
        lib=Library(self.directory)
        try:return action(lib)
        finally:lib.close()
    def _store(self,action):return self._library(lambda lib:action(TrackingStore(lib)))
    def _project(self):return self.projects.get(self.project.get())
    def _write(self,widget,text):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',text);widget.configure(state='disabled')
    def _text(self,parent,height=8):
        area=ttk.Frame(parent);area.pack(fill='both',expand=True)
        widget=tk.Text(area,height=height,wrap='word',font=(FONT,10),bg=INPUT,fg=FG,padx=16,pady=14,relief='flat',spacing3=7)
        scroll=ttk.Scrollbar(area,command=widget.yview);scroll.pack(side='right',fill='y');widget.configure(yscrollcommand=scroll.set);widget.pack(fill='both',expand=True);return widget
    def _tree(self,parent,columns,widths):
        area=ttk.Frame(parent);area.pack(fill='both',expand=True)
        tree=ttk.Treeview(area,columns=tuple(columns),show='headings',selectmode='browse',height=3)
        for (key,label),width in zip(columns.items(),widths):tree.heading(key,text=label);tree.column(key,width=width,minwidth=60)
        scroll=ttk.Scrollbar(area,command=tree.yview);scroll.pack(side='right',fill='y');tree.configure(yscrollcommand=scroll.set);tree.pack(fill='both',expand=True);return tree
    def _flex_rows(self,parent,flexible):
        parent.columnconfigure(0,weight=1)
        children=[(child,child.pack_info()) for child in parent.winfo_children()]
        for child,_ in children:child.pack_forget()
        for row,(child,options) in enumerate(children):
            child.grid(row=row,column=0,sticky='nsew' if child is flexible else 'ew',pady=options.get('pady',0),padx=options.get('padx',0))
            parent.rowconfigure(row,weight=1 if child is flexible else 0)

    def _build_review(self):
        bar=ttk.Frame(self.review);bar.pack(fill='x',pady=(0,12));self.day=tk.StringVar(value=(date.today()-timedelta(days=1)).isoformat());self.days=1
        for label,delta,days in [('昨天',-1,1),('今天',0,1),('近七天',0,7)]:ttk.Button(bar,text=label,style='Compact.TButton',command=lambda d=delta,n=days:self.set_day(d,n)).pack(side='left',padx=(0,6))
        entry=ttk.Entry(bar,textvariable=self.day,width=13);entry.pack(side='left',padx=6);entry.bind('<Return>',lambda _:self.set_custom_day())
        ttk.Button(bar,text='查看日期',style='Compact.TButton',command=self.set_custom_day).pack(side='left')
        ttk.Button(bar,text='导出',style='Compact.TButton',command=self.export).pack(side='right');ttk.Button(bar,text='复制总结',style='Compact.TButton',command=self.copy).pack(side='right',padx=6)
        cards=ttk.Frame(self.review);cards.pack(fill='x');self.stats=[]
        for i,label in enumerate(('读过的文献','阅读时长','笔记与标记')):
            cards.columnconfigure(i,weight=1);card=ttk.Frame(cards,style='Card.TFrame',padding=(18,12));card.grid(row=0,column=i,sticky='nsew',padx=(0,10 if i<2 else 0))
            ttk.Label(card,text=label,style='CardMuted.TLabel').pack(anchor='w');value=tk.StringVar(value='—');self.stats.append(value);ttk.Label(card,textvariable=value,style='CardStat.TLabel',font=(FONT,20)).pack(anchor='w',pady=(8,2))
        self.intro=tk.StringVar();ttk.Label(self.review,textvariable=self.intro,wraplength=950,style='Muted.TLabel').pack(anchor='w',pady=12)
        panes=ttk.Panedwindow(self.review,orient='horizontal');panes.pack(fill='both',expand=True);left=ttk.Frame(panes);right=ttk.Frame(panes);panes.add(left,weight=2);panes.add(right,weight=3)
        self.paper_tree=self._tree(left,{'title':'读过的研究','time':'阅读时长'},(300,115));self.paper_tree.bind('<<TreeviewSelect>>',lambda _:self._paper_detail());self.text=self._text(right)
        actions=ttk.Frame(self.review);actions.pack(fill='x',pady=(12,0));self.read_button=ttk.Button(actions,text='继续阅读',style='Accent.TButton',command=self._read_selected);self.read_button.pack(side='left')
        ttk.Button(actions,text='阅读时间如何计算',style='Subtle.TButton',command=lambda:messagebox.showinfo('阅读时间','只计算文献打开、阅读页面在你面前的时间。切到其他软件、打开总结或收起窗口时，计时会暂停。\n\n这是阅读停留时间，不代表已经理解或读完。笔记数量包含这些文献现有的笔记与标记。',parent=self.frame)).pack(side='right')
    def set_day(self,delta,days=1):self.days=days;self.day.set((date.today()+timedelta(days=delta)).isoformat());self.refresh()
    def set_custom_day(self):self.days=1;self.refresh()
    def refresh(self):
        try:end=date.fromisoformat(self.day.get())
        except ValueError:messagebox.showinfo('选择日期','请输入日期，例如 2026-10-11。',parent=self.frame);return
        def read(lib):
            self.projects={p['name']:p['id'] for p in lib.projects()}
            return reading_recap(lib,end-timedelta(days=self.days-1),end,self._project()),lib.records(self._project())
        self.data,self.records=self._library(read);self.project_box.configure(values=['全部课题',*self.projects]);self.content=recap_text(self.data)
        for variable,value in zip(self.stats,(f"{self.data['count']} 篇",duration(self.data['seconds']),f"{self.data['notes_count']} 份")):variable.set(value)
        self.intro.set(recap_intro(self.data));self.paper_tree.delete(*self.paper_tree.get_children());self.papers={p['id']:p for p in self.data['papers']}
        for p in self.data['papers']:self.paper_tree.insert('','end',iid=p['id'],values=(p['title'],duration(p['seconds'])))
        if self.papers:self.paper_tree.selection_set(next(iter(self.papers)));self._paper_detail()
        else:self._write(self.text,'这段时间还没有阅读记录。\n\n打开一篇感兴趣的文献，下一次回顾就从这里开始。\n\n也可以到“主题与检索”，看看课题中已经收藏的研究。')
        self.read_button.configure(state='normal' if self.papers else 'disabled');self.refresh_topics();self._load_topics();self.citations.refresh()
    def _paper_detail(self):
        selection=self.paper_tree.selection()
        if not selection:return
        p=self.papers[selection[0]];parts=[p['title'],duration(p['seconds']),'文献摘要',p['content']]
        if p['notes']:parts+=['我的想法',p['notes']]
        for a in p['annotations']:parts += [f"第 {a['page']+1} 页 · 摘录与批注",a.get('quote',''),a.get('text','')]
        self._write(self.text,'\n\n'.join(filter(None,parts)))
    def _read_selected(self):
        selected=self.paper_tree.selection()
        if selected and self.on_read:self.on_read(selected[0])

    def _build_topics(self):
        top=ttk.Frame(self.topics_page);top.pack(fill='x');ttk.Label(top,text='从已有研究，找到下一条线索',style='Section.TLabel').pack(side='left')
        self.scope=tk.StringVar(value='课题文献库');box=ttk.Combobox(top,textvariable=self.scope,values=['课题文献库','所选时段的阅读'],state='readonly',width=20);box.pack(side='right');box.bind('<<ComboboxSelected>>',lambda _:self.refresh_topics())
        self.topic_description=tk.StringVar();ttk.Label(self.topics_page,textvariable=self.topic_description,style='Muted.TLabel',wraplength=950).pack(anchor='w',pady=12)
        self.keyword_tree=self._tree(self.topics_page,{'term':'主题关键词','count':'相关文献','source':'来自'},(530,110,170));self.keyword_tree.bind('<Double-1>',lambda _:self._add_keyword())
        ttk.Label(self.topics_page,text='想继续了解什么？修改下面的词，用分号分隔；双击上方关键词也可以加入。',style='Muted.TLabel').pack(anchor='w',pady=(12,6))
        self.terms=tk.StringVar();ttk.Entry(self.topics_page,textvariable=self.terms).pack(fill='x');bar=ttk.Frame(self.topics_page);bar.pack(fill='x',pady=10)
        self.provider=tk.StringVar(value='PubMed');self.providers={'PubMed':'pubmed','Web of Science':'wos','Google Scholar':'scholar','Europe PMC':'europepmc'}
        box=ttk.Combobox(bar,textvariable=self.provider,values=list(self.providers),state='readonly',width=20);box.pack(side='left');box.bind('<<ComboboxSelected>>',lambda _:self.generate_queries())
        ttk.Button(bar,text='生成检索式',command=self.generate_queries).pack(side='left',padx=8);ttk.Button(bar,text='复制检索式',command=lambda:self._copy(self.query_text.get('1.0','end').strip())).pack(side='right')
        self.query_text=tk.Text(self.topics_page,height=3,wrap='word',font=(FONT,10),padx=12,pady=10);self.query_text.pack(fill='x')
        bottom=ttk.Frame(self.topics_page);bottom.pack(fill='x',pady=(12,0));ttk.Button(bottom,text='打开检索网站 ↗',style='Accent.TButton',command=self.open_search).pack(side='left');ttk.Button(bottom,text='关注这个主题',command=self.watch_terms).pack(side='left',padx=8)
        ttk.Label(self.topics_page,text='关键词来自标题、摘要和文献自带的关键词。检索式是继续探索的起点，可按研究问题进一步调整。',style='Muted.TLabel',wraplength=950).pack(anchor='w',pady=(10,0))
        self._flex_rows(self.topics_page,self.keyword_tree.master)
    def refresh_topics(self):
        overview=topic_overview(self.records if self.scope.get()=='课题文献库' else self.data['papers']);self.topic_description.set(overview['description']);self.keyword_tree.delete(*self.keyword_tree.get_children())
        for k in overview['keywords']:self.keyword_tree.insert('','end',values=(k['term'],f"{k['papers']} 篇",k['source']))
        self.terms.set('; '.join(k['term'] for k in overview['keywords'][:3]));self.generate_queries()
    def _add_keyword(self):
        selection=self.keyword_tree.selection()
        if selection:
            term=self.keyword_tree.item(selection[0],'values')[0];existing=[s.strip() for s in re.split('[;；\n]',self.terms.get()) if s.strip()]
            if term not in existing:existing.append(term)
            self.terms.set('; '.join(existing));self.generate_queries()
    def generate_queries(self):
        self.queries=build_search_queries(re.split('[;；\n]',self.terms.get()));self.query_text.delete('1.0','end');self.query_text.insert('1.0',self.queries[self.providers[self.provider.get()]])
    def open_search(self):
        query=self.query_text.get('1.0','end').strip()
        if not query:self.footer.set('先选几个感兴趣的关键词。');return
        key=self.providers[self.provider.get()]
        if key=='wos':self._copy(query);webbrowser.open('https://www.webofscience.com/wos/woscc/advanced-search');self.footer.set('检索式已复制。进入 Web of Science 后，粘贴到高级检索中。');return
        bases={'pubmed':'https://pubmed.ncbi.nlm.nih.gov/?term=','scholar':'https://scholar.google.com/scholar?q=','europepmc':'https://europepmc.org/search?query='};webbrowser.open(bases[key]+quote(query,safe=''))
    def watch_terms(self):
        query=self.query_text.get('1.0','end').strip() if self.provider.get()=='Europe PMC' else build_search_queries(re.split('[;；\n]',self.terms.get()))['europepmc']
        if not query:self.footer.set('先选几个感兴趣的关键词。');return
        self.topic_id=None;self.watch_name.set(self.project.get() if self._project() else self.terms.get()[:70]);self.watch_query.delete('1.0','end');self.watch_query.insert('1.0',query);self.automatic.set(False);self.watch_project=self._project();self.tabs.select(self.watch)
        self.watch_status.set(('已保留你编辑的检索式。' if self.provider.get()=='Europe PMC' else '已根据关键词生成 Europe PMC 检索式。')+'为主题起个名字，保存后即可查找新文献。');self.history.configure(values=[]);self.batch.set('');self._show_batch()

    def _build_watch(self):
        ttk.Label(self.watch,text='让感兴趣的话题持续有新进展',style='Section.TLabel').pack(anchor='w');ttk.Label(self.watch,text='Europe PMC · 生命科学与医学。仅在检查新文献时联网发送检索式。',style='Muted.TLabel').pack(anchor='w',pady=(6,10))
        bar=ttk.Frame(self.watch);bar.pack(fill='x');self.topic_choice=tk.StringVar();self.topic_box=ttk.Combobox(bar,textvariable=self.topic_choice,state='readonly',width=36);self.topic_box.pack(side='left');self.topic_box.bind('<<ComboboxSelected>>',lambda _:self._select_topic())
        ttk.Button(bar,text='新增主题',style='Compact.TButton',command=self._new_topic).pack(side='left',padx=8);self.watch_name=tk.StringVar();ttk.Entry(bar,textvariable=self.watch_name).pack(side='left',fill='x',expand=True)
        self.watch_query=tk.Text(self.watch,height=3,wrap='word',font=(FONT,10),padx=12,pady=9);self.watch_query.pack(fill='x',pady=10)
        bar=ttk.Frame(self.watch);bar.pack(fill='x');self.automatic=tk.BooleanVar(value=False);self.watch_project=None
        ttk.Checkbutton(bar,text='每天检查一次（软件运行时）',variable=self.automatic).pack(side='left');self.check_button=ttk.Button(bar,text='查找新文献',style='Accent.TButton',command=self.check_watch);self.check_button.pack(side='right');ttk.Button(bar,text='保存主题',command=self.save_watch).pack(side='right',padx=8)
        self.watch_status=tk.StringVar(value='保存关注主题，或从“主题与检索”添加。');ttk.Label(self.watch,textvariable=self.watch_status,style='Muted.TLabel',wraplength=940).pack(anchor='w',pady=10)
        bar=ttk.Frame(self.watch);bar.pack(fill='x',pady=(0,8));ttk.Label(bar,text='历次发现').pack(side='left');self.batch=tk.StringVar();self.history=ttk.Combobox(bar,textvariable=self.batch,state='readonly',width=55);self.history.pack(side='left',padx=10);self.history.bind('<<ComboboxSelected>>',lambda _:self._show_batch())
        self.undo_button=ttk.Button(bar,text='撤回这次发现',style='Compact.TButton',command=self.toggle_batch);self.undo_button.pack(side='right')
        self.result_tree=self._tree(self.watch,{'title':'发现的文献','date':'发表日期','collected':'收藏状态'},(620,110,95));self.result_tree.bind('<<TreeviewSelect>>',lambda _:self._result_detail())
        self.result_info=tk.StringVar();ttk.Label(self.watch,textvariable=self.result_info,wraplength=940,style='Muted.TLabel').pack(anchor='w',pady=10)
        bar=ttk.Frame(self.watch);bar.pack(fill='x');ttk.Button(bar,text='查找原文 / 下载归档',command=self._find_result).pack(side='left');ttk.Button(bar,text='收藏到课题',command=self._collect_result).pack(side='left',padx=8)
        self._flex_rows(self.watch,self.result_tree.master)
    def _new_topic(self):
        self.topic_id=None;self.topic_choice.set('');self.watch_name.set('');self.watch_query.delete('1.0','end');self.automatic.set(False);self.watch_project=self._project();self.batch.set('');self.history.configure(values=[]);self._show_batch();self.watch_status.set('填写主题名称和检索式。也可以从“主题与检索”生成。')
    def _load_topics(self):
        topics=self._store(lambda store:store.topics());self.saved_topics={f"{t['name']} · {t['id']}":t for t in topics};self.topic_box.configure(values=list(self.saved_topics))
        chosen=next((label for label,t in self.saved_topics.items() if t['id']==self.topic_id),None)
        if chosen:self.topic_choice.set(chosen);self._load_runs()
        elif not self.topic_id and topics and not self.watch_name.get():self.topic_choice.set(next(iter(self.saved_topics)));self._select_topic()
    def _select_topic(self):
        topic=self.saved_topics.get(self.topic_choice.get())
        if not topic:return
        self.topic_id=topic['id'];self.watch_project=topic['project'];self.watch_name.set(topic['name']);self.automatic.set(bool(topic['automatic']));self.watch_query.delete('1.0','end');self.watch_query.insert('1.0',topic['query']);self.watch_status.set(topic.get('last_error') or '准备好了。查找后可在下面回看每次发现。');self._load_runs()
    def save_watch(self):
        try:self.topic_id=self._store(lambda store:store.save_topic(self.watch_name.get(),self.watch_query.get('1.0','end').strip(),project=self.watch_project,topic_id=self.topic_id,automatic=self.automatic.get()))
        except ValueError as exc:self.watch_status.set(str(exc));return False
        self._load_topics();self.watch_status.set('主题已保存。'+('软件运行时，每天会为你检查一次。' if self.automatic.get() else '想了解新进展时，点击“查找新文献”。'));return True
    def check_watch(self):
        if self.topic_id in self.coordinator.busy:self.watch_status.set('正在查找这个主题的新文献…');return
        if self.save_watch() and self.coordinator.check(self.topic_id):self.watch_status.set('正在查找新文献，你可以继续阅读。');self.check_button.configure(state='disabled')
    def _checked(self,topic_id,result):
        if topic_id==self.topic_id:self.watch_status.set(result.get('message','查找完成。'));self.check_button.configure(state='normal');self._load_runs()
    def _load_runs(self,keep=None):
        runs=self._store(lambda store:store.runs(self.topic_id)) if self.topic_id else [];states={'complete':'已完成','rolled_back':'已撤回','failed':'未完成','running':'查找中'}
        self.runs={f"{datetime.fromtimestamp(r['created']).strftime('%m-%d %H:%M')} · {r['count']} 篇 · {states.get(r['status'],'')} · #{r['id']}":r for r in runs}
        self.history.configure(values=list(self.runs));self.batch.set(next((label for label,r in self.runs.items() if r['id']==keep),next(iter(self.runs),'')));self._show_batch();self.check_button.configure(state='disabled' if self.topic_id in self.coordinator.busy else 'normal')
    def _show_batch(self):
        run=getattr(self,'runs',{}).get(self.batch.get());items=self._store(lambda store:store.results(run['id'])) if run else [];self.results={str(p['id']):p for p in items};self.result_tree.delete(*self.result_tree.get_children())
        for p in items:self.result_tree.insert('','end',iid=str(p['id']),values=(p['title'],p.get('published') or p['year'],'已收藏' if p['already_collected'] else '待探索'))
        self.undo_button.configure(text='恢复这次发现' if run and run['status']=='rolled_back' else '撤回这次发现',state='normal' if run and run['status'] in ('complete','rolled_back') else 'disabled')
        info='选择一篇文献，查看来源并继续查找原文。' if items else '这里还没有发现记录。'
        if run:
            if run['status']=='rolled_back':info='这次发现已撤回，可以随时恢复。已收藏的文献、PDF 和笔记均保留。'
            elif run['status']=='failed':info=run.get('error') or '这次查找未完成，请稍后重试。'
            elif run['status']=='complete' and not items:info='本次没有发现新的匹配文献。'
            elif run.get('truncated'):info='结果较多，仅显示本次找到的前 50 篇。缩小主题范围可帮助你看得更全。'
        self.result_info.set(info)
    def toggle_batch(self):
        run=self.runs.get(self.batch.get())
        if run:self._store(lambda store:store.restore(run['id']) if run['status']=='rolled_back' else store.rollback(run['id']));self._load_runs(run['id'])
    def _selected_result(self):
        selected=self.result_tree.selection();return self.results.get(selected[0]) if selected else None
    def _result_detail(self):
        item=self._selected_result()
        if item:self.result_info.set(' · '.join(filter(None,[item.get('authors'),item.get('venue'),'Europe PMC',item.get('doi')]))[:450])
    def _find_result(self):
        item=self._selected_result()
        if item and self.on_query:self.on_query(item.get('doi') or item['title'])
    def _collect_result(self):
        item=self._selected_result()
        if not item:self.result_info.set('先选择一篇想收藏的文献。');return
        self._store(lambda store:store.add_result_to_library(item['id'],self._project() or self.watch_project));self._show_batch();self.footer.set('已加入文献收藏，可以继续查找原文并下载归档。');self._collection_changed()
    def _collection_changed(self):
        self.records=self._library(lambda lib:lib.records(self._project()));self.citations.refresh()
        # Refresh the suggestions without discarding a query the reader is editing.
        terms=self.terms.get();edited=self.query_text.get('1.0','end').strip();self.refresh_topics();self.terms.set(terms);self.query_text.delete('1.0','end');self.query_text.insert('1.0',edited)
    def _copy(self,text):
        if text:self.frame.clipboard_clear();self.frame.clipboard_append(text);self.footer.set('已复制，可以粘贴到笔记或检索网站。')
    def copy(self):self._copy(self.content)
    def export(self):
        path=filedialog.asksaveasfilename(parent=self.frame,initialfile=f'阅读总结-{self.day.get()}.md',defaultextension='.md',filetypes=[('Markdown','*.md'),('Text','*.txt')])
        if path:Path(path).write_text(self.content,encoding='utf-8');self.footer.set('总结已导出。')
    def close(self):
        if self._checked in self.coordinator.listeners:self.coordinator.listeners.remove(self._checked)
        self.citations.close()
        if self.owns_coordinator:self.coordinator.close()
