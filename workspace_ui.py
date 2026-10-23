"""Project workbench: a single entry for reading, evidence and research output."""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from workspace_state import WorkspaceStore
from library_core import display_name
from ui_widgets import flow_bar
from ui_theme import FONT


class WorkspacePage:
    def __init__(self,parent,directory,actions):
        self.store=WorkspaceStore(directory);self.actions=actions;self.project=None;self.closed=False
        self.frame=ttk.Frame(parent,padding=(24,12))
        heading=ttk.Frame(self.frame);heading.pack(fill='x')
        ttk.Label(heading,text='研究工作台',font=(FONT,21,'bold')).pack(side='left')
        self.project_var=tk.StringVar()
        self.project_combo=ttk.Combobox(heading,textvariable=self.project_var,state='readonly',width=34)
        self.project_combo.pack(side='right');self.project_combo.bind('<<ComboboxSelected>>',self.change_project)
        self.summary=tk.StringVar();ttk.Label(self.frame,textvariable=self.summary,style='Muted.TLabel').pack(anchor='w',pady=(6,12))
        bar=ttk.Frame(self.frame);bar.pack(fill='x',pady=(0,12));flow_bar(bar)
        for label,key in [('继续阅读','resume'),('课题文献','library'),('全文检索 / OCR','search'),('证据与写作','research'),('跨文献 AI','ai'),('课题交接','handoff'),('备份 / 任务','maintenance')]:
            ttk.Button(bar,text=label,command=lambda k=key:self.act(k),style='Accent.TButton' if key=='research' else 'TButton').pack(side='left',padx=(0,8))
        body=ttk.Panedwindow(self.frame,orient='horizontal');body.pack(fill='both',expand=True)
        left=ttk.Frame(body,padding=14,style='Card.TFrame');right=ttk.Frame(body,padding=14,style='Card.TFrame');body.add(left,weight=1);body.add(right,weight=2)
        ttk.Label(left,text='研究问题',font=(FONT,12,'bold')).pack(anchor='w')
        self.question=tk.Text(left,height=4,width=30,wrap='word',font=(FONT,10),undo=True,exportselection=False);self.question.pack(fill='x',pady=8)
        ttk.Button(left,text='保存研究问题',command=self.save_question).pack(anchor='e')
        ttk.Label(left,text='课题待办',font=(FONT,12,'bold')).pack(anchor='w',pady=(16,8))
        self.todos=self.table(left,('title','due'),('待办 / 完成状态','截止日期'),(260,100),height=5)
        todo_bar=ttk.Frame(left);todo_bar.pack(fill='x',pady=8);flow_bar(todo_bar)
        for label,func in [('添加',self.add_todo),('完成 / 继续',self.toggle_todo),('删除',self.delete_todo)]:ttk.Button(todo_bar,text=label,command=func).pack(side='left',padx=(0,6))
        ttk.Label(left,text='智能视图',font=(FONT,12,'bold')).pack(anchor='w',pady=(12,8))
        self.views=self.table(left,('name',),('已保存的筛选条件',),(300,),height=4)
        self.views.bind('<Double-1>',lambda _:self.open_view())
        ttk.Button(left,text='打开所选视图',command=self.open_view).pack(anchor='e',pady=8)
        ttk.Label(right,text='阅读队列',font=(FONT,12,'bold')).pack(anchor='w')
        ttk.Label(right,text='在文献列表右键加入队列，按安排顺序继续阅读。',style='Muted.TLabel').pack(anchor='w',pady=(6,8))
        self.queue=self.table(right,('title','status'),('文献','状态'),(400,80),height=9)
        self.queue.bind('<Double-1>',lambda _:self.read_queue())
        queue_bar=ttk.Frame(right);queue_bar.pack(fill='x',pady=8)
        ttk.Button(queue_bar,text='阅读',command=self.read_queue,style='Accent.TButton').pack(side='left')
        ttk.Button(queue_bar,text='移出队列',command=self.remove_queue).pack(side='left',padx=8)
        ttk.Label(right,text='最近阅读',font=(FONT,12,'bold')).pack(anchor='w',pady=(12,8))
        self.recent=self.table(right,('title',),('点击两次恢复阅读现场',),(480,),height=5)
        self.recent.bind('<Double-1>',lambda _:self.read_recent())
        self.feedback=tk.StringVar();ttk.Label(self.frame,textvariable=self.feedback,style='Muted.TLabel').pack(fill='x',pady=(10,0))
        self.refresh()

    @staticmethod
    def table(parent,columns,labels,widths,height=5):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=columns,show='headings',height=height,selectmode='browse')
        scroll=ttk.Scrollbar(frame,command=tree.yview);tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');tree.pack(fill='both',expand=True)
        for key,label,width in zip(columns,labels,widths):tree.heading(key,text=label);tree.column(key,width=width,minwidth=70,stretch=True)
        return tree

    def act(self,key):
        try:
            self.save_question(silent=True)
            self.actions[key](self.project)
        except Exception as exc:messagebox.showerror('研究工作台',str(exc),parent=self.frame)

    def refresh(self):
        if self.closed:return
        # Refreshing after another page changes must not discard the current
        # question draft. On a failed save leave the draft and selection intact.
        if self.project and hasattr(self,'_question_saved'):
            try:self.save_question(silent=True)
            except Exception as exc:self.feedback.set('研究问题尚未保存：'+str(exc));return False
        projects=self.store.library.projects();self.project_rows=projects
        self.project_combo.configure(values=[p['name'] for p in projects])
        if self.project not in {p['id'] for p in projects}:self.project=projects[0]['id'] if projects else None
        if self.project:self.project_combo.current(next(i for i,p in enumerate(projects) if p['id']==self.project))
        self.load_project()
        self.views.delete(*self.views.get_children());self.saved_views={v['id']:v for v in self.store.views()}
        for view in self.saved_views.values():self.views.insert('','end',iid=view['id'],values=(view['name'],))
        self.recent.delete(*self.recent.get_children())
        for record in self.store.library.recent_read(12):self.recent.insert('','end',iid=record['id'],values=(record['title'],))

    def change_project(self,_=None):
        index=self.project_combo.current()
        try:self.save_question(silent=True)
        except Exception as exc:
            self.project_var.set(next((p['name'] for p in self.project_rows if p['id']==self.project),''))
            self.feedback.set('研究问题尚未保存，已保留当前课题：'+str(exc));return
        if index>=0:self.project=self.project_rows[index]['id'];self.load_project()

    def load_project(self):
        self.question.delete('1.0','end');self.todos.delete(*self.todos.get_children());self.queue.delete(*self.queue.get_children())
        if not self.project:return
        self.question.insert('1.0',self.store.question(self.project));self._question_saved=self.question.get('1.0','end-1c')
        self.todo_rows={t['id']:t for t in self.store.todos(self.project)}
        for task in self.todo_rows.values():self.todos.insert('','end',iid=task['id'],values=(('✓ ' if task['done'] else '○ ')+task['title'],task['due']))
        for r in self.store.queue(self.project):self.queue.insert('','end',iid=r['id'],values=(display_name(r),r['status']))
        records=self.store.library.records(self.project,summary=True)
        self.summary.set(f"包含子课题 · {len(records)} 篇文献 · {sum(r['status']=='已读' for r in records)} 篇已读 · {sum(not t['done'] for t in self.todo_rows.values())} 项待办")

    def save_question(self,silent=False):
        if not self.project:return
        text=self.question.get('1.0','end-1c')
        if text!=getattr(self,'_question_saved',None):self.store.set_question(self.project,text);self._question_saved=text
        if not silent:self.feedback.set('研究问题已保存。')

    def add_todo(self):
        title=simpledialog.askstring('课题待办','要完成的工作：',parent=self.frame)
        if not title:return
        due=simpledialog.askstring('截止日期','YYYY-MM-DD，可留空：',parent=self.frame)
        if due is None:return
        try:self.save_question(silent=True);self.store.save_todo(self.project,title,due);self.load_project()
        except ValueError as exc:messagebox.showerror('课题待办',str(exc),parent=self.frame)

    def toggle_todo(self):
        if not self.todos.selection():return
        self.save_question(silent=True);task=self.todo_rows[self.todos.selection()[0]]
        self.store.save_todo(self.project,task['title'],task['due'],task['id'],not task['done']);self.load_project()

    def delete_todo(self):
        if self.todos.selection():self.save_question(silent=True);self.store.delete_todo(self.todos.selection()[0]);self.load_project()

    def read_queue(self):
        if self.queue.selection():self.save_question(silent=True);self.actions['read'](self.queue.selection()[0])

    def read_recent(self):
        if self.recent.selection():self.save_question(silent=True);self.actions['read'](self.recent.selection()[0])

    def remove_queue(self):
        if self.queue.selection():self.save_question(silent=True);self.store.dequeue(self.project,self.queue.selection()[0]);self.load_project()

    def open_view(self):
        if self.views.selection():self.save_question(silent=True);self.actions['view'](self.saved_views[self.views.selection()[0]]['criteria'])

    def close(self):
        if self.closed:return
        self.save_question(silent=True);self.store.close();self.closed=True
