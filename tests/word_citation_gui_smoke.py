"""Isolated Tk integration smoke. Never launches or touches Microsoft Word."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / 'build' / 'vendor'))

from library_core import Library
from test_word_citations import NumberingFormatter
from word_citations import plan_changes


STYLES = [
    {'id': 'fixture-numeric', 'title': '测试 · 数字编号', 'style_class': 'in-text'},
    {'id': 'fixture-author-year', 'title': '测试 · 作者年份', 'style_class': 'in-text'},
]


class FakeBridge:
    def __init__(self):
        self.state = {'document': {'name': 'UI fixture.docx', 'full_name': 'fictional/UI fixture.docx'},
                      'selection': {'start': 10, 'end': 10}, 'fields': []}
        self.applied = []
        self.delay = None

    def snapshot(self):
        if self.delay is not None:
            assert self.delay.wait(5), 'fixture release timed out'
        return deepcopy(self.state)

    def apply(self, expected, operations):
        assert expected == self.state, 'The UI must pass its fresh Word snapshot to apply.'
        self.applied.append(deepcopy(operations))
        self.state['fields'] = [f for f in self.state['fields'] if f['id'] not in operations.get('remove', [])]
        for change in operations.get('updates', []):
            field = next(f for f in self.state['fields'] if f['id'] == change['id'])
            field.update(deepcopy(change))
        if operations.get('insert'):
            field = deepcopy(operations['insert'])
            field.update(start=self.state['selection']['start'], end=self.state['selection']['start'] + 2)
            self.state['fields'].append(field)
        self.state['fields'].sort(key=lambda f: f['start'])
        self.state['selection']['start'] += 100
        self.state['selection']['end'] = self.state['selection']['start']
        return self.snapshot()


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def button(widget, label):
    return next(w for w in descendants(widget) if isinstance(w, ttk.Button) and w.cget('text') == label)


def run():
    # Import the UI against an explicitly fake style catalogue. The real engine
    # has separate formatting tests; this smoke exercises UI-to-planner wiring.
    stub = types.ModuleType('citation_styles')
    stub.list_styles = lambda custom_dir=None: deepcopy(STYLES)
    stub.import_style = lambda path, custom_dir: 'fixture-numeric'
    with patch.dict(sys.modules, {'citation_styles': stub}):
        import word_citation_ui as ui
        from app import App

    fake = FakeBridge()
    formatter = NumberingFormatter()
    original_plan = plan_changes

    def fake_plan(*args, **kwargs):
        kwargs['formatter'] = formatter
        return original_plan(*args, **kwargs)

    root = tk.Tk()
    root.withdraw()
    failures = []
    root.report_callback_exception = lambda *args: failures.append(args)
    window = None
    base = BASE / 'build' / 'word-gui-tests'
    base.mkdir(parents=True, exist_ok=True)

    def wait(predicate, seconds=8):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            root.update()
            time.sleep(.015)
        root.update()
        assert predicate(), 'UI operation did not finish'
        assert not failures, failures

    try:
        with tempfile.TemporaryDirectory(dir=base) as folder:
            library = Library(Path(folder) / 'store')
            project = library.create_project('Citation fixture project')
            first = library.save({'title': 'Alpha paper', 'authors': 'Alpha, Ann', 'year': '2020',
                                  'doi': '10.5555/citation-fixture-alpha', 'venue': 'Fixture Journal',
                                  'volume': '3', 'pages': '10-20', 'notes': 'Keep this local note',
                                  'authors_structured': [{'family': 'Alpha', 'given': 'Ann'}],
                                  'issued': {'date-parts': [[2020, 4, 5]]}}, project)
            second = library.save({'title': 'Beta paper', 'authors': 'Beta, Bob', 'year': '2021'}, project)
            library.close()
            changed = []
            with patch.object(ui.word_bridge, 'snapshot', side_effect=fake.snapshot), \
                    patch.object(ui.word_bridge, 'apply', side_effect=fake.apply), \
                    patch.object(ui, 'plan_changes', side_effect=fake_plan), \
                    patch.object(ui, 'list_styles', side_effect=stub.list_styles), \
                    patch.object(ui.messagebox, 'askyesno', return_value=True):
                window = ui.WordCitationsWindow(root, Path(folder) / 'store', [first], lambda: changed.append(True))
                # Keep the root hidden while allowing this owned test window to
                # lay out at the documented minimum size.
                window.win.transient('')
                window.win.geometry('940x700')
                window.win.deiconify()
                root.update()
                assert window.tree.selection() == (first,)
                for label in ('插入正文引文', '生成 / 更新参考文献表', '更新全部引用 / 切换格式', '预览所选文献'):
                    control = button(window.win, label)
                    assert control.winfo_ismapped(), label
                    bottom = control.winfo_rooty() - window.win.winfo_rooty() + control.winfo_height()
                    right = control.winfo_rootx() - window.win.winfo_rootx() + control.winfo_width()
                    assert bottom <= window.win.winfo_height(), (label, bottom, window.win.winfo_height())
                    assert right <= window.win.winfo_width(), (label, right, window.win.winfo_width())
                window.search.set('no such title')
                assert not window.tree.get_children()
                window.search.set('')
                window.tree.selection_set(first)
                window.execute('insert')
                assert '先打开 Word' in window.status.get()
                assert not fake.applied

                window.connect_button.invoke()
                wait(lambda: not window.busy)
                assert 'UI fixture.docx' in window.target.get()
                window.insert_button.invoke()
                wait(lambda: not window.busy)
                assert len(fake.state['fields']) == 1
                assert fake.state['fields'][0]['payload']['items'][0]['id'] == first
                window.tree.selection_set((first, second))
                window.locator.set('14-16')
                window.execute('insert')
                wait(lambda: not window.busy)
                assert len(fake.state['fields']) == 2
                assert fake.state['fields'][1]['payload']['items'][0]['locator'] == '14-16'

                window.style.set(STYLES[1]['title'])
                button(window.win, '更新全部引用 / 切换格式').invoke()
                wait(lambda: not window.busy)
                assert all(f['payload']['style_id'] == STYLES[1]['id'] for f in fake.state['fields'])
                button(window.win, '生成 / 更新参考文献表').invoke()
                wait(lambda: not window.busy)
                assert sum(f['kind'] == 'bibliography' for f in fake.state['fields']) == 1
                before_preview = len(fake.applied)
                button(window.win, '预览所选文献').invoke()
                wait(lambda: not window.busy)
                preview = next(w for w in window.win.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == '引用格式预览')
                text = next(w for w in descendants(preview) if isinstance(w, tk.Text))
                assert 'Alpha paper' in text.get('1.0', 'end')
                assert '参考文献' in text.get('1.0', 'end')
                assert len(fake.applied) == before_preview, 'Preview must not modify Word.'
                preview.destroy()

                # The document tab previews all connected citations, even when
                # the library selection only contains one of those papers.
                window.tree.selection_set(first)
                window.tabs.select(1)
                root.update()
                before_document_preview = len(fake.applied)
                button(window.win, '查看格式预览').invoke()
                wait(lambda: not window.busy)
                preview = next(w for w in window.win.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == '引用格式预览')
                text = next(w for w in descendants(preview) if isinstance(w, tk.Text))
                content = text.get('1.0', 'end')
                assert 'Alpha paper' in content and 'Beta paper' in content, 'Document preview must include every cited paper.'
                assert len(formatter.calls[-1][1]) == 2, 'Document preview must format both citation clusters.'
                assert len(fake.applied) == before_document_preview, 'Document preview must not modify Word.'
                preview.destroy()
                window.tabs.select(0)

                # A successfully applied Word update remains a success if saving
                # the optional local default style preference fails afterwards.
                before_preference_failure = len(fake.applied)
                with patch.object(ui.Library, 'set_setting', side_effect=OSError('fixture preference write failure')):
                    window.execute('refresh')
                    wait(lambda: not window.busy)
                assert len(fake.applied) == before_preference_failure + 1
                assert all(window.snapshot.get(key) == value for key, value in fake.state.items()), 'A completed Word update must still refresh the document snapshot.'
                assert '已更新' in window.status.get(), window.status.get()
                assert '保存' in window.status.get() and ('未' in window.status.get() or '失败' in window.status.get()), window.status.get()

                # Copied Word fields can carry duplicate PaperQuick IDs. Handle
                # this as an actionable document issue, before Treeview.insert
                # receives a duplicate iid or future edits use this snapshot.
                duplicate = deepcopy(fake.state)
                duplicate['fields'].append(deepcopy(duplicate['fields'][0]))
                window.show_document(duplicate)
                root.update()
                assert window.snapshot is None, 'A duplicate field snapshot must not be eligible for writes.'
                assert '重复' in window.status.get(), window.status.get()
                assert not failures, failures
                window.connect()
                wait(lambda: not window.busy)
                assert window.snapshot == fake.state

                window.tree.selection_set(first)
                button(window.win, '编辑文献信息').invoke()
                root.update()
                edit = next(w for w in window.win.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == '核对引用信息')
                entries = {int(w.grid_info()['row']): w for w in descendants(edit) if isinstance(w, ttk.Entry)}
                for row, value in ((0, 'Updated Alpha title'), (1, 'Edited, Ann; Second, Bob'), (2, '2025')):
                    entries[row].delete(0, 'end')
                    entries[row].insert(0, value)
                button(edit, '保存信息').invoke()
                root.update()
                saved = window._library(lambda lib: lib.get(first))
                assert saved['notes'] == 'Keep this local note'
                assert saved['title'] == 'Updated Alpha title'
                assert not saved.get('authors_structured'), 'Editing authors must clear obsolete structured names.'
                assert not saved.get('issued'), 'Editing the year must clear the obsolete full publication date.'
                assert saved['year'] == '2025'
                assert changed
                assert window.tree.selection() == (first,)
                window.execute('refresh')
                wait(lambda: not window.busy)
                assert fake.state['fields'][0]['payload']['items'][0]['itemData']['title'] == 'Updated Alpha title'

                with patch.object(ui, 'fetch_doi_metadata', return_value={
                        'authors': 'Fixture, Author', 'authors_structured': [{'family': 'Fixture', 'given': 'Author'}],
                        'year': '2026', 'issued': {'date-parts': [[2026]]}}) as fetch:
                    button(window.win, '按 DOI 补全信息').invoke()
                    wait(lambda: not window.busy)
                    fetch.assert_called_once_with('10.5555/citation-fixture-alpha')
                saved = window._library(lambda lib: lib.get(first))
                assert saved['notes'] == 'Keep this local note'
                assert saved['authors_structured'][0]['family'] == 'Fixture'

                # A different active Word document must never receive a stale
                # window's insertion, even though a fresh snapshot is available.
                before_other_doc = len(fake.applied)
                fake.state['document']['name'] = 'Different fixture.docx'
                window.execute('insert')
                wait(lambda: not window.busy)
                assert len(fake.applied) == before_other_doc
                assert '文档已改变' in window.status.get()
                window.connect()
                wait(lambda: not window.busy)

                fake.delay = threading.Event()
                window.connect()
                assert window.busy
                assert window.close() is False
                assert window.win.winfo_exists()
                # Execute the actual application's early close guard without
                # instantiating App or its real library/background services.
                owner = types.SimpleNamespace(library_window=types.SimpleNamespace(word_citations=window, busy=False))
                App.close(owner)
                assert not window.closed and '完成后' in window.status.get()
                fake.delay.set()
                wait(lambda: not window.busy)
                fake.delay = None
                assert window.close() is True
                assert not failures, failures
                window = None
    finally:
        if fake.delay is not None:
            fake.delay.set()
        if window is not None and not window.closed:
            wait(lambda: not window.busy)
            window.close()
        root.destroy()
    print('Word citations GUI passed: 940x700 layout / isolated connect / insert / style / bibliography / selected and document previews / preference failure / duplicate field guard / metadata / document guard / busy close guard')


if __name__ == '__main__':
    run()
