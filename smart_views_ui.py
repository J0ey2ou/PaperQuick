"""Smart-view controls shared by the library and research workbench."""
import tkinter as tk
import copy
from tkinter import ttk, simpledialog, messagebox
from workspace_state import WorkspaceStore
from ui_theme import style_dialog


class SmartViewsMixin:
    def view_criteria(self):
        columns=self.tree['displaycolumns']
        return dict(project=self.current_project,query=self.search.get(),status=self.status_filter.get(),
                    rating=self.rating_filter.get(),tag=self.tag_filter.get(),filters=copy.deepcopy(self.table_state.filters),
                    sort_key=self.table_state.sort_key,descending=self.table_state.descending,
                    columns=list(self.tree['columns']) if '#all' in columns else list(columns))

    def apply_view(self, criteria):
        store=WorkspaceStore(self.library.root)
        try:criteria=store.validate_view(criteria)
        finally:store.close()
        self.current_project=criteria['project'];self.search.set(criteria['query'])
        self.status_filter.set(criteria['status']);self.rating_filter.set(criteria['rating']);self.tag_filter.set(criteria['tag'])
        self.table_state.filters=criteria['filters'];self.table_state.sort_key=criteria['sort_key'];self.table_state.descending=criteria['descending']
        self.tree.configure(displaycolumns=criteria['columns'] or '#all')
        self.extra_view_criteria=criteria
        self.refresh()

    def save_smart_view(self):
        name=simpledialog.askstring('保存智能视图','名称（保存当前课题、筛选、排序及显示列）：',parent=self.win)
        if not name:return
        store=WorkspaceStore(self.library.root)
        try:
            criteria={**getattr(self,'extra_view_criteria',{}),**self.view_criteria()}
            store.save_view(name,criteria);self.status.set('智能视图已保存；后续导入的文献会自动参与筛选。')
        except ValueError as exc:messagebox.showerror('智能视图',str(exc),parent=self.win)
        finally:store.close()

    def smart_views(self):
        dialog=tk.Toplevel(self.win);dialog.title('智能视图');dialog.geometry('650x440');style_dialog(dialog)
        frame=ttk.Frame(dialog,padding=18);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='保存条件，文献变化后自动更新结果。').pack(anchor='w',pady=(0,10))
        tree=ttk.Treeview(frame,columns=('name','scope'),show='headings');tree.heading('name',text='视图');tree.heading('scope',text='课题范围');tree.pack(fill='both',expand=True)
        saved_views={}
        def refresh():
            tree.delete(*tree.get_children());store=WorkspaceStore(self.library.root)
            try:
                saved_views.clear();saved_views.update({v['id']:v for v in store.views()});projects={p['id']:p['name'] for p in store.library.projects()}
                for v in saved_views.values():tree.insert('','end',iid=v['id'],values=(v['name'],projects.get(v['criteria'].get('project'),'课题已不存在' if v['criteria'].get('project') else '全部文献')))
            finally:store.close()
        def load():
            if not tree.selection():return
            try:self.apply_view(saved_views[tree.selection()[0]]['criteria']);dialog.destroy()
            except ValueError as exc:messagebox.showerror('智能视图',str(exc),parent=dialog)
        def remove():
            if not tree.selection():return
            if not messagebox.askyesno('删除智能视图','删除此视图？文献与课题仍会保留。',parent=dialog):return
            store=WorkspaceStore(self.library.root)
            try:store.delete_view(tree.selection()[0]);refresh()
            finally:store.close()
        bar=ttk.Frame(frame);bar.pack(fill='x',pady=(12,0))
        ttk.Button(bar,text='删除所选视图',command=remove).pack(side='left')
        ttk.Button(bar,text='应用',command=load,style='Accent.TButton').pack(side='right')
        tree.bind('<Double-1>',lambda _:load());refresh()

    def choose_columns(self):
        from library_table import LABELS
        dialog=tk.Toplevel(self.win);dialog.title('显示列');style_dialog(dialog)
        frame=ttk.Frame(dialog,padding=18);frame.pack(fill='both',expand=True)
        current=self.view_criteria()['columns'];variables={}
        for key,title in LABELS.items():
            value=tk.BooleanVar(value=key in current);variables[key]=value
            ttk.Checkbutton(frame,text=title,variable=value,state='disabled' if key=='title' else 'normal').pack(anchor='w')
        def apply():self.tree.configure(displaycolumns=[k for k,v in variables.items() if v.get() or k=='title']);dialog.destroy()
        ttk.Button(frame,text='应用',command=apply).pack(pady=(12,0))

    def enqueue_selected(self):
        papers=self.selected()
        if not papers:return
        def add(project):
            store=WorkspaceStore(self.library.root)
            try:store.enqueue(project,papers);self.status.set(f'已加入课题阅读队列：{len(papers)} 篇。')
            except ValueError as exc:messagebox.showerror('阅读队列',str(exc),parent=self.win)
            finally:store.close()
        if self.current_project:add(self.current_project)
        else:self.choose_project(add,'加入课题阅读队列')
