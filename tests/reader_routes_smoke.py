from pathlib import Path
import tempfile
import sys
import time
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import App
from paper_finder import Paper,Link
from test_reader import text_pdf
base=Path(__file__).resolve().parents[1]/'build'/'reader-tests';base.mkdir(parents=True,exist_ok=True)
root=tk.Tk();app=App(root)
def ready():
    deadline=time.monotonic()+12
    while app.reader_page.loading and time.monotonic()<deadline:root.update();time.sleep(.02)
with tempfile.TemporaryDirectory(dir=base) as temp:
    app.library_directory=Path(temp)/'store';source=Path(temp)/'paper.pdf';text_pdf(source)
    window=app.open_library();rid=window.library.import_pdf(source,window.library.projects()[0]['id']);window.refresh();window.tree.selection_set(rid)
    window.open_pdf();ready();assert app.current_page=='reader';assert app.reader_page.rid==rid
    app.show_page('graph');app.graph_page.records={rid:window.library.get(rid)};app.graph_page.selected=rid;app.graph_page.open_pdf();ready();assert app.current_page=='reader'
    app.reader_page.change_page(1);ready();assert window.library.get(rid)['read_count']==2
    calls=[];window.collect=lambda paper,**kwargs:calls.append(kwargs)
    app.open_link(Paper('Example'),Link('PDF','https://example.org/paper.pdf','pdf','test'));assert calls[0]=={'read_after':True,'preferred_url':'https://example.org/paper.pdf'}
    assert app.current_page=='library'
    deadline=time.monotonic()+12
    while app.graph_page.busy and time.monotonic()<deadline:root.update();time.sleep(.02)
    app.close()
print('PDF routes passed: library and graph open in reader / page turns do not count as sessions / query PDF downloads before reading')
