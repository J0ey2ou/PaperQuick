"""Local update receipts and hidden status feedback; never launch an installer."""
import json
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock,patch

import app_updates
from update_ui import UpdateController
from app_version import VERSION


class InstallResultTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.directory=self.root/'.updates';self.directory.mkdir()

    def tearDown(self):self.temp.cleanup()

    def write(self,name,data):
        target=self.directory/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(data),encoding='utf-8');return target

    def test_latest_attempt_wins_and_legacy_failure_recovers_version_from_plan(self):
        self.write('latest-result.json',dict(state='installed',version='3.9.0',completed_at=100))
        self.write('attempt/result.json',dict(state='failed',error='file occupied',completed_at=200))
        self.write('attempt/plan.json',dict(version='3.9.1'))
        result=app_updates.latest_install_result(self.root)
        self.assertEqual((result['state'],result['version']),('failed','3.9.1'))
        self.assertEqual(result['error'],'file occupied')
        self.write('latest-result.json',dict(state='installed',version='3.9.1',completed_at=300))
        self.assertEqual(app_updates.latest_install_result(self.root)['state'],'installed')

    def test_invalid_reports_do_not_block_valid_result_and_no_receipt_returns_none(self):
        self.assertIsNone(app_updates.latest_install_result(self.root))
        self.write('bad/result.json',{'state':'failed','completed_at':float('inf')})
        self.write('missing-plan/result.json',{'state':'failed','error':'plan unreadable','completed_at':100})
        (self.directory/'latest-result.json').write_bytes(b'broken')
        result=app_updates.latest_install_result(self.root)
        self.assertEqual(result['version'],'');self.assertEqual(result['error'],'plan unreadable')

    def test_new_failure_record_has_attempt_version_and_time_without_waiting_on_process(self):
        plan=self.write('attempt/plan.json',dict(version='3.9.1',pid=1))
        with patch('ctypes.WinDLL',side_effect=OSError('fixture failure')):
            result=app_updates.installer_main(plan)
        self.assertEqual(result['state'],'failed');self.assertEqual(result['version'],'3.9.1')
        self.assertGreater(result['completed_at'],0);self.assertEqual(result['attempt_id'],'attempt')
        self.assertEqual(app_updates.latest_install_result(self.root)['error'],'fixture failure')


class UpdateResultUITests(unittest.TestCase):
    def test_failed_result_is_visible_in_settings_and_not_announced_twice(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);stage=directory/'.updates'/'attempt';stage.mkdir(parents=True)
            (stage/'result.json').write_text(json.dumps(dict(state='failed',version=VERSION,error='file occupied',completed_at=100)),encoding='utf-8')
            root=tk.Tk();root.withdraw();notify=Mock()
            with patch('app_updates._open',side_effect=AssertionError('No network')):
                try:
                    first=UpdateController(root,directory,directory/'settings.json',notify)
                    self.assertIn('file occupied',first.install_status.get());notify.assert_called_once()
                    first.refresh_install_result();notify.assert_called_once()
                    second=UpdateController(root,directory,directory/'settings.json',notify)
                    second.mount(ttk.Frame(root));notify.assert_called_once()
                    self.assertIn('file occupied',second.install_status.get())
                    self.assertTrue((stage/'result.json').exists())
                    self.assertEqual(root.state(),'withdrawn')
                finally:
                    for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
                    root.destroy()

    def test_first_run_without_receipt_does_not_claim_an_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=tk.Tk();root.withdraw();notify=Mock()
            try:
                controller=UpdateController(root,temporary,Path(temporary)/'settings.json',notify)
                notify.assert_not_called();self.assertEqual(controller.install_status.get(),'')
            finally:
                for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
                root.destroy()


if __name__=='__main__':unittest.main()
