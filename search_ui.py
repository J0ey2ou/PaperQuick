"""Full-library and in-document search with explicit local index/OCR tasks."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog

from fulltext_index import FulltextIndex, LocalOCR, IndexCancelled
from library_core import Library
from ui_theme import style_dialog
from ui_widgets import flow_bar
from workspace_tasks import TaskManager


def index_worker(directory, **options):
    def work(context):
        index = FulltextIndex(directory)
        try:return index.update(cancel=context.cancelled, progress=context.progress, **options)
        except IndexCancelled:
            context.check_cancelled()
            raise
    return work


def register_index_tasks(manager, directory):
    if hasattr(manager, 'register_retry'):
        manager.register_retry('fulltext-index', lambda values: index_worker(directory, **{key: values.get(key) for key in ('project', 'rid', 'attachment_id', 'ocr')}))


def location_label(result):
    kind = result.get('locator_kind')
    if kind == 'paragraph':return f"第 {int(result.get('paragraph') or 0) + 1} 段（非页码）"
    if kind in ('page', 'annotation') and result.get('page') is not None:return f"第 {int(result['page']) + 1} 页"
    return '阅读笔记' if kind == 'note' else '书目信息' if kind == 'record' else '批注'


class SearchWindow:
    def __init__(self, parent, directory, project=None, on_open=None, manager=None, *, on_location=None,
                 rid=None, attachment_id=None, query=''):
        self.directory = Path(directory)
        self.project, self.rid, self.attachment_id = project, rid, attachment_id
        self.on_open, self.on_location = on_open, on_location
        self.index = FulltextIndex(directory)
        self.manager = manager or TaskManager(directory)
        self.owns_manager = manager is None
        register_index_tasks(self.manager, directory)
        self.closed = False
        self.tasks = {}
        self.results = []
        self.search_generation = 0
        self.win = tk.Toplevel(parent)
        self.win.title('文内全文查找' if rid else '全文搜索')
        self.win.geometry('1000x700')
        self.win.minsize(760, 560)
        style_dialog(self.win)
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        self.win.bind('<Escape>', lambda _: self.close())
        form = ttk.Frame(self.win, padding=18)
        form.pack(fill='both', expand=True)
        ttk.Label(form, text='文内查找' if rid else '全文搜索', style='Section.TLabel').pack(anchor='w')
        ttk.Label(form, text='本机索引正文、附件、笔记与批注；PDF 显示真实页码，Word / TXT 显示逻辑段落。',
                  style='Muted.TLabel', wraplength=900).pack(anchor='w', pady=(5, 12))
        row = ttk.Frame(form)
        row.pack(fill='x')
        self.query = tk.StringVar(value=query)
        self.query_entry = ttk.Entry(row, textvariable=self.query)
        self.query_entry.pack(side='left', fill='x', expand=True)
        self.query_entry.bind('<Return>', lambda _: self.search())
        ttk.Button(row, text='搜索', style='Accent.TButton', command=self.search).pack(side='left', padx=(8, 0))
        actions = ttk.Frame(form)
        actions.pack(fill='x', pady=10)
        flow_bar(actions)
        ttk.Button(actions, text='建立 / 更新索引', command=self.start_index).pack(side='left')
        ttk.Button(actions, text='识别扫描页（本地 OCR）', command=lambda: self.start_index(True)).pack(side='left', padx=6)
        self.cancel_button = ttk.Button(actions, text='取消任务', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left')
        self.scope = tk.StringVar(value='当前文档' if attachment_id else '当前文献' if rid else '全部文献')
        self.projects = {'全部文献': None}
        if not rid:
            lib = Library(directory)
            try:self.projects.update({item['name']: item['id'] for item in lib.projects()})
            finally:lib.close()
            self.scope.set(next((name for name, pid in self.projects.items() if pid == project), '全部文献'))
            combo = ttk.Combobox(actions, textvariable=self.scope, values=list(self.projects), state='readonly', width=23)
            combo.pack(side='right')
            combo.bind('<<ComboboxSelected>>', lambda _: self.change_scope())
        else:ttk.Label(actions, textvariable=self.scope, style='Muted.TLabel').pack(side='right')
        self.notebook = ttk.Notebook(form)
        self.notebook.pack(fill='both', expand=True)
        result_tab, coverage_tab, ocr_tab = (ttk.Frame(self.notebook) for _ in range(3))
        self.notebook.add(result_tab, text='搜索结果')
        self.notebook.add(coverage_tab, text='索引覆盖')
        self.notebook.add(ocr_tab, text='本地 OCR 设置')
        self.tree = self._tree(result_tab, ('title', 'source', 'location', 'snippet'),
                               ('文献 / 附件', '来源', '位置', '命中内容'), (230, 70, 140, 420))
        self.tree.bind('<Double-1>', lambda _: self.open_selected())
        self.tree.bind('<Return>', lambda _: self.open_selected())
        ttk.Button(result_tab, text='打开选中结果', command=self.open_selected).pack(anchor='e', pady=8)
        self.coverage_tree = self._tree(coverage_tab, ('file', 'status', 'coverage', 'detail'),
                                        ('文件', '状态', '覆盖', '说明'), (240, 100, 180, 330))
        ttk.Label(coverage_tab, text='无可提取文字可能是扫描页或空白页；OCR 结果仅用于搜索，原文件保持原样。',
                  style='Muted.TLabel', wraplength=850).pack(anchor='w', pady=8)
        self._ocr_form(ocr_tab)
        self.status = tk.StringVar(value='先建立索引，再搜索关键词；多个关键词以空格分隔。')
        ttk.Label(form, textvariable=self.status, style='Muted.TLabel', wraplength=900).pack(fill='x', pady=(10, 0))
        self.refresh_coverage()
        self.job = self.win.after(100, self.poll)
        if rid:self.win.after_idle(self.start_index)

    def _tree(self, parent, columns, labels, widths):
        host = ttk.Frame(parent)
        host.pack(fill='both', expand=True)
        tree = ttk.Treeview(host, columns=columns, show='headings', selectmode='browse', height=8)
        for key, label, width in zip(columns, labels, widths):
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=65, stretch=key in ('title', 'snippet', 'file', 'detail'))
        vertical = ttk.Scrollbar(host, command=tree.yview)
        horizontal = ttk.Scrollbar(host, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        host.rowconfigure(0, weight=1);host.columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky='nsew');vertical.grid(row=0, column=1, sticky='ns');horizontal.grid(row=1, column=0, sticky='ew')
        return tree

    def _ocr_form(self, parent):
        form = ttk.Frame(parent, padding=16)
        form.pack(fill='both', expand=True)
        config = self.index.ocr_config()
        self.ocr_executable = tk.StringVar(value=config.get('executable', ''))
        self.ocr_languages = tk.StringVar(value=config.get('languages', 'eng'))
        ttk.Label(form, text='Tesseract 可执行文件（留空时查找本机 PATH）').pack(anchor='w')
        row = ttk.Frame(form);row.pack(fill='x', pady=(6, 12))
        ttk.Entry(row, textvariable=self.ocr_executable).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='选择文件', command=self.choose_ocr).pack(side='left', padx=(8, 0))
        ttk.Label(form, text='语言：eng（英文）、chi_sim+eng（简体中文与英文）；须已安装对应语言包。', wraplength=820).pack(anchor='w')
        ttk.Entry(form, textvariable=self.ocr_languages, width=28).pack(anchor='w', pady=(6, 12))
        ttk.Button(form, text='保存并检查可用性', command=self.check_ocr).pack(anchor='w')
        self.ocr_status = tk.StringVar(value='未检查引擎。软件不会自动安装引擎、下载语言包或上传文献。')
        ttk.Label(form, textvariable=self.ocr_status, style='Muted.TLabel', wraplength=820).pack(fill='x', pady=12)

    def choose_ocr(self):
        path = filedialog.askopenfilename(parent=self.win, title='选择本机 Tesseract', filetypes=[('可执行文件', '*.exe'), ('全部文件', '*')])
        if path:self.ocr_executable.set(path)

    def options(self, ocr=False):
        return dict(project=self.project, rid=self.rid, attachment_id=self.attachment_id, ocr=bool(ocr))

    def change_scope(self):
        self.project = self.projects[self.scope.get()]
        self.refresh_coverage()
        if self.query.get().strip():self.search()

    def start_index(self, ocr=False):
        if self.closed:return
        if any(kind == 'index' for kind, _ in self.tasks.values()):
            self.status.set('当前索引任务仍在运行，可在完成后继续。');return
        try:
            if ocr:self.index.save_ocr_config(self.ocr_executable.get().strip(), self.ocr_languages.get().strip())
            options = self.options(ocr)
            identifier = self.manager.submit('fulltext-index', '本地 OCR 与全文索引' if ocr else '更新全文索引',
                                             index_worker(self.directory, **options), metadata=options)
            self.tasks[identifier] = ('index', None)
            self.cancel_button.configure(state='normal')
            self.status.set('已加入后台任务；可继续阅读。')
        except (ValueError, OSError, RuntimeError) as exc:self.status.set(str(exc))

    def search(self):
        query = self.query.get().strip()
        if not query:self.status.set('请输入要查找的关键词。');return
        self.search_generation += 1
        generation = self.search_generation
        project, rid, attachment = self.project, self.rid, self.attachment_id
        directory = self.directory
        def work(context):
            context.check_cancelled()
            try:return FulltextIndex(directory).search(query, project, rid, attachment, limit=300, cancel=context.cancelled)
            except IndexCancelled:context.check_cancelled();raise
        identifier = self.manager.submit('fulltext-search', '搜索全文', work)
        self.tasks[identifier] = ('search', generation)
        self.status.set('正在搜索已建立的本地索引…')

    def check_ocr(self):
        try:config = self.index.save_ocr_config(self.ocr_executable.get().strip(), self.ocr_languages.get().strip())
        except (ValueError, OSError) as exc:self.ocr_status.set(str(exc));return
        def work(context):
            try:return LocalOCR(**config).probe(context.cancelled)
            except IndexCancelled:context.check_cancelled();raise
        identifier = self.manager.submit('ocr-check', '检查本地 OCR 引擎', work)
        self.tasks[identifier] = ('ocr', None)
        self.ocr_status.set('正在后台检查本地引擎与语言包…')

    def refresh_coverage(self):
        rows = self.index.coverage(self.project, self.rid, self.attachment_id)
        self.coverage_tree.delete(*self.coverage_tree.get_children())
        labels = {'complete': '已完成', 'partial': '部分有文字', 'empty': '无可提取文字', 'missing': '文件缺失',
                  'error': '无法索引', 'pending': '待索引', 'indexing': '正在索引', 'interrupted': '已中断', 'stale': '需更新'}
        for row in rows:
            unit = '页' if row.get('locator_kind') == 'page' else '段'
            coverage = f"{row.get('text_units') or 0} / {row.get('total') or 0} {unit}有文字"
            details = row.get('error') or (f"{row.get('empty_units') or 0} {unit}无可提取文字 · OCR {row.get('ocr_units') or 0} {unit}")
            self.coverage_tree.insert('', 'end', values=(row['label'], labels.get(row['status'], row['status']), coverage, details))

    def open_selected(self):
        selection = self.tree.selection()
        if not selection:return
        result = self.results[int(selection[0])]
        try:
            if self.on_location:self.on_location(dict(result))
            elif self.on_open:self.on_open(result['paper'], result['attachment'], result.get('page') if result['locator_kind'] != 'paragraph' else None)
            else:self.status.set('当前窗口尚未连接阅读器。');return
            self.status.set('已打开：' + location_label(result))
        except (ValueError, OSError) as exc:self.status.set('无法打开：' + str(exc))

    def poll(self):
        if self.closed:return
        for identifier, (kind, generation) in list(self.tasks.items()):
            task = self.manager.get_task(identifier)
            if not task:continue
            if task['status'] in ('queued', 'running'):
                if kind == 'index':self.status.set(task.get('message') or '正在建立索引…')
                continue
            self.tasks.pop(identifier, None)
            if task['status'] != 'succeeded':
                message = task.get('error') or task.get('message') or '任务未完成'
                (self.ocr_status if kind == 'ocr' else self.status).set(message)
                if kind == 'index':self.refresh_coverage()
                continue
            if kind == 'index':
                result = task['result'] or {}
                self.refresh_coverage()
                self.status.set(f"索引完成：更新 {result.get('updated', 0)} 项，复用 {result.get('unchanged', 0)} 项，需处理 {result.get('errors', 0)} 项。请查看索引覆盖。")
                if self.query.get().strip():self.search()
            elif kind == 'search' and generation == self.search_generation:
                self.results = task['result'] or []
                self.tree.delete(*self.tree.get_children())
                for number, result in enumerate(self.results):
                    source = result['source'] + (' · OCR' if result.get('origin') == 'ocr' else '')
                    self.tree.insert('', 'end', iid=str(number), values=(result['title'] + ' / ' + result['label'], source, location_label(result), result['snippet']))
                self.notebook.select(0)
                self.status.set(f'找到 {len(self.results)} 条结果' + ('（最多显示 300 条，请缩小关键词范围）' if len(self.results) == 300 else '；未索引、缺失或无文字的页面不会出现在结果中。'))
            elif kind == 'ocr':self.ocr_status.set('本地 OCR 可用。已安装语言：' + '、'.join(task['result']['languages']))
        self.cancel_button.configure(state='normal' if self.tasks else 'disabled')
        self.job = self.win.after(180, self.poll)

    def cancel(self):
        for identifier in self.tasks:self.manager.cancel(identifier)
        self.status.set('正在取消本窗口任务，已完成的附件索引保留。')

    def close(self):
        if self.closed:return
        self.closed = True
        self.cancel()
        if self.job:
            self.win.after_cancel(self.job);self.job = None
        if self.owns_manager:self.manager.close(wait=False)
        self.win.destroy()
