import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from library_core import Library
from literature_tracking import TrackingStore, run_check, fetch_europepmc, _safe_url


def batch(items, total=None, truncated=False):
    return {'items': items, 'total': len(items) if total is None else total, 'truncated': truncated}


class TrackingTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'build' / 'tracking-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.lib = Library(Path(self.temp.name) / 'library')
        self.store = TrackingStore(self.lib)
        self.project = self.lib.create_project('演示课题')
        self.topic = self.store.save_topic('营养研究', 'TITLE_ABS:nutrition', self.project, automatic=True)
        self.day = dt.date(2026, 10, 11)

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def check(self, items, **kwargs):
        return run_check(self.store, self.topic, lambda *a, **k: batch(items, **kwargs), self.day)

    def test_date_windows_dedup_and_daily_schedule(self):
        seen = []
        def fetch(query, start, end, limit):
            seen.append((query, start, end, limit))
            return batch([{'title': 'A study', 'doi': 'https://doi.org/10.1234/TEST'},
                          {'title': 'A study duplicate', 'doi': 'doi:10.1234/test'},
                          {'title': 'No DOI: Study'}, {'title': 'no doi study.'}])
        first = run_check(self.store, self.topic, fetch, self.day)
        self.assertEqual(first['count'], 2)
        self.assertEqual(seen[0][1], dt.date(2026, 9, 12))
        self.assertEqual(seen[0][3], 50)
        self.assertEqual(self.store.due_topics(self.day), [])
        self.assertEqual(len(self.store.due_topics(self.day + dt.timedelta(days=1))), 1)
        second = run_check(self.store, self.topic, fetch, self.day + dt.timedelta(days=1))
        self.assertEqual(second['count'], 0)
        self.assertEqual(seen[-1][1], dt.date(2026, 10, 4))
        self.assertEqual(self.store.runs()[0]['query'], 'TITLE_ABS:nutrition')

    def test_rollback_restore_preserves_collected_notes_and_metadata(self):
        rid = self.lib.save({'title': 'My edited title', 'doi': '10.1234/a', 'notes': 'My careful notes', 'status': '已读'}, self.project)
        original = Path(self.temp.name) / 'original.pdf'
        original.write_bytes(b'%PDF-1.4\n%%EOF\n')
        attached = self.lib.attach(rid, original, extract=False)
        contents = attached.read_bytes()
        result = self.check([{'title': 'Service title', 'doi': '10.1234/a', 'abstract': 'New abstract'}])
        row = self.store.results(result['run_id'])[0]
        self.assertTrue(row['already_collected'])
        self.assertEqual(self.store.add_result_to_library(row['id']), rid)
        before = self.lib.get(rid)
        checkpoint = self.store.topics()[0]['last_checked']
        self.assertTrue(self.store.rollback(result['run_id']))
        self.assertFalse(self.store.rollback(result['run_id']))
        self.assertEqual(self.store.results(result['run_id']), [])
        self.assertEqual(self.store.results(result['run_id'], True)[0]['id'], row['id'])
        self.assertEqual(self.store.topics()[0]['last_checked'], checkpoint)
        self.assertEqual(self.check([{'title': 'Service title', 'doi': '10.1234/a'}])['count'], 0)
        self.assertTrue(self.store.restore(result['run_id']))
        self.assertEqual(self.store.results(result['run_id'])[0]['id'], row['id'])
        self.assertEqual(self.lib.get(rid), before)
        self.assertEqual(before['title'], 'My edited title')
        self.assertEqual(before['notes'], 'My careful notes')
        self.assertEqual(before['abstract'], '')
        self.assertEqual(attached.read_bytes(), contents)
        self.assertEqual(original.read_bytes(), contents)

    def test_new_collection_is_idempotent_and_does_not_delete_on_rollback(self):
        result = self.check([{'title': 'Discovery', 'doi': '10.1234/new', 'abstract': '<p>Useful abstract</p>'}])
        row = self.store.results(result['run_id'])[0]
        rid = self.store.add_result_to_library(row['id'])
        self.assertEqual(self.lib.get(rid)['primary_project'], self.project)
        self.assertEqual(self.lib.get(rid)['abstract'], 'Useful abstract')
        self.lib.save({'notes': 'Later note'}, rid=rid)
        self.assertEqual(self.store.add_result_to_library(row['id']), rid)
        self.store.rollback(result['run_id'])
        self.assertEqual(self.lib.get(rid)['notes'], 'Later note')
        self.assertEqual(len(self.lib.records()), 1)

    def test_failure_keeps_checkpoint_and_no_automatic_retry_same_day(self):
        self.check([])
        tomorrow = self.day + dt.timedelta(days=1)
        def fail(*a, **k):
            raise urllib.error.URLError('Secret internal path not for display')
        result = run_check(self.store, self.topic, fail, tomorrow)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('Secret', result['message'])
        self.assertIn('网络', result['message'])
        topic = self.store.topics()[0]
        self.assertEqual(topic['last_checked'], self.day.isoformat())
        self.assertEqual(topic['last_attempt'], tomorrow.isoformat())
        self.assertFalse(self.store.due_topics(tomorrow))
        self.assertEqual(run_check(self.store, self.topic, lambda *a, **k: batch([]), tomorrow)['status'], 'complete')

    def test_truncation_is_visible_and_does_not_advance_checkpoint(self):
        result = self.check([{'title': f'Paper {i}'} for i in range(51)], total=100)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['count'], 50)
        self.assertIn('仍有更多', result['message'])
        self.assertIsNone(self.store.topics()[0]['last_checked'])
        self.assertEqual(len(self.store.results(result['run_id'])), 50)

    def test_query_edit_preserves_history_and_resets_date_window(self):
        self.check([])
        self.store.save_topic('改名', 'new query', self.project, self.topic, automatic=False)
        topic = self.store.topics()[0]
        self.assertIsNone(topic['last_checked'])
        self.assertIsNone(topic['last_attempt'])
        self.assertEqual(self.store.runs()[0]['query'], 'TITLE_ABS:nutrition')
        self.assertEqual(topic['query'], 'new query')

    def test_only_one_run_per_topic_and_topic_edit_is_blocked(self):
        entered, finish = threading.Event(), threading.Event()
        replies = []
        def fetch(*a, **k):
            entered.set()
            self.assertTrue(finish.wait(5))
            return batch([])
        thread = threading.Thread(target=lambda: replies.append(run_check(self.store, self.topic, fetch, self.day)))
        thread.start()
        self.assertTrue(entered.wait(5))
        try:
            competing = run_check(TrackingStore(self.lib), self.topic, lambda *a, **k: batch([]), self.day)
            self.assertEqual(competing['status'], 'running')
            with self.assertRaisesRegex(ValueError, '正在检查'):
                self.store.save_topic('Edited', 'edit', topic_id=self.topic)
            self.assertFalse(self.store.due_topics(self.day))
        finally:
            finish.set()
            thread.join(5)
        self.assertEqual(replies[0]['status'], 'complete')
        self.assertEqual(len(self.store.runs()), 1)

    def test_title_fallback_and_distinct_dois(self):
        result = self.check([{'title': 'Same title', 'doi': '10.1234/one'},
                             {'title': 'Same title', 'doi': '10.1234/two'},
                             {'title': 'Same title'}])
        self.assertEqual(result['count'], 2)
        rid = self.lib.save({'title': 'A title without DOI', 'notes': 'Keep this'})
        result = self.check([{'title': 'A title without DOI.', 'doi': '10.1234/new'}])
        self.assertEqual(self.store.add_result_to_library(self.store.results(result['run_id'])[0]['id']), rid)
        self.assertEqual(self.lib.get(rid)['notes'], 'Keep this')

    def test_interrupted_previous_launch_does_not_block_new_checks(self):
        with self.lib.db:
            self.lib.db.execute("INSERT INTO tracking_runs(topic_id,created,query,start_date,end_date,status,owner) VALUES(?,0,'old query','2026-10-01','2026-10-10','running','old-launch')", (self.topic,))
        store = TrackingStore(self.lib)
        self.assertEqual(store.runs()[0]['status'], 'failed')
        self.assertIn('上次检查', store.runs()[0]['error'])
        self.assertEqual(run_check(store, self.topic, lambda *a, **k: batch([]), self.day)['status'], 'complete')

    def test_results_and_success_are_committed_together(self):
        with self.lib.db:
            self.lib.db.execute("CREATE TRIGGER reject_test_result BEFORE INSERT ON tracking_results WHEN NEW.title_key='rejectthis' BEGIN SELECT RAISE(ABORT,'test failure'); END")
        result = self.check([{'title': 'First record'}, {'title': 'Reject this'}])
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(self.store.topics()[0]['last_checked'])
        self.assertEqual(self.store.results(result['run_id'], True), [])
        self.assertEqual(self.store.runs()[0]['status'], 'failed')


class FetchTests(unittest.TestCase):
    def test_cursor_pages_and_hit_count_truncation(self):
        calls = []
        class Opener:
            def open(self, request, timeout):
                calls.append((request.full_url, timeout))
                return io.BytesIO(json.dumps({'hitCount': 68, 'nextCursorMark': 'next', 'resultList': {'result': [
                    {'title': f'Paper {i}', 'doi': f'10.1234/{len(calls)}-{i}', 'pubYear': '2026',
                     'journalInfo': {'journal': {'title': 'Demo Journal'}}, 'firstPublicationDate': '2026-10-01'} for i in range(25)
                ]}}).encode())
        with patch('literature_tracking.urllib.request.build_opener', return_value=Opener()):
            result = fetch_europepmc('nutrition AND children', '2026-10-01', '2026-10-11')
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result['items']), 50)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['total'], 68)
        self.assertIn('cursorMark=next', calls[1][0])
        self.assertIn('FIRST_PDATE', calls[0][0])
        self.assertIn('sort_date', calls[0][0])
        self.assertEqual(calls[0][1], 12)
        self.assertEqual(result['items'][0]['venue'], 'Demo Journal')

    def test_unsafe_links_are_not_kept(self):
        for url in ['javascript:alert(1)', 'file:///C:/secret', 'https://localhost/paper',
                    'http://127.0.0.1/admin', 'http://192.168.1.1/', 'https://user:pass@example.com/paper']:
            self.assertEqual(_safe_url(url), '')
        self.assertEqual(_safe_url('https://europepmc.org/article/MED/123'), 'https://europepmc.org/article/MED/123')


if __name__ == '__main__':
    unittest.main()
