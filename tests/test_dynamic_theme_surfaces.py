"""Background-only checks for content created or redrawn after a skin switch."""
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app import App
from graph_ui import GraphPage
from paper_finder import Paper, Result
import ui_theme as theme


def contrast(first, second):
    bright, dark = sorted((theme._luminance(first), theme._luminance(second)), reverse=True)
    return (bright + .05) / (dark + .05)


class DynamicThemeSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.original_skin = theme.CURRENT_SKIN
        self.chrome = patch('ui_theme.window_chrome')
        self.chrome.start()

    def tearDown(self):
        theme.apply_skin(self.root, self.original_skin)
        for job in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()
        self.chrome.stop()

    def test_async_search_result_warning_is_readable_in_current_skin(self):
        app = App.__new__(App)
        app.root = self.root
        app.cards = ttk.Frame(self.root)
        app.canvas = tk.Canvas(self.root)
        app.status = tk.StringVar(master=self.root)
        app.started_at = time.monotonic()
        app.auto_open = False
        result = Result('test', [Paper('Awaiting an open full text')])
        for name in theme.SKINS:
            with self.subTest(skin=name):
                theme.apply_skin(self.root, name)
                # Results arrive after the theme callback has completed.
                app.render(result)
                card = app.cards.winfo_children()[0]
                warning = next(child for child in card.winfo_children()
                               if isinstance(child, tk.Label)
                               and str(child.cget('text')).startswith('本次未找到开放原文'))
                self.assertEqual(card.cget('highlightbackground'), theme.LINE)
                self.assertGreaterEqual(contrast(warning.cget('foreground'),
                                                warning.cget('background')), 4.5)
                self.assertEqual(self.root.state(), 'withdrawn')

    def test_graph_redraw_keeps_theme_surfaces_and_hollow_candidates(self):
        base = Path(__file__).resolve().parents[1] / 'build' / 'dynamic-theme-tests'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temp:
            page = GraphPage(self.root, Path(temp) / 'store')
            page.canvas.winfo_width = lambda: 800
            page.canvas.winfo_height = lambda: 450
            shared = dict(doi='', projects=['主题'], pdf=False, status='未读')
            page.data = dict(nodes=[dict(shared, id='paper', title='文献', in_library=True),
                                    dict(shared, id='candidate', title='候选文献', in_library=False)],
                             edges=[], groups=[])
            page.positions = {'paper': (-30, 0), 'candidate': (30, 0)}
            page.position_key = (('paper', 'candidate'), ())
            try:
                for name in theme.SKINS:
                    with self.subTest(skin=name):
                        theme.apply_skin(self.root, name)
                        page.mode = 'overview'
                        page.draw()
                        bars = page.canvas.find_withtag('project')
                        self.assertEqual(page.canvas.itemcget(bars[0], 'fill'), theme.SURFACE)
                        page.mode = 'network'
                        page.draw()
                        candidate = next(item for item in page.canvas.find_withtag('candidate')
                                         if page.canvas.type(item) == 'oval')
                        self.assertEqual(page.canvas.itemcget(candidate, 'fill'),
                                         page.canvas.cget('background'))
                        self.assertEqual(page.canvas.cget('background'), theme.INPUT)
                        self.assertEqual(self.root.state(), 'withdrawn')
            finally:
                page.close()


if __name__ == '__main__':
    unittest.main()
