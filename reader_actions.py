"""Reader search, evidence handoff and persistent positions, with no global hooks."""
import bisect
import sqlite3
import time
import tkinter as tk
from tkinter import ttk

from reading_resume import ReadingResumeStore


class ReaderActions:
    def reading_actions_state(self):
        self.resume_store = ReadingResumeStore(self.directory)
        self.search_window = None
        self.task_manager = None
        self.on_evidence = None
        self._reading_target = None
        self._pending_resume_layout = None
        self._resume_saved = None
        self._resume_checked = 0
        self._logical_document = False
        self._logical_offsets = []

    def reading_actions_widgets(self):
        bar = ttk.Frame(self.frame, padding=(24, 0, 24, 8))
        bar.pack(fill='x', before=self.body)
        self.reading_actions_bar = bar
        ttk.Button(bar, text='文内查找  Ctrl+F', command=self.search_document, style='Compact.TButton').pack(side='left')
        ttk.Button(bar, text='选文存为证据卡', command=self.capture_evidence, style='Compact.TButton').pack(side='left', padx=8)
        self.reading_menu.add_separator()
        self.reading_menu.add_command(label='在本文中查找…', command=self.search_document)
        self.reading_menu.add_command(label='选文存为证据卡', command=self.capture_evidence)
        self.canvas.bind('<Control-f>', lambda _: self.search_document())
        self.canvas.bind('<Control-F>', lambda _: self.search_document())
        self.frame.bind('<Control-f>', lambda _: self.search_document())
        self.splitter.bind('<Configure>', lambda _: self.apply_resume_layout(), add='+')

    def capture_evidence(self):
        if not self.rid:self.status.set('请先打开文献并选中原文。');return
        selection = self.current_selection()
        if self._logical_document and self.text_view:
            try:
                quote = self.text_view.get('sel.first', 'sel.last')
                offset = int(self.text_view.count('1.0', 'sel.first', 'chars')[0])
                paragraph = max(0, bisect.bisect_right(self._logical_offsets, offset) - 1)
                selection = dict(quote=quote, page=None, paragraph=paragraph, locator_kind='paragraph', rect=None)
            except tk.TclError:selection = None
        if not selection or not selection.get('quote', '').strip():self.status.set('先选中要保存的原文，再创建证据卡。');return
        if not self.on_evidence:self.status.set('当前阅读窗口尚未连接研究证据工作区。');return
        self.on_evidence(dict(selection, locator_kind=selection.get('locator_kind', 'page'), paper=self.rid, attachment=self.attachment_id))

    def search_document(self):
        if not self.rid:self.status.set('请先打开一篇文献。');return 'break'
        if self.search_window and not self.search_window.closed:
            if self.search_window.attachment_id == self.attachment_id:
                self.search_window.win.lift();return 'break'
            self.search_window.close()
        from search_ui import SearchWindow
        self.search_window = SearchWindow(self.frame, self.directory, rid=self.rid, attachment_id=self.attachment_id,
                                          manager=self.task_manager, on_location=self.open_search_result)
        return 'break'

    def open_search_result(self, result):
        kind = result.get('locator_kind')
        anchor = dict(page=result.get('page') or 0, paragraph=result.get('paragraph'), query=result.get('query', ''),
                      snippet=result.get('snippet', ''), locator_kind=kind)
        self.open(result['paper'], attachment_id=result.get('attachment'), anchor=anchor,
                  logical=kind == 'paragraph')
        if kind == 'note':
            self.show_notes();self.notebook.select(self.note_tab)
            term = str(result.get('query') or '').split()
            if term:
                index = self.notes.search(term[0], '1.0', stopindex='end', nocase=True)
                if index:self.notes.see(index)

    def show_paged_view(self):
        return super().show_paged_view()

    def prepare_resume(self, rid, attachment, anchor=None, resume=True, logical=False):
        saved = self.resume_store.get(attachment) if resume else None
        target = dict(saved or {})
        if anchor is not None:
            target.update(dict(page=0, fraction=0, x_fraction=0), **anchor)
        self._reading_target = target or None
        self._pending_resume_layout = saved
        self._logical_document = bool(logical if anchor is not None else logical or saved and saved.get('logical'))
        if saved:
            self.scale = saved['scale']
            self.continuous.set(saved['continuous'])
        self._resume_saved = None
        return target

    def save_reading_position(self, force=False):
        if not getattr(self, 'resume_store', None) or not self.rid or self.loading:return
        now = time.monotonic()
        if not force and now - self._resume_checked < 2:return
        self._resume_checked = now
        if self._reading_target:return
        value = dict(page=self.page, fraction=0., x_fraction=0., scale=self.scale,
                     continuous=self.continuous.get(), notes_visible=self.notes_visible, split=.75,
                     logical=self._logical_document, paragraph=0)
        if self._logical_document and self.text_view:
            value['fraction'] = self.text_view.yview()[0]
            offset = self.text_view.count('1.0', '@0,0', 'chars')
            value['paragraph'] = max(0, bisect.bisect_right(self._logical_offsets, int(offset[0]) if offset else 0) - 1)
        elif self.document_canvas.layout:
            top = self.canvas.canvasy(0)
            page = self.document_canvas.page_at(20, top + 18)
            if page in self.document_canvas.layout:
                _, y, _, height = self.document_canvas.layout[page]
                value.update(page=page, fraction=max(0, min(1, (top - y + 18) / max(1, height))), x_fraction=self.canvas.xview()[0])
        else:return
        if len(self.splitter.panes()) > 1 and not self.comparison and self.splitter.winfo_width() > 100:
            value['split'] = self.splitter.sashpos(0) / self.splitter.winfo_width()
        if value == self._resume_saved and not force:return
        try:
            self.resume_store.save(self.rid, self.attachment_id, **value)
            self._resume_saved = value
        except (ValueError, OSError, sqlite3.Error) as exc:self.status.set('阅读位置暂未保存：' + str(exc))

    def apply_resume_layout(self):
        saved = self._pending_resume_layout
        if not saved:return
        if saved.get('notes_visible', True):self.show_notes()
        elif self.notes_visible:
            self.splitter.forget(self.notes_panel);self.notes_visible = False
        if self.splitter.winfo_width() <= 100:return
        if self.notes_visible and len(self.splitter.panes()) > 1:
            self.splitter.sashpos(0, round(self.splitter.winfo_width() * saved['split']))
        self._pending_resume_layout = None

    def apply_reading_target(self):
        target = self._reading_target
        if not target or self.loading:return
        self.apply_resume_layout()
        # A cross-document link can arrive immediately after open(); it wins
        # over the saved position and will be handled by apply_link_location.
        if getattr(self, '_pending_location', None):self._reading_target = None;return
        if self._logical_document and self.text_view:
            if target.get('locator_kind') == 'paragraph':
                paragraph = min(max(0, int(target.get('paragraph') or 0)), max(0, len(self._logical_offsets) - 1))
                offset = self._logical_offsets[paragraph] if self._logical_offsets else 0
                index = self.text_view.index(f'1.0 + {offset} chars')
                self.text_view.see(index)
                self.text_view.tag_remove('search-hit', '1.0', 'end')
                self.text_view.tag_add('search-hit', index, index + ' lineend')
                from ui_theme import ACCENT
                self.text_view.tag_configure('search-hit', underline=True, foreground=ACCENT)
                self.page_label.set(f'第 {paragraph + 1} 段 · 逻辑段落（非页码）')
            else:self.text_view.yview_moveto(target.get('fraction', 0))
            self._reading_target = None
        elif self.path and self.document_canvas.layout:
            page = min(max(0, int(target.get('page') or 0)), max(0, self.count - 1))
            if page not in self.document_canvas.layout:
                self.change_page(page - self.page);return
            self.page = page
            _, y, _, height = self.document_canvas.layout[page]
            region = self.canvas.cget('scrollregion').split()
            self.canvas.yview_moveto(max(0, (y - 18 + target.get('fraction', 0) * height) / max(1, float(region[3]))))
            self.canvas.xview_moveto(target.get('x_fraction', 0))
            self.document_canvas.schedule()
            self._reading_target = None
        if self._reading_target is None:
            self.status.set(('已定位搜索结果：' + target.get('snippet', '')[:160]) if target.get('query') else '已恢复上次阅读位置。')

    def close_reading_actions(self):
        self.save_reading_position(force=True)
        if self.search_window and not self.search_window.closed:self.search_window.close()
