"""Action rows must wrap inside their own content area, including frame padding."""
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

import ui_theme
from ui_widgets import flow_bar


class FlowBarTests(unittest.TestCase):
    def test_hidden_action_rows_fit_inside_all_padding_forms(self):
        root = tk.Tk()
        root.withdraw()
        with patch('ui_theme.window_chrome'):
            try:
                ui_theme.install_theme(root)
                for padding, right in ((24, 24), ((24, 8), 24),
                                       ((24, 4, 32), 32), ((24, 4, 24, 8), 24)):
                    with self.subTest(padding=padding):
                        frame = ttk.Frame(root, padding=padding)
                        buttons = [ttk.Button(frame, text='导入文件夹', width=9) for _ in range(5)]
                        for button in buttons:
                            button.pack(side='left')
                        root.update_idletasks()
                        # Three buttons fit the outer width but not the padded content.
                        width = 3 * (buttons[0].winfo_reqwidth() + 6) + 12
                        frame.place(x=0, y=0, width=width, height=240)
                        flow_bar(frame)
                        root.update_idletasks()
                        self.assertNotEqual(buttons[0].grid_info()['in'], buttons[2].grid_info()['in'])
                        for button in buttons:
                            self.assertGreaterEqual(button.winfo_x(), 24)
                            self.assertLessEqual(button.winfo_x() + button.winfo_width(), width - right)
                        self.assertEqual(root.state(), 'withdrawn')
                        frame.destroy()
            finally:
                for job in root.tk.splitlist(root.tk.call('after', 'info')):
                    root.tk.call('after', 'cancel', job)
                root.destroy()

    def test_mixed_button_widths_reflow_without_shared_column_expansion(self):
        root = tk.Tk()
        root.withdraw()
        with patch('ui_theme.window_chrome'):
            try:
                ui_theme.install_theme(root)
                frame = ttk.Frame(root, padding=(24, 4, 24, 8))
                buttons = [ttk.Button(frame, text='操作', width=width) for width in (8, 18, 18, 8)]
                for button in buttons:
                    button.pack(side='left')
                root.update_idletasks()
                small, large = (buttons[index].winfo_reqwidth() for index in (0, 1))
                narrow = small + large + 2 * 6 + 2 + 48
                wide = 2 * (small + large) + 4 * 6 + 2 + 48
                frame.place(x=0, y=0, width=narrow, height=240)
                flow_bar(frame)
                heights = []
                for width in (narrow, wide, narrow):
                    frame.place_configure(width=width)
                    root.update_idletasks()
                    heights.append(frame.winfo_reqheight())
                    for button in buttons:
                        self.assertIs(button.master, frame)
                        self.assertGreaterEqual(button.winfo_x(), 24)
                        self.assertLessEqual(button.winfo_x() + button.winfo_width(), width - 24)
                    row_count = len({str(button.grid_info()['in']) for button in buttons})
                    self.assertEqual(row_count, 2 if width == narrow else 1)
                self.assertGreater(heights[0], heights[1])
                self.assertEqual(heights[0], heights[2])
                self.assertEqual(root.state(), 'withdrawn')
                frame.destroy()
                self.assertTrue(all(not button.winfo_exists() for button in buttons))
            finally:
                for job in root.tk.splitlist(root.tk.call('after', 'info')):
                    root.tk.call('after', 'cancel', job)
                root.destroy()


if __name__ == '__main__':
    unittest.main()
