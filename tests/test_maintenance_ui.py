from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest

from library_core import Library
from maintenance_ui import MaintenanceWindow
from workspace_tasks import TaskManager
from test_workspace_tasks import wait_for


class MaintenanceUITests(unittest.TestCase):
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
