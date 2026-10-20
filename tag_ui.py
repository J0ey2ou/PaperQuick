"""Reusable tag selection and library-wide management."""
import tkinter as tk
from tkinter import ttk,messagebox,simpledialog
from library_organization import normalize_tags
from ui_theme import style_dialog


def tag_picker(parent, library, initial, accept):
    dialog=tk.Toplevel(parent);style_dialog(dialog);dialog.title('编辑标签');dialog.geometry('520x480')
    panel=ttk.Frame(dialog,padding=20);panel.pack(fill='both',expand=True)
    ttk.Label(panel,text='选择已有标签，或输入新标签',style='Section.TLabel').pack(anchor='w')
    value=tk.StringVar(value='；'.join(initial));ttk.Entry(panel,textvariable=value).pack(fill='x',pady=12)
    ttk.Label(panel,text='点击下方标签切换选中；新标签可用分号分隔。',style='Muted.TLabel').pack(anchor='w')
    container=ttk.Frame(panel);container.pack(fill='both',expand=True,pady=10)
    tags=library.all_tags();listing=tk.Listbox(container,selectmode='multiple',exportselection=False,activestyle='none')
    scroll=ttk.Scrollbar(container,command=listing.yview);scroll.pack(side='right',fill='y');listing.configure(yscrollcommand=scroll.set);listing.pack(fill='both',expand=True)
    for tag in tags:listing.insert('end',tag)
    syncing=[False]
    def sync(*_):
        if syncing[0]:return
        try:keys={t.casefold() for t in normalize_tags(value.get())}
        except ValueError:return
        listing.selection_clear(0,'end')
        for i,tag in enumerate(tags):
            if tag.casefold() in keys:listing.selection_set(i)
    def select(_):
        try:current=normalize_tags(value.get())
        except ValueError:current=[]
        known={t.casefold() for t in tags};chosen=[tags[i] for i in listing.curselection()]
        syncing[0]=True;value.set('；'.join([t for t in current if t.casefold() not in known]+chosen));syncing[0]=False
    value.trace_add('write',sync);listing.bind('<<ListboxSelect>>',select);sync()
    def save():
        try:result=normalize_tags(value.get())
        except ValueError as exc:messagebox.showerror('标签未保存',str(exc),parent=dialog);return
        accept(result);dialog.destroy()
    ttk.Button(panel,text='保存标签',command=save,style='Accent.TButton').pack(anchor='e')
    return dialog


def tag_manager(parent, library, changed):
    dialog=tk.Toplevel(parent);style_dialog(dialog);dialog.title('标签管理');dialog.geometry('540x470')
    panel=ttk.Frame(dialog,padding=20);panel.pack(fill='both',expand=True)
    ttk.Label(panel,text='管理整个文献库的标签',style='Section.TLabel').pack(anchor='w')
    ttk.Label(panel,text='重命名会同步文献和自动归类规则；同名标签会合并。',style='Muted.TLabel',wraplength=470).pack(anchor='w',pady=8)
    listing=tk.Listbox(panel,exportselection=False);listing.pack(fill='both',expand=True)
    def fill():
        listing.delete(0,'end')
        for tag in library.all_tags():listing.insert('end',tag)
    def operate(rename):
        if not listing.curselection():return
        old=listing.get(listing.curselection()[0]);new=None
        if rename:
            new=simpledialog.askstring('重命名标签','新名称',initialvalue=old,parent=dialog)
            if new is None:return
        elif not messagebox.askyesno('删除标签',f'从所有文献和归类规则中移除“{old}”？文献及手动课题分类会保留。',parent=dialog):return
        try:library.change_tag(old,new)
        except ValueError as exc:messagebox.showerror('未完成',str(exc),parent=dialog);return
        fill();changed()
    fill();bar=ttk.Frame(panel);bar.pack(fill='x',pady=(12,0))
    ttk.Button(bar,text='重命名 / 合并',command=lambda:operate(True)).pack(side='left')
    ttk.Button(bar,text='删除此标签',command=lambda:operate(False)).pack(side='right')
    return dialog
