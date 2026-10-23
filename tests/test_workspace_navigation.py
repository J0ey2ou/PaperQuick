"""All five primary sections stay reachable in an isolated minimum-width layout."""
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

import app


class WorkspaceNavigationTests(unittest.TestCase):
    def test_five_sections_and_right_actions_fit_minimum_width_at_150_percent(self):
        with tempfile.TemporaryDirectory() as temporary, patch('app.app_dir', return_value=Path(temporary)), patch.object(app.App, 'start_selection_helper') as helper:
            root = tk.Tk();root.withdraw();root.tk.call('tk', 'scaling', 1.5)
            instance = app.App(root)
            try:
                navigation = instance.navigation
                navigation.pack_forget()
                # Keep the actual application hidden; only its owned navigation
                # frame receives the inner width of a 1120px window.
                navigation.place(x=0, y=0, width=1120-52, height=navigation.winfo_reqheight())
                root.update_idletasks()
                navigation.place_configure(height=navigation.winfo_reqheight())
                root.update_idletasks()
                self.assertEqual(set(instance.nav_buttons), {'workspace', 'query', 'library', 'graph', 'reader'})
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                actions = [child for child in descendants(navigation)
                           if isinstance(child, ttk.Button) and child.cget('text') in ('设置', '阅读总结')]
                self.assertEqual(len(actions), 2)
                for button in [*instance.nav_buttons.values(), *actions]:
                    with self.subTest(button=button.cget('text')):
                        self.assertTrue(str(button.cget('command')))
                        self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
                        current = button
                        while current is not navigation:
                            self.assertGreaterEqual(current.winfo_x(), 0)
                            self.assertLessEqual(current.winfo_x()+current.winfo_width(), current.master.winfo_width(),
                                                 f'{button.cget("text")} exceeds {current.master}')
                            self.assertGreaterEqual(current.winfo_y(), 0)
                            self.assertLessEqual(current.winfo_y()+current.winfo_height(), current.master.winfo_height())
                            current = current.master
                self.assertEqual(root.state(), 'withdrawn')
                helper.assert_not_called()
            finally:instance.close()


if __name__ == '__main__':unittest.main()
