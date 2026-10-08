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

BG = "#f3f6fa"
FG = "#172c45"
MUTED = "#5d6f84"
BLUE = "#215cce"
FONT = "Microsoft YaHei UI"


def app_dir():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


class App:
    def __init__(self, root):
        self.root = root
        root.title("文献直达")
        root.geometry("940x790")
        root.minsize(780, 630)
        root.configure(bg=BG)
        root.option_add("*Font", (FONT, 10))
        self.events = queue.Queue()
        self.result = None
        self.busy = False
        self.started_at = time.monotonic()
        self.auto_open = False
        self.email = ""
        self.config_path = app_dir() / "settings.json"
        try:
            self.email = json.loads(self.config_path.read_text("utf-8")).get("email", "")
        except (OSError, ValueError, AttributeError):
            pass
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Accent.TButton", font=(FONT, 10, "bold"), foreground="white", background=BLUE, padding=(18, 10), borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#194aa8"), ("disabled", "#a9b9d4")])
        style.configure("TButton", font=(FONT, 9), padding=(12, 7))
        style.configure("TProgressbar", background=BLUE, troughcolor="#e4eaf3", borderwidth=0)

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=28, pady=(22, 12))
        tk.Label(header, text="文献直达", bg=BG, fg=FG, font=(FONT, 23, "bold")).pack(side="left")
        tk.Label(header, text="从一段文献信息，到原文入口", bg=BG, fg=MUTED).pack(side="left", padx=16, pady=(9, 0))
        ttk.Button(header, text="设置", command=self.settings).pack(side="right")
        ttk.Button(header, text="右键工具", command=self.extension_help).pack(side="right", padx=8)
        ttk.Button(header, text="全局快捷键", command=self.start_selection_helper).pack(side="right")

        box = tk.Frame(root, bg="white", highlightbackground="#dce4ef", highlightthickness=1)
        box.pack(fill="x", padx=28)
        tk.Label(box, text="粘贴论文标题、DOI、arXiv 链接或推送链接", bg="white", fg=FG, anchor="w", font=(FONT, 11, "bold")).pack(fill="x", padx=18, pady=(15, 8))
        self.input = tk.Text(box, height=3, wrap="word", bg="#f7f9fc", fg=FG, relief="flat", padx=12, pady=9, insertbackground=BLUE, font=(FONT, 11), undo=True)
        self.input.pack(fill="x", padx=18)
        self.input.bind("<Control-Return>", lambda event: self.search())
        bar = tk.Frame(box, bg="white")
        bar.pack(fill="x", padx=18, pady=13)
        self.paste_button = ttk.Button(bar, text="粘贴并查找", command=self.paste_search)
        self.paste_button.pack(side="left")
        ttk.Button(bar, text="清空", command=lambda: self.input.delete("1.0", "end")).pack(side="left", padx=8)
        ttk.Button(bar, text="直接学术搜索 ↗", command=self.scholar_search).pack(side="left", padx=6)
        self.search_button = ttk.Button(bar, text="查找原文", style="Accent.TButton", command=self.search)
        self.search_button.pack(side="right")

        statusbar = tk.Frame(root, bg=BG)
        statusbar.pack(fill="x", padx=28, pady=(13, 6))
        self.status = tk.StringVar(value="准备就绪 · 需要联网检索")
        tk.Label(statusbar, textvariable=self.status, bg=BG, fg=MUTED, anchor="w").pack(side="left", fill="x", expand=True)
        self.copy_button = ttk.Button(statusbar, text="复制全部链接", command=self.copy_all, state="disabled")
        self.copy_button.pack(side="right")
        self.progress = ttk.Progressbar(root, mode="determinate")
        self.progress.pack(fill="x", padx=28, pady=(0, 9))

        result_frame = tk.Frame(root, bg=BG)
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
        footer = tk.Frame(root, bg=BG)
        footer.pack(fill="x", padx=28, pady=(8, 14))
        tk.Label(footer, text="开放版本优先 · 未找到免费原文时提供出版社入口 · 查询内容会发送到文献检索服务", bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        self.empty("复制一次，找到原文", "支持英文论文标题、DOI、arXiv，以及可读取的公众号 / 新闻推送。\n遇到中文推送标题或网页验证时，粘贴其中的英文论文标题最准确。")
        self.root.after(100, self.poll)
        self.input.focus_set()
        menu = tk.Menu(self.input, tearoff=False)
        menu.add_command(label="查询选中的文献", command=self.search_selection)
        menu.add_command(label="粘贴并查找", command=self.paste_search)
        self.input.bind("<Button-3>", lambda event: menu.tk_popup(event.x_root, event.y_root))

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
        if event.widget is self.input:
            return
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def clear_cards(self):
        for widget in self.cards.winfo_children():
            widget.destroy()
        self.canvas.yview_moveto(0)

    def empty(self, title, text):
        self.clear_cards()
        frame = tk.Frame(self.cards, bg="white", padx=24, pady=30)
        frame.pack(fill="x", pady=5)
        tk.Label(frame, text=title, fg=FG, bg="white", font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Label(frame, text=text, fg=MUTED, bg="white", justify="left", wraplength=780).pack(anchor="w", pady=(10, 0))

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
                        buttons = tk.Frame(frame, bg="white")
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
        self.root.after(100, self.poll)

    def render(self, result):
        self.clear_cards()
        count = sum(any(x.kind in ("pdf", "fulltext") for x in p.links) for p in result.papers)
        elapsed = time.monotonic() - self.started_at
        self.status.set(f"找到 {len(result.papers)} 篇文献 / 候选，其中 {count} 篇有开放原文入口 · {elapsed:.1f} 秒" + (" · 正在补充，可直接打开" if not result.complete else ""))
        width = max(500, self.canvas.winfo_width() - 45)
        for index, paper in enumerate(result.papers):
            frame = tk.Frame(self.cards, bg="white", highlightbackground="#dce4ef", highlightthickness=1, padx=17, pady=14)
            frame.pack(fill="x", pady=(0, 10))
            tk.Label(frame, text=f"{index + 1:02d}   {paper.match}", bg="white", fg=BLUE, font=(FONT, 9), anchor="w").pack(fill="x")
            tk.Label(frame, text=paper.title, bg="white", fg=FG, font=(FONT, 12, "bold"), justify="left", wraplength=width, anchor="w").pack(fill="x", pady=(5, 6))
            metadata = " · ".join(filter(None, [paper.year, paper.venue, paper.authors]))
            if metadata:
                tk.Label(frame, text=metadata, bg="white", fg=MUTED, justify="left", wraplength=width, anchor="w", font=(FONT, 9)).pack(fill="x")
            if paper.doi:
                tk.Label(frame, text="DOI  " + paper.doi, bg="white", fg=MUTED, justify="left", wraplength=width, anchor="w", font=(FONT, 9)).pack(fill="x", pady=(4, 0))
            if not any(x.kind in ("pdf", "fulltext") for x in paper.links):
                tk.Label(frame, text="正在查找开放版本；出版社入口已可打开。" if not result.complete else "本次未找到开放原文；可从出版社入口通过学校 / 机构权限访问。", bg="white", fg="#94652a", justify="left", wraplength=width, anchor="w", font=(FONT, 9)).pack(fill="x", pady=(7, 0))
            for link in paper.links[:7]:
                row = tk.Frame(frame, bg="white")
                row.pack(fill="x", pady=(8, 0))
                ttk.Button(row, text=link.label + " ↗", command=lambda url=link.url: self.open_url(url)).pack(side="left")
                ttk.Button(row, text="复制", command=lambda url=link.url: self.copy(url)).pack(side="left", padx=(6, 10))
                tk.Label(row, text=link.source + " · " + link.note, bg="white", fg=MUTED, font=(FONT, 8), justify="left", wraplength=max(250, width - 250)).pack(side="left", fill="x", expand=True)
        if result.notes:
            frame = tk.Frame(self.cards, bg=BG, padx=5, pady=6)
            frame.pack(fill="x")
            tk.Label(frame, text="检索说明\n" + "\n".join(result.notes), bg=BG, fg=MUTED, font=(FONT, 9), justify="left", wraplength=width, anchor="w").pack(fill="x")
        if self.auto_open:
            target = automatic_target(result)
            if target:
                self.auto_open = False
                self.open_url(target)
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
        dialog = tk.Toplevel(self.root)
        dialog.title("文献直达 · 设置")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        panel = ttk.Frame(dialog, padding=22)
        panel.pack(fill="both", expand=True)
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

        def save():
            value = email.get().strip()
            if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                messagebox.showerror("邮箱格式不正确", "请填写有效邮箱，或留空。", parent=dialog)
                return
            try:
                canonical, _, _ = parse_shortcut(shortcut.get())
                save_shortcut(app_dir(), canonical)
                self.config_path.write_text(json.dumps({"email": value}, ensure_ascii=False, indent=2), "utf-8")
            except (OSError, ValueError) as exc:
                messagebox.showerror("设置未保存", str(exc), parent=dialog)
                return
            self.email = value
            dialog.destroy()
            self.start_selection_helper()
            # The running helper reloads its config every 700 ms.
            self.root.after(1200, self.read_shortcut_status)
        ttk.Button(panel, text="保存并启用", style="Accent.TButton", command=save).pack(anchor="e", pady=(20, 0))
        entry.focus_set()


def main():
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
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
    app = App(root)
    if "--query" in sys.argv:
        index = sys.argv.index("--query")
        if index + 1 < len(sys.argv):
            app.input.insert("1.0", sys.argv[index + 1])
            app.auto_open = "--auto-open" in sys.argv
            root.after(100, app.search)
    root.mainloop()


if __name__ == "__main__":
    main()
