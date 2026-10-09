"""文献直达 Windows 桌面界面。"""
import ctypes
import json
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import webbrowser
import urllib.parse

from paper_finder import find_papers, LookupError, BrowserPageRequired, safe_link, automatic_target
from shortcuts import load_shortcut, parse_shortcut, save_shortcut
from ui_theme import BG, FG, MUTED, ACCENT as BLUE, PANEL, INPUT, LINE, FONT, install_theme, emblem, opening_animation, window_icon, style_dialog



def app_dir():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


class App:
    def __init__(self, root):
        self.root = root
        root.title("文献直达")
        root.geometry("1320x920")
        root.minsize(1120, 800)
        root.configure(bg=BG)
        root.option_add("*Font", (FONT, 10))
        self.events = queue.Queue()
        self.result = None
        self.busy = False
        self.started_at = time.monotonic()
        self.auto_open = False
        self.email = ""
        self.preferences={}
        self.config_path = app_dir() / "settings.json"
        try:
            self.preferences=json.loads(self.config_path.read_text("utf-8"));self.email = self.preferences.get("email", "")
        except (OSError, ValueError, AttributeError):
            self.preferences={}
        install_theme(root)
        window_icon(root)
        self.library_window = None
        self.library_directory=app_dir()/'本地文献库'
        self.graph_page = None
        self.reader_page = None
        self.summary_view=None;self.summary_dialog=None;self.settings_page=None
        from reading_stats import ReadingClock
        self.reading_clock=ReadingClock(lambda:self.library_directory)
        self.current_page = 'query'
        navigation=tk.Frame(root,bg=BG)
        navigation.pack(fill='x',padx=26,pady=(18,8))
        emblem(navigation,52).pack(side='left',padx=(0,10))
        tk.Label(navigation,text='文献直达',bg=BG,fg=FG,font=(FONT,17,'bold')).pack(side='left')
        tabs=tk.Frame(navigation,bg=BG);tabs.pack(side='left',padx=24)
        self.nav_buttons={}
        for key,title in [('query','文献查询'),('library','文献分类'),('graph','文献图谱'),('reader','文献阅读')]:
            button=ttk.Button(tabs,text=title,style='ActiveNav.TButton' if key=='query' else 'Nav.TButton',command=lambda k=key:self.show_page(k))
            button.pack(side='left',padx=3);self.nav_buttons[key]=button
        ttk.Button(navigation,text='设置',command=self.settings).pack(side='right')
        ttk.Button(navigation,text='阅读总结',command=self.show_summary).pack(side='right',padx=8)
        self.page_host=tk.Frame(root,bg=BG);self.page_host.pack(fill='both',expand=True)
        page=tk.Frame(self.page_host,bg=BG);page.pack(fill='both',expand=True)
        self.query_page=page

        header = tk.Frame(page, bg=BG)
        header.pack(fill="x", padx=28, pady=(22, 12))
        tk.Label(header, text="文献查询", bg=BG, fg=FG, font=(FONT, 21, "bold")).pack(side="left")
        tk.Label(header, text="查找原文 · 本地整理", bg=BG, fg=MUTED).pack(side="left", padx=12, pady=(9, 0))
        ttk.Button(header, text="右键工具", command=self.extension_help).pack(side="right", padx=8)
        ttk.Button(header, text="全局快捷键", command=self.start_selection_helper).pack(side="right")

        tk.Label(page,text="PAPERQUICK  /  RESEARCH WORKSPACE",bg=BG,fg=BLUE,font=('Segoe UI',9,'bold'),anchor='w').pack(fill='x',padx=28,pady=(0,12))
        box = tk.Frame(page, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        box.pack(fill="x", padx=28)
        tk.Label(box, text="粘贴论文标题、DOI、arXiv 链接或推送链接", bg=PANEL, fg=FG, anchor="w", font=(FONT, 11, "bold")).pack(fill="x", padx=18, pady=(15, 8))
        self.input = tk.Text(box, height=3, wrap="word", bg=INPUT, fg=FG, relief="flat", padx=12, pady=9, insertbackground=BLUE, font=(FONT, 11), undo=True)
        self.input.pack(fill="x", padx=18)
        self.input.bind("<Control-Return>", lambda event: self.search())
        bar = tk.Frame(box, bg=PANEL)
        bar.pack(fill="x", padx=18, pady=13)
        self.paste_button = ttk.Button(bar, text="粘贴并查找", command=self.paste_search)
        self.paste_button.pack(side="left")
        ttk.Button(bar, text="清空", command=lambda: self.input.delete("1.0", "end")).pack(side="left", padx=8)
        ttk.Button(bar, text="直接学术搜索 ↗", command=self.scholar_search).pack(side="left", padx=6)
        self.search_button = ttk.Button(bar, text="查找原文", style="Accent.TButton", command=self.search)
        self.search_button.pack(side="right")

        statusbar = tk.Frame(page, bg=BG)
        statusbar.pack(fill="x", padx=28, pady=(13, 6))
        self.status = tk.StringVar(value="准备就绪 · 需要联网检索")
        tk.Label(statusbar, textvariable=self.status, bg=BG, fg=MUTED, anchor="w").pack(side="left", fill="x", expand=True)
        self.copy_button = ttk.Button(statusbar, text="复制全部链接", command=self.copy_all, state="disabled")
        self.copy_button.pack(side="right")
        self.progress = ttk.Progressbar(page, mode="determinate")
        self.progress.pack(fill="x", padx=28, pady=(0, 9))

        result_frame = tk.Frame(page, bg=BG)
        result_frame.pack(fill="both", expand=True, padx=28)
        self.canvas = tk.Canvas(result_frame, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.cards = tk.Frame(self.canvas, bg=BG)
        self.cards_id = self.canvas.create_window((0, 0), window=self.cards, anchor="nw")
        self.cards.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize_cards)
        root.bind_all("<MouseWheel>", self.wheel)
        from ui_theme import apply_skin
        self.skin=apply_skin(root,self.preferences.get('skin','深空蓝'))
        self.root.after(1000,self.track_reading)
        footer = tk.Frame(page, bg=BG)
        footer.pack(fill="x", padx=28, pady=(8, 14))
        tk.Label(footer, text="开放版本优先 · 未找到免费原文时提供出版社入口 · 查询内容会发送到文献检索服务", bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        self.empty("复制一次，找到原文", "支持英文论文标题、DOI、arXiv，以及可读取的公众号 / 新闻推送。\n遇到中文推送标题或网页验证时，粘贴其中的英文论文标题最准确。")
        self.root.after(1000 if self.root.state()=='withdrawn' and not self.busy else 100, self.poll)
        self.input.focus_set()
        menu = tk.Menu(self.input, tearoff=False)
        menu.add_command(label="查询选中的文献", command=self.search_selection)
        menu.add_command(label="粘贴并查找", command=self.paste_search)
        self.input.bind("<Button-3>", lambda event: menu.tk_popup(event.x_root, event.y_root))
        root.protocol('WM_DELETE_WINDOW',self.close)

    def search_selection(self):
        if self.busy:
            return
        try:
            selected = self.input.get("sel.first", "sel.last")
        except tk.TclError:
            self.status.set("请先选中论文标题或 DOI。")
            return
        self.input.delete("1.0", "end")
        self.input.insert("1.0", selected)
        self.search()

    def open_library(self, paper=None):
        from library_ui import LibraryWindow
        if not self.library_window or not self.library_window.win.winfo_exists():
            self.library_window = LibraryWindow(self.page_host, self.library_directory, embedded=True)
            self.library_window.on_graph=lambda:self.show_page('graph')
            self.library_window.on_reader=self.open_reader
            self.library_window.lookup_email=lambda:self.email
        self.show_page('library')
        if paper:
            self.library_window.collect(paper)
        return self.library_window

    def show_page(self, key):
        if key!=self.current_page:self.stop_reading()
        if key=='library' and not self.library_window:
            self.open_library();return
        if key=='graph' and not self.graph_page:
            from graph_ui import GraphPage
            self.graph_page=GraphPage(self.page_host,self.library_directory)
            self.graph_page.on_reader=self.open_reader
            self.graph_page.on_query=self.query_reference
            self.graph_page.on_collect=self.collect_reference
        if key=='reader' and not self.reader_page:
            from reader_ui import ReaderPage
            self.reader_page=ReaderPage(self.page_host,self.library_directory,self.query_reference,self.collect_reference)
            self.reader_page.on_document_change=self.stop_reading
        for child in self.page_host.winfo_children():child.pack_forget()
        target=self.query_page if key=='query' else self.library_window.win if key=='library' else self.graph_page.frame if key=='graph' else self.reader_page.frame if key=='reader' else self.settings_page
        target.pack(fill='both',expand=True)
        self.current_page=key
        for name,button in self.nav_buttons.items():button.configure(style='ActiveNav.TButton' if name==key else 'Nav.TButton')
        if key=='graph':self.graph_page.refresh()
        from ui_theme import apply_skin
        apply_skin(self.root,self.skin)

    def show_summary(self):
        self.stop_reading()
        if self.summary_dialog and self.summary_dialog.winfo_exists():
            self.summary_view.refresh();self.summary_dialog.deiconify();self.summary_dialog.lift();self.summary_dialog.focus_force();return
        from summary_ui import SummaryView
        from ui_theme import apply_skin
        dialog=tk.Toplevel(self.root);self.summary_dialog=dialog
        dialog.title('阅读总结 · 昨日回顾');dialog.minsize(860,560);dialog.transient(self.root)
        self.root.update_idletasks()
        x=max(0,self.root.winfo_rootx()+(self.root.winfo_width()-920)//2)
        y=max(0,self.root.winfo_rooty()+(self.root.winfo_height()-740)//2)
        dialog.geometry(f'920x740+{x}+{y}');style_dialog(dialog)
        self.summary_view=SummaryView(dialog,self.library_directory)
        self.summary_view.frame.pack(fill='both',expand=True);self.summary_view.refresh()
        def dismiss():
            dialog.destroy();self.summary_dialog=None;self.summary_view=None
            self.root.focus_force()
        dialog.protocol('WM_DELETE_WINDOW',dismiss);dialog.bind('<Escape>',lambda _:dismiss())
        apply_skin(self.root,self.skin);dialog.lift();dialog.focus_force()

    def track_reading(self):
        from reading_stats import foreground_reader
        try:self.reading_clock.tick(self.reader_page.rid if self.reader_page else None,foreground_reader(self))
        except Exception as exc:self.status.set('阅读计时暂未保存：'+str(exc))
        if self.root.winfo_exists():self.root.after(1000,self.track_reading)

    def stop_reading(self):
        if self.reader_page:self.reader_page.save_notes()
        self.reading_clock.stop()

    def open_reader(self,rid):
        self.show_page('reader')
        try:self.reader_page.open(rid)
        except Exception as exc:messagebox.showerror('PDF 未打开',str(exc),parent=self.root)

    def query_reference(self,query):
        self.show_page('query');self.input.delete('1.0','end');self.input.insert('1.0',query)
        self.auto_open=False
        if self.busy:self.status.set('上一查询仍在进行；完成后点击查找原文。')
        else:self.search()

    def collect_reference(self,ref):
        from paper_finder import Paper
        self.open_library().collect(Paper(ref['title'],ref.get('doi',''),year=ref.get('year',''),origin='本地参考文献（需核对）'),download=False)

    def open_link(self,paper,link):
        if link.kind=='pdf':
            self.open_library()
            self.library_window.collect(paper,read_after=True,preferred_url=link.url)
        else:self.open_url(link.url)

    def close(self):
        if self.library_window and self.library_window.busy:
            self.library_window.status.set('归档操作仍在进行，完成后可退出。');return
        if self.reader_page:
            try:self.reader_page.close()
            except Exception as exc:messagebox.showerror('笔记未保存',str(exc),parent=self.root);return
        try:self.reading_clock.stop()
        except Exception as exc:messagebox.showerror('阅读统计未保存',str(exc),parent=self.root);return
        if self.library_window:self.library_window.library.close()
        if self.graph_page:self.graph_page.close()
        if getattr(self,'desktop',None):self.desktop.close()
        self.root.destroy()

    def scholar_search(self):
        query = self.input.get("1.0", "end").strip()
        if query:
            self.open_url("https://scholar.google.com/scholar?" + urllib.parse.urlencode({"q": query}))
        else:
            self.status.set("请先粘贴论文标题或 DOI。")

    def extension_help(self):
        path = app_dir() / "右键插件安装.html"
        if path.exists():
            webbrowser.open(path.as_uri())
        else:
            messagebox.showinfo("浏览器右键工具", "请保留软件旁边的 browser-extension 文件夹和右键插件安装.html。\n在 Edge / Chrome 扩展页开启开发者模式，加载 browser-extension 文件夹。", parent=self.root)

    def start_selection_helper(self):
        helper = app_dir() / "全局选词助手.exe"
        if not helper.exists():
            messagebox.showinfo("全局选词助手", "请将全局选词助手.exe 与文献直达.exe 放在同一目录。", parent=self.root)
            return
        try:
            subprocess.Popen([str(helper), str(app_dir() / "文献直达.exe")], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.status.set("快捷键助手已启动 · 正在确认可用快捷键…")
            self.root.after(400, self.read_shortcut_status)
        except OSError as exc:
            messagebox.showerror("启动失败", str(exc), parent=self.root)

    def read_shortcut_status(self, attempt=0):
        try:
            state = json.loads((app_dir() / "shortcut-status.json").read_text("utf-8"))
            shortcut = state.get("shortcut", "")
            shortcut = parse_shortcut(shortcut)[0]
            self.status.set(state.get("error") or ("选中文字后按 " + shortcut + " 查询" if state.get("registered") else "快捷键被占用 · 可使用浏览器右键或粘贴查询"))
        except (OSError, ValueError, AttributeError):
            if attempt < 5:
                self.root.after(200, lambda: self.read_shortcut_status(attempt + 1))
            else:
                self.status.set("快捷键助手已启动 · 可在托盘菜单查看当前快捷键")

    def resize_cards(self, event):
        self.canvas.itemconfigure(self.cards_id, width=event.width)
        for child in self.cards.winfo_children():
            for widget in child.winfo_children():
                if isinstance(widget, tk.Label):
                    widget.configure(wraplength=max(300, event.width - 50))

    def wheel(self, event):
        if event.widget is self.input or self.current_page!='query':
            return
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def clear_cards(self):
        for widget in self.cards.winfo_children():
            widget.destroy()
        self.canvas.yview_moveto(0)

    def empty(self, title, text):
        self.clear_cards()
        frame = tk.Frame(self.cards, bg=PANEL, padx=24, pady=30)
        frame.pack(fill="x", pady=5)
        tk.Label(frame, text=title, fg=FG, bg=PANEL, font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Label(frame, text=text, fg=MUTED, bg=PANEL, justify="left", wraplength=780).pack(anchor="w", pady=(10, 0))

    def paste_search(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("剪贴板为空", "请先复制论文标题、DOI 或推送链接。", parent=self.root)
            return
        self.input.delete("1.0", "end")
        self.input.insert("1.0", text)
        self.search()

    def search(self):
        if self.busy:
            return
        text = self.input.get("1.0", "end").strip()
        if not text:
            self.status.set("请先粘贴论文标题、DOI 或推送链接。")
            self.input.focus_set()
            return
        self.busy = True
        self.started_at = time.monotonic()
        self.result = None
        self.copy_button.configure(state="disabled")
        self.search_button.configure(state="disabled")
        self.paste_button.configure(state="disabled")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self.status.set("正在查找…")
        self.empty("正在查找文献…", "结果到达即可打开；论文信息和开放原文将陆续补齐。")
        email = self.email

        def work():
            try:
                result = find_papers(text, email, lambda value: self.events.put(("status", value)),
                                     lambda value: self.events.put(("partial", value)))
                self.events.put(("result", result))
            except BrowserPageRequired as exc:
                self.events.put(("browser-required", exc))
            except Exception as exc:
                self.events.put(("error", str(exc) if isinstance(exc, LookupError) else "查询暂时失败，请稍后重试或改用 DOI。"))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status.set(value)
                elif kind == "partial":
                    self.result = value
                    self.copy_button.configure(state="normal")
                    self.render(value)
                else:
                    self.busy = False
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.search_button.configure(state="normal")
                    self.paste_button.configure(state="normal")
                    if kind == "browser-required":
                        self.auto_open = False
                        self.result = None
                        self.copy_button.configure(state="disabled")
                        self.status.set("请在浏览器打开推送后继续查询")
                        self.empty("在浏览器中继续查找", str(value))
                        frame = self.cards.winfo_children()[0]
                        buttons = tk.Frame(frame, bg=PANEL)
                        buttons.pack(anchor="w", pady=(16, 0))
                        ttk.Button(buttons, text="在浏览器打开推送 ↗", style="Accent.TButton", command=lambda url=value.url: self.open_url(url)).pack(side="left")
                        ttk.Button(buttons, text="安装 / 使用右键工具", command=self.extension_help).pack(side="left", padx=10)
                        ttk.Button(buttons, text="启用快捷键", command=self.start_selection_helper).pack(side="left")
                    elif kind == "error":
                        self.auto_open = False
                        self.result = None
                        self.copy_button.configure(state="disabled")
                        self.status.set("查询未完成")
                        self.empty("暂时没有结果", value)
                    else:
                        self.result = value
                        self.copy_button.configure(state="normal")
                        self.render(value)
        except queue.Empty:
            pass
        self.root.after(1000 if self.root.state()=='withdrawn' and not self.busy else 100, self.poll)

    def render(self, result):
        self.clear_cards()
        count = sum(any(x.kind in ("pdf", "fulltext") for x in p.links) for p in result.papers)
        elapsed = time.monotonic() - self.started_at
        self.status.set(f"找到 {len(result.papers)} 篇文献 / 候选，其中 {count} 篇有开放原文入口 · {elapsed:.1f} 秒" + (" · 正在补充，可直接打开" if not result.complete else ""))
        width = max(500, self.canvas.winfo_width() - 45)
        for index, paper in enumerate(result.papers):
            frame = tk.Frame(self.cards, bg=PANEL, highlightbackground="#dce4ef", highlightthickness=1, padx=17, pady=14)
            frame.pack(fill="x", pady=(0, 10))
            tk.Label(frame, text=f"{index + 1:02d}   {paper.match}", bg=PANEL, fg=BLUE, font=(FONT, 9), anchor="w").pack(fill="x")
            tk.Label(frame, text=paper.title, bg=PANEL, fg=FG, font=(FONT, 12, "bold"), justify="left", wraplength=width, anchor="w").pack(fill="x", pady=(5, 6))
            metadata = " · ".join(filter(None, [paper.year, paper.venue, paper.authors]))
            if metadata:
                tk.Label(frame, text=metadata, bg=PANEL, fg=MUTED, justify="left", wraplength=width, anchor="w", font=(FONT, 9)).pack(fill="x")
            if paper.doi:
                tk.Label(frame, text="DOI  " + paper.doi, bg=PANEL, fg=MUTED, justify="left", wraplength=width, anchor="w", font=(FONT, 9)).pack(fill="x", pady=(4, 0))
            if not any(x.kind in ("pdf", "fulltext") for x in paper.links):
                tk.Label(frame, text="正在查找开放版本；出版社入口已可打开。" if not result.complete else "本次未找到开放原文；可从出版社入口通过学校 / 机构权限访问。", bg=PANEL, fg="#e6b980", justify="left", wraplength=width, anchor="w", font=(FONT, 9)).pack(fill="x", pady=(7, 0))
            ttk.Button(frame, text="收藏 / 下载归档", command=lambda p=paper: self.open_library(p)).pack(anchor="w", pady=(8, 0))
            for link in paper.links[:7]:
                row = tk.Frame(frame, bg=PANEL)
                row.pack(fill="x", pady=(8, 0))
                ttk.Button(row, text=link.label + (" · 阅读" if link.kind=='pdf' else " ↗"), command=lambda p=paper,l=link: self.open_link(p,l)).pack(side="left")
                ttk.Button(row, text="复制", command=lambda url=link.url: self.copy(url)).pack(side="left", padx=(6, 10))
                tk.Label(row, text=link.source + " · " + link.note, bg=PANEL, fg=MUTED, font=(FONT, 8), justify="left", wraplength=max(250, width - 250)).pack(side="left", fill="x", expand=True)
        if result.notes:
            frame = tk.Frame(self.cards, bg=BG, padx=5, pady=6)
            frame.pack(fill="x")
            tk.Label(frame, text="检索说明\n" + "\n".join(result.notes), bg=BG, fg=MUTED, font=(FONT, 9), justify="left", wraplength=width, anchor="w").pack(fill="x")
        if self.auto_open:
            target = automatic_target(result)
            if target:
                self.auto_open = False
                match=next(((p,l) for p in result.papers for l in p.links if l.url==target),None)
                if match:self.open_link(*match)
                else:self.open_url(target)
                self.status.set("已自动打开匹配论文的原文入口 · 可在下方选择其他版本")
            elif result.complete:
                self.auto_open = False
                self.status.set("检索完成 · 请核对候选后打开原文")

    def open_url(self, url):
        if safe_link(url):
            try:
                if not webbrowser.open(url):
                    self.copy(url)
                    self.status.set("浏览器未能打开，链接已复制；可手动粘贴到浏览器。")
            except Exception:
                self.copy(url)
                self.status.set("浏览器未能打开，链接已复制。")

    def copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self.status.set("已复制到剪贴板")

    def copy_all(self):
        if not self.result:
            return
        lines = []
        for paper in self.result.papers:
            lines.extend([paper.title, paper.match])
            if paper.doi:
                lines.append("DOI: " + paper.doi)
            lines.extend(f"{x.label} [{x.source}; {x.note}]: {x.url}" for x in paper.links)
            lines.append("")
        self.copy("\n".join(lines))

    def settings(self):
        if self.settings_page and self.settings_page.winfo_exists():self.settings_page.destroy()
        dialog = ttk.Frame(self.page_host);self.settings_page=dialog
        viewport=tk.Canvas(dialog,bg=BG,highlightthickness=0)
        scroll=ttk.Scrollbar(dialog,orient='vertical',command=viewport.yview);scroll.pack(side='right',fill='y');viewport.configure(yscrollcommand=scroll.set);viewport.pack(fill='both',expand=True)
        panel = ttk.Frame(viewport, padding=22)
        panel_id=viewport.create_window(0,0,window=panel,anchor='nw')
        panel.bind('<Configure>',lambda _:viewport.configure(scrollregion=viewport.bbox('all')))
        viewport.bind('<Configure>',lambda e:viewport.itemconfigure(panel_id,width=e.width))
        viewport.bind('<MouseWheel>',lambda e:viewport.yview_scroll(-int(e.delta/120),'units'))
        self.settings_panel=panel
        ttk.Label(panel,text='设置',font=(FONT,21,'bold')).pack(anchor='w',pady=(0,12))
        from ui_theme import SKINS,apply_skin
        ttk.Label(panel,text='界面皮肤（即时预览）',font=(FONT,12,'bold')).pack(anchor='w')
        skin=tk.StringVar(value=self.skin);skin_combo=ttk.Combobox(panel,textvariable=skin,values=list(SKINS),state='readonly',width=30);skin_combo.pack(anchor='w',pady=(7,18))
        def preview(_=None):self.skin=apply_skin(self.root,skin.get())
        skin_combo.bind('<<ComboboxSelected>>',preview)
        ttk.Label(panel, text="自定义全局快捷键", font=(FONT, 12, "bold")).pack(anchor="w")
        ttk.Label(panel, text="点击输入框后按下组合键，或手动填写，例如 Ctrl + Alt + J。\n至少两个修饰键（Ctrl / Alt / Shift）+ 字母、数字或 F1–F24。", justify="left").pack(anchor="w", pady=(8, 10))
        shortcut = tk.StringVar(value=load_shortcut(app_dir()))
        entry = ttk.Entry(panel, textvariable=shortcut, width=48)
        entry.pack(fill="x")

        def capture(event):
            key = event.keysym.upper()
            if not re.fullmatch(r"[A-Z0-9]|F(?:[1-9]|1[0-9]|2[0-4])", key):
                return
            modifiers = []
            if event.state & 4:
                modifiers.append("Ctrl")
            if event.state & (8 | 0x20000):
                modifiers.append("Alt")
            if event.state & 1:
                modifiers.append("Shift")
            if len(modifiers) >= 2:
                shortcut.set(" + ".join(modifiers + [key]))
                return "break"
        entry.bind("<KeyPress>", capture)
        ttk.Label(panel, text="保存后启动 / 更新托盘助手；占用时会提示并保留可用组合。", foreground=MUTED).pack(anchor="w", pady=(8, 20))
        ttk.Label(panel, text="Unpaywall 邮箱（可选）", font=(FONT, 11, "bold")).pack(anchor="w")
        ttk.Label(panel, text="留空即可查询；填写邮箱可补充更多开放版本。\n邮箱将发送到 Unpaywall，仅保存在本机设置文件。", justify="left").pack(anchor="w", pady=8)
        email = tk.StringVar(value=self.email)
        ttk.Entry(panel, textvariable=email, width=48).pack(fill="x")
        from desktop_runtime import startup_enabled,configure_startup
        startup=tk.BooleanVar(value=startup_enabled())
        ttk.Checkbutton(panel,text='登录 Windows 后启动到后台托盘',variable=startup).pack(anchor='w',pady=(18,5))
        ttk.Label(panel,text='关闭窗口保存笔记并驻留托盘；双击托盘恢复，右键“退出程序”彻底退出。',wraplength=460,style='Muted.TLabel').pack(anchor='w')

        def save():
            value = email.get().strip()
            if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                messagebox.showerror("邮箱格式不正确", "请填写有效邮箱，或留空。", parent=dialog)
                return
            try:
                canonical, _, _ = parse_shortcut(shortcut.get())
                save_shortcut(app_dir(), canonical)
                self.preferences.update(email=value,skin=skin.get());self.config_path.write_text(json.dumps(self.preferences, ensure_ascii=False, indent=2), "utf-8")
                if startup.get()!=startup_enabled():configure_startup(startup.get(),app_dir()/'文献直达.exe')
            except (OSError, ValueError) as exc:
                messagebox.showerror("设置未保存", str(exc), parent=dialog)
                return
            self.email = value
            self.skin=apply_skin(self.root,skin.get());feedback.set('设置已保存，皮肤立即生效。')
            self.start_selection_helper()
            # The running helper reloads its config every 1.5 seconds.
            self.root.after(1200, self.read_shortcut_status)
        ttk.Button(panel, text="保存并启用", style="Accent.TButton", command=save).pack(anchor="e", pady=(20, 0))
        feedback=tk.StringVar();ttk.Label(panel,textvariable=feedback,style='Muted.TLabel').pack(anchor='w')
        self.show_page('settings')
        entry.focus_set()


def main():
    instance=None
    if os.name=='nt' and not any(arg.startswith('--verify-') for arg in sys.argv):
        from desktop_runtime import Instance
        instance=Instance(app_dir())
        if not instance.primary:
            try:instance.send(sys.argv[1:])
            finally:instance.close()
            return
        if '--quit' in sys.argv:
            helper=app_dir()/'全局选词助手.exe'
            if helper.exists():subprocess.Popen([str(helper),'--exit'],creationflags=subprocess.CREATE_NO_WINDOW)
            instance.close();return
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    if '--background' in sys.argv:root.withdraw()
    # 只用于打包验收：加载 Tcl/Tk 和结果界面后写入指定报告，不联网。
    if len(sys.argv) == 3 and sys.argv[1] == "--verify-bundle":
        from paper_finder import Paper, Result
        root.withdraw()
        app = App(root)
        paper = Paper("Bundled desktop verification", "10.1000/test")
        paper.add_link("开放 PDF", "https://example.org/test.pdf", "pdf", "test")
        app.events.put(("result", Result("test", [paper])))
        app.poll()
        root.update_idletasks()
        assert "1 篇" in app.status.get()
        assert str(app.copy_button.cget("state")) == "normal"
        root.destroy()
        Path(sys.argv[2]).write_text(json.dumps({"passed": True, "frozen": bool(getattr(sys, "frozen", False)), "checks": ["Tcl/Tk runtime", "backend imports", "result rendering", "button state"]}, indent=2), "utf-8")
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--verify-library-bundle":
        import tempfile
        from library_ui import LibraryWindow
        from graph_view import write_graph
        from library_core import pdf_metadata
        from pypdf import PdfWriter
        root.withdraw()
        with tempfile.TemporaryDirectory(dir=app_dir()) as temp:
            source = Path(temp) / 'sample.pdf'
            writer = PdfWriter(); writer.add_blank_page(100, 100)
            writer.add_metadata({'/Title': 'Bundled library verification'})
            with source.open('wb') as stream: writer.write(stream)
            window = LibraryWindow(root, Path(temp) / 'store')
            pid = window.library.create_project('Bundle test')
            rid = window.library.import_pdf(source, pid)
            window.refresh(); root.update_idletasks()
            assert len(window.tree.get_children()) == 1
            assert window.library.get(rid)['attachments']
            assert write_graph(window.library).exists()
            window.close()
        root.destroy()
        Path(sys.argv[2]).write_text(json.dumps({'passed':True,'checks':['Tk library UI','pypdf runtime','PDF archive','offline graph template']}), 'utf-8')
        return
    if len(sys.argv) == 3 and sys.argv[1] == '--verify-reader-bundle':
        import tempfile
        from pypdf import PdfWriter
        from pdf_reader_core import document_info,render_page,extract_text
        from reader_ui import ReaderPage
        from graph_ui import GraphPage
        from ui_theme import window_icon
        root.withdraw();window_icon(root)
        with tempfile.TemporaryDirectory(dir=app_dir()) as temp:
            source=Path(temp)/'fixture.pdf';writer=PdfWriter();writer.add_blank_page(300,400)
            with source.open('wb') as stream:writer.write(stream)
            assert document_info(source)==1
            image=render_page(source,0,1);assert image.size==(300,400)
            assert extract_text(source)==''
            reader=ReaderPage(root,Path(temp)/'store',lambda q:None,lambda r:None)
            graph=GraphPage(root,Path(temp)/'store')
            root.update_idletasks();reader.close();graph.close()
            assert getattr(root,'_paperquick_icon',None)
        root.destroy()
        Path(sys.argv[2]).write_text(json.dumps({'passed':True,'checks':['bundled PDFium DLL','local PDF rendering','reader UI imports','native graph UI imports','new mascot icon']}),'utf-8')
        return
    app = App(root)
    if instance:
        from desktop_runtime import DesktopRuntime
        DesktopRuntime(app,instance,background='--background' in sys.argv)
    if '--background' not in sys.argv:opening_animation(root)
    if '--settings' in sys.argv:root.after(100,app.settings)
    if "--library" in sys.argv:
        root.after(100, app.open_library)
    if "--query" in sys.argv:
        index = sys.argv.index("--query")
        if index + 1 < len(sys.argv):
            app.input.insert("1.0", sys.argv[index + 1])
            app.auto_open = "--auto-open" in sys.argv
            root.after(100, app.search)
    root.mainloop()


if __name__ == "__main__":
    main()
