"""Exercise owned Tk UI directly with isolated fixture data, no real user library."""
from pathlib import Path
import sys
import tempfile
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_ui import LibraryWindow
from test_library import pdf,endnote
import endnote_sync
base=Path(__file__).resolve().parents[1]/'build'/'library-tests';base.mkdir(parents=True,exist_ok=True)
root=tk.Tk();root.withdraw()
with tempfile.TemporaryDirectory(dir=base) as temp:
    window=LibraryWindow(root,Path(temp)/'store')
    pid=window.library.create_project('演示课题');source=Path(temp)/'demo.pdf';pdf(source)
    rid=window.library.import_pdf(source,pid);window.refresh();root.update_idletasks()
    assert len(window.tree.get_children())==1
    window.tree.selection_set(rid);window.mark('已读');assert window.library.get(rid)['status']=='已读'
    window.naming();root.update_idletasks()
    dialogs=[w for w in window.win.winfo_children() if isinstance(w,tk.Toplevel)];assert len(dialogs)==1;dialogs[0].destroy()
    source=Path(temp)/'EndNote.enl';endnote(source);window.sync_preview(endnote_sync.preview(window.library,source));root.update_idletasks()
    dialogs=[w for w in window.win.winfo_children() if isinstance(w,tk.Toplevel)];assert len(dialogs)==1;dialogs[0].destroy()
    window.search.set('absent');assert not window.tree.get_children();window.search.set('Test');assert len(window.tree.get_children())==1
    window.close()
root.destroy();print('Library GUI smoke passed: projects / records / read status / naming / sync preview / search')
