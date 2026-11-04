"""Notebook navigation that stays usable when a reading sidebar is narrow."""
import tkinter as tk
from tkinter import ttk, font


class SidebarNotebook(ttk.Notebook):
    """Use native tabs when they fit, otherwise one full-width page selector.

    The selector is a sibling packed immediately above this notebook. Pages
    remain real Notebook children, preserving select/hide and keyboard behavior.
    """
    compact_style = 'SidebarCompact.TNotebook'

    def __init__(self, parent, **kwargs):
        self._normal_style = kwargs.pop('style', 'TNotebook')
        super().__init__(parent, style=self.compact_style, **kwargs)
        self._job = None
        self._visible_tabs = []
        self.navigation = ttk.Frame(parent)
        self.navigation.pack(fill='x', pady=(0, 6))
        ttk.Label(self.navigation, text='侧栏').pack(side='left', padx=(0, 6))
        self.selector = ttk.Combobox(self.navigation, state='readonly', width=1)
        self.selector.pack(side='left', fill='x', expand=True)
        style = ttk.Style(self)
        style.layout(self.compact_style + '.Tab', [])
        style.configure(self.compact_style, tabmargins=0)
        self.selector.bind('<<ComboboxSelected>>', self._choose)
        self.bind('<Configure>', self._schedule, add='+')
        self.bind('<<NotebookTabChanged>>', self._schedule, add='+')
        self.bind('<<ThemeChanged>>', self._schedule, add='+')
        self.bind('<Destroy>', self._destroy_navigation, add='+')
        self._schedule()

    def _schedule(self, event=None):
        if self._job is None:
            self._job = self.after_idle(self.refresh_navigation)

    def refresh_navigation(self):
        self._job = None
        if not self.winfo_exists():
            return
        style = ttk.Style(self)
        self._visible_tabs = [item for item in self.tabs() if self.tab(item, 'state') != 'hidden']
        labels = [self.tab(item, 'text') for item in self._visible_tabs]
        self.selector.configure(values=labels)
        selected = self.select()
        if selected in self._visible_tabs:
            self.selector.current(self._visible_tabs.index(selected))
        else:
            self.selector.set('')
        tab_style = self._normal_style + '.Tab'
        face = font.Font(root=self, font=style.lookup(tab_style, 'font') or 'TkDefaultFont')
        padding = self.tk.splitlist(style.lookup(tab_style, 'padding') or '0')
        left = self.winfo_pixels(str(padding[0])) if padding else 0
        right = self.winfo_pixels(str(padding[2])) if len(padding) > 2 else left
        required = sum(face.measure(label) + left + right + 12 for label in labels) + 8
        compact = required > self.winfo_width()
        target_style = self.compact_style if compact else self._normal_style
        if self.cget('style') != target_style:
            self.configure(style=target_style)
        if compact and self.winfo_manager() == 'pack':
            self.navigation.pack(fill='x', pady=(0, 6), before=self)
        elif not compact:
            self.navigation.pack_forget()

    def _choose(self, event=None):
        index = self.selector.current()
        if 0 <= index < len(self._visible_tabs):
            target = self._visible_tabs[index]
            if self.tab(target, 'state') != 'disabled':
                self.select(target)
        self._schedule()

    def add(self, child, **kwargs):
        result = super().add(child, **kwargs)
        self._schedule()
        return result

    def insert(self, position, child, **kwargs):
        result = super().insert(position, child, **kwargs)
        self._schedule()
        return result

    def hide(self, tab_id):
        result = super().hide(tab_id)
        self._schedule()
        return result

    def forget(self, tab_id):
        result = super().forget(tab_id)
        self._schedule()
        return result

    def tab(self, tab_id, option=None, **kwargs):
        result = super().tab(tab_id, option, **kwargs)
        if kwargs:
            self._schedule()
        return result

    def _destroy_navigation(self, event):
        if event.widget is self:
            if self._job is not None:
                self.after_cancel(self._job)
                self._job = None
            self.navigation.destroy()
