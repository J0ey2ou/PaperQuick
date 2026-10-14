"""Own fixtures: selection, continuous pages, image persistence, dock, TXT editing."""
import sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tkinter as tk
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_core import Library
from reader_ui import ReaderPage
from import_selection_ui import ImportSelection
from test_reader import text_pdf

base=Path(__file__).resolve().parents[1]/'build'/'reader-upgrade-gui';base.mkdir(parents=True,exist_ok=True)
root=tk.Tk();root.geometry('1440x1000')
def until(predicate,seconds=25):
    deadline=time.monotonic()+seconds
    while not predicate() and time.monotonic()<deadline:root.update();time.sleep(.02)
    assert predicate()
with tempfile.TemporaryDirectory(dir=base) as temp:
    directory=Path(temp)/'store';source=Path(temp)/'demo.pdf';text_pdf(source);lib=Library(directory);rid=lib.import_pdf(source);pid=lib.projects()[0]['id'];lib.close()
    reader=ReaderPage(root,directory,lambda q:None,lambda r:None);reader.frame.pack(fill='both',expand=True);reader.open(rid)
    until(lambda:reader.count==2 and not reader.loading and not reader.fit_pending and 0 in reader.document_canvas.cache)
    root.update();view=reader.document_canvas;chars=view.cache[0][1];start=next(c for c in chars if c['text']=='L');end=chars[15]
    def position(c):
        x0,y0,x1,y1=view.coords(0,c['rect']);return SimpleNamespace(x=(x0+x1)/2-reader.canvas.canvasx(0),y=(y0+y1)/2-reader.canvas.canvasy(0))
    reader.begin_selection(position(start));reader.move_selection(position(end));reader.end_selection(position(end));reader.copy_selected();assert 'Local literature' in root.clipboard_get()
    reader.change_page(1);until(lambda:reader.page==1 and 1 in view.cache);assert reader.canvas.canvasy(0)>100
    reader.change_page(-1);until(lambda:reader.page==0 and 0 in view.cache)
    reader.notes.insert('end','Image note:');reader.insert_note_image(Image.new('RGB',(220,120),'#99bbcc'));reader.save_notes()
    lib=Library(directory);data=lib.get(rid);assert len(data['note_images'])==1 and '\ufffc' in data['notes'];lib.close()
    reader.open(rid);until(lambda:not reader.loading and not reader.fit_pending);assert len(reader.note_images)==1
    reader.context_page=0;reader.context_point=[.2,.3];reader.context_note();assert any(a['kind']=='笔记' and a['rect'][:2]==[.2,.3] for a in reader.annotations)
    reader.dock_references();root.update();assert reader.reference_dock.winfo_ismapped();assert len(reader.docked_tree.get_children())==2
    before=reader.canvas.winfo_height();reader.toggle_focus();root.update();assert reader.canvas.winfo_height()>before;reader.toggle_focus();root.update()
    exported=Path(temp)/'notes.html'
    with patch('reader_ui.filedialog.asksaveasfilename',return_value=str(exported)):reader.export_notes()
    assert 'data:image/png;base64,' in exported.read_text('utf-8')
    lib=Library(directory);assert any(a['role']=='note' for a in lib.get(rid)['attachments']);assert any(e['kind']=='note' for e in lib.graph()['edges']);lib.close()
    txt=Path(temp)/'reading.txt';txt.write_text('A local text\nReferences\n[1] Doe J. A long useful title for research. doi:10.1234/demo',encoding='utf-8')
    lib=Library(directory);tid=lib.import_document(txt);lib.close();reader.open(tid);until(lambda:reader.text_view and reader.text_view.winfo_ismapped());assert 'A local text' in reader.text_view.get('1.0','end')
    reader.edit_document();until(lambda:reader.word_editing and not reader.document_job);reader.text_view.insert('1.0','Edited here\n');root.update();reader.save_document();until(lambda:not reader.document_job and not reader.word_editing)
    assert txt.read_text('utf-8').startswith('A local text');lib=Library(directory);managed=lib.root/lib.primary_attachment(tid)['path'];assert managed.read_text('utf-8').startswith('Edited here');lib.close()
    selected=[];dialog=ImportSelection(root,[source,txt],selected.append);dialog.toggle('1');dialog.accept();assert selected==[[source]]
    reader.close();root.destroy()
print('Upgrade GUI passed: character selection / continuous scrolling / image save and reload / positional marker / dock / focus / linked export / TXT editing / checked import')
