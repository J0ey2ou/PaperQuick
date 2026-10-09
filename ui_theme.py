"""Shared dark technology theme for the local desktop interface."""
import tkinter as tk
from tkinter import ttk

BG='#080f1c'
PANEL='#101c2e'
SURFACE='#15243a'
INPUT='#0b1627'
FG='#e5effb'
MUTED='#8ca3be'
ACCENT='#41d9e6'
LINE='#223b55'
FONT='Microsoft YaHei UI'
ENGLISH='Segoe UI Variable Text'
DISPLAY='Segoe UI Variable Display'
BASE={key:globals()[key] for key in ('BG','PANEL','SURFACE','INPUT','FG','MUTED','ACCENT','LINE')}
SKINS={'深空蓝':BASE,'极光紫':dict(BASE,BG='#110d20',PANEL='#1c1530',SURFACE='#2b2045',INPUT='#171024',ACCENT='#c5a1ff',LINE='#45345f'),
       '石墨灰':dict(BASE,BG='#141719',PANEL='#202529',SURFACE='#2c3338',INPUT='#191e22',ACCENT='#85d4bf',LINE='#414b52'),
       '极简浅色':dict(BASE,BG='#f3f5f8',PANEL='#ffffff',SURFACE='#e9edf4',INPUT='#f8faff',FG='#203047',MUTED='#56677e',ACCENT='#176ca4',LINE='#c5d1e0')}
CURRENT_SKIN='深空蓝'


def apply_skin(root,name):
    """Recolor existing widgets and imported palette names without rebuilding the reader."""
    import sys
    global CURRENT_SKIN
    name=name if name in SKINS else '深空蓝';palette=SKINS[name]
    mapping={value:palette[key] for key,value in BASE.items()}
    mapping.update({globals()[key]:palette[key] for key in BASE})
    mapping.update({'#132237':palette['SURFACE'],'#142137':palette['SURFACE'],'#142941':palette['LINE']})
    for key,value in palette.items():globals()[key]=value
    for module_name in ('app','library_ui','reader_ui','graph_ui','summary_ui','__main__'):
        module=sys.modules.get(module_name)
        if module:
            for key,value in palette.items():
                if hasattr(module,key):setattr(module,key,value)
            if hasattr(module,'BLUE'):module.BLUE=palette['ACCENT']
    CURRENT_SKIN=name;install_theme(root)
    def recolor(widget):
        for key in ('background','foreground','insertbackground','highlightbackground','selectbackground','selectforeground'):
            try:
                color=str(widget.cget(key))
                if color in mapping:widget.configure(**{key:mapping[color]})
            except tk.TclError:pass
        if isinstance(widget,tk.Canvas):
            for item in widget.find_all():
                for key in ('fill','outline'):
                    try:
                        value=widget.itemcget(item,key)
                        if value in mapping:widget.itemconfigure(item,**{key:mapping[value]})
                    except tk.TclError:pass
        if isinstance(widget,ttk.Treeview):
            for tag in widget.tk.splitlist(widget.tk.call(widget._w,'tag','names')):
                for option in ('background','foreground'):
                    value=str(widget.tag_configure(tag,option))
                    if value in mapping:widget.tag_configure(tag,**{option:mapping[value]})
        for child in widget.winfo_children():recolor(child)
    recolor(root)
    style=ttk.Style(root)
    if name=='极简浅色':
        style.map('TNotebook.Tab',background=[('selected','#dceafa'),('active',SURFACE)],foreground=[('selected',ACCENT),('active',FG)])
        style.map('TEntry',bordercolor=[('focus',ACCENT)])
    return name

def install_theme(root):
    root.configure(bg=BG)
    root.option_add('*Font',(FONT,10))
    for option,value in {'*Text.background':INPUT,'*Text.foreground':FG,'*Text.insertBackground':ACCENT,
                         '*Text.selectBackground':'#245271','*Text.relief':'flat',
                         '*Listbox.background':PANEL,'*Listbox.foreground':FG,'*Canvas.background':BG,
                         '*Menu.background':SURFACE,'*Menu.foreground':FG,'*Menu.activeBackground':'#245271',
                         '*Menu.activeForeground':FG}.items():root.option_add(option,value)
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',background=BG,foreground=FG,font=(FONT,10),bordercolor=LINE,lightcolor=LINE,darkcolor=LINE)
    style.configure('TFrame',background=BG)
    style.configure('TNotebook',background=PANEL,borderwidth=0)
    style.configure('TNotebook.Tab',background=SURFACE,foreground=MUTED,padding=(14,9))
    style.map('TNotebook.Tab',background=[('selected','#1c485f'),('active','#223b55')],foreground=[('selected',ACCENT),('active',FG)])
    style.configure('Horizontal.TScale',background=PANEL,troughcolor=LINE,bordercolor=LINE,lightcolor=ACCENT,darkcolor=LINE)
    style.configure('Card.TFrame',background=PANEL)
    style.configure('TLabel',background=BG,foreground=FG)
    style.configure('Card.TLabel',background=PANEL,foreground=FG)
    style.configure('Muted.TLabel',foreground=MUTED)
    style.configure('CardMuted.TLabel',background=PANEL,foreground=MUTED)
    style.configure('Number.TLabel',background=PANEL,foreground=ACCENT,font=(DISPLAY,29))
    style.configure('TButton',background=SURFACE,foreground=FG,padding=(14,9),borderwidth=1,relief='flat',focuscolor=ACCENT)
    style.map('TButton',background=[('disabled',PANEL),('pressed','#21435d'),('active','#203950')],foreground=[('disabled','#647991'),('active',ACCENT)])
    style.configure('Accent.TButton',background=ACCENT,foreground='#06212c',font=(FONT,10,'bold'),padding=(18,10),borderwidth=0)
    style.map('Accent.TButton',background=[('disabled','#24515f'),('pressed','#27b8c8'),('active','#71e9ef')],foreground=[('disabled','#8ca3be'),('!disabled','#06212c')])
    style.configure('TEntry',fieldbackground=INPUT,foreground=FG,insertcolor=ACCENT,padding=9,borderwidth=1)
    style.map('TEntry',bordercolor=[('focus',ACCENT)])
    style.configure('TCombobox',fieldbackground=INPUT,background=SURFACE,foreground=FG,arrowcolor=ACCENT,padding=7)
    style.map('TCombobox',fieldbackground=[('readonly',INPUT)],foreground=[('readonly',FG)],selectbackground=[('readonly',INPUT)],selectforeground=[('readonly',FG)])
    root.option_add('*TCombobox*Listbox.background',SURFACE);root.option_add('*TCombobox*Listbox.foreground',FG)
    style.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=FG,rowheight=43,borderwidth=0,font=(FONT,10))
    style.map('Treeview',background=[('selected','#1c485f')],foreground=[('selected','#8bf3fa')])
    style.configure('Treeview.Heading',background=SURFACE,foreground=MUTED,padding=(12,11),font=(FONT,10,'bold'),relief='flat')
    style.map('Treeview.Heading',background=[('active','#213a52')],foreground=[('active',ACCENT)])
    style.configure('TScrollbar',background='#2a435c',troughcolor=BG,arrowcolor=MUTED,borderwidth=0)
    style.map('TScrollbar',background=[('active','#427088')])
    style.configure('TProgressbar',background=ACCENT,troughcolor=INPUT,borderwidth=0)
    style.configure('TPanedwindow',background=BG,sashwidth=14)
    style.configure('TCheckbutton',background=BG,foreground=FG)
    style.configure('Nav.TButton',background=BG,foreground=MUTED,padding=(15,12),borderwidth=0,font=(FONT,11))
    style.map('Nav.TButton',background=[('active',PANEL)],foreground=[('active',FG)])
    style.configure('ActiveNav.TButton',background=SURFACE,foreground=ACCENT,padding=(15,12),borderwidth=0,font=(FONT,11,'bold'))
    style.map('ActiveNav.TButton',background=[('active','#203950')],foreground=[('active',ACCENT)])
    root.after(80,lambda:window_chrome(root))
    return style

def window_chrome(window):
    """Style this application's own Windows title bar, where supported."""
    import os
    if os.name!='nt' or not window.winfo_exists():return
    try:
        import ctypes
        from ctypes import wintypes
        window.update_idletasks()
        user32=ctypes.windll.user32;user32.GetParent.restype=wintypes.HWND
        hwnd=user32.GetParent(wintypes.HWND(window.winfo_id()))
        for attribute,value in ((20,1),(35,0x1c0f08),(36,0xfbefE5)):
            setting=ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd),attribute,ctypes.byref(setting),ctypes.sizeof(setting))
    except (AttributeError,OSError,tk.TclError):pass

def emblem(parent,size=52):
    from pathlib import Path
    try:
        path=Path(__file__).parent/'assets'/'assistant-64.png'
        photo=tk.PhotoImage(master=parent,file=path)
        if size<45:photo=photo.subsample(2)
        label=tk.Label(parent,image=photo,bg=BG,width=size,height=size)
        label.image=photo
        return label
    except (OSError,tk.TclError):pass
    canvas=tk.Canvas(parent,width=size,height=size,bg=BG,highlightthickness=0)
    canvas.create_polygon(size*.5,3,size-4,size*.26,size-4,size*.73,size*.5,size-3,4,size*.73,4,size*.26,outline=ACCENT,fill=PANEL,width=1.5)
    canvas.create_text(size/2,size/2,text='P',fill=ACCENT,font=('Segoe UI',int(size*.42),'bold'))
    return canvas

def window_icon(window):
    from pathlib import Path
    try:
        photo=tk.PhotoImage(master=window,file=Path(__file__).parent/'assets'/'assistant-64.png')
        window.iconphoto(True,photo);window._paperquick_icon=photo
    except (OSError,tk.TclError):pass

def style_dialog(window):
    window.configure(bg=BG);window_icon(window);window.after(80,lambda:window_chrome(window))

def opening_animation(window):
    """A short one-shot fade; respect the Windows client-animation preference."""
    import os
    enabled=True
    if os.name=='nt':
        try:
            import ctypes
            value=ctypes.c_int(1)
            ctypes.windll.user32.SystemParametersInfoW(0x1042,0,ctypes.byref(value),0)
            enabled=bool(value.value)
        except (AttributeError,OSError):pass
    if not enabled:return
    try:window.attributes('-alpha',.15)
    except tk.TclError:return
    def step(index=0):
        if not window.winfo_exists():return
        progress=min(1,index/14)
        try:window.attributes('-alpha',.15+.85*(1-(1-progress)**3))
        except tk.TclError:return
        if progress<1:window.after(18,lambda:step(index+1))
    window.after(20,step)
