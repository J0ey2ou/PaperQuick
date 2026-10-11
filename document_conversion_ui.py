"""Non-blocking document conversion dialog. Outputs always use a new filename."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from library_core import Library
from ui_theme import FONT, style_dialog

class ConversionWindow:
    def __init__(self,parent,directory,rid=None,source=None,on_done=None):
        self.directory=Path(directory);self.rid=rid;self.on_done=on_done;self.busy=False;self.closed=False;self.events=queue.Queue();self.result=None
        self.win=tk.Toplevel(parent);self.win.title('Word / PDF 转换');self.win.geometry('720x540');self.win.minsize(640,520);style_dialog(self.win);self.win.transient(parent.winfo_toplevel());self.win.protocol('WM_DELETE_WINDOW',self.close)
        owner=parent.winfo_toplevel();owner.update_idletasks()
        x=max(0,owner.winfo_rootx()+(owner.winfo_width()-720)//2);y=max(0,owner.winfo_rooty()+(owner.winfo_height()-540)//2)
        self.win.geometry(f'720x540+{x}+{y}')
        panel=ttk.Frame(self.win,padding=24);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='在阅读与写作之间轻松转换',font=(FONT,17,'bold')).pack(anchor='w')
        ttk.Label(panel,text='按你的使用方式，选择适合的文档格式。',style='Muted.TLabel').pack(anchor='w',pady=(8,18))
        self.source=tk.StringVar(value=str(source or ''));row=ttk.Frame(panel);row.pack(fill='x');ttk.Entry(row,textvariable=self.source,state='readonly').pack(side='left',fill='x',expand=True);ttk.Button(row,text='选择文件',command=self.choose).pack(side='right',padx=(8,0))
        self.direction=tk.StringVar();ttk.Label(panel,textvariable=self.direction,font=(FONT,13,'bold')).pack(anchor='w',pady=(20,10))
        self.mode=tk.StringVar(value='text');self.mode_frame=ttk.Frame(panel)
        for label,value in [('可编辑文字','text'),('保留页面外观','appearance')]:ttk.Radiobutton(self.mode_frame,text=label,variable=self.mode,value=value,command=self.refresh).pack(side='left',padx=(0,22))
        self.notice=tk.StringVar();self.notice_label=ttk.Label(panel,textvariable=self.notice,style='Muted.TLabel',wraplength=580);self.notice_label.pack(fill='x')
        self.associate=tk.BooleanVar(value=bool(rid));ttk.Checkbutton(panel,text='转换后，将新文件作为附件收纳到当前文献',variable=self.associate,state='normal' if rid else 'disabled').pack(anchor='w',pady=(20,12))
        self.progress=ttk.Progressbar(panel,mode='indeterminate');self.progress.pack(fill='x',pady=6)
        self.status=tk.StringVar(value='请选择新文件名保存，原文件会保留。');ttk.Label(panel,textvariable=self.status,style='Muted.TLabel',wraplength=580).pack(fill='x',pady=8)
        controls=ttk.Frame(panel);controls.pack(side='bottom',fill='x',pady=(12,0));self.start_button=ttk.Button(controls,text='转换并另存为',style='Accent.TButton',command=self.start);self.start_button.pack(side='right')
        ttk.Button(controls,text='完成',command=self.close).pack(side='right',padx=8)
        self.refresh();self.win.after(100,self.poll)

    def refresh(self):
        suffix=Path(self.source.get()).suffix.lower();self.direction.set('PDF → Word（.docx）' if suffix=='.pdf' else 'Word → PDF' if suffix in ('.doc','.docx') else '选择 PDF 或 Word 文件')
        if suffix=='.pdf':
            self.mode_frame.pack(fill='x',pady=(0,14),before=self.notice_label)
            self.notice.set('本机处理，无需安装 Word。\n'+('提取可编辑正文并保留分页；表格、公式和复杂布局不会还原，扫描页保留为图片。' if self.mode.get()=='text' else '每页完整保留为图片，适合对照原文和打印；页面内文字不能直接编辑。'))
        else:
            self.mode_frame.pack_forget()
            self.notice.set('需要本机安装桌面版 Microsoft Word。转换在本机完成；使用本机字体，缺失字体可能影响排版。' if suffix in ('.doc','.docx') else '选择 PDF 时可转换为 Word；选择 Word 时可生成 PDF。所有文件均在本机处理。')

    def choose(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self.win,title='选择需要转换的文件',filetypes=[('PDF / Word','*.pdf *.doc *.docx')])
        if path:self.source.set(path);self.refresh()

    def start(self):
        if self.busy:return
        source=Path(self.source.get())
        if not source.is_file() or source.suffix.lower() not in ('.pdf','.doc','.docx'):self.status.set('请选择一个可用的 PDF 或 Word 文件。');return
        suffix='.docx' if source.suffix.lower()=='.pdf' else '.pdf'
        target=filedialog.asksaveasfilename(parent=self.win,title='转换并另存为',initialdir=str(source.parent),initialfile=source.stem+'-转换'+suffix,defaultextension=suffix,filetypes=[('Word 文档' if suffix=='.docx' else 'PDF', '*'+suffix)])
        if not target:return
        if Path(target).exists():self.status.set('这个文件名已经存在。请使用新名称，避免覆盖已有文件。');return
        associate=bool(self.rid and self.associate.get());mode=self.mode.get();self.busy=True;self.start_button.configure(state='disabled');self.progress.start(12)
        self.status.set(('正在提取正文并生成 Word…' if mode=='text' else '正在逐页保留外观并生成 Word…') if source.suffix.lower()=='.pdf' else '正在通过本机 Word 生成 PDF…')
        def work():
            try:
                from document_conversion import convert_document
                result=convert_document(source,target,mode=mode) if source.suffix.lower()=='.pdf' else convert_document(source,target)
                attachment=None;warning=''
                if associate:
                    lib=None
                    try:
                        lib=Library(self.directory);stored=lib.add_attachment(self.rid,result,label=result.name)
                        attachment=next((a for a in lib.get(self.rid)['attachments'] if a.get('path') and (self.directory/a['path']).resolve()==Path(stored).resolve()),None)
                    except Exception as exc:warning='文件已转换成功，但暂未关联到文献：'+str(exc)
                    finally:
                        if lib:lib.close()
                self.events.put(('done',(result,attachment,warning)))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        if self.closed:return
        try:
            while True:
                kind,value=self.events.get_nowait();self.busy=False;self.start_button.configure(state='normal');self.progress.stop()
                if kind=='error':self.status.set('转换未完成：'+value)
                else:
                    result,attachment,warning=value;self.result=result;self.status.set(warning or ('已保存：'+str(result)+('。新文件已关联到当前文献。' if attachment else '')))
                    if self.on_done:
                        try:self.on_done(result,attachment)
                        except Exception as exc:self.status.set('新文件已保存：'+str(result)+'。暂未能打开预览：'+str(exc))
        except queue.Empty:pass
        self.win.after(100,self.poll)

    def close(self):
        if self.busy:self.status.set('转换正在进行，完成后即可关闭。');return False
        self.closed=True;self.win.destroy();return True
