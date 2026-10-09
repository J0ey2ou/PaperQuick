"""Native offline PDF reader, autosaved notes and detachable reference sidebar."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import time
import uuid
from library_core import Library
from pdf_reader_core import document_info,render_page,extract_text,region_text
from references import parse_references
from ui_theme import BG,PANEL,FG,MUTED,ACCENT,FONT,style_dialog

class ReaderPage:
    def __init__(self,parent,directory,on_query,on_collect):
        self.directory=Path(directory);self.on_query=on_query;self.on_collect=on_collect
        self.frame=tk.Frame(parent,bg=BG);self.events=queue.Queue();self.rid=None;self.path=None;self.page=0;self.count=0;self.scale=1.2;self.generation=0;self.references=[];self.loading=False;self.dirty=False;self.note_job=None
        self.annotations=[];self.selection_start=None;self.image_size=None;self.fit_pending=True
        header=ttk.Frame(self.frame,padding=(24,14));header.pack(fill='x')
        title=ttk.Frame(header);title.pack(side='left');ttk.Label(title,text='文献阅读',font=(FONT,21,'bold')).pack(anchor='w')
        self.title=tk.StringVar(value='打开 PDF，在这里阅读与记录想法');ttk.Label(title,textvariable=self.title,style='Muted.TLabel',wraplength=830).pack(anchor='w',pady=(5,0))
        ttk.Button(header,text='打开本地 PDF',command=self.choose_pdf).pack(side='right');ttk.Button(header,text='参考文献侧栏',command=self.reference_panel).pack(side='right',padx=8)
        toolbar=ttk.Frame(self.frame,padding=(24,0,24,10));toolbar.pack(fill='x')
        for label,command in [('上一页',lambda:self.change_page(-1)),('下一页',lambda:self.change_page(1)),('缩小',lambda:self.zoom(.85)),('放大',lambda:self.zoom(1.18)),('保存笔记',self.save_notes)]:ttk.Button(toolbar,text=label,command=command).pack(side='left',padx=(0,8))
        ttk.Button(toolbar,text='适合宽度',command=self.fit_width).pack(side='left',padx=(0,8))
        self.page_label=tk.StringVar(value='尚未打开 PDF');ttk.Label(toolbar,textvariable=self.page_label,style='Muted.TLabel').pack(side='left',padx=10)
        tools=ttk.Frame(self.frame,padding=(24,0,24,10));tools.pack(fill='x')
        self.tool=tk.StringVar(value='浏览');ttk.Label(tools,text='阅读工具').pack(side='left',padx=(0,10))
        for label in ('浏览','框选高亮','框选批注','复制文字'):
            ttk.Radiobutton(tools,text=label,variable=self.tool,value=label).pack(side='left',padx=7)
        self.annotation_color=tk.StringVar(value='黄色');self.colors={'黄色':'#ffd65c','绿色':'#66dfac','蓝色':'#76b9ff','粉色':'#f795c7'}
        ttk.Combobox(tools,textvariable=self.annotation_color,values=list(self.colors),state='readonly',width=6).pack(side='left',padx=8)
        self.page_input=tk.StringVar();entry=ttk.Entry(tools,textvariable=self.page_input,width=5);entry.pack(side='left',padx=(14,4));entry.bind('<Return>',lambda _:self.jump())
        ttk.Button(tools,text='跳转页',command=self.jump,width=7).pack(side='left')
        ttk.Button(tools,text='加书签',command=self.add_bookmark,width=7).pack(side='left',padx=6)
        body=ttk.Frame(self.frame,padding=(24,0));body.pack(fill='both',expand=True)
        splitter=ttk.Panedwindow(body,orient='horizontal');splitter.pack(fill='both',expand=True)
        notes_panel=ttk.Frame(splitter,style='Card.TFrame',padding=12,width=340)
        ttk.Label(notes_panel,text='阅读笔记',style='Card.TLabel',font=(FONT,12,'bold')).pack(anchor='w')
        self.note_status=tk.StringVar(value='笔记保存在本地文献库');ttk.Label(notes_panel,textvariable=self.note_status,style='CardMuted.TLabel',wraplength=300).pack(anchor='w',pady=(8,12))
        self.notebook=ttk.Notebook(notes_panel);self.notebook.pack(fill='both',expand=True)
        self.note_tab=ttk.Frame(self.notebook);self.annotation_tab=ttk.Frame(self.notebook)
        self.notebook.add(self.note_tab,text='笔记编辑');self.notebook.add(self.annotation_tab,text='高亮 / 批注')
        note_buttons=ttk.Frame(self.note_tab);note_buttons.pack(fill='x',pady=6)
        for i,(label,command) in enumerate([('编辑 / 新段落',self.new_paragraph),('插入页码',self.insert_page),('研究笔记模板',self.note_template),('导出笔记',self.export_notes),('加粗',lambda:self.format_note('bold')),('斜体',lambda:self.format_note('italic'))]):
            ttk.Button(note_buttons,text=label,command=command,width=13).grid(row=i//2,column=i%2,sticky='ew',padx=2,pady=2)
        note_buttons.columnconfigure((0,1),weight=1)
        self.notes=tk.Text(self.note_tab,height=4,width=28,bg='#0b1627',fg=FG,insertbackground=ACCENT,relief='solid',borderwidth=1,wrap='word',padx=12,pady=12,font=(FONT,11),undo=True,takefocus=True,state='normal',exportselection=False)
        note_scroll=ttk.Scrollbar(self.note_tab,command=self.notes.yview);note_scroll.pack(side='right',fill='y');self.notes.configure(yscrollcommand=note_scroll.set)
        self.notes.pack(fill='both',expand=True);self.notes.bind('<<Modified>>',self.notes_changed)
        self.notes.tag_configure('bold',font=(FONT,11,'bold'));self.notes.tag_configure('italic',font=(FONT,11,'italic'))
        self.notes.bind('<Control-s>',lambda _:self.save_key());self.notes.bind('<Control-S>',lambda _:self.save_key())
        self.notes.bind('<Button-1>',lambda _:self.notes.focus_set(),add='+')
        menu=tk.Menu(self.notes,tearoff=False)
        for label,event in [('撤销','<<Undo>>'),('重做','<<Redo>>'),('剪切','<<Cut>>'),('复制','<<Copy>>'),('粘贴','<<Paste>>'),('全选','<<SelectAll>>')]:menu.add_command(label=label,command=lambda e=event:self.notes.event_generate(e))
        self.notes.bind('<Button-3>',lambda e:menu.tk_popup(e.x_root,e.y_root))
        self.annotation_list=ttk.Treeview(self.annotation_tab,columns=('page','text'),show='headings',height=4)
        self.annotation_list.heading('page',text='页');self.annotation_list.heading('text',text='摘录 / 批注');self.annotation_list.column('page',width=38,stretch=False);self.annotation_list.column('text',width=220)
        self.annotation_list.pack(fill='both',expand=True);self.annotation_list.bind('<Double-1>',lambda _:self.locate_annotation())
        annotation_buttons=ttk.Frame(self.annotation_tab);annotation_buttons.pack(fill='x',pady=8)
        for i,(label,command) in enumerate([('定位',self.locate_annotation),('编辑',self.edit_annotation),('删除',self.delete_annotation)]):ttk.Button(annotation_buttons,text=label,command=command,width=6).grid(row=0,column=i,sticky='ew');annotation_buttons.columnconfigure(i,weight=1)
        ttk.Label(self.annotation_tab,text='在 PDF 上拖框高亮或批注；双击列表回到原页。\n批注保存在本地库，原 PDF 保持原样。',wraplength=300,style='Muted.TLabel').pack(fill='x',pady=5)
        viewer=ttk.Frame(splitter,style='Card.TFrame');splitter.add(viewer,weight=4);splitter.add(notes_panel,weight=1)
        self.canvas=tk.Canvas(viewer,bg='#142137',highlightthickness=0)
        v=ttk.Scrollbar(viewer,orient='vertical',command=self.canvas.yview);h=ttk.Scrollbar(viewer,orient='horizontal',command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=v.set,xscrollcommand=h.set);v.pack(side='right',fill='y');h.pack(side='bottom',fill='x');self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<MouseWheel>',self.scroll)
        self.canvas.bind('<Button-1>',self.begin_selection);self.canvas.bind('<B1-Motion>',self.move_selection);self.canvas.bind('<ButtonRelease-1>',self.end_selection)
        self.canvas.bind('<Double-1>',self.edit_clicked_annotation)
        self.reading_menu=tk.Menu(self.canvas,tearoff=False)
        self.reading_menu.add_command(label='添加阅读笔记（当前页 / 最近选区）',command=self.context_note)
        self.reading_menu.add_command(label='在此处添加批注',command=self.context_comment)
        self.reading_menu.add_command(label='添加当前页书签',command=self.add_bookmark)
        self.canvas.bind('<Button-3>',self.reading_context)
        self.status=tk.StringVar(value='PDF 渲染、笔记与参考文献提取均在本机进行')
        ttk.Label(self.frame,textvariable=self.status,style='Muted.TLabel',padding=(24,12)).pack(fill='x')
        self.canvas.create_text(260,200,text='从文献分类或图谱打开 PDF\n也可点击“打开本地 PDF”',fill=MUTED,font=(FONT,14),justify='center')
        self.frame.after(100,self.poll)

    def open(self,rid):
        if getattr(self,'on_document_change',None):self.on_document_change()
        self.save_notes()
        lib=Library(self.directory)
        try:
            record=lib.get(rid)
            if not record['attachments']:raise ValueError('这篇文献尚未归档 PDF。')
            self.rid=rid;self.attachment_id=record['attachments'][0]['id'];self.path=self.directory/record['attachments'][0]['path'];self.page=0;self.count=0;self.generation+=1;self.loading=True;self.fit_pending=True
            lib.save({'read_count':record.get('read_count',0)+1,'last_read':time.time()},rid=rid)
            self.title.set(record['title']);self.notes.configure(state='normal');self.notes.delete('1.0','end');self.notes.insert('1.0',record.get('notes',''));self.notes.edit_reset();self.notes.edit_modified(False);self.dirty=False
            for tag,ranges in record.get('note_styles',{}).items():
                if tag in ('bold','italic'):
                    for start,end in ranges:
                        try:self.notes.tag_add(tag,start,end)
                        except tk.TclError:pass
            self.annotations=record.get('annotations',[]);self.last_selection=None;self.refresh_annotations()
            self.references=record.get('references',[]);self.note_status.set('自动保存已启用 · 笔记保存在本机')
        finally:lib.close()
        generation=self.generation;path=self.path;self.status.set('正在本地读取 PDF…')
        def job():
            try:
                count=document_info(path);image=render_page(path,0,self.scale);self.events.put(('page',generation,(count,0,image)))
                text=extract_text(path);refs=parse_references(text);self.events.put(('references',generation,(text,refs)))
            except Exception as exc:self.events.put(('error',generation,str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def choose_pdf(self):
        source=filedialog.askopenfilename(parent=self.frame,filetypes=[('PDF','*.pdf')])
        if not source:return
        self.status.set('正在本地归档 PDF…')
        def job():
            lib=None
            try:
                lib=Library(self.directory);rid=lib.import_pdf(source,lib.projects()[0]['id']);self.events.put(('open',0,rid))
            except Exception as exc:self.events.put(('error',self.generation,str(exc)))
            finally:
                if lib:lib.close()
        threading.Thread(target=job,daemon=True).start()

    def change_page(self,delta):
        target=self.page+delta
        if not self.path or not 0<=target<self.count or self.loading:return
        self.page=target;self.render()

    def zoom(self,factor):
        if not self.path or self.loading:return
        self.scale=max(.45,min(3,self.scale*factor));self.render()

    def render(self):
        if self.loading:return
        lib=Library(self.directory)
        try:
            attachment=next(a for a in lib.get(self.rid)['attachments'] if a['id']==self.attachment_id)
            self.path=self.directory/attachment['path']
        except (ValueError,StopIteration) as exc:
            self.status.set('附件不可用，请重新打开文献：'+str(exc));return
        finally:lib.close()
        self.loading=True;generation=self.generation;page=self.page;path=self.path;scale=self.scale;self.status.set('正在渲染页面…')
        def job():
            try:self.events.put(('page',generation,(self.count,page,render_page(path,page,scale))))
            except Exception as exc:self.events.put(('error',generation,str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def poll(self):
        try:
            while True:
                kind,generation,value=self.events.get_nowait()
                if kind=='open':self.open(value);continue
                if generation!=self.generation:continue
                if kind=='page':
                    from PIL import ImageTk
                    self.loading=False;self.count,self.page,image=value;self.photo=ImageTk.PhotoImage(image,master=self.frame)
                    self.image_size=(image.width,image.height)
                    self.canvas.delete('all');self.canvas.create_image(18,18,image=self.photo,anchor='nw');self.canvas.configure(scrollregion=(0,0,image.width+36,image.height+36));self.canvas.yview_moveto(0);self.canvas.xview_moveto(0);self.draw_annotations()
                    self.page_input.set(str(self.page+1))
                    self.page_label.set(f'第 {self.page+1} / {self.count} 页 · {round(self.scale*100)}%');self.status.set('本地 PDF 阅读 · 笔记自动保存')
                    if self.fit_pending:self.fit_pending=False;self.fit_width()
                elif kind=='references':
                    text,self.references=value;lib=Library(self.directory)
                    try:lib.save({'text':text,'references':self.references},rid=self.rid)
                    finally:lib.close()
                    self.status.set(f'已在本地提取 {len(self.references)} 条参考文献；标题提取结果需要核对。')
                    if getattr(self,'reference_window',None) and self.reference_window.winfo_exists():self.fill_references()
                elif kind=='annotation':
                    self.last_selection=value
                    if value['kind']=='复制文字':
                        if value['quote']:self.frame.clipboard_clear();self.frame.clipboard_append(value['quote']);self.status.set('选区文字已复制')
                        else:self.status.set('选区没有可提取文字；扫描 PDF 可使用框选批注。')
                    elif value['kind']=='框选批注':self.annotation_editor(value)
                    else:self.add_annotation(value)
                elif kind=='error':self.loading=False;self.status.set('阅读未完成：'+value)
        except queue.Empty:pass
        if self.frame.winfo_exists():self.frame.after(1000 if self.frame.winfo_toplevel().state()=='withdrawn' and not self.loading else 100,self.poll)

    def notes_changed(self,_=None):
        if not self.notes.edit_modified():return
        self.notes.edit_modified(False)
        if not self.rid:return
        self.dirty=True;self.note_status.set('正在编辑 · 稍后自动保存')
        if self.note_job:self.frame.after_cancel(self.note_job)
        self.note_job=self.frame.after(1200,self.save_notes)

    def save_notes(self):
        if self.note_job:
            try:self.frame.after_cancel(self.note_job)
            except tk.TclError:pass
            self.note_job=None
        if not self.rid or not (self.dirty or self.notes.edit_modified()):return
        lib=None
        try:
            styles={tag:list(zip(*[iter(map(str,self.notes.tag_ranges(tag)))]*2)) for tag in ('bold','italic')}
            lib=Library(self.directory);lib.save({'notes':self.notes.get('1.0','end-1c'),'note_styles':styles},rid=self.rid);self.dirty=False;self.note_status.set('已自动保存到本机')
        except Exception as exc:self.note_status.set('保存失败：'+str(exc));raise
        finally:
            if lib:lib.close()

    def save_key(self):self.save_notes();return 'break'

    def reading_context(self,event):
        if not self.rid or not self.image_size:return
        w,h=self.image_size;self.context_point=(max(0,min(1,(self.canvas.canvasx(event.x)-18)/w)),max(0,min(1,(self.canvas.canvasy(event.y)-18)/h)))
        try:self.reading_menu.tk_popup(event.x_root,event.y_root)
        finally:self.reading_menu.grab_release()

    def context_note(self):
        if not self.rid:return
        self.new_paragraph();self.notes.insert('end',f'[第 {self.page+1} 页]\n')
        item=getattr(self,'last_selection',None)
        if item and item['page']==self.page and item.get('quote'):self.notes.insert('end',item['quote']+'\n\n我的笔记：')
        self.notes.mark_set('insert','end-1c');self.notes.see('end');self.notes.focus_set();self.notes_changed()

    def context_comment(self):
        if not self.rid:return
        x,y=getattr(self,'context_point',(.1,.1))
        self.annotation_editor({'id':uuid.uuid4().hex,'attachment':self.attachment_id,'page':self.page,'rect':[x,y,min(1,x+.025),min(1,y+.02)],'color':self.colors[self.annotation_color.get()],'kind':'批注','text':'','quote':'','created':time.time()})

    def format_note(self,tag):
        if not self.rid:return
        try:start,end=self.notes.index('sel.first'),self.notes.index('sel.last')
        except tk.TclError:self.note_status.set('先选中笔记文字，再设置加粗或斜体。');return
        if tag in self.notes.tag_names(start):self.notes.tag_remove(tag,start,end)
        else:self.notes.tag_add(tag,start,end)
        self.dirty=True;self.save_notes();self.notes.focus_set()

    def new_paragraph(self):
        if not self.rid:self.status.set('先打开一篇 PDF，再记录笔记。');return
        self.notebook.select(self.note_tab);self.notes.configure(state='normal');self.notes.insert('end','\n\n' if self.notes.get('1.0','end-1c') else '');self.notes.mark_set('insert','end-1c');self.notes.see('insert');self.notes.focus_set()

    def insert_page(self):
        if not self.rid:return
        self.notebook.select(self.note_tab);self.notes.insert('insert',f'\n[第 {self.page+1} 页] ');self.notes.focus_set()

    def note_template(self):
        if not self.rid:return
        self.new_paragraph();self.notes.insert('end','研究问题：\n\n方法与数据：\n\n主要发现：\n\n局限与疑问：\n\n与我的课题的联系：\n');self.notes.see('end')

    def fit_width(self):
        if not self.image_size or self.loading:return
        target=max(200,self.canvas.winfo_width()-40)
        value=max(.3,min(3,self.scale*target/self.image_size[0]))
        if abs(value-self.scale)>.025:self.scale=value;self.render()

    def jump(self):
        try:target=int(self.page_input.get())-1
        except ValueError:self.status.set('请输入数字页码。');return
        if not 0<=target<self.count:self.status.set(f'页码应在 1–{self.count} 之间。');return
        self.change_page(target-self.page)

    def begin_selection(self,event):
        if self.loading or not self.image_size:return
        if self.tool.get()=='浏览':self.canvas.scan_mark(event.x,event.y);return
        x=self.canvas.canvasx(event.x);y=self.canvas.canvasy(event.y)
        if not (18<=x<=18+self.image_size[0] and 18<=y<=18+self.image_size[1]):return
        self.selection_start=(x,y)

    def move_selection(self,event):
        if self.tool.get()=='浏览':self.canvas.scan_dragto(event.x,event.y,gain=1);return
        if not self.selection_start:return
        self.canvas.delete('selection');self.canvas.create_rectangle(*self.selection_start,self.canvas.canvasx(event.x),self.canvas.canvasy(event.y),outline=self.colors[self.annotation_color.get()],width=2,dash=(5,3),tags='selection')

    def end_selection(self,event):
        if not self.selection_start:return
        x1,y1=self.selection_start;x2=self.canvas.canvasx(event.x);y2=self.canvas.canvasy(event.y);self.selection_start=None;self.canvas.delete('selection')
        if min(abs(x2-x1),abs(y2-y1))<4:return
        w,h=self.image_size
        rect=[max(0,min(1,(min(x1,x2)-18)/w)),max(0,min(1,(min(y1,y2)-18)/h)),max(0,min(1,(max(x1,x2)-18)/w)),max(0,min(1,(max(y1,y2)-18)/h))]
        item={'id':uuid.uuid4().hex,'attachment':self.attachment_id,'page':self.page,'rect':rect,'color':self.colors[self.annotation_color.get()],'kind':self.tool.get(),'text':'','quote':'','created':time.time()}
        path=self.path;generation=self.generation
        def job():
            try:item['quote']=region_text(path,item['page'],rect)
            except Exception:pass
            self.events.put(('annotation',generation,item))
        threading.Thread(target=job,daemon=True).start()
        self.status.set('正在提取选区文字…')

    def add_annotation(self,item):
        previous=list(self.annotations)
        self.annotations=[a for a in self.annotations if a['id']!=item['id']]+[item]
        try:self.persist_annotations()
        except Exception:self.annotations=previous;raise
        self.notebook.select(self.annotation_tab);self.refresh_annotations();self.draw_annotations();self.status.set('高亮 / 批注已保存到本机')

    def persist_annotations(self):
        lib=Library(self.directory)
        try:lib.save({'annotations':self.annotations},rid=self.rid)
        finally:lib.close()

    def refresh_annotations(self):
        self.annotation_list.delete(*self.annotation_list.get_children())
        for a in sorted(self.annotations,key=lambda a:(a['page'],a.get('created',0))):
            if a['attachment']==getattr(self,'attachment_id',None):self.annotation_list.insert('','end',iid=a['id'],values=(a['page']+1,(a.get('text') or a.get('quote') or '区域高亮').replace('\n',' ')[:100]))

    def draw_annotations(self):
        self.canvas.delete('annotation')
        if not self.image_size:return
        w,h=self.image_size
        for a in self.annotations:
            if a['attachment']!=self.attachment_id or a['page']!=self.page:continue
            x1,y1,x2,y2=a['rect'];coords=(18+x1*w,18+y1*h,18+x2*w,18+y2*h)
            self.canvas.create_rectangle(*coords,fill=a['color'],stipple='gray25',outline=a['color'],width=1,tags=('annotation',a['id']))
            if a.get('text'):self.canvas.create_text(coords[2],coords[1],text='●',fill=a['color'],anchor='ne',tags=('annotation',a['id']))

    def selected_annotation(self):
        ids=self.annotation_list.selection();return next((a for a in self.annotations if ids and a['id']==ids[0]),None)

    def locate_annotation(self):
        a=self.selected_annotation()
        if not a or self.loading:return
        if a['page']!=self.page:self.change_page(a['page']-self.page)
        def locate():
            if self.loading:self.frame.after(80,locate);return
            if self.rid and self.image_size:self.canvas.yview_moveto(max(0,a['rect'][1]-.1));self.status.set(a.get('text') or a.get('quote') or '区域高亮')
        locate()

    def edit_annotation(self):
        a=self.selected_annotation()
        if a:self.annotation_editor(dict(a))

    def add_bookmark(self):
        if not self.rid or not self.count:return
        self.add_annotation({'id':uuid.uuid4().hex,'attachment':self.attachment_id,'page':self.page,'rect':[0,0,0,0],'color':self.colors[self.annotation_color.get()],'kind':'书签','text':f'第 {self.page+1} 页书签','quote':'','created':time.time()})

    def edit_clicked_annotation(self,event):
        x=self.canvas.canvasx(event.x);y=self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x-2,y-2,x+2,y+2)):
            tags=self.canvas.gettags(item)
            if tags and tags[0]=='annotation':
                a=next(a for a in self.annotations if a['id']==tags[1]);self.annotation_editor(dict(a));return

    def annotation_editor(self,item):
        dialog=tk.Toplevel(self.frame);style_dialog(dialog);dialog.title(f"第 {item['page']+1} 页 · 编辑批注");dialog.geometry('620x470');dialog.transient(self.frame.winfo_toplevel());dialog.grab_set()
        panel=ttk.Frame(dialog,padding=18);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='摘录（选区没有文字时也可直接写批注）').pack(anchor='w')
        quote=tk.Text(panel,height=4,wrap='word');quote.insert('1.0',item.get('quote',''));quote.pack(fill='x',pady=8)
        ttk.Label(panel,text='我的批注').pack(anchor='w');editor=tk.Text(panel,height=6,wrap='word',undo=True);editor.insert('1.0',item.get('text',''));editor.pack(fill='both',expand=True,pady=8);editor.focus_set()
        def save():
            item.update(text=editor.get('1.0','end-1c'),quote=quote.get('1.0','end-1c'))
            try:self.add_annotation(item)
            except Exception as exc:messagebox.showerror('保存失败',str(exc),parent=dialog);return
            dialog.destroy()
        ttk.Button(panel,text='保存批注',command=save).pack(anchor='e')

    def delete_annotation(self):
        a=self.selected_annotation()
        if not a:return
        if not messagebox.askyesno('删除批注','删除这条本地批注？',parent=self.frame):return
        previous=list(self.annotations);self.annotations=[x for x in self.annotations if x['id']!=a['id']]
        try:self.persist_annotations()
        except Exception as exc:self.annotations=previous;messagebox.showerror('保存失败',str(exc),parent=self.frame);return
        self.refresh_annotations();self.draw_annotations()

    def export_notes(self):
        if not self.rid:return
        self.save_notes();path=filedialog.asksaveasfilename(parent=self.frame,title='导出阅读笔记与批注',defaultextension='.md',filetypes=[('Markdown','*.md'),('Text','*.txt')])
        if not path:return
        lines=['# '+self.title.get(),'','## 阅读笔记','',self.notes.get('1.0','end-1c'),'','## 高亮与批注','']
        for a in sorted(self.annotations,key=lambda a:a['page']):lines.extend([f"### 第 {a['page']+1} 页",'',a.get('quote',''),'',a.get('text',''),''])
        try:Path(path).write_text('\n'.join(lines),encoding='utf-8');self.note_status.set('已导出笔记与批注')
        except OSError as exc:messagebox.showerror('导出失败',str(exc),parent=self.frame)

    def reference_panel(self):
        if getattr(self,'reference_window',None) and self.reference_window.winfo_exists():self.reference_window.deiconify();self.reference_window.lift();return
        window=tk.Toplevel(self.frame);self.reference_window=window;window.title('参考文献 · 独立侧栏');window.geometry('820x640');window.minsize(760,560);style_dialog(window)
        header=ttk.Frame(window,padding=16);header.pack(fill='x');ttk.Label(header,text='参考文献',font=(FONT,17,'bold')).pack(side='left')
        ttk.Label(window,text='保留原文标号；带 * 的数字仅为提取顺序，不能直接当作正文引用号。扫描件与复杂版式可能漏检。',style='Muted.TLabel',padding=(16,0,16,12)).pack(fill='x')
        self.reference_tree=ttk.Treeview(window,columns=('number','title','doi'),show='headings',height=4);self.reference_tree.heading('number',text='标号');self.reference_tree.column('number',width=58,stretch=False);self.reference_tree.heading('title',text='提取的文献 / 引用');self.reference_tree.heading('doi',text='DOI');self.reference_tree.column('title',width=490);self.reference_tree.column('doi',width=200)
        self.reference_tree.pack(fill='both',expand=True,padx=16)
        self.raw=tk.StringVar();ttk.Label(window,textvariable=self.raw,wraplength=760,style='Muted.TLabel',padding=16).pack(fill='x')
        self.reference_tree.bind('<<TreeviewSelect>>',lambda _:self.raw.set(self.get_reference().get('raw','')[:300] if self.get_reference() else ''))
        actions=ttk.Frame(window,padding=16);actions.pack(fill='x');self.reference_actions=actions;ttk.Button(actions,text='查找原文 / 下载归档',style='Accent.TButton',command=self.query_reference).pack(side='left');ttk.Button(actions,text='先收藏到课题',command=self.collect_reference).pack(side='left',padx=10)
        self.fill_references()

    def fill_references(self):
        self.reference_tree.delete(*self.reference_tree.get_children())
        self.raw.set('')
        for i,ref in enumerate(self.references):self.reference_tree.insert('','end',iid=str(i),values=(ref.get('number') or f'{i+1}*',ref['title'],ref['doi'] or '待核对'))

    def get_reference(self):
        selected=self.reference_tree.selection();return self.references[int(selected[0])] if selected else None

    def query_reference(self):
        ref=self.get_reference()
        if ref:self.on_query(ref['query']);self.reference_window.withdraw()

    def collect_reference(self):
        ref=self.get_reference()
        if ref:self.on_collect(ref)

    def scroll(self,event):self.canvas.yview_scroll(-int(event.delta/120),'units');return 'break'
    def close(self):self.save_notes()
