"""Select folder documents before any file is copied into the library."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from ui_theme import style_dialog,FONT

class ImportSelection:
    def __init__(self,parent,paths,on_accept):
        self.paths=list(paths);self.checked=set(range(len(self.paths)));self.on_accept=on_accept
        self.win=tk.Toplevel(parent);style_dialog(self.win);self.win.title('选择要导入的文献');self.win.geometry('940x660');self.win.minsize(700,480);self.win.transient(parent.winfo_toplevel())
        panel=ttk.Frame(self.win,padding=20);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='只收纳你需要的文献',font=(FONT,18,'bold')).pack(anchor='w')
        ttk.Label(panel,text='勾选需要导入的文件，取消勾选不需要的文件。确认后再选择课题。',style='Muted.TLabel').pack(anchor='w',pady=(7,14))
        bar=ttk.Frame(panel);bar.pack(fill='x');ttk.Label(bar,text='筛选文件').pack(side='left')
        self.search=tk.StringVar();ttk.Entry(bar,textvariable=self.search).pack(side='left',fill='x',expand=True,padx=10)
        ttk.Button(bar,text='全选当前列表',command=lambda:self.select(True)).pack(side='left',padx=3);ttk.Button(bar,text='全部取消',command=lambda:self.select(False)).pack(side='left')
        bottom=ttk.Frame(panel);bottom.pack(side='bottom',fill='x',pady=(12,0))
        self.count=tk.StringVar();ttk.Label(bottom,textvariable=self.count).pack(side='left');ttk.Button(bottom,text='取消',command=self.win.destroy).pack(side='right');ttk.Button(bottom,text='导入已勾选',style='Accent.TButton',command=self.accept).pack(side='right',padx=8)
        self.tree=ttk.Treeview(panel,columns=('checked','name','folder'),show='headings',selectmode='extended',height=6)
        for key,label,width in [('checked','导入',65),('name','文献文件',330),('folder','所在文件夹',430)]:self.tree.heading(key,text=label);self.tree.column(key,width=width,stretch=key!='checked')
        scroll=ttk.Scrollbar(panel,command=self.tree.yview);scroll.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scroll.set);self.tree.pack(fill='both',expand=True,pady=(12,0))
        self.tree.bind('<Button-1>',self.click);self.tree.bind('<Double-1>',lambda e:self.toggle(self.tree.identify_row(e.y)));self.tree.bind('<space>',lambda e:self.toggle_selected())
        self.search.trace_add('write',lambda *_:self.refresh());self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children());term=self.search.get().casefold()
        for i,p in enumerate(self.paths):
            if term not in str(p).casefold():continue
            self.tree.insert('','end',iid=str(i),values=('☑' if i in self.checked else '☐',Path(p).name,str(Path(p).parent)))
        self.count.set(f'已勾选 {len(self.checked)} / {len(self.paths)} 份文档')
    def click(self,event):
        if self.tree.identify_column(event.x)=='#1':self.toggle(self.tree.identify_row(event.y));return 'break'
    def toggle(self,iid):
        if not iid:return
        i=int(iid)
        if i in self.checked:self.checked.remove(i)
        else:self.checked.add(i)
        self.tree.set(iid,'checked','☑' if i in self.checked else '☐');self.count.set(f'已勾选 {len(self.checked)} / {len(self.paths)} 份文档')
    def toggle_selected(self):
        for iid in self.tree.selection():self.toggle(iid)
        return 'break'
    def select(self,checked):
        for iid in self.tree.get_children():
            if checked:self.checked.add(int(iid))
            else:self.checked.discard(int(iid))
        self.refresh()
    def accept(self):
        paths=[p for i,p in enumerate(self.paths) if i in self.checked]
        if not paths:messagebox.showinfo('尚未选择','请至少勾选一份文档。',parent=self.win);return
        self.win.destroy();self.on_accept(paths)
