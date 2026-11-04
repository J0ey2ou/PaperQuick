from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import patch

from library_core import Library
from maintenance_ui import MaintenanceWindow
from workspace_tasks import TaskManager
from test_workspace_tasks import wait_for


class MaintenanceUITests(unittest.TestCase):
    def test_history_is_paged_and_unchanged_rows_are_not_redrawn(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager=TaskManager(temporary);root=tk.Tk();root.withdraw()
            for index in range(250):
                manager._tasks[str(index)]=dict(id=str(index),kind='sample',label='Task '+str(index),status='succeeded',done=1,total=1,message='done',error='',result=None,created=index,updated=index,metadata={})
            window=MaintenanceWindow(root,temporary,manager=manager)
            try:
                self.assertEqual(len(window.tree.get_children()),100)
                self.assertEqual(window.tree.get_children()[0],'249')
                with patch.object(window.tree,'item',wraps=window.tree.item) as item:
                    window.refresh(schedule=False);item.assert_not_called()
                window.change_task_page(1);self.assertEqual(window.tree.get_children()[0],'149')
                window.change_task_page(1);self.assertEqual(len(window.tree.get_children()),50)
                window.tree.selection_set('0');self.assertEqual(window.selected_task()['label'],'Task 0')
                self.assertEqual(str(window.older_button.cget('state')),'disabled')
                self.assertEqual(manager.task_count(),250)
            finally:window.close();manager.close(wait=True);root.destroy()

    def test_hidden_backup_restore_monitor_and_explicit_switch(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            library = Library(base / 'library')
            library.save({'title': 'Maintenance test', 'notes': 'preserve'})
            manager = TaskManager(library.root)
            root = tk.Tk()
            root.withdraw()
            callbacks = []
            owner = threading.get_ident()
            window = MaintenanceWindow(root, library.root, manager=manager,
                                       on_restored=lambda path: callbacks.append((path, threading.get_ident())))
            try:
                backup_id = window.start_backup(base / 'snapshot.zip')
                self.assertEqual(wait_for(manager, backup_id)['status'], 'succeeded')
                restored = base / 'restored'
                restore_id = window.start_restore(base / 'snapshot.zip', restored)
                self.assertEqual(wait_for(manager, restore_id)['status'], 'succeeded')
                window.refresh(schedule=False)
                window.tree.selection_set(restore_id)
                window.show_selected()
                self.assertIn(str(restored), window.detail.get())
                self.assertEqual(callbacks, [])
                window.use_restored()
                self.assertEqual(callbacks, [(restored, owner)])
                self.assertEqual(root.state(), 'withdrawn')
                self.assertFalse(window.busy)
                window.close()
                self.assertFalse(manager._closed)
            finally:
                window.close()
                manager.close(wait=True)
                library.close()
                root.destroy()


if __name__ == '__main__':
    unittest.main()
