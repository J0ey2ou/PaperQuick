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
from library_core import Library, FIELDS, DEFAULT_TEMPLATE, validate_template, filename
from download_actions import resolve_download
from graph_view import write_graph
import endnote_sync
from ui_theme import BG, PANEL, SURFACE, FG, MUTED, ACCENT, LINE, FONT, install_theme, emblem, style_dialog

class LibraryWindow:
    def __init__(self, parent, directory, embedded=False):
        self.library = Library(directory)
        self.embedded=embedded
        self.win = tk.Frame(parent,bg=BG) if embedded else tk.Toplevel(parent)
        if not embedded:
            self.win.title('文献直达 · 本地文献库')
            self.win.geometry('1320x920'); self.win.minsize(1120,800)
        install_theme(self.win.winfo_toplevel())
        self.events = queue.Queue(); self.busy = False; self.current_project = None
        self.status = tk.StringVar(value='本地整理与图谱完全离线 · 导入 PDF 保留原文件')
        self.search = tk.StringVar()
        header=ttk.Frame(self.win,padding=(24,12 if embedded else 22,24,10)); header.pack(fill='x')
        if not embedded:emblem(header).pack(side='left',padx=(0,14))
        heading=ttk.Frame(header);heading.pack(side='left')
        ttk.Label(heading,text='文献分类' if embedded else '我的文献库',font=(FONT,21,'bold')).pack(anchor='w')
        ttk.Label(heading,text='PAPERQUICK  /  RESEARCH LIBRARY',foreground=ACCENT,font=('Segoe UI',9,'bold')).pack(anchor='w',pady=(4,0))
        ttk.Button(header,text='文献库文件夹',command=lambda: os.startfile(self.library.root)).pack(side='right')
        ttk.Label(header,text='● 本地工作区',foreground=ACCENT).pack(side='right',padx=20)
        stats=ttk.Frame(self.win,padding=(24,8,24,8));stats.pack(fill='x')
        self.metrics=[]
        for i,(label,hint,color) in enumerate([('总收藏','LIBRARY RECORDS',ACCENT),('已归档 PDF','LOCAL FULL TEXT','#7c9bff'),('已读文献','READING PROGRESS','#65dbb0'),('课题分类','RESEARCH PROJECTS','#bf9afb')]):
            stats.columnconfigure(i,weight=1)
            card=tk.Frame(stats,bg=PANEL,highlightbackground=LINE,highlightthickness=1)
            card.grid(row=0,column=i,sticky='nsew',padx=(0,12 if i<3 else 0))
            tk.Frame(card,bg=color,height=2).pack(fill='x')
            value=tk.StringVar(value='0');self.metrics.append(value)
            tk.Label(card,text=label,bg=PANEL,fg=MUTED,font=(FONT,10),anchor='w').pack(fill='x',padx=18,pady=(12,0))
            tk.Label(card,textvariable=value,bg=PANEL,fg=color,font=('Segoe UI Variable Display',25,'bold'),anchor='w').pack(fill='x',padx=18)
            tk.Label(card,text=hint,bg=PANEL,fg='#647e9b',font=('Segoe UI',8),anchor='w').pack(fill='x',padx=18,pady=(0,12))
        toolbar=ttk.Frame(self.win,padding=(24,10,24,14));toolbar.pack(fill='x')
        self.controls=[]
        for title,command in [('导入 PDF',self.import_pdfs),('导入文件夹',self.import_folder),('新增条目',self.new_record),('命名规则',self.naming),('离线图谱',self.graph),('EndNote 同步',self.endnote)]:
            button=ttk.Button(toolbar,text=title,command=command,style='Accent.TButton' if title=='导入 PDF' else 'TButton');button.pack(side='left',padx=(0,9));self.controls.append(button)
        footer=ttk.Frame(self.win);footer.pack(side='bottom',fill='x')
        body=ttk.Panedwindow(self.win,orient='horizontal');body.pack(fill='both',expand=True,padx=24)
        left=ttk.Frame(body,width=210,padding=14,style='Card.TFrame');right=ttk.Frame(body,padding=(16,10),style='Card.TFrame');body.add(left,weight=0);body.add(right,weight=1)
        ttk.Label(left,text='课题导航',font=(FONT,12,'bold'),style='Card.TLabel').pack(anchor='w',pady=(4,6))
        ttk.Label(left,text='RESEARCH PROJECTS',font=('Segoe UI',8,'bold'),style='CardMuted.TLabel').pack(anchor='w',pady=(0,16))
        self.projects=tk.Listbox(left,exportselection=False,width=22,relief='flat',bg=PANEL,fg=FG,selectbackground='#1c485f',selectforeground=ACCENT,highlightthickness=0,activestyle='none',font=(FONT,11),borderwidth=0);self.projects.pack(fill='both',expand=True)
        self.projects.bind('<<ListboxSelect>>',self.select_project)
        project_button=ttk.Button(left,text='+ 新建课题',command=self.new_project)
        project_button.pack(side='bottom',fill='x',pady=8,before=self.projects)
        filterbar=ttk.Frame(right,style='Card.TFrame');filterbar.pack(fill='x',pady=(2,14))
        self.scope_title=tk.StringVar(value='全部文献')
        ttk.Label(filterbar,textvariable=self.scope_title,font=(FONT,12,'bold'),style='Card.TLabel').pack(side='left',padx=(0,18));ttk.Label(filterbar,text='搜索',style='CardMuted.TLabel').pack(side='left');ttk.Entry(filterbar,textvariable=self.search).pack(side='left',fill='x',expand=True,padx=(10,0))
        self.search.trace_add('write',lambda *_:self.refresh_records())
        columns=('title','year','project','status','pdf')
        self.tree=ttk.Treeview(right,columns=columns,show='headings',selectmode='extended',height=4)
        for key,label,width in zip(columns,('论文标题','年份','主课题','阅读状态','全文'),(450,65,130,90,80)):
            self.tree.heading(key,text=label);self.tree.column(key,width=width,stretch=key=='title')
        self.tree.tag_configure('even',background=PANEL)
        self.tree.tag_configure('odd',background='#132237')
        self.tree.tag_configure('read',foreground='#77ddba')
        scroll=ttk.Scrollbar(right,orient='vertical',command=self.tree.yview);self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
        self.tree.bind('<Double-1>',lambda _:self.open_pdf());self.tree.bind('<<TreeviewSelect>>',self.detail)
        self.context_menu=tk.Menu(self.win,tearoff=False,bg=PANEL,fg=FG,activebackground='#1c485f',activeforeground=ACCENT)
        for title,command in [('下载原文（打开下载页面）',self.download_selected),('下载并自动归档',lambda:self.download_selected(archive=True)),('按规则重新命名',self.rename_selected),('选择所有文献',lambda:self.select_all(False)),('选择所有已下载文献',lambda:self.select_all(True)),('打开 PDF',self.open_pdf),('关联已下载 PDF',self.attach_pdf),('编辑信息',self.edit),('分配课题',self.assign)]:
            self.context_menu.add_command(label=title,command=command)
        self.tree.bind('<Button-3>',self.show_context_menu)
        self.tree.bind('<Control-a>',lambda _:self.select_all(False))
        selection_bar=ttk.Frame(footer,padding=(24,8,24,0));selection_bar.pack(fill='x')
        for title,command in [('选择所有文献',lambda:self.select_all(False)),('选择所有已下载',lambda:self.select_all(True)),('按规则重新命名',self.rename_selected)]:
            b=ttk.Button(selection_bar,text=title,command=command);b.pack(side='left',padx=(0,8));self.controls.append(b)
        actions=ttk.Frame(footer,padding=(24,8,24,8));actions.pack(fill='x')
        for title,command in [('下载原文',self.download_selected),('打开 PDF',self.open_pdf),('关联已下载 PDF',self.attach_pdf),('编辑信息',self.edit),('分配课题',self.assign),('标记已读',lambda:self.mark('已读')),('标记未读',lambda:self.mark('未读'))]:
            button=ttk.Button(actions,text=title,command=command,style='Accent.TButton' if title=='打开 PDF' else 'TButton');button.pack(side='left',padx=(0,9));self.controls.append(button)
        self.details=tk.StringVar(value='选择文献可查看 DOI、摘要和附件位置。')
        detail_card=ttk.Frame(footer,style='Card.TFrame',padding=(16,8));detail_card.pack(fill='x',padx=24)
        ttk.Label(detail_card,text='文献详情  /  PAPER INSIGHT',foreground=ACCENT,background=PANEL,font=(FONT,9,'bold')).pack(anchor='w',pady=(0,5))
        detail_text=tk.Text(detail_card,height=3,wrap='word',bg=PANEL,fg=MUTED,font=(FONT,10),relief='flat',state='disabled')
        detail_text.pack(fill='x')
        def update_details(*_):
            detail_text.configure(state='normal');detail_text.delete('1.0','end');detail_text.insert('1.0',self.details.get());detail_text.configure(state='disabled')
        self.details.trace_add('write',update_details);update_details()
        ttk.Label(footer,textvariable=self.status,padding=(24,8),style='Muted.TLabel').pack(fill='x')
        self.refresh();self.win.after(120,self.poll)
        if not embedded:self.win.protocol('WM_DELETE_WINDOW',self.close)

    def close(self):
        if self.busy:
            self.status.set('操作仍在进行，完成后可关闭。');return
        self.library.close();self.win.destroy()

    def refresh(self):
        previous=self.current_project
        records=self.library.records()
        for value,count in zip(self.metrics,(len(records),sum(bool(r['attachments']) for r in records),sum(r['status']=='已读' for r in records),len(self.library.projects()))):value.set(str(count))
        self.project_rows=self.library.projects();self.projects.delete(0,'end')
        self.projects.insert('end',f'全部文献 ({len(self.library.records())})')
        for p in self.project_rows:
            self.projects.insert('end',f"{p['name']} ({len(self.library.records(p['id']))})")
        index=next((i+1 for i,p in enumerate(self.project_rows) if p['id']==previous),0)
        self.projects.selection_set(index);self.refresh_records()

    def select_project(self,_=None):
        selected=self.projects.curselection()
        if selected:
            self.current_project=self.project_rows[selected[0]-1]['id'] if selected[0] else None
            self.refresh_records()

    def refresh_records(self):
        selected=set(self.tree.selection());self.tree.delete(*self.tree.get_children())
        query=self.search.get().lower()
        self.scope_title.set(self.library.project(self.current_project)['name'] if self.current_project else '全部文献')
        index=0
        for r in self.library.records(self.current_project):
            if query not in ' '.join(str(r.get(k,'')) for k in ('title','doi','authors','keywords')).lower():continue
            self.tree.insert('','end',iid=r['id'],values=(r['title'],r['year'],self.library.project(r['primary_project'])['name'],r['status'],'已归档' if r['attachments'] else '待添加'),tags=('odd' if index%2 else 'even','read' if r['status']=='已读' else ''))
            index+=1
            if r['id'] in selected:self.tree.selection_add(r['id'])

    def selected(self,one=False):
        ids=self.tree.selection()
        if not ids:messagebox.showinfo('选择文献','请先选择一篇文献。',parent=self.win);return None if one else []
        return ids[0] if one else list(ids)

    def detail(self,_=None):
        if not self.tree.selection():return
        r=self.library.get(self.tree.selection()[0]);names=' / '.join(self.library.project(p)['name'] for p in r['projects'])
        self.details.set(f"{r['authors'][:150]} · DOI: {r['doi'] or '待补充'}\n课题：{names}\n{r['abstract'][:220] or '摘要待补充'}")

    def run(self,title,work,done=None):
        if self.busy:return
        self.busy=True;self.status.set(title+'…')
        for b in self.controls:b.configure(state='disabled')
        def job():
            lib=None
            try:
                lib=Library(self.library.root);result=work(lib);self.events.put(('ok',result,done))
            except Exception as exc:self.events.put(('error',str(exc),None))
            finally:
                if lib:lib.close()
        threading.Thread(target=job,daemon=True).start()

    def poll(self):
        try:
            while True:
                kind,result,done=self.events.get_nowait();self.busy=False
                for b in self.controls:b.configure(state='normal')
                self.refresh()
                if kind=='error':
                    self.status.set('操作未完成：'+result);messagebox.showerror('操作未完成',result,parent=self.win)
                else:
                    self.status.set(str(result) if not done else '操作完成')
                    if done:done(result)
        except queue.Empty:pass
        if self.win.winfo_exists():self.win.after(1000 if self.win.winfo_toplevel().state()=='withdrawn' and not self.busy else 120,self.poll)

    def choose_project(self,callback,title='选择归档课题'):
        dialog=tk.Toplevel(self.win);style_dialog(dialog);dialog.title(title);dialog.transient(self.win)
        panel=ttk.Frame(dialog,padding=20);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='选择课题，或输入新课题名称（自动新建文件夹）').pack(anchor='w')
        value=tk.StringVar(value=self.library.project(self.current_project)['name'] if self.current_project else self.library.projects()[0]['name'])
        combo=ttk.Combobox(panel,textvariable=value,values=[p['name'] for p in self.library.projects()],width=45);combo.pack(fill='x',pady=12)
        def accept():
            try:pid=self.library.create_project(value.get())
            except Exception as exc:messagebox.showerror('课题',str(exc),parent=dialog);return
            dialog.destroy();self.refresh();callback(pid)
        ttk.Button(panel,text='确认',command=accept).pack(anchor='e')

    def new_project(self):self.choose_project(lambda pid:None,'新建课题')

    def import_pdfs(self):
        paths=filedialog.askopenfilenames(parent=self.win,title='选择 PDF（复制原文件）',filetypes=[('PDF','*.pdf')])
        if paths:self.choose_project(lambda pid:self.batch_import(paths,pid))

    def import_folder(self):
        folder=filedialog.askdirectory(parent=self.win,title='导入文件夹中的 PDF（包含子目录）')
        if folder:
            paths=list(Path(folder).rglob('*.pdf'))
            if not paths:messagebox.showinfo('没有 PDF','该文件夹中没有 PDF。',parent=self.win);return
            self.choose_project(lambda pid:self.batch_import(paths,pid))

    def batch_import(self,paths,pid):
        def work(lib):
            count=0;errors=[]
            for path in paths:
                try:lib.import_pdf(path,pid);count+=1
                except Exception as exc:errors.append(f'{Path(path).name}: {exc}')
            return f'已导入 / 关联 {count} 个 PDF。'+ ('\n失败：\n'+'\n'.join(errors[:10]) if errors else '')
        self.run('正在本地解析与归档',work,lambda result:messagebox.showinfo('导入完成',result,parent=self.win))

    def show_context_menu(self,event):
        rid=self.tree.identify_row(event.y)
        if not rid:return
        if rid not in self.tree.selection():self.tree.selection_set(rid)
        self.tree.focus(rid);self.detail()
        for index in range(self.context_menu.index('end')+1):
            self.context_menu.entryconfigure(index,state='disabled' if self.busy else 'normal')
        try:self.context_menu.tk_popup(event.x_root,event.y_root)
        finally:self.context_menu.grab_release()

    def select_all(self,downloaded=False):
        if self.busy:return 'break'
        self.current_project=None;self.search.set('');self.refresh()
        ids=[r['id'] for r in self.library.records() if not downloaded or r['attachments']]
        self.tree.selection_set(ids)
        self.status.set(f'已选择全库 {len(ids)} 篇'+('已下载文献' if downloaded else '文献')+'；可点击“按规则重新命名”。')
        return 'break'

    def rename_selected(self):
        if self.busy:return
        ids=self.selected()
        if not ids:return
        records=[self.library.get(rid) for rid in ids];downloaded=[r for r in records if r['attachments']]
        if not downloaded:self.status.set('所选文献尚未下载 PDF，没有文件可重命名。');return
        preview=[]
        for r in downloaded[:6]:
            preview.append(Path(r['attachments'][0]['path']).name+'\n→ '+self.library.target(r).name)
        skipped=len(records)-len(downloaded)
        if not messagebox.askyesno('按规则重新命名',f'将对 {len(downloaded)} 篇文献的已归档附件应用各自主课题的命名规则。\n未下载的 {skipped} 篇跳过；原始导入文件不改动。\n\n'+'\n\n'.join(preview)+'\n\n同名文件会自动添加后缀。继续？',parent=self.win):return
        def work(lib):
            count=0;errors=[]
            for r in downloaded:
                try:count+=len(lib.rename(r['id']))
                except Exception as exc:errors.append(r['title'][:60]+': '+str(exc))
            return f'已处理 {count} 个附件；跳过 {skipped} 篇无 PDF 文献。'+ ('\n未完成：\n'+'\n'.join(errors[:8]) if errors else '')
        self.run('正在按规则重新命名',work,lambda result:messagebox.showinfo('重命名完成',result,parent=self.win))

    def download_selected(self,archive=False):
        if self.busy:self.status.set('下载 / 归档仍在进行，请等待完成。');return
        rid=self.selected(True)
        if rid:self.start_download(rid,lookup=True,open_page=not archive)

    def start_download(self,rid,read_after=False,preferred_url=None,lookup=False,open_page=False):
        if self.busy:self.status.set('下载 / 归档仍在进行，请等待完成。');return
        def done(result):
            if result['kind'] in ('downloaded','existing'):
                self.status.set(('已归档：' if result['kind']=='downloaded' else '已有归档 PDF：')+result['path'])
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
        attachments=self.library.get(rid)['attachments']
        if not attachments:self.status.set('此条目尚无 PDF，可关联已下载文件。');return
        if getattr(self,'on_reader',None):self.on_reader(rid);return
        try:os.startfile(self.library.root/attachments[0]['path'])
        except OSError as exc:messagebox.showerror('打开失败',str(exc),parent=self.win)

    def new_record(self):self.edit_record(None)
    def edit(self):
        rid=self.selected(True)
        if rid:self.edit_record(rid)

    def edit_record(self,rid):
        data=self.library.get(rid) if rid else {}
        dialog=tk.Toplevel(self.win);style_dialog(dialog);dialog.title('编辑文献信息');dialog.transient(self.win)
        panel=ttk.Frame(dialog,padding=18);panel.pack(fill='both',expand=True);variables={}
        labels=('标题','作者（换行或分号分隔）','年份','DOI','期刊','摘要','关键词','笔记','阅读状态')
        for field,label in zip(FIELDS,labels):
            ttk.Label(panel,text=label).pack(anchor='w');widget=tk.Text(panel,height=3 if field in ('abstract','notes') else 1,width=82,wrap='word');widget.insert('1.0',data.get(field,'未读' if field=='status' else ''));widget.pack(fill='x',pady=(2,7));variables[field]=widget
        def save():
            values={f:w.get('1.0','end').strip() for f,w in variables.items()}
            if not values['title']:messagebox.showerror('标题','请填写标题。',parent=dialog);return
            self.library.save(values,self.current_project,rid);dialog.destroy();self.refresh()
        ttk.Button(panel,text='保存',command=save).pack(anchor='e')

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
        dialog=tk.Toplevel(self.win);style_dialog(dialog);dialog.title('自动命名规则');panel=ttk.Frame(dialog,padding=20);panel.pack(fill='both')
        scope=self.current_project
        ttk.Label(panel,text='当前课题规则' if scope else '全库默认规则',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        ttk.Label(panel,text='支持 {年份} {第一作者} {标题} {DOI} {课题}；文字、空格、下划线可直接填写。\n新导入时自动命名；已归档文件只在点击“批量应用”后重命名。').pack(anchor='w',pady=10)
        template=tk.StringVar(value=self.library.template(scope) if scope else self.library.setting('template',DEFAULT_TEMPLATE))
        ttk.Entry(panel,textvariable=template,width=70).pack(fill='x')
        length=tk.StringVar(value=str(self.library.setting('title_length',80)));ttk.Label(panel,text='标题最大字符数（20–120）').pack(anchor='w',pady=(10,3));ttk.Entry(panel,textvariable=length,width=8).pack(anchor='w')
        result=tk.StringVar();ttk.Label(panel,textvariable=result,wraplength=600).pack(anchor='w',pady=12)
        def values():
            validate_template(template.get());n=int(length.get())
            if not 20<=n<=120:raise ValueError('标题长度应在 20–120 之间。')
            return template.get(),n
        def preview(*_):
            try:
                t,n=values();records=self.library.records(scope);sample=records[0] if records else {'title':'Example research paper','authors':'Wang, Li','year':'2026'}
                result.set('示例：'+filename(sample,self.library.project(scope)['name'] if scope else '示例课题',t,n))
            except Exception as exc:result.set(str(exc))
        template.trace_add('write',preview);length.trace_add('write',preview);preview()
        def save(batch=False):
            try:t,n=values()
            except Exception as exc:messagebox.showerror('模板',str(exc),parent=dialog);return
            if batch:
                records=self.library.records(scope)
                sample='\n'.join(f"{r['attachments'][0]['path']}\n→ {filename(r,self.library.project(r['primary_project'])['name'],t,n)}" for r in records[:8] if r['attachments'])
                if not messagebox.askyesno('重命名预览',sample+'\n\n确认对当前范围全部附件应用？原始导入文件保持不变。',parent=dialog):return
            if scope:
                with self.library.db:self.library.db.execute('UPDATE projects SET template=? WHERE id=?',(t,scope))
            else:self.library.set_setting('template',t)
            self.library.set_setting('title_length',n);dialog.destroy()
            if batch:self.run('重命名已归档 PDF',lambda lib:sum(len(lib.rename(r['id'])) for r in lib.records(scope)),lambda count:self.status.set(f'已重命名 {count} 个文件；操作记录保存在本地数据库。'))
        buttons=ttk.Frame(panel);buttons.pack(fill='x');ttk.Button(buttons,text='保存（用于后续导入）',command=save).pack(side='left');ttk.Button(buttons,text='预览并批量应用',command=lambda:save(True)).pack(side='right')

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
