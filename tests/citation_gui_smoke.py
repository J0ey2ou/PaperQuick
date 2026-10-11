"""Citation browsing, collection and closing a pending request; no network calls."""
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from citation_ui import CitationView
from library_core import Library
from ui_theme import apply_skin


def wait(root, predicate):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        root.update()
        time.sleep(.01)
    assert predicate(), 'Citation lookup did not finish'


test_root = Path(__file__).resolve().parents[1] / 'build' / 'citation-ui-tests'
test_root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=test_root) as directory:
    lib = Library(directory)
    project = lib.create_project('示例课题')
    seed = lib.save({'title': 'Example starting paper', 'doi': '10.1234/seed', 'year': '2020'}, project)
    lib.save({'title': 'Already collected', 'doi': '10.1234/existing'}, project)
    lib.close()
    root = tk.Tk()
    root.withdraw()
    apply_skin(root, '深空蓝')
    queried, collected = [], []
    view = CitationView(root, directory, queried.append, lambda: collected.append(True))
    view.search.set('starting')
    assert view._seed_record()['id'] == seed
    result = {
        'items': [
            {'title': 'Reference paper', 'doi': '10.1234/reference', 'year': '2018', 'relation': 'reference', 'seed_title': 'Example starting paper', 'seed_doi': '10.1234/seed', 'abstract': 'Example abstract', 'source': 'Europe PMC'},
            {'title': 'Later paper', 'doi': '10.1234/citing', 'year': '2024', 'relation': 'citing'},
            {'title': 'Already collected', 'doi': '10.1234/existing', 'relation': 'reference'},
        ], 'message': '部分结果已找到，稍后可再试另一个方向。', 'truncated': False,
    }
    with patch('citation_ui.find_related', return_value=result) as lookup:
        view.find()
        wait(root, lambda: not view.busy)
        assert lookup.call_args.kwargs['direction'] == 'both'
    assert len(view.items) == 2
    assert 'Example abstract' in view.detail.get('1.0', 'end')
    assert '部分结果' in view.status.get()
    view.query_selected()
    assert queried == ['10.1234/reference']
    view.target_project.set('新收藏课题')
    view.collect_selected()
    assert collected == [True]
    lib = Library(directory)
    saved = next(record for record in lib.records() if record['doi'] == '10.1234/reference')
    assert lib.project(saved['primary_project'])['name'] == '新收藏课题'
    assert saved['discovered_from']['relation'] == 'reference'
    lib.close()
    assert len(view.items) == 1
    event, finished = threading.Event(), threading.Event()
    requested_limits = []
    def pending(*args, **kwargs):
        requested_limits.append(kwargs['limit'])
        event.wait(2)
        finished.set()
        return result
    with patch('citation_ui.find_related', side_effect=pending):
        view.result_limit.set('200')
        view.find()
        view.close()
        view.frame.destroy()
        event.set()
        wait(root, finished.is_set)
        root.update()
    assert view.closed and view.poll_id is None
    assert requested_limits == [200]
    # Allocate real child geometry while the desktop window stays withdrawn.
    # This reproduces the minimum popup size without interrupting the user.
    from summary_ui import SummaryView
    holder = ttk.Frame(root)
    holder.place(x=0, y=0, width=1020, height=720)
    summary = SummaryView(holder, directory)
    summary.frame.pack(fill='both', expand=True)
    summary.refresh()
    summary.tabs.select(summary.citations.frame)
    root.update_idletasks()
    citations = summary.citations
    footer = citations.query_button.master
    assert footer.winfo_y() + footer.winfo_height() <= citations.frame.winfo_height()
    assert citations.query_button.winfo_height() >= 30
    assert citations.status_label.winfo_y() + citations.status_label.winfo_height() <= citations.frame.winfo_height()
    assert citations.tree.winfo_height() > 80
    assert citations.detail.winfo_height() >= 36
    summary.close()
    holder.destroy()
    root.destroy()
print('Citation GUI passed: seed search / partial results / library exclusion / lookup / collection / 200 results / safe close / minimum popup layout')
