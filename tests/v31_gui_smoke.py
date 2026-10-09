from pathlib import Path
import sys,tempfile,time
from unittest.mock import patch
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import App
from ui_theme import apply_skin,SKINS
from test_reader import text_pdf
base=Path(__file__).resolve().parents[1]/'build'/'v31-tests';base.mkdir(parents=True,exist_ok=True)
root=tk.Tk();app=App(root)
def wait(predicate):
    deadline=time.monotonic()+15
    while not predicate() and time.monotonic()<deadline:root.update();time.sleep(.02)
    assert predicate()
with tempfile.TemporaryDirectory(dir=base) as temp:
    app.library_directory=Path(temp)/'store';window=app.open_library();lib=window.library;pid=lib.create_project('课题')
    source=Path(temp)/'demo.pdf';text_pdf(source);rid=lib.import_pdf(source,pid);other=lib.save({'title':'No PDF'},pid)
    lib.save({'title':'Updated filename'},rid=rid);lib.set_setting('template','{标题}')
    window.search.set('absent');window.select_all(True);assert window.tree.selection()==(rid,)
    with patch('library_ui.messagebox.askyesno',return_value=True),patch('library_ui.messagebox.showinfo'):
        window.rename_selected();wait(lambda:not window.busy)
    assert Path(lib.get(rid)['attachments'][0]['path']).name=='Updated filename.pdf'
    window.select_all(False);assert len(window.tree.selection())==2
    app.open_reader(rid);reader=app.reader_page;wait(lambda:reader.count and not reader.loading and not reader.fit_pending)
    reader.context_note();root.update();reader.notes.insert('end','Context note');reader.save_notes();assert 'Context note' in lib.get(rid)['notes']
    reader.references=[{'title':'Numbered','doi':'','raw':'test','number':'7','query':'Numbered'}];reader.reference_panel();assert reader.reference_tree.item('0','values')[0]=='7';reader.reference_window.destroy()
    for skin in SKINS:app.skin=apply_skin(root,skin);root.update()
    original_page=app.current_page;app.show_summary();root.update()
    assert '阅读总结' in app.summary_view.content
    assert app.current_page==original_page and app.summary_dialog.winfo_exists()
    assert 'summary' not in app.nav_buttons
    app.show_summary();assert app.summary_dialog.winfo_exists()
    app.summary_dialog.event_generate('<Escape>');root.update()
    app.settings();root.update();assert app.current_page=='settings';assert app.settings_page.winfo_ismapped()
    app.close()
print('v3.1 GUI passed: full-library selections / rename attached file / reader context notes / reference numbering / four skins / summary / settings page')
