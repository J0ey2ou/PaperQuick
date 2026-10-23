from pathlib import Path
import tempfile
import tkinter as tk
import unittest

from library_core import Library
from project_handoff_ui import ProjectHandoffWindow
from workspace_tasks import TaskManager
from test_workspace_tasks import wait_for


class HandoffUITests(unittest.TestCase):
    def test_hidden_export_preview_import_and_explicit_switch(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            library = Library(base / 'library')
            project = library.projects()[0]['id']
            library.save({'title': '交接测试'}, project)
            manager = TaskManager(library.root)
            root = tk.Tk()
            root.withdraw()
            callbacks = []
            window = ProjectHandoffWindow(root, library.root, project, manager, callbacks.append)
            try:
                output = base / 'handoff.zip'
                exported = window.start_export(output)
                self.assertEqual(wait_for(manager, exported)['status'], 'succeeded')
                window.archive.set(str(output))
                window.destination.set(str(base / 'new-library'))
                self.assertIsNone(window.start_import())
                inspected = window.start_preview()
                self.assertEqual(wait_for(manager, inspected)['status'], 'succeeded')
                window.poll(schedule=False)
                self.assertIn('每条文献均保留', window.preview_text.get())
                imported = window.start_import()
                self.assertEqual(wait_for(manager, imported)['status'], 'succeeded')
                window.poll(schedule=False)
                self.assertEqual(callbacks, [])
                window.use_imported()
                self.assertEqual(callbacks, [base / 'new-library'])
                self.assertEqual(root.state(), 'withdrawn')
                window.close()
                self.assertFalse(manager._closed)
            finally:
                window.close()
                manager.close(wait=True)
                library.close()
                root.destroy()


if __name__ == '__main__':
    unittest.main()
