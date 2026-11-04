"""Directory, page labels and opt-in online translation for the reader."""
import json
import queue
import re
import threading
from collections import OrderedDict
from copy import deepcopy
from pdf_reader_core import file_version, DocumentReadCancelled
from urllib.parse import urlencode
from urllib.request import urlopen
import tkinter as tk
from tkinter import ttk, simpledialog
from library_core import Library


def text_headings(text):
    result=[]; offset=0
    for line in text.splitlines(keepends=True):
        title=line.strip()
        if len(title)<=120 and (re.match(r'^(?:第[一二三四五六七八九十百\d]+[章节篇]|\d+(?:\.\d+){0,3}[.、\s]+)\s*\S', title) or re.match(r'^(?:abstract|introduction|methods|results|discussion|conclusion|references|contents|摘要|引言|结论|参考文献|目录)$', title, re.I)):
            result.append({'title':title,'offset':offset,'level':0})
        offset+=len(line)
    return result[:1000]


_outline_cache=OrderedDict()
_outline_lock=threading.RLock()


def clear_outline_cache():
    with _outline_lock:_outline_cache.clear()


def _check_cancelled(cancelled):
    if cancelled and cancelled():raise DocumentReadCancelled()


def pdf_outline(path, cancelled=None):
    # File-like fixtures remain supported; real files reuse outlines, including
    # empty results, until the file version changes. Never share mutable items.
    _check_cancelled(cancelled);version=file_version(path)
    if version is not None:
        with _outline_lock:
            if version in _outline_cache:
                _outline_cache.move_to_end(version)
                return deepcopy(_outline_cache[version])
    result=_read_pdf_outline(path,cancelled)
    _check_cancelled(cancelled)
    if version is not None:
        if file_version(path)!=version:
            raise ValueError('文档在读取时已改变，请重新打开。')
        with _outline_lock:
            _outline_cache[version]=deepcopy(result)
            while len(_outline_cache)>32:_outline_cache.popitem(last=False)
    return result


def _read_pdf_outline(path, cancelled=None):
    from pypdf import PdfReader
    reader=PdfReader(path); result=[]
    def walk(items, level=0):
        for item in items:
            _check_cancelled(cancelled)
            if isinstance(item,list):walk(item,level+1);continue
            try:
                page=reader.get_destination_page_number(item)
                if page is not None and page>=0:result.append({'title':str(item.title),'page':page,'level':level})
            except (AttributeError,ValueError,KeyError,TypeError):continue
    try:walk(reader.outline)
    except DocumentReadCancelled:raise
    except Exception:pass
    if result:return result
    for page_no,page in enumerate(reader.pages):
        _check_cancelled(cancelled)
        try:headings=text_headings(page.extract_text() or '')
        except Exception:continue
        for item in headings:result.append({'title':item['title'],'page':page_no,'level':0})
    return result[:1000]


def translate(text, source, target):
    text=text.strip()
    if not text:raise ValueError('请先选择文字。')
    if len(text.encode('utf-8'))>500:raise ValueError('选文超过 500 字节，请选择较短的段落。')
    url='https://api.mymemory.translated.net/get?'+urlencode({'q':text,'langpair':source+'|'+target})
    with urlopen(url,timeout=20) as response:data=json.load(response)
    if data.get('responseStatus')!=200:raise ValueError(data.get('responseDetails') or '翻译服务暂时不可用。')
    result=data.get('responseData',{}).get('translatedText','').strip()
    if not result:raise ValueError('翻译服务没有返回结果。')
    return result


class ReaderNavigation:
    def __init__(self, reader):
        self.r=reader;self.outline=[];self.labels=[];self.events=queue.Queue();self.serial=0
        tab=ttk.Frame(reader.notebook,padding=6);reader.notebook.add(tab,text='目录 / 标签');self.tab=tab
        self.hint=tk.StringVar(value='打开文档后自动识别目录。')
        ttk.Label(tab,textvariable=self.hint,wraplength=280).pack(fill='x')
        self.tree=ttk.Treeview(tab,show='tree',height=9);self.tree.pack(fill='both',expand=True,pady=4);self.tree.bind('<Double-1>',self.goto_outline);self.tree.bind('<Return>',self.goto_outline)
        from ui_widgets import flow_bar
        row=ttk.Frame(tab);row.pack(fill='x');flow_bar(row);ttk.Label(row,text='自定义页面标签').pack(side='left');ttk.Button(row,text='添加当前位置',command=self.add_label).pack(side='right')
        self.list=ttk.Treeview(tab,columns=('location',),show='tree headings',height=6);self.list.heading('#0',text='标签');self.list.heading('location',text='位置');self.list.column('#0',width=130);self.list.column('location',width=75);self.list.pack(fill='both',expand=True,pady=4);self.list.bind('<Double-1>',self.goto_label);self.list.bind('<Return>',self.goto_label)
        row=ttk.Frame(tab);row.pack(fill='x');flow_bar(row);ttk.Button(row,text='跳转',command=self.goto_label).pack(side='left');ttk.Button(row,text='重命名',command=self.rename_label).pack(side='left',padx=4);ttk.Button(row,text='删除',command=self.delete_label).pack(side='left')
        self.frame=ttk.Frame(reader.notebook,padding=6);reader.notebook.add(self.frame,text='翻译')
        ttk.Label(self.frame,text='选文翻译 · MyMemory 免费服务',wraplength=280).pack(anchor='w')
        ttk.Label(self.frame,text='选文将发送至第三方；请勿发送敏感内容。匿名免费额度有限。',wraplength=280).pack(fill='x',pady=5)
        row=ttk.Frame(self.frame);row.pack(fill='x');flow_bar(row);self.pair=tk.StringVar(value='英语 → 中文');ttk.Combobox(row,textvariable=self.pair,values=['英语 → 中文','中文 → 英语','日语 → 中文','法语 → 中文','德语 → 中文'],state='readonly',width=16).pack(side='left');ttk.Button(row,text='翻译',command=self.send).pack(side='right')
        ttk.Label(self.frame,text='原文（可编辑）').pack(anchor='w');self.source=tk.Text(self.frame,height=5,wrap='word',exportselection=False);self.source.pack(fill='x')
        ttk.Label(self.frame,text='译文').pack(anchor='w',pady=(8,0));self.answer=tk.Text(self.frame,height=9,wrap='word',exportselection=False);self.answer.pack(fill='both',expand=True)
        self.status=tk.StringVar(value='在文中选中文字，右键选择“翻译选中文字”。');ttk.Label(self.frame,textvariable=self.status,wraplength=280).pack(fill='x',pady=5)
        self.frame.after(150,self.poll)
    def key(self):return 'reader-page-labels:'+self.r.rid+':'+self.r.attachment_id
    def open(self):
        self.serial+=1;self.outline=[];self.fill_outline();self.source.delete('1.0','end');self.answer.delete('1.0','end');self.status.set('在文中选中文字，右键选择“翻译选中文字”。')
        lib=Library(self.r.directory)
        try:self.labels=lib.setting(self.key(),[])
        finally:lib.close()
        self.fill_labels()
    def fill_outline(self):
        self.tree.delete(*self.tree.get_children());parents=[]
        for i,item in enumerate(self.outline):
            level=min(item.get('level',0),len(parents));parents=parents[:level];parent=parents[-1] if parents else ''
            suffix=f"  ·  {item['page']+1} 页" if 'page' in item else ''
            node=self.tree.insert(parent,'end',iid=str(i),text=item['title']+suffix,open=True);parents.append(node)
        self.hint.set(('双击跳转 · 自动识别结果请核对' if self.outline else '未识别到目录或章节标题。'))
    def goto_outline(self,event=None):
        selected=self.tree.selection()
        if selected:self.go(self.outline[int(selected[0])])
    def go(self,item):
        r=self.r
        if 'offset' in item and r.text_view and r.text_view.winfo_ismapped():r.text_view.see('1.0 + %d chars'%item['offset']);return
        if r.path and not r.loading:
            r._reading_target={'page':item.get('page',0),'fraction':item.get('fraction',0)};r.apply_reading_target()
    def fill_labels(self):
        self.list.delete(*self.list.get_children())
        for i,item in enumerate(self.labels):self.list.insert('','end',iid=str(i),text=item['name'],values=('文本位置' if 'offset' in item else '第 %d 页'%(item['page']+1),))
    def save(self):
        lib=Library(self.r.directory)
        try:lib.set_setting(self.key(),self.labels)
        finally:lib.close()
        self.fill_labels()
    def add_label(self):
        r=self.r
        if not r.rid or r.loading:return
        name=simpledialog.askstring('新建标签','标签名称：',parent=r.frame)
        if not name or not name.strip():return
        item={'name':name.strip()}
        if r.text_view and r.text_view.winfo_ismapped():item['offset']=int(r.text_view.count('1.0','@0,0','chars')[0] or 0)
        else:item['page']=r.page
        self.labels.append(item);self.save()
    def index(self):
        selected=self.list.selection();return int(selected[0]) if selected else None
    def goto_label(self,event=None):
        i=self.index()
        if i is not None:self.go(self.labels[i])
    def rename_label(self):
        i=self.index()
        if i is None:return
        name=simpledialog.askstring('重命名标签','标签名称：',initialvalue=self.labels[i]['name'],parent=self.r.frame)
        if name and name.strip():self.labels[i]['name']=name.strip();self.save()
    def delete_label(self):
        i=self.index()
        if i is not None:self.labels.pop(i);self.save()
    def select_translation(self):
        r=self.r
        if r.text_view and r.text_view.winfo_ismapped():
            try:quote=r.text_view.get('sel.first','sel.last')
            except tk.TclError:quote=''
        else:
            item=r.current_selection();quote=item.get('quote','') if item else ''
        if not quote.strip():r.status.set('请先选中文字，再选择翻译。');return
        self.source.delete('1.0','end');self.source.insert('1.0',quote);self.answer.delete('1.0','end');self.status.set('确认语言后点击翻译，选文将发送给 MyMemory。');r.show_notes();r.notebook.select(self.frame)
    def send(self):
        text=self.source.get('1.0','end-1c');pairs={'英语 → 中文':('en','zh-CN'),'中文 → 英语':('zh-CN','en'),'日语 → 中文':('ja','zh-CN'),'法语 → 中文':('fr','zh-CN'),'德语 → 中文':('de','zh-CN')};source,target=pairs[self.pair.get()];serial=self.serial;events=self.events
        self.serial+=1;serial=self.serial
        self.status.set('正在翻译…')
        def job():
            try:events.put((serial,True,translate(text,source,target)))
            except Exception as exc:events.put((serial,False,str(exc)))
        threading.Thread(target=job,daemon=True).start()
    def poll(self):
        if self.r.closed:return
        try:
            while True:
                serial,ok,value=self.events.get_nowait()
                if serial!=self.serial:continue
                if ok:self.answer.delete('1.0','end');self.answer.insert('1.0',value);self.status.set('翻译完成；请核对专业术语。')
                else:self.status.set('翻译未完成：'+value)
        except queue.Empty:pass
        self.frame.after(150,self.poll)
