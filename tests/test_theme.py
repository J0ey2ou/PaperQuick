"""Guard the readable states and live theme changes used by the review dialog."""
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

import ui_theme as theme


def contrast(first, second):
    bright, dark = sorted((theme._luminance(first), theme._luminance(second)), reverse=True)
    return (bright+.05)/(dark+.05)


class ThemeTests(unittest.TestCase):
    def test_readable_text_and_interactive_states_in_each_skin(self):
        for name, palette in theme.SKINS.items():
            colors = theme._tokens(palette)
            for background, foreground in (
                (palette['BG'], palette['FG']), (palette['PANEL'], palette['MUTED']),
                (palette['ACCENT'], colors['accent_fg']),
                (colors['accent_hover'], colors['accent_fg']),
                (colors['accent_pressed'], colors['accent_fg']),
                (colors['selection'], colors['selection_fg']),
                (colors['hover'], palette['FG']),
            ):
                self.assertGreaterEqual(contrast(background, foreground), 4.5,
                                        f'{name}: {background} / {foreground}')

    def test_switching_skins_preserves_content_and_card_roles(self):
        root = tk.Tk()
        root.withdraw()
        with patch('ui_theme.window_chrome'):
            try:
                theme.apply_skin(root, '深空蓝')
                card = tk.Frame(root, bg=theme.PANEL)
                text = tk.Text(card, bg=theme.INPUT, fg=theme.FG)
                text.insert('end', '保留阅读笔记')
                tree = ttk.Treeview(card)
                tree.tag_configure('odd', background='#132237')
                dialog = tk.Toplevel(root)
                dialog.withdraw()
                theme.style_dialog(dialog)
                for name in (*theme.SKINS, '深空蓝'):
                    theme.apply_skin(root, name)
                    self.assertEqual(card.cget('background'), theme.PANEL)
                    self.assertEqual(text.cget('background'), theme.INPUT)
                    self.assertEqual(dialog.cget('background'), theme.BG)
                    self.assertEqual(text.get('1.0', 'end-1c'), '保留阅读笔记')
                    self.assertEqual(str(tree.tag_configure('odd', 'background')), theme.SURFACE)
                    self.assertEqual(root.attributes('-alpha'), 1.0)
                    self.assertEqual(dialog.attributes('-alpha'), 1.0)
                root.update_idletasks()
                pending = root.tk.call('after', 'info')
                for _ in range(5):
                    theme.apply_skin(root, '深空蓝')
                self.assertEqual(root.tk.call('after', 'info'), pending)
            finally:
                root.destroy()

    def test_ttk_input_widgets_survive_live_skin_changes(self):
        root = tk.Tk()
        root.withdraw()
        with patch('ui_theme.window_chrome'):
            try:
                plain = tk.Entry(root)
                plain.insert('end', '原生输入框')
                entry = ttk.Entry(root)
                entry.insert('end', '主题输入框')
                combo = ttk.Combobox(root, values=['示例课题'], state='readonly')
                combo.set('示例课题')
                spin = ttk.Spinbox(root, from_=1, to=20)
                spin.set('7')
                for name in theme.SKINS:
                    theme.apply_skin(root, name)
                    self.assertEqual(plain.get(), '原生输入框')
                    self.assertEqual(entry.get(), '主题输入框')
                    self.assertEqual(combo.get(), '示例课题')
                    self.assertEqual(spin.get(), '7')
                    self.assertEqual(plain.cget('selectforeground'), theme.FG)
            finally:
                root.destroy()

    def test_label_font_sizes_are_used_by_actual_widgets(self):
        root = tk.Tk()
        root.withdraw()
        with patch('ui_theme.window_chrome'):
            try:
                theme.install_theme(root)
                body = ttk.Label(root, text='阅读总结', style='TLabel')
                hero = ttk.Label(root, text='阅读总结', style='Hero.TLabel')
                stat = ttk.Label(root, text='28', style='CardStat.TLabel')
                # An explicit widget font silently overrides ttk's font style.
                self.assertFalse(str(hero.cget('font')))
                self.assertFalse(str(stat.cget('font')))
                root.update_idletasks()
                self.assertGreater(hero.winfo_reqheight(), body.winfo_reqheight()*1.6)
                self.assertGreater(stat.winfo_reqheight(), body.winfo_reqheight()*1.6)
                notebook = ttk.Notebook(root)
                first, second = ttk.Frame(notebook), ttk.Frame(notebook)
                notebook.add(first, text='阅读回顾')
                notebook.add(second, text='主题与检索')
                notebook.select(second)
                self.assertEqual(notebook.select(), str(second))
                layout = ttk.Style(root).layout('TNotebook.Tab')
                self.assertEqual(layout[0][0], 'Button.border')
            finally:
                root.destroy()

    def test_glass_windows_and_startup_remain_fully_opaque(self):
        from unittest.mock import Mock
        root = tk.Tk()
        root.withdraw()
        with patch('ui_theme.window_chrome'):
            try:
                theme.apply_skin(root, '琉璃·冰川蓝')
                dialog = tk.Toplevel(root)
                dialog.withdraw()
                theme.style_dialog(dialog)
                self.assertEqual(dialog.attributes('-alpha'), 1.0)
                # Startup must never fade through to another application.
                animated = Mock()
                animated.winfo_exists.return_value = True
                callbacks = []
                animated.after.side_effect = lambda delay, callback: callbacks.append(callback)
                theme.opening_animation(animated)
                theme.apply_skin(root, '琉璃·深海青')
                while callbacks:
                    callbacks.pop(0)()
                self.assertEqual(animated.attributes.call_args.args, ('-alpha', 1.0))
                self.assertEqual(animated.attributes.call_count, 1)
                animated.after.assert_not_called()
                # Switching away from a previously translucent window restores opacity.
                root.attributes('-alpha', .78)
                theme.apply_skin(root, '极简浅色')
                self.assertEqual(root.attributes('-alpha'), 1.0)
                self.assertEqual(dialog.attributes('-alpha'), 1.0)
                self.assertEqual(theme.skin_opacity('unknown'), 1.0)
            finally:
                theme.apply_skin(root, '深空蓝')
                root.destroy()


if __name__ == '__main__':
    unittest.main()
