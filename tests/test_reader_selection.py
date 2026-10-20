"""Withdrawn reader checks. Drag calls use local widget coordinates, never desktop input."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from reader_ui import ReaderPage
from library_core import Library


class ReaderSelectionTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'build' / 'selection-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.directory = Path(self.tmp.name) / 'store'
        self.lib = Library(self.directory)
        self.rid = self.lib.save({'title': 'Selection fixture'})
        self.root = tk.Tk(); self.root.withdraw()
        self.reader = ReaderPage(self.root, self.directory, lambda _: None, lambda _: None)
        r = self.reader
        r.rid = self.rid; r.attachment_id = 'fixture'; r.path = Path('fixture.pdf')
        r.page = 1; r.count = 2; r.image_size = (300, 400); r.loading = False
        r.document_canvas.layout = {0: (18, 18, 300, 400), 1: (18, 460, 300, 400)}
        r.document_canvas.tops = [(18, 0), (460, 1)]
        r.document_canvas.cache = {0: (Image.new('RGB', (300, 400), 'red'), []),
                                   1: (Image.new('RGB', (300, 400), 'blue'), [])}
        r.canvas.configure(scrollregion=(0, 0, 360, 900))

    def tearDown(self):
        self.reader.dirty = False
        self.reader.close(); self.lib.close()
        self.root.destroy(); self.tmp.cleanup()

    def event(self, x, y):
        # Canvas transforms are patched to identity; these are document coordinates.
        return SimpleNamespace(x=x, y=y)

    def test_reverse_screenshot_crop_is_immediate_clipped_and_restores_selection(self):
        r = self.reader
        with patch.object(r.canvas, 'canvasx', side_effect=lambda x: x), patch.object(r.canvas, 'canvasy', side_effect=lambda y: y), \
             patch.object(r, 'insert_note_image') as insert, patch.object(r, 'add_point_marker') as marker, \
             patch('reader_ui.region_text', side_effect=AssertionError('Screenshot must not extract text')):
            r.screenshot_tool()
            r.begin_selection(self.event(218, 760))
            r.move_selection(self.event(-80, 400))
            self.assertTrue(r.canvas.find_withtag('rubber-band'))
            r.end_selection(self.event(-80, 400))
            image = insert.call_args.args[0]
            self.assertEqual(image.size, (200, 300))
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))
            self.assertEqual(r.last_selection['page'], 1)
            self.assertEqual(r.last_selection['rect'], [0, 0, 2/3, .75])
            self.assertEqual(r.tool.get(), '选择文字')
            self.assertFalse(r.canvas.find_withtag('rubber-band'))
            marker.assert_called_once()
            self.assertTrue(r.events.empty())

    def test_page_gaps_outside_start_tiny_boxes_and_escape_do_not_crop(self):
        r = self.reader
        with patch.object(r.canvas, 'canvasx', side_effect=lambda x: x), patch.object(r.canvas, 'canvasy', side_effect=lambda y: y), \
             patch.object(r, 'insert_note_image') as insert:
            r.screenshot_tool()
            for start, end in [((5, 100), (100, 200)), ((50, 440), (100, 500)), ((50, 500), (51, 501))]:
                r.begin_selection(self.event(*start)); r.end_selection(self.event(*end))
            insert.assert_not_called()
            r.begin_selection(self.event(50, 500));r.move_selection(self.event(100, 600))
            r.cancel_box_selection()
            r.end_selection(self.event(100, 600))
            insert.assert_not_called()
            with self.assertRaises(ValueError):r.document_canvas.screenshot(1, [0, 0, 0, 0])

    def test_chat_image_retains_box_without_saving_note_and_rejects_stale_attachment(self):
        r = self.reader
        with patch.object(r.canvas, 'canvasx', side_effect=lambda x: x), patch.object(r.canvas, 'canvasy', side_effect=lambda y: y), \
             patch.object(r, 'insert_note_image') as insert, patch.object(r, 'open_chat') as chat:
            r.chat_image_tool();r.begin_selection(self.event(50, 500));r.end_selection(self.event(150, 600))
            insert.assert_not_called()
            self.assertEqual(r.tool.get(), '选择文字')
            r.chat_selected_image()
            self.assertEqual(chat.call_args.kwargs['image'].size, (100, 100))
            self.assertEqual(chat.call_args.kwargs['page'], 1)
            r.attachment_id = 'changed'
            self.assertIsNone(r.current_selection())
            r.chat_selected_text()
            self.assertIn('先选中文字', r.status.get())

    def test_open_chat_uses_bridge_and_mocked_browser_only(self):
        r = self.reader
        bridge = Mock(); bridge.prepare.return_value = 'https://chatgpt.com/#paperquick=fixture'
        bridge.prepare.return_value='https://chatgpt.com/#paperquick=54321.'+'a'*43
        bridge.open_url.return_value='http://127.0.0.1:54321/handoff/'+'a'*43+'/open'
        bridge.status.return_value={'state':'waiting-extension','detail':''}
        r._chat_bridge = bridge
        with patch('webbrowser.open', return_value=True) as browser:
            r.open_chat(quote='selected quotation', page=1)
        bridge.prepare.assert_called_once_with(self.rid, quote='selected quotation', image=None, page=1,anchor={'rect':[.06,.06,.06,.06],'quote':'selected quotation'})
        browser.assert_called_once_with(bridge.open_url.return_value)

    def test_cross_page_text_selection_crops_both_pages_in_reading_order(self):
        r=self.reader;dc=r.document_canvas
        first=[{'text':'A','rect':[.1,.1,.3,.2]}, {'text':'B','rect':[.2,.8,.6,.9]}]
        second=[{'text':'C','rect':[.1,.1,.5,.2]}, {'text':'D','rect':[.2,.5,.6,.6]}]
        dc.cache[0]=(dc.cache[0][0],first);dc.cache[1]=(dc.cache[1][0],second)
        for endpoints in [((0,1),(1,0)),((1,0),(0,1))]:
            dc.selection=endpoints;dc.selection_text={0:first,1:second}
            with patch.object(dc,'move'):
                dc.finish(self.event(0,0))
            item=r.last_selection
            self.assertEqual(item['quote'],'B\nC')
            self.assertEqual([region['page'] for region in item['regions']],[0,1])
            r.context_page=1  # Right-click on the second page must retain the entire selection.
            self.assertIs(r.current_selection(),item)
            with patch.object(r,'insert_note_image') as insert,patch.object(r,'add_point_marker'):
                r.selection_screenshot()
            image=insert.call_args.args[0]
            self.assertEqual(image.size,(120,96))
            self.assertEqual(image.getpixel((10,10)),(255,0,0))
            self.assertEqual(image.getpixel((10,80)),(0,0,255))

    def test_evicted_middle_page_is_loaded_instead_of_silently_omitted(self):
        r=self.reader;dc=r.document_canvas
        first=[{'text':'First','rect':[.1,.1,.4,.2]}]
        middle=[{'text':'Middle','rect':[.1,.1,.4,.2]}]
        last=[{'text':'Last','rect':[.1,.1,.4,.2]}]
        dc.layout[2]=(18,900,300,400)
        dc.cache={0:(Image.new('RGB',(300,400),'red'),first),2:(Image.new('RGB',(300,400),'blue'),last)}
        dc.selection=((0,0),(2,0));dc.selection_text={0:first,2:last}
        with patch.object(dc,'move'),patch('reader_canvas.render_page_data',return_value=(Image.new('RGB',(300,400),'green'),middle)) as render:
            dc.finish(self.event(0,0))
            self.assertEqual(r.last_selection['quote'],'First\nMiddle\nLast')
            image=dc.selection_image(r.last_selection)
            self.assertEqual(image.size,(90,152))
            self.assertEqual(image.getpixel((5,70)),(0,128,0))
            self.assertEqual(image.getpixel((5,140)),(0,0,255))
            self.assertEqual(render.call_count,2)

    def test_saved_long_note_image_keeps_lower_pages_and_does_not_resize_input(self):
        r=self.reader
        image=Image.new('RGB',(500,3000),'red')
        image.paste(Image.new('RGB',(500,1500),'blue'),(0,1500))
        r.insert_note_image(image)
        saved=next(iter(r.note_images.values()))
        with Image.open(self.directory/saved['path']) as stored:
            self.assertEqual(stored.size,(500,3000))
            self.assertEqual(stored.getpixel((100,2800)),(0,0,255))
        self.assertEqual(image.size,(500,3000))


if __name__ == '__main__': unittest.main()
