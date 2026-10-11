"""Exercise the summary popup in a hidden Tk session with an isolated library."""
from datetime import date, datetime, time as daytime, timedelta
from pathlib import Path
import os
import sys
import tempfile
import time
from unittest.mock import patch
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App
from library_core import Library
from literature_tracking import TrackingStore


def main():
    base = Path(__file__).resolve().parents[1] / 'build' / 'summary-gui-tests'
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as directory:
        root = tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda exc, value, tb: errors.append((exc, value))
        # Configuration, icon resolution and later lazy pages all stay in the
        # fixture directory; no personal library is opened or changed.
        with patch('app.app_dir', return_value=Path(directory)):
            app = App(root)
        root.withdraw()
        app.library_directory = Path(directory) / 'store'
        lib = Library(app.library_directory)
        try:
            project_a = lib.create_project('营养主题')
            project_b = lib.create_project('代谢主题')
            seed = lib.save({'title': 'Dietary patterns in childhood', 'doi': '10.9999/gui-seed',
                             'keywords': 'dietary patterns; childhood nutrition',
                             'abstract': 'This article describes dietary patterns in childhood.'}, project_a)
            other = lib.save({'title': 'Metabolic health', 'doi': '10.9999/gui-other',
                              'keywords': 'metabolic health'}, project_b)
            day = date.today() - timedelta(days=1)
            stamp = datetime.combine(day, daytime(12)).astimezone().timestamp()
            with lib.db:
                lib.db.executemany('INSERT INTO reading_sessions(paper,start,end) VALUES(?,?,?)',
                                   [(seed, stamp, stamp + 120), (other, stamp + 120, stamp + 180)])
            calls = []

            def fetch(query, first, last, limit=50):
                calls.append((query, first, last, limit))
                items = [{'title': 'New dietary patterns research', 'doi': '10.9999/gui-new',
                          'published': date.today().isoformat(), 'abstract': 'A new nutrition article about microbiome diversity.',
                          'authors': 'A. Example', 'venue': 'Demonstration journal'}]
                if len(calls) > 1:
                    items.append({'title': 'Another dietary patterns article', 'doi': '10.9999/gui-newer',
                                  'published': date.today().isoformat()})
                return {'items': items, 'total': len(items), 'truncated': False}

            app.tracking.fetcher = fetch
            page = app.current_page
            nav = tuple(app.nav_buttons)
            app.show_summary()
            app.summary_dialog.withdraw()
            view = app.summary_view
            root.update()
            assert root.state() == 'withdrawn'
            assert page == app.current_page and tuple(app.nav_buttons) == nav
            assert nav == ('query', 'library', 'graph', 'reader')
            assert [view.tabs.tab(tab, 'text') for tab in view.tabs.tabs()] == [
                '阅读回顾', '主题与检索', '引用与被引', '主题追踪']
            assert view.data['count'] == 2 and view.data['seconds'] == 180
            view.project.set('营养主题')
            view.refresh()
            assert view.data['count'] == 1 and view.data['seconds'] == 120
            assert list(view.papers) == [seed]
            view.set_day(0)
            assert view.data['count'] == 0
            view.set_day(0, 7)
            assert view.data['count'] == 1
            view.scope.set('所选时段的阅读')
            view.refresh_topics()
            assert 'dietary patterns' in view.terms.get()
            assert 'metabolic health' not in view.terms.get()

            view.scope.set('课题文献库')
            view.refresh_topics()
            view.terms.set('dietary patterns; childhood nutrition; obesity; diabetes')
            view.provider.set('Europe PMC')
            view.generate_queries()
            assert view.query_text.get('1.0', 'end').count('TITLE_ABS:') == 4
            edited_query = '((TITLE_ABS:"dietary patterns" OR TITLE_ABS:"obesity") AND TITLE_ABS:"diabetes")'
            view.query_text.delete('1.0', 'end')
            view.query_text.insert('1.0', edited_query)
            edited_terms = view.terms.get()
            view.watch_terms()
            assert view.tabs.select() == str(view.watch)
            assert view.watch_query.get('1.0', 'end').strip() == edited_query
            view.watch_name.set('营养新进展')
            view.automatic.set(False)
            assert view.save_watch()
            topic_id = view.topic_id
            assert TrackingStore(lib).topics()[0]['project'] == project_a
            assert TrackingStore(lib).topics()[0]['query'] == edited_query

            def wait(predicate):
                until = time.monotonic() + 10
                while not predicate() and time.monotonic() < until:
                    root.update()
                    time.sleep(.01)
                assert predicate(), 'Summary worker did not finish'
                assert not errors, errors

            view.check_watch()
            wait(lambda: topic_id not in app.tracking.busy)
            assert len(calls) == 1 and calls[0][3] == 50
            assert calls[0][0] == edited_query
            assert len(view.results) == 1
            result_id = next(iter(view.results))
            view.result_tree.selection_set(result_id)
            view._collect_result()
            assert view.terms.get() == edited_terms
            assert view.query_text.get('1.0', 'end').strip() == edited_query
            visible_keywords = [view.keyword_tree.item(row, 'values')[0] for row in view.keyword_tree.get_children()]
            assert any('microbiome' in term for term in visible_keywords), visible_keywords
            collected = next(record for record in lib.records() if record['doi'] == '10.9999/gui-new')
            assert project_a in collected['projects']
            lib.save({'notes': 'Keep this reading note after withdrawal.'}, rid=collected['id'])
            run_id = view.runs[view.batch.get()]['id']
            view.toggle_batch()
            assert not view.results
            assert view.undo_button.cget('text') == '恢复这次发现'
            assert lib.get(collected['id'])['notes'] == 'Keep this reading note after withdrawal.'
            view.toggle_batch()
            assert len(view.results) == 1
            assert next(iter(view.results.values()))['already_collected']
            assert view.runs[view.batch.get()]['id'] == run_id
            view.check_watch()
            wait(lambda: topic_id not in app.tracking.busy)
            assert len(view.runs) == 2
            assert len(view.results) == 1  # Prior discoveries do not appear twice.
            assert next(iter(view.results.values()))['doi'] == '10.9999/gui-newer'
            old_label = next(label for label, run in view.runs.items() if run['id'] == run_id)
            view.batch.set(old_label)
            view._show_batch()
            assert next(iter(view.results.values()))['already_collected']

            # Saving another topic and choosing the first restores its query and history.
            view._new_topic()
            view.watch_name.set('第二个主题')
            view.watch_query.insert('1.0', 'TITLE_ABS:"metabolic health"')
            assert view.save_watch()
            assert view.topic_id != topic_id
            view.topic_choice.set(next(label for label, topic in view.saved_topics.items() if topic['id'] == topic_id))
            view._select_topic()
            assert view.topic_id == topic_id and len(view.runs) == 2
            assert 'diabetes' in view.watch_query.get('1.0', 'end')
            assert app.current_page == page and tuple(app.nav_buttons) == nav
            assert not errors, errors
            # A withdrawn window does not lay out notebook contents. Briefly
            # map a fully transparent tool window, without changing focus, to
            # verify the supported minimum size without displaying test data.
            # App's popup is transient to its intentionally withdrawn owner;
            # Tk can retain a 1x1 geometry for that ownership combination.
            # Use a separate non-transient container for layout measurement.
            from summary_ui import SummaryView
            dialog = tk.Toplevel(root)
            dialog.withdraw()
            dialog.attributes('-alpha', 0)
            if os.name == 'nt':
                dialog.attributes('-toolwindow', True)
            dialog.geometry('1020x720+0+0')
            layout_view = SummaryView(dialog, app.library_directory, coordinator=app.tracking)
            layout_view.frame.pack(fill='both', expand=True)
            layout_view.refresh()
            dialog.deiconify()
            for _ in range(3):
                root.update()
                time.sleep(.02)
            assert (dialog.winfo_width(), dialog.winfo_height()) == (1020, 720), (
                'Unexpected test geometry', dialog.winfo_width(), dialog.winfo_height(), dialog.geometry())

            def buttons(widget):
                if widget.winfo_class() == 'TButton':
                    yield widget
                for child in widget.winfo_children():
                    yield from buttons(child)

            layout_errors = []
            for tab in layout_view.tabs.tabs():
                layout_view.tabs.select(tab)
                root.update()
                page_widget = root.nametowidget(tab)
                for button in buttons(page_widget):
                    x = button.winfo_rootx() - page_widget.winfo_rootx()
                    y = button.winfo_rooty() - page_widget.winfo_rooty()
                    if (not button.winfo_ismapped() or button.winfo_width() <= 1 or button.winfo_height() <= 1
                            or x < 0 or y < 0 or x + button.winfo_width() > page_widget.winfo_width()
                            or y + button.winfo_height() > page_widget.winfo_height()):
                        layout_errors.append((layout_view.tabs.tab(tab, 'text'), button.cget('text'),
                                              x, y, button.winfo_width(), button.winfo_height()))
            layout_view.close()
            dialog.withdraw()
            dialog.destroy()
            assert not layout_errors, ('Minimum size clips actions', layout_errors)
            assert root.state() == 'withdrawn'
        finally:
            app.close()
            lib.close()
    print('Summary GUI passed: hidden popup / four tabs / dates and projects / edited queries retained / refreshed keywords / checks and history / reversible discoveries / saved papers retained / 1020x720 actions visible')


if __name__ == '__main__':
    main()
