from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from library_backup import create_backup, restore_backup, MANIFEST
from library_core import Library
from workspace_tasks import TaskCancelled


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.library = Library(self.base / 'library')
        self.paper = self.library.save({'title': '备份文献', 'notes': '研究笔记'})
        source = self.base / '正文.txt'
        source.write_text('完整正文与中文路径', encoding='utf-8')
        self.library.add_attachment(self.paper, source, role='primary')
        self.relative = self.library.get(self.paper)['attachments'][0]['path']
        (self.library.root / 'note-assets').mkdir()
        (self.library.root / 'note-assets' / 'figure.bin').write_bytes(b'figure-data')
        (self.library.root / 'cache').mkdir()
        (self.library.root / 'cache' / 'ignore.bin').write_bytes(b'cache')
        (self.library.root / 'cache' / 'fulltext').mkdir()
        (self.library.root / 'cache' / 'fulltext' / 'index.sqlite').write_bytes(b'index-cache')
        (self.library.root / '.paperquick-tasks.json').write_text('{"task-history":"private-runtime"}')
        self.library.db.execute('CREATE TABLE future_research_data(value TEXT)')
        self.library.db.execute('INSERT INTO future_research_data VALUES(?)', ('未来新增研究数据',))
        self.library.db.commit()

    def tearDown(self):
        self.library.close()
        self.temp.cleanup()

    def test_online_roundtrip_preserves_all_tables_assets_and_original(self):
        original = (self.library.root / self.relative).read_bytes()
        archive = self.base / 'snapshot.zip'
        result = create_backup(self.library.root, archive)
        self.assertEqual(result['missing_attachments'], [])
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read(MANIFEST))
            self.assertNotIn('cache/ignore.bin', bundle.namelist())
            self.assertNotIn('cache/fulltext/index.sqlite', bundle.namelist())
            self.assertNotIn('.paperquick-tasks.json', bundle.namelist())
            self.assertNotIn('library.sqlite-wal', bundle.namelist())
            for entry in manifest['files']:
                payload = bundle.read(entry['path'])
                self.assertEqual(len(payload), entry['size'])
                self.assertEqual(hashlib.sha256(payload).hexdigest(), entry['sha256'])
        destination = self.base / 'restored'
        restore_backup(archive, destination)
        restored = Library(destination)
        try:
            self.assertEqual(restored.get(self.paper)['notes'], '研究笔记')
            self.assertEqual(restored.db.execute('SELECT value FROM future_research_data').fetchone()[0], '未来新增研究数据')
            self.assertEqual((destination / self.relative).read_bytes(), original)
            self.assertEqual((destination / 'note-assets' / 'figure.bin').read_bytes(), b'figure-data')
        finally:
            restored.close()
        self.assertEqual((self.library.root / self.relative).read_bytes(), original)

    def test_missing_attachments_are_explicit_and_survive_restore(self):
        (self.library.root / self.relative).unlink()
        archive = self.base / 'missing.zip'
        result = create_backup(self.library.root, archive)
        self.assertEqual(len(result['missing_attachments']), 1)
        restored = restore_backup(archive, self.base / 'missing-restored')
        self.assertEqual(restored['missing_attachments'], result['missing_attachments'])
        self.assertTrue(restored['warnings'])

    def test_concurrent_database_change_prevents_publishing(self):
        owner = self
        class Context:
            changed = False
            def check_cancelled(self):
                pass
            def progress(self, done, total, message):
                if done and not self.changed:
                    self.changed = True
                    owner.library.set_setting('changed-during-backup', True)
        output = self.base / 'changing.zip'
        with self.assertRaisesRegex(RuntimeError, '发生变化'):
            create_backup(self.library.root, output, Context())
        self.assertFalse(output.exists())
        self.assertEqual(list(self.base.glob('.paperquick-backup-*')), [])

    def test_cancel_cleans_staging_and_never_overwrites_outputs(self):
        class Context:
            stop = False
            def check_cancelled(self):
                if self.stop:
                    raise TaskCancelled()
            def progress(self, done, total, message):
                self.stop = bool(done)
        archive = self.base / 'cancel.zip'
        with self.assertRaises(TaskCancelled):
            create_backup(self.library.root, archive, Context())
        self.assertFalse(archive.exists())
        create_backup(self.library.root, archive)
        before = archive.read_bytes()
        with self.assertRaises(ValueError):
            create_backup(self.library.root, archive)
        destination = self.base / 'cancel-restore'
        with self.assertRaises(TaskCancelled):
            restore_backup(archive, destination, Context())
        self.assertFalse(destination.exists())
        destination.mkdir()
        (destination / 'keep.txt').write_text('keep')
        with self.assertRaises(ValueError):
            restore_backup(archive, destination)
        self.assertEqual((destination / 'keep.txt').read_text(), 'keep')
        self.assertEqual(archive.read_bytes(), before)
        self.assertFalse(list(self.base.glob('.paperquick-restore-*')))

    def test_tampering_unsafe_paths_duplicates_and_oversized_restore_rejected(self):
        original = self.base / 'good.zip'
        create_backup(self.library.root, original)
        with zipfile.ZipFile(original) as bundle:
            contents = {name: bundle.read(name) for name in bundle.namelist()}
        for case in ('hash', 'size', 'extra', 'traversal', 'windows', 'case', 'duplicate', 'schema', 'entry'):
            with self.subTest(case=case):
                items = dict(contents)
                manifest = json.loads(items[MANIFEST])
                if case == 'hash':
                    manifest['files'][0]['sha256'] = '0' * 64
                elif case == 'size':
                    manifest['files'][0]['size'] += 1
                elif case == 'extra':
                    items['unexpected.bin'] = b'extra'
                elif case == 'traversal':
                    items['../escape.txt'] = b'escape'
                elif case == 'windows':
                    items['papers/CON.txt'] = b'bad'
                elif case == 'case':
                    items['LIBRARY.SQLITE'] = items['library.sqlite']
                elif case == 'schema':
                    manifest['schema'] = True
                elif case == 'entry':
                    manifest['files'][0] = []
                items[MANIFEST] = json.dumps(manifest).encode()
                broken = self.base / (case + '.zip')
                with zipfile.ZipFile(broken, 'w') as bundle:
                    for name, value in items.items():
                        bundle.writestr(name, value)
                    if case == 'duplicate':
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore', UserWarning)
                            bundle.writestr('library.sqlite', items['library.sqlite'])
                target = self.base / ('restored-' + case)
                with self.assertRaises((ValueError, zipfile.BadZipFile)):
                    restore_backup(broken, target)
                self.assertFalse(target.exists())
        with self.assertRaisesRegex(ValueError, '安全上限'):
            restore_backup(original, self.base / 'too-large', max_total_bytes=1)
        self.assertFalse((self.base / 'escape.txt').exists())

    def test_final_publish_race_preserves_newly_created_destination(self):
        import os
        rename = os.rename
        archive = self.base / 'raced.zip'
        def publish(source, target):
            if Path(target) == archive:
                archive.write_bytes(b'user-file-arrived')
            return rename(source, target)
        with patch('library_backup.os.rename', side_effect=publish):
            with self.assertRaises(FileExistsError):
                create_backup(self.library.root, archive)
        self.assertEqual(archive.read_bytes(), b'user-file-arrived')
        self.assertFalse(list(self.base.glob('.paperquick-backup-*')))


if __name__ == '__main__':
    unittest.main()
