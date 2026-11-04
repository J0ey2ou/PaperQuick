"""Delayed local work must not keep a destroyed Tk reading page alive."""
import gc
from pathlib import Path
import tempfile
import threading
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

from library_core import Library
from reader_ui import ReaderPage
from test_fulltext_index import make_pdf


class ReaderWorkerLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.base=Path(self.temporary.name)
        self.directory=self.base/'library';self.library=Library(self.directory)
        self.root=tk.Tk();self.root.withdraw();self.pending=[]

    def tearDown(self):
        try:self.root.destroy()
        except tk.TclError:pass
        self.library.close();self.temporary.cleanup()

    def queue_thread(self,*,target,daemon):
        self.pending.append(target)
        return SimpleNamespace(start=lambda:None)

    def release_reader(self,reader):
        events=reader.events;reference=weakref.ref(reader)
        self.assertTrue(reader.close());self.root.destroy()
        # Dispose only this test interpreter's variable callbacks. Tcl trace
        # commands can otherwise retain the page after widgets are destroyed;
        # they are independent from the queued worker ownership tested here.
        for value in gc.get_objects():
            if isinstance(value,tk.Variable) and value._tk is self.root.tk:
                for modes,command in value.trace_info():
                    value.trace_remove(modes,command)
        return events,reference

    def finish_worker(self):
        self.assertEqual(len(self.pending),1)
        # Keep the real worker alive until after the main thread has reclaimed
        # the reader. No Tk calls are legal when this delayed work completes.
        worker=threading.Thread(target=self.pending.pop(),daemon=True)
        worker.start();worker.join(10)
        self.assertFalse(worker.is_alive())

    def test_document_preparation_completes_after_main_thread_releases_reader(self):
        for extension in ('.txt','.pdf'):
            with self.subTest(extension=extension):
                if extension=='.pdf':self.root=tk.Tk();self.root.withdraw()
                source=self.base/('source'+extension)
                if extension=='.pdf':make_pdf(source,['Delayed PDF body'])
                else:source.write_text('Delayed text body','utf-8')
                rid=self.library.import_document(source)
                reader=ReaderPage(self.root,self.directory,lambda _:None,lambda _:None)
                with patch('reader_ui.threading.Thread',side_effect=self.queue_thread):reader.open(rid)
                events,reference=self.release_reader(reader);del reader;gc.collect()
                self.assertIsNone(reference(),'Queued document work still owns the Tk reader')
                self.finish_worker()
                messages=[]
                while not events.empty():messages.append(events.get_nowait())
                kinds=[item[0] for item in messages]
                self.assertNotIn('error',kinds)
                self.assertIn('logical-document' if extension=='.txt' else 'prepared',kinds)

    def test_page_render_completes_after_main_thread_releases_reader(self):
        source=self.base/'render.pdf';make_pdf(source,['Deferred page'])
        rid=self.library.import_document(source)
        reader=ReaderPage(self.root,self.directory,lambda _:None,lambda _:None)
        with patch('reader_ui.threading.Thread',side_effect=self.queue_thread):
            reader.open(rid,anchor={'page':0,'scale':1.2})
            reader.fit_pending=False
            self.pending.pop()();reader.poll()
            self.assertFalse(reader.loading)
            reader.render()
        events,reference=self.release_reader(reader);del reader;gc.collect()
        self.assertIsNone(reference(),'Queued rendering work still owns the Tk reader')
        self.finish_worker()
        message=events.get_nowait();self.assertEqual(message[0],'page')
        self.assertEqual(message[2][1],0)

    def test_initial_fit_renders_at_viewport_width_once(self):
        from pdf_reader_core import render_page_data
        source=self.base/'first-frame.pdf';make_pdf(source,['First frame'])
        rid=self.library.import_document(source)
        reader=ReaderPage(self.root,self.directory,lambda _:None,lambda _:None)
        try:
            with patch('reader_ui.threading.Thread',side_effect=self.queue_thread),patch.object(reader.canvas,'winfo_width',return_value=1000),patch('pdf_reader_core.render_page_data',wraps=render_page_data) as render:
                reader.open(rid)
                self.pending.pop()();reader.poll()
                self.assertFalse(reader.fit_pending)
                self.assertAlmostEqual(reader.scale,1.6)
                self.assertEqual(render.call_count,1)
                self.assertFalse(reader.loading)
        finally:reader.close()

    def test_replaced_file_between_worker_and_poll_drops_stale_preparation(self):
        import os
        source=self.base/'replaced.pdf';make_pdf(source,['Original frame'])
        rid=self.library.import_document(source)
        reader=ReaderPage(self.root,self.directory,lambda _:None,lambda _:None)
        try:
            with patch('reader_ui.threading.Thread',side_effect=self.queue_thread):
                reader.open(rid);self.pending.pop()()
                replacement=self.base/'replacement.pdf';make_pdf(replacement,['Changed frame'])
                os.replace(replacement,reader.source_path)
                reader.poll()
            self.assertIsNone(reader.path)
            self.assertEqual(reader.document_canvas.layout,{})
            self.assertFalse(reader.loading)
            self.assertIn('已改变',reader.status.get())
        finally:reader.close()

    def test_visible_page_worker_does_not_retain_canvas_or_reader(self):
        source=self.base/'continuous.pdf';make_pdf(source,['Visible page'])
        rid=self.library.import_document(source)
        reader=ReaderPage(self.root,self.directory,lambda _:None,lambda _:None)
        with patch('reader_ui.threading.Thread',side_effect=self.queue_thread):
            reader.open(rid,anchor={'page':0,'scale':1.2});reader.fit_pending=False
            self.pending.pop()();reader.poll()
            reader.document_canvas.cache.clear();reader.document_canvas.load_visible()
        canvas=weakref.ref(reader.document_canvas)
        events,reference=self.release_reader(reader);del reader;gc.collect()
        self.assertIsNone(reference(),'Queued visible-page work still owns the Tk reader')
        self.assertIsNone(canvas(),'Queued visible-page work still owns the document canvas')
        self.finish_worker()
        # Closing cancels unstarted viewport work as well as releasing Tk.
        self.assertTrue(events.empty())


if __name__=='__main__':unittest.main()
