"""Foreground reading intervals and factual daily recaps; no network or AI."""
from datetime import datetime,timedelta
import time
import re
from library_core import Library


class ReadingClock:
    def __init__(self,directory):
        self.directory=directory;self.previous=None;self.pending=[];self.last_flush=time.monotonic()

    def tick(self,rid,active,wall=None,mono=None):
        wall=time.time() if wall is None else wall;mono=time.monotonic() if mono is None else mono
        if self.previous:
            old_id,old_active,old_wall,old_mono=self.previous;elapsed=mono-old_mono
            # Large gaps include sleep, suspend or a stalled UI: never infer reading time.
            if active and old_active and rid==old_id and 0<elapsed<=3 and abs((wall-old_wall)-elapsed)<.5:
                start=wall-elapsed
                if self.pending and self.pending[-1][0]==rid and abs(self.pending[-1][2]-start)<.1:self.pending[-1][2]=wall
                else:self.pending.append([rid,start,wall])
        self.previous=(rid,active,wall,mono)
        if mono-self.last_flush>=15:self.flush();self.last_flush=mono

    def stop(self):self.previous=None;self.flush()

    def flush(self):
        if not self.pending:return
        lib=Library(self.directory())
        try:
            with lib.db:lib.db.executemany('INSERT INTO reading_sessions(paper,start,end) VALUES(?,?,?)',self.pending)
            self.pending=[]
        finally:lib.close()


def foreground_reader(app):
    if app.current_page!='reader' or not app.reader_page or not app.reader_page.rid or app.reader_page.loading:return False
    if not getattr(app.reader_page,'path',None) or getattr(app.reader_page,'count',0)<=0:return False
    if app.root.state() not in ('normal','zoomed'):return False
    import os
    if os.name!='nt':return app.root.focus_displayof() is not None
    import ctypes
    from ctypes import wintypes
    user=ctypes.windll.user32
    user.GetForegroundWindow.restype=wintypes.HWND
    user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user.GetAncestor.restype=wintypes.HWND
    return bool(user.GetForegroundWindow()==user.GetAncestor(app.root.winfo_id(),2))


def content_excerpt(record):
    if record.get('abstract'):return record['abstract'][:900]
    text=record.get('text','')
    found=re.search(r'(?is)\babstract\b\s*[:：]?(.{50,2200}?)(?:\bkeywords\b|\bintroduction\b|\bbackground\b|$)',text)
    return re.sub(r'\s+',' ',found.group(1)).strip()[:900] if found else '这篇文献还没有摘要。阅读时记下的想法也会出现在这里。'


def daily_recap(library,day):
    return reading_recap(library,day,day)


def reading_recap(library,first_day,last_day=None,project=None):
    last_day=last_day or first_day
    if last_day<first_day:raise ValueError('结束日期不能早于开始日期。')
    start=datetime.combine(first_day,datetime.min.time()).astimezone();end=datetime.combine(last_day+timedelta(days=1),datetime.min.time()).astimezone()
    totals={}
    for row in library.db.execute('SELECT paper,start,end FROM reading_sessions WHERE start<? AND end>?',(end.timestamp(),start.timestamp())):
        seconds=max(0,min(row['end'],end.timestamp())-max(row['start'],start.timestamp()))
        totals[row['paper']]=totals.get(row['paper'],0)+seconds
    papers=[]
    for rid,seconds in sorted(totals.items(),key=lambda item:-item[1]):
        if seconds<=0:continue
        try:record=library.get(rid)
        except ValueError:continue
        if project and project not in record['projects']:continue
        papers.append({'id':rid,'title':record['title'],'doi':record['doi'],'seconds':seconds,'content':content_excerpt(record),
                       'abstract':record.get('abstract',''),'keywords':record.get('keywords',''),
                       'notes':record.get('notes',''),'annotations':record.get('annotations',[]),'attachments':record.get('attachments',[])})
    from research_topics import topic_overview
    topics=topic_overview(papers)
    return {'date':first_day.isoformat(),'end_date':last_day.isoformat(),'count':len(papers),
            'seconds':sum(p['seconds'] for p in papers),'papers':papers,'topics':topics,
            'notes_count':sum(bool(p['notes'].strip())+len(p['annotations']) for p in papers)}


def duration(seconds):
    seconds=int(seconds);hours,seconds=divmod(seconds,3600);minutes,seconds=divmod(seconds,60)
    return (f'{hours} 小时 ' if hours else '')+f'{minutes} 分 {seconds} 秒'


def recap_text(data):
    period=data['date'] if data.get('end_date',data['date'])==data['date'] else data['date']+' — '+data['end_date']
    lines=[f"{period} 阅读总结",recap_intro(data),'']
    keywords=[k['term'] for k in data.get('topics',{}).get('keywords',[])[:8]]
    if keywords:lines.extend(['阅读关键词：'+' · '.join(keywords),''])
    for i,p in enumerate(data['papers'],1):
        lines.extend([f"{i}. {p['title']}",f"阅读时间：{duration(p['seconds'])}",f"DOI：{p['doi'] or '待补充'}",'文献摘要：'+p['content'],''])
        if p['notes']:lines.extend(['我的笔记：',p['notes'][:4000],''])
        for a in p['annotations'][:12]:lines.extend([f"第 {a['page']+1} 页摘录 / 批注：",a.get('quote',''),a.get('text',''),''])
    if not data['papers']:lines.append('这段时间还没有阅读记录。打开一篇文献，下一次回顾就从这里开始。')
    return '\n'.join(lines)


def recap_intro(data):
    if not data['count']:return '留一点时间，读一篇想读的文献。'
    intro=f"这段时间，你阅读了 {data['count']} 篇文献，累计 {duration(data['seconds'])}。"
    if data.get('notes_count'):intro+=f"这些文献已有 {data['notes_count']} 份笔记与标记，可以一起回顾。"
    return intro
