"""Asynchronous settings controls for GitHub release updates."""
import queue
import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from app_version import VERSION
from preferences import load_preferences,save_preferences
import app_updates


class UpdateController:
    def __init__(self,root,directory,config,notify=lambda text:None):
        self.root=root;self.directory=Path(directory);self.config=config;self.notify=notify
        self.events=queue.Queue();self.busy=False;self.release=None;self.pending=False;self.notes=''
        prefs=load_preferences(config)
        self.automatic=tk.BooleanVar(master=root,value=prefs.get('check_updates_on_start',False))
        self.preview=tk.BooleanVar(master=root,value=prefs.get('receive_preview_updates',False))
        self.status=tk.StringVar(master=root,value=f'当前版本 {VERSION}。点击检查 GitHub 新版本。')
        self.automatic.trace_add('write',self.save_options);self.preview.trace_add('write',self.save_options)
        self.view=None;self.root.after(200,self.poll)
        if self.automatic.get():self.root.after(5000,self.check)
        if prefs.get('last_seen_version')!=VERSION:
            self.notify(f'已更新到 {VERSION}：新增标签与子课题、Word 参考文献同步、解读模板和设置内更新。')
            try:save_preferences(config,{'last_seen_version':VERSION})
            except OSError:pass

    def save_options(self,*_):
        try:save_preferences(self.config,{'check_updates_on_start':self.automatic.get(),'receive_preview_updates':self.preview.get()})
        except OSError:self.status.set('更新偏好未保存，请检查程序目录是否可写。')

    def mount(self,parent):
        frame=ttk.LabelFrame(parent,text='软件更新',padding=12);frame.pack(fill='x',pady=12);self.view=frame
        ttk.Label(frame,textvariable=self.status,wraplength=760,style='Muted.TLabel').pack(fill='x')
        bar=ttk.Frame(frame);bar.pack(fill='x',pady=8)
        ttk.Button(bar,text='检查更新',command=self.check).pack(side='left')
        ttk.Button(bar,text='下载并在退出后更新',command=self.download).pack(side='left',padx=8)
        ttk.Checkbutton(bar,text='启动时检查更新',variable=self.automatic).pack(side='left',padx=8)
        ttk.Checkbutton(bar,text='接收预览版',variable=self.preview).pack(side='left')
        self.note_widget=tk.Text(frame,height=5,wrap='word',state='disabled');self.note_widget.pack(fill='x');self.render_notes()
        ttk.Label(frame,text='下载完成后，请从托盘正常退出主程序和选词助手。程序文件更新，文献库与设置保留；下次启动使用新版。',wraplength=760,style='Muted.TLabel').pack(fill='x',pady=(8,0))

    def render_notes(self):
        if self.view and self.view.winfo_exists():
            self.note_widget.configure(state='normal');self.note_widget.delete('1.0','end');self.note_widget.insert('1.0',self.notes or '发现新版后在此显示更新说明。');self.note_widget.configure(state='disabled')

    def run(self,work,kind):
        if self.busy:return
        self.busy=True
        def job():
            try:self.events.put((kind,work()))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def check(self):
        if self.busy or self.pending:return
        preview=self.preview.get();self.status.set('正在检查 GitHub 发布版本…')
        self.run(lambda:app_updates.check_update(VERSION,preview),'checked')

    def download(self):
        if self.busy or self.pending:return
        if not self.release:self.status.set('请先检查更新，发现新版后即可下载。');return
        self.status.set('正在后台下载新版…');release=dict(self.release)
        self.run(lambda:app_updates.download_update(self.directory,release,lambda done,total:self.events.put(('progress',(done,total)))),'downloaded')

    def poll(self):
        try:
            while True:
                kind,result=self.events.get_nowait()
                if kind=='progress':self.status.set(f'正在下载：{result[0]*100//result[1]}%');continue
                self.busy=False
                if kind=='error':self.status.set('更新未完成：'+result)
                elif kind=='checked':
                    self.release=result;self.notes=result['notes'] if result else '';self.render_notes()
                    text=f"发现新版本 {result['version']}，可下载并在退出后更新。" if result else f'当前 {VERSION} 已是此更新通道的最新版本。'
                    self.status.set(text)
                    if result:self.notify(text+' 请到设置查看更新说明。')
                elif kind=='downloaded':
                    try:app_updates.launch_installer(result);self.pending=True;self.status.set('已校验下载文件。正常退出主程序和选词助手后更新，下次启动生效。')
                    except (ValueError,OSError) as exc:self.status.set(str(exc))
        except queue.Empty:pass
        self.root.after(200,self.poll)
