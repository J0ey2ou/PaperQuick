"""Temporary, fictional fixtures; no user's Word session or library is opened."""
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_core import Library
from reader_ui import ReaderPage
from attachment_ui import AttachmentManager,open_external
from document_conversion_ui import ConversionWindow
from test_reader import text_pdf
from ui_theme import install_theme

def word_fixture(path):
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Fictional Word attachment</w:t></w:r></w:p></w:body></w:document>')

root=tk.Tk();root.geometry('1120x800');install_theme(root)
errors=[];root.report_callback_exception=lambda *args:errors.append(args)
def wait(condition,timeout=15):
    deadline=time.monotonic()+timeout
    while not condition() and time.monotonic()<deadline:root.update();time.sleep(.02)
    root.update();assert condition(),'Timed out';assert not errors,errors

base=Path(__file__).resolve().parents[1]/'build'/'reader-tests';base.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=base) as temp:
    directory=Path(temp)/'store';source=Path(temp)/'main.pdf';supplement=Path(temp)/'supplement.pdf';word=Path(temp)/'appendix.docx';text_pdf(source);shutil.copy2(source,supplement)
    with supplement.open('ab') as f:f.write(b'\n% Fictional supplement\n')
    word_fixture(word)
    lib=Library(directory);rid=lib.import_pdf(source);lib.add_attachment(rid,supplement,label='Supplement tables');lib.add_attachment(rid,word,label='Protocol');items=lib.get(rid)['attachments'];primary=lib.primary_attachment(rid);pdf=next(a for a in items if a.get('label')=='Supplement tables');worditem=next(a for a in items if a.get('label')=='Protocol');lib.close()
    def preview(path,cache_dir,timeout=120):return Path(path) if Path(path).suffix.lower()=='.pdf' else source
    with patch('document_conversion.preview_pdf',side_effect=preview):
        reader=ReaderPage(root,directory,lambda _:None,lambda _:None);reader.frame.pack(fill='both',expand=True);reader.open(rid)
        wait(lambda:reader.count==2 and not reader.loading and len(reader.references)==2)
        reader.notes.insert('end','Main notes remain attached to the paper.');reader.save_notes();reader.add_bookmark();reader.change_page(1);wait(lambda:not reader.loading)
        original_page=reader.page;original_annotation=reader.annotations[0]['id'];reader.compare_attachment(pdf);wait(lambda:reader.comparison and reader.comparison.count==2 and not reader.comparison.loading)
        wait(lambda:not reader.loading and abs(reader.image_size[0]-(reader.canvas.winfo_width()-40))<4)
        reader.zoom(1.18);wait(lambda:not reader.loading);manual_scale=reader.scale
        pause=time.monotonic()+.35
        while time.monotonic()<pause:root.update();time.sleep(.02)
        assert reader.scale==manual_scale
        reader.comparison.change_page(1);wait(lambda:not reader.comparison.loading)
        assert reader.page==original_page and reader.attachment_id==primary['id'];assert len(reader.splitter.panes())==2 and not reader.notes_visible
        assert reader.viewer.winfo_width()>300 and reader.comparison.frame.winfo_width()>300
        assert reader.frame.winfo_width()==1120;assert reader.frame.winfo_children()[-1].winfo_y()+reader.frame.winfo_children()[-1].winfo_height()<=800
        reader.compare_attachment(worditem);wait(lambda:reader.comparison.count==2 and not reader.comparison.loading);assert reader.comparison.attachment_id==worditem['id'];assert reader.page==original_page
        reader.toggle_notes();root.update();assert reader.notes_visible and len(reader.splitter.panes())==3
        reader.hide_comparison();root.update();assert reader.comparison is None and reader.notes_visible
        reader.attachment_panel();manager=reader.attachment_manager;root.update();manager.win.geometry('720x500');root.update();manager.tree.selection_set(worditem['id'])
        manager.set_primary();wait(lambda:not manager.busy and not reader.loading and reader.attachment_id==worditem['id'])
        assert reader.path==source and reader.source_path.suffix.lower()=='.docx';assert not reader.annotation_list.get_children()
        lib=Library(directory);assert lib.get(rid)['notes']=='Main notes remain attached to the paper.';assert lib.get(rid)['read_count']==1;lib.close()
        manager.tree.selection_set(primary['id']);manager.set_primary();wait(lambda:not manager.busy and not reader.loading and reader.attachment_id==primary['id']);assert original_annotation in reader.annotation_list.get_children()
        manager.busy=True;assert not reader.can_close() and not manager.close();manager.busy=False;manager.close()
        reader.conversion();converter=reader.conversion_window;root.update();converter.win.geometry('640x520');root.update();assert converter.start_button.winfo_ismapped();assert converter.mode.get()=='text';assert converter.mode_frame.winfo_ismapped();assert '无需安装 Word' in converter.notice.get()
        converter.source.set(str(word));converter.refresh();root.update();assert not converter.mode_frame.winfo_ismapped();assert '需要本机安装' in converter.notice.get()
        converter.source.set(str(source));converter.mode.set('appearance');converter.refresh();root.update();assert converter.mode_frame.winfo_ismapped();assert '不能直接编辑' in converter.notice.get()
        target=Path(temp)/'converted.docx'
        modes=[]
        def convert(src,dest,timeout=120,mode='text'):modes.append(mode);word_fixture(dest);return Path(dest)
        with patch('document_conversion_ui.filedialog.asksaveasfilename',return_value=str(target)),patch('document_conversion.convert_document',side_effect=convert):
            converter.start();assert reader.busy and not reader.can_close();wait(lambda:not converter.busy)
        assert target.exists();assert converter.result==target;assert reader.comparison;assert modes==['appearance']
        wait(lambda:reader.comparison.count==2 and not reader.comparison.loading)
        assert reader.attachment_id==primary['id'];lib=Library(directory);record=lib.get(rid);lib.close();assert len(record['attachments']) in (3,4);assert record['read_count']==1 # byte-identical fixtures may be deduplicated
        with patch('document_conversion_ui.filedialog.asksaveasfilename',return_value=str(target)),patch('document_conversion.convert_document') as convert_mock:
            converter.start();assert not converter.busy;convert_mock.assert_not_called()
        converter.close();reader.hide_comparison();reader.open(rid);wait(lambda:not reader.loading)
        # Closing a comparison pane must not lose track of its private Word job.
        started=threading.Event();release=threading.Event()
        def slow_preview(*args,**kwargs):started.set();release.wait(10);return source
        with patch('document_conversion.preview_pdf',side_effect=slow_preview):
            reader.compare_attachment(worditem);wait(started.is_set);reader.hide_comparison();assert not reader.can_close();release.set();wait(reader.can_close)
        # A failed Word preview leaves no readable page, and cannot inherit old PDF annotations.
        lib=Library(directory);lib.set_primary_attachment(rid,worditem['id']);lib.close()
        with patch('document_conversion.preview_pdf',side_effect=RuntimeError('Test conversion unavailable')):
            reader.open(rid,record_read=False);wait(lambda:not reader.loading)
            assert reader.path is None and reader.count==0 and reader.image_size is None
        assert reader.close()
    # External links to executable files are never launched by the attachment reader.
    executable=directory/'unsafe.exe';executable.write_bytes(b'fixture')
    with patch('attachment_ui.os.startfile') as start:
        try:open_external(directory,{'path':'unsafe.exe'})
        except ValueError:pass
        else:raise AssertionError('Executable attachment should not launch')
        start.assert_not_called()
root.destroy()
print('Attachment reader passed: Word preview / independent comparison pages / main-file annotations / notes preservation / conversions and attachment linking / overwrite refusal / busy close guards / failed preview / 1120px layout')
