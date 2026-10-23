from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
from library_core import Library
from graph_ui import GraphPage
from relations_ui import relationship_editor
import ui_theme


class GraphRelationshipUITests(unittest.TestCase):
    def test_hidden_graph_draws_named_regions_and_shared_editor_saves_relationship(self):
        base=Path(__file__).resolve().parents[1]/'build'/'graph-ui-tests';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temp:
            directory=Path(temp)/'store';lib=Library(directory)
            one=lib.save({'title':'Paper one'});two=lib.save({'title':'Paper two'})
            gid=lib.create_graph_group([one,two],'同一研究队列','ellipse')
            root=tk.Tk();root.withdraw()
            with patch('ui_theme.window_chrome'):
                try:
                    ui_theme.install_theme(root);page=GraphPage(root,directory)
                    page.data=lib.graph();page.records={r['id']:r for r in lib.records()};page.mode='network'
                    page.canvas.winfo_width=lambda:800;page.canvas.winfo_height=lambda:450
                    # This check concerns rendering and editing, so complete the
                    # real layout task deterministically and consume its queue
                    # explicitly instead of racing Tk timers against a deadline.
                    with patch('graph_ui.threading.Thread', side_effect=lambda *, target, daemon: SimpleNamespace(start=target)) as worker:
                        page.draw()
                        page.poll()
                    worker.assert_called_once()
                    self.assertFalse(page.layout_running)
                    self.assertTrue(page.canvas.find_withtag('group'))
                    callback=Mock();dialog=relationship_editor(root,directory,[one,two],callback);dialog.withdraw()
                    def children(widget):
                        for child in widget.winfo_children():
                            yield child;yield from children(child)
                    widgets=list(children(dialog))
                    reason=next(w for w in widgets if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox))
                    reason.insert(0,'方法对照')
                    button=next(w for w in widgets if isinstance(w,ttk.Button) and w.cget('text')=='保存关系')
                    button.invoke()
                    callback.assert_called_once()
                    self.assertEqual(lib.relation_edges({one,two})[0]['label'],'方法对照')
                    page.close()
                finally:
                    for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
                    lib.close();root.destroy()


if __name__=='__main__':unittest.main()
