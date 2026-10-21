"""Lifecycle of an owned WebView2 child inside the reader; no desktop automation."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tkinter as tk
from tkinter import ttk


class EmbeddedChat:
    def __init__(self,panel):
        self.panel=panel;self.reader=panel.reader;self.process=None;self.provider=None;self.events=queue.Queue()
        self.tab=ttk.Frame(self.reader.notebook);self.reader.notebook.add(self.tab,text='聊天网页')
        bar=ttk.Frame(self.tab);bar.pack(fill='x',pady=4)
        self.status=tk.StringVar(value='首次在此登录，登录信息保存在本机独立配置中。')
        ttk.Label(bar,textvariable=self.status,wraplength=360,style='Muted.TLabel').pack(fill='x')
        buttons=ttk.Frame(bar);buttons.pack(fill='x',pady=4)
        ttk.Button(buttons,text='在浏览器中打开',command=self.external).pack(side='left')
        ttk.Button(buttons,text='回答 / 笔记',command=lambda:self.reader.notebook.select(self.panel.frame)).pack(side='left',padx=5)
        ttk.Button(buttons,text='关闭内嵌聊天',command=self.close).pack(side='right')
        self.host=tk.Frame(self.tab,bg='#ffffff',width=380,height=600);self.host.pack(fill='both',expand=True)

    def open(self,url,provider):
        if os.name!='nt':raise ValueError('当前内嵌网页仅支持 Windows；Mac 可继续使用网页账号或 API 模式。')
        root=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
        executable=root/'embedded-browser/EmbeddedChat.exe'
        if not executable.is_file():raise ValueError('此安装包缺少内嵌网页组件，请更新完整 Windows 包。')
        self.reader.show_notes();self.reader.notebook.add(self.tab,text='聊天网页');self.reader.notebook.select(self.tab);self.host.update_idletasks()
        if self.process and self.process.poll() is not None:self.process=None
        if self.process is None:
            profile=self.reader.directory.parent/'runtime'/'embedded-chat'/'profile';profile.mkdir(parents=True,exist_ok=True)
            self.process=subprocess.Popen([str(executable),str(self.host.winfo_id()),str(profile),str(root/'browser-extension')],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
            self.provider=provider
            import threading
            process=self.process
            def receive():
                for line in process.stdout:
                    try:self.events.put(json.loads(line))
                    except ValueError:pass
            threading.Thread(target=receive,daemon=True,name='paperquick-embedded-chat').start()
        self.process.stdin.write(json.dumps({'type':'navigate','url':url})+'\n');self.process.stdin.flush()
        self.url=url
        self.rid=self.reader.rid
        self.status.set('正在加载聊天网页；请在此登录并核对问题后发送。')

    def poll(self):
        try:
            while True:self.status.set(self.events.get_nowait()['detail'])
        except queue.Empty:pass

    def external(self):
        if getattr(self,'url',None):
            import webbrowser
            webbrowser.open(self.reader.chat_bridge().open_url(self.url))

    def close(self):
        if self.process:
            try:self.process.stdin.write('{"type":"close"}\n');self.process.stdin.flush();self.process.stdin.close()
            except (OSError,ValueError):pass
            self.process=None;self.provider=None
