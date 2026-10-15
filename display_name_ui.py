"""Editable, display-only naming preview with optional explicit DOI completion."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from library_core import display_name, filename
from display_renaming import FIELDS,display_template,display_name_from_rule
from metadata_renaming import NAMES
from ui_theme import style_dialog, FONT


class DisplayNameDialog:
    def __init__(self,parent,library,plans,on_apply):
        self.library=library;self.plans={p['id']:p for p in plans};self.on_apply=on_apply
        self.active=None;self.events=queue.Queue();self.closed=False;self.lookup_pending=False
        self.win=tk.Toplevel(parent);style_dialog(self.win);self.win.title('识别 / 修改软件中的文献名称')
        width=min(1040,max(640,self.win.winfo_screenwidth()-80));height=min(790,max(480,self.win.winfo_screenheight()-120))
        self.win.geometry(f'{width}x{height}');self.win.minsize(min(760,width),min(480,height))
        # Allocate the footer first so DPI scaling and long forms cannot hide Save.
        self.footer=ttk.Frame(self.win,padding=(18,8,18,12));self.footer.pack(side='bottom',fill='x')
        self.feedback=tk.StringVar(value='识别结果尚未保存；核对后点击右下角“确认保存显示名称”。')
        self.feedback_label=ttk.Label(self.footer,textvariable=self.feedback,style='Muted.TLabel',wraplength=900)
        self.feedback_label.pack(fill='x',pady=(0,6))
        self.footer.bind('<Configure>',lambda e:self.feedback_label.configure(wraplength=max(300,e.width-40)))
        actions=ttk.Frame(self.footer);actions.pack(fill='x')
        ttk.Button(actions,text='取消',command=self.close).pack(side='left')
        self.save_button=ttk.Button(actions,text='确认保存显示名称',command=self.accept,style='Accent.TButton');self.save_button.pack(side='right')
        content=ttk.Frame(self.win);content.pack(fill='both',expand=True)
        self.viewport=tk.Canvas(content,highlightthickness=0,borderwidth=0,bg=ui_background())
        body_scroll=ttk.Scrollbar(content,orient='vertical',command=self.viewport.yview);body_scroll.pack(side='right',fill='y')
        self.viewport.configure(yscrollcommand=body_scroll.set);self.viewport.pack(fill='both',expand=True)
        panel=ttk.Frame(self.viewport,padding=18)
        self.panel=panel;panel_id=self.viewport.create_window(0,0,window=panel,anchor='nw')
        panel.bind('<Configure>',lambda _:self.viewport.configure(scrollregion=self.viewport.bbox('all')))
        self.viewport.bind('<Configure>',lambda e:self.viewport.itemconfigure(panel_id,width=e.width))
        ttk.Label(panel,text='仅修改软件显示名称，不修改任何附件文件名',font=(FONT,12,'bold')).pack(anchor='w')
        ttk.Label(panel,text='先选中文献，核对或编辑名称。识别失败也可手动保存；取消不会改动文献。',style='Muted.TLabel').pack(anchor='w',pady=8)
        table=ttk.Frame(panel);table.pack(fill='x')
        self.tree=ttk.Treeview(table,columns=('old','new'),show='headings',height=min(4,max(1,len(plans))),selectmode='browse')
        self.tree.heading('old',text='原显示名称');self.tree.heading('new',text='将保存的显示名称')
        for column in ('old','new'):self.tree.column(column,width=440)
        scroll=ttk.Scrollbar(table,command=self.tree.yview);scroll.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scroll.set);self.tree.pack(fill='both',expand=True)
        self.name=tk.StringVar();self.vars={key:tk.StringVar() for key in FIELDS};self.sync=tk.BooleanVar(value=False)
        ttk.Label(panel,text='文献显示名称（可直接编辑）',font=(FONT,11,'bold')).pack(anchor='w',pady=(12,5))
        ttk.Entry(panel,textvariable=self.name).pack(fill='x')
        editor=ttk.Frame(panel);editor.pack(fill='x',pady=8);editor.columnconfigure(1,weight=1)
        for i,key in enumerate(FIELDS):
            ttk.Label(editor,text=NAMES[key]).grid(row=i,column=0,sticky='w',padx=(0,12),pady=3)
            ttk.Entry(editor,textvariable=self.vars[key]).grid(row=i,column=1,sticky='ew',pady=3)
        buttons=ttk.Frame(panel);buttons.pack(fill='x')
        ttk.Button(buttons,text='用论文标题作为名称',command=self.from_title).pack(side='left')
        ttk.Button(buttons,text='按命名规则生成预览',command=self.from_rule).pack(side='left',padx=8)
        self.doi_button=ttk.Button(buttons,text='通过 DOI 联网补全',command=self.lookup);self.doi_button.pack(side='left')
        ttk.Checkbutton(panel,text='同时保存上方核对后的论文信息（标题、作者、期刊、年份和 DOI）',variable=self.sync).pack(anchor='w',pady=8)
        self.evidence=tk.Text(panel,height=5,wrap='word',font=(FONT,9));self.evidence.pack(fill='x');self.evidence.configure(state='disabled')
        def scroll_form(event):
            self.viewport.yview_scroll(-int(event.delta/120),'units');return 'break'
        def bind_scroll(widget):
            if not isinstance(widget,(tk.Text,ttk.Treeview)):widget.bind('<MouseWheel>',scroll_form,add='+')
            for child in widget.winfo_children():bind_scroll(child)
        bind_scroll(panel);self.viewport.bind('<MouseWheel>',scroll_form)
        for plan in plans:self.tree.insert('','end',iid=plan['id'],values=(display_name(plan['before']),plan['display_name']))
        self.tree.bind('<<TreeviewSelect>>',self.select)
        self.name.trace_add('write',self.name_changed)
        if plans:self.tree.selection_set(plans[0]['id']);self.select()
        self.win.protocol('WM_DELETE_WINDOW',self.close);self.job=self.win.after(100,self.poll)

    def persist(self):
        if not self.active:return
        plan=self.plans[self.active];plan['display_name']=self.name.get();plan['fields']={k:v.get() for k,v in self.vars.items()};plan['sync_metadata']=self.sync.get()

    def select(self,_=None):
        chosen=self.tree.selection()
        if not chosen or chosen[0]==self.active:return
        self.persist();self.active=chosen[0];self.load_active()

    def load_active(self):
        plan=self.plans[self.active];self.name.set(plan['display_name']);self.sync.set(plan.get('sync_metadata',False))
        for key,var in self.vars.items():var.set(plan['fields'].get(key,''))
        text='\n'.join(f"{NAMES[k]}：识别 {plan['sources'].get(k,'未识别，暂沿用库中信息')}；库中原值：{plan['before'].get(k) or '空'}" for k in FIELDS)
        if plan['warnings']:text+='\n'+'；'.join(plan['warnings'])
        self.evidence.configure(state='normal');self.evidence.delete('1.0','end');self.evidence.insert('1.0',text);self.evidence.configure(state='disabled')

    def name_changed(self,*_):
        if self.active:
            self.plans[self.active]['display_name']=self.name.get()
            self.tree.set(self.active,'new',self.name.get())

    def from_rule(self):
        if not self.active:return
        record=dict(self.plans[self.active]['before'],**{k:v.get() for k,v in self.vars.items()})
        project=self.library.project(record['primary_project'])
        try:value=display_name_from_rule(record,project['name'],display_template(self.library,project['id']),self.library.setting('display_title_length',500))
        except (ValueError,TypeError) as exc:self.feedback.set('无法生成名称：'+str(exc));return
        self.preview_name(value)

    def from_title(self):
        self.preview_name(self.vars['title'].get())

    def preview_name(self,value):
        unchanged=value==self.name.get();self.name.set(value)
        self.feedback.set(('生成的名称与当前预览相同。' if unchanged else '显示名称预览已更新。')+'请点击右下角“确认保存显示名称”完成更改。')

    def lookup(self):
        if not self.active or self.lookup_pending:return
        self.persist();rid=self.active;doi=self.vars['doi'].get().strip()
        if not doi:self.feedback.set('请先填写这篇文献的 DOI，再点击补全。');return
        self.lookup_pending=True;self.doi_button.configure(state='disabled');self.feedback.set('正在查询 DOI 对应的文献信息；结果仍可修改。')
        def work():
            from citation_metadata import fetch_doi_metadata
            try:self.events.put((rid,doi,fetch_doi_metadata(doi),None))
            except Exception as exc:self.events.put((rid,doi,None,str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        if self.closed:return
        try:
            rid,doi,result,error=self.events.get_nowait();self.lookup_pending=False;self.doi_button.configure(state='normal');self.persist()
            if error:self.feedback.set(error)
            elif self.plans[rid]['fields'].get('doi','').strip()!=doi:self.feedback.set('DOI 已变化，未套用旧查询结果。')
            else:
                plan=self.plans[rid]
                for key in FIELDS:
                    if result.get(key):plan['fields'][key]=result[key];plan['sources'][key]='DOI 查询结果（请核对）'
                if result.get('title'):plan['display_name']=result['title'];self.tree.set(rid,'new',result['title'])
                if self.active==rid:self.load_active()
                self.feedback.set('已取得 DOI 信息，请核对名称及作者后保存。')
        except queue.Empty:pass
        self.job=self.win.after(100,self.poll)

    def accept(self):
        self.persist();plans=list(self.plans.values())
        if any(not p['display_name'].strip() or len(p['display_name'].strip())>500 for p in plans):
            self.feedback.set('请为每篇文献填写 1–500 字的显示名称。');return
        self.close();self.on_apply(plans)

    def close(self):
        if self.closed:return
        self.closed=True
        if getattr(self,'job',None):self.win.after_cancel(self.job)
        self.win.destroy()


def ui_background():
    from ui_theme import BG
    return BG
