from pathlib import Path
import csv
import io
import json
import tempfile
import threading
import unittest
import zipfile

from library_core import Library
from topic_package import prepare_package, export_package, PackageCancelled


class TopicPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.lib = Library(self.base / 'library')
        self.parent = self.lib.create_project('课题')
        self.child = self.lib.create_project('子课题', self.parent)
        self.other = self.lib.create_project('其他课题')
        self.one = self.paper(self.parent, '正文一', 'same.txt')
        self.two = self.paper(self.child, '正文二', 'second.txt')
        self.three = self.paper(self.other, '其他正文', 'third.txt')
        self.lib.assign(self.two, self.parent)
        extra = self.base / '原始数据.csv'
        extra.write_bytes(b'alpha,beta\r\n1,2\r\n')
        self.lib.add_attachment(self.one, extra)
        self.output = self.base / 'exports'
        self.output.mkdir()

    def paper(self, project, content, filename):
        source = self.base / filename
        source.write_text(content, 'utf-8')
        rid = self.lib.save({'title': '同名文献', 'authors': '=1+1'}, project, deduplicate=False)
        self.lib.add_attachment(rid, source, role='primary')
        return rid

    def tearDown(self):
        self.lib.close()
        self.tmp.cleanup()

    def selection(self, plan):
        return {p.id: {a.id for a in p.files if a.state == '可打包'} for p in plan.papers}

    def test_scope_descendants_and_multiple_memberships_export_once(self):
        plan = prepare_package(self.lib, self.parent)
        self.assertEqual({p.id for p in plan.papers}, {self.one, self.two})
        self.assertEqual(len(plan.papers), 2)
        self.assertEqual({p.id for p in prepare_package(self.lib, self.child).papers}, {self.two})
        self.assertEqual(len(prepare_package(self.lib).papers), 3)

    def test_zip_and_folder_contain_identical_selected_files_and_unicode_inventory(self):
        plan = prepare_package(self.lib, self.parent)
        selection = self.selection(plan)
        before = {a.path: (plan.root / a.path).read_bytes() for p in plan.papers for a in p.files}
        zipped = export_package(plan, selection, self.output, '课题', 'zip')
        folder = export_package(plan, selection, self.output, '课题', 'folder')
        self.assertEqual(zipped['papers'], 2)
        self.assertEqual(zipped['files'], 3)
        with zipfile.ZipFile(zipped['path']) as archive:
            zip_files = {name.split('/', 1)[1]: archive.read(name) for name in archive.namelist()}
        folder_files = {str(p.relative_to(folder['path'])).replace('\\', '/'): p.read_bytes() for p in folder['path'].rglob('*') if p.is_file()}
        self.assertEqual(zip_files, folder_files)
        inventory = json.loads(zip_files['打包清单.json'])
        exported = [a['path'] for p in inventory['papers'] for a in p['files']]
        self.assertEqual(len(set(exported)), 3)
        for relative in exported:
            self.assertIn(Path(relative).suffix, ('.txt', '.csv'))
        self.assertEqual(sorted(zip_files[p] for p in exported), sorted(before.values()))
        rows = list(csv.reader(io.StringIO(zip_files['文献目录.csv'].decode('utf-8-sig'))))
        self.assertEqual(rows[1][1], "'=1+1")
        self.assertEqual(before, {path: (plan.root / path).read_bytes() for path in before})
        self.assertEqual(len(self.lib.records()), 3)

    def test_deselected_paper_and_individual_attachment_are_excluded(self):
        plan = prepare_package(self.lib, self.parent)
        selection = self.selection(plan)
        del selection[self.two]
        primary = self.lib.primary_attachment(self.one)['id']
        selection[self.one] = {primary}
        result = export_package(plan, selection, self.output, '选中部分', 'folder')
        self.assertEqual((result['papers'], result['files']), (1, 1))
        inventory = json.loads((result['path'] / '打包清单.json').read_text('utf-8'))
        self.assertEqual([p['id'] for p in inventory['papers']], [self.one])
        self.assertEqual(sorted(f['state'] for f in inventory['papers'][0]['files']), ['已打包', '未勾选'])

    def test_missing_files_links_and_records_without_files_remain_explicit(self):
        empty = self.lib.save({'title': '尚未下载'}, self.parent)
        self.lib.add_attachment_link(empty, 'https://example.org/paper', '原文地址')
        primary = self.lib.primary_attachment(self.one)
        (self.lib.root / primary['path']).unlink()
        plan = prepare_package(self.lib, self.parent)
        result = export_package(plan, self.selection(plan), self.output, '缺失提示', 'folder')
        self.assertEqual(result['unavailable'], 1)
        inventory = json.loads((result['path'] / '打包清单.json').read_text('utf-8'))
        states = [a['state'] for p in inventory['papers'] for a in p['files']]
        self.assertIn('文件缺失', states)
        link = next(p for p in inventory['papers'] if p['id'] == empty)['files'][0]
        self.assertEqual((link['state'], link['url']), ('链接', 'https://example.org/paper'))

    def test_export_rejects_empty_selection_and_library_destination(self):
        plan = prepare_package(self.lib, self.parent)
        for format in ('zip', 'folder'):
            with self.assertRaises(ValueError):
                export_package(plan, {}, self.output, '空', format)
            with self.assertRaises(ValueError):
                export_package(plan, self.selection(plan), self.lib.root / 'papers', '不要导出进库', format)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_existing_outputs_are_preserved_and_collisions_are_numbered(self):
        plan = prepare_package(self.lib, self.parent)
        existing = self.output / '课题.zip'
        existing.write_bytes(b'keep existing zip')
        old_folder = self.output / '课题'
        old_folder.mkdir()
        (old_folder / 'keep.txt').write_bytes(b'keep folder')
        for format, expected in [('zip', '课题 (2).zip'), ('folder', '课题 (2)')]:
            result = export_package(plan, self.selection(plan), self.output, '课题', format)
            self.assertEqual(result['path'].name, expected)
        self.assertEqual(existing.read_bytes(), b'keep existing zip')
        self.assertEqual((old_folder / 'keep.txt').read_bytes(), b'keep folder')

    def test_cancellation_and_copy_failure_remove_only_the_new_output(self):
        plan = prepare_package(self.lib, self.parent)
        sentinel = self.output / 'keep.txt'
        sentinel.write_bytes(b'keep')
        for format in ('zip', 'folder'):
            cancel = threading.Event()
            def progress(done, total):
                if done:
                    cancel.set()
            with self.assertRaises(PackageCancelled):
                export_package(plan, self.selection(plan), self.output, '取消', format, progress, cancel)
            def fail(done, total):
                if done:
                    raise OSError('Simulated full disk')
            with self.assertRaises(OSError):
                export_package(plan, self.selection(plan), self.output, '失败', format, fail)
            self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_disappearing_file_fails_and_cleans_up_instead_of_silently_omitting_it(self):
        plan = prepare_package(self.lib, self.parent)
        (plan.root / plan.papers[0].files[0].path).unlink()
        with self.assertRaises(FileNotFoundError):
            export_package(plan, self.selection(plan), self.output, '已失效', 'zip')
        self.assertEqual(list(self.output.iterdir()), [])

    def test_outside_library_paths_are_reported_and_not_exported(self):
        aid = self.lib.primary_attachment(self.one)['id']
        secret = self.base / 'secret.txt'
        secret.write_bytes(b'not a library document')
        with self.lib.db:
            self.lib.db.execute('UPDATE attachments SET path=? WHERE id=?', ('../secret.txt', aid))
        plan = prepare_package(self.lib, self.parent)
        row = next(a for p in plan.papers for a in p.files if a.id == aid)
        self.assertEqual(row.state, '路径异常')
        result = export_package(plan, self.selection(plan), self.output, '../CON', 'folder')
        self.assertEqual(result['path'].parent, self.output)
        self.assertNotIn(secret.read_bytes(), [p.read_bytes() for p in result['path'].rglob('*') if p.is_file()])
