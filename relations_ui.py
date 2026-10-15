"""Shared explicit relationship editor for library and graph pages."""
import tkinter as tk
from tkinter import ttk, messagebox
from library_core import Library, display_name
from ui_theme import style_dialog, FONT


def relationship_editor(parent, directory, selected=(), on_saved=None):
    lib=Library(directory)
    try:records=lib.records()
    finally:lib.close()
    if len(records)<2:
        messagebox.showinfo('添加关系','文献库中至少需要两篇文献。',parent=parent);return
    ids=[r['id'] for r in records]
    chosen=[rid for rid in selected if rid in ids]
    values={f"{display_name(r)}  [{r['id'][:8]}]":r['id'] for r in records}
    reverse={rid:label for label,rid in values.items()}
    dialog=tk.Toplevel(parent);dialog.title('添加两篇文献的关系');style_dialog(dialog)
    panel=ttk.Frame(dialog,padding=20);panel.pack(fill='both',expand=True)
    ttk.Label(panel,text='选择两篇文献，说明它们为什么相关',font=(FONT,12,'bold')).pack(anchor='w',pady=(0,12))
    fields=[]
    for i,label in enumerate(('第一篇文献','第二篇文献')):
        ttk.Label(panel,text=label).pack(anchor='w')
        initial=chosen[i] if i<len(chosen) else next(rid for rid in ids if not i or rid!=values.get(fields[0].get()))
        var=tk.StringVar(value=reverse[initial]);fields.append(var)
        combo=ttk.Combobox(panel,textvariable=var,values=list(values),width=85)
        combo.pack(fill='x',pady=(5,12))
        def filter_options(event,widget=combo,variable=var):
            term=variable.get().casefold();widget.configure(values=[v for v in values if term in v.casefold()])
        combo.bind('<KeyRelease>',filter_options)
    ttk.Label(panel,text='关联原因（例如：使用同一队列、方法相同、结果相互补充）').pack(anchor='w')
    reason=tk.StringVar();ttk.Entry(panel,textvariable=reason,width=85).pack(fill='x',pady=8)
    def save():
        if any(v.get() not in values for v in fields):
            messagebox.showerror('请选中文献','请从下拉列表选择两篇文献。',parent=dialog);return
        lib=Library(directory)
        try:lib.relate(values[fields[0].get()],values[fields[1].get()],reason.get())
        except ValueError as exc:messagebox.showerror('关系未保存',str(exc),parent=dialog);return
        finally:lib.close()
        dialog.destroy()
        if on_saved:on_saved()
    buttons=ttk.Frame(panel);buttons.pack(fill='x',pady=12)
    ttk.Button(buttons,text='取消',command=dialog.destroy).pack(side='left')
    ttk.Button(buttons,text='保存关系',command=save,style='Accent.TButton').pack(side='right')
    return dialog
