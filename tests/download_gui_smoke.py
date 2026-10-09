"""Test collector and right-click wiring with isolated data and no network."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from library_ui import LibraryWindow
from paper_finder import Paper, Link
from test_library import pdf

base=Path(__file__).resolve().parents[1]/'build'/'download-tests';base.mkdir(parents=True,exist_ok=True)
root=tk.Tk();root.withdraw()
with tempfile.TemporaryDirectory(dir=base) as temp:
    window=LibraryWindow(root,Path(temp)/'store')
    pid=window.library.create_project('下载课题')
    window.choose_project=lambda callback,*args:callback(pid)
    source=Path(temp)/'sample.pdf';pdf(source)
    def wait():
        deadline=time.monotonic()+8
        while window.busy and time.monotonic()<deadline:root.update();time.sleep(.02)
        assert not window.busy
    with patch('download_actions.download_pdf',side_effect=lambda lib,rid,url:lib.attach(rid,source)):
        window.collect(Paper('PDF paper','10.1000/pdf',links=[Link('PDF','https://example.org/paper.pdf','pdf','test')]))
        wait()
    rid=window.library.records()[0]['id'];assert window.library.get(rid)['attachments']
    assert not [w for w in window.win.winfo_children() if isinstance(w,tk.Toplevel)]
    with patch('library_ui.webbrowser.open',return_value=True) as browser:
        window.collect(Paper('Publisher paper','10.1000/pub',links=[Link('Publisher','https://example.org/pub','publisher','test')]))
        wait();browser.assert_called_once_with('https://example.org/pub')
    other=next(r['id'] for r in window.library.records() if r['doi']=='10.1000/pub')
    window.tree.selection_set(rid);root.update()
    bounds=window.tree.bbox(other);assert bounds
    with patch.object(window.context_menu,'tk_popup') as popup:
        window.show_context_menu(SimpleNamespace(y=bounds[1]+5,x_root=100,y_root=100))
        popup.assert_called_once()
    assert window.tree.selection()==(other,)
    with patch.object(window,'start_download') as start:
        window.context_menu.invoke(0);start.assert_called_once_with(other,lookup=True,open_page=True)
    with patch.object(window.context_menu,'tk_popup') as popup:
        window.show_context_menu(SimpleNamespace(y=10000,x_root=100,y_root=100));popup.assert_not_called()
    with patch.object(window,'start_download') as start:
        window.collect(Paper('Offline collection'),download=False);start.assert_not_called()
    window.close()
root.destroy()
print('Download GUI passed: collection auto archives / publisher opens / right-click selects target / offline collection stays offline')
