from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from library_core import Library
from graph_selection import region_members
from graph_ui import GraphPage


class GraphGroupTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'build'/'graph-group-tests';root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root);self.directory=Path(self.tmp.name)/'store';self.lib=Library(self.directory)
        self.one=self.lib.save({'title':'First paper'});self.two=self.lib.save({'title':'Second paper'});self.three=self.lib.save({'title':'Third paper'})

    def tearDown(self):self.lib.close();self.tmp.cleanup()

    def test_box_and_ellipse_use_actual_shape_with_reversed_drag(self):
        points={'center':(5,5),'corner':(0,0),'edge':(5,0),'outside':(12,4)}
        self.assertEqual(set(region_members(points,(10,10),(0,0))),{'center','corner','edge'})
        self.assertEqual(set(region_members(points,(10,10),(0,0),'ellipse')),{'center','edge'})
        self.assertEqual(region_members(points,(1,1),(1,10)),[])

    def test_region_selection_only_names_visible_library_papers(self):
        graph=SimpleNamespace(drag='select-ellipse',drag_start=(0,0),
              visible_nodes=[{'id':self.one},{'id':self.two},{'id':'candidate'},{'id':'attachment-x'}],
              records={self.one:{},self.two:{},self.three:{}},positions={self.one:(5,5),self.two:(5,0),self.three:(5,5),'candidate':(5,5),'attachment-x':(5,5)},
              selected=None,draw=Mock(),status=Mock(),name_selection=Mock())
        graph.position=lambda rid:graph.positions[rid]
        GraphPage.release(graph,SimpleNamespace(x=10,y=10))
        self.assertEqual(graph.selection_ids,{self.one,self.two});self.assertEqual(graph.selection_shape,'ellipse')
        graph.name_selection.assert_called_once()

    def test_groups_survive_restart_filtering_and_rename_without_changing_papers(self):
        before=self.lib.records()
        gid=self.lib.create_graph_group([self.one,self.two,self.one],'同一队列，结果相互补充','ellipse')
        self.lib.close();self.lib=Library(self.directory)
        groups=self.lib.graph(include_candidates=False)['groups']
        self.assertEqual(len(groups),1);self.assertEqual(set(groups[0]['members']),{self.one,self.two})
        self.assertEqual(groups[0]['shape'],'ellipse')
        self.lib.rename_graph_group(gid,'比较不同模型')
        self.assertEqual(self.lib.graph_groups({self.one})[0]['members'],[self.one])
        self.assertEqual(self.lib.graph_groups()[0]['label'],'比较不同模型')
        self.lib.remove_graph_group(gid)
        self.assertEqual(self.lib.graph_groups(),[]);self.assertEqual(self.lib.records(),before)

    def test_deleted_group_member_returns_when_paper_is_restored(self):
        self.lib.create_graph_group([self.one,self.two],'方法相关')
        self.lib.remove_papers([self.two])
        self.assertEqual(self.lib.graph_groups()[0]['members'],[self.one])
        self.lib.restore_removed()
        self.assertEqual(set(self.lib.graph_groups()[0]['members']),{self.one,self.two})

    def test_manual_edges_are_named_idempotent_and_reject_invalid_pairs(self):
        self.lib.relate(self.one,self.two,'同一研究问题')
        self.lib.relate(self.two,self.one,'同一研究问题')
        self.lib.relate(self.one,self.two,'不同方法对照')
        edges=[e for e in self.lib.graph()['edges'] if e['kind']=='related']
        self.assertEqual({e['label'] for e in edges},{'同一研究问题','不同方法对照'})
        self.assertEqual(len(edges),2)
        for first,second,label in ((self.one,self.one,'self'),(self.one,self.two,' '),(self.one,'missing','why')):
            with self.assertRaises(ValueError):self.lib.relate(first,second,label)
        with self.assertRaises(ValueError):self.lib.create_graph_group([self.one],'单篇')


if __name__=='__main__':unittest.main()
