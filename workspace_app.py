"""Lazy application wiring for research services and their shared task queue."""
from pathlib import Path
from tkinter import messagebox, filedialog


class WorkspaceAppMixin:
    def init_workspace(self):
        self.workspace_page=None;self.task_manager=None;self.workspace_windows=[]

    def tasks(self):
        if self.task_manager is None:
            from workspace_tasks import TaskManager
            from maintenance_ui import register_maintenance_tasks
            self.task_manager=TaskManager(self.library_directory)
            register_maintenance_tasks(self.task_manager)
        return self.task_manager

    def make_workspace(self):
        from workspace_ui import WorkspacePage
        self.workspace_page=WorkspacePage(self.page_host,self.library_directory,{
            'resume':self.continue_reading, 'library':self.open_project_library,
            'search':self.open_fulltext, 'research':self.open_research, 'ai':self.open_project_ai,
            'handoff':self.open_handoff, 'maintenance':lambda _:self.open_maintenance(),
            'read':self.open_reader,'view':self.open_saved_view})

    def open_project_library(self,project=None):
        window=self.open_library();window.current_project=project;window.refresh()

    def open_saved_view(self,criteria):self.open_library().apply_view(criteria)

    def continue_reading(self,project=None):
        from library_core import Library
        library=Library(self.library_directory)
        try:
            if project:
                recent=sorted((r for r in library.records(project,summary=True) if r.get('last_read')),key=lambda r:float(r['last_read']),reverse=True)[:1]
            else:recent=library.recent_read(1)
        finally:library.close()
        if recent:self.open_reader(recent[0]['id'])
        else:messagebox.showinfo('继续阅读','打开一篇文献后，这里会恢复上次的阅读现场。',parent=self.root)

    def _workspace_window(self,window):
        self.workspace_windows=[w for w in self.workspace_windows if not getattr(w,'closed',False)]
        self.workspace_windows.append(window)
        from ui_theme import apply_skin
        apply_skin(self.root,self.skin)
        return window

    def open_fulltext(self,project=None):
        from search_ui import SearchWindow
        return self._workspace_window(SearchWindow(self.root,self.library_directory,project=project,
                    on_open=self.open_source,manager=self.tasks(),on_location=self.open_search_location))

    def open_search_location(self,result):
        if result.get('locator_kind') in ('record','note') and not result.get('attachment'):
            from library_core import Library
            library=Library(self.library_directory)
            try:attachment=library.primary_attachment(result['paper'])
            finally:library.close()
            if result.get('locator_kind')=='record' or not attachment:
                window=self.open_library()
                if not window.tree.exists(result['paper']):
                    window.current_project=None;window.refresh();window.clear_column_filters()
                if window.tree.exists(result['paper']):
                    window.tree.selection_set(result['paper']);window.tree.see(result['paper']);window.detail()
                else:messagebox.showinfo('来源已变化','此文献已不存在，请重新检索。',parent=self.root)
                return
        self.show_page('reader')
        try:self.reader_page.open_search_result(result)
        except Exception as exc:messagebox.showerror('来源未打开',str(exc),parent=self.root)

    def open_source(self,rid,attachment_id=None,page=None):
        self.show_page('reader')
        try:self.reader_page.open(rid,attachment_id=attachment_id,anchor={'page':page} if page is not None else None)
        except Exception as exc:messagebox.showerror('来源未打开',str(exc),parent=self.root)

    def open_research(self,project=None):
        from research_ui import ResearchWindow
        return self._workspace_window(ResearchWindow(self.root,self.library_directory,project=project,on_open=self.open_source,on_location=self.open_search_location))

    def capture_evidence(self,data):
        from library_core import Library
        library=Library(self.library_directory)
        try:project=library.get(data['paper'])['primary_project']
        finally:library.close()
        self.open_research(project).new_card(data)

    def open_project_ai(self,project=None):
        from project_ai_ui import ProjectAIWindow
        return self._workspace_window(ProjectAIWindow(self.root,self.library_directory,project=project,
                    manager=self.tasks(),on_location=self.open_search_location))

    def open_handoff(self,project=None):
        from project_handoff_ui import ProjectHandoffWindow
        return self._workspace_window(ProjectHandoffWindow(self.root,self.library_directory,project=project,
                    manager=self.tasks(),on_imported=self.use_library_next_start))

    def open_maintenance(self):
        from maintenance_ui import MaintenanceWindow
        return self._workspace_window(MaintenanceWindow(self.root,self.library_directory,manager=self.tasks(),on_restored=self.use_library_next_start))

    def use_library_next_start(self,directory):
        directory=Path(directory).resolve()
        if not (directory/'library.sqlite').is_file():raise ValueError('所选文件夹没有有效文献库。')
        from preferences import save_preferences
        self.preferences=save_preferences(self.config_path,{'library_directory':str(directory)})
        messagebox.showinfo('文献库已选定',f'下次启动将打开：\n{directory}\n\n当前文献库继续可用。请正常退出后重新打开软件。',parent=self.root)

    def select_library_next_start(self):
        directory=filedialog.askdirectory(title='选择已有文献库（包含 library.sqlite）',parent=self.root)
        if not directory:return
        try:
            import sqlite3
            path=Path(directory).resolve()/'library.sqlite'
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
                db.execute('PRAGMA trusted_schema=OFF')
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('数据库完整性检查失败。')
                if not {'papers','projects','attachments'} <= {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:raise ValueError('这不是 PaperQuick 文献库。')
            self.use_library_next_start(directory)
        except Exception as exc:messagebox.showerror('无法切换文献库',str(exc),parent=self.root)

    def can_close_workspace(self):
        try:
            if self.workspace_page:self.workspace_page.save_question(silent=True)
        except Exception as exc:
            messagebox.showerror('研究问题未保存',str(exc),parent=self.root);return False
        for window in self.workspace_windows:
            if getattr(window,'closed',False):continue
            check=getattr(window,'can_close',None)
            if check and not check():return False
        return True

    def close_workspace(self,discard_confirmed=False):
        if not discard_confirmed and not self.can_close_workspace():return False
        for window in self.workspace_windows:
            if getattr(window,'closed',False):continue
            if window.win.winfo_exists():
                from research_ui import ResearchWindow
                result=window.close(discard_confirmed=True) if isinstance(window,ResearchWindow) else window.close()
                if result is False:return False
        if self.workspace_page:self.workspace_page.close()
        if self.task_manager:self.task_manager.close(wait=False)
        return True
