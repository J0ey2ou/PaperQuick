"""Native graph page sharing the desktop window; all calculations are local."""
import math
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk,messagebox,colorchooser
from library_core import Library
from graph_view import write_graph
from ui_theme import BG,PANEL,SURFACE,FG,MUTED,ACCENT,LINE,FONT,style_dialog
from graph_style import DEFAULT,validate_style,score,appearance
from graph_layout import subset,force_layout

class GraphPage:
    def __init__(self,parent,directory):
        self.directory=directory;self.frame=tk.Frame(parent,bg=BG)
        lib=Library(directory)
        try:self.highlight=validate_style(lib.setting('graph_style',DEFAULT))
        finally:lib.close()
        self.events=queue.Queue();self.busy=False;self.data=None;self.records={};self.selected=None;self.drag=None;self.zoom=1
        self.pan=[0.,0.];self.focus=None;self.layout_key=None;self.position_key=None;self.layout_running=False;self.layout_events=queue.Queue();self.draw_job=None;self.closed=False
        header=ttk.Frame(self.frame,padding=(24,16));header.pack(fill='x')
        title=ttk.Frame(header);title.pack(side='left')
        ttk.Label(title,text='文献图谱',font=(FONT,21,'bold')).pack(anchor='w')
        ttk.Label(title,text='KNOWLEDGE NETWORK  /  LOCAL INSIGHTS',foreground=ACCENT,font=('Segoe UI Variable Text',9)).pack(anchor='w',pady=(4,0))
        ttk.Button(header,text='导出离线网页',command=self.export).pack(side='right')
        ttk.Button(header,text='刷新图谱',command=self.refresh).pack(side='right',padx=8)
        stats=ttk.Frame(self.frame,padding=(24,0,24,16));stats.pack(fill='x');self.metrics=[]
        for i,label in enumerate(('收藏文献','已归档 PDF','已读文献','未入库候选')):
            stats.columnconfigure(i,weight=1);card=ttk.Frame(stats,style='Card.TFrame',padding=(18,12));card.grid(row=0,column=i,sticky='nsew',padx=(0,12 if i<3 else 0))
            value=tk.StringVar(value='—');self.metrics.append(value)
            ttk.Label(card,text=label,style='CardMuted.TLabel').pack(anchor='w')
            ttk.Label(card,textvariable=value,style='Number.TLabel').pack(anchor='w')
        toolbar=ttk.Frame(self.frame,padding=(24,0,24,12));toolbar.pack(fill='x')
        self.mode='overview';self.buttons={}
        for key,label in (('overview','收藏概览'),('network','文献关系')):
            button=ttk.Button(toolbar,text=label,style='Accent.TButton' if key=='overview' else 'TButton',command=lambda k=key:self.switch(k));button.pack(side='left',padx=(0,8));self.buttons[key]=button
        self.project=tk.StringVar(value='所有课题');self.project_combo=ttk.Combobox(toolbar,textvariable=self.project,values=['所有课题'],state='readonly',width=22);self.project_combo.pack(side='left',padx=8);self.project_combo.bind('<<ComboboxSelected>>',lambda _:self.draw())
        self.search=tk.StringVar();ttk.Entry(toolbar,textvariable=self.search,width=27).pack(side='left',fill='x',expand=True,padx=8);self.search.trace_add('write',lambda *_:self.draw())
        ttk.Label(toolbar,text='搜索标题 / DOI',style='Muted.TLabel').pack(side='left')
        highlights=ttk.Frame(self.frame,padding=(24,0,24,12));highlights.pack(fill='x')
        ttk.Label(highlights,text='节点高亮',style='Muted.TLabel').pack(side='left',padx=(0,10))
        self.highlight_modes={'是否下载':'downloaded','阅读次数':'read_count','本地被引用次数':'citation_count','自定义权重':'custom'}
        self.highlight_mode=tk.StringVar(value=next(k for k,v in self.highlight_modes.items() if v==self.highlight['mode']))
        combo=ttk.Combobox(highlights,textvariable=self.highlight_mode,values=list(self.highlight_modes),state='readonly',width=20);combo.pack(side='left');combo.bind('<<ComboboxSelected>>',self.change_highlight)
        ttk.Button(highlights,text='自定义颜色 / 权重',command=self.custom_highlight).pack(side='left',padx=10)
        self.show_candidates=tk.BooleanVar(value=True);ttk.Checkbutton(highlights,text='显示未入库候选（虚线）',variable=self.show_candidates,command=self.draw).pack(side='left',padx=8)
        explore=ttk.Frame(self.frame,padding=(24,0,24,10));explore.pack(fill='x')
        ttk.Label(explore,text='显示数量',style='Muted.TLabel').pack(side='left')
        self.limit=tk.DoubleVar(value=80);self.limit_label=tk.StringVar(value='80 篇')
        self.limit_slider=ttk.Scale(explore,from_=1,to=800,variable=self.limit,command=self.schedule_draw);self.limit_slider.pack(side='left',fill='x',expand=True,padx=12)
        ttk.Label(explore,textvariable=self.limit_label,width=20).pack(side='left')
        for label,command in [('聚焦关联',self.focus_selected),('返回全图',self.reset),('适应窗口',self.fit_view)]:ttk.Button(explore,text=label,command=command).pack(side='left',padx=4)
        content=ttk.Frame(self.frame,padding=(24,0));content.pack(fill='both',expand=True)
        side=ttk.Frame(content,style='Card.TFrame',padding=18,width=290);side.pack(side='right',fill='y',padx=(14,0));side.pack_propagate(False)
        ttk.Label(side,text='研究关系',style='Card.TLabel',font=(FONT,12,'bold')).pack(anchor='w',pady=(0,12))
        self.similarity=tk.BooleanVar(value=True);self.citation=tk.BooleanVar(value=True)
        for title,var in [('内容相似',self.similarity),('本地引用证据',self.citation)]:ttk.Checkbutton(side,text=title,variable=var,command=self.draw).pack(anchor='w',pady=3)
        ttk.Label(side,text='相似：标题、摘要、关键词\n引用：本地 PDF 参考文献 DOI',style='CardMuted.TLabel',justify='left').pack(anchor='w',pady=(12,20))
        self.info=tk.StringVar(value='点击节点查看详情；双击节点聚焦关联。\n\n拖动空白处平移，滚轮以鼠标为中心缩放。按住 Shift 框选区域放大。\n\n滑条控制显示数量，优先展示库内文献与连接较多的节点。')
        information=tk.Text(side,height=4,wrap='word',bg=PANEL,fg=MUTED,relief='flat',font=(FONT,10),state='disabled')
        information.pack(fill='both',expand=True)
        def update_info(*_):
            information.configure(state='normal');information.delete('1.0','end');information.insert('1.0',self.info.get());information.configure(state='disabled')
        self.info.trace_add('write',update_info);update_info()
        ttk.Button(side,text='打开选中文献 PDF',command=self.open_pdf).pack(fill='x',pady=8)
        ttk.Button(side,text='查找选中文献原文',command=self.query_selected).pack(fill='x',pady=(0,8))
        ttk.Button(side,text='将候选文献收藏到课题',command=self.collect_selected).pack(fill='x',pady=(0,8))
        ttk.Button(side,text='重置视图',command=self.reset).pack(fill='x')
        self.canvas=tk.Canvas(content,bg='#0b1627',highlightbackground=LINE,highlightthickness=1)
        self.canvas.pack(side='left',fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda _:self.draw());self.canvas.bind('<Button-1>',self.select);self.canvas.bind('<B1-Motion>',self.move);self.canvas.bind('<ButtonRelease-1>',self.release);self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Double-1>',self.double_click)
        self.status=tk.StringVar(value='完全离线 · 不调用 AI / API · 引用覆盖可能不完整')
        ttk.Label(self.frame,textvariable=self.status,style='Muted.TLabel',padding=(24,12)).pack(fill='x')
        self.positions={};self.frame.after(100,self.poll)

    def refresh(self):
        if self.busy:return
        self.busy=True;self.status.set('正在本地生成图谱…')
        def job():
            lib=None
            try:
                lib=Library(self.directory);self.events.put((lib.graph(),lib.records(),None))
            except Exception as exc:self.events.put((None,None,str(exc)))
            finally:
                if lib:lib.close()
        threading.Thread(target=job,daemon=True).start()

    def poll(self):
        if self.closed:return
        try:
            key,positions,error=self.layout_events.get_nowait();self.layout_running=False
            if key==self.layout_key:
                if error:self.status.set('布局未完成：'+error)
                else:self.positions=positions;self.position_key=key;self.fit_view()
            else:self.draw()
        except queue.Empty:pass
        try:
            data,records,error=self.events.get_nowait();self.busy=False
            if error:self.status.set(error)
            else:
                self.data=data;self.records={r['id']:r for r in records};self.positions={};self.layout_key=None
                self.project_combo.configure(values=['所有课题']+sorted({p for n in data['nodes'] for p in n['projects']}))
                self.status.set('完全离线 · 青色为内容相似，橙色箭头为本地引用证据 · PDF 提取范围有限，关系需核对')
                self.draw()
        except queue.Empty:pass
        if self.frame.winfo_exists():self.frame.after(1000 if self.frame.winfo_toplevel().state()=='withdrawn' and not self.busy and not self.layout_running else 120,self.poll)

    def switch(self,mode):
        self.mode=mode
        for key,button in self.buttons.items():button.configure(style='Accent.TButton' if mode==key else 'TButton')
        self.draw()

    def reset(self):self.focus=None;self.selected=None;self.layout_key=None;self.positions={};self.pan=[0.,0.];self.zoom=1;self.draw()

    def schedule_draw(self,_=None):
        self.limit_label.set(f'{int(self.limit.get())} 篇')
        if self.draw_job:self.frame.after_cancel(self.draw_job)
        self.draw_job=self.frame.after(140,self.apply_limit)

    def apply_limit(self):self.draw_job=None;self.draw()

    def focus_selected(self):
        if self.selected:self.focus=self.selected;self.mode='network';self.switch('network')

    def fit_view(self):
        if self.positions:
            xs,ys=zip(*self.positions.values());cx=(min(xs)+max(xs))/2;cy=(min(ys)+max(ys))/2
            self.zoom=min(3,max(.08,min((self.canvas.winfo_width()-100)/max(100,max(xs)-min(xs)),(self.canvas.winfo_height()-100)/max(100,max(ys)-min(ys)))))
            self.pan=[-cx*self.zoom,-cy*self.zoom]
        self.draw()

    def position(self,rid):
        x,y=self.positions[rid];return self.canvas.winfo_width()/2+x*self.zoom+self.pan[0],self.canvas.winfo_height()/2+y*self.zoom+self.pan[1]

    def world(self,x,y):return ((x-self.canvas.winfo_width()/2-self.pan[0])/self.zoom,(y-self.canvas.winfo_height()/2-self.pan[1])/self.zoom)

    def filtered(self):
        if not self.data:return []
        term=self.search.get().strip().lower();project=self.project.get()
        return [n for n in self.data['nodes'] if (self.show_candidates.get() or n.get('in_library',True)) and (project=='所有课题' or project in n['projects']) and term in (n['title']+' '+n['doi']).lower()]

    def draw(self):
        self.canvas.delete('all');width=self.canvas.winfo_width();height=self.canvas.winfo_height()
        if width<50 or height<50:return
        for x in range(0,width,34):self.canvas.create_line(x,0,x,height,fill='#142941')
        for y in range(0,height,34):self.canvas.create_line(0,y,width,y,fill='#142941')
        nodes=self.filtered();ids={n['id'] for n in nodes}
        edges=[] if not self.data else [e for e in self.data['edges'] if e['source'] in ids and e['target'] in ids and (self.similarity.get() if e['kind']=='similarity' else self.citation.get() if e['kind']=='citation' else self.show_candidates.get())]
        for value,count in zip(self.metrics,(sum(n.get('in_library',True) for n in nodes),sum(n['pdf'] for n in nodes),sum(n['status']=='已读' for n in nodes),sum(not n.get('in_library',True) for n in nodes))):value.set(str(count))
        if not nodes:self.canvas.create_text(width/2,height/2,text='正在生成图谱…' if self.busy else '暂无匹配文献',fill=MUTED,font=(FONT,13));return
        if self.mode=='overview':
            nodes=[n for n in nodes if n.get('in_library',True)]
            projects=sorted({p for n in nodes for p in n['projects']});self.canvas.create_text(26,28,text='课题收藏分布',anchor='w',fill=FG,font=(FONT,15,'bold'))
            for i,p in enumerate(projects[:max(1,(height-85)//56)]):
                y=82+i*56;count=sum(p in n['projects'] for n in nodes);self.canvas.create_text(26,y,text=p[:20],anchor='w',fill=FG,font=(FONT,11))
                start=min(240,width*.4);end=width-85;self.canvas.create_rectangle(start,y-12,end,y+12,fill='#1c3047',outline='',tags=('project',p));self.canvas.create_rectangle(start,y-12,start+(end-start)*count/max(1,len(nodes)),y+12,fill=ACCENT,outline='',tags=('project',p));self.canvas.create_text(width-35,y,text=str(count),fill=FG,font=('Segoe UI Variable Text',12),tags=('project',p))
            return
        total=len(nodes);self.limit_slider.configure(to=max(1,total))
        if self.focus not in ids:self.focus=None
        nodes,edges=subset(nodes,edges,self.limit.get(),self.focus);ids={n['id'] for n in nodes}
        self.limit_label.set(f'{len(nodes)} / {total} 篇'+(' · 局部' if self.focus else ''))
        self.visible_nodes=nodes
        key=(tuple(n['id'] for n in nodes),tuple((e['source'],e['target'],e['kind']) for e in edges))
        if key!=self.position_key or set(self.positions)!=ids:
            self.layout_key=key
            if not self.layout_running:
                self.layout_running=True
                def layout():
                    try:self.layout_events.put((key,force_layout(nodes,edges),None))
                    except Exception as exc:self.layout_events.put((key,{},str(exc)))
                threading.Thread(target=layout,daemon=True).start()
            self.canvas.create_text(width/2,height/2,text='正在按文献关系排布…',fill=MUTED,font=(FONT,13));return
        neighbors={self.selected}
        for e in edges:
            if self.selected in (e['source'],e['target']):neighbors.update((e['source'],e['target']))
        for e in edges:
            active=self.selected in (e['source'],e['target'])
            if self.selected and not active:continue
            x1,y1=self.position(e['source']);x2,y2=self.position(e['target'])
            self.canvas.create_line(x1,y1,x2,y2,fill=self.highlight['candidate'] if e['kind']=='candidate' else '#e5a15a' if e['kind']=='citation' else '#397589' if active else '#203e50',width=2 if active else 1,arrow='last' if e['kind']=='citation' else 'none',dash=(4,5) if e['kind']=='candidate' else ())
        maximum=max((score(n,self.highlight) for n in nodes if n.get('in_library',True)),default=1)
        label_boxes=[]
        for n in sorted(nodes,key=lambda n:n['id']!=self.selected):
            x,y=self.position(n['id']);color,r=appearance(n,self.highlight,maximum);r=9 if n['id']==self.selected else max(5,r);tags=('node',n['id'])
            if self.selected and n['id'] not in neighbors:color='#324057'
            if n['id']==self.selected:self.canvas.create_oval(x-15,y-15,x+15,y+15,outline=ACCENT,width=1)
            self.canvas.create_oval(x-r,y-r,x+r,y+r,fill=color if n.get('in_library',True) else '#0b1627',outline='' if n.get('in_library',True) else color,width=1.5,tags=tags)
            if len(nodes)<22 or (self.selected and n['id'] in neighbors) or (self.zoom>1.7 and len(nodes)<90):
                label=self.canvas.create_text(x+13 if x<width-230 else x-13,y,text=n['title'][:34],anchor='w' if x<width-230 else 'e',fill=FG if n['id']==self.selected else MUTED,font=(FONT,9),tags=tags)
                box=self.canvas.bbox(label)
                overlaps=any(box[0]<b[2]+5 and box[2]>b[0]-5 and box[1]<b[3]+4 and box[3]>b[1]-4 for b in label_boxes)
                if overlaps:self.canvas.delete(label)
                else:label_boxes.append(box)

    def select(self,event):
        if self.mode!='network':
            for item in self.canvas.find_overlapping(event.x-2,event.y-2,event.x+2,event.y+2):
                tags=self.canvas.gettags(item)
                if tags and tags[0]=='project':self.project.set(tags[1]);self.switch('network');return
            return
        self.drag_start=(event.x,event.y);self.pan_start=list(self.pan)
        if event.state & 1:self.drag='region';return
        items=self.canvas.find_overlapping(event.x-8,event.y-8,event.x+8,event.y+8)
        for item in reversed(items):
            tags=self.canvas.gettags(item)
            if tags and tags[0]=='node':
                self.selected=tags[1];self.drag=tags[1];n=self.selected_node()
                if not n.get('in_library',True):self.info.set('未入库候选 · 关系待核对\n\n'+n['title']+'\n\n'+n.get('evidence','')+'\n'+n.get('raw','')[:260])
                else:
                    r=self.records[self.selected]
                    self.info.set(r['title']+'\n\n'+r['year']+' · '+r['status']+f"\n阅读 {n.get('read_count',0)} 次 · 本地被引用 {n.get('citation_count',0)} 次"+'\n\nDOI: '+(r['doi'] or '待补充')+'\n\n'+r['abstract'][:120])
                self.draw();return
        self.selected=None;self.drag='pan';self.draw()

    def move(self,event):
        if not self.drag:return
        if self.drag=='region':
            self.canvas.delete('region');self.canvas.create_rectangle(*self.drag_start,event.x,event.y,outline=ACCENT,dash=(5,3),width=2,tags='region');return
        if self.drag=='pan':self.pan=[self.pan_start[0]+event.x-self.drag_start[0],self.pan_start[1]+event.y-self.drag_start[1]]
        else:self.positions[self.drag]=self.world(event.x,event.y)
        self.draw()

    def release(self,event):
        if self.drag=='region':
            x,y=self.drag_start;w=abs(event.x-x);h=abs(event.y-y)
            if min(w,h)>15:
                cx,cy=self.world((event.x+x)/2,(event.y+y)/2)
                self.zoom=min(8,self.zoom*min(self.canvas.winfo_width()/w,self.canvas.winfo_height()/h)*.85);self.pan=[-cx*self.zoom,-cy*self.zoom]
        self.drag=None;self.draw()

    def double_click(self,event):
        if self.selected:self.focus_selected()
        else:self.zoom_at(event.x,event.y,1.8)

    def zoom_at(self,x,y,factor):
        wx,wy=self.world(x,y);self.zoom=max(.08,min(8,self.zoom*factor))
        self.pan=[x-self.canvas.winfo_width()/2-wx*self.zoom,y-self.canvas.winfo_height()/2-wy*self.zoom];self.draw()

    def wheel(self,event):
        if self.mode=='network':self.zoom_at(event.x,event.y,1.15 if event.delta>0 else 1/1.15)
        return 'break'

    def open_pdf(self):
        if not self.selected:self.info.set('先在文献关系图中选中一个节点。');return
        if self.selected not in self.records:self.info.set('这篇候选文献尚未入库。可以先查找原文，再下载归档。');return
        attachments=self.records[self.selected]['attachments']
        if not attachments:self.info.set('此文献尚未添加 PDF。请到“文献分类”关联已下载文件。');return
        if getattr(self,'on_reader',None):self.on_reader(self.selected);return
        try:os.startfile(self.directory/attachments[0]['path'])
        except OSError as exc:self.status.set(str(exc))

    def export(self):
        lib=Library(self.directory)
        try:path=write_graph(lib)
        finally:lib.close()
        import webbrowser
        webbrowser.open(path.as_uri());self.status.set('已导出并打开离线网页：'+str(path))

    def close(self):self.closed=True

    def selected_node(self):return next((n for n in (self.data or {}).get('nodes',[]) if n['id']==self.selected),None)

    def query_selected(self):
        n=self.selected_node()
        if n and getattr(self,'on_query',None):self.on_query(n['doi'] or n['title'])
        else:self.info.set('请先选择一个文献节点。')

    def collect_selected(self):
        n=self.selected_node()
        if n and not n.get('in_library',True) and getattr(self,'on_collect',None):self.on_collect(n)
        else:self.info.set('请选择一个尚未入库的候选节点。')

    def change_highlight(self,_=None):
        self.highlight['mode']=self.highlight_modes[self.highlight_mode.get()];self.save_highlight();self.draw()

    def save_highlight(self):
        lib=Library(self.directory)
        try:lib.set_setting('graph_style',self.highlight)
        finally:lib.close()

    def custom_highlight(self):
        dialog=tk.Toplevel(self.frame);style_dialog(dialog);dialog.title('自定义图谱高亮');panel=ttk.Frame(dialog,padding=22);panel.pack(fill='both')
        ttk.Label(panel,text='颜色与权重',font=(FONT,15,'bold')).pack(anchor='w')
        ttk.Label(panel,text='阅读次数按每次打开 PDF 计数；引用次数仅统计本地引用证据。\n自定义权重模式将三项分数组合，并调整颜色与节点大小。',style='Muted.TLabel').pack(anchor='w',pady=12)
        values={}
        for key,label in [('low','低值颜色'),('high','高值颜色'),('candidate','候选颜色'),('read_weight','阅读权重'),('citation_weight','引用权重'),('download_weight','下载权重')]:
            row=ttk.Frame(panel);row.pack(fill='x',pady=5);ttk.Label(row,text=label,width=12).pack(side='left');v=tk.StringVar(value=str(self.highlight[key]));values[key]=v;ttk.Entry(row,textvariable=v,width=24).pack(side='left')
            if key in ('low','high','candidate'):
                def choose(variable=v):
                    color=colorchooser.askcolor(variable.get(),parent=dialog)[1]
                    if color:variable.set(color)
                ttk.Button(row,text='选色',command=choose).pack(side='left',padx=8)
        def save():
            try:self.highlight=validate_style(dict(self.highlight,**{k:v.get() for k,v in values.items()}))
            except ValueError as exc:messagebox.showerror('设置无效',str(exc),parent=dialog);return
            self.highlight['mode']='custom';self.highlight_mode.set('自定义权重');self.save_highlight();self.draw();dialog.destroy()
        ttk.Button(panel,text='保存并应用',style='Accent.TButton',command=save).pack(anchor='e',pady=(15,0))
