"""Single-row reader tools with hover help and accessible overflow actions."""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk
import ui_theme as theme


def icon_image(name, color, size=20):
    image = Image.new('RGBA', (80, 80))
    draw = ImageDraw.Draw(image)
    def line(points): draw.line([(x*4,y*4) for x,y in points], fill=color, width=6, joint='curve')
    def box(bounds): draw.rectangle(tuple(x*4 for x in bounds), outline=color, width=5)
    if name in ('previous', 'next'):
        x = 12 if name == 'previous' else 8
        line([(x,4),(20-x,10),(x,16)])
    elif name in ('minus','plus','fit'):
        line([(4,10),(16,10)])
        if name=='plus': line([(10,4),(10,16)])
        if name=='fit': line([(3,5),(3,15)]);line([(17,5),(17,15)])
    elif name=='more':
        for x in (4,10,16): draw.ellipse((x*4-4,36,x*4+4,44), fill=color)
    elif name=='bookmark': line([(6,3),(14,3),(14,17),(10,13),(6,17),(6,3)])
    elif name=='save': box((3,3,17,17));box((6,3,13,8));box((6,12,14,17))
    elif name=='focus':
        for points in ([(7,3),(3,3),(3,7)],[(13,3),(17,3),(17,7)],[(3,13),(3,17),(7,17)],[(13,17),(17,17),(17,13)]):line(points)
    elif name=='select':line([(5,3),(5,16),(9,12),(13,17),(15,16),(11,11),(17,10),(5,3)])
    elif name=='hand':line([(4,11),(7,14),(7,5),(9,5),(9,11),(9,3),(11,3),(11,11),(11,5),(13,5),(13,11),(13,7),(15,7),(15,14),(12,18),(8,18),(3,13),(4,11)])
    elif name in ('edit','highlight'):line([(4,14),(13,4),(16,7),(7,17),(4,17),(4,14)]);line([(11,6),(14,9)])
    elif name=='comment':line([(3,4),(17,4),(17,14),(9,14),(5,18),(5,14),(3,14),(3,4)])
    elif name=='camera':box((2,6,18,17));box((6,3,13,6));draw.ellipse((28,32,52,56),outline=color,width=5)
    elif name=='compare':box((2,3,18,17));line([(10,3),(10,17)])
    elif name=='continuous':box((4,1,16,8));box((4,12,16,19))
    elif name=='notes':box((3,3,17,17));line([(6,7),(14,7)]);line([(6,10),(14,10)]);line([(6,13),(11,13)])
    elif name=='references':box((3,3,17,17));line([(7,3),(7,17)]);line([(10,7),(14,7)]);line([(10,11),(14,11)])
    elif name=='convert':line([(3,6),(16,6),(13,3)]);line([(17,14),(4,14),(7,17)])
    elif name=='image':box((2,3,18,17));line([(3,16),(8,10),(11,13),(14,8),(18,14)])
    elif name=='close':line([(5,5),(15,15)]);line([(15,5),(5,15)])
    elif name=='jump':line([(3,10),(15,10),(11,6)]);line([(15,10),(11,14)]);line([(18,4),(18,16)])
    elif name=='color':draw.ellipse((16,16,64,64),fill=color)
    elif name=='bold':line([(6,3),(6,17),(12,17),(15,14),(13,10),(6,10)]);line([(6,3),(12,3),(14,6),(12,10)])
    elif name=='italic':line([(9,3),(16,3)]);line([(4,17),(11,17)]);line([(13,3),(7,17)])
    else:box((4,2,16,18));line([(7,7),(13,7)]);line([(7,11),(13,11)])
    return image.resize((size,size), Image.Resampling.LANCZOS)


class HoverHelp:
    def __init__(self, widget, text):
        self.widget=widget;self.text=text;self.job=None;self.window=None
        widget.bind('<Enter>', self.enter, add='+')
        for event in ('<Leave>','<ButtonPress>','<Unmap>','<Destroy>'):widget.bind(event,self.hide,add='+')
    def enter(self, _=None):
        self.hide();self.job=self.widget.after(450,self.show)
    def show(self):
        self.job=None
        if not self.widget.winfo_exists() or not self.widget.winfo_viewable():return
        self.window=tk.Toplevel(self.widget);self.window.withdraw();self.window.overrideredirect(True)
        ttk.Label(self.window,text=self.text() if callable(self.text) else self.text,padding=(9,6)).pack()
        self.window.update_idletasks()
        x=min(self.widget.winfo_rootx(),self.window.winfo_screenwidth()-self.window.winfo_reqwidth()-8)
        y=min(self.widget.winfo_rooty()+self.widget.winfo_height()+4,self.window.winfo_screenheight()-self.window.winfo_reqheight()-8)
        self.window.geometry(f'+{max(0,x)}+{max(0,y)}');self.window.deiconify()
    def hide(self, _=None):
        if self.job:
            try:self.widget.after_cancel(self.job)
            except tk.TclError:pass
            self.job=None
        if self.window:
            try:self.window.destroy()
            except tk.TclError:pass
            self.window=None


class IconToolbar(ttk.Frame):
    def __init__(self,parent,**kwargs):
        super().__init__(parent,height=40,**kwargs)
        self.items=[];self.hidden=[];self.cell=32;self._theme_key=None
        self.pack_propagate(False)
        self.menu=tk.Menu(self,tearoff=False)
        self.more=ttk.Button(self,command=self.show_more,style='Icon.TButton',takefocus=True)
        self.more_help=HoverHelp(self.more,'更多工具')
        self.bind('<Configure>',lambda e:self.arrange(e.width))
        self.bind('<<ThemeChanged>>',lambda e:self.refresh_icons(),add='+')
    def add(self,icon,label,command,variable=None,value=None,color=None):
        def invoke():
            if variable is not None:variable.set(not variable.get() if value is None else value)
            command()
            self.refresh_icons(force=True)
        button=ttk.Button(self,command=invoke,style='Icon.TButton',takefocus=True)
        item=dict(icon=icon,label=label,command=invoke,widget=button,variable=variable,value=value,color=color)
        self.items.append(item);button.help=HoverHelp(button,label)
        if variable is not None:variable.trace_add('write',lambda *_:self.refresh_icons(force=True) if self.winfo_exists() else None)
        self.refresh_icons(force=True);return button
    def add_page(self,variable,jump,status):
        self.page_entry=ttk.Entry(self,textvariable=variable,width=4,style='Toolbar.TEntry')
        self.page_entry.bind('<Return>',lambda _:jump());self.page_entry.help=HoverHelp(self.page_entry,'输入页码，按回车跳转')
        self.page_status=ttk.Label(self,textvariable=status,style='Muted.TLabel',anchor='w',width=15)
        self.page_status.help=HoverHelp(self.page_status,lambda:status.get())
    def selected(self,item):
        var=item['variable']
        return var is not None and (bool(var.get()) if item['value'] is None else var.get()==item['value'])
    def refresh_icons(self,force=False):
        key=(theme.CURRENT_SKIN,theme.FG,theme.ACCENT)
        if not force and self._theme_key==key:return
        self._theme_key=key
        for item in self.items:
            selected=self.selected(item);widget=item['widget']
            color=item['color']() if item['color'] else theme.FG
            widget.photo=ImageTk.PhotoImage(icon_image(item['icon'],color),master=self)
            widget.configure(image=widget.photo,style='SelectedIcon.TButton' if selected else 'Icon.TButton')
        self.more.photo=ImageTk.PhotoImage(icon_image('more',theme.FG),master=self)
        self.more.configure(image=self.more.photo)
        self.arrange()
    def arrange(self,width=None):
        width=width or self.winfo_width()
        has_page=hasattr(self,'page_entry');reserved=155 if has_page and width>=450 else 45 if has_page else 0
        capacity=max(0,(width-reserved)//self.cell)
        visible=len(self.items) if capacity>=len(self.items) else max(0,capacity-1)
        for i,item in enumerate(self.items):
            if i<visible:item['widget'].place(x=i*self.cell,y=3,width=self.cell-2,height=32)
            else:item['widget'].place_forget()
        self.hidden=self.items[visible:]
        if self.hidden:self.more.place(x=visible*self.cell,y=3,width=30,height=32)
        else:self.more.place_forget()
        if has_page:
            self.page_entry.place(x=max(0,width-reserved),y=6,width=40,height=27)
            if reserved>45:self.page_status.place(x=width-reserved+46,y=7,width=reserved-46,height=25)
            else:self.page_status.place_forget()
    def show_more(self):
        self.menu.delete(0,'end')
        for item in self.hidden:
            self.menu.add_command(label=('✓ ' if self.selected(item) else '')+item['label'],command=item['command'])
        try:self.menu.tk_popup(self.more.winfo_rootx(),self.more.winfo_rooty()+32)
        finally:self.menu.grab_release()
