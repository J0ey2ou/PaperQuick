from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from library_core import Library
from project_handoff import export_project_handoff, inspect_project_handoff, import_project_handoff, MANIFEST
from library_backup import CHUNK
from research_store import ResearchStore
from workspace_state import WorkspaceStore
from workspace_tasks import TaskCancelled


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.library = Library(self.base / 'source')
        self.project = self.library.create_project('交接课题')
        self.child = self.library.create_project('子课题', self.project)
        self.other = self.library.create_project('无关课题')
        self.paper = self.add_paper('第一篇', self.project)
        self.second = self.add_paper('同 DOI 独立记录', self.child)
        self.external = self.add_paper('跨课题证据来源', self.other)
        self.unrelated = self.add_paper('不应泄露的无关文献', self.other)
        self.aid = self.library.get(self.paper)['attachments'][0]['id']
        self.external_aid = self.library.get(self.external)['attachments'][0]['id']
        note = self.library.root / 'note-assets' / self.paper / 'figure.png'
        note.parent.mkdir(parents=True)
        note.write_bytes(b'figure-bytes')
        self.library.save({'notes': '完整笔记\ufffc', 'note_styles': [{'tag': 'bold', 'start': '1.0', 'end': '1.2'}],
                           'note_images': [{'id': 'figure', 'path': str(note.relative_to(self.library.root)), 'offset': 4, 'index': '1.4'}],
                           'annotations': [{'id': 'annotation', 'attachment': self.aid, 'target': self.external,
                                            'target_attachment': self.external_aid, 'page': 0, 'quote': '原文'}],
                           'references': [{'title': '引用记录', 'doi': '10.1234/reference'}]}, rid=self.paper)
        self.library.relate(self.paper, self.second, '比较')
        with self.library.db:
            self.library.db.execute('INSERT INTO graph_groups VALUES(?,?,?,?)', ('group', '分组', 'circle', 1))
            self.library.db.execute('INSERT INTO graph_group_members VALUES(?,?)', ('group', self.paper))
            self.library.db.execute('INSERT INTO reading_sessions(paper,start,end) VALUES(?,?,?)', (self.paper, 10, 40))
        self.library.set_project_rules(self.project, ['交接标签'])
        self.library.set_setting('ai-secret', 'DO-NOT-EXPORT-SECRET')
        self.library.set_setting('ai-profiles', {'key': 'DO-NOT-EXPORT-PROFILE'})
        self.library.set_setting('ai-history', 'DO-NOT-EXPORT-HISTORY')
        self.library.set_setting('reader_marker_size', 22)
        self.library.set_setting('reading-last', {'paper': self.paper, 'attachment': self.aid})
        self.library.set_setting('reading-paper-last:' + self.paper, self.aid)
        self.library.set_setting('reading-position:' + self.aid,
                                 {'paper': self.paper, 'attachment': self.aid, 'page': 4, 'fraction': .4, 'scale': 1.2, 'secret': 'DO-NOT-EXPORT-NESTED'})
        research = ResearchStore(self.library.root)
        try:
            card = research.save_card({'project': self.project, 'paper': self.external, 'attachment': self.external_aid,
                                       'page': 0, 'quote': '明确来源', 'interpretation': '研究解释', 'verified': True})
            research.save_section({'project': self.project, 'title': '综述小节', 'body': '综述内容', 'position': 0, 'evidence': [card['id']]})
            research.save_decision(self.project, self.paper, 'title_abstract', 'include')
        finally:
            research.close()
        workspace = WorkspaceStore(self.library.root)
        try:
            workspace.set_question(self.project, '研究问题')
            workspace.save_todo(self.project, '人工核验结论', '2026-12-01')
            workspace.enqueue(self.project, [self.paper])
            workspace.save_view('课题智能视图', {'project': self.project})
        finally:
            workspace.close()
        self.archive = self.base / 'handoff.zip'

    def add_paper(self, title, project):
        rid = self.library.save({'title': title, 'doi': '10.1234/same', 'tags': []}, project, deduplicate=False)
        source = self.base / (rid + '.txt')
        source.write_text('same content', encoding='utf-8')
        self.library.add_attachment(rid, source, role='primary')
        self.library.add_attachment_link(rid, 'https://example.org/' + rid)
        return rid

    def tearDown(self):
        self.library.close()
        self.temp.cleanup()

    def test_full_roundtrip_preserves_records_evidence_workbench_and_reading_scene(self):
        exported = export_project_handoff(self.library.root, self.project, self.archive)
        self.assertEqual(exported['papers'], 3)
        self.assertEqual(exported['external_papers'], 1)
        preview = inspect_project_handoff(self.archive, self.library.root)
        self.assertTrue(preview['duplicate_papers'])
        self.assertTrue(preview['duplicate_files'])
        self.assertTrue(preview['preserve_every_record'])
        with zipfile.ZipFile(self.archive) as bundle:
            text = bundle.read('handoff.json').decode('utf-8')
            self.assertNotIn('DO-NOT-EXPORT', text)
            self.assertNotIn('不应泄露的无关文献', text)
            self.assertNotIn('library.sqlite', bundle.namelist())
        destination = self.base / 'imported'
        result = import_project_handoff(self.archive, destination)
        restored = Library(destination)
        try:
            self.assertEqual(len(restored.records()), 3)
            rid, aid = result['paper_map'][self.paper], result['attachment_map'][self.aid]
            record = restored.get(rid)
            self.assertEqual(record['notes'], '完整笔记\ufffc')
            self.assertEqual(record['references'][0]['title'], '引用记录')
            self.assertEqual(record['annotations'][0]['attachment'], aid)
            self.assertEqual(record['annotations'][0]['target'], result['paper_map'][self.external])
            self.assertEqual((destination / record['note_images'][0]['path']).read_bytes(), b'figure-bytes')
            self.assertEqual(restored.setting('reading-last'), {'paper': rid, 'attachment': aid})
            self.assertEqual(restored.setting('reading-paper-last:' + rid), aid)
            self.assertEqual(restored.setting('reading-position:' + aid)['page'], 4)
            self.assertIsNone(restored.setting('ai-secret'))
            self.assertEqual(len(restored.db.execute('SELECT * FROM paper_relations').fetchall()), 1)
            self.assertEqual(len(restored.db.execute('SELECT * FROM graph_group_members').fetchall()), 1)
            self.assertEqual(len(restored.db.execute('SELECT * FROM reading_sessions').fetchall()), 1)
            extra = restored.get(result['paper_map'][self.external])
            self.assertEqual(restored.project(extra['primary_project'])['name'], '交接来源文献')
        finally:
            restored.close()
        research = ResearchStore(destination)
        try:
            card = research.cards()[0]
            self.assertEqual(card['paper'], result['paper_map'][self.external])
            self.assertEqual(card['attachment'], result['attachment_map'][self.external_aid])
            self.assertTrue(card['imported_verified'])
            self.assertFalse(card['verified'])
            self.assertEqual(research.sections()[0]['evidence'], [card['id']])
        finally:
            research.close()
        workspace = WorkspaceStore(destination)
        try:
            pid = result['project_map'][self.project]
            self.assertEqual(workspace.question(pid), '研究问题')
            self.assertEqual(workspace.todos(pid)[0]['title'], '人工核验结论')
            self.assertEqual(workspace.queue(pid)[0]['id'], result['paper_map'][self.paper])
            self.assertEqual(len(workspace.views()), 1)
        finally:
            workspace.close()

    def test_missing_source_file_warned_and_record_preserved(self):
        relative = self.library.get(self.external)['attachments'][0]['path']
        (self.library.root / relative).unlink()
        export_project_handoff(self.library.root, self.project, self.archive)
        preview = inspect_project_handoff(self.archive)
        self.assertEqual(len(preview['missing_sources']), 1)
        result = import_project_handoff(self.archive, self.base / 'missing-import')
        self.assertEqual(result['papers'], 3)
        self.assertTrue(any(issue['code'] == 'missing_file' for issue in result['research_issues']))

    def test_cancel_and_concurrent_change_leave_no_published_output(self):
        owner = self
        class Changed:
            changed = False
            def check_cancelled(self):
                pass
            def progress(self, done, total, message):
                if done and not self.changed:
                    self.changed = True
                    owner.library.set_setting('concurrent', True)
        with self.assertRaisesRegex(RuntimeError, '发生变化'):
            export_project_handoff(self.library.root, self.project, self.archive, Changed())
        self.assertFalse(self.archive.exists())
        export_project_handoff(self.library.root, self.project, self.archive)
        class Cancelled:
            def check_cancelled(self):
                raise TaskCancelled()
        target = self.base / 'cancelled'
        with self.assertRaises(TaskCancelled):
            import_project_handoff(self.archive, target, Cancelled())
        self.assertFalse(target.exists())
        self.assertFalse(list(self.base.glob('.paperquick-handoff-import-*')))

    def test_tamper_private_config_unsafe_entries_and_existing_target_rejected(self):
        export_project_handoff(self.library.root, self.project, self.archive)
        with zipfile.ZipFile(self.archive) as bundle:
            original = {name: bundle.read(name) for name in bundle.namelist()}
        for case in ('hash', 'private', 'unsafe'):
            with self.subTest(case=case):
                items = dict(original)
                if case == 'hash':
                    items['handoff.json'] += b' '
                elif case == 'unsafe':
                    items['../escape.txt'] = b'escape'
                else:
                    payload = json.loads(items['handoff.json'])
                    payload['config']['ai-secret'] = 'forbidden'
                    items['handoff.json'] = json.dumps(payload).encode()
                    manifest = json.loads(items[MANIFEST])
                    for entry in manifest['files']:
                        if entry['path'] == 'handoff.json':
                            entry.update(size=len(items['handoff.json']), sha256=hashlib.sha256(items['handoff.json']).hexdigest())
                    items[MANIFEST] = json.dumps(manifest).encode()
                path = self.base / (case + '.zip')
                with zipfile.ZipFile(path, 'w') as bundle:
                    for name, data in items.items():
                        bundle.writestr(name, data)
                with self.assertRaises(ValueError):
                    import_project_handoff(path, self.base / ('bad-' + case))
                self.assertFalse((self.base / ('bad-' + case)).exists())
        with self.assertRaises(ValueError):
            import_project_handoff(self.archive, self.library.root)
        self.assertEqual(len(self.library.records()), 4)

    def test_preview_manifest_binding_and_publish_race_preserve_destination(self):
        import os
        export_project_handoff(self.library.root, self.project, self.archive)
        preview = inspect_project_handoff(self.archive)
        target = self.base / 'changed-preview'
        with self.assertRaisesRegex(ValueError, '预览后发生变化'):
            import_project_handoff(self.archive, target, expected_manifest='0' * 64)
        self.assertFalse(target.exists())
        rename = os.rename
        def publish(source, destination):
            if Path(destination) == target:
                target.mkdir()
                (target / 'keep.txt').write_text('user content')
            return rename(source, destination)
        with patch('project_handoff.os.rename', side_effect=publish):
            with self.assertRaises(OSError):
                import_project_handoff(self.archive, target, expected_manifest=preview['manifest_sha256'])
        self.assertEqual((target / 'keep.txt').read_text(), 'user content')
        self.assertEqual(list(target.iterdir()), [target / 'keep.txt'])
        self.assertFalse(list(self.base.glob('.paperquick-handoff-import-*')))

    def test_external_file_change_after_copy_prevents_publish(self):
        changed = self.library.root / self.library.get(self.paper)['attachments'][0]['path']
        class Context:
            reports = 0
            def check_cancelled(self):
                pass
            def progress(self, done, total, message):
                self.reports += 1
                if self.reports == 2:
                    changed.write_text('changed externally after first file copied', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, '发生变化'):
            export_project_handoff(self.library.root, self.project, self.archive, Context())
        self.assertFalse(self.archive.exists())

    def test_small_project_export_does_not_load_unrelated_full_records(self):
        original = Library.records
        full_projects = []
        def scoped(instance, project=None, summary=False):
            if not summary:
                self.assertIsNotNone(project, 'A project export must not materialize the whole library')
                full_projects.append(project)
            return original(instance, project, summary=summary)
        with patch.object(Library, 'records', scoped):
            export_project_handoff(self.library.root, self.project, self.archive)
        self.assertEqual(full_projects, [self.project])
        with zipfile.ZipFile(self.archive) as bundle:
            payload = json.loads(bundle.read('handoff.json'))
        self.assertEqual({item['id'] for item in payload['records']}, {self.paper, self.second, self.external})

    def test_cancel_during_asset_copy_does_not_publish_or_modify_sources(self):
        source = self.library.root / self.library.get(self.paper)['attachments'][0]['path']
        content = b'a' * (CHUNK * 3 + 7)
        source.write_bytes(content)
        export_project_handoff(self.library.root, self.project, self.archive)
        archive_hash = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        class Context:
            stop = False
            copied = 0
            previous = 0
            def check_cancelled(self):
                if self.stop:
                    raise TaskCancelled()
            def progress(self, done, total, message):
                if message.startswith('正在写入新文献库'):
                    copied = done - self.previous
                    self.previous = done
                    if message.endswith('.txt'):
                        self.copied = copied
                        self.stop = True
        context = Context()
        target = self.base / 'cancel-mid-copy'
        with self.assertRaises(TaskCancelled):
            import_project_handoff(self.archive, target, context)
        self.assertEqual(context.copied, CHUNK)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.base.glob('.paperquick-handoff-import-*')))
        self.assertEqual(source.read_bytes(), content)
        self.assertEqual(hashlib.sha256(self.archive.read_bytes()).hexdigest(), archive_hash)


if __name__ == '__main__':
    unittest.main()
