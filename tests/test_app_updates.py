from pathlib import Path
import hashlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import app_updates as updates


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.stage=self.root/'.updates'/'fixture';self.stage.mkdir(parents=True)
        self.files={'文献直达.exe':b'new fictional executable bytes','README.md':b'New notes','version.json':b'{"version":"3.5.1"}'}

    def tearDown(self):self.tmp.cleanup()

    def package(self,extra=None,manifest_change=None):
        manifest={'schema':1,'version':'3.5.1','files':{name:hashlib.sha256(data).hexdigest() for name,data in self.files.items()}}
        if manifest_change:manifest_change(manifest)
        target=self.stage/'download.zip'
        with zipfile.ZipFile(target,'w') as z:
            for name,data in self.files.items():z.writestr('PaperQuick-v3.5.1/'+name,data)
            z.writestr('PaperQuick-v3.5.1/update-manifest.json',json.dumps(manifest))
            if extra:z.writestr(*extra)
        return target,{'version':'3.5.1','sha256':updates.hash_file(target)}

    def test_semantic_version_order_and_release_channel(self):
        def release(version,preview=False,url=None):
            name=f'PaperQuick-v{version}-Windows.zip'
            return {'tag_name':'v'+version,'prerelease':preview,'assets':[{'name':name,'state':'uploaded','size':20,'digest':'sha256:'+'a'*64,'browser_download_url':url or 'https://github.com/J0ey2ou/PaperQuick/releases/download/v'+version+'/'+name}]}
        values=[release('3.9.0'),release('3.10.0'),release('3.11.0',True),release('8.0.0',url='https://evil.example/app.zip')]
        self.assertEqual(updates.select_release(values,'3.5.0')['version'],'3.10.0')
        self.assertEqual(updates.select_release(values,'3.5.0',True)['version'],'3.11.0')
        self.assertIsNone(updates.select_release(values,'9.0.0'))

    def test_verified_install_preserves_personal_library_settings_and_source_checkout(self):
        (self.root/'文献直达.exe').write_bytes(b'old')
        private={'settings.json':b'personal settings','本地文献库/note.txt':b'Keep notes','.git/config':b'Keep git'}
        for name,data in private.items():path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        archive,release=self.package();plan=updates.stage_archive(archive,self.root,release)
        result=updates.apply_staged(plan)
        self.assertEqual(result['state'],'installed')
        for name,data in private.items():self.assertEqual((self.root/name).read_bytes(),data)
        self.assertEqual((self.root/'文献直达.exe').read_bytes(),self.files['文献直达.exe'])
        self.assertEqual((self.stage/'backup/文献直达.exe').read_bytes(),b'old')

    def test_locked_file_failure_rolls_back_prior_changes(self):
        (self.root/'文献直达.exe').write_bytes(b'old exe');(self.root/'README.md').write_bytes(b'old notes')
        archive,release=self.package();plan=updates.stage_archive(archive,self.root,release)
        def replace(source,target):
            if Path(target).name=='README.md':raise PermissionError('Still in use')
            updates.os.replace(source,target)
        with self.assertRaises(PermissionError):updates.apply_staged(plan,replace)
        self.assertEqual((self.root/'文献直达.exe').read_bytes(),b'old exe')
        self.assertEqual((self.root/'README.md').read_bytes(),b'old notes')
        self.assertFalse((self.root/'version.json').exists())

    def test_corrupt_package_or_staged_file_never_changes_program(self):
        archive,release=self.package();release['sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'校验失败'):updates.stage_archive(archive,self.root,release)
        archive,release=self.package();plan=updates.stage_archive(archive,self.root,release)
        (self.stage/'package/README.md').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'发生变化'):updates.apply_staged(plan)
        self.assertFalse((self.root/'文献直达.exe').exists())

    def test_paths_and_personal_files_cannot_be_installed(self):
        for extra in [('PaperQuick-v3.5.1/../escape.exe',b'bad'),('PaperQuick-v3.5.1/settings.json',b'bad'),('C:/escape.exe',b'bad')]:
            archive,release=self.package(extra)
            with self.assertRaises(ValueError):updates.stage_archive(archive,self.root,release)
        self.assertFalse((self.root/'settings.json').exists())

    def test_download_length_and_digest_are_checked_without_external_network(self):
        archive,release=self.package();data=archive.read_bytes();release.update(url='https://github.com/J0ey2ou/PaperQuick/releases/download/v3.5.1/PaperQuick-v3.5.1-Windows.zip',size=len(data))
        with patch('app_updates._open',return_value=io.BytesIO(data)),patch('app_updates.launch_installer') as launch:
            plan=updates.download_update(self.root,release)
        self.assertTrue(plan.is_file());launch.assert_not_called()

    def test_verified_download_is_reused_for_retry_without_network(self):
        archive,release=self.package();release.update(size=archive.stat().st_size)
        with patch('app_updates._open',side_effect=AssertionError('Must reuse verified download')):
            plan=updates.download_update(self.root,release)
        self.assertEqual(plan.parent,self.stage)

    def test_stable_updates_use_public_manifest_without_anonymous_api_quota(self):
        feed={'schema':1,'version':'3.5.1','tag':'v3.5.1','prerelease':False,'notes':'Release notes',
              'package':{'name':'PaperQuick-v3.5.1-Windows.zip','url':'https://github.com/J0ey2ou/PaperQuick/releases/download/v3.5.1/PaperQuick-v3.5.1-Windows.zip','size':42,'sha256':'a'*64}}
        def open_fixture(url):
            self.assertEqual(url,updates.UPDATE_FEED)
            return io.BytesIO(json.dumps(feed).encode())
        with patch('app_updates._open',side_effect=open_fixture):
            self.assertEqual(updates.check_update('3.4.3')['version'],'3.5.1')
            self.assertIsNone(updates.check_update('3.5.1'))
        feed['package']['url']='https://evil.example/app.zip'
        with self.assertRaises(ValueError):updates.manifest_release(feed,'3.4.3')

    def test_missing_public_manifest_falls_back_to_release_api(self):
        from urllib.error import HTTPError
        calls=[]
        def open_fixture(url):
            calls.append(url)
            if url==updates.UPDATE_FEED:raise HTTPError(url,404,'Not found',{},None)
            return io.BytesIO(b'[]')
        with patch('app_updates._open',side_effect=open_fixture):self.assertIsNone(updates.check_update('3.5.1'))
        self.assertEqual(calls,[updates.UPDATE_FEED,updates.API])
