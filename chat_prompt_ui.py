"""Editable whole-paper prompts; only an explicit button opens the web handoff."""
import tkinter as tk
from tkinter import ttk
import webbrowser
from library_core import Library
from ui_theme import style_dialog, FONT

DEFAULT_CHAT_PROMPT = '''请阅读上传的《{标题}》，用中文逐步解读这篇文章：
1. 用一段话概括研究问题、主要发现和文章价值。
2. 说明研究背景、核心假设与创新点。
3. 解释研究设计、数据或样本、关键方法及其适用条件。
4. 梳理主要结果和图表，区分作者的结论与推测。
5. 分析局限、潜在偏差以及结论适用的范围。
6. 给出继续精读的顺序和需要重点关注的问题。
请尽量标注对应页码或章节；文中未报告或无法确认的信息请明确说明，不要补写事实。'''


def render_chat_prompt(template, record):
    text = str(template).strip()
    if not text or len(text) > 100000:
        raise ValueError('解读模板请填写 1–100000 字。')
    return text.replace('{标题}', record.get('title') or '本文').replace('{作者}', record.get('authors') or '').replace('{年份}', record.get('year') or '')


class ChatPromptDialog:
    def __init__(self, parent, directory, rid=None, bridge=None, on_prepared=None):
        self.directory=directory;self.rid=rid;self.bridge=bridge;self.on_prepared=on_prepared
        lib=Library(directory)
        try:self.record=lib.get(rid) if rid else {};template=lib.setting('chat_full_paper_prompt',DEFAULT_CHAT_PROMPT)
        finally:lib.close()
        self.win=tk.Toplevel(parent);self.win.title('ChatGPT 通篇解读模板');self.win.geometry('760x600');style_dialog(self.win)
        footer=ttk.Frame(self.win,padding=16);footer.pack(side='bottom',fill='x')
        self.status=tk.StringVar(value='模板会填入 ChatGPT 输入框；文献上传完成后，由你核对并点击发送。')
        ttk.Label(footer,textvariable=self.status,wraplength=700,style='Muted.TLabel').pack(fill='x')
        bar=ttk.Frame(footer);bar.pack(fill='x',pady=(10,0))
        ttk.Button(bar,text='恢复默认模板',command=lambda:self.replace(DEFAULT_CHAT_PROMPT)).pack(side='left')
        ttk.Button(bar,text='保存为默认模板',command=self.save).pack(side='left',padx=8)
        if rid:ttk.Button(bar,text='上传文献并打开 ChatGPT',command=self.open_chat,style='Accent.TButton').pack(side='right')
        ttk.Label(self.win,text=('文献：'+self.record['title']) if rid else '设置以后通篇解读使用的默认问题',padding=16,wraplength=700).pack(fill='x')
        ttk.Label(self.win,text='支持 {标题}、{作者}、{年份}；可以直接修改下面的内容。',padding=(16,0,16,10),style='Muted.TLabel').pack(fill='x')
        body=ttk.Frame(self.win,padding=(16,0));body.pack(fill='both',expand=True)
        self.text=tk.Text(body,wrap='word',font=(FONT,11),undo=True);scroll=ttk.Scrollbar(body,command=self.text.yview);scroll.pack(side='right',fill='y');self.text.configure(yscrollcommand=scroll.set);self.text.pack(fill='both',expand=True);self.replace(template)

    def replace(self, text):self.text.delete('1.0','end');self.text.insert('1.0',text)

    def save(self):
        try:
            template=self.text.get('1.0','end-1c').strip();render_chat_prompt(template,self.record)
            lib=Library(self.directory)
            try:lib.set_setting('chat_full_paper_prompt',template)
            finally:lib.close()
            self.status.set('默认模板已保存。');return template
        except (ValueError,OSError) as exc:self.status.set(str(exc));return None

    def open_chat(self):
        template=self.save()
        if template is None:return
        try:
            url=self.bridge.prepare(self.rid,quote=render_chat_prompt(template,self.record),whole_document=True)
            if not webbrowser.open(self.bridge.open_url(url)):raise ValueError('默认浏览器未能打开，请检查浏览器设置。')
            if self.on_prepared:self.on_prepared(url)
            self.status.set('已打开本机连接页，扩展会上传正文并填入解读问题。请保持软件运行。')
        except (ValueError,OSError) as exc:self.status.set('未能准备解读：'+str(exc))
