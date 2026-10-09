from datetime import date,timedelta
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
from library_core import Library
from reading_stats import daily_recap,recap_text,duration
from ui_theme import BG,FG,INPUT,MUTED,FONT,ACCENT


class SummaryView:
    def __init__(self,parent,directory):
        self.directory=directory;self.frame=ttk.Frame(parent,padding=24)
        ttk.Label(self.frame,text='阅读总结',font=(FONT,21,'bold')).pack(anchor='w')
        ttk.Label(self.frame,text='回看昨日读了什么、读了多久。计时从本版开始。',style='Muted.TLabel').pack(anchor='w',pady=(6,18))
        bar=ttk.Frame(self.frame);bar.pack(fill='x')
        self.day=tk.StringVar(value=(date.today()-timedelta(days=1)).isoformat());entry=ttk.Entry(bar,textvariable=self.day,width=14);entry.pack(side='left');entry.bind('<Return>',lambda _:self.refresh())
        for label,command in [('昨日',lambda:self.set_day(-1)),('今日',lambda:self.set_day(0)),('查看',self.refresh),('复制总结',self.copy),('导出总结',self.export)]:ttk.Button(bar,text=label,command=command).pack(side='left',padx=5)
        self.metrics=tk.StringVar();ttk.Label(self.frame,textvariable=self.metrics,font=(FONT,15,'bold'),foreground=ACCENT).pack(anchor='w',pady=18)
        area=ttk.Frame(self.frame);area.pack(fill='both',expand=True)
        self.text=tk.Text(area,wrap='word',font=(FONT,11),bg=INPUT,fg=FG,padx=18,pady=15,relief='flat',state='disabled')
        scroll=ttk.Scrollbar(area,command=self.text.yview);scroll.pack(side='right',fill='y');self.text.configure(yscrollcommand=scroll.set);self.text.pack(fill='both',expand=True)
    def set_day(self,delta):self.day.set((date.today()+timedelta(days=delta)).isoformat());self.refresh()
    def refresh(self):
        try:day=date.fromisoformat(self.day.get())
        except ValueError:messagebox.showerror('日期格式','请输入 YYYY-MM-DD，例如 2026-10-09。',parent=self.frame);return
        lib=Library(self.directory)
        try:self.data=daily_recap(lib,day)
        finally:lib.close()
        self.metrics.set(f"{self.data['count']} 篇文献  ·  {duration(self.data['seconds'])}");self.content=recap_text(self.data)
        self.text.configure(state='normal');self.text.delete('1.0','end');self.text.insert('1.0',self.content);self.text.configure(state='disabled')
    def copy(self):self.frame.clipboard_clear();self.frame.clipboard_append(self.content)
    def export(self):
        path=filedialog.asksaveasfilename(parent=self.frame,initialfile=f"阅读总结-{self.day.get()}.md",defaultextension='.md',filetypes=[('Markdown','*.md'),('Text','*.txt')])
        if path:Path(path).write_text(self.content,encoding='utf-8')
