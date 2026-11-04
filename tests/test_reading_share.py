from pathlib import Path
import json
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
from reading_share import share_model, render_card, save_cards, card_count, paper_share_data, wrapped_lines, _font


class ShareTests(unittest.TestCase):
    def fixture(self,count=1):
        return {'kind':'paper' if count==1 else 'recap','date':'2026-11-04','seconds':1830,
                'papers':[{'title':f'文献 {i+1}：长期随访研究中的证据与思考','authors':'Example Research Team',
                           'doi':'10.0000/example','abstract':'这是用于界面验证的虚构摘要。研究设计与样本选择需要结合原文判断。'*5,
                           'notes':'private-note','annotations':[{'quote':'private-quote','text':'private-comment'}],
                           'attachments':[{'path':'private/library/paper.pdf'}],'note_images':['private/image.png'],
                           'seconds':300} for i in range(count)]}

    def test_private_content_is_opt_in_and_paths_never_export(self):
        public=share_model(self.fixture());encoded=json.dumps(public)
        self.assertNotIn('private',encoded)
        private=json.dumps(share_model(self.fixture(),include_notes=True))
        self.assertIn('private-note',private);self.assertIn('private-quote',private)
        self.assertNotIn('private/library',private);self.assertNotIn('private/image',private)
        self.assertNotIn('seconds',json.dumps(share_model(self.fixture(),include_time=False)))

    def test_every_paper_has_a_page_and_long_text_fits(self):
        data=self.fixture(9);model=share_model(data);self.assertEqual(card_count(model),3)
        for theme in ('书页花园','静夜书海'):
            with render_card(model,theme,2) as image:self.assertEqual(image.size,(1080,1600))
        data=self.fixture();data['papers'][0]['title']='很长的英文标题 LongTitleWithoutSpaces'*30
        data['papers'][0]['notes']='大量笔记\n'*1000
        with render_card(share_model(data,include_notes=True)) as image:self.assertEqual(image.mode,'RGB')
        with Image.new('RGB',(400,400)) as canvas:
            lines=wrapped_lines(ImageDraw.Draw(canvas),'研究标题'*500,_font(28),250,4)
            self.assertEqual(len(lines),4);self.assertTrue(lines[-1].endswith('…'))
            self.assertTrue(all(ImageDraw.Draw(canvas).textlength(line,font=_font(28))<=250 for line in lines))
            self.assertEqual(wrapped_lines(ImageDraw.Draw(canvas),'一\n二\n三',_font(28),250,2),['一','二…'])

    def test_png_export_is_local_paginated_and_preserves_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'share.png';model=share_model(self.fixture(5))
            paths=save_cards(model,target);self.assertEqual([p.name for p in paths],['share-01.png','share-02.png'])
            with Image.open(paths[0]) as image:self.assertEqual(image.info,{})
            original=paths[0].read_bytes()
            with self.assertRaises(FileExistsError):save_cards(model,target)
            self.assertEqual(paths[0].read_bytes(),original)

    def test_export_failure_cleans_only_its_new_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'share.png';sentinel=Path(folder)/'keep.txt';sentinel.write_text('keep')
            with patch('reading_share.render_card',side_effect=[Image.new('RGB',(10,10)),ValueError('fixture')]):
                with self.assertRaises(ValueError):save_cards(share_model(self.fixture(5)),target)
            self.assertFalse((Path(folder)/'share-01.png').exists())
            self.assertFalse((Path(folder)/'share-02.png').exists());self.assertEqual(sentinel.read_text(),'keep')

    def test_single_paper_uses_actual_sessions(self):
        from library_core import Library
        with tempfile.TemporaryDirectory() as folder:
            lib=Library(folder)
            try:
                rid=lib.save({'title':'Fixture'})
                with lib.db:lib.db.execute('INSERT INTO reading_sessions(paper,start,end) VALUES(?,?,?)',(rid,100,165))
                data=paper_share_data(lib,rid);self.assertEqual(data['seconds'],65)
                self.assertEqual(data['papers'][0]['title'],'Fixture')
            finally:lib.close()

    def test_hidden_preview_switch_and_close_during_pending_work(self):
        from ui_theme import install_theme
        from reading_share_ui import ShareDialog
        root=tk.Tk();root.withdraw();install_theme(root)
        dialog=None
        try:
            dialog=ShareDialog(root,self.fixture(5));dialog.win.withdraw()
            deadline=time.monotonic()+10
            while dialog.preview_image is None and time.monotonic()<deadline:root.update();time.sleep(.02)
            self.assertIsNotNone(dialog.preview_image)
            self.assertFalse(dialog.notes.get());dialog.theme.set('静夜书海');dialog.turn(1)
            deadline=time.monotonic()+10
            while (dialog.job or dialog._rendering) and time.monotonic()<deadline:root.update();time.sleep(.02)
            self.assertEqual(dialog.page_text.get(),'2 / 2 张')
            dialog.caption.set('新的寄语');dialog.close();root.update()
            self.assertTrue(dialog.closed)
        finally:
            if dialog:dialog.close()
            root.destroy()


if __name__=='__main__':unittest.main()
