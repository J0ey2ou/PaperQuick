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
    return re.sub(r'\s+',' ',found.group(1)).strip()[:900] if found else '尚无可用摘要；可补充文献信息或记录阅读笔记。'


def daily_recap(library,day):
    start=datetime.combine(day,datetime.min.time()).astimezone();end=datetime.combine(day+timedelta(days=1),datetime.min.time()).astimezone()
    totals={}
    for row in library.db.execute('SELECT paper,start,end FROM reading_sessions WHERE start<? AND end>?',(end.timestamp(),start.timestamp())):
        seconds=max(0,min(row['end'],end.timestamp())-max(row['start'],start.timestamp()))
        totals[row['paper']]=totals.get(row['paper'],0)+seconds
    papers=[]
    for rid,seconds in sorted(totals.items(),key=lambda item:-item[1]):
        if seconds<=0:continue
        try:record=library.get(rid)
        except ValueError:continue
        papers.append({'id':rid,'title':record['title'],'doi':record['doi'],'seconds':seconds,'content':content_excerpt(record),
                       'notes':record.get('notes',''),'annotations':record.get('annotations',[])})
    return {'date':day.isoformat(),'count':len(papers),'seconds':sum(p['seconds'] for p in papers),'papers':papers}


def duration(seconds):
    seconds=int(seconds);hours,seconds=divmod(seconds,3600);minutes,seconds=divmod(seconds,60)
    return (f'{hours} 小时 ' if hours else '')+f'{minutes} 分 {seconds} 秒'


def recap_text(data):
    lines=[f"{data['date']} 阅读总结",f"阅读 {data['count']} 篇 · 前台阅读 {duration(data['seconds'])}",'',
           '仅统计阅读页作为前台主窗口的停留时间；切换页面、其他软件、托盘、休眠间隔不计入。',
           '内容来自当前本地摘要、笔记与批注，未调用 AI。升级前未记录的阅读时间不追溯。','']
    for i,p in enumerate(data['papers'],1):
        lines.extend([f"{i}. {p['title']}",f"阅读时间：{duration(p['seconds'])}",f"DOI：{p['doi'] or '待补充'}",'摘要 / 内容：'+p['content'],''])
        if p['notes']:lines.extend(['当前笔记：',p['notes'][:4000],''])
        for a in p['annotations'][:12]:lines.extend([f"第 {a['page']+1} 页摘录 / 批注：",a.get('quote',''),a.get('text',''),''])
    if not data['papers']:lines.append('这一天没有已记录的前台阅读。开始阅读后，这里会自动汇总。')
    return '\n'.join(lines)
