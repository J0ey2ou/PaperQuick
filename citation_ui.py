"""Explore references and citing papers from a saved paper, without blocking Tk."""
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

from library_core import Library, normalize_doi
import ui_theme as theme


def find_related(*args, **kwargs):
    # Loading on demand keeps the view usable before a network search is requested.
    from citation_tracking import find_related as lookup
    return lookup(*args, **kwargs)


def _title_key(value):
    return re.sub(r'[^\w]+', '', str(value).casefold())


def _existing(item, records):
    doi = normalize_doi(item.get('doi', ''))
    title = _title_key(item.get('title', ''))
    for record in records:
        other_doi = normalize_doi(record.get('doi', ''))
        if doi and other_doi:
            if doi == other_doi:
                return record
        elif title and title == _title_key(record.get('title', '')):
            return record
    return None


class CitationView:
    """Notebook content. Call close() before its containing dialog is destroyed."""

    def __init__(self, parent, directory, on_query=None, on_collected=None):
        self.directory = Path(directory)
        self.on_query = on_query
        self.on_collected = on_collected
        self.frame = ttk.Frame(parent, padding=(4, 12, 4, 0))
        self.closed = False
        self.busy = False
        self.events = queue.Queue()
        self.poll_id = None
        self.records = []
        self.projects = []
        self.items = []
        self.seed_rows = {}
        self.last_search_seed = None
        self._default_target = ''
        self.scope = tk.StringVar(value='全部课题')
        self.search = tk.StringVar()
        self.seed = tk.StringVar()
        self.direction = tk.StringVar(value='both')
        self.result_limit = tk.StringVar(value='50')
        self.target_project = tk.StringVar()
        self.status = tk.StringVar(value='选一篇已收藏的文献，继续探索它的参考文献与后续研究。')
        self.result_heading = tk.StringVar(value='等待探索')

        ttk.Label(self.frame, text='从一篇文献，发现更多相关研究', style='Section.TLabel').pack(anchor='w')
        ttk.Label(self.frame, text='联网查找它引用的文献，以及引用它的研究。已收藏的文献会自动略过。',
                  style='Muted.TLabel').pack(anchor='w', pady=(5, 14))
        filters = ttk.Frame(self.frame)
        filters.pack(fill='x')
        ttk.Label(filters, text='从课题中选择').pack(side='left', padx=(0, 8))
        self.project_combo = ttk.Combobox(filters, textvariable=self.scope, state='readonly', width=19)
        self.project_combo.pack(side='left')
        self.project_combo.bind('<<ComboboxSelected>>', lambda _: self._seed_options())
        ttk.Label(filters, text='查找文献').pack(side='left', padx=(18, 8))
        self.search_entry = ttk.Entry(filters, textvariable=self.search)
        self.search_entry.pack(side='left', fill='x', expand=True)
        self.search.trace_add('write', lambda *_: self._seed_options())

        seeds = ttk.Frame(self.frame)
        seeds.pack(fill='x', pady=(9, 0))
        ttk.Label(seeds, text='探索起点').pack(side='left', padx=(0, 18))
        self.seed_combo = ttk.Combobox(seeds, textvariable=self.seed, state='readonly')
        self.seed_combo.pack(side='left', fill='x', expand=True)
        self.seed_combo.bind('<<ComboboxSelected>>', lambda _: self._seed_changed())
        self.remove_seed_button = ttk.Button(seeds, text='删除错误导入', command=self.remove_seed)
        self.remove_seed_button.pack(side='right', padx=(8, 0))
        self.restore_button = ttk.Button(seeds, text='恢复最近删除', command=self.restore_removed)
        self.restore_button.pack(side='right', padx=(8, 0))

        actions = ttk.Frame(self.frame)
        actions.pack(fill='x', pady=(9, 14))
        self.direction_buttons = []
        for title, value in (('两个方向', 'both'), ('它引用的', 'reference'), ('引用它的', 'citing')):
            button = ttk.Radiobutton(actions, text=title, value=value, variable=self.direction)
            button.pack(side='left', padx=(0, 16))
            self.direction_buttons.append(button)
        ttk.Label(actions, text='最多显示').pack(side='left', padx=(0, 6))
        self.limit_combo = ttk.Combobox(actions, textvariable=self.result_limit,
                                        values=('50', '100', '200'), state='readonly', width=4)
        self.limit_combo.pack(side='left')
        self.find_button = ttk.Button(actions, text='查找关联文献', style='Accent.TButton', command=self.find)
        self.find_button.pack(side='right')
        self.progress = ttk.Progressbar(actions, mode='indeterminate', length=100)
        self.progress.pack(side='right', padx=12)

        ttk.Label(self.frame, textvariable=self.result_heading, style='Eyebrow.TLabel').pack(anchor='w', pady=(0, 7))
        body = ttk.Panedwindow(self.frame, orient='vertical')
        body.pack(fill='both', expand=True)
        table = ttk.Frame(body)
        body.add(table, weight=3)
        self.tree = ttk.Treeview(table, columns=('relation', 'year', 'title'),
                                 show='headings', selectmode='browse', height=2)
        for key, title, width in (('relation', '关联方向', 100), ('year', '年份', 66), ('title', '文献标题', 500)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=55, stretch=key == 'title')
        scrollbar = ttk.Scrollbar(table, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self._detail)
        self.tree.bind('<Double-1>', lambda _: self.query_selected())
        self.result_menu = tk.Menu(self.tree, tearoff=False)
        self.result_menu.add_command(label='查找原文', command=self.query_selected)
        self.result_menu.add_command(label='收藏文献', command=self.collect_selected)
        self.result_menu.add_command(label='移除这条错误结果', command=self.remove_result)
        self.tree.bind('<Button-3>', self.result_context)
        detail_frame = ttk.Frame(body, padding=(0, 10, 0, 0))
        body.add(detail_frame, weight=2)
        self.detail = tk.Text(detail_frame, height=2, wrap='word', bg=theme.PANEL, fg=theme.FG,
                              relief='flat', padx=14, pady=12, font=(theme.FONT, 10), state='disabled')
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.detail.yview)
        detail_scroll.pack(side='right', fill='y')
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.pack(fill='both', expand=True)
        self._set_detail('选中文献后，可以查看摘要、查找原文，或先收藏到课题。')

        footer = ttk.Frame(self.frame)
        footer.pack(side='bottom', fill='x', pady=(12, 8), before=body)
        self.query_button = ttk.Button(footer, text='查找原文', command=self.query_selected, state='disabled')
        self.query_button.pack(side='left')
        ttk.Label(footer, text='收藏到').pack(side='left', padx=(16, 8))
        self.target_combo = ttk.Combobox(footer, textvariable=self.target_project, width=23)
        self.target_combo.pack(side='left', fill='x', expand=True)
        self.collect_button = ttk.Button(footer, text='收藏文献', command=self.collect_selected, state='disabled')
        self.collect_button.pack(side='left', padx=(8, 0))
        self.status_label = ttk.Label(self.frame, textvariable=self.status, style='Muted.TLabel', wraplength=780)
        self.status_label.pack(side='bottom', fill='x', before=footer)
        self.frame.bind('<Configure>', lambda e: self.status_label.configure(wraplength=max(320, e.width-12)))
        self.frame.bind('<Destroy>', self._destroyed, add='+')
        self.refresh()

    def refresh(self):
        if self.closed or self.busy:
            return
        lib = Library(self.directory)
        try:
            self.records = lib.records()
            self.projects = lib.projects()
        finally:
            lib.close()
        names = [project['name'] for project in self.projects]
        self.project_combo.configure(values=['全部课题'] + names)
        self.target_combo.configure(values=names)
        if self.scope.get() not in ['全部课题'] + names:
            self.scope.set('全部课题')
        self._seed_options()
        self.items = [item for item in self.items if not _existing(item, self.records)]
        self._render_results()
        if not self.records:
            self.status.set('先在「文献分类」收藏一篇文献，再从这里发现相关研究。')

    def _seed_options(self):
        if self.closed:
            return
        selected_id = self.seed_rows.get(self.seed.get())
        pid = next((project['id'] for project in self.projects if project['name'] == self.scope.get()), None)
        query = self.search.get().casefold().strip()
        self.seed_rows = {}
        for record in self.records:
            if pid and pid not in record.get('projects', []):
                continue
            if query and query not in (str(record.get('title', '')) + ' ' + str(record.get('doi', ''))).casefold():
                continue
            label = str(record.get('title') or '未命名文献')
            if record.get('year'):
                label += ' · ' + str(record['year'])
            if label in self.seed_rows:
                label += ' · ' + record['id'][:6]
            self.seed_rows[label] = record['id']
        self.seed_combo.configure(values=list(self.seed_rows))
        selected = next((label for label, rid in self.seed_rows.items() if rid == selected_id), None)
        self.seed.set(selected or next(iter(self.seed_rows), ''))
        self.find_button.configure(state='normal' if self.seed_rows and not self.busy else 'disabled')
        self.remove_seed_button.configure(state='normal' if self.seed_rows and not self.busy else 'disabled')
        self._seed_changed()

    def _seed_record(self):
        rid = self.seed_rows.get(self.seed.get())
        return next((record for record in self.records if record['id'] == rid), None)

    def _seed_changed(self):
        record = self._seed_record()
        if record and self.target_project.get() in ('', self._default_target):
            project = next((p for p in self.projects if p['id'] == record.get('primary_project')), None)
            if project:
                self.target_project.set(project['name'])
                self._default_target = project['name']

    def _set_busy(self, busy):
        self.busy = busy
        self.remove_seed_button.configure(state='disabled' if busy or not self.seed_rows else 'normal')
        self.restore_button.configure(state='disabled' if busy else 'normal')
        self.find_button.configure(state='disabled' if busy or not self.seed_rows else 'normal')
        self.project_combo.configure(state='disabled' if busy else 'readonly')
        self.seed_combo.configure(state='disabled' if busy else 'readonly')
        self.limit_combo.configure(state='disabled' if busy else 'readonly')
        self.search_entry.configure(state='disabled' if busy else 'normal')
        for button in self.direction_buttons:
            button.configure(state='disabled' if busy else 'normal')
        if busy:
            self.progress.start(16)
        else:
            self.progress.stop()

    def find(self):
        if self.closed or self.busy:
            return
        seed = self._seed_record()
        if not seed:
            self.status.set('请先选择一篇已收藏的文献。')
            return
        self.last_search_seed = dict(seed)
        records, direction = list(self.records), self.direction.get()
        limit = int(self.result_limit.get()) if self.result_limit.get() in ('50', '100', '200') else 50
        self._set_busy(True)
        self.status.set('正在查找引用关系，请稍候。找到后会自动排除已收藏的文献。')
        self.result_heading.set('正在探索相关研究')
        def work():
            try:
                result = find_related(dict(seed), records, direction=direction, limit=limit)
                self.events.put(('ok', result))
            except Exception:
                self.events.put(('error', None))
        threading.Thread(target=work, daemon=True).start()
        self.poll_id = self.frame.after(100, self._poll)

    def _poll(self):
        self.poll_id = None
        if self.closed:
            return
        try:
            kind, result = self.events.get_nowait()
        except queue.Empty:
            self.poll_id = self.frame.after(100, self._poll)
            return
        self._set_busy(False)
        if kind == 'error':
            self.result_heading.set('暂时未能完成查找')
            self.status.set('暂时连接不上文献服务。请检查网络，稍后再试；之前的结果仍会保留。')
            return
        lib = Library(self.directory)
        try:
            self.records = lib.records()
        finally:
            lib.close()
        self.items = [dict(item) for item in result.get('items', [])
                      if item.get('title') and not _existing(item, self.records)]
        self._render_results()
        message = result.get('message', '')
        if result.get('truncated'):
            message += ' 可以增加显示数量，或切换到单一方向继续查找。'
        self.status.set(message.strip() or (f'找到 {len(self.items)} 篇尚未收藏的文献。' if self.items else '暂时没有找到尚未收藏的关联文献。'))

    def _render_results(self):
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.items):
            self.tree.insert('', 'end', iid=str(index), values=(self._relation(item), item.get('year', ''), item.get('title', '')))
        self.result_heading.set(f'{len(self.items)} 篇待探索文献' if self.items else '尚无待探索文献')
        if self.items:
            self.tree.selection_set('0')
            self._detail()
        else:
            self.query_button.configure(state='disabled')
            self.collect_button.configure(state='disabled')
            self._set_detail('还没有待探索的文献。选择探索起点，再点「查找关联文献」。')

    @staticmethod
    def _relation(item):
        if set(item.get('relations') or ()) >= {'reference', 'citing'}:
            return '双向引用'
        return {'reference': '它引用的', 'citing': '引用它的'}.get(item.get('relation'), '相关文献')

    def _selected(self):
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return self.items[int(selection[0])]
        except (ValueError, IndexError):
            return None

    def _set_detail(self, value):
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', value)
        self.detail.configure(state='disabled')

    def _detail(self, _=None):
        item = self._selected()
        if not item:
            return
        seed_title = item.get('seed_title') or (self.last_search_seed or {}).get('title', '')
        source = item.get('source') or 'Europe PMC'
        lines = [item.get('title', ''), '', self._relation(item) + ' · 来源：' + str(source)]
        if seed_title:
            lines.append('探索起点：' + str(seed_title))
        details = ' · '.join(str(item.get(key)) for key in ('year', 'authors', 'venue') if item.get(key))
        if details:
            lines.extend(['', details])
        if item.get('doi'):
            lines.append('DOI：' + str(item['doi']))
        lines.extend(['', item.get('abstract') or '暂未提供摘要，可以查找原文了解这篇研究。'])
        self._set_detail('\n'.join(lines))
        self.query_button.configure(state='normal')
        self.collect_button.configure(state='normal')

    def query_selected(self):
        item = self._selected()
        if not item:
            self.status.set('请先选择一篇待探索文献。')
            return
        query = item.get('doi') or item.get('title', '')
        if self.on_query:
            self.on_query(query)
        else:
            from urllib.parse import quote
            url = 'https://doi.org/' + quote(normalize_doi(item['doi']), safe='/') if item.get('doi') else item.get('url')
            if not url or not str(url).startswith(('https://', 'http://')):
                url = 'https://europepmc.org/search?query=' + quote(query)
            webbrowser.open(url)

    def collect_selected(self):
        item = self._selected()
        if not item:
            self.status.set('请先选择一篇待探索文献。')
            return
        name = self.target_project.get().strip()
        if not name:
            self.status.set('请选择一个收藏课题，也可以输入新课题名称。')
            self.target_combo.focus_set()
            return
        lib = Library(self.directory)
        try:
            pid = lib.create_project(name)
            existing = _existing(item, lib.records())
            if existing:
                lib.assign(existing['id'], pid)
            else:
                metadata = {key: item[key] for key in ('title', 'doi', 'year', 'authors', 'venue', 'abstract', 'url', 'links', 'europepmc_id') if key in item}
                metadata['discovered_from'] = {'id': item.get('seed_id', ''), 'title': item.get('seed_title', ''), 'doi': item.get('seed_doi', ''), 'relation': item.get('relation', ''), 'relations': item.get('relations', []), 'source': item.get('source', 'Europe PMC')}
                lib.save(metadata, project=pid)
        except Exception:
            self.status.set('这次未能保存文献，请稍后再试。')
            return
        finally:
            lib.close()
        self.refresh()
        self.status.set(f'已收藏到「{name}」。可以继续查找原文，再下载归档。')
        if self.on_collected:
            self.on_collected()

    def result_context(self, event):
        row = self.tree.identify_row(event.y)
        if not row or self.busy:return
        self.tree.selection_set(row);self._detail()
        try:self.result_menu.tk_popup(event.x_root, event.y_root)
        finally:self.result_menu.grab_release()

    def remove_result(self):
        item = self._selected()
        if self.busy or item is None:return
        self.items.remove(item);self._render_results()
        self.status.set('已从本次结果中移除这条文献。')

    def remove_seed(self):
        record = self._seed_record()
        if self.busy or not record:return
        if not messagebox.askyesno('删除错误导入', '将《'+record['title']+'》移出文献库？原文件保留，可通过“恢复最近删除”找回。', parent=self.frame):return
        before = getattr(self, 'before_remove', None)
        if before and before([record['id']]) is False:
            self.status.set('请先完成正文或附件中的保存，再删除文献。');return
        lib = Library(self.directory)
        try:lib.remove_papers([record['id']])
        finally:lib.close()
        self.refresh();self.status.set('错误导入已删除，可恢复最近删除。')
        if self.on_collected:self.on_collected()

    def restore_removed(self):
        if self.busy:return
        lib = Library(self.directory)
        try:lib.restore_removed()
        except ValueError as exc:self.status.set(str(exc));return
        finally:lib.close()
        self.refresh();self.status.set('已恢复最近删除的文献。')
        if self.on_collected:self.on_collected()

    def _destroyed(self, event):
        if event.widget == self.frame:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.poll_id:
            try:
                self.frame.after_cancel(self.poll_id)
            except tk.TclError:
                pass
            self.poll_id = None
        try:
            self.progress.stop()
        except tk.TclError:
            pass
