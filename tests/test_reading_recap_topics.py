from datetime import date, datetime, time, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from library_core import Library
from reading_stats import reading_recap, daily_recap, recap_text, recap_intro


class ReadingRecapTopicsTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / 'build' / 'recap-topic-tests'
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.lib = Library(Path(self.tmp.name) / 'store')
        self.day = date(2026, 10, 8)
        self.project_a = self.lib.create_project('儿童营养')
        self.project_b = self.lib.create_project('代谢健康')
        self.first = self.lib.save({
            'title': 'Dietary patterns and childhood obesity',
            'doi': '10.9999/recap-a',
            'abstract': 'The article describes dietary patterns in children.',
            'keywords': 'dietary patterns; childhood obesity',
            'notes': '比较不同饮食模式的定义。',
            'annotations': [{'page': 1, 'quote': 'Dietary patterns in children', 'text': '留意年龄分组。'}],
        }, self.project_a)
        self.second = self.lib.save({
            'title': 'Metabolic health in adolescents',
            'doi': '10.9999/recap-b',
            'abstract': 'A description of metabolic health in adolescents.',
            'keywords': 'metabolic health',
        }, self.project_b)

    def tearDown(self):
        self.lib.close()
        self.tmp.cleanup()

    def moment(self, day, hour=0, minute=0, second=0):
        return datetime.combine(day, time(hour, minute, second)).astimezone().timestamp()

    def session(self, paper, start, end):
        with self.lib.db:
            self.lib.db.execute('INSERT INTO reading_sessions(paper,start,end) VALUES(?,?,?)', (paper, start, end))

    def test_cross_day_totals_and_distinct_papers(self):
        tomorrow = self.day + timedelta(days=1)
        self.session(self.first, self.moment(self.day, 23, 59, 30), self.moment(tomorrow, 0, 0, 30))
        self.session(self.first, self.moment(tomorrow, 12), self.moment(tomorrow, 12, 1, 30))
        self.session(self.second, self.moment(self.day, 9), self.moment(self.day, 9, 2))
        self.assertEqual(daily_recap(self.lib, self.day)['seconds'], 150)
        self.assertEqual(daily_recap(self.lib, tomorrow)['seconds'], 120)
        result = reading_recap(self.lib, self.day, tomorrow)
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['seconds'], 270)
        self.assertEqual(result['date'], '2026-10-08')
        self.assertEqual(result['end_date'], '2026-10-09')
        self.assertEqual(result['papers'][0]['id'], self.first)
        self.assertIn('2026-10-08 — 2026-10-09', recap_text(result))

    def test_dates_include_only_time_inside_selected_range(self):
        start = self.moment(self.day)
        end = self.moment(self.day + timedelta(days=2))
        self.session(self.first, start - 30, start + 30)
        self.session(self.first, end - 30, end + 30)
        self.session(self.second, start - 120, start)
        self.session(self.second, end, end + 60)
        result = reading_recap(self.lib, self.day, self.day + timedelta(days=1))
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['seconds'], 60)

    def test_project_filter_honours_all_memberships(self):
        self.lib.assign(self.first, self.project_b)
        start = self.moment(self.day, 9)
        self.session(self.first, start, start + 120)
        self.session(self.second, start + 120, start + 180)
        first_project = reading_recap(self.lib, self.day, project=self.project_a)
        second_project = reading_recap(self.lib, self.day, project=self.project_b)
        self.assertEqual(first_project['count'], 1)
        self.assertEqual(first_project['seconds'], 120)
        self.assertEqual(second_project['count'], 2)
        self.assertEqual(second_project['seconds'], 180)
        self.assertEqual(reading_recap(self.lib, self.day, project='missing-project')['count'], 0)

    def test_keywords_use_only_papers_read_in_the_selected_project(self):
        start = self.moment(self.day, 9)
        self.session(self.first, start, start + 60)
        self.session(self.second, start + 60, start + 120)
        # A paper that has never been read must not influence this recap.
        self.lib.save({'title': 'Astronomy research', 'keywords': 'galactic astronomy'}, self.project_a)
        result = reading_recap(self.lib, self.day, project=self.project_a)
        topics = result['topics']
        terms = {item['term'] for item in topics['keywords']}
        self.assertEqual(topics['paper_count'], 1)
        self.assertIn('dietary patterns', terms)
        self.assertIn('childhood obesity', terms)
        self.assertNotIn('metabolic health', terms)
        self.assertNotIn('galactic astronomy', terms)
        self.assertTrue(all(item['papers'] == 1 for item in topics['keywords']))
        self.assertIn('阅读关键词：', recap_text(result))

    def test_empty_and_invalid_ranges(self):
        result = reading_recap(self.lib, self.day)
        self.assertEqual(result['count'], 0)
        self.assertEqual(result['seconds'], 0)
        self.assertEqual(result['notes_count'], 0)
        self.assertEqual(result['topics']['keywords'], [])
        self.assertIn('还没有阅读记录', recap_text(result))
        self.assertIn('想读的文献', recap_intro(result))
        with self.assertRaises(ValueError):
            reading_recap(self.lib, self.day, self.day - timedelta(days=1))

    def test_customer_copy_preserves_reading_content_without_technical_labels(self):
        start = self.moment(self.day, 9)
        self.session(self.first, start, start + 125)
        result = reading_recap(self.lib, self.day)
        text = recap_text(result)
        self.assertEqual(result['notes_count'], 2)
        for expected in ('阅读了 1 篇文献', '2 分 5 秒', '文献摘要：', '我的笔记：',
                         '比较不同饮食模式的定义。', '第 2 页摘录 / 批注：', '留意年龄分组。'):
            self.assertIn(expected, text)
        for technical_label in ('SQLite', 'API', '元数据', '采样', '前台窗口', '数据库',
                                '序列化', '进程', 'schema', 'migration', 'flush'):
            self.assertNotIn(technical_label, text)
        for invented_conclusion in ('研究证明', '研究表明', '结果表明', '显著改善', '证实了'):
            self.assertNotIn(invented_conclusion, result['topics']['description'])

    def test_missing_abstract_invites_notes_and_deleted_papers_do_not_break_recap(self):
        third = self.lib.save({'title': 'Nutrition and dietary choices'})
        start = self.moment(self.day, 9)
        self.session(third, start, start + 60)
        self.session('deleted-paper-id', start + 60, start + 120)
        result = reading_recap(self.lib, self.day)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['seconds'], 60)
        self.assertIn('还没有摘要', result['papers'][0]['content'])


if __name__ == '__main__':
    unittest.main()
