"""Topic package selection and background file export."""
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog

from topic_package import prepare_package, export_package, PackageCancelled
from ui_theme import FONT, style_dialog


def size_label(size):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f'{size:.1f} {unit}' if unit != 'B' else f'{size} B'
        size /= 1024


class TopicPackageWindow:
    def __init__(self, parent, library, project=None):
        self.library = library
        self.busy = False
        self.closed = False
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.result = None
        self.win = tk.Toplevel(parent)
        self.win.title('课题一键打包')
        self.win.geometry('920x680')
        self.win.minsize(720, 560)
        self.win.transient(parent.winfo_toplevel())
        style_dialog(self.win)
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        panel = ttk.Frame(self.win, padding=16)
        panel.pack(fill='both', expand=True)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(3, weight=1)
        ttk.Label(panel, text='把一个课题的文献一起带走', font=(FONT, 14, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(panel, text='默认全选，含子课题；不受列表筛选影响。',
                  wraplength=680, style='Muted.TLabel').grid(row=1, column=0, sticky='w', pady=(4, 8))
        scope = ttk.Frame(panel)
        scope.grid(row=2, column=0, sticky='ew')
        ttk.Label(scope, text='打包范围').pack(side='left', padx=(0, 10))
        self.project_ids = [None] + [p['id'] for p in library.projects()]
        self.project_names = ['全部文献'] + [p['name'] for p in library.projects()]
        self.scope = ttk.Combobox(scope, values=self.project_names, state='readonly')
        self.scope.current(self.project_ids.index(project) if project in self.project_ids else 0)
        self.scope.pack(side='left', fill='x', expand=True)
        self.scope.bind('<<ComboboxSelected>>', lambda _: self.load_scope())
        self.select_buttons = []
        for label, value in [('全选', True), ('全不选', False)]:
            button = ttk.Button(scope, text=label, command=lambda v=value: self.select_all(v), style='Compact.TButton')
            button.pack(side='left', padx=(8, 0))
            self.select_buttons.append(button)
        table = ttk.Frame(panel)
        table.grid(row=3, column=0, sticky='nsew', pady=(10, 6))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=('state', 'size'), show='tree headings', selectmode='browse')
        self.tree.heading('#0', text='勾选文献 / 正文与附件（点击方框切换，空格切换当前项）')
        self.tree.column('#0', width=490, minwidth=260)
        self.tree.heading('state', text='文件状态')
        self.tree.column('state', width=125, minwidth=105, stretch=False)
        self.tree.heading('size', text='大小')
        self.tree.column('size', width=85, minwidth=70, stretch=False, anchor='e')
        scroll = ttk.Scrollbar(table, command=self.tree.yview)
        horizontal = ttk.Scrollbar(table, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.tree.bind('<Button-1>', self.click)
        self.tree.bind('<space>', self.toggle_focused)
        self.summary = tk.StringVar()
        ttk.Label(panel, textvariable=self.summary, style='Muted.TLabel', wraplength=680).grid(row=4, column=0, sticky='w', pady=(0, 8))
        options = ttk.Frame(panel)
        options.grid(row=5, column=0, sticky='ew')
        formats = ttk.Frame(options)
        formats.grid(row=0, column=2, sticky='e', padx=(8, 0))
        self.format = tk.StringVar(value='zip')
        self.option_widgets = []
        for label, value in [('ZIP 压缩包', 'zip'), ('文件夹', 'folder')]:
            button = ttk.Radiobutton(formats, text=label, variable=self.format, value=value, command=self.update_summary)
            button.pack(side='left', padx=(0, 10))
            self.option_widgets.append(button)
        self.directory = tk.StringVar()
        self.name = tk.StringVar()
        for row, label, variable in [(1, '保存到', self.directory), (0, '打包名称', self.name)]:
            ttk.Label(options, text=label).grid(row=row, column=0, sticky='w', pady=4, padx=(0, 10))
            entry = ttk.Entry(options, textvariable=variable)
            entry.grid(row=row, column=1, sticky='ew', pady=5)
            self.option_widgets.append(entry)
        browse = ttk.Button(options, text='选择位置…', command=self.browse)
        browse.grid(row=1, column=2, padx=(8, 0))
        self.option_widgets.append(browse)
        options.columnconfigure(1, weight=1)
        ttk.Label(panel, text='附文献与文件清单 · 同名自动编号 · 链接仅保存地址',
                  style='Muted.TLabel', wraplength=680).grid(row=6, column=0, sticky='w', pady=(5, 8))
        self.progress = ttk.Progressbar(panel, mode='determinate', maximum=100)
        self.progress.grid(row=7, column=0, sticky='ew')
        bottom = ttk.Frame(panel)
        bottom.grid(row=8, column=0, sticky='ew', pady=(10, 0))
        self.status = tk.StringVar(value='请选择保存位置，然后开始打包。')
        ttk.Label(bottom, textvariable=self.status, wraplength=470, style='Muted.TLabel').pack(side='left', fill='x', expand=True)
        self.close_button = ttk.Button(bottom, text='关闭', command=self.close)
        self.close_button.pack(side='right', padx=(8, 0))
        self.start_button = ttk.Button(bottom, text='开始打包', style='Accent.TButton', command=self.start)
        self.start_button.pack(side='right')
        self.load_scope()
        self.poll_job = self.win.after(100, self.poll)

    def load_scope(self):
        if self.busy:
            return
        self.plan = prepare_package(self.library, self.project_ids[self.scope.current()])
        self.name.set(self.plan.name.replace(' / ', '_'))
        self.selection = {p.id: {a.id for a in p.files if a.state == '可打包'} for p in self.plan.papers}
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        for i, paper in enumerate(self.plan.papers):
            key = f'p{i}'
            self.rows[key] = (paper, None)
            self.tree.insert('', 'end', iid=key)
            for j, attachment in enumerate(paper.files):
                child = f'{key}f{j}'
                self.rows[child] = (paper, attachment)
                self.tree.insert(key, 'end', iid=child)
        self.update_summary()

    def update_summary(self):
        files, size, unavailable = 0, 0, 0
        for key, (paper, attachment) in self.rows.items():
            included = paper.id in self.selection
            if attachment is None:
                available = {a.id for a in paper.files if a.state == '可打包'}
                chosen = self.selection.get(paper.id, set())
                check = '☑' if included and chosen == available else ('◩' if included else '☐')
                self.tree.item(key, text=f'{check} {paper.title}', values=(f'{len(chosen)} / {len(available)} 个文件', ''))
            else:
                available = attachment.state == '可打包'
                checked = included and attachment.id in self.selection[paper.id]
                check = ('☑' if checked else '☐') if available else '—'
                role = '正文' if attachment.role == 'primary' else '附件'
                self.tree.item(key, text=f'{check} [{role}] {attachment.name}', values=(attachment.state, size_label(attachment.size) if available else ''))
                if checked:
                    files += 1
                    size += attachment.size
                if included and attachment.state in ('文件缺失', '路径异常'):
                    unavailable += 1
        self.summary.set(f'已选 {len(self.selection)} / {len(self.plan.papers)} 篇文献 · {files} 个文件 · {size_label(size)}'
                         + (f' · {unavailable} 个缺失或异常文件，将在清单中标出' if unavailable else '')
                         + (' · 无本地文件的文献仍保留目录记录' if self.selection and not files else ''))
        self.start_button.configure(state='normal' if self.selection and not self.busy else 'disabled')

    def toggle(self, key):
        if self.busy or key not in self.rows:
            return
        paper, attachment = self.rows[key]
        if attachment is None:
            available = {a.id for a in paper.files if a.state == '可打包'}
            if paper.id in self.selection and self.selection[paper.id] == available:
                del self.selection[paper.id]
            else:
                self.selection[paper.id] = available
        elif attachment.state == '可打包':
            chosen = self.selection.setdefault(paper.id, set())
            if attachment.id in chosen:
                chosen.remove(attachment.id)
            else:
                chosen.add(attachment.id)
        self.update_summary()

    def click(self, event):
        # The disclosure indicator still expands/collapses; the checkbox or
        # title toggles the row, without selecting a different file by accident.
        if self.tree.identify_column(event.x) == '#0' and 'indicator' not in self.tree.identify_element(event.x, event.y):
            self.toggle(self.tree.identify_row(event.y))

    def toggle_focused(self, _=None):
        self.toggle(self.tree.focus())
        return 'break'

    def select_all(self, selected):
        if not self.busy:
            self.selection = {p.id: {a.id for a in p.files if a.state == '可打包'} for p in self.plan.papers} if selected else {}
            self.update_summary()

    def browse(self):
        path = filedialog.askdirectory(parent=self.win, title='选择打包保存位置', initialdir=self.directory.get() or None, mustexist=True)
        if path:
            self.directory.set(path)

    def start(self):
        if self.busy or not self.selection:
            return
        if not self.directory.get().strip():
            self.browse()
            if not self.directory.get().strip():
                return
        if not self.name.get().strip():
            self.status.set('请填写打包名称。')
            return
        self.busy = True
        self.result = None
        self.cancel.clear()
        self.progress['value'] = 0
        self.status.set('正在打包，请稍候…')
        self.close_button.configure(text='取消打包')
        self.scope.configure(state='disabled')
        for widget in self.option_widgets + self.select_buttons + [self.start_button]:
            widget.configure(state='disabled')
        plan = self.plan
        selection = {rid: set(files) for rid, files in self.selection.items()}
        directory, name, format = self.directory.get(), self.name.get(), self.format.get()

        def work():
            last = [0.0]
            def progress(done, total):
                now = time.monotonic()
                if now - last[0] > .1 or done >= total:
                    last[0] = now
                    self.events.put(('progress', (done, total)))
            try:
                result = export_package(plan, selection, directory, name, format, progress, self.cancel)
                self.events.put(('done', result))
            except PackageCancelled:
                self.events.put(('cancelled', None))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, result = self.events.get_nowait()
                if kind == 'progress':
                    done, total = result
                    self.progress['value'] = min(99, done * 100 / total) if total else 0
                    self.status.set(f'正在打包 · {size_label(done)} / {size_label(total)}')
                    continue
                self.busy = False
                self.scope.configure(state='readonly')
                for widget in self.option_widgets + self.select_buttons:
                    widget.configure(state='normal')
                self.close_button.configure(text='关闭')
                self.update_summary()
                if kind == 'done':
                    self.result = result
                    self.progress['value'] = 100
                    self.status.set(f'完成：{result["papers"]} 篇 / {result["files"]} 个文件\n保存至 {result["path"]}')
                else:
                    self.progress['value'] = 0
                    self.status.set('已取消打包，未完成的输出已清理。' if kind == 'cancelled' else '打包未完成：' + result)
        except queue.Empty:
            pass
        if not self.closed:
            self.poll_job = self.win.after(100, self.poll)

    def close(self):
        if self.busy:
            self.cancel.set()
            self.status.set('正在取消并清理未完成的输出，请稍候…')
            return
        self.closed = True
        self.win.after_cancel(self.poll_job)
        self.win.destroy()
