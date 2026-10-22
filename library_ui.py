"""Tk local manager; slow PDF/import operations run outside the UI thread."""
from dataclasses import asdict
from pathlib import Path
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import webbrowser
from library_core import Library, FIELDS, DEFAULT_TEMPLATE, validate_template, filename,local_attachments,readable_attachments,display_name
from download_actions import resolve_download
from library_organization import READING_STATES,normalize_tags
from graph_view import write_graph
import endnote_sync
from ui_theme import BG, PANEL, SURFACE, FG, MUTED, ACCENT, LINE, FONT, install_theme, emblem, style_dialog
from ui_widgets import flow_bar
from smart_views_ui import SmartViewsMixin

class LibraryWindow(SmartViewsMixin):
    def __init__(self, parent, directory, embedded=False):
        self.library = Library(directory)
        self.embedded=embedded
        self.win = tk.Frame(parent,bg=BG) if embedded else tk.Toplevel(parent)
        if not embedded:
            self.win.title('文献直达 · 本地文献库')
            self.win.geometry('1320x920'); self.win.minsize(1120,800)
        install_theme(self.win.winfo_toplevel())
        self.events = queue.Queue(); self.busy = False; self.current_project = None;self.word_citations=None;self.attachment_window=None;self.conversion_window=None;self.package_window=None
        self.status = tk.StringVar(value='本地整理与图谱完全离线 · 导入 PDF 保留原文件')
        self.search = tk.StringVar()
        header=ttk.Frame(self.win,padding=(24,12 if embedded else 22,24,10)); header.pack(fill='x')
        if not embedded:emblem(header).pack(side='left',padx=(0,14))
        heading=ttk.Frame(header);heading.pack(side='left')
        ttk.Label(heading,text='文献分类' if embedded else '我的文献库',font=(FONT,21,'bold')).pack(anchor='w')
        ttk.Label(heading,text='PAPERQUICK  /  RESEARCH LIBRARY',foreground=ACCENT,font=('Segoe UI',9,'bold')).pack(anchor='w',pady=(4,0))
        ttk.Button(header,text='文献库文件夹',command=lambda: os.startfile(self.library.root)).pack(side='right')
        stats=ttk.Frame(self.win,padding=(24,0,24,4));stats.pack(fill='x')
        self.metrics=[]
        for i,(label,hint,color) in enumerate([('总收藏','LIBRARY RECORDS',ACCENT),('已归档正文','LOCAL FULL TEXT','#7c9bff'),('已读文献','READING PROGRESS','#65dbb0'),('课题分类','RESEARCH PROJECTS','#bf9afb')]):
            stats.columnconfigure(i,weight=1)
            card=tk.Frame(stats,bg=PANEL,highlightbackground=LINE,highlightthickness=1)
            card.grid(row=0,column=i,sticky='nsew',padx=(0,12 if i<3 else 0))
            value=tk.StringVar(value='0');self.metrics.append(value)
            tk.Label(card,textvariable=value,bg=PANEL,fg=ACCENT,font=('Segoe UI',20,'bold'),anchor='w').pack(side='left',padx=(14,10),pady=8)
            tk.Label(card,text=label,bg=PANEL,fg=MUTED,font=(FONT,10),anchor='w').pack(side='left',padx=(0,12))
        toolbar=ttk.Frame(self.win,padding=(24,4,24,8));toolbar.pack(fill='x');flow_bar(toolbar)
        self.controls=[]
        for title,command in [('导入文档',self.import_pdfs),('导入文件夹',self.import_folder),('新增条目',self.new_record),('离线图谱',self.graph),('Word 引用',self.word)]:
            button=ttk.Button(toolbar,text=title,command=command,style='Accent.TButton' if title=='导入文档' else 'TButton');button.pack(side='left',padx=(0,9));self.controls.append(button)
        self.action_menu(toolbar,'文献库工具', [('导入记录',self.import_report),('撤回导入',self.undo_import),('命名规则',self.naming),('EndNote 同步',self.endnote)])
        self.action_menu(toolbar,'智能视图', [('保存当前视图',self.save_smart_view),('打开已保存视图',self.smart_views),('显示列',self.choose_columns)])
        footer=ttk.Frame(self.win);footer.pack(side='bottom',fill='x')
        body=ttk.Panedwindow(self.win,orient='horizontal');body.pack(fill='both',expand=True,padx=24)
        left=ttk.Frame(body,width=210,padding=14,style='Card.TFrame');right=ttk.Frame(body,padding=(16,10),style='Card.TFrame');body.add(left,weight=0);body.add(right,weight=1)
        ttk.Label(left,text='课题导航',font=(FONT,12,'bold'),style='Card.TLabel').pack(anchor='w',pady=(4,6))
        ttk.Label(left,text='RESEARCH PROJECTS',font=('Segoe UI',8,'bold'),style='CardMuted.TLabel').pack(anchor='w',pady=(0,16))
        project_actions=ttk.Frame(left,style='Card.TFrame');project_actions.pack(side='bottom',fill='x',pady=(10,0))
        project_button=ttk.Button(project_actions,text='+ 新建课题',command=self.new_project)
        project_button.pack(fill='x',pady=(0,6));self.controls.append(project_button)
        self.action_menu(project_actions,'课题与标签管理', [('+ 新建子课题',self.new_subproject),('标签管理',self.manage_tags),('标签自动归类规则',self.project_tag_rules)],fill=True)
        project_list=ttk.Frame(left,style='Card.TFrame');project_list.pack(fill='both',expand=True)
        self.projects=tk.Listbox(project_list,exportselection=False,width=22,relief='flat',bg=PANEL,fg=FG,selectbackground='#1c485f',selectforeground=ACCENT,highlightthickness=0,activestyle='none',font=(FONT,11),borderwidth=0);self.projects.pack(side='left',fill='both',expand=True)
        project_scroll=ttk.Scrollbar(project_list,command=self.projects.yview);project_scroll.pack(side='right',fill='y');self.projects.configure(yscrollcommand=project_scroll.set)
        self.projects.bind('<<ListboxSelect>>',self.select_project)
        filterbar=ttk.Frame(right,style='Card.TFrame');filterbar.pack(fill='x',pady=(2,10))
        self.scope_title=tk.StringVar(value='全部文献')
        scope_label=ttk.Label(filterbar,textvariable=self.scope_title,font=(FONT,12,'bold'),style='Card.TLabel',wraplength=420)
        scope_label.grid(row=0,column=0,columnspan=2,sticky='w',padx=(0,12))
        self.package_button=ttk.Button(filterbar,text='打包课题',command=self.package_topic,style='Accent.TButton')
        self.package_button.grid(row=0,column=2,sticky='e');self.controls.append(self.package_button)
        filterbar.bind('<Configure>',lambda event:scope_label.configure(wraplength=max(120,event.width-self.package_button.winfo_reqwidth()-18)))
        self._search_job=None
        self.search.trace_add('write',self.schedule_search)
        self.status_filter=tk.StringVar(value='全部状态');self.rating_filter=tk.StringVar(value='全部评分');self.tag_filter=tk.StringVar(value='全部标签')
        ttk.Label(filterbar,text='搜索文献',style='CardMuted.TLabel').grid(row=1,column=0,sticky='w',padx=(0,10),pady=(10,0))
        search_entry=ttk.Entry(filterbar,textvariable=self.search,width=20);search_entry.grid(row=1,column=1,sticky='ew',padx=(0,10),pady=(10,0))
        self.search_entry=search_entry
        filterbar.columnconfigure(1,weight=1)
        self.filter_summary=tk.StringVar(value='点击列名排序 · ▾ 筛选')
        ttk.Label(filterbar,textvariable=self.filter_summary,style='CardMuted.TLabel').grid(row=2,column=0,columnspan=3,sticky='w',pady=(7,0))
        ttk.Button(filterbar,text='清除筛选',command=self.clear_column_filters,style='Subtle.TButton').grid(row=1,column=2,pady=(10,0))
        from library_table import TableState
        self.table_state=TableState()
        table=ttk.Frame(right,style='Card.TFrame');table.pack(fill='both',expand=True)
        columns=('title','year','project','tags','status','rating','pdf')
        self.tree=ttk.Treeview(table,columns=columns,show='headings',selectmode='extended',height=4)
        from tkinter.font import Font
        heading_font=Font(self.win,font=(FONT,10,'bold'))
        for key,label,width in zip(columns,('论文标题','年份','主课题','标签','阅读状态','评分','全文'),(310,76,150,140,110,110,100)):
            minimum=max(heading_font.measure(label+' ↓ ·  ▾')+24,220 if key=='title' else 70)
            self.tree.heading(key,text=label+'  ▾',command=lambda k=key:self.sort_column(k));self.tree.column(key,width=max(width,minimum),minwidth=minimum,stretch=key=='title',anchor='w' if key in ('title','project','tags') else 'center')
        self.tree.tag_configure('even',background=PANEL)
        self.tree.tag_configure('odd',background='#132237')
        self.tree.tag_configure('read',foreground='#77ddba')
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview)
        horizontal=ttk.Scrollbar(table,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        table.rowconfigure(0,weight=1);table.columnconfigure(0,weight=1)
        self.tree.grid(row=0,column=0,sticky='nsew');scroll.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        self.tree.bind('<Button-1>',self.column_click,add='+')
        self.tree.bind('<Double-1>',lambda e:self.open_pdf() if self.tree.identify_region(e.x,e.y)=='cell' else None);self.tree.bind('<<TreeviewSelect>>',self.detail)
        self.context_menu=tk.Menu(self.win,tearoff=False,bg=PANEL,fg=FG,activebackground='#1c485f',activeforeground=ACCENT)
        for title,command in [('下载原文（打开下载页面）',self.download_selected),('下载并自动归档',lambda:self.download_selected(archive=True)),('识别 / 修改显示名称',self.rename_selected),('选择所有文献',lambda:self.select_all(False)),('选择所有已下载文献',lambda:self.select_all(True)),('阅读正文',self.open_pdf),('关联已下载 PDF',self.attach_pdf),('编辑信息',self.edit),('分配课题',self.assign)]:
            self.context_menu.add_command(label=title,command=command)
        self.tree.bind('<Button-3>',self.show_context_menu)
        self.context_menu.add_separator();self.context_menu.add_command(label='插入 Word 引用 / 参考文献',command=self.word)
        self.context_menu.add_command(label='附件管理 / 比对阅读',command=self.attachments)
        self.context_menu.add_command(label='添加文献关系',command=self.add_relationship)
        self.context_menu.add_command(label='Word / PDF 互转',command=self.convert_document)
        self.context_menu.add_command(label='打开已下载原文所在位置',command=self.open_document_location)
        self.context_menu.add_command(label='编辑标签',command=self.edit_tags)
        self.context_menu.add_command(label='打包当前课题…',command=self.package_topic)
        self.context_menu.add_command(label='加入课题阅读队列',command=self.enqueue_selected)
        self.context_menu.add_command(label='ChatGPT 通篇解读 / 修改模板',command=self.chat_full_paper)
        states=tk.Menu(self.context_menu,tearoff=False);ratings=tk.Menu(self.context_menu,tearoff=False)
        for value in READING_STATES:states.add_command(label=value,command=lambda v=value:self.mark(v))
        for value in range(6):ratings.add_command(label=('未评分' if value==0 else '★'*value),command=lambda v=value:self.rate(v))
        self.context_menu.add_cascade(label='阅读状态',menu=states);self.context_menu.add_cascade(label='文献评分',menu=ratings)
        self.context_menu.add_separator();self.context_menu.add_command(label='删除文献',command=self.delete_selected);self.context_menu.add_command(label='恢复最近删除',command=self.restore_deleted)
        self.tree.bind('<Control-a>',lambda _:self.select_all(False))
        actions=ttk.Frame(footer,padding=(24,8,24,8));actions.pack(fill='x')
        flow_bar(actions)
        self.selection_summary=tk.StringVar(value='已选 0 篇')
        ttk.Label(actions,textvariable=self.selection_summary,style='Muted.TLabel').pack(side='left',padx=(0,10))
        self.action_menu(actions,'选择', [('选择所有文献',lambda:self.select_all(False)),('选择所有已下载',lambda:self.select_all(True)),('取消选择',lambda:self.tree.selection_remove(*self.tree.selection()))])
        self.selection_controls=[]
        for title,command in [('阅读正文',self.open_pdf),('下载原文',self.download_selected),('附件 / 比对',self.attachments),('编辑信息',self.edit),('分配课题',self.assign)]:
            button=ttk.Button(actions,text=title,command=command,style='Accent.TButton' if title=='阅读正文' else 'TButton');button.pack(side='left',padx=(0,9));self.controls.append(button);self.selection_controls.append(button)
        self.action_menu(actions,'更多操作', [('识别 / 修改显示名称',self.rename_selected),('添加关系',self.add_relationship),('编辑标签',self.edit_tags),('标记已读',lambda:self.mark('已读')),('标记未读',lambda:self.mark('未读')),('删除文献',self.delete_selected),('恢复最近删除',self.restore_deleted)])
        self.details=tk.StringVar(value='选择文献可查看 DOI、摘要和附件位置。')
        self.detail_button=ttk.Button(actions,text='展开详情',command=self.toggle_details,style='Subtle.TButton');self.detail_button.pack(side='left')
        detail_card=ttk.Frame(footer,style='Card.TFrame',padding=(16,8));self.detail_card=detail_card
        ttk.Label(detail_card,text='文献详情  /  PAPER INSIGHT',foreground=ACCENT,background=PANEL,font=(FONT,9,'bold')).pack(anchor='w',pady=(0,5))
        detail_text=tk.Text(detail_card,height=3,wrap='word',bg=PANEL,fg=MUTED,font=(FONT,10),relief='flat',state='disabled')
        detail_text.pack(fill='x')
        def update_details(*_):
            detail_text.configure(state='normal');detail_text.delete('1.0','end');detail_text.insert('1.0',self.details.get());detail_text.configure(state='disabled')
        self.details.trace_add('write',update_details);update_details()
        self.status_label=ttk.Label(footer,textvariable=self.status,padding=(24,8),style='Muted.TLabel');self.status_label.pack(fill='x')
        self.refresh();self.win.after(120,self.poll)
        if not embedded:self.win.protocol('WM_DELETE_WINDOW',self.close)

    def close(self):
        if self.busy or any(w and not w.closed and w.busy for w in (self.word_citations,self.attachment_window,self.conversion_window,self.package_window)):
            self.status.set('操作仍在进行，完成后可关闭。');return
        for window in (self.word_citations,self.attachment_window,self.conversion_window,self.package_window):
            if window and not window.closed:window.close()
        self.library.close();self.win.destroy()
        if getattr(self,'_chat_bridge',None):self._chat_bridge.close()

    def action_menu(self,parent,title,commands,fill=False):
        button=ttk.Menubutton(parent,text=title)
        menu=tk.Menu(button,tearoff=False)
        for label,command in commands:menu.add_command(label=label,command=command)
        button.configure(menu=menu)
        button.pack(fill='x' if fill else None,side='top' if fill else 'left',padx=(0,0 if fill else 8))
        self.controls.append(button)
        return button

    def toggle_details(self):
        opened=bool(self.detail_card.winfo_manager())
        if opened:self.detail_card.pack_forget()
        else:self.detail_card.pack(fill='x',padx=24,before=self.status_label)
        self.detail_button.configure(text='展开详情' if opened else '收起详情')

    def package_topic(self):
        if self.busy:return
        if self.package_window and not self.package_window.closed:
            self.package_window.win.lift();return
        from topic_package_ui import TopicPackageWindow
        self.package_window=TopicPackageWindow(self.win,self.library,self.current_project)

    def attachments(self):
        if self.busy:return
        rid=self.selected(True)
        if not rid:return
        if self.attachment_window and not self.attachment_window.closed:
            if self.attachment_window.busy:self.attachment_window.win.lift();return
            self.attachment_window.close()
        from attachment_ui import AttachmentManager
        def compare(attachment):
            if getattr(self,'on_compare',None):self.on_compare(rid,attachment)
            else:self.status.set('请从主窗口的文献阅读页面打开附件比对。')
        self.attachment_window=AttachmentManager(self.win,self.library.root,rid,on_compare=compare,on_changed=self.refresh)

    def convert_document(self):
        if self.busy:return
        rid=self.selected(True)
        if not rid:return
        if self.conversion_window and not self.conversion_window.closed:
            self.conversion_window.win.lift();return
        from document_conversion_ui import ConversionWindow
        primary=self.library.primary_attachment(rid)
        source=self.library.root/primary['path'] if primary else None
        self.conversion_window=ConversionWindow(self.win,self.library.root,rid,source=source,on_done=lambda path,attachment:self.refresh())

    def word(self):
        if self.busy:self.status.set('文献仍在整理，请完成后打开 Word 引用。');return
        if self.word_citations and not self.word_citations.closed:
            self.word_citations.load_records();self.word_citations.win.deiconify();self.word_citations.win.lift();return
        from word_citation_ui import WordCitationsWindow
        self.word_citations=WordCitationsWindow(self.win,self.library.root,selected=list(self.tree.selection()),on_library_changed=self.refresh)

    def refresh(self):
        previous=self.current_project
        records=self.library.records(summary=True);self._records_cache=records
        tags=sorted({t for r in records for t in r.get('tags',[])},key=str.casefold)
        if self.tag_filter.get() not in ['全部标签',*tags]:self.tag_filter.set('全部标签')
        for value,count in zip(self.metrics,(len(records),sum(any(a.get('role')=='primary' for a in readable_attachments(r)) for r in records),sum(r['status']=='已读' for r in records),len(self.library.projects()))):value.set(str(count))
        project_items=self.library.projects();children={}
        for p in project_items:children.setdefault(p.get('parent',''),[]).append(p)
        self.project_rows=[]
        def add_children(parent,depth=0):
            for p in children.get(parent,[]):
                p['_depth']=depth;self.project_rows.append(p);add_children(p['id'],depth+1)
        add_children('');self.projects.delete(0,'end')
        self.projects.insert('end',f'全部文献 ({len(records)})')
        ancestors={p['id']:self.library.project_descendants(p['id']) for p in self.project_rows}
        self._project_scopes=ancestors
        for p in self.project_rows:
            label=p['name'].split(' / ')[-1] if p.get('parent') else p['name']
            self.projects.insert('end',f"{'  '*p['_depth']}{label} ({sum(bool(set(r['projects']) & ancestors[p['id']]) for r in records)})")
        index=next((i+1 for i,p in enumerate(self.project_rows) if p['id']==previous),0)
        self.projects.selection_clear(0,'end');self.projects.selection_set(index);self.refresh_records()

    def schedule_search(self,*_):
        if self._search_job:self.win.after_cancel(self._search_job)
        self._search_job=self.win.after(160,self.refresh_records)

    def select_project(self,_=None):
        selected=self.projects.curselection()
        if selected:
            self.current_project=self.project_rows[selected[0]-1]['id'] if selected[0] else None
            self.refresh_records()

    def refresh_records(self):
        if self._search_job:self.win.after_cancel(self._search_job);self._search_job=None
        selected=set(self.tree.selection());self.tree.delete(*self.tree.get_children())
        query=self.search.get().lower()
        scope_name=self.library.project(self.current_project)['name'] if self.current_project else '全部文献'
        self.scope_title.set(scope_name if len(scope_name)<=30 else scope_name[:29]+'…')
        self.package_button.configure(text='打包课题' if self.current_project else '打包全部')
        index=0
        projects={p['id']:p['name'] for p in self.project_rows}
        scope=self._project_scopes.get(self.current_project) if self.current_project else None
        from library_table import values
        rows={r['id']:values(r,projects) for r in self._records_cache}
        for r in self.table_state.ordered(self._records_cache,rows):
            from workspace_state import WorkspaceStore
            extras={k:v for k,v in getattr(self,'extra_view_criteria',{}).items() if k in ('download','year_from','year_to')}
            if not WorkspaceStore.matches(r,rows[r['id']],extras):continue
            if not self.table_state.matches(rows[r['id']]):continue
            if scope is not None and not set(r['projects']) & scope:continue
            if query not in ' '.join(str(r.get(k,'')) for k in ('title','display_name','doi','authors','keywords','tags')).lower():continue
            if self.status_filter.get()!='全部状态' and r['status']!=self.status_filter.get():continue
            rating=r.get('rating',0)
            if self.rating_filter.get()=='未评分' and rating:continue
            if '星及以上' in self.rating_filter.get() and rating<int(self.rating_filter.get()[0]):continue
            if self.tag_filter.get()!='全部标签' and self.tag_filter.get() not in r.get('tags',[]):continue
            self.tree.insert('','end',iid=r['id'],values=(display_name(r),r['year'],projects.get(r['primary_project'],'未分类'),'；'.join(r.get('tags',[])),r['status'],'★'*rating or '未评分','已归档' if any(a.get('role')=='primary' for a in readable_attachments(r)) else '待添加'),tags=('odd' if index%2 else 'even','read' if r['status']=='已读' else ''))
            index+=1
            if r['id'] in selected:self.tree.selection_add(r['id'])

        from library_table import LABELS
        for key,label in LABELS.items():
            indicator=(' ↓' if self.table_state.descending else ' ↑') if self.table_state.sort_key==key else ''
            self.tree.heading(key,text=label+indicator+(' ·' if key in self.table_state.filters else '')+'  ▾')
        count=len(self.table_state.filters)
        self.filter_summary.set(f'{index} 篇 · {count} 列已筛选' if count else f'{index} 篇 · 点击列名排序 / ▾ 筛选')
        self.detail()

    def sort_column(self,key):
        self.table_state.sort(key);self.refresh_records()

    def clear_column_filters(self):
        self.extra_view_criteria={};self.search.set('');self.table_state.filters.clear();self.status_filter.set('全部状态');self.rating_filter.set('全部评分');self.tag_filter.set('全部标签');self.refresh_records()

    def column_choices(self,key):
        from library_table import values
        projects={p['id']:p['name'] for p in self.project_rows};scope=self._project_scopes.get(self.current_project) if self.current_project else None
        result=set()
        for record in self._records_cache:
            if scope is not None and not set(record['projects']) & scope:continue
            row=values(record,projects)
            if not self.table_state.matches(row,ignore=key):continue
            value=row[key];result.update(value or [''] if isinstance(value,list) else [value])
        return sorted(result,key=lambda v:(int(v) if key=='rating' else v.casefold()))

    def column_click(self,event):
        if self.tree.identify_region(event.x,event.y)!='heading':return
        index=int(self.tree.identify_column(event.x)[1:])-1;columns=list(self.tree['displaycolumns'])
        if '#all' in columns:columns=list(self.tree['columns'])
        if not 0<=index<len(columns):return
        widths=[int(self.tree.column(c,'width')) for c in columns]
        edge=sum(widths[:index+1])-round(sum(widths)*self.tree.xview()[0])
        if edge-27<=event.x<=edge-4:
            from library_table import ColumnFilter
            old=getattr(self,'column_popup',None)
            if old and old.win.winfo_exists():old.win.destroy()
            self.column_popup=ColumnFilter(self,columns[index],event.x_root,event.y_root+10);return 'break'

    def selected(self,one=False):
        ids=self.tree.selection()
        if not ids:messagebox.showinfo('选择文献','请先选择一篇文献。',parent=self.win);return None if one else []
        return ids[0] if one else list(ids)

    def detail(self,_=None):
        selected=self.tree.selection()
        self.selection_summary.set(f'已选 {len(selected)} 篇')
        for button in self.selection_controls:button.configure(state='normal' if selected and not self.busy else 'disabled')
        if not selected:
            self.details.set('选择文献可查看 DOI、摘要和附件位置。');return
        r=self.library.get(self.tree.selection()[0]);names=' / '.join(self.library.project(p)['name'] for p in r['projects'])
        self.details.set(f"{r['authors'][:150]} · DOI: {r['doi'] or '待补充'}\n课题：{names} · 标签：{'；'.join(r.get('tags',[])) or '无'} · 评分：{'★'*r.get('rating',0) or '未评分'}\n{r['abstract'][:220] or '摘要待补充'}")

    def run(self,title,work,done=None):
        if self.busy:return
        self.busy=True;self.status.set(title+'…')
        for b in self.controls:b.configure(state='disabled')
        def job(context=None):
            lib=None
            try:
                lib=Library(self.library.root);result=work(lib);self.events.put(('ok',result,done));return '文献库操作已完成'
            except Exception as exc:
                self.events.put(('error',str(exc),None))
                if context is not None:raise
            finally:
                if lib:lib.close()
        if getattr(self,'task_manager',None):
            try:self._managed_task_id=self.task_manager.submit('library-operation',title,job,metadata={'cancellable':False,'retryable':False})
            except Exception as exc:
                self.busy=False;self._managed_task_id=None
                for button in self.controls:button.configure(state='normal')
                self.status.set('任务未启动：'+str(exc));self.detail()
        else:threading.Thread(target=job,daemon=True).start()

    def poll(self):
        try:
            # A durable queue can fail before invoking our worker (for example
            # when its state file becomes unwritable). Surface that terminal
            # state here rather than leaving the library controls busy forever.
            task_id=getattr(self,'_managed_task_id',None)
            if self.busy and task_id and self.events.empty():
                task=self.task_manager.get_task(task_id)
                if task and task['status'] not in self.task_manager.ACTIVE:
                    self.events.put(('error',task.get('error') or task.get('message') or '任务未执行，请重试。',None))
            while True:
                kind,result,done=self.events.get_nowait();self.busy=False
                if kind=='progress':self.busy=True;self.status.set(result);continue
                self._managed_task_id=None
                for b in self.controls:b.configure(state='normal')
                self.refresh()
                if kind=='error':
                    self.status.set('操作未完成：'+result);messagebox.showerror('操作未完成',result,parent=self.win)
                else:
                    self.status.set(str(result) if not done else '操作完成')
                    if done:done(result)
        except queue.Empty:pass
        except Exception as exc:
            self.busy=False
            for b in self.controls:b.configure(state='normal')
            self.status.set('界面刷新未完成：'+(str(exc) or type(exc).__name__)+'；导入结果可在“导入记录”中查看。')
        finally:
            if self.win.winfo_exists():self.win.after(1000 if self.win.winfo_toplevel().state()=='withdrawn' and not self.busy else 120,self.poll)

    def choose_project(self,callback,title='选择归档课题'):
        dialog=tk.Toplevel(self.win);style_dialog(dialog);dialog.title(title);dialog.transient(self.win)
        panel=ttk.Frame(dialog,padding=20);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='选择课题，或输入新课题名称（自动新建文件夹）').pack(anchor='w')
        value=tk.StringVar(value=self.library.project(self.current_project)['name'] if self.current_project else self.library.projects()[0]['name'])
        combo=ttk.Combobox(panel,textvariable=value,values=[p['name'] for p in self.library.projects()],width=45);combo.pack(fill='x',pady=12)
        def accept():
            try:pid=next((p['id'] for p in self.library.projects() if p['name']==value.get().strip()),None) or self.library.create_project(value.get())
            except Exception as exc:messagebox.showerror('课题',str(exc),parent=dialog);return
            dialog.destroy();self.refresh();callback(pid)
        ttk.Button(panel,text='确认',command=accept).pack(anchor='e')

    def new_project(self):self.choose_project(lambda pid:None,'新建课题')

    def new_subproject(self):
        if not self.current_project:self.status.set('请先在左侧选择父课题，再新建子课题。');return
        name=simpledialog.askstring('新建子课题','父课题：'+self.library.project(self.current_project)['name']+'\n子课题名称：',parent=self.win)
        if name:
            try:self.library.create_project(name,self.current_project);self.refresh()
            except ValueError as exc:self.status.set(str(exc))

    def project_tag_rules(self):
        if not self.current_project:self.status.set('请先选择要自动归类到的课题或子课题。');return
        pid=self.current_project
        tags=simpledialog.askstring('标签自动归类','匹配任意一个标签即加入此课题；多个标签用分号分隔。\n清空会移除此课题的自动规则，手动分类保留。',initialvalue='；'.join(self.library.project_rules(pid)),parent=self.win)
        if tags is not None:self.run('更新标签归类规则',lambda lib:lib.set_project_rules(pid,tags),lambda _:self.status.set('规则已应用到现有文献；以后设置标签也会自动归类。'))

    def edit_tags(self):
        if self.busy:return
        ids=self.selected()
        if not ids:return
        from tag_ui import tag_picker
        initial=self.library.get(ids[0]).get('tags',[]) if len(ids)==1 else []
        self.tag_dialog=tag_picker(self.win,self.library,initial,lambda tags:self.run('保存标签并自动归类',lambda lib:[lib.save({'tags':tags},rid=rid) for rid in ids]))

    def manage_tags(self):
        if self.busy:return
        from tag_ui import tag_manager
        self.tag_manager=tag_manager(self.win,self.library,self.refresh)

    def rate(self,value):
        for rid in self.selected():self.library.save({'rating':value},rid=rid)
        self.refresh()

    def open_document_location(self):
        rid=self.selected(True)
        if not rid:return
        try:os.startfile(self.library.document_location(rid).parent)
        except (ValueError,OSError) as exc:self.status.set(str(exc))

    def chat_full_paper(self,rid=None):
        rid=rid or self.selected(True)
        if not rid:return
        from chat_bridge import ChatBridge
        from chat_prompt_ui import ChatPromptDialog
        if not getattr(self,'_chat_bridge',None):self._chat_bridge=ChatBridge(self.library.root)
        self.chat_prompt=ChatPromptDialog(self.win,self.library.root,rid,self._chat_bridge)

    def import_pdfs(self):
        paths=filedialog.askopenfilenames(parent=self.win,title='导入文档（保留原文件）',filetypes=[('文献文档','*.pdf *.docx *.doc *.txt *.md'),('PDF','*.pdf'),('Word','*.docx *.doc'),('文本','*.txt *.md')])
        if paths:self.choose_project(lambda pid:self.batch_import(paths,pid))

    def import_folder(self):
        if self.busy:return
        folder=filedialog.askdirectory(parent=self.win,title='选择文献文件夹（包含子目录）')
        if folder:
            self.run('正在查找文件',lambda lib:sorted((p for p in Path(folder).rglob('*') if p.is_file() and p.suffix.lower() in ('.pdf','.docx','.doc','.txt','.md') and not p.name.startswith('~$')),key=lambda p:str(p).casefold()),self.choose_import_files)

    def choose_import_files(self,paths):
        if not paths:messagebox.showinfo('没有可导入文档','文件夹中没有 PDF、Word 或 TXT 文档。',parent=self.win);return
        from import_selection_ui import ImportSelection
        self.import_selection=ImportSelection(self.win,paths,lambda selected:self.choose_project(lambda pid:self.batch_import(selected,pid)))

    def batch_import(self,paths,pid):
        def done(result):
            self.reveal_import(result,pid)
            self.status.set(f"导入完成：成功 / 关联 {result['count']} 份，失败 {len(result['errors'])} 份。详细结果见“导入记录”。")
            if result['errors']:messagebox.showwarning('部分文件未导入','\n'.join(result['errors'][:12]),parent=self.win)
            new_ids=result.get('new_paper_ids',[])
            if len(new_ids)==1:self.chat_full_paper(new_ids[0])
        self.run('正在整理文献',lambda lib:lib.import_batch(paths,pid,lambda n,total,name:self.events.put(('progress',f'正在导入 {n} / {total}：{name}',None))),done)

    def import_report(self):
        report=self.library.setting('last_import_report',{})
        if not report:self.status.set('还没有导入记录。');return
        dialog=tk.Toplevel(self.win);style_dialog(dialog);dialog.title('最近一次导入结果');dialog.geometry('760x500')
        panel=ttk.Frame(dialog,padding=18);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='逐文件导入结果',style='Section.TLabel').pack(anchor='w',pady=(0,12))
        text=tk.Text(panel,wrap='word');scroll=ttk.Scrollbar(panel,command=text.yview);scroll.pack(side='right',fill='y');text.configure(yscrollcommand=scroll.set);text.pack(fill='both',expand=True)
        states={'imported':'已导入','linked':'已关联已有文献','recovered':'已修复错误合并并恢复独立文献','error':'失败'}
        for item in report.get('files',[]):text.insert('end',f"{states.get(item['state'],item['state'])} · {item.get('seconds',0):.2f}s · {item['source']}\n"+(item.get('error','')+'\n' if item.get('error') else '')+'\n')
        text.configure(state='disabled')

    def reveal_import(self,result,pid):
        if not result.get('paper_ids'):return
        self.current_project=pid
        self.table_state.filters.clear();self.search.set('');self.status_filter.set('全部状态');self.rating_filter.set('全部评分');self.tag_filter.set('全部标签')
        self.refresh()
        visible=[rid for rid in result['paper_ids'] if self.tree.exists(rid)]
        if visible:self.tree.selection_set(visible);self.tree.focus(visible[0]);self.tree.see(visible[0]);self.detail()
        if getattr(self,'on_library_changed',None):self.on_library_changed()

    def undo_import(self):
        if self.busy:return
        row=self.library.latest_import()
        if not row:self.status.set('没有可以撤回的导入记录。');return
        if not messagebox.askyesno('撤回最近一次导入','撤回最近一批导入？原文件会保留；导入后已经编辑、阅读或新增笔记的文献也会保留。',parent=self.win):return
        self.run('正在撤回导入',lambda lib:lib.undo_import(row['id']),lambda r:self.status.set(f"已撤回 {r['restored']} 项；保留导入后有变化的 {r['kept']} 篇文献。"))

    def delete_selected(self):
        if self.busy:return
        ids=self.selected()
        if not ids:return
        if not messagebox.askyesno('删除文献',f'将选中的 {len(ids)} 篇文献移出文献库？可通过“恢复最近删除”找回。导入前的原文件不会删除。',parent=self.win):return
        if getattr(self,'before_remove',None) and self.before_remove(ids) is False:return
        self.run('正在移出文献库',lambda lib:lib.remove_papers(ids),lambda n:self.status.set(f'已移出 {n} 篇文献，可以恢复。'))

    def restore_deleted(self):
        if self.busy:return
        self.run('正在恢复文献',lambda lib:lib.restore_removed(),lambda n:self.status.set(f'已恢复 {n} 篇文献。'))

    def show_context_menu(self,event):
        rid=self.tree.identify_row(event.y)
        if not rid:return
        if rid not in self.tree.selection():self.tree.selection_set(rid)
        self.tree.focus(rid);self.detail()
        for index in range(self.context_menu.index('end')+1):
            if self.context_menu.type(index)!='separator':
                self.context_menu.entryconfigure(index,state='disabled' if self.busy else 'normal')
        try:self.context_menu.tk_popup(event.x_root,event.y_root)
        finally:self.context_menu.grab_release()

    def select_all(self,downloaded=False):
        if self.busy:return 'break'
        self.current_project=None;self.search.set('');self.refresh()
        ids=[r['id'] for r in self.library.records() if not downloaded or any(a.get('role')=='primary' for a in readable_attachments(r))]
        self.tree.selection_set(ids)
        self.status.set(f'已选择全库 {len(ids)} 篇'+('已下载文献' if downloaded else '文献')+'；可点击“识别 / 修改显示名称”。')
        return 'break'

    def rename_selected(self):
        if self.busy:return
        self.rename_records(self.selected())

    def add_relationship(self):
        if self.busy:return
        from relations_ui import relationship_editor
        def saved():
            self.status.set('文献关系已保存，可在图谱中查看关联原因。')
            if getattr(self,'on_library_changed',None):self.on_library_changed()
        relationship_editor(self.win,self.library.root,self.selected(),saved)

    def rename_records(self,ids,use_rule=False):
        if not ids:return
        from display_renaming import prepare_display_names
        def work(lib):
            plans=prepare_display_names(lib,ids)
            if use_rule:
                from display_renaming import display_template,display_name_from_rule
                for plan in plans:
                    pid=plan['before']['primary_project']
                    plan['display_name']=display_name_from_rule(plan['fields'],lib.project(pid)['name'],display_template(lib,pid),lib.setting('display_title_length',500))
            return plans
        self.run('正在读取文献信息（只修改软件显示名称）',work,self.preview_renames)

    def preview_renames(self,plans,skipped=0):
        from display_name_ui import DisplayNameDialog
        from display_renaming import apply_display_names
        def accept(confirmed):
            def done(result):
                text=f"已更新 {result['count']} 篇文献的显示名称，附件文件名保持不变。"
                if result['errors']:text+='\n跳过 / 未完成：\n'+'\n'.join(result['errors'])
                self.status.set(text.splitlines()[0]);messagebox.showinfo('重命名完成',text,parent=self.win)
                if getattr(self,'on_library_changed',None):self.on_library_changed()
            self.run('正在保存文献显示名称',lambda lib:apply_display_names(lib,confirmed),done)
        return DisplayNameDialog(self.win,self.library,plans,accept)

    def download_selected(self,archive=False):
        if self.busy:self.status.set('下载 / 归档仍在进行，请等待完成。');return
        rid=self.selected(True)
        if rid:self.start_download(rid,lookup=True,open_page=not archive)

    def start_download(self,rid,read_after=False,preferred_url=None,lookup=False,open_page=False):
        if self.busy:self.status.set('下载 / 归档仍在进行，请等待完成。');return
        def done(result):
            if result['kind'] in ('downloaded','existing'):
                self.status.set(('已归档：' if result['kind']=='downloaded' else '已有归档正文：')+result['path'])
                if read_after and getattr(self,'on_reader',None):self.on_reader(rid)
            elif result['kind']=='browser':
                try:opened=webbrowser.open(result['url'])
                except Exception:opened=False
                self.status.set((result.get('issue','')+' ' if result.get('issue') else '')+
                    ('已打开原文页面；下载后右键此条目 → 关联已下载 PDF，自动命名归档。' if opened else '请复制原文地址到浏览器下载：'+result['url']))
            else:
                self.status.set((result.get('issue','')+' ' if result.get('issue') else '')+'未找到可下载原文；可在查询页核对标题，或关联已下载 PDF。')
        email=getattr(self,'lookup_email',lambda:'')()
        self.run('正在定位并打开下载页面' if open_page else '正在查找开放版本并下载归档' if lookup else '正在下载归档 / 打开原文页面',
                 lambda lib:resolve_download(lib,rid,preferred_url,lookup,email,open_page),done)

    def collect(self,paper,read_after=False,preferred_url=None,download=True):
        if self.busy:self.status.set('下载 / 归档仍在进行，请等待完成。');return
        data={k:v for k,v in asdict(paper).items() if v};data.pop('match',None);data.pop('score',None)
        def accept(pid):
            if self.busy:self.status.set('下载 / 归档仍在进行，请等待完成后重试收藏。');return
            rid=self.library.save(data,pid);self.refresh()
            if self.tree.exists(rid):self.tree.selection_set(rid);self.tree.see(rid)
            if download:self.start_download(rid,read_after,preferred_url,lookup=not bool(paper.links))
            else:self.status.set('已收藏到课题；稍后可右键下载原文。')
        self.choose_project(accept,'收藏 / 下载归档')

    def attach_pdf(self):
        rid=self.selected(True)
        if not rid:return
        path=filedialog.askopenfilename(parent=self.win,filetypes=[('PDF','*.pdf')])
        if path:self.run('关联与归档 PDF',lambda lib:lib.attach(rid,path),lambda p:self.status.set('已归档：'+str(p)))

    def open_pdf(self):
        rid=self.selected(True)
        if not rid:return
        attachment=self.library.primary_attachment(rid)
        if not attachment:self.status.set('此条目尚无正文，请在“附件 / 比对”中添加 PDF / Word 并设为正文。');return
        if getattr(self,'on_reader',None):self.on_reader(rid);return
        try:os.startfile(self.library.root/attachment['path'])
        except OSError as exc:messagebox.showerror('打开失败',str(exc),parent=self.win)

    def new_record(self):self.edit_record(None)
    def edit(self):
        rid=self.selected(True)
        if rid:self.edit_record(rid)

    def edit_record(self,rid):
        data=self.library.get(rid) if rid else {}
        dialog=tk.Toplevel(self.win);style_dialog(dialog);dialog.title('编辑文献信息');dialog.transient(self.win)
        dialog.geometry(f"760x{min(800,max(480,dialog.winfo_screenheight()-120))}")
        footer=ttk.Frame(dialog,padding=(18,8));footer.pack(side='bottom',fill='x')
        canvas=tk.Canvas(dialog,highlightthickness=0);scroll=ttk.Scrollbar(dialog,command=canvas.yview);scroll.pack(side='right',fill='y');canvas.configure(yscrollcommand=scroll.set);canvas.pack(fill='both',expand=True)
        panel=ttk.Frame(canvas,padding=18);item=canvas.create_window(0,0,window=panel,anchor='nw');variables={}
        panel.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        labels=('标题','作者（换行或分号分隔）','年份','DOI','期刊','摘要','关键词','笔记','阅读状态')
        for field,label in zip(FIELDS,labels):
            if field=='status':continue
            ttk.Label(panel,text=label).pack(anchor='w');widget=tk.Text(panel,height=3 if field in ('abstract','notes') else 1,width=82,wrap='word');widget.insert('1.0',data.get(field,'未读' if field=='status' else ''));widget.pack(fill='x',pady=(2,7));variables[field]=widget
        tags=tk.StringVar(value='；'.join(data.get('tags',[])));state=tk.StringVar(value=data.get('status','未读'));rating=tk.StringVar(value=str(data.get('rating',0)))
        ttk.Label(panel,text='标签（分号分隔，自动匹配课题规则）').pack(anchor='w');ttk.Entry(panel,textvariable=tags).pack(fill='x',pady=5)
        def choose_tags():
            from tag_ui import tag_picker
            try:initial=normalize_tags(tags.get())
            except ValueError:initial=[]
            tag_picker(dialog,self.library,initial,lambda chosen:tags.set('；'.join(chosen)))
        ttk.Button(panel,text='选择已有标签…',command=choose_tags).pack(anchor='w',pady=4)
        bar=ttk.Frame(panel);bar.pack(fill='x',pady=6)
        for label,variable,choices in [('阅读状态',state,READING_STATES),('评分',rating,list(range(6)))]:
            ttk.Label(bar,text=label).pack(side='left',padx=8);ttk.Combobox(bar,textvariable=variable,values=choices,state='readonly',width=10).pack(side='left')
        def save():
            values={f:w.get('1.0','end').strip() for f,w in variables.items()}
            try:values.update(tags=normalize_tags(tags.get()),status=state.get(),rating=int(rating.get()))
            except ValueError as exc:messagebox.showerror('标签或评分',str(exc),parent=dialog);return
            if not values['title']:messagebox.showerror('标题','请填写标题。',parent=dialog);return
            self.library.save(values,self.current_project,rid);dialog.destroy();self.refresh()
        ttk.Button(footer,text='保存',command=save).pack(anchor='e')

    def assign(self):
        ids=self.selected()
        if not ids:return
        def accepted(pid):
            primary=messagebox.askyesno('主归档课题','设为主课题并移动已归档 PDF？\n选择“否”仅增加课题标签。',parent=self.win)
            self.run('分配课题',lambda lib:[lib.assign(rid,pid,primary) for rid in ids],lambda _:self.status.set('已更新课题分类'))
        self.choose_project(accepted)

    def mark(self,status):
        for rid in self.selected():self.library.save({'status':status},rid=rid)
        self.refresh()

    def naming(self):
        from display_renaming import display_template,display_name_from_rule
        dialog=tk.Toplevel(self.win);style_dialog(dialog);dialog.title('显示名称生成规则');panel=ttk.Frame(dialog,padding=20);panel.pack(fill='both')
        scope=self.current_project
        ttk.Label(panel,text='当前课题规则' if scope else '全库默认规则',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        ttk.Label(panel,text='支持 {年份} {第一作者} {标题} {期刊} {DOI} {课题}。缺失字段会自动跳过。\n只生成软件中的显示名称，不更改原文件或归档附件的文件名。').pack(anchor='w',pady=10)
        template=tk.StringVar(value=display_template(self.library,scope) if scope else self.library.setting('display_name_template','{标题}'))
        ttk.Entry(panel,textvariable=template,width=70).pack(fill='x')
        length=tk.StringVar(value=str(self.library.setting('display_title_length',500)));ttk.Label(panel,text='标题最大字符数（20–500）').pack(anchor='w',pady=(10,3));ttk.Entry(panel,textvariable=length,width=8).pack(anchor='w')
        result=tk.StringVar();ttk.Label(panel,textvariable=result,wraplength=600).pack(anchor='w',pady=12)
        def values():
            validate_template(template.get());n=int(length.get())
            if not 20<=n<=500:raise ValueError('标题长度应在 20–500 之间。')
            return template.get(),n
        def preview(*_):
            try:
                t,n=values();records=self.library.records(scope);sample=records[0] if records else {'title':'Example research paper','authors':'Wang, Li','year':'2026'}
                result.set('显示名称示例：'+display_name_from_rule(sample,self.library.project(scope)['name'] if scope else '示例课题',t,n))
            except Exception as exc:result.set(str(exc))
        template.trace_add('write',preview);length.trace_add('write',preview);preview()
        def save(batch=False):
            try:t,n=values()
            except Exception as exc:messagebox.showerror('模板',str(exc),parent=dialog);return
            self.library.set_setting('display_name_template:'+scope if scope else 'display_name_template',t)
            self.library.set_setting('display_title_length',n);dialog.destroy()
            if batch:self.rename_records([r['id'] for r in self.library.records(scope)],use_rule=True)
        buttons=ttk.Frame(panel);buttons.pack(fill='x');ttk.Button(buttons,text='保存显示规则',command=save).pack(side='left');ttk.Button(buttons,text='预览并批量修改显示名称',command=lambda:save(True)).pack(side='right')

    def graph(self):
        if getattr(self,'on_graph',None):self.on_graph();return
        self.run('生成离线图谱',lambda lib:write_graph(lib,self.current_project),lambda p:webbrowser.open(p.as_uri()))

    def endnote(self):
        source=filedialog.askopenfilename(parent=self.win,title='选择 EndNote .enl（只读源库）',initialfile=Path(self.library.setting('endnote_source','')).name,filetypes=[('EndNote','*.enl')])
        if source:self.run('读取 EndNote 并比较双方修改',lambda lib:endnote_sync.preview(lib,source),self.sync_preview)

    def sync_preview(self,plan):
        dialog=tk.Toplevel(self.win);style_dialog(dialog);dialog.title('EndNote 同步预览 · 源库只读');dialog.geometry('1040x720');panel=ttk.Frame(dialog,padding=18);panel.pack(fill='both',expand=True)
        entries=plan['entries'];conflicts=[(e,f) for e in entries for f in e['conflicts']];counts={key:sum(e['action']==key for e in entries) for key in set(e['action'] for e in entries)}
        names={'import':'新增到本地','link':'首次关联','export':'本地 → EndNote','update-local':'EndNote → 本地','both':'双方合并','export-new':'新增到 EndNote','unchanged':'无需修改','missing-endnote':'EndNote 缺失（不删除）','missing-local':'本地缺失（不删除）'}
        ttk.Label(panel,text=' · '.join(f'{names[k]} {n}' for k,n in counts.items()),wraplength=970,font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w')
        ttk.Label(panel,text='源库：'+plan['source']+'\n本版：读取 EndNote 修改到本地，导出 XML 与字段修改清单；已有 EndNote 条目需手动更新，不自动写回 .enl。\n课题通过 PaperQuick课题: 关键词交换；原生分组不映射。关闭 EndNote 库后预览；冲突必须逐项选择。',wraplength=970).pack(anchor='w',pady=10)
        report=tk.Text(panel,height=10,wrap='word');report.pack(fill='x')
        for e in entries:
            if e['action']!='unchanged':report.insert('end',f"[{names[e['action']]}] {(e['merged'] or e['remote'] or e['local']).get('title','条目缺失')}\n")
        report.configure(state='disabled')
        ttk.Label(panel,text=f'字段冲突：{len(conflicts)}（保留版本）').pack(anchor='w',pady=(12,5))
        frame=ttk.Frame(panel);frame.pack(fill='both',expand=True)
        canvas=tk.Canvas(frame,highlightthickness=0);scroll=ttk.Scrollbar(frame,orient='vertical',command=canvas.yview);canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        content=ttk.Frame(canvas);canvas.create_window((0,0),window=content,anchor='nw');content.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        choices={}
        for e,f in conflicts:
            row=ttk.Frame(content,padding=5);row.pack(fill='x');text=f"{e['merged'].get('title','')[:70]} · {f}\n本地：{str(e['local'][f])[:150]}\nEndNote：{str(e['remote'][f])[:150]}"
            ttk.Label(row,text=text,width=90,wraplength=730).pack(side='left');v=tk.StringVar();choices[(e['external_id'],f)]=v;ttk.Combobox(row,textvariable=v,values=('保留本地','保留 EndNote'),state='readonly',width=16).pack(side='right')
        def import_local():
            dialog.destroy();self.run('导入 EndNote 条目与 PDF',lambda lib:endnote_sync.import_only(lib,plan,self.current_project),lambda n:(self.library.set_setting('endnote_source',plan['source']),self.status.set(f'已导入 {n} 条文献；源库保持不变。')))
        def sync():
            if any(not v.get() for v in choices.values()):messagebox.showerror('冲突待处理','请逐项选择保留版本。',parent=dialog);return
            folder=filedialog.askdirectory(parent=dialog,title='选择保存交换包的位置')
            if not folder:return
            import time
            target=Path(folder)/('EndNote交换包-'+time.strftime('%Y%m%d-%H%M%S'))
            decisions={key:'local' if v.get()=='保留本地' else 'endnote' for key,v in choices.items()};dialog.destroy()
            self.run('应用到本地并生成离线交换包',lambda lib:endnote_sync.export_exchange(lib,plan,target,decisions),lambda p:(os.startfile(p),self.status.set('已生成交换包；请按包内说明在 EndNote 导入新增 / 核对更新。')))
        actions=ttk.Frame(panel);actions.pack(fill='x',pady=(12,0));ttk.Button(actions,text='仅导入新增条目到本地',command=import_local).pack(side='left');ttk.Button(actions,text='应用到本地 / 导出 EndNote 交换包',command=sync).pack(side='right')
