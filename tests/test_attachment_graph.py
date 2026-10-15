from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from library_core import Library
from graph_ui import GraphPage
from reader_ui import ReaderPage
from test_library_documents import pdf


class AttachmentGraphTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / 'build' / 'attachment-graph-tests'
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.base = Path(self.tmp.name)
        self.lib = Library(self.base / 'store')
        main = self.base / 'main.pdf'; pdf(main, 'Main paper')
        self.rid = self.lib.import_pdf(main)
        self.extra = self.base / 'extra.pdf'; pdf(self.extra, 'Another article')
        self.lib.add_attachment(self.rid, self.extra, label='Associated article')
        self.item = next(a for a in self.lib.get(self.rid)['attachments'] if a['role'] == 'supplement')

    def tearDown(self):
        self.lib.close(); self.tmp.cleanup()

    def test_attachment_nodes_and_edges_follow_add_remove_and_existing_papers(self):
        graph = self.lib.graph(include_candidates=False)
        nodes = [n for n in graph['nodes'] if n.get('kind') == 'attachment']
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]['attachment_id'], self.item['id'])
        self.assertEqual(nodes[0]['title'], 'Associated article')
        self.assertTrue(any(e['source'] == self.rid and e['target'] == nodes[0]['id'] and e['kind'] == 'attachment' for e in graph['edges']))
        self.assertEqual(graph['summary']['total'], 1)
        # The same bytes as an existing independent article should connect paper to paper.
        other = self.lib.save({'title': 'Existing article'})
        self.lib.add_attachment(other, self.extra, role='primary')
        graph = self.lib.graph(include_candidates=False)
        self.assertFalse(any(n.get('kind') == 'attachment' for n in graph['nodes']))
        self.assertTrue(any(e['source'] == self.rid and e['target'] == other and e['kind'] == 'attachment' for e in graph['edges']))
        with self.lib.db:self.lib.db.execute('DELETE FROM attachments WHERE id=?', (self.item['id'],))
        self.assertFalse(any(e['kind'] == 'attachment' for e in self.lib.graph()['edges']))

    def make_page(self):
        page = GraphPage.__new__(GraphPage)
        page.directory = self.lib.root
        page.data = self.lib.graph(include_candidates=False)
        page.records = {r['id']: r for r in self.lib.records()}
        page.selected = self.rid
        page.info = Mock(); page.status = Mock(); page.draw = Mock(); page.zoom_at = Mock()
        page.on_attachment = Mock(); page.on_reader = Mock()
        attachment_node = next(n for n in page.data['nodes'] if n.get('kind') == 'attachment')
        page.canvas = Mock()
        page.canvas.find_overlapping.return_value = (7,)
        page.canvas.gettags.return_value = ('node', attachment_node['id'])
        return page, attachment_node

    def test_double_click_opens_the_clicked_attachment_not_stale_selection(self):
        page, node = self.make_page()
        page.double_click(SimpleNamespace(x=10, y=20))
        self.assertEqual(page.selected, node['id'])
        page.on_attachment.assert_called_once()
        self.assertEqual(page.on_attachment.call_args.args[0], self.rid)
        self.assertEqual(page.on_attachment.call_args.args[1]['id'], self.item['id'])
        page.on_reader.assert_not_called()

    def test_context_open_uses_the_same_correct_reader_route(self):
        page, node = self.make_page(); page.frame = Mock()
        menu = Mock(); commands = []
        menu.add_command.side_effect = lambda **kw: commands.append(kw['command'])
        menu.tk_popup.side_effect = lambda *_: commands[0]()
        with patch('graph_ui.tk.Menu', return_value=menu):
            page.context_menu(SimpleNamespace(x=1, y=2, x_root=3, y_root=4))
        page.on_attachment.assert_called_once()
        self.assertEqual(page.selected, node['id'])
        menu.destroy.assert_not_called()  # The posted menu must remain available to click.

    def test_removed_attachment_cannot_open_a_stale_graph_node(self):
        page, node = self.make_page(); page.selected = node['id']
        with self.lib.db:self.lib.db.execute('DELETE FROM attachments WHERE id=?', (self.item['id'],))
        page.open_pdf()
        page.on_attachment.assert_not_called()
        self.assertIn('附件已移除', page.info.set.call_args.args[0])

    def test_reading_attachment_changes_request_a_graph_refresh(self):
        primary = self.lib.primary_attachment(self.rid)
        reader = SimpleNamespace(rid=self.rid, directory=self.lib.root, attachment_id=primary['id'],
                                 comparison=None, on_library_changed=Mock())
        ReaderPage.attachments_changed(reader)
        reader.on_library_changed.assert_called_once()
        busy = SimpleNamespace(busy=True)
        GraphPage.refresh(busy)
        self.assertTrue(busy._refresh_pending)


if __name__ == '__main__': unittest.main()
