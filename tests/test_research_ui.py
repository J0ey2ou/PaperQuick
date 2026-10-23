"""Research workflow through hidden dialogs, with no desktop or clipboard calls."""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from library_core import Library
from research_ui import ResearchWindow
import ui_theme


class ResearchUITests(unittest.TestCase):
    def test_hidden_evidence_matrix_outline_and_screening_editors(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/'library'; library = Library(directory)
            project = library.create_project('课题'); paper = library.save({'title': 'Hidden test paper'}, project)
            source = Path(temp)/'source.txt'; source.write_text('Test quote', encoding='utf-8')
            library.add_attachment(paper, source, role='primary'); attachment = library.primary_attachment(paper); library.close()
            root = tk.Tk(); root.withdraw(); ui_theme.install_theme(root); callback = Mock()
            window = ResearchWindow(root, directory, project, callback)
            try:
                self.assertEqual(len(window.tabs.tabs()), 5)
                dialog = window.new_card({'paper': paper, 'attachment': attachment['id'], 'page': 0, 'quote': 'Test quote', 'rect': [.1, .2, .3, .4]})
                dialog.texts['claim'].insert('1.0', 'A claim'); card = dialog.save()
                self.assertIsNotNone(card); self.assertFalse(card['verified']); self.assertEqual(card['rect'], [.1, .2, .3, .4])
                window.card_tree.selection_set(card['id']); window.open_source(); callback.assert_called_once_with(paper, attachment['id'], 0)
                matrix_dialog = window.new_matrix(); matrix_dialog.fields['name'].set('Comparison'); matrix = matrix_dialog.save()
                self.assertIsNotNone(matrix); window.matrix_tree.selection_set(paper)
                cell = window.edit_cell(); cell.texts['body'].insert('1.0', 'Compared result'); cell.evidence_box.selection_set(0); self.assertIsNotNone(cell.save())
                outline = window.new_section(); outline.fields['title'].set('结论'); outline.texts['body'].insert('1.0', 'Draft paragraph'); outline.evidence_box.selection_set(0); section = outline.save()
                self.assertEqual(section['evidence'], [card['id']])
                window.screen_tree.selection_set(paper); screen = window.screen_editor(); screen.fields['decision'].set('纳入'); self.assertIsNotNone(screen.save())
                window.screen_tree.selection_set(paper); screen = window.screen_editor(); self.assertEqual(screen.fields['stage'].get(), '全文')
                screen.fields['decision'].set('排除'); screen.texts['reason'].insert('1.0', '不符合研究问题'); self.assertIsNotNone(screen.save())
                self.assertEqual(window.store.screening_counts(project)['full_text']['exclude'], 1)
                self.assertEqual(root.state(), 'withdrawn'); self.assertEqual(window.win.state(), 'withdrawn')
            finally:
                with patch('research_ui.messagebox.askyesno', return_value=True):
                    window.close()
                root.destroy()

    def test_export_declining_overwrite_and_unsaved_close_keep_data(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/'library'; library = Library(directory)
            project = library.create_project('课题'); library.save({'title': 'Paper'}, project); library.close()
            root = tk.Tk(); root.withdraw(); ui_theme.install_theme(root)
            window = ResearchWindow(root, directory, project)
            try:
                path = Path(temp)/'outline.md'; path.write_text('Old content', encoding='utf-8')
                with patch('research_ui.filedialog.asksaveasfilename', return_value=str(path)), patch('research_ui.messagebox.askyesno', return_value=False):
                    window.export_outline('md')
                self.assertEqual(path.read_text('utf-8'), 'Old content')
                editor = window.new_section(); editor.fields['title'].set('Unsaved')
                with patch('research_ui.messagebox.askyesno', return_value=False):
                    self.assertFalse(window.close()); self.assertFalse(window.closed)
                with patch('research_ui.messagebox.askyesno', return_value=True):
                    self.assertTrue(window.close())
            finally:
                if not window.closed:
                    with patch('research_ui.messagebox.askyesno', return_value=True):
                        window.close()
                root.destroy()


if __name__ == '__main__':
    unittest.main()
