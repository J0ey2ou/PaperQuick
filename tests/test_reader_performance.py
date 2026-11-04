"""Local synthetic PDFs and render scheduling; no windows or desktop input."""
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

import pdf_reader_core as core
from reader_render_queue import PageRenderQueue
from reading_documents import locate_word_comments
from test_fulltext_index import make_pdf


class ReaderCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name);self.path=self.root/'sample.pdf'
        make_pdf(self.path,['Original research text','Second page'])
        core.clear_document_cache()

    def tearDown(self):
        core.clear_document_cache();self.tmp.cleanup()

    def test_metadata_reopens_nothing_and_returns_independent_values(self):
        sizes=core.page_sizes(self.path);text=core.extract_text(self.path)
        annotations=core.original_pdf_annotations(self.path)
        sizes[0]=(1,1)
        with patch.object(core,'pdfium',side_effect=AssertionError('cache miss')):
            self.assertEqual(core.document_info(self.path),2)
            self.assertEqual(core.page_sizes(self.path)[0],(600,800))
            self.assertEqual(core.extract_text(self.path),text)
            self.assertEqual(core.original_pdf_annotations(self.path),annotations)

    def test_zoom_reuses_geometry_without_sharing_mutable_selection(self):
        image,chars=core.render_page_data(self.path,0,1)
        expected=core.page_characters(self.path,0)
        chars[0]['rect'][0]=999;chars[0]['text']='changed'
        with patch.object(core,'_page_characters',side_effect=AssertionError('re-extracted')):
            enlarged,again=core.render_page_data(self.path,0,1.5)
        self.assertEqual(again,expected)
        self.assertEqual(enlarged.size,(900,1200))
        self.assertEqual(image.size,(600,800))

    def test_same_path_replacement_invalidates_cached_text_geometry_and_sizes(self):
        core.page_sizes(self.path);core.extract_text(self.path);core.page_characters(self.path,0)
        before=core.file_version(self.path);old_stat=self.path.stat()
        replacement=self.root/'replacement.pdf';make_pdf(replacement,['Modified research text'])
        os.utime(replacement,ns=(old_stat.st_atime_ns,old_stat.st_mtime_ns))
        os.replace(replacement,self.path)
        self.assertNotEqual(core.file_version(self.path),before)
        self.assertEqual(len(core.page_sizes(self.path)),1)
        self.assertIn('Modified',core.extract_text(self.path))
        self.assertIn('Modified',''.join(c['text'] for c in core.page_characters(self.path,0)))
        self.assertTrue(all(key[1]!=before for key in core._CACHE))

    def test_rotated_geometry_and_fast_page_dimensions_match_bitmap(self):
        from pypdf import PdfWriter
        rotated=self.root/'rotated.pdf';writer=PdfWriter(clone_from=self.path)
        writer.pages[0].rotate(90);writer.write(rotated)
        image,chars=core.render_page_data(rotated,0,1)
        self.assertEqual(core.page_sizes(rotated)[0],image.size)
        self.assertEqual(image.size,(800,600))
        self.assertTrue(any(0<c['rect'][0]<c['rect'][2]<1 for c in chars))
        self.assertEqual(chars,core.render_page_data(rotated,0,.5)[1])
        self.assertIn('Original',core.region_text(rotated,0,[0,0,1,1]))

    def test_cropbox_and_rotation_keep_layout_dimensions_consistent(self):
        from pypdf import PdfWriter
        cropped=self.root/'cropped.pdf';writer=PdfWriter(clone_from=self.path)
        writer.pages[0].cropbox.lower_left=(20,100)
        writer.pages[0].cropbox.upper_right=(500,780)
        writer.pages[0].rotate(270);writer.write(cropped)
        image,chars=core.render_page_data(cropped,0,1)
        self.assertEqual(core.page_sizes(cropped)[0],image.size)
        self.assertEqual(image.size,(680,480))
        self.assertEqual(chars,core.page_characters(cropped,0))

    def test_changed_file_is_not_published_to_cache(self):
        version=core.file_version(self.path)
        with patch.object(core,'file_version',return_value=version+('changed',)):
            with self.assertRaises(ValueError):core._remember(self.path,version,'text','stale',100)
        self.assertIsNone(core._cached(('text',version,None)))

    def test_background_cancel_never_publishes_partial_text(self):
        calls=iter((False,False,True))
        with self.assertRaises(core.DocumentReadCancelled):core.extract_text(self.path,cancelled=lambda:next(calls))
        self.assertIsNone(core._cached(('text',core.file_version(self.path),None)))
        self.assertIn('Second page',core.extract_text(self.path))

    def test_cache_budget_evicts_old_results(self):
        version=core.file_version(self.path)
        with patch.object(core,'_CACHE_LIMIT',250):
            for page in range(5):core._remember(self.path,version,'chars',(page,),100,page)
        self.assertLessEqual(core._CACHE_BYTES,250)
        self.assertIsNone(core._cached(('chars',version,0)))

    def test_word_without_unlocated_comments_does_not_open_pdf(self):
        with patch.object(core,'pdfium',side_effect=AssertionError('unnecessary scan')):
            self.assertEqual(locate_word_comments([],self.path),[])
            comments=[{'page':0,'quote':'already located'}]
            self.assertIs(locate_word_comments(comments,self.path),comments)

    def test_preparation_rejects_mixed_metadata_and_image_revisions(self):
        original=core.render_page_data
        def replace_then_render(path,page,scale):
            replacement=self.root/'new.pdf';make_pdf(replacement,['Replacement document'])
            os.replace(replacement,self.path)
            return original(path,page,scale)
        with patch.object(core,'render_page_data',side_effect=replace_then_render):
            with self.assertRaises(core.DocumentChangedError):core.prepare_page(self.path,0)

    def test_preparation_uses_current_count_and_clamps_removed_page(self):
        count,page,*_=core.prepare_page(self.path,99)
        self.assertEqual((count,page),(2,1))

    def test_loading_zoom_never_dispatches_new_scale_with_old_layout(self):
        from reader_canvas import DocumentCanvas
        canvas=DocumentCanvas.__new__(DocumentCanvas)
        canvas.r=SimpleNamespace(closed=False,loading=True)
        canvas.layout={0:(0,0,10,10)};canvas.canvas=Mock()
        canvas.render_queue=Mock()
        canvas.load_visible()
        canvas.render_queue.request.assert_not_called()
        canvas.canvas.canvasy.assert_not_called()


class RenderQueueTests(unittest.TestCase):
    def test_file_revision_is_checked_before_and_after_render(self):
        for versions,calls in [([('new',)],0),([('old',),('new',)],1)]:
            events=queue.Queue();render=Mock(return_value=('image',[]))
            renderer=PageRenderQueue(render)
            with patch('reader_render_queue.file_version',side_effect=versions):
                renderer.request('unused',1,('unused',1,1,True,('old',)),1,[0],events)
                event=events.get(timeout=2)
            self.assertEqual(render.call_count,calls)
            self.assertIsNone(event[2][2]);self.assertIn('已改变',event[2][3])

    def test_new_viewport_replaces_queued_pages_and_drops_stale_result(self):
        entered=threading.Event();release=threading.Event();finished=threading.Event()
        calls=[];events=queue.Queue()
        def render(path,page,scale):
            calls.append(page)
            if page==0:entered.set();release.wait(3)
            if page==7:finished.set()
            return ('image',[])
        renderer=PageRenderQueue(render)
        renderer.request('unused',1,('sign',),1,[0,1,2],events)
        self.assertTrue(entered.wait(2))
        renderer.request('unused',1,('sign',),1,[8,7],events)
        release.set();self.assertTrue(finished.wait(2))
        self.assertEqual([events.get(timeout=2)[2][1] for _ in range(2)],[8,7])
        self.assertEqual(calls,[0,8,7]);self.assertTrue(events.empty())

    def test_cancel_discards_delayed_jobs_and_queue_is_bounded(self):
        targets=[];events=queue.Queue();calls=[]
        renderer=PageRenderQueue(lambda path,page,scale:calls.append(page))
        with patch('reader_render_queue.threading.Thread') as thread:
            thread.side_effect=lambda *,target,daemon: type('Delayed',(),{'start':lambda self:targets.append(target)})()
            renderer.request('unused',1,('old',),1,list(range(100)),events)
        self.assertEqual(len(renderer.jobs),8)
        renderer.cancel();targets.pop()()
        self.assertEqual(calls,[]);self.assertTrue(events.empty())


if __name__=='__main__':unittest.main()
