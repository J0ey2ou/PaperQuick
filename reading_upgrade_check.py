"""Frozen v3.9.2 verification: isolated files and withdrawn widgets only."""
from pathlib import Path
import json
import hashlib
import shutil
import sys
import time
import uuid


def run(destination):
    progress=Path(destination).with_suffix('.progress.txt')
    def stage(name):progress.write_text(name+'\n',encoding='utf-8')
    stage('imports')
    from contextlib import ExitStack
    from unittest.mock import patch
    import tkinter as tk
    from tkinter import ttk
    from app_version import VERSION
    from library_core import Library
    from fulltext_index import FulltextIndex
    from reading_share import paper_share_data, share_model, save_cards
    from reading_share_ui import ShareDialog
    from ui_theme import install_theme
    from sidebar_notebook import SidebarNotebook
    from pdf_reader_core import page_sizes, render_page_data
    from pypdf import PdfWriter
    report=Path(destination).resolve();report.parent.mkdir(parents=True,exist_ok=True)
    folder=report.parent/('reading-upgrade-check-'+uuid.uuid4().hex);folder.mkdir()
    root=None
    def forbidden(*args,**kwargs):raise AssertionError('Desktop interaction forbidden in bundle check')
    try:
        with ExitStack() as stack:
            for name in ('focus_set','focus_force','lift','tkraise'):stack.enter_context(patch.object(tk.Misc,name,lambda *a,**k:None))
            for name in ('clipboard_append','clipboard_clear','clipboard_get'):stack.enter_context(patch.object(tk.Misc,name,forbidden))
            stack.enter_context(patch('webbrowser.open',forbidden));stack.enter_context(patch('ui_theme.window_chrome'))
            stack.enter_context(patch('embedded_chat.EmbeddedChat.open',forbidden))
            stack.enter_context(patch.object(tk.Wm,'deiconify',lambda *a,**k:None))
            original_top=tk.Toplevel.__init__
            def hidden_top(window,*args,**kwargs):original_top(window,*args,**kwargs);window.withdraw()
            stack.enter_context(patch.object(tk.Toplevel,'__init__',hidden_top))
            stage('hidden-tk');root=tk.Tk();root.withdraw();install_theme(root)
            errors=[];root.report_callback_exception=lambda *args:errors.append(str(args[1]))
            stage('library');lib=Library(folder/'store')
            try:
                source=folder/'fixture.txt';source.write_text('Research evidence fixture for reading share.','utf-8')
                rid=lib.import_document(source);lib.save({'notes':'Private notes retained'},rid=rid)
                assert len(lib.records(summary=True))==1 and 'notes' not in lib.records(summary=True)[0]
                FulltextIndex(lib.root).update();assert FulltextIndex(lib.root).search('evidence',rid=rid)
                data=paper_share_data(lib,rid)
            finally:lib.close()
            stage('share-export')
            for theme in ('书页花园','静夜书海'):
                paths=save_cards(share_model(data),folder/(theme+'.png'),theme)
                assert paths[0].stat().st_size>10000
            stage('hidden-share-preview');notebook=SidebarNotebook(root);notebook.pack()
            pages=[ttk.Frame(notebook) for _ in range(7)]
            for n,page in enumerate(pages):notebook.add(page,text='测试页面'+str(n))
            notebook.select(pages[5]);root.update();assert notebook.select()==str(pages[5])
            dialog=ShareDialog(root,data);dialog.win.withdraw();deadline=time.monotonic()+10
            while dialog.preview_image is None and time.monotonic()<deadline:root.update();time.sleep(.02)
            assert dialog.preview_image is not None,dialog.status.get();dialog.close()
            stage('compact-attachment-reader')
            from reader_ui import ReaderPage
            reader=ReaderPage(root,folder/'store',lambda _:None,lambda _:None,compact=True)
            reader.frame.pack(fill='both',expand=True);reader.open(rid)
            deadline=time.monotonic()+10
            while reader.loading and time.monotonic()<deadline:root.update();time.sleep(.02)
            assert not reader.loading and reader.text_view is not None
            assert not reader.header.winfo_manager()
            reader.close()
            stage('pdfium');pdf=folder/'fixture.pdf';writer=PdfWriter();writer.add_blank_page(300,400)
            with pdf.open('wb') as stream:writer.write(stream)
            assert page_sizes(pdf)==[(300.0,400.0)]
            image,chars=render_page_data(pdf,0,1);assert image.size==(300,400);image.close()
            from reader_render_queue import PageRenderQueue
            native=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'embedded-browser/EmbeddedChat.exe'
            assert native.is_file()
            assert not errors,errors
            stage('cleanup');root.destroy();root=None
        report.write_text(json.dumps({'passed':True,'frozen':bool(getattr(sys,'frozen',False)),'version':VERSION,
            'binary_sha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
            'embedded_sha256':hashlib.sha256(native.read_bytes()).hexdigest(),
            'background_only':True,'native_webview_run':False,
            'checks':['lightweight library migration','scoped fulltext search','both share artwork assets','private fields omitted',
                      'local PNG export','hidden seven-page sidebar','hidden share preview','PDFium cached rendering',
                      'bounded render queue import','compact attachment reader','native chat helper bundled']},ensure_ascii=False,indent=2),'utf-8')
        stage('complete')
    finally:
        if root:
            try:root.destroy()
            except tk.TclError:pass
        if folder.resolve().parent==report.parent and folder.name.startswith('reading-upgrade-check-'):
            shutil.rmtree(folder)
