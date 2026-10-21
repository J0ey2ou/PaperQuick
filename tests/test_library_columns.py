import tempfile
from pathlib import Path
import tkinter as tk
import unittest
from library_core import Library
from library_table import TableState,ColumnFilter,values
from library_ui import LibraryWindow


class ColumnTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.lib=Library(Path(self.tmp.name)/'store')
        self.ids=[self.lib.save({'title':title,'year':year,'tags':tags,'rating':rating,'status':state}) for title,year,tags,rating,state in [('Zebra','2009',['医学'],1,'在读'),('Alpha','2024',['方法','医学'],5,'已读'),('Beta','',['方法'],0,'未读')]]
        self.root=tk.Tk();self.root.withdraw();self.owner=LibraryWindow(self.root,self.lib.root)

    def tearDown(self):self.owner.close();self.root.destroy();self.lib.close();self.tmp.cleanup()

    def test_each_column_has_sort_and_year_rating_are_numeric(self):
        owner=self.owner
        for key in owner.tree['columns']:
            self.assertTrue(owner.tree.heading(key,'command'));owner.sort_column(key)
            self.assertEqual(len(owner.tree.get_children()),3)
        owner.table_state.sort_key=None;owner.sort_column('year');self.assertEqual(owner.tree.get_children(),tuple(self.ids))
        owner.sort_column('year');self.assertEqual(owner.tree.get_children(),(self.ids[1],self.ids[0],self.ids[2]))
        owner.sort_column('rating');self.assertEqual(owner.tree.get_children(),(self.ids[2],self.ids[0],self.ids[1]))

    def test_filter_multiple_columns_and_clear_without_losing_records(self):
        owner=self.owner;owner.table_state.filters={'tags':{'values':['医学']},'status':{'values':['已读']}}
        owner.refresh_records();self.assertEqual(owner.tree.get_children(),(self.ids[1],));self.assertIn('2 列',owner.filter_summary.get())
        self.assertIn('·',owner.tree.heading('status','text'));owner.clear_column_filters();self.assertEqual(len(owner.tree.get_children()),3)

    def test_dropdown_filters_by_contains_and_selected_values(self):
        popup=ColumnFilter(self.owner,'title',0,0);self.assertFalse(popup.win.winfo_ismapped())
        popup.query.set('alp');popup.apply();self.assertEqual(self.owner.tree.get_children(),(self.ids[1],))
        popup=ColumnFilter(self.owner,'title',0,0);popup.clear();self.assertEqual(len(self.owner.tree.get_children()),3)

    def test_top_filter_controls_are_replaced_and_unknown_year_stays_last(self):
        self.assertFalse(hasattr(self.owner,'tag_filter_box'))
        self.owner.table_state.filters={'year':{'values':['']}};self.owner.refresh_records();self.assertEqual(self.owner.tree.get_children(),(self.ids[2],))
