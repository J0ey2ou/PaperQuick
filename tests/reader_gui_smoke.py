from pathlib import Path
import tempfile
import sys
import time
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_core import Library
from reader_ui import ReaderPage
from test_reader import text_pdf
base=Path(__file__).resolve().parents[1]/'build'/'reader-tests';base.mkdir(parents=True,exist_ok=True)
root=tk.Tk();root.geometry('1320x920')
with tempfile.TemporaryDirectory(dir=base) as temp:
    directory=Path(temp)/'store';source=Path(temp)/'demo.pdf';text_pdf(source);lib=Library(directory);rid=lib.import_pdf(source,lib.projects()[0]['id']);lib.close()
    queried=[];collected=[];reader=ReaderPage(root,directory,queried.append,collected.append);reader.frame.pack(fill='both',expand=True);reader.open(rid)
    deadline=time.monotonic()+15
    while (reader.count!=2 or not reader.references) and time.monotonic()<deadline:root.update();time.sleep(.025)
    assert reader.count==2 and len(reader.references)==2;assert hasattr(reader,'photo')
    root.geometry('1120x800');root.update_idletasks()
    footer=reader.frame.winfo_children()[-1];assert footer.winfo_y()+footer.winfo_height()<=reader.frame.winfo_height()
    reader.notes.insert('end','Saved reader note');root.update();reader.save_notes()
    lib=Library(directory);assert lib.get(rid)['notes']=='Saved reader note';assert lib.get(rid)['read_count']==1;lib.close()
    reader.reference_panel();root.update();reader.reference_window.geometry('760x560');root.update();root.update_idletasks()
    assert reader.reference_actions.winfo_y()+reader.reference_actions.winfo_height()<=reader.reference_window.winfo_height(), (reader.reference_actions.winfo_y(),reader.reference_actions.winfo_height(),reader.reference_window.winfo_height())
    reader.reference_tree.selection_set('0');reader.query_reference();assert queried[0]=='10.9999/not-collected'
    reader.reference_panel();root.update();assert reader.reference_window.state()!='withdrawn';reader.collect_reference();assert collected
    lib=Library(directory);lib.save({'title':'Renamed during reading'},rid=rid);lib.rename(rid);lib.close()
    reader.change_page(1);deadline=time.monotonic()+10
    while reader.loading and time.monotonic()<deadline:root.update();time.sleep(.025)
    assert reader.page==1 and reader.path.exists() and 'Renamed during reading' in reader.path.name;reader.close();root.destroy()
print('Reader UI passed: local PDF rendering / notes persistence / read counter / references panel / query and collect callbacks / page navigation')
