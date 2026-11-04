"""Preview and export reading cards locally; no upload, clipboard or browser."""
from copy import deepcopy
from datetime import datetime
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog

from PIL import Image, ImageTk
from reading_share import THEMES, share_model, card_count, render_card, save_cards
from ui_theme import style_dialog


class ShareDialog:
    def __init__(self,parent,data):
        self.data=deepcopy(data);self.events=queue.Queue();self.generation=0;self.page=0;self.closed=False
        self.preview_image=None;self._pending=None;self._rendering=False;self._saving=False
        self._closed_event=threading.Event();self._result_lock=threading.Lock()
        self.win=tk.Toplevel(parent);self.win.title('分享阅读');self.win.geometry('850x820');self.win.minsize(580,560)
        style_dialog(self.win);self.win.protocol('WM_DELETE_WINDOW',self.close)
        self.win.bind('<Destroy>',self._destroyed,add='+')
        outer=ttk.Frame(self.win,padding=18);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='把阅读，分享成一张卡片',style='Section.TLabel').pack(anchor='w')
        ttk.Label(outer,text='先预览，再保存图片。所有内容在本机生成。',style='Muted.TLabel').pack(anchor='w',pady=(5,12))
        from ui_widgets import flow_bar
        options=ttk.Frame(outer);options.pack(fill='x')
        self.theme=tk.StringVar(value='书页花园');self.notes=tk.BooleanVar(value=False)
        self.abstract=tk.BooleanVar(value=True);self.time=tk.BooleanVar(value=True)
        for widget in (ttk.Combobox(options,textvariable=self.theme,values=list(THEMES),state='readonly',width=13),
                       ttk.Checkbutton(options,text='文献摘要',variable=self.abstract),
                       ttk.Checkbutton(options,text='阅读时长',variable=self.time),
                       ttk.Checkbutton(options,text='我的笔记与摘录',variable=self.notes)):
            widget.pack(side='left',padx=(0,10))
        flow_bar(options)
        self.caption=tk.StringVar(value='');caption_row=ttk.Frame(outer);caption_row.pack(fill='x',pady=(10,12))
        ttk.Label(caption_row,text='分享寄语').pack(side='left',padx=(0,10))
        ttk.Entry(caption_row,textvariable=self.caption).pack(side='left',fill='x',expand=True)
        self.canvas=tk.Canvas(outer,highlightthickness=0,bg='#e6e5e0');self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda _:self.show_preview())
        bar=ttk.Frame(outer);bar.pack(fill='x',pady=(12,0))
        self.previous=ttk.Button(bar,text='上一张',command=lambda:self.turn(-1));self.previous.pack(side='left')
        self.page_text=tk.StringVar(value='正在生成预览…');ttk.Label(bar,textvariable=self.page_text).pack(side='left',padx=12)
        self.next=ttk.Button(bar,text='下一张',command=lambda:self.turn(1));self.next.pack(side='left')
        self.save_button=ttk.Button(bar,text='保存分享图片',style='Accent.TButton',command=self.save);self.save_button.pack(side='right')
        self.status=tk.StringVar(value='笔记和摘录默认不分享；长内容显示节选，多篇回顾自动分页。')
        label=ttk.Label(outer,textvariable=self.status,style='Muted.TLabel',wraplength=760);label.pack(fill='x',pady=(10,0))
        outer.bind('<Configure>',lambda e:label.configure(wraplength=max(200,e.width-36)),add='+')
        for variable in (self.theme,self.notes,self.abstract,self.time,self.caption):variable.trace_add('write',self.schedule)
        self.job=None;self.poll_job=self.win.after(80,self.poll);self.schedule()

    def schedule(self,*_):
        if self.closed:return
        self.generation+=1
        if self.job:self.win.after_cancel(self.job)
        self.job=self.win.after(180,self.prepare)
        self.save_button.configure(state='disabled')

    def prepare(self):
        self.job=None
        model=share_model(self.data,self.notes.get(),self.abstract.get(),self.time.get(),self.caption.get())
        self.page=min(self.page,card_count(model)-1);self.model=model
        self._pending=(self.generation,model,self.theme.get(),self.page)
        self._start_preview()

    def _start_preview(self):
        if self.closed or self._rendering or self._pending is None:return
        generation,model,theme,page=self._pending;self._pending=None;self._rendering=True;events=self.events
        closed=self._closed_event;lock=self._result_lock
        def worker():
            try:
                result=render_card(model,theme,page)
                with lock:
                    if closed.is_set():result.close()
                    else:events.put(('preview',generation,result))
            except Exception as exc:events.put(('error',generation,str(exc)))
        threading.Thread(target=worker,daemon=True,name='PaperQuick-share-preview').start()

    def turn(self,delta):
        if hasattr(self,'model'):
            self.page=max(0,min(card_count(self.model)-1,self.page+delta));self.schedule()

    def show_preview(self):
        if self.closed or self.preview_image is None:return
        width=max(1,self.canvas.winfo_width()-24);height=max(1,self.canvas.winfo_height()-24)
        copy=self.preview_image.copy();copy.thumbnail((width,height),Image.Resampling.LANCZOS)
        self.photo=ImageTk.PhotoImage(copy,master=self.win);copy.close()
        self.canvas.delete('all');self.canvas.create_image(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,image=self.photo)

    def save(self):
        if self._saving or not hasattr(self,'model') or self._rendering or self.job:return
        path=filedialog.asksaveasfilename(parent=self.win,title='保存分享图片',defaultextension='.png',
             initialfile='PaperQuick-阅读分享-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.png',filetypes=[('PNG 图片','*.png')])
        if not path:return
        events=self.events;model=deepcopy(self.model);theme=self.theme.get();self._saving=True
        self.save_button.configure(state='disabled');self.status.set('正在保存图片…')
        def worker():
            try:events.put(('saved',0,save_cards(model,path,theme)))
            except Exception as exc:events.put(('save-error',0,str(exc)))
        # Normal application exit waits for a confirmed local export to finish.
        threading.Thread(target=worker,daemon=False,name='PaperQuick-share-export').start()

    def poll(self):
        if self.closed:return
        try:
            while True:
                kind,generation,value=self.events.get_nowait()
                if kind in ('preview','error'):
                    self._rendering=False
                    if generation==self.generation:
                        if kind=='preview':
                            if self.preview_image:self.preview_image.close()
                            self.preview_image=value;self.show_preview();count=card_count(self.model)
                            self.page_text.set(f'{self.page+1} / {count} 张')
                            self.previous.configure(state='normal' if self.page else 'disabled')
                            self.next.configure(state='normal' if self.page+1<count else 'disabled')
                            self.save_button.configure(state='disabled' if self._saving else 'normal')
                            self.status.set('已包含个人笔记与摘录，请核对后保存。' if self.notes.get() else '未包含个人笔记与摘录。长内容显示节选，所有文献均可翻页查看。')
                        else:self.status.set('图片生成未完成：'+value)
                    elif kind=='preview':value.close()
                    self._start_preview()
                elif kind in ('saved','save-error'):
                    self._saving=False;self.save_button.configure(state='normal' if not self._rendering and not self.job else 'disabled')
                    self.status.set(f'已保存 {len(value)} 张图片：{value[0].parent}' if kind=='saved' else '保存未完成：'+value)
        except queue.Empty:pass
        self.poll_job=self.win.after(80,self.poll)

    def _destroyed(self,event):
        if event.widget is self.win:self.close(destroy=False)

    def close(self,destroy=True):
        if self.closed:return
        self.closed=True;self._pending=None
        with self._result_lock:
            self._closed_event.set()
            while not self.events.empty():
                kind,_,value=self.events.get_nowait()
                if kind=='preview':value.close()
        for job in (self.job,self.poll_job):
            if job:
                try:self.win.after_cancel(job)
                except tk.TclError:pass
        if self.preview_image:self.preview_image.close()
        if destroy:self.win.destroy()
