"""Run the actual desktop UI using fictional local demo records."""
from pathlib import Path
import sys
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_ui import LibraryWindow
from app import App
from graph_ui import GraphPage
from reader_ui import ReaderPage
from ui_theme import opening_animation
root=tk.Tk();app=App(root);root.title('文献直达 · UI演示')
root.geometry('1400x920+50+30')
app.preferences={};app.email=''
directory=Path(__file__).resolve().parents[1]/'build'/'demo-library'
app.library_directory=directory
window=LibraryWindow(app.page_host,directory,embedded=True)
app.library_window=window
app.graph_page=GraphPage(app.page_host,directory)
app.reader_page=ReaderPage(app.page_host,directory,app.query_reference,app.collect_reference)
app.reader_page.on_document_change=app.stop_reading
window.on_reader=app.open_reader
app.graph_page.on_reader=app.open_reader
app.graph_page.on_query=app.query_reference
app.graph_page.on_collect=app.collect_reference
app.show_page('reader')
rid=next(r['id'] for r in window.library.records() if r['title']=='Local literature reading demo')
app.reader_page.open(rid)
window.status.set('界面演示 · 使用虚构文献示例 · 本地离线工作区')
window.tree.selection_set(window.tree.get_children()[0]);window.detail()
opening_animation(root)
if len(sys.argv)>1:
    if sys.argv[1]=='summary':root.after(500,app.show_summary)
    else:app.show_page(sys.argv[1])
root.mainloop()
