"""Virtual continuous pages with a real PDF text-selection layer."""
import bisect
import threading
from PIL import ImageTk
from pdf_reader_core import render_page_data,math_sqrt_limit


class DocumentCanvas:
    def __init__(self,reader):
        self.r=reader;self.canvas=reader.canvas;self.cache={};self.photos={};self.pending=set();self.layout={};self.tops=[];self.sign=None;self.job=None;self.selection=None
        self.canvas.bind('<Control-c>',lambda e:self.copy());self.canvas.bind('<Control-C>',lambda e:self.copy())
        self.canvas.bind('<Button-2>',lambda e:self.canvas.scan_mark(e.x,e.y));self.canvas.bind('<B2-Motion>',lambda e:self.canvas.scan_dragto(e.x,e.y,gain=1))

    def reset(self):
        if self.job:
            try:self.canvas.after_cancel(self.job)
            except Exception:pass
        self.job=None;self.cache={};self.photos={};self.pending=set();self.layout={};self.tops=[];self.sign=None;self.selection=None;self.canvas.delete('all')

    def adopt(self,path,page,count,image,chars,sizes):
        sign=(str(path),self.r.scale,self.r.generation,self.r.continuous.get())
        changed=sign!=self.sign;self.sign=sign
        if changed:
            self.cache={};self.photos={};self.pending=set();self.selection=None;self.layout={};self.tops=[];self.canvas.delete('all')
            y=18
            pages=range(count) if self.r.continuous.get() else [page]
            for n in pages:
                w,h=sizes[n];scale=min(self.r.scale,math_sqrt_limit(w,h));w,h=round(w*scale),round(h*scale)
                self.layout[n]=(18,y,w,h);self.tops.append((y,n))
                self.canvas.create_rectangle(18,y,18+w,y+h,fill='#f7f8fa',outline='',tags=('page-background',))
                self.canvas.create_text(30,y+16,text=f'第 {n+1} 页',fill='#8090a0',anchor='nw')
                y+=h+24
            self.canvas.configure(scrollregion=(0,0,max(x+w for x,y,w,h in self.layout.values())+18,y))
        elif not self.r.continuous.get() and page not in self.layout:
            self.sign=None;return self.adopt(path,page,count,image,chars,sizes)
        self.receive(page,image,chars)
        if changed:self.goto(page)
        self.schedule()

    def receive(self,page,image,chars):
        if page not in self.layout:return
        self.pending.discard(page);self.cache[page]=(image,chars);self.photos[page]=ImageTk.PhotoImage(image,master=self.r.frame)
        self.canvas.delete('image-'+str(page));x,y,w,h=self.layout[page]
        self.canvas.create_image(x,y,image=self.photos[page],anchor='nw',tags=('page-image','image-'+str(page)))
        self.r.photo=self.photos.get(self.r.page,self.photos[page]);self.r.draw_annotations()
        if self.selection:self.paint_selection()

    def schedule(self):
        if self.job:
            try:self.canvas.after_cancel(self.job)
            except Exception:pass
        self.job=self.canvas.after(65,self.load_visible)

    def load_visible(self):
        self.job=None
        if self.r.closed or not self.layout:return
        top=self.canvas.canvasy(0);bottom=self.canvas.canvasy(self.canvas.winfo_height());visible=[n for n,(x,y,w,h) in self.layout.items() if y+h>=top-160 and y<=bottom+160]
        current=self.page_at(30,top+80)
        if current is not None:
            self.r.page=current;self.r.page_input.set(str(current+1));self.r.image_size=self.layout[current][2:]
            self.r.page_label.set(f'第 {current+1} / {self.r.count} 页 · {round(self.r.scale*100)}%'+(' · 连续阅读' if self.r.continuous.get() else ''))
        for n in visible:
            if n in self.cache or n in self.pending:continue
            self.pending.add(n);path=self.r.path;scale=self.r.scale;sign=self.sign;generation=self.r.generation
            def job(page=n):
                try:self.r.events.put(('canvas-page',generation,(sign,page,render_page_data(path,page,scale),None)))
                except Exception as exc:self.r.events.put(('canvas-page',generation,(sign,page,None,str(exc))))
            threading.Thread(target=job,daemon=True).start()
        # Keep only visible pages and nearby pages; a long thesis stays bounded.
        keep=set(visible)|{self.r.page}
        for n in list(self.cache):
            if n not in keep:
                self.canvas.delete('image-'+str(n));self.cache.pop(n,None);self.photos.pop(n,None)

    def scrolled(self,*args):
        self.r.vertical_scroll.set(*args);self.schedule()

    def page_at(self,x,y):
        if not self.tops:return None
        index=max(0,bisect.bisect_right([t[0] for t in self.tops],y)-1);return self.tops[index][1]

    def context(self,event):
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y);n=self.page_at(x,y)
        if n is None:return None
        left,top,w,h=self.layout[n]
        return n,[max(0,min(1,(x-left)/w)),max(0,min(1,(y-top)/h))]

    def coords(self,page,rect):
        x,y,w,h=self.layout[page];return x+rect[0]*w,y+rect[1]*h,x+rect[2]*w,y+rect[3]*h

    def goto(self,page):
        if page not in self.layout:return False
        self.r.page=page;x,y,w,h=self.layout[page]
        region=self.canvas.cget('scrollregion').split();height=float(region[3]);self.canvas.yview_moveto(max(0,(y-18)/height));self.schedule();return True

    def nearest(self,event):
        context=self.context(event)
        if not context:return None
        page,(x,y)=context
        if page not in self.cache:return None
        chars=self.cache[page][1];visible=[(j,c) for j,c in enumerate(chars) if c['rect'][2]>c['rect'][0] and c['text'].strip()]
        if not visible:return None
        w,h=self.layout[page][2:]
        def distance(item):
            a,b,c,d=item[1]['rect'];return (max(a-x,0,x-c)*w)**2+(max(b-y,0,y-d)*h)**2*2
        index,char=min(visible,key=distance)
        return page,index

    def begin(self,event):
        self.canvas.focus_set();point=self.nearest(event)
        if point:self.selection=(point,point);self.paint_selection()
        else:self.selection=None;self.canvas.delete('selection');self.r.status.set('这一页尚无可选文字；扫描页可使用截图或框选批注。')

    def move(self,event):
        if not self.selection:return
        point=self.nearest(event)
        if point:self.selection=(self.selection[0],point);self.paint_selection()

    def selected(self):
        if not self.selection:return []
        (a,ia),(b,ib)=sorted(self.selection);result=[]
        for n in range(a,b+1):
            if n not in self.cache:continue
            chars=self.cache[n][1];result.append((n,chars[ia if n==a else 0:ib+1 if n==b else len(chars)]))
        return result

    def paint_selection(self):
        self.canvas.delete('selection')
        for page,chars in self.selected():
            boxes=[]
            for c in chars:
                rect=c['rect']
                if not c['text'].strip() or rect[2]<=rect[0]:continue
                if boxes and abs(rect[1]-boxes[-1][1])<.007 and rect[0]-boxes[-1][2]<.025 and rect[0]>=boxes[-1][0]:boxes[-1][2]=max(rect[2],boxes[-1][2]);boxes[-1][3]=max(rect[3],boxes[-1][3])
                else:boxes.append(list(rect))
            for box in boxes:self.canvas.create_rectangle(*self.coords(page,box),fill='#74b9ff',stipple='gray50',outline='',tags='selection')

    def finish(self,event):
        self.move(event);groups=self.selected()
        if not groups:return
        quote='\n'.join(''.join(c['text'] for c in chars) for _,chars in groups).strip();page,chars=groups[0];boxes=[c['rect'] for c in chars if c['text'].strip()]
        if not boxes:return
        rect=[min(c[0] for c in boxes),min(c[1] for c in boxes),max(c[2] for c in boxes),max(c[3] for c in boxes)]
        self.r.last_selection={'page':page,'attachment':self.r.attachment_id,'rect':rect,'quote':quote,'kind':'选择文字'}
        self.r.status.set('文字已选中：Ctrl+C 复制，右键可记笔记、添加链接或关联文献。')

    def copy(self):
        groups=self.selected();quote='\n'.join(''.join(c['text'] for c in chars) for _,chars in groups).strip()
        if quote:self.canvas.clipboard_clear();self.canvas.clipboard_append(quote);self.r.status.set('选中文字已复制')
        return 'break'

    def screenshot(self,page,rect):
        if page not in self.cache:raise ValueError('这一页仍在准备，请稍后重试。')
        image=self.cache[page][0];w,h=image.size
        return image.crop((round(rect[0]*w),round(rect[1]*h),round(rect[2]*w),round(rect[3]*h)))
