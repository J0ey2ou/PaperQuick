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
        from tracking_runtime import TrackingCoordinator
        self.tracking=TrackingCoordinator(root,lambda:self.library_directory)
        self.current_page = 'query'
        navigation=tk.Frame(root,bg=BG)
        self.navigation=navigation
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

        tk.Label(page,text="收到一篇文献，顺手开始阅读",bg=BG,fg=BLUE,font=(FONT,10),anchor='w').pack(fill='x',padx=28,pady=(0,12))
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
            self.library_window.on_compare=self.open_attachment
            self.library_window.lookup_email=lambda:self.email
            self.library_window.before_remove=self.before_remove_papers
        self.show_page('library')
        if paper:
            self.library_window.collect(paper)
        return self.library_window

    def show_page(self, key):
        if key!='reader' and self.reader_page and self.reader_page.focus_mode:self.reader_page.toggle_focus()
        if key!=self.current_page:self.stop_reading()
        if key=='library' and not self.library_window:
            self.open_library();return
        if key=='graph' and not self.graph_page:
            from graph_ui import GraphPage
            self.graph_page=GraphPage(self.page_host,self.library_directory)
            self.graph_page.on_reader=self.open_reader
            self.graph_page.on_query=self.query_reference
            self.graph_page.on_collect=self.collect_reference
            self.graph_page.on_note=self.open_note
        if key=='reader' and not self.reader_page:
            from reader_ui import ReaderPage
            self.reader_page=ReaderPage(self.page_host,self.library_directory,self.query_reference,self.collect_reference)
            self.reader_page.on_open_related=self.open_reader
            self.reader_page.on_focus_mode=self.reader_focus_mode
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
        dialog.title('阅读总结 · 发现下一篇好文献');dialog.minsize(1020,720);dialog.transient(self.root)
        self.root.update_idletasks()
        width=min(1160,self.root.winfo_screenwidth()-60);height=min(860,self.root.winfo_screenheight()-90)
        x=max(0,self.root.winfo_rootx()+(self.root.winfo_width()-width)//2)
        y=max(0,self.root.winfo_rooty()+(self.root.winfo_height()-height)//2)
        dialog.geometry(f'{width}x{height}+{x}+{y}');style_dialog(dialog)
        def dismiss():
            if self.summary_view:self.summary_view.close()
            dialog.destroy();self.summary_dialog=None;self.summary_view=None
            self.root.focus_force()
        def read(rid):dismiss();self.open_reader(rid)
        def query(value):dismiss();self.query_reference(value)
        self.summary_view=SummaryView(dialog,self.library_directory,on_read=read,on_query=query,coordinator=self.tracking)
        self.summary_view.frame.pack(fill='both',expand=True);self.summary_view.refresh()
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
        except Exception as exc:messagebox.showerror('文档未打开',str(exc),parent=self.root)

    def reader_focus_mode(self,focused):
        if focused:self.navigation.pack_forget()
        else:self.navigation.pack(fill='x',padx=26,pady=(18,8),before=self.page_host)

    def open_note(self,rid):
        self.open_reader(rid)
        if self.reader_page:self.reader_page.show_notes();self.reader_page.notebook.select(self.reader_page.note_tab)

    def before_remove_papers(self,ids):
        if self.reader_page and self.reader_page.rid in ids:
            if not self.reader_page.can_close():return False
            self.stop_reading();self.reader_page.save_notes();self.reader_page.rid=None;self.reader_page.generation+=1;self.reader_page.path=None;self.reader_page.count=0;self.reader_page.image_size=None
            self.reader_page.canvas.delete('all');self.reader_page.title.set('文献已移出，可在文献分类中恢复')
            self.reader_page.document_canvas.reset();self.reader_page.loading=False
        return True

    def open_attachment(self,rid,attachment):
        self.show_page('reader')
        try:
            if self.reader_page.rid!=rid:self.reader_page.open(rid)
            self.reader_page.compare_attachment(attachment)
        except Exception as exc:messagebox.showerror('附件未打开',str(exc),parent=self.root)

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
        word=getattr(self.library_window,'word_citations',None)
        if word and word.busy:
            word.status.set('Word 引用仍在处理，完成后即可退出。');return
        if self.library_window and self.library_window.busy:
            self.library_window.status.set('归档操作仍在进行，完成后可退出。');return
        for window in (getattr(self.library_window,'attachment_window',None),getattr(self.library_window,'conversion_window',None)):
            if window and not window.closed and window.busy:
                window.win.lift();return
        if self.reader_page:
            try:
                if self.reader_page.close() is False:return
            except Exception as exc:messagebox.showerror('笔记未保存',str(exc),parent=self.root);return
        try:self.reading_clock.stop()
        except Exception as exc:messagebox.showerror('阅读统计未保存',str(exc),parent=self.root);return
        if word and not word.closed:word.close()
        for window in (getattr(self.library_window,'attachment_window',None),getattr(self.library_window,'conversion_window',None)):
            if window and not window.closed:window.close()
        if self.library_window:self.library_window.library.close()
        if self.graph_page:self.graph_page.close()
        if self.summary_view:self.summary_view.close()
        self.tracking.close()
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

        from library_core import Library
        from reading_documents import DEFAULT_NOTE_TEMPLATE
        library=Library(self.library_directory)
        try:
            marker_size=tk.StringVar(value=str(library.setting('reader_marker_size',18)))
            note_template_value=library.setting('research_note_template',DEFAULT_NOTE_TEMPLATE)
            continuous=tk.BooleanVar(value=library.setting('continuous_reading',True))
        finally:library.close()
        ttk.Separator(panel).pack(fill='x',pady=18)
        ttk.Label(panel,text='阅读与笔记',font=(FONT,12,'bold')).pack(anchor='w')
        ttk.Checkbutton(panel,text='连续阅读，向下滚动即可接着看下一页',variable=continuous).pack(anchor='w',pady=10)
        row=ttk.Frame(panel);row.pack(fill='x');ttk.Label(row,text='页内笔记 / 链接标记大小（8–48）').pack(side='left');ttk.Spinbox(row,from_=8,to=48,width=7,textvariable=marker_size).pack(side='left',padx=12)
        ttk.Label(panel,text='自定义研究笔记模板',font=(FONT,11,'bold')).pack(anchor='w',pady=(18,6))
        template_editor=tk.Text(panel,height=9,wrap='word',font=(FONT,11),undo=True);template_editor.insert('1.0',note_template_value);template_editor.pack(fill='x')
        def restore_template():template_editor.delete('1.0','end');template_editor.insert('1.0',DEFAULT_NOTE_TEMPLATE)
        ttk.Button(panel,text='恢复默认模板',command=restore_template).pack(anchor='w',pady=6)

        def save():
            value = email.get().strip()
            if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                messagebox.showerror("邮箱格式不正确", "请填写有效邮箱，或留空。", parent=dialog)
                return
            try:
                canonical, _, _ = parse_shortcut(shortcut.get())
                size=int(marker_size.get());template=template_editor.get('1.0','end-1c')
                if not 8<=size<=48:raise ValueError('标记大小应在 8–48 之间。')
                if len(template)>12000:raise ValueError('笔记模板最多 12000 个字符。')
                save_shortcut(app_dir(), canonical)
                self.preferences.update(email=value,skin=skin.get());self.config_path.write_text(json.dumps(self.preferences, ensure_ascii=False, indent=2), "utf-8")
                if startup.get()!=startup_enabled():configure_startup(startup.get(),app_dir()/'文献直达.exe')
                library=Library(self.library_directory)
                try:
                    library.set_setting('reader_marker_size',size);library.set_setting('research_note_template',template);library.set_setting('continuous_reading',continuous.get())
                finally:library.close()
                if self.reader_page:
                    self.reader_page.marker_size=size;self.reader_page.draw_annotations()
                    changed=self.reader_page.continuous.get()!=continuous.get();self.reader_page.continuous.set(continuous.get())
                    if changed and self.reader_page.path and not self.reader_page.loading:self.reader_page.render()
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
    if len(sys.argv)==3 and sys.argv[1]=='--verify-reader-upgrade-bundle':
        import tempfile
        from library_core import Library
        from reader_ui import ReaderPage
        from references import parse_references
        from reading_documents import read_text_file
        from PIL import Image
        from document_conversion import converter_path
        root.withdraw()
        with tempfile.TemporaryDirectory(dir=app_dir()) as temp:
            source=Path(temp)/'fixture.txt';source.write_text('Bundled text reading\nReferences\n[1] Doe J. A complete reference example. doi:10.9999/fixture',encoding='utf-8')
            lib=Library(Path(temp)/'store');rid=lib.import_document(source);lib.close()
            reader=ReaderPage(root,Path(temp)/'store',lambda q:None,lambda ref:None);reader.frame.pack(fill='both',expand=True);reader.open(rid)
            deadline=time.monotonic()+15
            while reader.loading and time.monotonic()<deadline:root.update();time.sleep(.02)
            assert reader.text_view and 'Bundled text' in reader.text_view.get('1.0','end')
            reader.notes.insert('end','Fixture note');reader.insert_note_image(Image.new('RGB',(80,60),'blue'));reader.save_notes();reader.dock_references();root.update_idletasks()
            lib=Library(reader.directory);assert lib.get(rid)['note_images'];reader.workflow_export_notes(Path(temp)/'notes.html');graph=lib.graph();assert any(e['kind']=='note' for e in graph['edges'])
            second=Path(temp)/'second.txt';second.write_text('Second fixture',encoding='utf-8');batch=lib.import_batch([second],lib.projects()[0]['id']);assert lib.undo_import(batch['batch'])['restored']==1
            lib.remove_papers([rid]);assert lib.restore_removed()==1;lib.close()
            assert len(parse_references('1 Doe A. Study title. J Med 2024;1:2. doi:10.9999/one\n2 Roe B. Study two. J Med 2025;2:3. doi:10.9999/two\n3 Ray C. Study three. J Med 2026;3:4. doi:10.9999/three'))==3
            assert converter_path().is_file();reader.close()
        root.destroy();Path(sys.argv[2]).write_text(json.dumps({'passed':True,'frozen':bool(getattr(sys,'frozen',False)),'checks':['TXT reader','embedded image notes','reference dock','export-note graph','durable import undo','removal and recovery','BMJ-style references','Word helper bundled']},ensure_ascii=False,indent=2),'utf-8');return
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
    if len(sys.argv)==3 and sys.argv[1]=='--verify-discovery-bundle':
        import tempfile
        from library_core import Library
        from summary_ui import SummaryView
        from citation_tracking import find_related
        from literature_tracking import TrackingStore,run_check
        root.withdraw()
        with tempfile.TemporaryDirectory(dir=app_dir()) as temp:
            lib=Library(Path(temp)/'store');lib.save({'title':'Fictional nutrition study','keywords':'nutrition; dietary patterns'})
            store=TrackingStore(lib);tid=store.save_topic('Bundle topic','TITLE_ABS:nutrition')
            result=run_check(store,tid,fetcher=lambda *a,**kw:{'items':[{'title':'Fictional discovery','doi':'10.9999/fixture'}],'total':1})
            assert result['status']=='complete';assert len(store.results(result['run_id']))==1
            view=SummaryView(root,lib.root);view.refresh();root.update_idletasks()
            assert len(view.tabs.tabs())==4 and view.queries['pubmed']
            assert find_related({},[])['items']==[]
            view.close();lib.close()
        root.destroy();Path(sys.argv[2]).write_text(json.dumps({'passed':True,'checks':['summary popup','local keywords','four search queries','tracking history','citation modules']}),'utf-8');return
    if len(sys.argv)==3 and sys.argv[1]=='--verify-word-bundle':
        import tempfile
        from library_core import Library
        from word_citation_ui import WordCitationsWindow
        from citation_styles import list_styles,format_document,asset_directory
        from citation_metadata import to_csl
        from word_bridge import health
        root.withdraw()
        styles=list_styles();assert len(styles)>=31
        item=to_csl({'id':'fixture','title':'Fictional citation example','authors_structured':[{'family':'Chen','given':'Lin'}],'year':'2025','venue':'Example Journal','volume':'7','pages':'12-18'})
        for style in ('apa','vancouver-nlm','china-national-standard-gb-t-7714-2015-numeric'):
            result=format_document({'fixture':item},[{'id':'check','items':[{'id':'fixture'}]}],style)
            assert result['citations']['check'].startswith('{\\rtf') and 'Fictional citation example' in result['plain_bibliography']
        assert health()['installed']
        assert (asset_directory()/'vendor'/'node.exe').is_file()
        with tempfile.TemporaryDirectory(dir=app_dir()) as temp:
            lib=Library(Path(temp)/'store');lib.save({'title':'Fictional citation example'});lib.close()
            window=WordCitationsWindow(root,Path(temp)/'store');root.update_idletasks();assert len(window.tree.get_children())==1;window.close()
        root.destroy();Path(sys.argv[2]).write_text(json.dumps({'passed':True,'frozen':bool(getattr(sys,'frozen',False)),'styles':len(styles),'checks':['portable offline CSL runtime','APA / Vancouver / GB citation rendering','Word bridge binary','Word citation dialog']}),'utf-8');return
    if len(sys.argv)==3 and sys.argv[1]=='--verify-documents-bundle':
        import tempfile,zipfile
        from library_core import Library
        from document_conversion import health,can_convert,convert_document
        from attachment_ui import AttachmentManager
        from document_conversion_ui import ConversionWindow
        root.withdraw()
        assert health()['helper']
        with tempfile.TemporaryDirectory(dir=app_dir()) as temp:
            source=Path(temp)/'fictional.docx'
            with zipfile.ZipFile(source,'w') as archive:
                archive.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
                archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Fictional Word archive check</w:t></w:r></w:p></w:body></w:document>')
            lib=Library(Path(temp)/'store');rid=lib.import_document(source)
            lib.add_attachment_link(rid,'https://example.org/supplement','Fictional supplement')
            assert lib.primary_attachment(rid)['kind']=='docx'
            assert len(lib.get(rid)['attachments'])==2
            assert can_convert(source,'.pdf') and can_convert('sample.pdf','.docx')
            from pypdf import PdfWriter
            from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
            pdf=Path(temp)/'fictional.pdf';writer=PdfWriter();page=writer.add_blank_page(300,400)
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 25 350 Td (Fictional conversion check) Tj ET');page[NameObject('/Contents')]=writer._add_object(content)
            writer.add_blank_page(300,400)
            with pdf.open('wb') as stream:writer.write(stream)
            for mode in ('text','appearance'):
                output=convert_document(pdf,Path(temp)/(mode+'.docx'),mode=mode)
                with zipfile.ZipFile(output) as archive:
                    assert 'word/document.xml' in archive.namelist()
                    assert any(name.startswith('word/media/') for name in archive.namelist())
            manager=AttachmentManager(root,lib.root,rid);root.update_idletasks();manager.close()
            conversion=ConversionWindow(root,lib.root,rid=rid,source=source);root.update_idletasks();conversion.close();lib.close()
        root.destroy();Path(sys.argv[2]).write_text(json.dumps({'passed':True,'frozen':bool(getattr(sys,'frozen',False)),'checks':['Word import and primary attachment','supplement URL association','attachment manager UI','conversion UI and helper binary','local PDF to Word in both modes']}),'utf-8');return
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
