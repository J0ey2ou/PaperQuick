"""Attachment management and an independent, read-only comparison reader."""
from pathlib import Path
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import webbrowser
from library_core import Library
from pdf_reader_core import document_info, render_page
from ui_theme import FONT, MUTED, style_dialog

READABLE = {'pdf', 'doc', 'docx', 'word', 'txt', 'md'}

def attachment_name(item):
    return item.get('label') or (Path(item['original']).name if item.get('original') and not item.get('url') else '') or Path(item.get('path') or '').name or item.get('url') or '附件'

def readable(item):
    return item.get('kind') in READABLE or Path(item.get('path') or '').suffix.lower() in ('.pdf', '.doc', '.docx', '.txt', '.md')

def open_external(directory, item):
    if item.get('url'):
        webbrowser.open(item['url'])
    else:
        path=Path(directory)/item['path']
        if not path.is_file():raise ValueError('找不到这个附件，请重新添加文件。')
        if path.suffix.lower() in {'.exe','.com','.bat','.cmd','.ps1','.psm1','.vbs','.vbe','.js','.jse','.wsf','.wsh','.lnk','.url','.scr','.msi','.msp','.reg','.hta','.cpl'}:
            raise ValueError('这类文件不能直接运行。请在文献库文件夹中查看和管理。')
        os.startfile(str(path))

class AttachmentManager:
    def __init__(self,parent,directory,rid,on_compare=None,on_changed=None):
        self.directory=Path(directory);self.rid=rid;self.on_compare=on_compare;self.on_changed=on_changed
        self.busy=False;self.closed=False;self.events=queue.Queue()
        self.win=tk.Toplevel(parent);self.win.title('正文与附件');self.win.geometry('880x600');self.win.minsize(720,500);style_dialog(self.win);self.win.transient(parent.winfo_toplevel());self.win.protocol('WM_DELETE_WINDOW',self.close)
        panel=ttk.Frame(self.win,padding=20);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='把补充材料留在文献身边',font=(FONT,18,'bold')).pack(anchor='w')
        ttk.Label(panel,text='正文、补充材料、研究方案和相关网址统一收纳。选择 PDF 或 Word 附件，即可并排比对。',style='Muted.TLabel',wraplength=810).pack(fill='x',pady=(8,16))
        box=ttk.Frame(panel);box.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(box,columns=('name','role','kind'),show='headings',height=7)
        for key,label,width in [('name','名称',500),('role','用途',90),('kind','类型',80)]:self.tree.heading(key,text=label);self.tree.column(key,width=width,minwidth=55,stretch=key=='name')
        scroll=ttk.Scrollbar(box,command=self.tree.yview);self.tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
        self.tree.bind('<Double-1>',lambda _:self.compare())
        actions=ttk.Frame(panel);actions.pack(fill='x',pady=(14,5))
        for i,(label,command) in enumerate([('添加文件',self.add_files),('添加网址',self.add_link),('修改名称',self.rename),('设为正文',self.set_primary),('并排阅读',self.compare),('外部打开',self.external)]):
            ttk.Button(actions,text=label,command=command).grid(row=i//3,column=i%3,sticky='ew',padx=3,pady=3)
        actions.columnconfigure((0,1,2),weight=1)
        self.status=tk.StringVar(value='文件会复制到本地文献库；原文件会保留。');ttk.Label(panel,textvariable=self.status,style='Muted.TLabel',wraplength=810).pack(fill='x',pady=(8,0))
        self.reload();self.win.after(100,self.poll)

    def reload(self):
        lib=Library(self.directory)
        try:self.items=lib.get(self.rid)['attachments']
        finally:lib.close()
        selected=self.tree.selection();self.tree.delete(*self.tree.get_children())
        for item in self.items:self.tree.insert('','end',iid=item['id'],values=(attachment_name(item),'正文' if item.get('role')=='primary' else '笔记' if item.get('role')=='note' else '补充材料',('网址' if item.get('url') else item.get('kind','文件').upper())))
        if selected and self.tree.exists(selected[0]):self.tree.selection_set(selected[0])

    def selected(self):
        ids=self.tree.selection();return next((x for x in self.items if ids and x['id']==ids[0]),None)

    def run(self,job):
        if self.busy:return
        self.busy=True;self.status.set('正在收纳附件，请稍候…')
        def work():
            try:self.events.put(('done',job()))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def add_files(self):
        if self.busy:return
        sources=filedialog.askopenfilenames(parent=self.win,title='添加补充材料',filetypes=[('文档','*.pdf *.doc *.docx'),('所有文件','*.*')])
        if not sources:return
        def job():
            lib=Library(self.directory);added=0;failures=[]
            try:
                for source in sources:
                    try:lib.add_attachment(self.rid,source);added+=1
                    except Exception as exc:failures.append(Path(source).name+'：'+str(exc))
            finally:lib.close()
            return f'已收纳 {added} 个文件。'+(('\n'+ '\n'.join(failures)) if failures else '')
        self.run(job)

    def add_link(self):
        if self.busy:return
        url=simpledialog.askstring('添加附件网址','粘贴补充材料或相关网页的网址：',parent=self.win)
        if not url:return
        label=simpledialog.askstring('附件名称','给这个网址起个名字（可留空）：',parent=self.win)
        if label is None:return
        def job():
            lib=Library(self.directory)
            try:lib.add_attachment_link(self.rid,url,label)
            finally:lib.close()
            return '网址已关联到这篇文献。'
        self.run(job)

    def rename(self):
        item=self.selected()
        if self.busy or not item:return
        label=simpledialog.askstring('修改附件名称','名称：',initialvalue=attachment_name(item),parent=self.win)
        if label is None:return
        self.mutate(lambda lib:lib.rename_attachment_label(self.rid,item['id'],label),'附件名称已更新。')

    def set_primary(self):
        item=self.selected()
        if self.busy or not item:return
        if not readable(item):self.status.set('请选择 PDF 或 Word 文件作为正文。');return
        self.mutate(lambda lib:lib.set_primary_attachment(self.rid,item['id']),'正文已更新。原正文的批注会保留，切换回原文件后可继续查看。')

    def mutate(self,action,message):
        def job():
            lib=Library(self.directory)
            try:action(lib)
            finally:lib.close()
            return message
        self.run(job)

    def compare(self):
        item=self.selected()
        if self.busy or not item:return
        if not readable(item):self.status.set('这个附件可点击“外部打开”查看。');return
        if self.on_compare:self.on_compare(item)
        else:self.status.set('请先打开文献阅读，再选择附件并排阅读。')

    def external(self):
        item=self.selected()
        if not item:return
        try:open_external(self.directory,item)
        except Exception as exc:self.status.set(str(exc))

    def poll(self):
        if self.closed:return
        try:
            while True:
                kind,message=self.events.get_nowait();self.busy=False;self.status.set(message if kind=='done' else '未能完成：'+message)
                if kind=='done':
                    try:
                        self.reload()
                        if self.on_changed:self.on_changed()
                    except Exception as exc:self.status.set(message+' 刷新界面时遇到问题，请重新打开：'+str(exc))
        except queue.Empty:pass
        self.win.after(100,self.poll)

    def close(self):
        if self.busy:self.status.set('正在保存附件，完成后即可关闭。');return False
        self.closed=True;self.win.destroy();return True

class AttachmentPreview:
    """No note/stat mutation: page position belongs only to this comparison pane."""
    def __init__(self,parent,directory,on_close,on_preview_start=None):
        self.directory=Path(directory);self.frame=ttk.Frame(parent,style='Card.TFrame',padding=8)
        self.on_preview_start=on_preview_start
        self.events=queue.Queue();self.closed=False;self.generation=0;self.loading=False;self.path=None;self.page=0;self.count=0;self.scale=1.;self.items=[];self.fit_pending=False
        self.continuous=tk.BooleanVar(master=parent,value=True)
        header=ttk.Frame(self.frame);header.pack(fill='x')
        ttk.Label(header,text='附件比对',font=(FONT,12,'bold')).pack(side='left')
        self.choice=tk.StringVar();self.combo=ttk.Combobox(self.frame,textvariable=self.choice,state='readonly',width=24);self.combo.pack(fill='x',pady=8);self.combo.bind('<<ComboboxSelected>>',self.choose)
        from icon_toolbar import IconToolbar
        self.page_input=tk.StringVar();self.page_label=tk.StringVar(value='请选择附件')
        controls=IconToolbar(self.frame);self.toolbar=controls;controls.pack(fill='x',pady=(0,5))
        for icon,label,command in [('previous','上一页',lambda:self.change_page(-1)),('next','下一页',lambda:self.change_page(1)),('fit','适合宽度',self.fit_width),('minus','缩小',lambda:self.zoom(.85)),('plus','放大',lambda:self.zoom(1.18))]:
            controls.add(icon,label,command)
        controls.add('continuous','连续阅读 / 单页阅读',self.toggle_continuous,variable=self.continuous)
        controls.add('close','收起附件比对',on_close)
        controls.add_page(self.page_input,self.jump,self.page_label)
        viewer=ttk.Frame(self.frame);self.viewer=viewer;self.text_display=None;viewer.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(viewer,bg='#142137',highlightthickness=0);scroll=ttk.Scrollbar(viewer,command=self.canvas.yview);horizontal=ttk.Scrollbar(viewer,orient='horizontal',command=self.canvas.xview);self.canvas.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        self.vertical_scroll=scroll
        from reader_canvas import DocumentCanvas
        self.document_canvas=DocumentCanvas(self)
        self.canvas.configure(yscrollcommand=self.document_canvas.scrolled)
        scroll.pack(side='right',fill='y');horizontal.pack(side='bottom',fill='x');self.canvas.pack(fill='both',expand=True);self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        self.canvas.bind('<Button-1>',lambda e:self.canvas.scan_mark(e.x,e.y));self.canvas.bind('<B1-Motion>',lambda e:self.canvas.scan_dragto(e.x,e.y,gain=1))
        self.status=tk.StringVar(value='附件独立连续阅读，不影响正文和笔记。');ttk.Label(self.frame,textvariable=self.status,style='Muted.TLabel',wraplength=360).pack(fill='x',pady=6)
        self.frame.after(100,self.poll)

    def set_items(self,items,selected=None):
        self.items=[i for i in items if readable(i)];self.combo.configure(values=[f'{i+1}. {attachment_name(x)}' for i,x in enumerate(self.items)])
        index=next((i for i,x in enumerate(self.items) if x['id']==selected),0)
        if self.items:self.combo.current(index)

    def choose(self,_=None):
        index=self.combo.current()
        if 0<=index<len(self.items):self.open(self.items[index])

    def open(self,item):
        self.generation+=1;generation=self.generation;source=self.directory/item['path'];self.attachment_id=item['id'];self.rid=item.get('paper');self.path=None;self.page=0;self.count=0;self.loading=True;self.fit_pending=True;self.image_size=None
        self.document_canvas.reset()
        self.status.set('正在准备附件预览…');self.canvas.delete('all');self.page_label.set('正在打开…')
        preview_done=threading.Event()
        if source.suffix.lower() in ('.doc','.docx') and self.on_preview_start:self.on_preview_start(preview_done)
        def work():
            try:
                if source.suffix.lower() in ('.txt','.md'):
                    from reading_documents import read_text_file
                    self.events.put(('text',generation,read_text_file(source)));return
                from document_conversion import preview_pdf
                try:path=preview_pdf(source,self.directory/'cache'/'document-previews')
                finally:preview_done.set()
                from pdf_reader_core import render_page_data,page_sizes
                count=document_info(path);image,chars=render_page_data(path,0,self.scale);self.events.put(('open',generation,(path,count,image,chars,page_sizes(path))))
            except Exception as exc:preview_done.set();self.events.put(('error',generation,str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def change_page(self,delta):
        if self.loading or not self.path or not 0<=self.page+delta<self.count:return
        if self.continuous.get() and self.document_canvas.goto(self.page+delta):return
        self.page+=delta;self.render()

    def draw_annotations(self):
        # The shared virtual canvas keeps this pane independent of main-paper notes.
        pass

    def toggle_continuous(self):
        if self.path and not self.loading:self.render()

    def zoom(self,factor):
        if self.path and not self.loading:
            self.scale=max(.2,min(3,self.scale*factor));self.render()

    def render(self):
        if self.loading or not self.path:return
        if self.rid:
            lib=Library(self.directory)
            try:
                item=next(a for a in lib.get(self.rid)['attachments'] if a['id']==self.attachment_id)
                if Path(item['path']).suffix.lower()=='.pdf':self.path=self.directory/item['path']
            except (ValueError,StopIteration):self.status.set('附件已变更，请重新选择。');return
            finally:lib.close()
        self.loading=True;generation=self.generation;page=self.page;scale=self.scale;path=self.path
        def work():
            try:
                from pdf_reader_core import render_page_data,page_sizes
                image,chars=render_page_data(path,page,scale)
                self.events.put(('page',generation,(page,image,chars,page_sizes(path),scale)))
            except Exception as exc:self.events.put(('error',generation,str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def jump(self):
        try:target=int(self.page_input.get())-1
        except ValueError:self.status.set('请输入数字页码。');return
        if not 0<=target<self.count:self.status.set(f'页码应在 1–{self.count} 之间。');return
        self.change_page(target-self.page)

    def fit_width(self):
        if self.loading or not getattr(self,'image_size',None):return
        value=max(.2,min(3,self.scale*max(150,self.canvas.winfo_width()-24)/self.image_size[0]))
        if abs(value-self.scale)>.02:self.scale=value;self.render()

    def poll(self):
        if self.closed:return
        try:
            while True:
                kind,generation,value=self.events.get_nowait()
                if generation!=self.generation:continue
                if kind=='canvas-page':
                    sign,page,data,error=value
                    if sign!=self.document_canvas.sign:continue
                    if error:
                        self.document_canvas.pending.discard(page);self.status.set('附件页面暂时无法加载：'+error)
                    else:self.document_canvas.receive(page,*data)
                    continue
                self.loading=False
                if kind=='error':self.status.set('附件暂时无法预览：'+value);continue
                if kind=='text':
                    if not self.text_display:self.text_display=tk.Text(self.viewer,wrap='word',font=(FONT,12),padx=16,pady=14)
                    self.text_display.configure(yscrollcommand=self.vertical_scroll.set);self.vertical_scroll.configure(command=self.text_display.yview)
                    self.canvas.pack_forget();self.text_display.pack(fill='both',expand=True);self.text_display.configure(state='normal');self.text_display.delete('1.0','end');self.text_display.insert('1.0',value);self.text_display.configure(state='disabled');self.count=1;self.page=0;self.image_size=None;self.page_label.set('文本 · 连续阅读');continue
                if self.text_display:self.text_display.pack_forget()
                self.vertical_scroll.configure(command=self.canvas.yview)
                self.canvas.pack(fill='both',expand=True)
                if kind=='open':self.path,self.count,image,chars,sizes=value;self.page=0
                else:
                    page,image,chars,sizes,scale=value
                    if scale!=self.scale:continue
                    self.page=page
                self.image_size=(image.width,image.height)
                self.document_canvas.adopt(self.path,self.page,self.count,image,chars,sizes)
                self.page_input.set(str(self.page+1));self.page_label.set(f'第 {self.page+1} / {self.count} 页'+(' · 连续阅读' if self.continuous.get() else ''))
                self.status.set('向下滚动接着阅读下一页 · 附件与正文独立' if self.continuous.get() else '独立分页阅读 · 可切换连续阅读')
                if self.fit_pending:self.fit_pending=False;self.fit_width()
        except queue.Empty:pass
        self.frame.after(100,self.poll)

    def close(self):self.closed=True;self.generation+=1;self.document_canvas.reset();self.frame.destroy()
