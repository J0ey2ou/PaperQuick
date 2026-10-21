"""Column sorting/filtering shared by the library header and its popovers."""
import re
import tkinter as tk
from tkinter import ttk
from library_core import display_name,readable_attachments
from ui_theme import style_dialog,FONT

LABELS={'title':'论文标题','year':'年份','project':'主课题','tags':'标签','status':'阅读状态','rating':'评分','pdf':'全文'}


def values(record,projects):
    return {'title':display_name(record),'year':str(record.get('year') or ''),'project':projects.get(record.get('primary_project'),'未分类'),
            'tags':record.get('tags') or [],'status':record.get('status') or '', 'rating':str(record.get('rating') or 0),
            'pdf':'已归档' if any(a.get('role')=='primary' for a in readable_attachments(record)) else '待添加'}


class TableState:
    def __init__(self):self.sort_key=None;self.descending=False;self.filters={}

    def sort(self,key):
        self.descending=not self.descending if self.sort_key==key else False;self.sort_key=key

    def matches(self,row,ignore=None):
        for key,criterion in self.filters.items():
            if key==ignore:continue
            value=row[key];selected=criterion.get('values',[]);query=criterion.get('contains','').casefold()
            cells=(value or ['']) if isinstance(value,list) else [value]
            if selected and not any(cell in selected for cell in cells):return False
            if query and query not in '；'.join(cells).casefold():return False
        return True

    def ordered(self,records,rows):
        key=self.sort_key
        if not key:return records
        def number(row):
            found=re.search(r'\d+',row[key]);return int(found.group()) if found else None
        if key in ('year','rating'):
            known=[r for r in records if number(rows[r['id']]) is not None];blank=[r for r in records if number(rows[r['id']]) is None]
            return sorted(known,key=lambda r:number(rows[r['id']]),reverse=self.descending)+blank
        return sorted(records,key=lambda r:('；'.join(rows[r['id']][key]) if isinstance(rows[r['id']][key],list) else rows[r['id']][key]).casefold(),reverse=self.descending)


class ColumnFilter:
    def __init__(self,owner,key,x,y):
        self.owner=owner;self.key=key;self.state=owner.table_state;self.all_values=owner.column_choices(key)
        self.win=tk.Toplevel(owner.win);self.win.title(LABELS[key]+'筛选');style_dialog(self.win)
        self.win.geometry(f'310x410+{max(0,x-245)}+{max(0,y)}');self.win.transient(owner.win.winfo_toplevel())
        form=ttk.Frame(self.win,padding=16);form.pack(fill='both',expand=True)
        ttk.Label(form,text=LABELS[key],font=(FONT,12,'bold')).pack(anchor='w')
        self.query=tk.StringVar(value=self.state.filters.get(key,{}).get('contains',''))
        ttk.Label(form,text='包含文字（可留空）',style='Muted.TLabel').pack(anchor='w',pady=(12,4))
        ttk.Entry(form,textvariable=self.query).pack(fill='x')
        ttk.Label(form,text='选择值；Ctrl / Shift 可多选',wraplength=260,style='Muted.TLabel').pack(anchor='w',pady=(12,4))
        body=ttk.Frame(form);body.pack(fill='both',expand=True)
        self.list=tk.Listbox(body,selectmode='extended',exportselection=False,relief='flat',borderwidth=0,highlightthickness=0,activestyle='none',font=(FONT,10))
        scroll=ttk.Scrollbar(body,command=self.list.yview);scroll.pack(side='right',fill='y');self.list.configure(yscrollcommand=scroll.set);self.list.pack(fill='both',expand=True)
        selected=self.state.filters.get(key,{}).get('values',[])
        for index,value in enumerate(self.all_values):
            label=('未评分' if value=='0' else value+' 星') if key=='rating' else value or '（空白）'
            self.list.insert('end',label)
            if value in selected:self.list.selection_set(index)
        buttons=ttk.Frame(form);buttons.pack(fill='x',pady=(14,0))
        ttk.Button(buttons,text='清除此列',command=self.clear).pack(side='left')
        ttk.Button(buttons,text='应用筛选',command=self.apply,style='Accent.TButton').pack(side='right')
        self.win.bind('<Escape>',lambda _:self.win.destroy())
        self.win.bind('<Return>',lambda _:self.apply())

    def clear(self):self.state.filters.pop(self.key,None);self.owner.refresh_records();self.win.destroy()

    def apply(self):
        selected=[self.all_values[index] for index in self.list.curselection()];query=self.query.get().strip()
        if selected or query:self.state.filters[self.key]={'values':selected,'contains':query}
        else:self.state.filters.pop(self.key,None)
        self.owner.refresh_records();self.win.destroy()
