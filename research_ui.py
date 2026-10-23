"""Research workspace: local evidence, matrix, outline and screening editors."""
from pathlib import Path
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from research_store import ResearchStore, STAGES, DEFAULT_COLUMNS, source_location, write_export
from ui_theme import FONT, style_dialog
from ui_widgets import scrollable_page, flow_bar

STANCE_LABELS = {'支持': 'support', '反对': 'oppose', '混合': 'mixed', '中性 / 描述': 'neutral'}
DECISION_LABELS = {'纳入': 'include', '排除': 'exclude', '待定': 'uncertain'}
STAGE_LABELS = {'题录 / 摘要': 'title_abstract', '全文': 'full_text'}


def _label(mapping, value):
    return next((k for k, v in mapping.items() if v == value), value or '待筛选')


def _text(parent, height=5, readonly=False):
    frame = ttk.Frame(parent); frame.pack(fill='both', expand=True, pady=(3, 8))
    area = tk.Text(frame, height=height, wrap='word', font=(FONT, 10), undo=True)
    scroll = ttk.Scrollbar(frame, command=area.yview); scroll.pack(side='right', fill='y')
    area.configure(yscrollcommand=scroll.set); area.pack(fill='both', expand=True)
    if readonly:
        area.configure(state='disabled')
    return area


def _write(widget, value):
    state = widget.cget('state'); widget.configure(state='normal')
    widget.delete('1.0', 'end'); widget.insert('1.0', value); widget.edit_modified(False)
    widget.configure(state=state)


def _tree(parent, columns, height=10):
    frame = ttk.Frame(parent); frame.pack(fill='both', expand=True)
    tree = ttk.Treeview(frame, columns=tuple(columns), show='headings', selectmode='browse', height=height)
    for key, title in columns.items():
        tree.heading(key, text=title); tree.column(key, width=170, minwidth=90)
    vertical = ttk.Scrollbar(frame, command=tree.yview); vertical.pack(side='right', fill='y')
    horizontal = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview); horizontal.pack(side='bottom', fill='x')
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set); tree.pack(fill='both', expand=True)
    return tree


class Editor:
    """Explicit save/cancel editor; every Tk control remains owned by its dialog."""
    def __init__(self, owner, title, width=720, height=660):
        self.owner = owner; self.win = tk.Toplevel(owner.win); self.win.title(title)
        style_dialog(self.win); self.win.geometry(f'{width}x{height}'); self.win.minsize(520, 420)
        self.win.transient(owner.win); self.closed = False; self.dirty = False
        self.win.protocol('WM_DELETE_WINDOW', self.cancel)
        self.win.bind('<Escape>', lambda _: self.cancel())
        host, self.form = scrollable_page(self.win, padding=18); host.pack(fill='both', expand=True)
        self.buttons = ttk.Frame(self.win, padding=(18, 8)); self.buttons.pack(fill='x')
        self.feedback = tk.StringVar(master=self.win)
        ttk.Label(self.buttons, textvariable=self.feedback, style='Muted.TLabel', wraplength=480).pack(fill='x')
        ttk.Button(self.buttons, text='取消', command=self.cancel).pack(side='left', pady=5)
        self.save_button = ttk.Button(self.buttons, text='保存', style='Accent.TButton'); self.save_button.pack(side='right', pady=5)
        owner.editors.append(self)

    def entry(self, label, value='', values=None):
        ttk.Label(self.form, text=label).pack(anchor='w', pady=(7, 3))
        variable = tk.StringVar(master=self.win, value=value)
        widget = ttk.Entry(self.form, textvariable=variable) if values is None else ttk.Combobox(self.form, textvariable=variable, values=values, state='readonly')
        widget.pack(fill='x'); variable.trace_add('write', lambda *_: self.changed())
        return variable, widget

    def text(self, label, value='', height=4):
        ttk.Label(self.form, text=label).pack(anchor='w', pady=(8, 2))
        area = _text(self.form, height=height); _write(area, value)
        def changed(_):
            if area.edit_modified():
                self.changed(); area.edit_modified(False)
        area.bind('<<Modified>>', changed)
        return area

    def evidence(self, cards, selected=()):
        ttk.Label(self.form, text='关联证据（Ctrl / Shift 可多选；空选表示尚无支持证据）', style='Muted.TLabel', wraplength=620).pack(anchor='w', pady=(10, 4))
        frame = ttk.Frame(self.form); frame.pack(fill='both', expand=True)
        box = tk.Listbox(frame, height=7, selectmode='extended', exportselection=False, font=(FONT, 10))
        scroll = ttk.Scrollbar(frame, command=box.yview); scroll.pack(side='right', fill='y')
        box.configure(yscrollcommand=scroll.set); box.pack(fill='both', expand=True)
        for index, card in enumerate(cards):
            box.insert('end', f"{card['id'][:8]} · {card['claim'] or card['quote'][:60] or card['interpretation'][:60]} · {'已核对' if card['verified'] else '待核对'}")
            if card['id'] in selected:
                box.selection_set(index)
        box.bind('<<ListboxSelect>>', lambda _: self.changed())
        return box, lambda: [cards[i]['id'] for i in box.curselection()]

    def changed(self):
        self.dirty = True

    def cancel(self):
        if self.dirty and not messagebox.askyesno('放弃修改', '这个编辑窗口还有未保存的修改，确定放弃吗？', parent=self.win):
            return False
        self.destroy(); return True

    def destroy(self):
        if not self.closed:
            self.closed = True; self.win.destroy()
            if self in self.owner.editors:
                self.owner.editors.remove(self)

    def commit(self, action):
        try:
            result = action()
        except Exception as exc:
            self.feedback.set(str(exc)); return None
        self.dirty = False; self.owner.refresh(); self.destroy(); return result


class ResearchWindow:
    def __init__(self, parent, directory, project=None, on_open=None, on_location=None):
        self.directory = Path(directory); self.store = ResearchStore(directory)
        self.on_open = on_open; self.closed = False; self.editors = []
        self.on_location = on_location
        self.audit_running = False; self.audit_events = queue.Queue(); self.audit_job = None
        self.win = tk.Toplevel(parent); self.win.title('研究整理与输出'); style_dialog(self.win)
        self.win.geometry('1160x780'); self.win.minsize(820, 580); self.win.protocol('WM_DELETE_WINDOW', self.close)
        header = ttk.Frame(self.win, padding=(20, 15)); header.pack(fill='x')
        ttk.Label(header, text='研究整理与输出', font=(FONT, 19, 'bold')).pack(side='left')
        self.project_value = tk.StringVar(master=self.win)
        self.project_box = ttk.Combobox(header, textvariable=self.project_value, state='readonly', width=30); self.project_box.pack(side='right')
        self.project_box.bind('<<ComboboxSelected>>', lambda _: self.refresh())
        self.projects = {p['name']: p['id'] for p in self.store.projects()}
        self.project_box.configure(values=list(self.projects))
        self.project_value.set(next((name for name, pid in self.projects.items() if pid == project), next(iter(self.projects), '')))
        self.tabs = ttk.Notebook(self.win); self.tabs.pack(fill='both', expand=True, padx=20)
        self.pages = {}
        for key, label in (('cards', '证据卡'), ('matrix', '比较矩阵'), ('outline', '综述提纲'), ('screening', '文献筛选'), ('audit', '引用审计')):
            page = ttk.Frame(self.tabs, padding=12); self.tabs.add(page, text=label); self.pages[key] = page
        self.status = tk.StringVar(master=self.win, value='研究资料保存在本地文献库。导出前可在“引用审计”核查来源。')
        ttk.Label(self.win, textvariable=self.status, style='Muted.TLabel', padding=(20, 10), wraplength=1050).pack(fill='x')
        self._build_cards(); self._build_matrix(); self._build_outline(); self._build_screening(); self._build_audit(); self.refresh()

    @property
    def project(self):
        return self.projects.get(self.project_value.get())

    def _bar(self, parent, actions):
        bar = ttk.Frame(parent); bar.pack(fill='x', pady=(0, 8))
        for label, action in actions:
            ttk.Button(bar, text=label, command=action, style='Compact.TButton').pack(side='left', padx=(0, 5))
        flow_bar(bar); return bar

    def _selected(self, tree):
        selected = tree.selection()
        if not selected:
            self.status.set('请先选择一项。'); return None
        return selected[0]

    def _error(self, action):
        try:
            return action()
        except Exception as exc:
            self.status.set('操作未完成：'+str(exc)); return None

    def _build_cards(self):
        page = self.pages['cards']
        self._bar(page, [('新建证据卡', self.new_card), ('编辑', self.edit_card), ('删除', self.delete_card), ('回到来源', self.open_source)])
        ttk.Label(page, text='原文摘录与自己的解释分开保存；“已核对”需要你实际查看原文。页码采用阅读器页序。', style='Muted.TLabel', wraplength=1000).pack(anchor='w', pady=(0, 8))
        self.card_tree = _tree(page, {'claim': '论点 / 摘录', 'paper': '来源文献', 'page': '来源位置', 'stance': '立场', 'verified': '原文核对'}, height=9)
        self.card_tree.bind('<<TreeviewSelect>>', lambda _: self.card_detail())
        self.card_tree.bind('<Double-1>', lambda _: self.edit_card())
        self.card_preview = _text(page, height=6, readonly=True)

    def card_detail(self):
        selected = self.card_tree.selection()
        if not selected:
            _write(self.card_preview, '新建证据卡，记录一段原文及其对研究问题的意义。'); return
        card = self.card_rows[selected[0]]
        _write(self.card_preview, '原文摘录\n'+card['quote']+'\n\n我的解释\n'+card['interpretation']+'\n\n研究论点\n'+card['claim'])

    def new_card(self, data=None):
        return self.card_editor(dict(data or {}))

    def edit_card(self):
        ident = self._selected(self.card_tree)
        if ident:
            return self.card_editor(self.store.card(ident))

    def card_editor(self, card):
        papers = self.store.papers(self.project)
        if not papers:
            self.status.set('此课题还没有文献，请先导入或分配文献。'); return
        dialog = Editor(self, '编辑证据卡' if card.get('id') else '新建证据卡', height=780)
        names = {p['title']+' · '+p['id'][:8]: p['id'] for p in papers}
        if card.get('paper') and card['paper'] not in names.values():
            names['[来源已缺失或移出课题] '+card['paper'][:8]] = card['paper']
        source_name = next((name for name, ident in names.items() if ident == card.get('paper')), next(iter(names)))
        paper, paper_box = dialog.entry('来源文献', source_name, list(names))
        attachment, attachment_box = dialog.entry('具体附件', '', [])
        attachments = {}
        def load_attachments(_=None):
            attachments.clear(); attachments['未关联附件'] = ''
            for item in self.store.attachments(names[paper.get()]):
                attachments[(item.get('label') or Path(item['path']).name or item.get('url', '链接'))+' · '+item['id'][:8]] = item['id']
            attachment_box.configure(values=list(attachments))
            attachment.set(next((name for name, ident in attachments.items() if ident == card.get('attachment')), '未关联附件'))
        paper_box.bind('<<ComboboxSelected>>', load_attachments); load_attachments()
        locator, _ = dialog.entry('来源位置类型', '逻辑段落' if card.get('locator_kind') == 'paragraph' else '阅读器页码', ['阅读器页码', '逻辑段落'])
        initial_position = card.get('paragraph') if card.get('locator_kind') == 'paragraph' else card.get('page')
        page, _ = dialog.entry('页码 / 逻辑段落编号（从 1 开始；未知可留空）', str(initial_position+1) if initial_position is not None else '')
        stance, _ = dialog.entry('该证据与论点的关系', _label(STANCE_LABELS, card.get('stance', 'neutral')), list(STANCE_LABELS))
        texts = {key: dialog.text(label, card.get(key, ''), height=4) for key, label in [('quote', '原文摘录'), ('interpretation', '我的解释'), ('claim', '研究论点')]}
        verified = tk.BooleanVar(master=dialog.win, value=card.get('verified', False) and not self.store._source_issues(card))
        ttk.Checkbutton(dialog.form, text='我已逐字核对原文及来源位置', variable=verified, command=dialog.changed).pack(anchor='w', pady=10)
        def save():
            raw = page.get().strip()
            if raw and (not raw.isdecimal() or int(raw) < 1):
                raise ValueError('请输入大于 0 的阅读器页码，或留空。')
            values = {key: widget.get('1.0', 'end-1c') for key, widget in texts.items()}
            values.update(project=card.get('project') or self.project, paper=names[paper.get()], attachment=attachments[attachment.get()],
                          page=int(raw)-1 if raw else None, rect=card.get('rect'), stance=STANCE_LABELS[stance.get()], verified=verified.get())
            values['locator_kind'] = 'paragraph' if locator.get() == '逻辑段落' else 'page'
            if values['locator_kind'] == 'paragraph':
                values['paragraph'] = values.pop('page'); values['page'] = None
            if card.get('id'):
                values.update(id=card['id'], revision=card['revision'])
            return self.store.save_card(values)
        dialog.fields = dict(paper=paper, attachment=attachment, page=page, locator=locator, stance=stance, verified=verified)
        dialog.texts = texts; dialog.save = lambda: dialog.commit(save); dialog.save_button.configure(command=dialog.save); dialog.dirty = False
        return dialog

    def delete_card(self):
        ident = self._selected(self.card_tree)
        if ident and messagebox.askyesno('删除证据卡', '删除后会移除矩阵和提纲中的此证据引用，原文及操作记录会保留。继续吗？', parent=self.win):
            self._error(lambda: self.store.delete_card(ident)); self.refresh()

    def open_source(self, card=None):
        if card is None:
            ident = self._selected(self.card_tree)
            if not ident:
                return
            card = self.store.card(ident)
        problems = [message for code, message in self.store._source_issues(card) if code in ('missing_paper', 'missing_attachment', 'wrong_attachment', 'missing_file')]
        if problems:
            self.status.set('无法回源：'+'；'.join(problems)); return
        if card.get('locator_kind') == 'paragraph' and self.on_location:
            self.on_location(dict(card, snippet=card['quote'], query=''))
        elif self.on_open:
            self.on_open(card['paper'], card['attachment'] or None, card['page'] or 0)
        else:
            self.status.set('此窗口未连接阅读器。来源文献：'+self.paper_names.get(card['paper'], card['paper']))

    def _build_matrix(self):
        page = self.pages['matrix']
        self._bar(page, [('新建矩阵', self.new_matrix), ('名称与比较列', self.edit_matrix), ('删除矩阵', self.delete_matrix), ('编辑所选单元格', self.edit_cell), ('导出 CSV', self.export_matrix)])
        self.matrix_value = tk.StringVar(master=self.win)
        self.matrix_box = ttk.Combobox(page, textvariable=self.matrix_value, state='readonly'); self.matrix_box.pack(fill='x', pady=(0, 8))
        self.matrix_box.bind('<<ComboboxSelected>>', lambda _: self.refresh_matrix())
        ttk.Label(page, text='双击比较列的单元格填写内容并关联该篇文献的证据；CSV 可用 Excel 打开。', style='Muted.TLabel', wraplength=1000).pack(anchor='w', pady=(0, 8))
        self.matrix_tree = _tree(page, {'paper': '文献'})
        self.matrix_tree.bind('<Double-1>', self.edit_cell)

    def current_matrix(self):
        return self.matrix_names.get(self.matrix_value.get())

    def new_matrix(self):
        return self.matrix_editor({})

    def edit_matrix(self):
        ident = self.current_matrix()
        if ident:
            return self.matrix_editor(self.store.matrix(ident))
        self.status.set('请先新建比较矩阵。')

    def matrix_editor(self, matrix):
        dialog = Editor(self, '比较矩阵设置', height=580)
        name, _ = dialog.entry('矩阵名称', matrix.get('name', '文献比较'))
        columns = dialog.text('比较列（每行一列；修改名称保留该位置已有内容）', '\n'.join(c['title'] for c in matrix.get('columns', [])) or '\n'.join(DEFAULT_COLUMNS), height=9)
        def save():
            labels = [line.strip() for line in columns.get('1.0', 'end-1c').splitlines() if line.strip()]
            old_columns = matrix.get('columns', [])
            values = [({'id': old_columns[i]['id'], 'title': title} if i < len(old_columns) else title) for i, title in enumerate(labels)]
            data = {'project': matrix.get('project') or self.project, 'name': name.get(), 'columns': values}
            if matrix.get('id'):
                data['id'] = matrix['id']
            result = self.store.save_matrix(data); self._preferred_matrix = result['id']; return result
        dialog.fields = {'name': name}; dialog.texts = {'columns': columns}; dialog.save = lambda: dialog.commit(save)
        dialog.save_button.configure(command=dialog.save); dialog.dirty = False; return dialog

    def refresh_matrix(self):
        ident = self.current_matrix(); self.matrix_tree.delete(*self.matrix_tree.get_children())
        if not ident:
            self.matrix_tree.configure(columns=('paper',)); self.matrix_tree.heading('paper', text='请先新建比较矩阵'); return
        matrix = self.store.matrix(ident); columns = ['paper']+[c['id'] for c in matrix['columns']]
        self.matrix_tree.configure(columns=columns)
        for key, title in [('paper', '文献')]+[(c['id'], c['title']) for c in matrix['columns']]:
            self.matrix_tree.heading(key, text=title); self.matrix_tree.column(key, width=230 if key == 'paper' else 190, minwidth=100, stretch=False)
        cells = {(c['paper'], c['column']): c for c in self.store.cells(ident)}
        papers = {p['id']: p for p in self.store.papers(matrix['project'])}
        for paper, _ in cells:
            papers.setdefault(paper, {'id': paper, 'title': '[来源缺失] '+paper[:8]})
        for paper in papers.values():
            values = [paper['title']]
            for column in matrix['columns']:
                cell = cells.get((paper['id'], column['id']), {})
                values.append(cell.get('text', '')[:160]+(f" 〔{len(cell['evidence'])} 条证据〕" if cell.get('evidence') else ''))
            self.matrix_tree.insert('', 'end', iid=paper['id'], values=values)

    def edit_cell(self, event=None):
        ident = self.current_matrix()
        if not ident:
            self.status.set('请先新建比较矩阵。'); return
        paper = self.matrix_tree.identify_row(event.y) if event else self._selected(self.matrix_tree)
        if not paper:
            return
        matrix = self.store.matrix(ident); initial_column = None
        if event:
            column = int(self.matrix_tree.identify_column(event.x)[1:])-1
            if column <= 0:
                return
            initial_column = matrix['columns'][column-1]['id']
        dialog = Editor(self, '编辑比较单元格', height=680)
        names = {c['title']+' · '+c['id'][:6]: c['id'] for c in matrix['columns']}
        selected, box = dialog.entry('比较维度', next((name for name, cid in names.items() if cid == initial_column), next(iter(names))), list(names))
        body = dialog.text('比较内容', height=7)
        cards = [c for c in self.store.cards(matrix['project']) if c['paper'] == paper]
        evidence_box, evidence = dialog.evidence(cards)
        cells = {c['column']: c for c in self.store.cells(ident) if c['paper'] == paper}
        def load(_=None):
            cell = cells.get(names[selected.get()], {}); _write(body, cell.get('text', '')); evidence_box.selection_clear(0, 'end')
            for i, card in enumerate(cards):
                if card['id'] in cell.get('evidence', []):
                    evidence_box.selection_set(i)
            dialog.dirty = False
        previous = [selected.get()]
        def switch(_):
            if dialog.dirty and not messagebox.askyesno('放弃当前修改', '切换维度会放弃这个单元格尚未保存的修改。继续吗？', parent=dialog.win):
                selected.set(previous[0]); return
            previous[0] = selected.get(); load()
        box.bind('<<ComboboxSelected>>', switch); load()
        dialog.save = lambda: dialog.commit(lambda: self.store.save_cell(ident, paper, names[selected.get()], body.get('1.0', 'end-1c'), evidence()))
        dialog.save_button.configure(command=dialog.save)
        ttk.Button(dialog.buttons, text='清空单元格', command=lambda: dialog.commit(lambda: self.store.delete_cell(ident, paper, names[selected.get()])) if messagebox.askyesno('清空单元格', '清空比较内容及证据引用？证据卡仍会保留。', parent=dialog.win) else None).pack(side='left', padx=8)
        dialog.fields = {'column': selected}; dialog.texts = {'body': body}; dialog.evidence_box = evidence_box
        return dialog

    def delete_matrix(self):
        ident = self.current_matrix()
        if ident and messagebox.askyesno('删除矩阵', '删除这个矩阵及其单元格？原文和证据卡会保留。', parent=self.win):
            self._error(lambda: self.store.delete_matrix(ident)); self.refresh()

    def _build_outline(self):
        page = self.pages['outline']
        self._bar(page, [('新增小节', self.new_section), ('编辑小节', self.edit_section), ('删除小节', self.delete_section), ('导出 Markdown', lambda: self.export_outline('md')), ('导出 Word', lambda: self.export_outline('docx'))])
        self.section_tree = _tree(page, {'position': '顺序', 'title': '小节标题', 'evidence': '证据数'}, height=8)
        self.section_tree.bind('<Double-1>', lambda _: self.edit_section())
        self.section_tree.bind('<<TreeviewSelect>>', lambda _: self.section_detail())
        self.outline_preview = _text(page, height=9, readonly=True)

    def section_detail(self):
        chosen = self.section_tree.selection()
        if chosen:
            section = self.section_rows[chosen[0]]; _write(self.outline_preview, section['title']+'\n\n'+section['body']+'\n\n关联证据：'+'、'.join(i[:8] for i in section['evidence']))
        else:
            _write(self.outline_preview, '按小节整理综述，每段论点可关联已保存的证据卡。导出保留摘录、解释及来源核对状态。')

    def new_section(self):
        return self.section_editor({})

    def edit_section(self):
        ident = self._selected(self.section_tree)
        if ident:
            return self.section_editor(self.section_rows[ident])

    def section_editor(self, section):
        dialog = Editor(self, '编辑综述小节', height=740)
        title, _ = dialog.entry('小节标题', section.get('title', ''))
        position, _ = dialog.entry('排列顺序（非负整数）', str(section.get('position', len(self.section_rows)+1)))
        body = dialog.text('段落草稿 / 写作思路', section.get('body', ''), height=7)
        cards = self.store.cards(section.get('project') or self.project)
        box, evidence = dialog.evidence(cards, section.get('evidence', []))
        def save():
            if not position.get().isdecimal():
                raise ValueError('排列顺序请输入非负整数。')
            value = {'project': section.get('project') or self.project, 'title': title.get(), 'position': int(position.get()), 'body': body.get('1.0', 'end-1c'), 'evidence': evidence()}
            if section.get('id'):
                value['id'] = section['id']
            return self.store.save_section(value)
        dialog.fields = {'title': title, 'position': position}; dialog.texts = {'body': body}; dialog.evidence_box = box
        dialog.save = lambda: dialog.commit(save); dialog.save_button.configure(command=dialog.save); dialog.dirty = False; return dialog

    def delete_section(self):
        ident = self._selected(self.section_tree)
        if ident and messagebox.askyesno('删除小节', '删除此提纲小节？证据卡会保留。', parent=self.win):
            self._error(lambda: self.store.delete_section(ident)); self.refresh()

    def _build_screening(self):
        page = self.pages['screening']
        self._bar(page, [('记录筛选结论', self.screen_editor), ('查看所选文献历史', self.screen_history), ('导出筛选清单 CSV', self.export_screening), ('导出统计与历史', self.export_counts)])
        ttk.Label(page, text='单人本地筛选：先做题录 / 摘要筛选，纳入后才能做全文筛选；排除或待定须填写原因。此记录不代表双人独立评审。', style='Muted.TLabel', wraplength=1000).pack(anchor='w', pady=(0, 6))
        self.screen_counts = tk.StringVar(master=self.win)
        ttk.Label(page, textvariable=self.screen_counts, wraplength=1000).pack(anchor='w', pady=(0, 8))
        self.screen_tree = _tree(page, {'paper': '文献', 'first': '题录 / 摘要', 'second': '全文', 'reason': '最近原因'})
        self.screen_tree.bind('<Double-1>', lambda _: self.screen_editor())
        self.history_preview = _text(page, height=5, readonly=True)

    def screen_editor(self):
        paper = self._selected(self.screen_tree)
        if not paper:
            return
        project = self.project; row = self.screen_rows[paper]
        dialog = Editor(self, '记录筛选结论', height=560)
        initial_stage = '全文' if row[STAGES[0]] and row[STAGES[0]]['decision'] == 'include' else '题录 / 摘要'
        stage, box = dialog.entry('筛选阶段', initial_stage, list(STAGE_LABELS))
        decision, _ = dialog.entry('结论', '待定', list(DECISION_LABELS))
        reason = dialog.text('判断依据 / 排除原因（排除和待定必填）', height=6)
        def load(_=None):
            old = row[STAGE_LABELS[stage.get()]] or {}; decision.set(_label(DECISION_LABELS, old.get('decision', 'uncertain'))); _write(reason, old.get('reason', '')); dialog.dirty = False
        box.bind('<<ComboboxSelected>>', load); load()
        def save():
            return self.store.save_decision(project, paper, STAGE_LABELS[stage.get()], DECISION_LABELS[decision.get()], reason.get('1.0', 'end-1c'))
        dialog.fields = {'stage': stage, 'decision': decision}; dialog.texts = {'reason': reason}
        dialog.save = lambda: dialog.commit(save); dialog.save_button.configure(command=dialog.save); return dialog

    def screen_history(self):
        paper = self._selected(self.screen_tree)
        if not paper:
            return
        lines = []
        from datetime import datetime
        for entry in self.store.history(self.project):
            data = entry['data'].get('after', {})
            if entry['action'] == 'screening_decision' and data.get('paper') == paper:
                lines.append(datetime.fromtimestamp(entry['at']).strftime('%Y-%m-%d %H:%M')+' · '+_label(STAGE_LABELS, data['stage'])+' · '+_label(DECISION_LABELS, data['decision'])+'\n'+data['reason'])
        _write(self.history_preview, '\n\n'.join(lines) or '尚无本地筛选操作记录。交接来源历史可通过统计与历史导出查看。')

    def _build_audit(self):
        page = self.pages['audit']
        self._bar(page, [('重新检查', self.refresh), ('校验附件内容', self.verify_attachments), ('查看证据', self.audit_card), ('导出引用审计', self.export_audit)])
        ttk.Label(page, text='检查来源是否存在、摘录与页码是否齐全、是否人工核对及提纲是否有证据。不能自动判断研究结论是否正确。', style='Muted.TLabel', wraplength=1000).pack(anchor='w', pady=(0, 8))
        self.audit_tree = _tree(page, {'kind': '对象', 'paper': '来源文献', 'message': '需要核查的内容'})
        self.audit_tree.bind('<Double-1>', lambda _: self.audit_card())

    def verify_attachments(self):
        if self.audit_running:
            return
        self.audit_running = True; project = self.project
        self.status.set('正在后台核对来源文件 SHA256；大附件可能需要一些时间。')
        def work():
            store = None
            try:
                store = ResearchStore(self.directory); self.audit_events.put((project, store.validate_sources(project, verify_files=True), None))
            except Exception as exc:
                self.audit_events.put((project, None, str(exc)))
            finally:
                if store:
                    store.close()
        threading.Thread(target=work, daemon=True, name='paperquick-research-audit').start()
        self.audit_job = self.win.after(100, self._poll_audit)

    def _poll_audit(self):
        self.audit_job = None
        if self.closed:
            return
        try:
            project, issues, error = self.audit_events.get_nowait()
        except queue.Empty:
            self.audit_job = self.win.after(100, self._poll_audit); return
        self.audit_running = False
        if error:
            self.status.set('来源校验未完成：'+error)
        elif self.project == project:
            self.audit_rows = issues; self._render_audit()
            self.status.set(f'附件内容校验完成；共有 {len(issues)} 项待核查。')
        else:
            self.status.set('上一个课题的附件内容校验已完成；当前课题可重新校验。')

    def _render_audit(self):
        self.audit_tree.delete(*self.audit_tree.get_children())
        for index, issue in enumerate(self.audit_rows):
            self.audit_tree.insert('', 'end', iid=str(index), values=({'card': '证据卡', 'cell': '矩阵单元格', 'section': '提纲小节', 'decision': '筛选记录'}.get(issue['kind'], issue['kind']), self.paper_names.get(issue['paper'], issue['paper'] or '—'), issue['message']))

    def audit_card(self):
        selected = self._selected(self.audit_tree)
        if not selected:
            return
        issue = self.audit_rows[int(selected)]
        if issue['kind'] == 'card':
            self.tabs.select(self.pages['cards']); self.card_tree.selection_set(issue['id']); self.card_tree.see(issue['id']); self.card_detail()

    def refresh(self):
        if self.closed:
            return
        previous_project = self.project
        self.projects = {p['name']: p['id'] for p in self.store.projects()}
        self.project_box.configure(values=list(self.projects))
        self.project_value.set(next((name for name, pid in self.projects.items() if pid == previous_project), next(iter(self.projects), '')))
        self.paper_names = {p['id']: p['title'] for p in self.store.papers()}
        selected = self.card_tree.selection(); self.card_rows = {c['id']: c for c in self.store.cards(self.project)}
        self.card_tree.delete(*self.card_tree.get_children())
        for card in self.card_rows.values():
            self.card_tree.insert('', 'end', iid=card['id'], values=(card['claim'] or card['quote'][:100] or card['interpretation'][:100], self.paper_names.get(card['paper'], '[来源缺失]'), source_location(card), _label(STANCE_LABELS, card['stance']), '已核对' if card['verified'] else '待核对'))
        if selected and selected[0] in self.card_rows:
            self.card_tree.selection_set(selected[0])
        self.card_detail()
        prior = getattr(self, '_preferred_matrix', None) or getattr(self, 'matrix_names', {}).get(self.matrix_value.get())
        self._preferred_matrix = None
        self.matrix_names = {m['name']+' · '+m['id'][:6]: m['id'] for m in self.store.matrices(self.project)}
        self.matrix_box.configure(values=list(self.matrix_names)); self.matrix_value.set(next((name for name, ident in self.matrix_names.items() if ident == prior), next(iter(self.matrix_names), ''))); self.refresh_matrix()
        self.section_rows = {s['id']: s for s in self.store.sections(self.project)}; self.section_tree.delete(*self.section_tree.get_children())
        for section in self.section_rows.values():
            self.section_tree.insert('', 'end', iid=section['id'], values=(section['position'], section['title'], len(section['evidence'])))
        self.section_detail(); self.screen_tree.delete(*self.screen_tree.get_children())
        self.screen_rows = {r['id']: r for r in self.store.screening_rows(self.project)}
        for row in self.screen_rows.values():
            first, second = row[STAGES[0]] or {}, row[STAGES[1]] or {}
            self.screen_tree.insert('', 'end', iid=row['id'], values=(row['title'], _label(DECISION_LABELS, first.get('decision')), _label(DECISION_LABELS, second.get('decision')), (second or first).get('reason', '')))
        counts = self.store.screening_counts(self.project)
        self.screen_counts.set('；'.join(label+f"：{counts[stage]['total']} 篇，纳入 {counts[stage]['include']} / 排除 {counts[stage]['exclude']} / 待定 {counts[stage]['uncertain']} / 未筛选 {counts[stage]['pending']}" for label, stage in STAGE_LABELS.items()))
        self.audit_rows = self.store.validate_sources(self.project); self._render_audit()
        self.status.set(f'当前课题及子课题：{len(self.card_rows)} 张证据卡，{len(self.matrix_names)} 个矩阵，{len(self.section_rows)} 个小节；{len(self.audit_rows)} 项待核查。筛选结论按当前课题单独记录。')

    def _export(self, extension, title, content):
        path = filedialog.asksaveasfilename(parent=self.win, title=title, defaultextension='.'+extension, filetypes=[(extension.upper(), '*.'+extension)], confirmoverwrite=False)
        if not path:
            return
        if Path(path).suffix.lower() != '.'+extension:
            self.status.set('请使用 .'+extension+' 扩展名，避免覆盖其他类型的文件。'); return
        overwrite = Path(path).exists()
        if overwrite and not messagebox.askyesno('覆盖导出文件', '此文件已经存在。确定使用本次导出替换它吗？\n'+path, parent=self.win):
            return
        result = self._error(lambda: write_export(path, content(), overwrite=overwrite))
        if result:
            self.status.set('已导出：'+str(result))
        return result

    def export_matrix(self):
        ident = self.current_matrix()
        if ident:
            return self._export('csv', '导出比较矩阵', lambda: self.store.matrix_csv(ident))

    def export_outline(self, extension):
        project = self.project
        return self._export(extension, '导出综述提纲', lambda: self.store.outline_docx(project) if extension == 'docx' else self.store.outline_markdown(project))

    def export_screening(self):
        project = self.project
        return self._export('csv', '导出筛选清单', lambda: self.store.screening_csv(project))

    def export_counts(self):
        project = self.project
        return self._export('json', '导出筛选统计与完整历史', lambda: json.dumps({'schema': 1, 'project': project, 'counts': self.store.screening_counts(project), 'decisions': self.store.decisions(project), 'history': self.store.history(project)}, ensure_ascii=False, indent=2))

    def export_audit(self):
        project = self.project
        return self._export('json', '导出引用审计', lambda: json.dumps({'schema': 1, 'project': project, 'issues': self.audit_rows}, ensure_ascii=False, indent=2))

    def can_close(self):
        return not any(editor.dirty for editor in self.editors) or messagebox.askyesno('关闭研究整理', '编辑窗口还有未保存的修改，确定放弃并关闭吗？', parent=self.win)

    def close(self, discard_confirmed=False):
        if self.closed:
            return True
        if not discard_confirmed and not self.can_close():
            return False
        for editor in list(self.editors):
            editor.destroy()
        if self.audit_job:
            self.win.after_cancel(self.audit_job); self.audit_job = None
        self.closed = True; self.store.close(); self.win.destroy(); return True
