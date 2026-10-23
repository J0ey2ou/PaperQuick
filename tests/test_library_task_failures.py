from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock,patch
from library_ui import LibraryWindow


class LibraryTaskFailureTests(unittest.TestCase):
    def test_submit_and_pre_worker_failure_release_busy_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=tk.Tk();root.withdraw();window=LibraryWindow(root,Path(tmp)/'library',embedded=True)
            try:
                manager=Mock(ACTIVE={'queued','running'});window.task_manager=manager
                manager.submit.side_effect=OSError('disk full')
                worker=Mock();window.run('Import',worker)
                self.assertFalse(window.busy);self.assertIn('disk full',window.status.get());worker.assert_not_called()
                manager.submit.side_effect=None;manager.submit.return_value='failed-before-start'
                manager.get_task.return_value={'status':'failed','error':'state cannot be persisted'}
                window.run('Import',worker);self.assertTrue(window.busy)
                with patch('library_ui.messagebox.showerror') as error:window.poll();error.assert_called_once()
                self.assertFalse(window.busy);self.assertIsNone(window._managed_task_id);worker.assert_not_called()
                self.assertTrue(all(str(button.cget('state'))=='normal' for button in window.controls if button not in window.selection_controls))
            finally:window.close();root.destroy()
