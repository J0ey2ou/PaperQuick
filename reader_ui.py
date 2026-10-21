"""Native offline PDF reader, autosaved notes and detachable reference sidebar."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import time
import uuid
from library_core import Library,display_name
from pdf_reader_core import document_info,render_page,render_page_data,page_sizes,extract_text,region_text,original_pdf_annotations
from references import parse_references
from ui_theme import BG,PANEL,FG,MUTED,ACCENT,FONT,style_dialog
from reader_workflow_ui import ReaderWorkflow

class ReaderPage(ReaderWorkflow):
    def __init__(self,parent,directory,on_query,on_collect):
        self.directory=Path(directory);self.on_query=on_query;self.on_collect=on_collect
        self.frame=tk.Frame(parent,bg=BG);self.events=queue.Queue();self.rid=None;self.path=None;self.page=0;self.count=0;self.scale=1.2;self.generation=0;self.references=[];self.loading=False;self.dirty=False;self.note_job=None
        self.annotations=[];self.selection_start=None;self.image_size=None;self.fit_pending=True
        self.source_path=None;self._import_busy=False;self._preview_jobs=[];self.attachment_manager=None;self.conversion_window=None;self.comparison=None;self.notes_visible=True;self.closed=False;self._compare_layout_token=0
        self.workflow_state()
        header=ttk.Frame(self.frame,padding=(24,14));self.header=header;header.pack(fill='x')
        title=ttk.Frame(header);title.pack(side='left');ttk.Label(title,text='文献阅读',font=(FONT,21,'bold')).pack(anchor='w')
        self.title=tk.StringVar(value='打开 PDF 或 Word，在这里阅读与记录想法');title_label=ttk.Label(title,textvariable=self.title,style='Muted.TLabel',wraplength=520);title_label.pack(anchor='w',pady=(5,0))
        header.bind('<Configure>',lambda e:title_label.configure(wraplength=max(180,e.width-520)))
        ttk.Button(header,text='打开 PDF / Word / TXT',command=self.choose_pdf).pack(side='right');ttk.Button(header,text='参考文献侧栏',command=self.reference_panel).pack(side='right',padx=8)
        ttk.Button(header,text='最近阅读',command=self.toggle_recent_reading).pack(side='right')
        self.recent_panel=ttk.Frame(self.frame,padding=(24,0,24,12))
        recent_bar=ttk.Frame(self.recent_panel);recent_bar.pack(fill='x',pady=(0,6))
        self.recent_hint=tk.StringVar(value='最近阅读 · 点击文献继续阅读')
        ttk.Label(recent_bar,textvariable=self.recent_hint,style='Muted.TLabel').pack(side='left')
        ttk.Button(recent_bar,text='收起',command=self.recent_panel.pack_forget,style='Compact.TButton').pack(side='right')
        recent_list=ttk.Frame(self.recent_panel);recent_list.pack(fill='x')
        self.recent_tree=ttk.Treeview(recent_list,columns=('title','time'),show='headings',height=4,selectmode='browse')
        self.recent_tree.heading('title',text='文献标题');self.recent_tree.heading('time',text='最近阅读时间')
        self.recent_tree.column('title',width=650);self.recent_tree.column('time',width=160,stretch=False)
        recent_scroll=ttk.Scrollbar(recent_list,orient='vertical',command=self.recent_tree.yview)
        recent_scroll.pack(side='right',fill='y');self.recent_tree.configure(yscrollcommand=recent_scroll.set);self.recent_tree.pack(fill='x',expand=True)
        self.recent_tree.bind('<ButtonRelease-1>',self.open_recent_reading)
        self.recent_tree.bind('<Return>',lambda _:self.open_recent_reading())
        self.controls_host=ttk.Panedwindow(self.frame,orient='horizontal');self.controls_host.pack(fill='x')
        control_left=ttk.Frame(self.controls_host);self.controls_host.add(control_left,weight=4)
        from icon_toolbar import IconToolbar
        self.tool=tk.StringVar(value='选择文字')
        self.annotation_color=tk.StringVar(value='黄色');self.colors={'黄色':'#ffd65c','绿色':'#66dfac','蓝色':'#76b9ff','粉色':'#f795c7'}
        self.page_input=tk.StringVar();self.page_label=tk.StringVar(value='尚未打开文档')
        toolbar=IconToolbar(control_left);self.toolbar=toolbar;toolbar.pack(fill='x',padx=(24,12),pady=(0,6))
        for icon,label,command in [
            ('previous','上一页',lambda:self.change_page(-1)),('next','下一页',lambda:self.change_page(1)),
            ('minus','缩小',lambda:self.zoom(.85)),('plus','放大',lambda:self.zoom(1.18)),('fit','适合宽度',self.fit_width),
            ('save','保存笔记',self.save_notes),('document','正文与附件',self.attachment_panel),
            ('compare','附件比对',self.toggle_comparison),('convert','Word / PDF 转换',self.conversion),
            ('notes','显示 / 收起笔记',self.toggle_notes),('focus','专注阅读',self.toggle_focus),('edit','编辑原文',self.edit_document)]:
            toolbar.add(icon,label,command)
        for icon,label in [('select','选择文字'),('hand','拖动阅读'),('highlight','框选高亮'),('comment','框选批注')]:
            toolbar.add(icon,label,lambda:None,variable=self.tool,value=label)
        def choose_color():
            menu=tk.Menu(toolbar,tearoff=False)
            for name in self.colors:menu.add_radiobutton(label=name,variable=self.annotation_color,value=name)
            try:menu.tk_popup(color_button.winfo_rootx(),color_button.winfo_rooty()+32)
            finally:menu.grab_release()
        color_button=toolbar.add('color','高亮 / 批注颜色',choose_color,color=lambda:self.colors[self.annotation_color.get()])
        self.annotation_color.trace_add('write',lambda *_:toolbar.refresh_icons(force=True))
        toolbar.add('bookmark','添加书签',self.add_bookmark)
        toolbar.add('continuous','连续阅读 / 单页阅读',self.toggle_continuous,variable=self.continuous)
        toolbar.add('camera','截图到笔记',self.screenshot_tool)
        toolbar.add('image','框选图片供 ChatGPT 讨论',self.chat_image_tool)
        toolbar.add('document','返回分页阅读',self.show_paged_view)
        toolbar.add('references','嵌入参考文献',self.dock_references)
        toolbar.add_page(self.page_input,self.jump,self.page_label)
        body=ttk.Frame(self.frame,padding=(24,0));self.body=body;body.pack(fill='both',expand=True)
        splitter=ttk.Panedwindow(body,orient='horizontal');self.splitter=splitter;splitter.pack(fill='both',expand=True)
        notes_panel=ttk.Frame(splitter,style='Card.TFrame',padding=12,width=340);self.notes_panel=notes_panel
        ttk.Label(notes_panel,text='阅读笔记',style='Card.TLabel',font=(FONT,12,'bold')).pack(anchor='w')
        self.note_status=tk.StringVar(value='笔记保存在本地文献库');ttk.Label(notes_panel,textvariable=self.note_status,style='CardMuted.TLabel',wraplength=300).pack(anchor='w',pady=(8,12))
        self.notebook=ttk.Notebook(notes_panel);self.notebook.pack(fill='both',expand=True)
        self.note_tab=ttk.Frame(self.notebook);self.annotation_tab=ttk.Frame(self.notebook)
        self.notebook.add(self.note_tab,text='笔记编辑');self.notebook.add(self.annotation_tab,text='高亮 / 批注')
        note_buttons=IconToolbar(self.note_tab);self.note_toolbar=note_buttons;note_buttons.pack(fill='x',pady=3)
        for icon,label,command in [('edit','编辑 / 新段落',self.new_paragraph),('document','插入页码',self.insert_page),('notes','研究笔记模板',self.note_template),('save','导出笔记',self.export_notes),('bold','加粗',lambda:self.format_note('bold')),('italic','斜体',lambda:self.format_note('italic')),('image','插入图片',self.insert_note_image),('camera','截图到笔记',self.screenshot_tool)]:
            note_buttons.add(icon,label,command)
        self.notes=tk.Text(self.note_tab,height=4,width=28,bg='#0b1627',fg=FG,insertbackground=ACCENT,relief='solid',borderwidth=1,wrap='word',padx=12,pady=12,font=(FONT,11),undo=True,takefocus=True,state='normal',exportselection=False)
        note_scroll=ttk.Scrollbar(self.note_tab,command=self.notes.yview);note_scroll.pack(side='right',fill='y');self.notes.configure(yscrollcommand=note_scroll.set)
        self.notes.pack(fill='both',expand=True);self.notes.bind('<<Modified>>',self.notes_changed)
        self.notes.tag_configure('bold',font=(FONT,11,'bold'));self.notes.tag_configure('italic',font=(FONT,11,'italic'))
        self.notes.bind('<Control-s>',lambda _:self.save_key());self.notes.bind('<Control-S>',lambda _:self.save_key())
        self.notes.bind('<Button-1>',lambda _:self.notes.focus_set(),add='+')
        menu=tk.Menu(self.notes,tearoff=False)
        for label,event in [('撤销','<<Undo>>'),('重做','<<Redo>>'),('剪切','<<Cut>>'),('复制','<<Copy>>'),('粘贴','<<Paste>>'),('全选','<<SelectAll>>')]:menu.add_command(label=label,command=lambda e=event:self.notes.event_generate(e))
        menu.add_separator();menu.add_command(label='插入图片',command=self.insert_note_image);menu.add_command(label='粘贴截图 / 图片',command=self.paste_note_image)
        self.notes.bind('<Button-3>',lambda e:menu.tk_popup(e.x_root,e.y_root))
        self.annotation_list=ttk.Treeview(self.annotation_tab,columns=('page','text'),show='headings',height=4)
        self.annotation_list.heading('page',text='页');self.annotation_list.heading('text',text='摘录 / 批注');self.annotation_list.column('page',width=38,stretch=False);self.annotation_list.column('text',width=220)
        self.annotation_list.pack(fill='both',expand=True);self.annotation_list.bind('<Double-1>',lambda _:self.locate_annotation())
        annotation_buttons=ttk.Frame(self.annotation_tab);annotation_buttons.pack(fill='x',pady=8)
        for i,(label,command) in enumerate([('定位',self.locate_annotation),('编辑',self.edit_annotation),('删除',self.delete_annotation)]):ttk.Button(annotation_buttons,text=label,command=command,width=6).grid(row=0,column=i,sticky='ew');annotation_buttons.columnconfigure(i,weight=1)
        ttk.Label(self.annotation_tab,text='在 PDF 上拖框高亮或批注；双击列表回到原页。\n批注保存在本地库，原 PDF 保持原样。',wraplength=300,style='Muted.TLabel').pack(fill='x',pady=5)
        viewer=ttk.Frame(splitter,style='Card.TFrame');self.viewer=viewer;splitter.add(viewer,weight=4);splitter.add(notes_panel,weight=1)
        self.canvas=tk.Canvas(viewer,bg='#142137',highlightthickness=0)
        v=ttk.Scrollbar(viewer,orient='vertical',command=self.canvas.yview);h=ttk.Scrollbar(viewer,orient='horizontal',command=self.canvas.xview)
        self.vertical_scroll=v;self.horizontal_scroll=h
        self.canvas.configure(yscrollcommand=v.set,xscrollcommand=h.set);v.pack(side='right',fill='y');h.pack(side='bottom',fill='x');self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<MouseWheel>',self.scroll)
        self.canvas.bind('<Button-1>',self.begin_selection);self.canvas.bind('<B1-Motion>',self.move_selection);self.canvas.bind('<ButtonRelease-1>',self.end_selection)
        self.canvas.bind('<Double-1>',self.edit_clicked_annotation)
        self.reading_menu=tk.Menu(self.canvas,tearoff=False)
        self.reading_menu.add_command(label='添加阅读笔记（当前页 / 最近选区）',command=self.context_note)
        self.reading_menu.add_command(label='在此处添加批注',command=self.context_comment)
        self.reading_menu.add_command(label='添加当前页书签',command=self.add_bookmark)
        self.canvas.bind('<Button-3>',self.reading_context)
        self.status=tk.StringVar(value='安心阅读，笔记自动保存')
        ttk.Label(self.frame,textvariable=self.status,style='Muted.TLabel',padding=(24,12)).pack(fill='x')
        self.canvas.create_text(260,200,text='从文献分类或图谱打开文档\n也可点击“打开 PDF / Word”',fill=MUTED,font=(FONT,14),justify='center')
        self.workflow_widgets()
        self.frame.after(100,self.poll)

    def toggle_recent_reading(self):
        if self.recent_panel.winfo_manager():
            self.recent_panel.pack_forget();return
        lib=Library(self.directory)
        try:records=lib.recent_read()
        finally:lib.close()
        self.recent_tree.delete(*self.recent_tree.get_children())
        for record in records:
            self.recent_tree.insert('', 'end',iid=record['id'],values=(record['title'] or '未命名文献',time.strftime('%Y-%m-%d %H:%M',time.localtime(record['last_read']))))
        self.recent_hint.set('最近阅读 · 最近 50 篇，点击文献继续阅读' if records else '还没有阅读记录，打开一篇文献后会显示在这里。')
        self.recent_panel.pack(fill='x',after=self.header)

    def open_recent_reading(self,event=None):
        rid=self.recent_tree.identify_row(event.y) if event is not None else next(iter(self.recent_tree.selection()),None)
        if not rid:return
        try:
            self.open(rid)
            if self.rid==rid:self.recent_panel.pack_forget()
        except (ValueError,OSError) as exc:
            self.status.set('无法打开最近阅读的文献：'+str(exc))

    def open(self,rid,record_read=True,attachment_id=None):
        if self.busy:raise ValueError('正在收纳或转换文档，请完成后再切换文献。')
        if self.editor_dirty and not messagebox.askyesno('原文尚未保存','放弃本次原文修改并打开文献？',parent=self.frame):return
        self.editor_dirty=False;self.word_editing=False
        if self.text_view:self.text_panel.pack_forget()
        self.vertical_scroll.pack(side='right',fill='y');self.horizontal_scroll.pack(side='bottom',fill='x');self.canvas.pack(fill='both',expand=True)
        if self.rid and self.rid!=rid:
            for window in (self.attachment_manager,self.conversion_window):
                if window and not window.closed:window.close()
        if getattr(self,'on_document_change',None):self.on_document_change()
        self.save_notes()
        lib=Library(self.directory)
        try:
            record=lib.get(rid)
            attachment=next((a for a in record['attachments'] if a['id']==attachment_id),None) if attachment_id else lib.primary_attachment(rid)
            if not attachment:raise ValueError('这篇文献尚未添加正文。请在“正文与附件”中添加 PDF 或 Word，并设为正文。')
            self.rid=rid;self.attachment_id=attachment['id'];self.source_path=self.directory/attachment['path'];self.path=None;self.page=0;self.count=0;self.generation+=1;self.loading=True;self.fit_pending=True;self.image_size=None
            self._pending_location=None
            self.document_canvas.reset()
            if record_read:
                changes={'read_count':record.get('read_count',0)+1,'last_read':time.time()}
                if record.get('status') in ('未读','待读'):changes['status']='在读'
                lib.save(changes,rid=rid)
            self.title.set(display_name(record));self.notes.configure(state='normal');self.notes.delete('1.0','end');self.notes.insert('1.0',record.get('notes',''));self.notes.edit_reset();self.notes.edit_modified(False);self.dirty=False
            self.load_note_images(record)
            for tag,ranges in record.get('note_styles',{}).items():
                if tag in ('bold','italic'):
                    for start,end in ranges:
                        try:self.notes.tag_add(tag,start,end)
                        except tk.TclError:pass
            self.annotations=record.get('annotations',[]);self._annotation_ids={a['id'] for a in self.annotations};self.original_annotations=[];self.last_selection=None;self.refresh_annotations()
            self.references=record.get('references',[]);self.note_status.set('笔记会自动保存')
        finally:lib.close()
        if getattr(self,'ai_panel',None):self.ai_panel.document_changed()
        self.hide_comparison();self.canvas.delete('all');self.page_label.set('正在打开文档…')
        generation=self.generation;source=self.source_path;scale=self.scale;self.status.set('正在准备 Word 阅读预览…' if source.suffix.lower() in ('.doc','.docx') else '正在本地读取 PDF…')
        preview_done=threading.Event()
        if source.suffix.lower() in ('.doc','.docx'):self.register_preview(preview_done)
        def job():
            try:
                if source.suffix.lower() in ('.txt','.md'):
                    from reading_documents import read_text_file
                    text=read_text_file(source);self.events.put(('text-document',generation,(text,parse_references(text))));return
                from document_conversion import preview_pdf
                try:path=preview_pdf(source,self.directory/'cache'/'document-previews')
                finally:preview_done.set()
                count=document_info(path);image,chars=render_page_data(path,0,scale);sizes=page_sizes(path);self.events.put(('prepared',generation,(path,count,0,image,chars,sizes)))
                text=extract_text(path);refs=parse_references(text);self.events.put(('references',generation,(text,refs)))
                if source.suffix.lower()=='.pdf':comments=original_pdf_annotations(path)
                else:
                    from reading_documents import docx_comments,locate_word_comments,word_content
                    comments=locate_word_comments(docx_comments(source),path) if source.suffix.lower()=='.docx' else word_content(source)['comments']
                self.events.put(('original-comments',generation,comments))
            except Exception as exc:preview_done.set();self.events.put(('error',generation,str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def choose_pdf(self):
        if self._import_busy:return
        source=filedialog.askopenfilename(parent=self.frame,filetypes=[('文献文档','*.pdf *.doc *.docx *.txt *.md')])
        if not source:return
        self._import_busy=True;self.status.set('正在本地收纳文档…')
        def job():
            lib=None
            try:
                lib=Library(self.directory);rid=lib.import_document(source,lib.projects()[0]['id']);self.events.put(('open',0,rid))
            except Exception as exc:self.events.put(('import_error',0,str(exc)))
            finally:
                if lib:lib.close()
        threading.Thread(target=job,daemon=True).start()

    def change_page(self,delta):
        target=self.page+delta
        if not self.path or not 0<=target<self.count or self.loading:return
        lib=Library(self.directory)
        try:a=next(a for a in lib.get(self.rid)['attachments'] if a['id']==self.attachment_id)
        finally:lib.close()
        current=self.directory/a['path'];self.source_path=current
        if current.suffix.lower()=='.pdf' and current!=self.path:self.path=current;self.page=target;self.render();return
        if self.continuous.get() and self.document_canvas.goto(target):return
        self.page=target;self.render()

    def zoom(self,factor):
        if not self.path or self.loading:return
        self._compare_layout_token+=1  # A user's zoom takes precedence over the initial split-layout fit.
        self.scale=max(.45,min(3,self.scale*factor));self.render()

    def render(self):
        if self.loading:return
        lib=Library(self.directory)
        try:
            attachment=next(a for a in lib.get(self.rid)['attachments'] if a['id']==self.attachment_id)
            self.source_path=self.directory/attachment['path']
            if self.source_path.suffix.lower()=='.pdf':self.path=self.source_path
        except (ValueError,StopIteration) as exc:
            self.status.set('附件不可用，请重新打开文献：'+str(exc));return
        finally:lib.close()
        self.loading=True;generation=self.generation;page=self.page;path=self.path;scale=self.scale;self.status.set('正在打开这一页…')
        def job():
            try:
                image,chars=render_page_data(path,page,scale);self.events.put(('page',generation,(self.count,page,image,chars,page_sizes(path))))
            except Exception as exc:self.events.put(('error',generation,str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def poll(self):
        if self.closed:return
        self.sync_incoming_annotations()
        self.apply_link_location()
        try:
            while True:
                kind,generation,value=self.events.get_nowait()
                if kind=='open':
                    self._import_busy=False;self.open(value)
                    if getattr(self,'on_library_changed',None):self.on_library_changed()
                    continue
                if kind=='import_error':self._import_busy=False;self.status.set('导入未完成：'+value);continue
                if generation!=self.generation:continue
                if self.workflow_event(kind,value):continue
                if kind in ('page','prepared'):
                    if kind=='prepared':self.path=value[0];value=value[1:]
                    from PIL import ImageTk
                    self.loading=False;self.count,self.page,image,chars,sizes=value;self.photo=ImageTk.PhotoImage(image,master=self.frame)
                    self.image_size=(image.width,image.height)
                    self.document_canvas.adopt(self.path,self.page,self.count,image,chars,sizes);self.draw_annotations()
                    self.page_input.set(str(self.page+1))
                    self.page_label.set(f'第 {self.page+1} / {self.count} 页 · {round(self.scale*100)}%');self.status.set(('Word 阅读预览' if self.source_path and self.source_path.suffix.lower() in ('.doc','.docx') else '本地 PDF 阅读')+' · 笔记自动保存')
                    if self.fit_pending:self.fit_pending=False;self.fit_width()
                elif kind=='references':
                    text,self.references=value;lib=Library(self.directory)
                    try:
                        primary=lib.primary_attachment(self.rid)
                        if not primary or primary['id']!=self.attachment_id:
                            self.status.set('正文已更新，请重新打开文献阅读。');continue
                        lib.save({'text':text,'references':self.references},rid=self.rid)
                    finally:lib.close()
                    self.status.set(f'已在本地提取 {len(self.references)} 条参考文献；标题提取结果需要核对。')
                    if getattr(self,'reference_window',None) and self.reference_window.winfo_exists():self.fill_references()
                    self.fill_docked_references()
                elif kind=='annotation':
                    self.last_selection=value
                    if value['kind']=='截图到笔记':
                        self.insert_note_image(self.document_canvas.screenshot(value['page'],value['rect']));self.add_point_marker('笔记','阅读截图',page=value['page'],point=value['rect'][:2])
                    elif value['kind']=='复制文字':
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
            text,images=self.note_snapshot();lib=Library(self.directory);lib.save({'notes':text,'note_styles':styles,'note_images':images},rid=self.rid);self.dirty=False;self.note_status.set('已自动保存到本机')
        except Exception as exc:self.note_status.set('保存失败：'+str(exc));raise
        finally:
            if lib:lib.close()

    def save_key(self):self.save_notes();return 'break'

    def reading_context(self,event):
        if not self.rid or not self.context_location(event):return
        self.cancel_box_selection()
        try:self.reading_menu.tk_popup(event.x_root,event.y_root)
        finally:self.reading_menu.grab_release()

    def context_note(self):
        if not self.rid:return
        self.new_paragraph();index=self.notes.index('end-1c');page=getattr(self,'context_page',self.page);self.notes.insert('end',f'[第 {page+1} 页]\n')
        item=self.current_selection()
        if item and item.get('quote'):self.notes.insert('end',item['quote']+'\n\n我的笔记：')
        self.notes.mark_set('insert','end-1c');self.notes.see('end');self.notes.focus_set();self.notes_changed()
        self.add_point_marker('笔记','阅读笔记',note_index=index)

    def context_comment(self):
        if not self.rid:return
        x,y=getattr(self,'context_point',(.1,.1))
        self.annotation_editor({'id':uuid.uuid4().hex,'attachment':self.attachment_id,'page':getattr(self,'context_page',self.page),'rect':[x,y,min(1,x+.025),min(1,y+.02)],'color':self.colors[self.annotation_color.get()],'kind':'批注','text':'','quote':'','created':time.time()})

    def format_note(self,tag):
        if not self.rid:return
        try:start,end=self.notes.index('sel.first'),self.notes.index('sel.last')
        except tk.TclError:self.note_status.set('先选中笔记文字，再设置加粗或斜体。');return
        if tag in self.notes.tag_names(start):self.notes.tag_remove(tag,start,end)
        else:self.notes.tag_add(tag,start,end)
        self.dirty=True;self.save_notes();self.notes.focus_set()

    def new_paragraph(self):
        if not self.rid:self.status.set('先打开一篇 PDF，再记录笔记。');return
        self.show_notes()
        self.notebook.select(self.note_tab);self.notes.configure(state='normal');self.notes.insert('end','\n\n' if self.notes.get('1.0','end-1c') else '');self.notes.mark_set('insert','end-1c');self.notes.see('insert');self.notes.focus_set()

    def insert_page(self):
        if not self.rid:return
        self.show_notes()
        self.notebook.select(self.note_tab);self.notes.insert('insert',f'\n[第 {self.page+1} 页] ');self.notes.focus_set()

    def note_template(self):
        if not self.rid:return
        from reading_documents import DEFAULT_NOTE_TEMPLATE
        lib=Library(self.directory)
        try:template=lib.setting('research_note_template',DEFAULT_NOTE_TEMPLATE)
        finally:lib.close()
        self.new_paragraph();self.notes.insert('end',template);self.notes.see('end')

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
        self.selection_start=None;self.canvas.delete('rubber-band')
        if self.tool.get() in ('浏览','选择文字'):self.document_canvas.begin(event);return
        if self.tool.get()=='拖动阅读':self.canvas.scan_mark(event.x,event.y);return
        x=self.canvas.canvasx(event.x);y=self.canvas.canvasy(event.y)
        self.selection_page=self.document_canvas.page_at(x,y)
        if self.selection_page not in self.document_canvas.layout:return
        left,top,w,h=self.document_canvas.layout[self.selection_page]
        if not (left<=x<=left+w and top<=y<=top+h):return
        if self.selection_page not in self.document_canvas.cache:
            self.status.set('这一页仍在准备，请稍后框选。');return
        self.document_canvas.selection=None;self.document_canvas.selection_text={};self.document_canvas.selecting=False;self.canvas.delete('selection')
        self.selection_start=(x,y)

    def move_selection(self,event):
        if self.tool.get() in ('浏览','选择文字'):self.document_canvas.move(event);return
        if self.tool.get()=='拖动阅读':self.canvas.scan_dragto(event.x,event.y,gain=1);return
        if not self.selection_start:return
        box=self.document_canvas.box_selection(self.canvas.canvasx(event.x),self.canvas.canvasy(event.y))
        self.canvas.delete('rubber-band')
        if box:self.canvas.create_rectangle(*box,outline='#2389e8',width=2,fill='#74b9ff',stipple='gray12',tags='rubber-band')

    def end_selection(self,event):
        if self.tool.get() in ('浏览','选择文字'):self.document_canvas.finish(event);return
        if not self.selection_start:return
        box=self.document_canvas.box_selection(self.canvas.canvasx(event.x),self.canvas.canvasy(event.y));self.selection_start=None;self.canvas.delete('rubber-band')
        if not box:return
        x1,y1,x2,y2=box
        if min(x2-x1,y2-y1)<4:return
        left,top,w,h=self.document_canvas.layout[self.selection_page]
        rect=[max(0,min(1,(min(x1,x2)-left)/w)),max(0,min(1,(min(y1,y2)-top)/h)),max(0,min(1,(max(x1,x2)-left)/w)),max(0,min(1,(max(y1,y2)-top)/h))]
        item={'id':uuid.uuid4().hex,'attachment':self.attachment_id,'page':self.selection_page,'rect':rect,'color':self.colors[self.annotation_color.get()],'kind':self.tool.get(),'text':'','quote':'','created':time.time()}
        if item['kind'] in ('截图到笔记','框选图片'):
            self.last_selection=item;self.context_page=item['page']
            try:
                if item['kind']=='截图到笔记':
                    image=self.document_canvas.screenshot(item['page'],rect)
                    self.insert_note_image(image);self.add_point_marker('笔记','阅读截图',page=item['page'],point=rect[:2])
                    self.status.set('选框图片已保存到笔记。')
                else:
                    self.canvas.create_rectangle(*box,outline='#2389e8',width=2,tags='selection')
                    self.status.set('图片已框选；右键“用 ChatGPT 讨论选框图片”。')
            except (ValueError,OSError) as exc:self.status.set(str(exc))
            finally:self.tool.set('选择文字')
            return
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
        self.show_notes();self.notebook.select(self.annotation_tab);self.refresh_annotations();self.draw_annotations();self.status.set('高亮 / 批注已保存到本机')

    def persist_annotations(self):
        lib=Library(self.directory)
        try:
            self.annotations=lib.merge_annotations(self.rid,self.annotations,getattr(self,'_annotation_ids',()))
            self._annotation_ids={a['id'] for a in self.annotations}
        finally:lib.close()

    def sync_incoming_annotations(self):
        if not self.rid or time.monotonic()-getattr(self,'_annotation_checked',0)<1.2:return
        self._annotation_checked=time.monotonic()
        import sqlite3,json
        db=None
        try:
            db=sqlite3.connect((self.directory/'library.sqlite').resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)
            row=db.execute("SELECT json_extract(data,'$.annotations') FROM papers WHERE id=?",(self.rid,)).fetchone()
            annotations=json.loads(row[0] or '[]') if row else []
            if annotations!=self.annotations:
                added={a['id'] for a in annotations}-getattr(self,'_annotation_ids',set())
                self.annotations=annotations;self._annotation_ids={a['id'] for a in annotations}
                self.refresh_annotations();self.draw_annotations()
                if added:self.status.set('收到新的文献批注；在“高亮 / 批注”中可查看和定位。')
        except (sqlite3.Error,OSError,ValueError):pass
        finally:
            if db:db.close()

    def refresh_annotations(self):
        self.annotation_list.delete(*self.annotation_list.get_children())
        for a in sorted(self.annotations+self.original_annotations,key=lambda a:(a.get('page',0),a.get('created',0))):
            if a.get('attachment')==getattr(self,'attachment_id',None):self.annotation_list.insert('','end',iid=a['id'],values=(a.get('page',0)+1,('原批注 · ' if a.get('original') else '')+(a.get('text') or a.get('quote') or '区域高亮').replace('\n',' ')[:100]))

    def draw_annotations(self):
        self.workflow_draw_annotations()

    def selected_annotation(self):
        ids=self.annotation_list.selection();return next((a for a in self.annotations+self.original_annotations if ids and a['id']==ids[0]),None)

    def locate_annotation(self):
        a=self.selected_annotation()
        if not a or self.loading:return
        if a['page']!=self.page:self.change_page(a['page']-self.page)
        def locate():
            if self.loading:self.frame.after(80,locate);return
            if self.rid and self.image_size:
                x,y,_,_=self.document_canvas.coords(a['page'],a['rect']);height=float(self.canvas.cget('scrollregion').split()[3]);self.canvas.yview_moveto(max(0,(y-60)/height));self.status.set(a.get('text') or a.get('quote') or '区域高亮')
        locate()

    def edit_annotation(self):
        a=self.selected_annotation()
        if a:
            if a.get('original'):self.activate_marker(a)
            else:self.annotation_editor(dict(a))

    def add_bookmark(self):
        if not self.rid or not self.count:return
        self.add_annotation({'id':uuid.uuid4().hex,'attachment':self.attachment_id,'page':self.page,'rect':[0,0,0,0],'color':self.colors[self.annotation_color.get()],'kind':'书签','text':f'第 {self.page+1} 页书签','quote':'','created':time.time()})

    def edit_clicked_annotation(self,event):
        self.workflow_click_annotation(event)

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
        if a.get('original'):self.status.set('这是原文件批注，请在 Word 或 PDF 原文中修改。');return
        if not messagebox.askyesno('删除批注','删除这条本地批注？',parent=self.frame):return
        previous=list(self.annotations);self.annotations=[x for x in self.annotations if x['id']!=a['id']]
        try:self.persist_annotations()
        except Exception as exc:self.annotations=previous;messagebox.showerror('保存失败',str(exc),parent=self.frame);return
        self.refresh_annotations();self.draw_annotations()

    def export_notes(self):
        if not self.rid:return
        self.save_notes();path=filedialog.asksaveasfilename(parent=self.frame,title='导出阅读笔记与批注',defaultextension='.html',filetypes=[('网页笔记（含图片）','*.html'),('Markdown','*.md'),('Text','*.txt')])
        if not path:return
        try:self.workflow_export_notes(Path(path))
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
        menu=tk.Menu(window,tearoff=False);menu.add_command(label='嵌入阅读页顶部',command=self.dock_references);menu.add_command(label='在阅读位置留下引用链接',command=lambda:self.mark_reference(self.get_reference()));menu.add_command(label='在阅读页查原文 / 下载归档',command=lambda:self.lookup_reference(self.get_reference()));menu.add_command(label='重新提取参考文献',command=self.reextract_references)
        def popup(event):
            iid=self.reference_tree.identify_row(event.y)
            if iid:self.reference_tree.selection_set(iid)
            try:menu.tk_popup(event.x_root,event.y_root)
            finally:menu.grab_release()
        self.reference_tree.bind('<Button-3>',popup)

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

    @property
    def busy(self):
        return self._import_busy or self.document_job or any(window and not window.closed and window.busy for window in (self.attachment_manager,self.conversion_window,getattr(self,'word_citations',None),*self.lookup_windows))

    def can_close(self):
        if self.editor_dirty:self.status.set('原文修改尚未保存，请先按 Ctrl+S 保存。');return False
        if self.busy:self.status.set('正在收纳或转换文档，完成后即可关闭。');return False
        if any(not job.is_set() for job in self._preview_jobs):self.status.set('正在准备 Word 预览，完成后即可关闭。');return False
        return True

    def register_preview(self,done):
        self._preview_jobs=[job for job in self._preview_jobs if not job.is_set()]+[done]

    def attachment_panel(self):
        if not self.rid:self.status.set('请先打开一篇文献，再为它添加附件。');return
        if self.attachment_manager and not self.attachment_manager.closed:
            self.attachment_manager.reload();self.attachment_manager.win.lift();return
        from attachment_ui import AttachmentManager
        self.attachment_manager=AttachmentManager(self.frame,self.directory,self.rid,on_compare=self.compare_attachment,on_changed=self.attachments_changed)

    def attachments_changed(self):
        if not self.rid:return
        if getattr(self,'on_library_changed',None):self.on_library_changed()
        lib=Library(self.directory)
        try:primary=lib.primary_attachment(self.rid);items=lib.get(self.rid)['attachments']
        finally:lib.close()
        if primary and primary['id']!=self.attachment_id:self.open(self.rid,record_read=False)
        elif self.comparison:self.comparison.set_items(items,getattr(self.comparison,'attachment_id',None))

    def compare_attachment(self,attachment):
        if not self.rid:return
        from attachment_ui import AttachmentPreview,readable
        if not readable(attachment):self.status.set('这个附件暂不支持页内预览，请从附件列表选择“外部打开”。');return
        lib=Library(self.directory)
        try:items=lib.get(self.rid)['attachments']
        finally:lib.close()
        if not any(a['id']==attachment['id'] for a in items):self.status.set('这个附件不属于当前文献。请重新选择。');return
        if self.notes_visible:self.splitter.forget(self.notes_panel);self.notes_visible=False
        if not self.comparison:self.comparison=AttachmentPreview(self.splitter,self.directory,self.hide_comparison,on_preview_start=self.register_preview)
        if str(self.comparison.frame) not in self.splitter.panes():self.splitter.add(self.comparison.frame,weight=4)
        self.comparison.set_items(items,attachment['id']);self.comparison.open(attachment)
        self._compare_layout_token+=1;layout_token=self._compare_layout_token
        def fit_settled(previous_width=None):
            if self.closed or not self.comparison or layout_token!=self._compare_layout_token:return
            width=self.canvas.winfo_width()
            if self.loading or width<100 or width!=previous_width:
                self.frame.after(80,lambda:fit_settled(width));return
            self.fit_width()
            if self.comparison.loading:self.comparison.fit_pending=True
            else:self.comparison.fit_width()
        def resize():
            if self.closed or not self.comparison or layout_token!=self._compare_layout_token:return
            if len(self.splitter.panes())>1:self.splitter.sashpos(0,max(260,self.splitter.winfo_width()//2))
            # Tk finishes pane geometry after idle callbacks; wait for a stable width.
            self.frame.after(120,fit_settled)
        self.frame.after_idle(resize)
        self.status.set('正文与附件独立翻页。需要记录时可点击“显示 / 收起笔记”。')

    def toggle_comparison(self):
        if self.comparison and str(self.comparison.frame) in self.splitter.panes():self.hide_comparison();return
        if not self.rid:self.status.set('请先打开一篇文献。');return
        from attachment_ui import readable
        lib=Library(self.directory)
        try:items=[a for a in lib.get(self.rid)['attachments'] if readable(a) and a['id']!=self.attachment_id]
        finally:lib.close()
        if items:self.compare_attachment(items[0])
        else:self.attachment_panel();self.status.set('先添加一份 PDF 或 Word 附件，就能与正文并排比对。')

    def hide_comparison(self):
        self._compare_layout_token+=1
        if self.comparison:
            if str(self.comparison.frame) in self.splitter.panes():self.splitter.forget(self.comparison.frame)
            self.comparison.close();self.comparison=None
        self.show_notes()

    def show_notes(self):
        if not self.notes_visible:self.splitter.add(self.notes_panel,weight=2);self.notes_visible=True

    def toggle_notes(self):
        if self.notes_visible:self.splitter.forget(self.notes_panel);self.notes_visible=False
        else:self.show_notes()
        self.frame.after_idle(self.fit_width)

    def conversion(self):
        if self.conversion_window and not self.conversion_window.closed:self.conversion_window.win.lift();return
        from document_conversion_ui import ConversionWindow
        self.conversion_window=ConversionWindow(self.frame,self.directory,self.rid,self.source_path,on_done=self.converted)

    def converted(self,path,attachment):
        if self.attachment_manager and not self.attachment_manager.closed:self.attachment_manager.reload()
        if attachment:self.compare_attachment(attachment)
        self.status.set('转换已完成，新文件已保存。'+('已在右侧打开比对。' if attachment else ''))

    def scroll(self,event):
        if self.document_canvas.control_wheel(event):return 'break'
        from ui_widgets import wheel_units
        units=wheel_units(self.canvas,event.delta)
        if units:self.canvas.yview_scroll(units,'units')
        return 'break'
    def close(self):
        if not self.can_close():return False
        if getattr(self,'ai_panel',None):self.ai_panel.stop();self.ai_panel.closed=True
        self.save_notes();self.closed=True;self.generation+=1
        if getattr(self,'_chat_bridge',None):self._chat_bridge.close();self._chat_bridge=None
        for window in (self.attachment_manager,self.conversion_window,getattr(self,'word_citations',None)):
            if window and not window.closed:window.close()
        if self.comparison:self.comparison.close();self.comparison=None
        for window in self.lookup_windows:
            if not window.closed:window.close()
        return True
