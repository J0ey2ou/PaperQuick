"""Images, document editing, inline links, and an embedded reference workspace."""
from pathlib import Path
import base64
import html
import io
import json
import os
import re
import shutil
import threading
import time
import uuid
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from PIL import Image,ImageTk,ImageGrab,ImageDraw
from library_core import Library,digest
from reading_documents import DEFAULT_NOTE_TEMPLATE,read_text_file,word_content,edit_word_copy,valid_hyperlink
from ui_theme import FONT,FG,ACCENT,style_dialog


class ReaderWorkflow:
    def workflow_state(self):
        lib=Library(self.directory)
        try:self.continuous=tk.BooleanVar(value=lib.setting('continuous_reading',True));self.marker_size=int(lib.setting('reader_marker_size',18))
        finally:lib.close()
        self.note_images={};self.note_photos={};self.original_annotations=[];self.lookup_windows=[];self.reference_dock=None;self.text_view=None;self.word_editing=False;self.editor_dirty=False;self.editor_raw='';self.document_job=False;self.focus_mode=False;self.text_marker_widgets=[];self.drawing_text_markers=False

    def workflow_widgets(self):
        from reader_canvas import DocumentCanvas
        self.document_canvas=DocumentCanvas(self);self.canvas.configure(yscrollcommand=self.document_canvas.scrolled)
        self.splitter.bind('<ButtonRelease-1>',lambda e:self.frame.after(120,self.fit_width))
        self.reading_menu.add_separator()
        self.reading_menu.add_command(label='用 ChatGPT 讨论选中文字',command=self.chat_selected_text)
        self.reading_menu.add_command(label='用 ChatGPT 讨论选框图片',command=self.chat_selected_image)
        self.reading_menu.add_command(label='框选图片供 ChatGPT 讨论',command=self.chat_image_tool)
        self.reading_menu.add_command(label='重新绑定这篇文献的 ChatGPT 对话',command=self.reset_chat)
        self.reading_menu.add_separator()
        for label,command in [('复制选中文字',self.copy_selected),('插入选区截图到笔记',self.selection_screenshot),('关联已收集文献…',self.link_collected),('在此处添加超链接…',self.add_hyperlink),('在顶部显示参考文献',self.dock_references),('修改 Word 原文',self.edit_document)]:self.reading_menu.add_command(label=label,command=command)
        self.canvas.bind('<Escape>',lambda _:(self.cancel_box_selection(),self.tool.set('选择文字'),'break')[-1])
        self.tool.trace_add('write',lambda *_:self.selection_tool_changed())
        self.notes.bind('<Control-v>',self.paste_note_image);self.notes.bind('<Control-V>',self.paste_note_image)
        self.frame.bind('<Control-s>',lambda e:self.save_document() if self.word_editing else self.save_key())
        self.focus_bar=ttk.Frame(self.frame,padding=(12,5))
        ttk.Button(self.focus_bar,text='返回完整阅读界面',command=self.toggle_focus).pack(side='left')
        ttk.Button(self.focus_bar,text='显示 / 收起笔记',command=self.toggle_notes).pack(side='left',padx=6)
        ttk.Button(self.focus_bar,text='适合宽度',command=self.fit_width).pack(side='left')
        ttk.Label(self.focus_bar,textvariable=self.page_label,style='Muted.TLabel').pack(side='right')

    def note_snapshot(self):
        parts=[];images=[]
        for kind,value,index in self.notes.dump('1.0','end-1c',text=True,image=True):
            if kind=='text':parts.append(value)
            elif kind=='image':
                data=self.note_images.get(value)
                if data:images.append(dict(data,index=index,offset=sum(len(p) for p in parts)));parts.append('\ufffc')
        return ''.join(parts),images

    def load_note_images(self,record):
        self.note_images={};self.note_photos={}
        for item in reversed(record.get('note_images',[])):
            try:
                path=(self.directory/item['path']).resolve()
                if not path.is_relative_to(self.directory.resolve()) or not path.is_file():continue
                index=item['index']
                if self.notes.get(index,index+' +1c')!='\ufffc':continue
                image=Image.open(path).copy();image.thumbnail((390,280));photo=ImageTk.PhotoImage(image,master=self.frame)
                self.notes.delete(index,index+' +1c');self.notes.image_create(index,image=photo,name=item['id']);self.note_images[item['id']]=dict(item);self.note_photos[item['id']]=photo
            except (OSError,KeyError,tk.TclError):continue
        self.notes.edit_modified(False)

    def insert_note_image(self,image=None):
        if not self.rid:self.status.set('请先打开一篇文献。');return
        if image is None:
            path=filedialog.askopenfilename(parent=self.frame,title='插入笔记图片',filetypes=[('图片','*.png *.jpg *.jpeg *.webp *.bmp')])
            if not path:return
            try:
                with Image.open(path) as source:image=source.copy()
            except OSError as exc:messagebox.showerror('图片未打开',str(exc),parent=self.frame);return
        image=image.copy()
        factor=min(1,2400/image.width,(24000000/(image.width*image.height))**.5)
        if factor<1:image=image.resize((max(1,round(image.width*factor)),max(1,round(image.height*factor))))
        image=image.convert('RGB')
        aid='note-image-'+uuid.uuid4().hex;relative=Path('note-assets')/self.rid/(aid+'.png');path=self.directory/relative;path.parent.mkdir(parents=True,exist_ok=True);image.save(path)
        thumb=image.copy();thumb.thumbnail((390,280));photo=ImageTk.PhotoImage(thumb,master=self.frame)
        self.show_notes();self.notebook.select(self.note_tab);self.notes.insert('insert','\n');self.notes.image_create('insert',image=photo,name=aid);self.notes.insert('insert','\n')
        self.note_images[aid]={'id':aid,'path':str(relative),'caption':'阅读图片'};self.note_photos[aid]=photo;self.dirty=True;self.save_notes();self.note_status.set('图片已插入并保存到本机')

    def paste_note_image(self,event=None):
        try:image=ImageGrab.grabclipboard()
        except Exception:return None
        if isinstance(image,Image.Image):self.insert_note_image(image);return 'break'
        if isinstance(image,list) and image:
            try:
                with Image.open(image[0]) as source:self.insert_note_image(source.copy());return 'break'
            except OSError:pass
        return None

    def screenshot_tool(self):
        self.start_box_tool('截图到笔记','在文档页面内拖一个矩形框，松开后插入笔记；Esc 取消。')

    def start_box_tool(self,tool,hint):
        if not self.path or self.loading or (self.text_view and self.text_view.winfo_ismapped()):
            self.status.set('请先打开 PDF / Word 分页阅读，再框选图片。');return
        self.tool.set(tool);self.canvas.focus_set();self.status.set(hint)

    def selection_tool_changed(self):
        self.cancel_box_selection()
        self.canvas.configure(cursor='crosshair' if self.tool.get() in ('截图到笔记','框选图片') else '')

    def cancel_box_selection(self):
        self.selection_start=None;self.canvas.delete('rubber-band')
        if self.tool.get() in ('截图到笔记','框选图片'):
            self.canvas.configure(cursor='crosshair')
        return 'break'

    def current_selection(self):
        item=getattr(self,'last_selection',None)
        if not item or item.get('attachment')!=getattr(self,'attachment_id',None):return None
        pages={region['page'] for region in item.get('regions',[])} or {item.get('page')}
        if getattr(self,'context_page',self.page) not in pages:return None
        return item

    def selection_screenshot(self):
        item=self.current_selection()
        if not item or not item.get('rect') or not self.path:self.screenshot_tool();return
        try:
            self.insert_note_image(self.document_canvas.selection_image(item))
            self.add_point_marker('笔记','阅读截图',page=item['page'],point=[item['rect'][0],item['rect'][1]])
        except Exception as exc:self.status.set(str(exc))

    def chat_image_tool(self):
        self.start_box_tool('框选图片','拖框选择文档中的图表；选好后右键“用 ChatGPT 讨论选框图片”；Esc 取消。')

    def chat_selected_text(self):
        if self.text_view and self.text_view.winfo_ismapped():
            try:quote=self.text_view.get('sel.first','sel.last')
            except tk.TclError:quote=''
        else:
            item=self.current_selection();quote=item.get('quote','') if item else ''
        if not quote.strip():self.status.set('请先选中文字，再右键用 ChatGPT 讨论。');return
        self.open_chat(quote=quote,page=(self.current_selection() or {}).get('page',self.page))

    def chat_selected_image(self):
        item=self.current_selection()
        if not item or not self.path:self.chat_image_tool();return
        try:image=self.document_canvas.selection_image(item)
        except (ValueError,KeyError) as exc:self.status.set(str(exc));return
        self.open_chat(image=image,page=item['page'])

    def chat_bridge(self):
        if not getattr(self,'_chat_bridge',None):
            from chat_bridge import ChatBridge
            self._chat_bridge=ChatBridge(self.directory)
        return self._chat_bridge

    def open_chat(self,quote='',image=None,page=0):
        if not self.rid:return
        import webbrowser
        try:
            url=self.chat_bridge().prepare(self.rid,quote=quote,image=image,page=page)
            if not webbrowser.open(url):raise ValueError('默认浏览器未能打开。请检查浏览器设置。')
            self.status.set('已打开 ChatGPT；需在该浏览器启用新版右键扩展。首次附上正文，检查后点击发送，同篇复用对话。')
        except (ValueError,OSError) as exc:self.status.set('ChatGPT 未打开：'+str(exc))

    def reset_chat(self):
        if not self.rid:return
        if messagebox.askyesno('重新绑定对话','下次讨论将新建对话并重新附上正文，原 ChatGPT 对话保留。继续？',parent=self.frame):
            self.chat_bridge().reset(self.rid);self.status.set('已解除绑定，下次右键讨论将创建新对话。')

    def toggle_continuous(self):
        lib=Library(self.directory)
        try:lib.set_setting('continuous_reading',self.continuous.get())
        finally:lib.close()
        if self.path:self.render()

    def toggle_focus(self):
        self.focus_mode=not self.focus_mode
        if self.focus_mode:
            self.header.pack_forget();self.controls_host.pack_forget();self.focus_bar.pack(fill='x',before=self.body)
        else:
            self.focus_bar.pack_forget();self.header.pack(fill='x',before=self.body);self.controls_host.pack(fill='x',before=self.body)
        if getattr(self,'on_focus_mode',None):self.on_focus_mode(self.focus_mode)
        self.frame.after(150,self.fit_width)

    def context_location(self,event):
        if self.text_view and self.text_view.winfo_ismapped():
            index=self.text_view.index(f'@{event.x},{event.y}');self.context_text_index=index;self.context_page=0;self.context_point=[.05,.05]
            try:quote=self.text_view.get('sel.first','sel.last')
            except tk.TclError:quote=''
            self.last_selection={'page':0,'quote':quote,'rect':[0,0,0,0],'kind':'选择文字','attachment':self.attachment_id} if quote else None
        else:
            point=self.document_canvas.context(event)
            if not point:return False
            self.context_page,self.context_point=point
        return True

    def copy_selected(self):
        if self.text_view and self.text_view.winfo_ismapped():
            self.text_view.event_generate('<<Copy>>');return
        self.document_canvas.copy()

    def add_point_marker(self,kind,text='',page=None,point=None,**fields):
        page=getattr(self,'context_page',self.page) if page is None else page;x,y=point or getattr(self,'context_point',[.1,.1])
        item={'id':uuid.uuid4().hex,'attachment':self.attachment_id,'page':page,'rect':[x,y,x,y],
              'color':'#5aa5eb','kind':kind,'text':text,'quote':'','created':time.time(),**fields}
        if self.text_view and self.text_view.winfo_ismapped():
            item['text_index']=getattr(self,'context_text_index',self.text_view.index('insert'))
            item['text_offset']=int(self.text_view.tk.call('string','length',self.text_view.get('1.0',item['text_index'])))
        self.annotations.append(item);self.persist_annotations();self.refresh_annotations();self.draw_annotations();return item

    def workflow_draw_annotations(self):
        self.canvas.delete('annotation')
        for a in self.annotations+self.original_annotations:
            if a.get('attachment')!=getattr(self,'attachment_id',None):continue
            page=a.get('page',0)
            if page not in self.document_canvas.layout:continue
            coords=self.document_canvas.coords(page,a['rect']);tags=('annotation',a['id']);color=a.get('color','#5aa5eb')
            point=a['kind'] in ('笔记','链接','关联文献','参考文献','书签') or a.get('original')
            if point:
                x,y=coords[:2];size=self.marker_size;self.canvas.create_oval(x-2,y-2,x+size,y+size,fill=color,outline='#ffffff',tags=tags)
                symbol='笔' if a['kind']=='笔记' else '↗' if a['kind'] in ('链接','参考文献','原文件链接') else '链' if a['kind']=='关联文献' else '评' if a.get('original') else '签'
                self.canvas.create_text(x+size/2-1,y+size/2-1,text=symbol,fill='white',font=(FONT,max(8,size//2),'bold'),tags=tags)
            else:
                self.canvas.create_rectangle(*coords,fill=color,stipple='gray25',outline=color,width=1,tags=tags)
                if a.get('text'):self.canvas.create_text(coords[2],coords[1],text='●',fill=color,anchor='ne',font=(FONT,self.marker_size),tags=tags)
        self.draw_text_markers()

    def draw_text_markers(self):
        if not self.text_view or not self.text_view.winfo_ismapped():return
        state=self.text_view.cget('state');modified=self.text_view.edit_modified();self.drawing_text_markers=True;self.text_view.configure(state='normal')
        for kind,value,index in reversed(self.text_view.dump('1.0','end-1c',window=True)):
            if kind=='window':self.text_view.delete(index,index+' +1c')
        for widget in self.text_marker_widgets:
            try:widget.destroy()
            except tk.TclError:pass
        self.text_marker_widgets=[]
        for name in self.text_view.tag_names():
            if name.startswith('document-marker-'):self.text_view.tag_delete(name)
        pending=[]
        for a in self.annotations+self.original_annotations:
            if a.get('attachment')!=self.attachment_id:continue
            index=self.text_view.index('1.0 +'+str(a['text_offset'])+'c') if 'text_offset' in a else a.get('text_index')
            if not index and a.get('quote'):
                index=self.text_view.search(a['quote'], '1.0',stopindex='end',exact=True)
            if not index:continue
            tag='document-marker-'+a['id'];self.text_view.tag_add(tag,index,index+' +1c');self.text_view.tag_configure(tag,background='#c3d9ed',foreground='#162c44',underline=True)
            self.text_view.tag_bind(tag,'<Double-1>',lambda e,item=a:self.activate_marker(item))
            pending.append((index,a))
        for index,a in sorted(pending,key=lambda p:tuple(map(int,p[0].split('.'))),reverse=True):
            marker=tk.Label(self.text_view,text='✎' if a['kind']=='笔记' else '↗' if a['kind'] in ('链接','参考文献') else '●',font=(FONT,self.marker_size),fg='#245faa',bg='#e5edf8',cursor='hand2')
            marker.bind('<Button-1>',lambda e,item=a:self.activate_marker(item));self.text_view.window_create(index,window=marker);self.text_marker_widgets.append(marker)
        self.text_view.configure(state=state);self.text_view.edit_modified(modified);self.drawing_text_markers=False

    def workflow_click_annotation(self,event):
        x=self.canvas.canvasx(event.x);y=self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x-3,y-3,x+3,y+3)):
            tags=self.canvas.gettags(item)
            if tags and tags[0]=='annotation':
                a=next((a for a in self.annotations+self.original_annotations if a['id']==tags[1]),None)
                if a:self.activate_marker(a);return True
        return False

    def activate_marker(self,a):
        if a.get('target'):
            if getattr(self,'on_open_related',None):self.on_open_related(a['target'])
            else:self.open(a['target'])
        elif a.get('url'):
            try:kind,url=valid_hyperlink(a['url'])
            except ValueError as exc:self.status.set(str(exc));return
            if kind=='url':
                import webbrowser
                webbrowser.open(url)
        elif a.get('reference'):self.lookup_reference(a['reference'])
        elif a['kind']=='笔记':
            self.show_notes();self.notebook.select(self.note_tab);index=a.get('note_index','end-1c');self.notes.mark_set('insert',index);self.notes.see(index);self.notes.focus_set()
        elif a.get('original'):
            messagebox.showinfo('原文件批注',(a.get('author','')+'\n'+a.get('quote','')+'\n\n'+a.get('text','')).strip(),parent=self.frame)
        else:self.annotation_editor(dict(a))

    def link_collected(self):
        if not self.rid:return
        dialog=tk.Toplevel(self.frame);style_dialog(dialog);dialog.title('关联已收集文献');dialog.geometry('800x510');dialog.transient(self.frame.winfo_toplevel())
        panel=ttk.Frame(dialog,padding=18);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='让两篇文献留下联系',font=(FONT,16,'bold')).pack(anchor='w')
        term=tk.StringVar();ttk.Entry(panel,textvariable=term).pack(fill='x',pady=12)
        tree=ttk.Treeview(panel,columns=('title','year'),show='headings',height=8);tree.heading('title',text='文献');tree.column('title',width=620);tree.heading('year',text='年份');tree.column('year',width=70);tree.pack(fill='both',expand=True)
        lib=Library(self.directory)
        try:records=[r for r in lib.records() if r['id']!=self.rid]
        finally:lib.close()
        def fill(*_):
            tree.delete(*tree.get_children())
            for r in records:
                if term.get().casefold() in (r['title']+' '+r['doi']).casefold():tree.insert('','end',iid=r['id'],values=(r['title'],r['year']))
        term.trace_add('write',fill);fill()
        def save():
            ids=tree.selection()
            if not ids:return
            target=ids[0];lib=Library(self.directory)
            try:lib.relate(self.rid,target);title=lib.get(target)['title']
            finally:lib.close()
            self.add_point_marker('关联文献',title,target=target);dialog.destroy();self.status.set('已关联；双击页内标记即可打开，图谱中也会显示。')
            if getattr(self,'on_library_changed',None):self.on_library_changed()
        ttk.Button(panel,text='关联并留下页内标记',style='Accent.TButton',command=save).pack(anchor='e',pady=12)

    def add_hyperlink(self):
        if not self.rid:return
        dialog=tk.Toplevel(self.frame);style_dialog(dialog);dialog.title('添加文献链接');dialog.transient(self.frame.winfo_toplevel())
        panel=ttk.Frame(dialog,padding=20);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='网址或本地文档').pack(anchor='w');url=tk.StringVar();ttk.Entry(panel,textvariable=url,width=70).pack(fill='x',pady=10)
        def pick():
            path=filedialog.askopenfilename(parent=dialog,filetypes=[('文档','*.pdf *.doc *.docx *.txt *.md')])
            if path:url.set(path)
        ttk.Button(panel,text='选择本地文档',command=pick).pack(anchor='w')
        ttk.Label(panel,text='显示名称（可选）').pack(anchor='w',pady=(14,4));label=tk.StringVar();ttk.Entry(panel,textvariable=label).pack(fill='x')
        def save():
            try:
                kind,value=valid_hyperlink(url.get());fields={}
                if kind=='file':
                    lib=Library(self.directory)
                    try:target=lib.import_document(value,lib.get(self.rid)['primary_project']);lib.relate(self.rid,target,'文档链接');fields={'target':target}
                    finally:lib.close()
                else:fields={'url':value}
                self.add_point_marker('链接',label.get().strip() or Path(value).name or value,**fields)
            except Exception as exc:messagebox.showerror('链接未添加',str(exc),parent=dialog);return
            dialog.destroy();self.status.set('已在右键位置留下链接标记；双击标记即可打开。')
            if getattr(self,'on_library_changed',None):self.on_library_changed()
        ttk.Button(panel,text='添加链接',style='Accent.TButton',command=save).pack(anchor='e',pady=(16,0))

    def dock_references(self):
        if self.reference_dock:
            if str(self.reference_dock) not in self.controls_host.panes():self.controls_host.add(self.reference_dock,weight=2)
            self.fill_docked_references();return
        dock=ttk.Frame(self.controls_host,padding=(12,4),width=360);self.reference_dock=dock
        row=ttk.Frame(dock);row.pack(fill='x');ttk.Label(row,text='参考文献',font=(FONT,11,'bold')).pack(side='left')
        ttk.Button(row,text='独立窗口',command=self.undock_references,width=8,style='Compact.TButton').pack(side='right')
        ttk.Button(row,text='刷新',command=self.reextract_references,width=5,style='Compact.TButton').pack(side='right',padx=4)
        ttk.Style(self.frame).configure('Reference.Treeview',rowheight=25,font=(FONT,9))
        self.docked_tree=ttk.Treeview(dock,columns=('number','title'),show='headings',height=3,style='Reference.Treeview')
        self.docked_tree.heading('number',text='标号');self.docked_tree.column('number',width=50,stretch=False);self.docked_tree.heading('title',text='文献 / 引用');self.docked_tree.column('title',width=290)
        self.docked_tree.pack(fill='both',expand=True,pady=5)
        self.docked_tree.bind('<Double-1>',lambda e:self.lookup_reference(self.docked_reference()))
        menu=tk.Menu(dock,tearoff=False)
        menu.add_command(label='查找原文 / 下载归档',command=lambda:self.lookup_reference(self.docked_reference()))
        menu.add_command(label='在阅读位置留下引用链接',command=lambda:self.mark_reference(self.docked_reference()))
        menu.add_command(label='移到独立窗口',command=self.undock_references)
        def popup(event):
            iid=self.docked_tree.identify_row(event.y)
            if iid:self.docked_tree.selection_set(iid)
            try:menu.tk_popup(event.x_root,event.y_root)
            finally:menu.grab_release()
        self.docked_tree.bind('<Button-3>',popup)
        ttk.Button(dock,text='查原文 / 下载归档',command=lambda:self.lookup_reference(self.docked_reference()),style='Compact.TButton').pack(fill='x')
        self.controls_host.add(dock,weight=2);self.fill_docked_references();self.frame.after_idle(lambda:self.controls_host.sashpos(0,max(650,self.controls_host.winfo_width()-380)))
        if getattr(self,'reference_window',None) and self.reference_window.winfo_exists():self.reference_window.withdraw()

    def fill_docked_references(self):
        if not self.reference_dock:return
        selected=self.docked_tree.selection();self.docked_tree.delete(*self.docked_tree.get_children())
        for i,ref in enumerate(self.references):self.docked_tree.insert('','end',iid=str(i),values=(ref.get('number') or f'{i+1}*',ref['title']))
        if selected and self.docked_tree.exists(selected[0]):self.docked_tree.selection_set(selected[0])

    def docked_reference(self):
        ids=self.docked_tree.selection();return self.references[int(ids[0])] if ids else None

    def undock_references(self):
        if self.reference_dock and str(self.reference_dock) in self.controls_host.panes():self.controls_host.forget(self.reference_dock)
        self.reference_panel()

    def mark_reference(self,ref):
        if ref:self.add_point_marker('参考文献',f"[{ref.get('number') or '?'}] {ref['title']}",reference=dict(ref));self.status.set('参考文献链接已留在阅读位置。')

    def lookup_reference(self,ref):
        if not ref:return
        from reference_lookup_ui import ReferenceLookup
        self.lookup_windows=[w for w in self.lookup_windows if not w.closed]
        self.lookup_windows.append(ReferenceLookup(self,ref))

    def reextract_references(self):
        if not self.rid:return
        self.references=[]
        if self.source_path and self.source_path.suffix.lower() in ('.txt','.md'):
            from references import parse_references
            self.references=parse_references(read_text_file(self.source_path));self.fill_docked_references()
            if getattr(self,'reference_window',None) and self.reference_window.winfo_exists():self.fill_references()
        else:self.open(self.rid,record_read=False)

    def show_text(self,text,editable=False):
        self.canvas.pack_forget();self.vertical_scroll.pack_forget();self.horizontal_scroll.pack_forget()
        if not self.text_view:
            self.text_panel=ttk.Frame(self.viewer);self.text_view=tk.Text(self.text_panel,wrap='word',undo=True,font=(FONT,13),padx=28,pady=24,bg='#f7f8fb',fg='#263343',insertbackground='#245faa',exportselection=False)
            scroll=ttk.Scrollbar(self.text_panel,command=self.text_view.yview);scroll.pack(side='right',fill='y');self.text_view.configure(yscrollcommand=scroll.set);self.text_view.pack(fill='both',expand=True)
            self.text_view.bind('<Button-3>',self.reading_context);self.text_view.bind('<<Modified>>',self.document_changed)
            self.text_view.bind('<Control-s>',lambda e:self.save_document());self.text_view.bind('<Control-S>',lambda e:self.save_document())
        self.text_panel.pack(fill='both',expand=True);self.text_view.configure(state='normal');self.text_view.delete('1.0','end');self.text_view.insert('1.0',text.replace('\r','\n').replace('\x07','␇'));self.text_view.edit_reset();self.text_view.edit_modified(False)
        self.text_view.configure(state='normal' if editable else 'disabled');self.editor_dirty=False;self.word_editing=editable
        self.page=0;self.count=1;self.page_label.set('原文编辑 · Ctrl+S 保存' if editable else 'TXT / Markdown · 连续阅读');self.draw_text_markers()

    def show_paged_view(self):
        if self.word_editing and self.editor_dirty:
            if not messagebox.askyesno('尚未保存','放弃本次原文修改并返回分页阅读？',parent=self.frame):return
        self.editor_dirty=False;self.word_editing=False
        if self.text_view:self.text_panel.pack_forget()
        self.vertical_scroll.pack(side='right',fill='y');self.horizontal_scroll.pack(side='bottom',fill='x');self.canvas.pack(fill='both',expand=True)
        if self.rid:self.open(self.rid,record_read=False)

    def document_changed(self,event=None):
        if self.drawing_text_markers:return
        if not self.text_view or not self.text_view.edit_modified():return
        self.text_view.edit_modified(False)
        if self.word_editing:self.editor_dirty=True;self.status.set('正在编辑归档副本 · Ctrl+S 保存；原导入文件会保留。')

    def edit_document(self):
        if not self.source_path or self.document_job:return
        suffix=self.source_path.suffix.lower()
        if suffix not in ('.doc','.docx','.txt','.md'):self.status.set('原文编辑支持 Word 与 TXT；PDF 可以选择文字、记笔记和批注。');return
        self.document_job=True;self.status.set('正在打开可编辑原文…');generation=self.generation;source=self.source_path
        def job():
            try:
                data={'text':read_text_file(source),'comments':[]} if suffix in ('.txt','.md') else word_content(source)
                data['sha']=digest(source);self.events.put(('editable-document',generation,data))
            except Exception as exc:self.events.put(('document-error',generation,str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def save_document(self):
        if not self.word_editing or not self.editor_dirty or self.document_job:return 'break'
        source=self.source_path;edited=self.text_view.get('1.0','end-1c');raw=self.editor_raw;sha=self.editor_sha;rid=self.rid;aid=self.attachment_id;generation=self.generation
        if source.suffix.lower() in ('.doc','.docx'):edited=edited.replace('␇','\x07')
        self.document_job=True;self.text_view.configure(state='disabled');self.status.set('正在保存原文，保存后保留上一版本…')
        def job():
            staged=self.directory/'staging'/('edited-'+uuid.uuid4().hex+source.suffix);staged.parent.mkdir(parents=True,exist_ok=True);lib=None
            try:
                if source.suffix.lower() in ('.txt','.md'):staged.write_text(edited,encoding='utf-8')
                else:edit_word_copy(source,raw,edited,staged)
                lib=Library(self.directory);lib.replace_document(rid,aid,staged,sha);self.events.put(('document-saved',generation,None))
            except Exception as exc:self.events.put(('document-error',generation,str(exc)))
            finally:
                if lib:lib.close()
                staged.unlink(missing_ok=True)
        threading.Thread(target=job,daemon=True).start();return 'break'

    def workflow_event(self,kind,value):
        if kind=='canvas-page':
            sign,page,data,error=value
            if sign!=self.document_canvas.sign:return True
            self.document_canvas.pending.discard(page)
            if error:self.status.set('页面未打开：'+error)
            else:self.document_canvas.receive(page,*data)
        elif kind=='original-comments':
            self.original_annotations=[dict(a,attachment=self.attachment_id) for a in value];self.refresh_annotations();self.draw_annotations()
        elif kind=='text-document':
            text,refs=value;self.loading=False;self.path=None;self.image_size=None;self.show_text(text);self.references=refs;self.fill_docked_references();self.status.set('本地文本阅读 · 选中文字后右键记录或添加链接')
            if getattr(self,'reference_window',None) and self.reference_window.winfo_exists():self.fill_references()
        elif kind=='editable-document':
            self.document_job=False;self.editor_raw=value['text'];self.editor_sha=value['sha'];self.show_text(value['text'],True);self.status.set('可以直接修改原文。保存会更新归档副本并保留上一版本。')
            if value.get('comments'):self.original_annotations=[dict(a,attachment=self.attachment_id) for a in value['comments']];self.refresh_annotations();self.draw_text_markers()
        elif kind=='document-saved':
            self.document_job=False;self.editor_dirty=False;self.word_editing=False
            if self.text_view:self.text_panel.pack_forget()
            self.vertical_scroll.pack(side='right',fill='y');self.horizontal_scroll.pack(side='bottom',fill='x');self.canvas.pack(fill='both',expand=True)
            self.open(self.rid,record_read=False);self.status.set('原文已保存，上一版本保存在文献库 versions 文件夹。')
        elif kind=='document-error':
            self.document_job=False
            if self.text_view and self.word_editing:self.text_view.configure(state='normal')
            self.status.set('原文操作未完成：'+value);messagebox.showerror('原文操作未完成',value,parent=self.frame)
        else:return False
        return True

    def workflow_export_notes(self,path):
        self.save_notes();text,images=self.note_snapshot();by_offset={a['offset']:a for a in images}
        source_name=self.source_path.name if self.source_path else self.title.get();parts=[];asset_files=[]
        for i,ch in enumerate(text):
            if ch!='\ufffc':parts.append(html.escape(ch) if path.suffix.lower()=='.html' else ch);continue
            item=by_offset.get(i)
            if not item:continue
            source=(self.directory/item['path']).resolve()
            if not source.is_relative_to(self.directory.resolve()) or not source.is_file():continue
            if path.suffix.lower()=='.html':parts.append('<img alt="阅读图片" style="max-width:100%" src="data:image/png;base64,'+base64.b64encode(source.read_bytes()).decode()+'">')
            else:
                assets=path.parent/(path.stem+'.assets');assets.mkdir(exist_ok=True);target=assets/source.name;shutil.copy2(source,target);asset_files.append(target)
                parts.append('![阅读图片]('+assets.name+'/'+source.name+')' if path.suffix.lower()=='.md' else '[阅读图片：'+assets.name+'/'+source.name+']')
        body=''.join(parts);annotation_lines=[]
        for a in sorted(self.annotations+self.original_annotations,key=lambda a:a.get('page',0)):
            annotation_lines.extend([f"### 第 {a.get('page',0)+1} 页 · {a['kind']}",a.get('quote',''),a.get('text',''),a.get('url',''),''])
        content='\n'.join(['# '+self.title.get(),'','用途：阅读笔记','对应文件：'+source_name,'文献标识：'+self.rid,'','## 阅读笔记','',body,'','## 高亮、批注与关联','',*annotation_lines])
        if path.suffix.lower()=='.html':
            content='<!doctype html><meta charset="utf-8"><title>'+html.escape(self.title.get())+' · 笔记</title><style>body{max-width:850px;margin:40px auto;padding:20px;font:16px/1.8 system-ui;color:#263343}pre{white-space:pre-wrap}img{display:block;margin:14px 0}</style><h1>'+html.escape(self.title.get())+'</h1><p>阅读笔记 · '+html.escape(source_name)+'</p><pre>'+body+'</pre><h2>高亮、批注与关联</h2><pre>'+html.escape('\n'.join(annotation_lines))+'</pre>'
        path.write_text(content,encoding='utf-8')
        lib=Library(self.directory)
        try:
            archived=lib._add_attachment(self.rid,path,'笔记 · '+time.strftime('%Y-%m-%d %H:%M'),role='note')
            for asset in asset_files:
                dest=archived.parent/asset.parent.name;dest.mkdir(exist_ok=True)
                if asset.resolve()!=(dest/asset.name).resolve():shutil.copy2(asset,dest/asset.name)
        finally:lib.close()
        self.note_status.set('已导出并关联为“笔记”附件，图谱中可以查看。')
