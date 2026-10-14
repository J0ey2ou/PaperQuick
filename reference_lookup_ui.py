"""Find and collect a reference while the main reading page stays open."""
from dataclasses import asdict
import queue
import threading
import tkinter as tk
from tkinter import ttk,messagebox
import webbrowser
from urllib.parse import quote
from library_core import Library
from paper_finder import find_papers,safe_link
from download_actions import resolve_download
from ui_theme import style_dialog,FONT

class ReferenceLookup:
    def __init__(self,reader,reference):
        self.reader=reader;self.reference=dict(reference);self.owner=reader.rid;self.events=queue.Queue();self.busy=False;self.closed=False
        self.win=tk.Toplevel(reader.frame);style_dialog(self.win);self.win.title('参考文献 · 原文与归档');self.win.geometry('880x620');self.win.minsize(700,500);self.win.transient(reader.frame.winfo_toplevel());self.win.protocol('WM_DELETE_WINDOW',self.close)
        panel=ttk.Frame(self.win,padding=20);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='顺着这条参考文献继续阅读',font=(FONT,17,'bold')).pack(anchor='w')
        ttk.Label(panel,text=reference.get('raw') or reference['title'],wraplength=800,style='Muted.TLabel').pack(fill='x',pady=10)
        self.status=tk.StringVar(value='正在查找原文入口…');ttk.Label(panel,textvariable=self.status,wraplength=800).pack(side='bottom',fill='x',pady=10)
        links=ttk.Frame(panel);links.pack(fill='x',pady=8)
        if reference.get('doi'):ttk.Button(links,text='先打开 DOI / 出版社',command=lambda:webbrowser.open('https://doi.org/'+quote(reference['doi'],safe='/'))).pack(side='left',padx=(0,8))
        ttk.Button(links,text='网页检索',command=lambda:webbrowser.open('https://scholar.google.com/scholar?q='+quote(reference.get('query') or reference['title']))).pack(side='left')
        self.cards=ttk.Frame(panel);self.cards.pack(fill='both',expand=True)
        def job():
            try:self.events.put(('results',find_papers(reference.get('query') or reference['title'])))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=job,daemon=True).start();self.win.after(100,self.poll)

    def show(self,result):
        for widget in self.cards.winfo_children():widget.destroy()
        self.status.set('请核对标题、作者和年份，再选择收藏与下载。')
        for paper in result.papers[:3]:
            card=ttk.LabelFrame(self.cards,text='候选文献',padding=12);card.pack(fill='x',pady=6)
            ttk.Label(card,text=paper.title,wraplength=770,font=(FONT,11,'bold')).pack(anchor='w')
            ttk.Label(card,text=f'{paper.year} · {paper.authors[:120]}',wraplength=770,style='Muted.TLabel').pack(anchor='w',pady=6)
            row=ttk.Frame(card);row.pack(fill='x')
            for link in paper.links[:3]:
                if safe_link(link.url):ttk.Button(row,text=link.label,command=lambda url=link.url:webbrowser.open(url)).pack(side='left',padx=(0,5))
            ttk.Button(row,text='收藏 / 下载归档',style='Accent.TButton',command=lambda p=paper:self.collect(p)).pack(side='right')
        if not result.papers:self.status.set('暂时没有找到唯一匹配。可以打开 DOI 或网页检索后核对。')

    def collect(self,paper):
        if self.busy:return
        dialog=tk.Toplevel(self.win);style_dialog(dialog);dialog.title('选择归档课题');dialog.transient(self.win)
        panel=ttk.Frame(dialog,padding=20);panel.pack(fill='both',expand=True)
        lib=Library(self.reader.directory)
        try:projects=lib.projects();owner=lib.get(self.owner);current=lib.project(owner['primary_project'])['name']
        finally:lib.close()
        ttk.Label(panel,text='选择已有课题，或填写新课题名称').pack(anchor='w')
        value=tk.StringVar(value=current);ttk.Combobox(panel,textvariable=value,values=[p['name'] for p in projects],width=40).pack(fill='x',pady=12)
        def accept():
            name=value.get().strip()
            if not name:return
            dialog.destroy();self.busy=True;self.status.set('正在收藏并下载开放全文…')
            def job():
                lib=Library(self.reader.directory)
                try:
                    pid=lib.create_project(name);rid=lib.save(asdict(paper),pid)
                    if rid!=self.owner:lib.relate(self.owner,rid,'参考文献')
                    result=resolve_download(lib,rid,lookup=False);self.events.put(('collected',result))
                except Exception as exc:self.events.put(('error',str(exc)))
                finally:lib.close()
            threading.Thread(target=job,daemon=True).start()
        ttk.Button(panel,text='收藏并下载',style='Accent.TButton',command=accept).pack(anchor='e')

    def poll(self):
        if self.closed:return
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='results':self.show(value)
                elif kind=='collected':
                    self.busy=False
                    if value['kind'] in ('existing','downloaded'):self.status.set('已收藏、关联到当前文献，并归档全文。')
                    elif value.get('url'):webbrowser.open(value['url']);self.status.set('已收藏并关联；原文页面已打开，下载后可导入或关联。')
                    else:self.status.set(value.get('issue') or '已收藏并关联，全文可以稍后补充。')
                else:self.busy=False;self.status.set('查找暂未完成：'+value)
        except queue.Empty:pass
        self.win.after(100,self.poll)
    def close(self):
        if self.busy:self.status.set('正在归档，完成后可以关闭。');return
        self.closed=True;self.win.destroy()
