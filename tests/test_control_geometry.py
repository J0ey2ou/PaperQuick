"""Hidden-widget regression checks for clipped icons and semantic surfaces."""
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from PIL import ImageTk
import ui_theme as theme
from icon_toolbar import IconToolbar, icon_image


class ControlGeometryTests(unittest.TestCase):
    def test_glyph_visible_bounds_are_centered(self):
        for name in ('previous', 'next', 'minus', 'plus', 'fit', 'more', 'bookmark',
                     'save', 'focus', 'select', 'hand', 'edit', 'highlight', 'comment',
                     'camera', 'compare', 'continuous', 'notes', 'references', 'convert',
                     'image', 'close', 'jump', 'color', 'bold', 'italic', 'document'):
            for size in (20, 30, 40):
                # Ignore the almost-transparent edge pixels from antialiasing.
                mask = icon_image(name, '#ffffff', size).getchannel('A').point(lambda alpha: 255 if alpha >= 128 else 0)
                x0, y0, x1, y1 = mask.getbbox()
                self.assertLessEqual(abs(x0+x1-size), 1, name)
                self.assertLessEqual(abs(y0+y1-size), 1, name)

    def test_icon_hitboxes_fit_content_and_keep_selection_after_theme_switch(self):
        root = tk.Tk(); root.withdraw()
        original = theme.CURRENT_SKIN
        try:
            with patch('ui_theme.window_chrome'):
                theme.install_theme(root)
                selected = tk.BooleanVar(root, True)
                bar = IconToolbar(root)
                button = bar.add('select', '选择文字', lambda: None, variable=selected)
                bar.add_page(tk.StringVar(root, '12'), lambda: None, tk.StringVar(root, '12 / 240'))
                for skin in theme.SKINS:
                    theme.apply_skin(root, skin)
                    root.update_idletasks()
                    self.assertEqual(bar._theme_key[0], skin)
                    for width in (36, 80, 240, 800):
                        bar.place(width=width, height=bar.winfo_reqheight())
                        root.update_idletasks(); bar.arrange(width); root.update_idletasks()
                        for widget in (button, bar.more, bar.page_entry):
                            if widget.winfo_manager():
                                self.assertGreaterEqual(widget.winfo_x(), 0)
                                self.assertLessEqual(widget.winfo_x()+widget.winfo_width(), width)
                                self.assertLessEqual(widget.winfo_reqheight(), widget.winfo_height())
                    self.assertEqual(button.cget('style'), 'SelectedIcon.TButton')
                    self.assertNotEqual(ImageTk.getimage(button.photo).tobytes(), ImageTk.getimage(button.disabled_photo).tobytes())
                    style = ttk.Style(root)
                    layouts = [style.layout(name)[0][0] for name in ('TButton', 'Icon.TButton', 'SelectedIcon.TButton', 'Nav.TButton', 'ActiveNav.TButton')]
                    self.assertEqual(len(set(layouts)), len(layouts))
                    button.state(['disabled']); self.assertTrue(button.instate(['disabled']))
                    button.state(['!disabled'])
                selected.set(False)
                self.assertEqual(button.cget('style'), 'Icon.TButton')
        finally:
            with patch('ui_theme.window_chrome'): theme.apply_skin(root, original)
            root.destroy()


if __name__ == '__main__': unittest.main()
