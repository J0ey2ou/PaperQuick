"""Project handoff selection and reviewed imports through the shared task queue."""
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog

from library_core import Library
from maintenance_ui import MaintenanceWindow, shared_task_manager
from project_handoff import export_project_handoff, inspect_project_handoff, import_project_handoff
from workspace_tasks import TaskManager
from ui_theme import FONT, style_dialog


def register_handoff_tasks(manager):
    manager.register_retry('handoff-export', lambda data: lambda context: export_project_handoff(data['directory'], data['project'], data['output'], context))
    manager.register_retry('handoff-preview', lambda data: lambda context: inspect_project_handoff(data['archive'], data['directory'], context))
    manager.register_retry('handoff-import', lambda data: lambda context: import_project_handoff(data['archive'], data['destination'], context, expected_manifest=data.get('expected_manifest')))


class ProjectHandoffWindow:
    def __init__(self, parent, directory, project=None, manager=None, on_imported=None):
        self.directory = Path(directory).resolve()
        self.parent, self.on_imported = parent, on_imported
        self.closed = False
        self.task_id = None
        self.preview = None
        self.import_result = None
        self.maintenance = None
        self.manager = manager or shared_task_manager(parent, self.directory)
        register_handoff_tasks(self.manager)
        library = Library(self.directory)
        try:
            projects = library.projects()
        finally:
            library.close()
        self.project_ids = [item['id'] for item in projects]
        self.win = tk.Toplevel(parent)
        self.win.title('完整课题交接')
        self.win.geometry('900x660')
        self.win.minsize(760, 580)
        self.win.transient(parent.winfo_toplevel())
        style_dialog(self.win)
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        panel = ttk.Frame(self.win, padding=18)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='完整课题交接', font=(FONT, 15, 'bold')).pack(anchor='w')
        ttk.Label(panel, text='携带文献、批注、关系、证据与工作台；从新文献库继续研究。', style='Muted.TLabel').pack(anchor='w', pady=(4, 12))
        export = ttk.LabelFrame(panel, text='导出课题', padding=12)
        export.pack(fill='x')
        self.scope = ttk.Combobox(export, state='readonly', values=[item['name'] for item in projects])
        self.scope.current(self.project_ids.index(project) if project in self.project_ids else 0)
        self.scope.pack(side='left', fill='x', expand=True)
        ttk.Button(export, text='导出交接 ZIP…', command=self.start_export, style='Accent.TButton').pack(side='left', padx=(10, 0))
        ttk.Label(panel, text='包含子课题；额外引用的来源文献单独收纳。账号、AI 密钥及私有配置不进入交接包。',
                  style='Muted.TLabel', wraplength=830).pack(anchor='w', pady=(7, 12))
        incoming = ttk.LabelFrame(panel, text='检查并导入交接包', padding=12)
        incoming.pack(fill='x')
        incoming.columnconfigure(1, weight=1)
        self.archive, self.destination = tk.StringVar(), tk.StringVar()
        for row, label, variable, command in ((0, '交接 ZIP', self.archive, self.browse_archive),
                                               (1, '新文献库目录', self.destination, self.browse_destination)):
            ttk.Label(incoming, text=label).grid(row=row, column=0, sticky='w', padx=(0, 8), pady=4)
            ttk.Entry(incoming, textvariable=variable).grid(row=row, column=1, sticky='ew', pady=4)
            ttk.Button(incoming, text='选择…', command=command).grid(row=row, column=2, padx=(8, 0), pady=4)
        self.archive.trace_add('write', lambda *_: self.invalidate_preview())
        buttons = ttk.Frame(incoming)
        buttons.grid(row=2, column=0, columnspan=3, sticky='ew', pady=(8, 0))
        ttk.Button(buttons, text='校验并预览', command=self.start_preview).pack(side='left')
        self.import_button = ttk.Button(buttons, text='保留全部记录并导入新库', command=self.start_import, state='disabled')
        self.import_button.pack(side='right')
        self.preview_text = tk.StringVar(value='先校验交接包，查看同 DOI、相同文件与缺失来源情况。重复记录会全部保留。')
        ttk.Label(panel, textvariable=self.preview_text, wraplength=830, justify='left').pack(fill='x', pady=12)
        self.progress = ttk.Progressbar(panel, maximum=100)
        self.progress.pack(fill='x')
        self.status = tk.StringVar(value='当前文献库保持完整；导入只写入新的目录。')
        ttk.Label(panel, textvariable=self.status, style='Muted.TLabel', wraplength=830, justify='left').pack(fill='x', pady=8)
        actions = ttk.Frame(panel)
        actions.pack(side='bottom', fill='x')
        ttk.Button(actions, text='查看任务中心', command=self.open_tasks).pack(side='left')
        self.cancel_button = ttk.Button(actions, text='取消当前任务', command=self.cancel_task, state='disabled')
        self.cancel_button.pack(side='left', padx=8)
        self.use_button = ttk.Button(actions, text='下次启动使用导入的文献库', command=self.use_imported, state='disabled')
        if on_imported:
            self.use_button.pack(side='left')
        ttk.Button(actions, text='关闭', command=self.close).pack(side='right')
        self.poll_job = self.win.after(150, self.poll)

    @property
    def busy(self):
        task = self.manager.get_task(self.task_id) if self.task_id else None
        return bool(task and task['status'] in TaskManager.ACTIVE)

    def invalidate_preview(self):
        self.preview = None
        self.import_button.configure(state='disabled')

    def browse_archive(self):
        path = filedialog.askopenfilename(parent=self.win, title='选择课题交接包', filetypes=[('交接 ZIP', '*.zip')])
        if path:
            self.archive.set(path)

    def browse_destination(self):
        path = filedialog.askdirectory(parent=self.win, title='选择新文献库的上级文件夹', mustexist=True)
        if path:
            self.destination.set(str(Path(path) / ('交接文献库-' + datetime.now().strftime('%Y%m%d-%H%M%S'))))

    def _submit(self, kind, label, data, worker):
        if self.busy:
            self.status.set('当前任务仍在执行，可在任务中心查看进度。')
            return None
        self.task_id = self.manager.submit(kind, label, worker, metadata=data)
        self.status.set('已加入后台任务队列。')
        self.cancel_button.configure(state='normal')
        return self.task_id

    def start_export(self, output=None):
        project = self.project_ids[self.scope.current()]
        if output is None:
            output = filedialog.asksaveasfilename(parent=self.win, title='保存课题交接包', defaultextension='.zip',
                                                initialfile='PaperQuick-课题交接-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip',
                                                filetypes=[('交接 ZIP', '*.zip')])
        if not output:
            return None
        data = dict(directory=str(self.directory), project=project, output=str(Path(output).resolve()))
        return self._submit('handoff-export', '导出完整课题', data,
                            lambda context: export_project_handoff(data['directory'], data['project'], data['output'], context))

    def start_preview(self):
        if not self.archive.get().strip():
            self.status.set('请先选择交接 ZIP。')
            return None
        data = dict(archive=str(Path(self.archive.get()).resolve()), directory=str(self.directory))
        return self._submit('handoff-preview', '校验课题交接包', data,
                            lambda context: inspect_project_handoff(data['archive'], data['directory'], context))

    def start_import(self):
        if not self.preview or self.preview['path'] != str(Path(self.archive.get()).resolve()):
            self.status.set('请先完成当前交接包的校验和预览。')
            return None
        if not self.destination.get().strip():
            self.status.set('请填写尚不存在的新文献库目录。')
            return None
        data = dict(archive=self.preview['path'], destination=str(Path(self.destination.get()).resolve()), expected_manifest=self.preview['manifest_sha256'])
        return self._submit('handoff-import', '导入完整课题到新库', data,
                            lambda context: import_project_handoff(data['archive'], data['destination'], context, expected_manifest=data['expected_manifest']))

    def poll(self, schedule=True):
        if self.closed:
            return
        task = self.manager.get_task(self.task_id) if self.task_id else None
        if task:
            self.progress['value'] = min(100, task['done'] * 100 / task['total']) if task['total'] else 0
            self.cancel_button.configure(state='normal' if self.busy else 'disabled')
            self.status.set(task['error'] or task['message'])
            if task['status'] == 'succeeded':
                result = task['result']
                self.status.set('已完成：' + str(result.get('path', '')))
                if task['kind'] == 'handoff-preview' and result['path'] == str(Path(self.archive.get()).resolve()):
                    self.preview = result
                    self.preview_text.set(f"{result['title']} · {result['projects']} 个课题 · {result['papers']} 篇文献（额外来源 {result['external_papers']} 篇）\n"
                                          f"同 DOI 提示 {len(result['duplicate_papers'])} 条 · 相同文件提示 {len(result['duplicate_files'])} 条 · 缺失来源 {len(result['missing_sources'])} 条\n"
                                          '每条文献均保留，导入独立新库，不与当前库合并。' +
                                          ('\n' + '；'.join(item['message'] + '：' + str(item.get('path') or item.get('id', '')) for item in result['missing_sources'][:3]) if result['missing_sources'] else ''))
                    self.import_button.configure(state='normal')
                elif task['kind'] == 'handoff-import':
                    self.import_result = result
                    self.use_button.configure(state='normal')
                if result.get('warnings'):
                    self.status.set(self.status.get() + f"\n需留意 {len(result['warnings'])} 个缺失来源。")
        if schedule:
            self.poll_job = self.win.after(150, self.poll)

    def cancel_task(self):
        if self.task_id:
            self.manager.cancel(self.task_id)

    def open_tasks(self):
        if self.maintenance is None or self.maintenance.closed:
            self.maintenance = MaintenanceWindow(self.win, self.directory, manager=self.manager)

    def use_imported(self):
        if self.import_result and self.on_imported:
            self.on_imported(Path(self.import_result['path']))

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.poll_job:
            self.win.after_cancel(self.poll_job)
        if self.maintenance and not self.maintenance.closed:
            self.maintenance.close()
        self.win.destroy()
