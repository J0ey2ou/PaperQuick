"""Lifecycle of an owned WebView2 child inside the reader; no desktop automation."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
from app_version import VERSION


class EmbeddedChat:
    def __init__(self,panel):
        self.panel=panel;self.reader=panel.reader;self.process=None;self.provider=None;self.events=queue.Queue()
        self.tab=ttk.Frame(self.reader.notebook);self.reader.notebook.add(self.tab,text='聊天网页')
        bar=ttk.Frame(self.tab);bar.pack(fill='x',pady=4)
        self.status=tk.StringVar(value='首次在此登录，登录信息保存在本机独立配置中。')
        self.status_label=ttk.Label(bar,textvariable=self.status,wraplength=360,style='Muted.TLabel')
        self.status_label.pack(fill='x')
        bar.bind('<Configure>',lambda event:self.status_label.configure(wraplength=max(180,event.width-8)),add='+')
        buttons=ttk.Frame(bar);buttons.pack(fill='x',pady=4)
        style=ttk.Style(self.tab);style.configure('Chat.TButton',padding=(6,3),width=0);style.configure('Chat.TMenubutton',padding=(6,3),width=0)
        for column,(label,command) in enumerate((('重试准备',lambda:self.action('retry')),('绑定对话',lambda:self.action('bind')),('回存选中',lambda:self.action('reply')),('笔记',lambda:self.reader.notebook.select(self.panel.frame)))):
            ttk.Button(buttons,text=label,style='Chat.TButton',command=command).grid(row=0,column=column,padx=(0,3),sticky='ew')
        more=ttk.Menubutton(buttons,text='更多',style='Chat.TMenubutton');more.grid(row=0,column=4,sticky='e')
        menu=tk.Menu(more,tearoff=False);more.configure(menu=menu)
        for label,command in (('在浏览器中打开',self.external),('重新显示',self.reveal),('关闭内嵌聊天',self.close)):menu.add_command(label=label,command=command)
        buttons.columnconfigure(4,weight=1)
        self.host=tk.Frame(self.tab,bg='#ffffff',width=380,height=600);self.host.pack(fill='both',expand=True)
        self.host.bind('<Map>',lambda event:self._sync_display(),add='+')

    def open(self,url,provider):
        if os.name!='nt':raise ValueError('当前内嵌网页仅支持 Windows；Mac 可继续使用网页账号或 API 模式。')
        root=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
        executable=root/'embedded-browser/EmbeddedChat.exe'
        if not executable.is_file():raise ValueError('此安装包缺少内嵌网页组件，请更新完整 Windows 包。')
        self.reader.show_notes();self.reader.notebook.add(self.tab,text='聊天网页');self.reader.notebook.select(self.tab);self.host.update_idletasks()
        if self.process and self.process.poll() is not None:self.process=None
        if self.process is None:
            while not self.events.empty():self.events.get_nowait()
            profile=self.reader.directory.parent/'runtime'/'embedded-chat'/'profile';profile.mkdir(parents=True,exist_ok=True)
            self.diagnostic_path=profile.parent/'display-diagnostics.jsonl'
            self.process=subprocess.Popen([str(executable),str(self.host.winfo_id()),str(profile),str(root/'browser-extension')],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
            self.provider=provider
            import threading
            process=self.process
            def receive():
                for line in process.stdout:
                    try:
                        event=json.loads(line)
                        if self.process is process:self.events.put(event)
                    except ValueError:pass
            threading.Thread(target=receive,daemon=True,name='paperquick-embedded-chat').start()
        self.process.stdin.write(json.dumps({'type':'navigate','url':url})+'\n');self.process.stdin.flush()
        self.pending_url=url
        self.rid=self.reader.rid
        self.status.set('正在加载聊天网页；请在此登录并核对问题后发送。')

    def poll(self):
        try:
            while True:
                event=self.events.get_nowait()
                if event.get('state')=='opened' and event.get('url'):self.url=event['url']
                if event.get('detail'):self.status.set(event['detail'])
                if event.get('state')=='display-state' and getattr(self,'diagnostic_path',None):
                    # Never record conversation URLs/tokens, prompts, replies or files.
                    safe={key:event[key] for key in ('state','attached','controllerReady','controllerVisible','width','height','renderMode','hostKind') if key in event}
                    safe['version']=VERSION
                    try:
                        if self.diagnostic_path.exists() and self.diagnostic_path.stat().st_size>65536:
                            self.diagnostic_path.replace(self.diagnostic_path.with_suffix('.previous.jsonl'))
                        with self.diagnostic_path.open('a',encoding='utf-8') as log:log.write(json.dumps(safe)+'\n')
                    except OSError:pass
        except queue.Empty:pass
        if self.process and self.process.poll() is not None:
            self.status.set('内嵌聊天组件已退出，请关闭后重新打开；也可使用浏览器或 API。')
            self.process=None

    def _sync_display(self):
        if self.process and self.process.poll() is None:
            try:self.process.stdin.write('{"type":"sync-host"}\n');self.process.stdin.flush();return True
            except (OSError,ValueError):pass
        return False

    def action(self,action):
        if action not in ('retry','bind','reply'):return
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(json.dumps({'type':'adapter-action','action':action})+'\n');self.process.stdin.flush()
                self.status.set({'retry':'正在重新准备问题和文献…','bind':'正在确认已发送的文献对话…','reply':'正在回存网页选中的回答…'}[action]);return
            except (OSError,ValueError):pass
        self.status.set('聊天组件未运行，请在 AI 阅读重新打开。')

    def reveal(self):
        """Reattach our owned child without navigating away from an unsent draft."""
        if self._sync_display():
            self.status.set('正在确认聊天显示通道，当前网页和草稿保持不变…')
        else:self.status.set('聊天组件已退出，请回到 AI 阅读重新打开。')

    def external(self):
        url=getattr(self,'url',None) or getattr(self,'pending_url',None)
        if url:
            import webbrowser
            webbrowser.open(self.reader.chat_bridge().open_url(url))

    def close(self):
        if self.process:
            try:self.process.stdin.write('{"type":"close"}\n');self.process.stdin.flush();self.process.stdin.close()
            except (OSError,ValueError):pass
            self.process=None;self.provider=None
        try:
            self.reader.notebook.select(self.panel.frame);self.reader.notebook.hide(self.tab)
        except tk.TclError:pass
