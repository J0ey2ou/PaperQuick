"""Exercise graph camera/subsets and persistent reader annotations with owned fixtures."""
import sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_core import Library
from graph_ui import GraphPage
from reader_ui import ReaderPage
from pdf_reader_core import region_text
from test_reader import text_pdf

base=Path(__file__).resolve().parents[1]/'build'/'exploration-tests';base.mkdir(parents=True,exist_ok=True)
root=tk.Tk();root.geometry('1320x960')
def until(predicate):
    deadline=time.monotonic()+20
    while not predicate() and time.monotonic()<deadline:root.update();time.sleep(.02)
    assert predicate()
with tempfile.TemporaryDirectory(dir=base) as temp:
    directory=Path(temp)/'store';graph=GraphPage(root,directory);graph.frame.pack(fill='both',expand=True)
    nodes=[dict(id=str(i),title=f'Research {i}',doi='',projects=['Demo'],status='未读',pdf=i%10==0,in_library=True) for i in range(110)]
    edges=[dict(source=str(i),target=str(i+1),kind='similarity',weight=.5) for i in range(109)]
    graph.data={'nodes':nodes,'edges':edges};root.update();graph.switch('network');until(lambda:not graph.layout_running)
    assert len(graph.visible_nodes)==80
    graph.limit.set(25);graph.apply_limit();until(lambda:not graph.layout_running);assert len(graph.visible_nodes)==25
    graph.selected=graph.visible_nodes[0]['id'];graph.focus_selected();until(lambda:not graph.layout_running)
    assert len(graph.visible_nodes)<=3
    before=graph.world(150,200);graph.zoom_at(150,200,1.5);after=graph.world(150,200)
    assert max(abs(a-b) for a,b in zip(before,after))<1e-8
    graph.reset();until(lambda:not graph.layout_running);assert len(graph.visible_nodes)==25
    graph.close();graph.frame.destroy()
    source=Path(temp)/'fixture.pdf';text_pdf(source)
    assert 'Local literature' in region_text(source,0,[.05,.04,.95,.12])
    lib=Library(directory);rid=lib.import_pdf(source,lib.projects()[0]['id']);lib.close()
    reader=ReaderPage(root,directory,lambda q:None,lambda r:None);reader.frame.pack(fill='both',expand=True);reader.open(rid)
    until(lambda:reader.count==2 and not reader.loading and not reader.fit_pending)
    reader.new_paragraph();root.update();assert reader.notes.cget('state')=='normal'
    reader.notes.insert('insert','My editable research note');reader.save_notes()
    reader.tool.set('框选高亮');w,h=reader.image_size
    reader.begin_selection(SimpleNamespace(x=18+.05*w,y=18+.04*h));reader.end_selection(SimpleNamespace(x=18+.95*w,y=18+.12*h))
    until(lambda:len(reader.annotations)==1)
    highlight=reader.annotations[0];assert 'Local literature' in highlight['quote']
    revised=dict(highlight,text='A saved comment');reader.add_annotation(revised)
    reader.add_bookmark();assert len(reader.annotations)==2
    reader.zoom(.8);until(lambda:not reader.loading);assert reader.canvas.find_withtag('annotation')
    reader.open(rid);until(lambda:not reader.loading and reader.count==2 and not reader.fit_pending)
    assert reader.notes.get('1.0','end-1c')=='My editable research note'
    assert reader.annotations[0]['text']=='A saved comment'
    assert reader.annotations[0]['rect']==highlight['rect']
    exported=Path(temp)/'notes.md'
    with patch('reader_ui.filedialog.asksaveasfilename',return_value=str(exported)):reader.export_notes()
    assert 'A saved comment' in exported.read_text('utf-8')
    reader.annotation_list.selection_set(highlight['id'])
    with patch('reader_ui.messagebox.askyesno',return_value=True):reader.delete_annotation()
    lib=Library(directory);assert len(lib.get(rid)['annotations'])==1;assert lib.get(rid)['notes']=='My editable research note';lib.close()
    reader.close();root.destroy()
print('Exploration passed: graph subset / neighbor focus / cursor zoom / editable notes / region text / highlight and comment persistence / bookmarks / export / deletion')
