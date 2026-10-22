"""Library backup/restore and task monitoring; all Tk work stays on the UI thread."""
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from library_backup import create_backup, restore_backup
from workspace_tasks import TaskManager
from ui_theme import FONT, style_dialog

STATES = dict(queued='等待执行', running='正在执行', succeeded='已完成', failed='失败',
              cancelled='已取消', interrupted='已中断')


def register_maintenance_tasks(manager):
    manager.register_retry('backup', lambda data: lambda context: create_backup(data['directory'], data['output'], context))
    manager.register_retry('restore', lambda data: lambda context: restore_backup(data['archive'], data['destination'], context))


def shared_task_manager(parent, directory):
    root = parent._root()
    managers = getattr(root, '_paperquick_task_managers', {})
    key = str(Path(directory).resolve())
    if key not in managers:
        managers[key] = TaskManager(key)
        root.bind('<Destroy>', lambda event, owner=root, item=managers[key]: item.close() if event.widget is owner else None, add='+')
    root._paperquick_task_managers = managers
    return managers[key]


class MaintenanceWindow:
    def __init__(self, parent, directory, manager=None, on_restored=None):
        self.directory = Path(directory).resolve()
        self.on_restored = on_restored
        self.closed = False
        root = parent.winfo_toplevel()
        if manager is None:
            manager = shared_task_manager(parent, directory)
        self.manager = manager
        register_maintenance_tasks(manager)
        self.win = tk.Toplevel(parent)
        self.win.title('备份恢复与任务中心')
        self.win.geometry('940x700')
        self.win.minsize(760, 560)
        self.win.transient(root)
        style_dialog(self.win)
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        panel = ttk.Frame(self.win, padding=18)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='文献库备份与任务中心', font=(FONT, 15, 'bold')).pack(anchor='w')
        ttk.Label(panel, text='完整保留文献、课题、笔记与研究数据；恢复到新文件夹。',
                  style='Muted.TLabel').pack(anchor='w', pady=(4, 12))
        backup = ttk.LabelFrame(panel, text='完整备份', padding=10)
        backup.pack(fill='x')
        ttk.Label(backup, text=str(self.directory), style='Muted.TLabel', wraplength=650).pack(side='left', fill='x', expand=True)
        ttk.Button(backup, text='创建备份 ZIP…', style='Accent.TButton', command=self.start_backup).pack(side='right', padx=(8, 0))
        restore = ttk.LabelFrame(panel, text='恢复备份', padding=10)
        restore.pack(fill='x', pady=10)
        restore.columnconfigure(1, weight=1)
        self.archive = tk.StringVar()
        self.destination = tk.StringVar()
        for row, label, variable, command in ((0, '备份文件', self.archive, self.choose_archive),
                                               (1, '恢复到新目录', self.destination, self.choose_destination)):
            ttk.Label(restore, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=4)
            ttk.Entry(restore, textvariable=variable).grid(row=row, column=1, sticky='ew', pady=4)
            ttk.Button(restore, text='选择…', command=command).grid(row=row, column=2, padx=(8, 0), pady=4)
        ttk.Label(restore, text='恢复前核对文件清单与 SHA256；现有文献库保留。', style='Muted.TLabel').grid(row=2, column=0, columnspan=2, sticky='w', pady=(7, 0))
        ttk.Button(restore, text='开始恢复', command=self.start_restore).grid(row=2, column=2, padx=(8, 0), pady=(7, 0))
        heading = ttk.Frame(panel)
        heading.pack(fill='x', pady=(4, 6))
        ttk.Label(heading, text='后台任务', font=(FONT, 11, 'bold')).pack(side='left')
        ttk.Label(heading, text='关闭窗口后任务继续；退出前请等待不可取消任务完成。', style='Muted.TLabel').pack(side='right')
        table = ttk.Frame(panel)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('status', 'progress', 'time'), show='tree headings', selectmode='browse', height=7)
        for key, label, width in (('#0', '任务', 340), ('status', '状态', 95), ('progress', '进度', 80), ('time', '创建时间', 145)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=70, stretch=key == '#0')
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(table, command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.show_selected())
        self.detail = tk.StringVar(value='任务进度、结果和异常信息会显示在这里。')
        ttk.Label(panel, textvariable=self.detail, style='Muted.TLabel', wraplength=830, justify='left').pack(fill='x', pady=8)
        actions = ttk.Frame(panel)
        actions.pack(fill='x')
        self.cancel_button = ttk.Button(actions, text='取消任务', command=self.cancel_selected, state='disabled')
        self.cancel_button.pack(side='left')
        self.retry_button = ttk.Button(actions, text='重新执行', command=self.retry_selected, state='disabled')
        self.retry_button.pack(side='left', padx=8)
        self.use_button = ttk.Button(actions, text='使用恢复的文献库', command=self.use_restored, state='disabled')
        if on_restored:
            self.use_button.pack(side='left')
        ttk.Button(actions, text='关闭', command=self.close).pack(side='right')
        self.status = tk.StringVar(value='备份会提示缺失附件；缓存、临时文件与任务历史不进入备份。')
        ttk.Label(panel, textvariable=self.status, style='Muted.TLabel', wraplength=830).pack(anchor='w', pady=(8, 0))
        self.poll_job = None
        self.refresh()

    @property
    def busy(self):
        return any(task['status'] in TaskManager.ACTIVE for task in self.manager.list_tasks())

    def choose_archive(self):
        value = filedialog.askopenfilename(parent=self.win, title='选择文献库备份', filetypes=[('文献库备份', '*.zip')])
        if value:
            self.archive.set(value)

    def choose_destination(self):
        value = filedialog.askdirectory(parent=self.win, title='选择恢复目录的上级文件夹', mustexist=True)
        if value:
            self.destination.set(str(Path(value) / ('文献库-恢复-' + datetime.now().strftime('%Y%m%d-%H%M%S'))))

    def start_backup(self, output=None):
        if output is None:
            output = filedialog.asksaveasfilename(parent=self.win, title='保存完整文献库备份', defaultextension='.zip',
                                                initialfile='PaperQuick-文献库-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip',
                                                filetypes=[('ZIP 备份', '*.zip')])
        if not output:
            return None
        data = dict(directory=str(self.directory), output=str(Path(output).resolve()))
        return self._submit('backup', '完整文献库备份', data,
                            lambda context: create_backup(data['directory'], data['output'], context))

    def start_restore(self, archive=None, destination=None):
        archive = archive or self.archive.get().strip()
        destination = destination or self.destination.get().strip()
        if not archive or not destination:
            self.status.set('请选择备份文件，并填写尚不存在的恢复目录。')
            return None
        data = dict(archive=str(Path(archive).resolve()), destination=str(Path(destination).resolve()))
        return self._submit('restore', '恢复文献库备份', data,
                            lambda context: restore_backup(data['archive'], data['destination'], context))

    def _submit(self, kind, label, data, worker):
        try:
            task_id = self.manager.submit(kind, label, worker, metadata=data)
            self.status.set('任务已加入队列，可继续使用软件。')
            self.refresh(schedule=False)
            self.tree.selection_set(task_id)
            self.show_selected()
            return task_id
        except Exception as exc:
            self.status.set(str(exc))
            return None

    def refresh(self, schedule=True):
        if self.closed:
            return
        tasks = self.manager.list_tasks()
        known = set(self.tree.get_children())
        for task in tasks:
            percentage = f"{min(100, round(100 * task['done'] / task['total']))}%" if task['total'] else '—'
            values = (STATES.get(task['status'], task['status']), percentage,
                      datetime.fromtimestamp(task['created']).strftime('%m-%d %H:%M:%S'))
            if task['id'] in known:
                self.tree.item(task['id'], text=task['label'], values=values)
            else:
                self.tree.insert('', 0, iid=task['id'], text=task['label'], values=values)
        for stale in known - {task['id'] for task in tasks}:
            self.tree.delete(stale)
        self.show_selected()
        if schedule:
            self.poll_job = self.win.after(250, self.refresh)

    def selected_task(self):
        selected = self.tree.selection()
        return self.manager.get_task(selected[0]) if selected else None

    def show_selected(self):
        task = self.selected_task()
        self.cancel_button.configure(state='normal' if task and task.get('can_cancel') else 'disabled')
        self.retry_button.configure(state='normal' if task and task['can_retry'] else 'disabled')
        restored = bool(task and task['kind'] == 'restore' and task['status'] == 'succeeded')
        self.use_button.configure(state='normal' if restored and self.on_restored else 'disabled')
        if task:
            text = task['error'] or task['message']
            if task['status'] in TaskManager.ACTIVE and not task.get('can_cancel'):
                text += '\n此任务需要完整执行，暂不支持取消；完成后可正常退出程序。'
            result = task.get('result')
            if isinstance(result, dict):
                if result.get('path'):
                    text += '\n' + result['path']
                warnings = result.get('warnings', [])
                if warnings:
                    text += f'\n有 {len(warnings)} 个缺失附件：' + '；'.join(warnings[:3])
                    if len(warnings) > 3:
                        text += '…（完整记录保存在备份清单）'
            self.detail.set(text)

    def cancel_selected(self):
        task = self.selected_task()
        if task:
            self.manager.cancel(task['id'])
            self.refresh(schedule=False)

    def retry_selected(self):
        task = self.selected_task()
        if task:
            try:
                task_id = self.manager.retry(task['id'])
                self.refresh(schedule=False)
                self.tree.selection_set(task_id)
            except Exception as exc:
                self.status.set(str(exc))

    def use_restored(self):
        task = self.selected_task()
        if self.on_restored and task and task['kind'] == 'restore' and task['status'] == 'succeeded':
            self.on_restored(Path(task['result']['path']))

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.poll_job:
            self.win.after_cancel(self.poll_job)
            self.poll_job = None
        self.win.destroy()
