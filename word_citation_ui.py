"""Choose library papers and maintain Word citations without leaving local storage."""
from pathlib import Path
import queue,threading,webbrowser
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from library_core import Library
from citation_metadata import quality_warnings,fetch_doi_metadata
from citation_styles import list_styles,import_style
from word_citations import plan_changes,citation_label
import word_bridge
from ui_theme import FONT,style_dialog,apply_skin,CURRENT_SKIN


class WordCitationsWindow:
    def __init__(self,parent,directory,selected=None,on_library_changed=None):
        self.directory=Path(directory);self.custom_dir=self.directory/'citation-styles';self.on_library_changed=on_library_changed
        self.win=tk.Toplevel(parent);self.win.title('Word 引用 · 文献直达');self.win.geometry('1060x810');self.win.minsize(940,700);self.win.transient(parent.winfo_toplevel());style_dialog(self.win)
        self.busy=False;self.closed=False;self.snapshot=None;self.events=queue.Queue();self.content_records={}
        frame=ttk.Frame(self.win,padding=22);frame.pack(fill='both',expand=True);frame.columnconfigure(0,weight=1);frame.rowconfigure(3,weight=1)
        header=ttk.Frame(frame);header.grid(row=0,column=0,sticky='ew');ttk.Label(header,text='让引用跟着写作走',style='Hero.TLabel').pack(side='left')
        self.connect_button=ttk.Button(header,text='连接 / 重新读取 Word',command=self.connect);self.connect_button.pack(side='right')
        self.target=tk.StringVar(value='先在桌面版 Word 中打开文档、放好光标，再点击右侧连接。')
        ttk.Label(frame,textvariable=self.target,style='Muted.TLabel',wraplength=990).grid(row=1,column=0,sticky='ew',pady=(8,16))
        bar=ttk.Frame(frame);bar.grid(row=2,column=0,sticky='ew',pady=(0,16));ttk.Label(bar,text='引用格式').pack(side='left',padx=(0,10))
        self.style=tk.StringVar();self.style_box=ttk.Combobox(bar,textvariable=self.style,state='readonly',width=48);self.style_box.pack(side='left',fill='x',expand=True)
        ttk.Button(bar,text='导入期刊样式',command=self.add_style).pack(side='left',padx=8)
        ttk.Button(bar,text='更多期刊格式 ↗',command=lambda:webbrowser.open('https://www.zotero.org/styles')).pack(side='left')
        self.tabs=ttk.Notebook(frame);self.tabs.grid(row=3,column=0,sticky='nsew')
        choose=ttk.Frame(self.tabs,padding=(0,12));document=ttk.Frame(self.tabs,padding=(0,12));self.tabs.add(choose,text='选择文献');self.tabs.add(document,text='文档中的引文')
        choose.columnconfigure(0,weight=1);choose.rowconfigure(1,weight=1)
        filters=ttk.Frame(choose);filters.grid(row=0,column=0,sticky='ew',pady=(0,9));self.project=tk.StringVar(value='全部课题');self.search=tk.StringVar()
        self.project_box=ttk.Combobox(filters,textvariable=self.project,state='readonly',width=19);self.project_box.pack(side='left');self.project_box.bind('<<ComboboxSelected>>',lambda _:self.filter_records())
        ttk.Label(filters,text='搜索').pack(side='left',padx=10);ttk.Entry(filters,textvariable=self.search).pack(side='left',fill='x',expand=True);self.search.trace_add('write',lambda *_:self.filter_records())
        area=ttk.Frame(choose);area.grid(row=1,column=0,sticky='nsew');self.tree=self._tree(area,('title','authors','year'),('论文标题','作者','年份'),(470,260,60),multiple=True)
        self.tree.bind('<<TreeviewSelect>>',lambda _:self.describe_selection())
        self.details=tk.StringVar(value='支持 Ctrl / Shift 多选，将多篇文献合并到一处引文。')
        ttk.Label(choose,textvariable=self.details,style='Muted.TLabel',wraplength=980).grid(row=2,column=0,sticky='ew',pady=(10,0))
        document.columnconfigure(0,weight=1);document.rowconfigure(1,weight=1)
        ttk.Label(document,text='这些引文由文献直达插入。可以替换所引文献，或删除一处后重新整理编号。',style='Muted.TLabel',wraplength=960).grid(row=0,column=0,sticky='ew',pady=(0,9))
        area=ttk.Frame(document);area.grid(row=1,column=0,sticky='nsew');self.doc_tree=self._tree(area,('order','title'),('顺序','引用的文献'),(70,770))
        edits=ttk.Frame(document);edits.grid(row=2,column=0,sticky='ew',pady=(10,0))
        ttk.Button(edits,text='用所选文献替换这处引文',command=lambda:self.execute('replace')).pack(side='left')
        ttk.Button(edits,text='删除这处引文',command=lambda:self.execute('remove')).pack(side='left',padx=8)
        ttk.Button(edits,text='查看格式预览',command=lambda:self.execute('document_preview')).pack(side='right')
        actions=ttk.Frame(frame);actions.grid(row=4,column=0,sticky='ew',pady=(14,8))
        self.insert_button=ttk.Button(actions,text='插入正文引文',style='Accent.TButton',command=lambda:self.execute('insert'));self.insert_button.pack(side='left')
        ttk.Label(actions,text='引用页码（可选）').pack(side='left',padx=(14,8));self.locator=tk.StringVar();ttk.Entry(actions,textvariable=self.locator,width=11).pack(side='left')
        ttk.Button(actions,text='编辑文献信息',command=self.edit_metadata).pack(side='right');ttk.Button(actions,text='按 DOI 补全信息',command=self.enrich).pack(side='right',padx=8)
        actions=ttk.Frame(frame);actions.grid(row=5,column=0,sticky='ew')
        ttk.Button(actions,text='生成 / 更新参考文献表',command=lambda:self.execute('bibliography')).pack(side='left')
        ttk.Button(actions,text='更新全部引用 / 切换格式',command=lambda:self.execute('refresh')).pack(side='left',padx=8)
        ttk.Button(actions,text='预览所选文献',command=lambda:self.execute('preview')).pack(side='right')
        self.status=tk.StringVar(value='参考文献表插在 Word 光标处。移动或删除正文引文后，点“更新全部引用”整理编号。')
        ttk.Label(frame,textvariable=self.status,style='Muted.TLabel',wraplength=980).grid(row=6,column=0,sticky='ew',pady=(12,0))
        credit=ttk.Label(frame,text='citeproc-js implements the Citation Style Language · © Frank Bennett  ↗',style='Muted.TLabel',cursor='hand2')
        credit.grid(row=7,column=0,sticky='w',pady=(8,0));credit.bind('<Button-1>',lambda _:webbrowser.open('https://citationstyles.org/'))
        self.load_records();self.load_styles();self.tree.selection_set([rid for rid in selected or [] if self.tree.exists(rid)])
        self.win.protocol('WM_DELETE_WINDOW',self.close);self.win.bind('<Escape>',lambda _:self.close());self.poll_id=self.win.after(120,self.poll)
        apply_skin(parent.winfo_toplevel(),getattr(parent.winfo_toplevel(),'_paperquick_theme',CURRENT_SKIN))

    def _tree(self,parent,columns,labels,widths,multiple=False):
        tree=ttk.Treeview(parent,columns=columns,show='headings',height=4,selectmode='extended' if multiple else 'browse')
        for key,label,width in zip(columns,labels,widths):tree.heading(key,text=label);tree.column(key,width=width,minwidth=50,stretch=key=='title')
        scroll=ttk.Scrollbar(parent,command=tree.yview);scroll.pack(side='right',fill='y');tree.configure(yscrollcommand=scroll.set);tree.pack(fill='both',expand=True);return tree
    def _library(self,callback):
        lib=Library(self.directory)
        try:return callback(lib)
        finally:lib.close()
    def load_records(self):
        self.records,self.projects=self._library(lambda lib:(lib.records(),lib.projects()));self.content_records={r['id']:r for r in self.records};self.project_box.configure(values=['全部课题']+[p['name'] for p in self.projects]);self.filter_records()
    def filter_records(self):
        selected=self.tree.selection();self.tree.delete(*self.tree.get_children());pid=next((p['id'] for p in self.projects if p['name']==self.project.get()),None);term=self.search.get().casefold().strip()
        for r in self.records:
            if pid and pid not in r['projects']:continue
            if term and term not in ' '.join(str(r.get(k,'')) for k in ('title','doi','authors','year')).casefold():continue
            self.tree.insert('','end',iid=r['id'],values=(r['title'],r.get('authors',''),r.get('year','')))
        self.tree.selection_set([rid for rid in selected if self.tree.exists(rid)])
    def load_styles(self,preferred=None):
        styles=list_styles(custom_dir=self.custom_dir);self.styles={s['title']:s for s in styles if s.get('style_class')!='note'};self.style_box.configure(values=list(self.styles))
        saved=preferred or self._library(lambda lib:lib.setting('word_citation_style',''))
        chosen=next((title for title,s in self.styles.items() if s['id']==saved),None)
        self.style.set(chosen or next(iter(self.styles),''))
    def selected_records(self):return [self.content_records[rid] for rid in self.tree.selection() if rid in self.content_records]
    def describe_selection(self):
        records=self.selected_records()
        if not records:return
        warnings=quality_warnings(records[0]) if len(records)==1 else []
        self.details.set(f'已选择 {len(records)} 篇。'+('；'.join(warnings) if warnings else '可以直接插入，或先预览引用格式。'))
    def _run(self,work,done):
        if self.busy:self.status.set('正在处理 Word 引用，请稍候。');return
        self.busy=True;self.status.set('正在处理，请稍候…')
        def worker():
            try:self.events.put(('ok',work(),done))
            except Exception as exc:self.events.put(('error',str(exc),None))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        if self.closed:return
        try:
            while True:
                kind,result,done=self.events.get_nowait();self.busy=False
                if kind=='error':self.status.set(result or '操作未完成，请重试。')
                else:
                    try:done(result)
                    except Exception as exc:self.status.set(str(exc) or '显示结果时遇到问题，请重新连接 Word。')
        except queue.Empty:pass
        self.poll_id=self.win.after(120,self.poll)
    def connect(self):self._run(word_bridge.snapshot,self.show_document)
    def show_document(self,snapshot):
        ids=[f['id'] for f in snapshot['fields']]
        if len(ids)!=len(set(ids)):
            self.snapshot=None;self.doc_tree.delete(*self.doc_tree.get_children())
            self.target.set('文档中发现了复制后重复的引文。')
            self.status.set('请先在 Word 中撤销复制，或删除重复副本，再通过“插入正文引文”添加到新位置，然后重新连接。');return
        self.snapshot=snapshot;doc=snapshot['document'];count=sum(f['kind']=='citation' for f in snapshot['fields'])
        saved_style=next((f.get('payload',{}).get('style_id') for f in snapshot['fields'] if f.get('payload',{}).get('style_id')),None)
        if saved_style:
            found=next((title for title,s in self.styles.items() if s['id']==saved_style),None)
            if found:self.style.set(found)
        self.target.set('已连接：'+doc.get('name',doc.get('full_name','Word 文档'))+f'  ·  {count} 处引文')
        self.doc_tree.delete(*self.doc_tree.get_children())
        for index,field in enumerate((f for f in snapshot['fields'] if f['kind']=='citation'),1):self.doc_tree.insert('','end',iid=field['id'],values=(index,citation_label(field)))
        self.status.set('连接成功。插入前可回到 Word 调整光标位置；插入后仍可用 Word 的撤销操作。')
    def execute(self,action):
        if self.busy:return
        style=self.styles.get(self.style.get())
        if not style:self.status.set('请选择引用格式。');return
        if action!='preview' and self.snapshot is None:self.status.set('先打开 Word 文档，再点击“连接 / 重新读取 Word”。');return
        selected=self.selected_records();target=self.doc_tree.selection();target_id=target[0] if target else None;locator=self.locator.get()
        if action=='remove' and target_id and not messagebox.askyesno('删除这处引文','删除所选正文引文，并更新其余编号和参考文献表？可以在 Word 中撤销。',parent=self.win):return
        expected=self.snapshot;records=list(self.records);style_id=style['id']
        def work():
            if action=='preview':
                snapshot={'fields':[],'selection':{'start':0,'end':0}};_,formatted=plan_changes(snapshot,records,style_id,'insert',selected,locator=locator,custom_dir=self.custom_dir);return formatted
            if action=='document_preview':
                if not any(f['kind']=='citation' for f in expected['fields']):raise ValueError('文档中还没有文献直达插入的引文。')
                _,formatted=plan_changes(expected,records,style_id,'refresh',custom_dir=self.custom_dir);return formatted
            fresh=word_bridge.snapshot()
            if fresh['document']!=expected['document']:raise ValueError('Word 当前显示的文档已改变。请重新连接，确认文档名称后再插入。')
            operations,formatted=plan_changes(fresh,records,style_id,action,selected,target_id,locator,custom_dir=self.custom_dir)
            result=word_bridge.apply(fresh,operations)
            try:self._library(lambda lib:lib.set_setting('word_citation_style',style_id))
            except Exception:result['_preference_warning']=True
            return result
        def done(result):
            if action in ('preview','document_preview'):self.preview(result);self.status.set('格式预览已生成，可以核对后再插入或更新 Word。');return
            self.show_document(result);self.status.set('引用已更新。修改已保留在打开的 Word 文档中，请按平时习惯保存文档。')
            if result.get('_preference_warning'):self.status.set('Word 引用已更新。常用格式偏好未能保存，下次请重新选择格式；请照常保存 Word 文档。')
        self._run(work,done)
    def preview(self,result):
        dialog=tk.Toplevel(self.win);dialog.title('引用格式预览');dialog.geometry('780x540');style_dialog(dialog)
        dialog.columnconfigure(0,weight=1);dialog.rowconfigure(0,weight=1)
        text=tk.Text(dialog,wrap='word',font=(FONT,11),padx=22,pady=20);text.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(dialog,command=text.yview);scroll.grid(row=0,column=1,sticky='ns');text.configure(yscrollcommand=scroll.set)
        citations=result.get('plain_citations',{});bibliography=result.get('plain_bibliography','')
        if not citations and not bibliography:content='格式已经生成。插入 Word 后可查看完整排版。'
        else:content='正文引文\n\n'+'\n'.join(citations.values())+'\n\n参考文献\n\n'+bibliography
        text.insert('1.0',content);text.configure(state='disabled');ttk.Label(dialog,text='文字预览用于核对信息，斜体、上标及段落格式以 Word 中的显示为准。',style='Muted.TLabel',padding=12,wraplength=720).grid(row=1,column=0,columnspan=2,sticky='ew')
    def add_style(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self.win,title='选择 CSL 期刊格式',filetypes=[('CSL 引用样式','*.csl')])
        if not path:return
        try:
            identifier=import_style(path,self.custom_dir);self.load_styles(identifier)
            if not any(s['id']==identifier for s in self.styles.values()):self.status.set('这个样式采用脚注或尾注，本版暂不支持。请选择正文编号或作者年份格式。')
            else:self.status.set('期刊样式已加入，可从引用格式列表选择。')
        except Exception as exc:self.status.set(str(exc))
    def edit_metadata(self):
        if self.busy:return
        records=self.selected_records()
        if len(records)!=1:self.status.set('先选择一篇文献，再编辑信息。');return
        record=records[0];dialog=tk.Toplevel(self.win);dialog.title('核对引用信息');dialog.geometry('760x740');dialog.transient(self.win);style_dialog(dialog)
        panel=ttk.Frame(dialog,padding=22);panel.pack(fill='both',expand=True);panel.columnconfigure(1,weight=1);values={}
        fields=[('title','标题'),('authors','作者（多人用分号分隔）'),('year','年份'),('venue','期刊 / 书名'),('volume','卷'),('issue','期'),('pages','页码 / 文章号'),('doi','DOI'),('publisher','出版社'),('edition','版次')]
        for row,(key,label) in enumerate(fields):
            ttk.Label(panel,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=5);variable=tk.StringVar(value=record.get(key,''));values[key]=variable;ttk.Entry(panel,textvariable=variable).grid(row=row,column=1,sticky='ew',pady=5)
        types={'期刊论文':'article-journal','图书':'book','书中章节':'chapter','会议论文':'paper-conference','学位论文':'thesis','报告':'report','网页':'webpage','数据集':'dataset'}
        kind=tk.StringVar(value=next((label for label,value in types.items() if value==record.get('type')),'期刊论文'))
        ttk.Label(panel,text='文献类型').grid(row=len(fields),column=0,sticky='w',pady=5);ttk.Combobox(panel,textvariable=kind,values=list(types),state='readonly').grid(row=len(fields),column=1,sticky='ew',pady=5)
        ttk.Label(panel,text='准确的作者、年份、卷期与页码，才能生成完整的参考文献。',style='Muted.TLabel').grid(row=len(fields)+1,column=0,columnspan=2,sticky='w',pady=12)
        def save():
            data={key:variable.get().strip() for key,variable in values.items()}
            data['type']=types[kind.get()]
            if not data['title']:messagebox.showinfo('填写标题','请填写文献标题。',parent=dialog);return
            if data['authors']!=record.get('authors',''):data['authors_structured']=[]
            if data['year']!=record.get('year',''):data['issued']=None
            if data['doi']!=record.get('doi',''):data['DOI']=data['doi']
            self._library(lambda lib:lib.save(data,rid=record['id']));self.load_records();self.tree.selection_set(record['id']);dialog.destroy();self.status.set('文献信息已保存，点击“更新全部引用”即可同步到 Word。')
            if self.on_library_changed:self.on_library_changed()
        ttk.Button(panel,text='保存信息',style='Accent.TButton',command=save).grid(row=len(fields)+2,column=1,sticky='e')
    def enrich(self):
        records=self.selected_records()
        if len(records)!=1:self.status.set('先选择一篇文献，再按 DOI 补全。');return
        record=records[0]
        if not record.get('doi'):self.status.set('这篇文献还没有 DOI，可以先编辑信息手动补充。');return
        def work():return fetch_doi_metadata(record['doi'])
        def done(data):
            self._library(lambda lib:lib.save(data,rid=record['id']));self.load_records();self.tree.selection_set(record['id']);self.status.set('已从 Crossref 补全引用信息。请核对后插入或更新 Word 引用。')
            if self.on_library_changed:self.on_library_changed()
        self._run(work,done)
    def close(self):
        if self.busy:self.status.set('Word 引用仍在处理，完成后即可关闭。');return False
        self.closed=True
        try:self.win.after_cancel(self.poll_id)
        except tk.TclError:pass
        self.win.destroy();return True
