"""Check the owned unified UI, graph interaction and minimum-size layout."""
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import App
from library_ui import LibraryWindow
from graph_ui import GraphPage

base=Path(__file__).resolve().parents[1]/'build'/'library-tests';base.mkdir(parents=True,exist_ok=True)
root=tk.Tk();app=App(root)
with tempfile.TemporaryDirectory(dir=base) as temp:
    window=LibraryWindow(app.page_host,Path(temp),embedded=True);app.library_window=window
    window.library.save({'title':'Protein structure prediction','doi':'10.1000/a'})
    window.refresh();app.graph_page=GraphPage(app.page_host,Path(temp))
    app.show_page('library');root.update();assert app.current_page=='library'
    root.geometry('1120x800');root.update_idletasks()
    # The footer must remain inside the displayed page, rather than being packed below it.
    bottom=window.win.winfo_children()[-1]
    assert bottom.winfo_y()+bottom.winfo_height()<=window.win.winfo_height(), (bottom.winfo_y(),bottom.winfo_height(),window.win.winfo_height())
    project_button=next(w for w in window.projects.master.winfo_children() if w.winfo_class()=='TButton')
    assert project_button.winfo_ismapped()
    assert project_button.winfo_y()+project_button.winfo_height()<=project_button.master.winfo_height()
    app.show_page('graph');deadline=time.monotonic()+10
    while app.graph_page.busy and time.monotonic()<deadline:root.update();time.sleep(.025)
    assert not app.graph_page.busy;assert app.graph_page.data['summary']['total']==1
    bottom=app.graph_page.frame.winfo_children()[-1]
    assert bottom.winfo_y()+bottom.winfo_height()<=app.graph_page.frame.winfo_height()
    app.graph_page.switch('network');deadline=time.monotonic()+10
    while app.graph_page.layout_running and time.monotonic()<deadline:root.update();time.sleep(.025)
    root.update();assert app.graph_page.canvas.find_withtag('node')
    app.show_page('query');root.update();assert app.query_page.winfo_ismapped()
    app.close()
print('Unified UI smoke passed: parallel navigation / graph generation / network drawing / minimum-size layout')
