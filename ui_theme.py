"""Shared, accessible palettes and typography for the desktop interface."""
import tkinter as tk
from tkinter import ttk
import sys

FONT = 'Microsoft YaHei UI'
ENGLISH = 'Segoe UI Variable Text'
DISPLAY = 'Segoe UI Variable Display'
if sys.platform=='darwin':FONT='PingFang SC';ENGLISH='Helvetica Neue';DISPLAY='Helvetica Neue'
_CORE = ('BG', 'PANEL', 'SURFACE', 'INPUT', 'FG', 'MUTED', 'ACCENT', 'LINE')
BASE = dict(zip(_CORE, ('#101722', '#192331', '#243247', '#121d2b',
                        '#edf3fb', '#a5b4c8', '#99c5ff', '#35475f')))
SKINS = {
    '书页白': dict(BASE, BG='#f5f4f0', PANEL='#ffffff', SURFACE='#eeede8',
                  INPUT='#fcfcfa', FG='#26352f', MUTED='#5f6b64', ACCENT='#29634c', LINE='#dce1da'),
    '深空蓝': BASE,
    '极光紫': dict(BASE, BG='#181523', PANEL='#242034', SURFACE='#342d49',
                  INPUT='#1b1729', ACCENT='#cfb7fa', LINE='#514461'),
    '石墨灰': dict(BASE, BG='#181c20', PANEL='#232a30', SURFACE='#303b43',
                  INPUT='#1c2228', ACCENT='#9ddacb', LINE='#47575f'),
    '极简浅色': dict(BASE, BG='#f4f6fa', PANEL='#ffffff', SURFACE='#e9eef6',
                   INPUT='#fcfdff', FG='#233249', MUTED='#58697f',
                   ACCENT='#245faa', LINE='#cbd5e3'),
    '琉璃·冰川蓝': dict(BASE, BG='#f2f5f9', PANEL='#ffffff', SURFACE='#e7edf5',
                      INPUT='#fbfcfe', FG='#24364c', MUTED='#53677d', ACCENT='#2d6197', LINE='#d1dce8'),
    '琉璃·翡翠绿': dict(BASE, BG='#e5f5ee', PANEL='#f2fcf7', SURFACE='#cfe9dd',
                      INPUT='#f7fdf9', FG='#173c30', MUTED='#3f6355', ACCENT='#226546', LINE='#95c8b1'),
    '琉璃·蔷薇粉': dict(BASE, BG='#f9eaf1', PANEL='#fff5fa', SURFACE='#efd5e2',
                      INPUT='#fff9fc', FG='#46283b', MUTED='#725164', ACCENT='#8e3f65', LINE='#d4a6bd'),
    '琉璃·鸢尾紫': dict(BASE, BG='#f5f3f8', PANEL='#ffffff', SURFACE='#ece8f2',
                      INPUT='#fdfcfe', FG='#352e43', MUTED='#665c77', ACCENT='#6b5290', LINE='#dcd5e6'),
    '琉璃·琥珀金': dict(BASE, BG='#faf0de', PANEL='#fff9ed', SURFACE='#ecddbd',
                      INPUT='#fffdf7', FG='#45351c', MUTED='#6c5939', ACCENT='#80561a', LINE='#ccb58b'),
    '琉璃·深海青': dict(BASE, BG='#102c36', PANEL='#193b46', SURFACE='#234d59',
                      INPUT='#102f3a', FG='#eefcff', MUTED='#b1d1da', ACCENT='#9ce4ea', LINE='#50808c'),
}
GLASS_SKINS = tuple(name for name in SKINS if name.startswith('琉璃·'))
CURRENT_SKIN = '书页白'
globals().update(SKINS[CURRENT_SKIN])
_LEGACY = dict(zip(_CORE, ('#080f1c', '#101c2e', '#15243a', '#0b1627',
                          '#e5effb', '#8ca3be', '#41d9e6', '#223b55')))


def _mix(first, second, amount):
    values = [round(int(first[i:i+2], 16) * (1-amount) +
                    int(second[i:i+2], 16) * amount) for i in (1, 3, 5)]
    return '#' + ''.join(f'{value:02x}' for value in values)


def _luminance(color):
    channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    channels = [v / 12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in channels]
    return sum(v * weight for v, weight in zip(channels, (.2126, .7152, .0722)))


def _tokens(palette):
    light = _luminance(palette['BG']) > .5
    return {
        'selection': _mix(palette['PANEL'], palette['ACCENT'], .18 if light else .25),
        'selection_fg': palette['FG'],
        'hover': _mix(palette['SURFACE'], palette['ACCENT'], .12),
        'pressed': _mix(palette['SURFACE'], palette['ACCENT'], .21),
        'accent_fg': '#ffffff' if light else '#152133',
        'accent_hover': _mix(palette['ACCENT'], '#000000' if light else '#ffffff', .10),
        'accent_pressed': _mix(palette['ACCENT'], '#000000', .16),
        'disabled': _mix(palette['MUTED'], palette['SURFACE'], .30),
        'scroll': _mix(palette['LINE'], palette['MUTED'], .18),
        'read': '#256c56' if light else '#9bd8c2',
        'warning': '#89601c' if light else '#e6c58e',
    }


def _recolor_widgets(widget, mapping, tokens):
    """Update explicit Tk colors while leaving document images and user colors alone."""
    for key in ('background', 'foreground', 'insertbackground', 'highlightbackground',
                'highlightcolor', 'selectbackground', 'selectforeground',
                'activebackground', 'activeforeground', 'disabledforeground'):
        try:
            color = str(widget.cget(key)).lower()
            if color in mapping:
                widget.configure(**{key: mapping[color]})
        except tk.TclError:
            pass
    # ttk.Entry (and its Combobox/Spinbox subclasses) also inherits tk.Entry,
    # but selection colors are style options rather than widget options.
    if isinstance(widget, (tk.Text, tk.Listbox, tk.Entry)) and not isinstance(widget, ttk.Widget):
        widget.configure(selectbackground=tokens['selection'], selectforeground=tokens['selection_fg'])
    if isinstance(widget, tk.Menu):
        widget.configure(activebackground=tokens['selection'], activeforeground=tokens['selection_fg'])
    if isinstance(widget, tk.Canvas):
        for item in widget.find_all():
            for key in ('fill', 'outline'):
                try:
                    value = widget.itemcget(item, key).lower()
                    if value in mapping:
                        widget.itemconfigure(item, **{key: mapping[value]})
                except tk.TclError:
                    pass
    if isinstance(widget, ttk.Treeview):
        for tag in widget.tk.splitlist(widget.tk.call(widget._w, 'tag', 'names')):
            for option in ('background', 'foreground'):
                value = str(widget.tag_configure(tag, option)).lower()
                if value in mapping:
                    widget.tag_configure(tag, **{option: mapping[value]})
    for child in widget.winfo_children():
        _recolor_widgets(child, mapping, tokens)


def apply_skin(root, name):
    """Apply a palette to open pages and dialogs, retaining their current contents."""
    import sys
    global CURRENT_SKIN
    name = name if name in SKINS else '书页白'
    previous = {key: globals()[key] for key in _CORE}
    palette, tokens = SKINS[name], _tokens(SKINS[name])
    mapping = {value: palette[key] for source in (_LEGACY, BASE, previous)
               for key, value in source.items()}
    old_tokens = _tokens(previous)
    for key in ('selection', 'hover', 'pressed', 'disabled', 'scroll', 'read', 'warning'):
        mapping[old_tokens[key]] = tokens[key]
    mapping.update({
        '#132237': palette['SURFACE'], '#142137': palette['SURFACE'],
        '#142941': palette['LINE'], '#1c3047': palette['SURFACE'],
        '#1c485f': tokens['selection'], '#245271': tokens['selection'],
        '#8bf3fa': tokens['selection_fg'], '#06212c': tokens['accent_fg'],
        '#647e9b': palette['MUTED'], '#dce4ef': palette['LINE'],
        '#77ddba': tokens['read'], '#e6b980': tokens['warning'],
    })
    globals().update(palette)
    from pathlib import Path
    directory=Path(__file__).resolve().parent
    for module in list(sys.modules.values()):
        location=getattr(module,'__file__',None)
        if not location or Path(location).resolve().parent!=directory:continue
        if module:
            for key, value in palette.items():
                if hasattr(module, key):
                    setattr(module, key, value)
            if hasattr(module, 'BLUE'):
                module.BLUE = palette['ACCENT']
    CURRENT_SKIN = name
    if getattr(root, '_paperquick_theme', None) != name:
        install_theme(root)
    _recolor_widgets(root, mapping, tokens)
    _style_window_tree(root)
    return name


def install_theme(root):
    root.configure(bg=BG)
    from ui_widgets import install_scrolling
    install_scrolling(root)
    for widget_class in ('TCombobox','TEntry','TSpinbox'):
        root.option_add(f'*{widget_class}.font',(FONT,10))
    tokens = _tokens({key: globals()[key] for key in _CORE})
    # A wildcard *Font also becomes ttk.Label's explicit widget font and
    # overrides Hero/CardStat styles. Limit option defaults to classic Tk.
    for widget_class in ('Label', 'Button', 'Entry', 'Text', 'Listbox', 'Menu',
                         'Menubutton', 'Checkbutton', 'Radiobutton', 'Spinbox', 'Message'):
        root.option_add(f'*{widget_class}.font', (FONT, 10))
    for option, value in {
        '*Text.background': INPUT, '*Text.foreground': FG, '*Text.insertBackground': ACCENT,
        '*Text.selectBackground': tokens['selection'], '*Text.selectForeground': FG,
        '*Text.relief': 'flat', '*Listbox.background': PANEL, '*Listbox.foreground': FG,
        '*Listbox.selectBackground': tokens['selection'], '*Listbox.selectForeground': FG,
        '*Canvas.background': BG, '*Menu.background': PANEL, '*Menu.foreground': FG,
        '*Menu.activeBackground': tokens['selection'], '*Menu.activeForeground': FG,
        '*Menu.borderWidth': 0, '*Menu.relief': 'flat',
    }.items():
        root.option_add(option, value)
    style = ttk.Style(root)
    if style.theme_use() != 'clam':
        style.theme_use('clam')
    style.configure('.', background=BG, foreground=FG, font=(FONT, 10),
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    style.configure('TFrame', background=BG)
    style.configure('Card.TFrame', background=PANEL)
    style.configure('TLabel', background=BG, foreground=FG)
    for name, options in {
        'Hero.TLabel': dict(font=(FONT, 24, 'bold')),
        'Section.TLabel': dict(font=(FONT, 13, 'bold')),
        'Eyebrow.TLabel': dict(font=(FONT, 9, 'bold'), foreground=ACCENT),
        'Stat.TLabel': dict(font=(DISPLAY, 28), foreground=ACCENT),
        'Muted.TLabel': dict(foreground=MUTED),
        'Card.TLabel': dict(background=PANEL),
        'CardTitle.TLabel': dict(background=PANEL, font=(FONT, 12, 'bold')),
        'CardBody.TLabel': dict(background=PANEL, font=(FONT, 10)),
        'CardMuted.TLabel': dict(background=PANEL, foreground=MUTED),
        'CardStat.TLabel': dict(background=PANEL, font=(DISPLAY, 28), foreground=ACCENT),
        'Number.TLabel': dict(background=PANEL, font=(DISPLAY, 29), foreground=ACCENT),
    }.items():
        style.configure(name, **options)
    style.configure('TButton', background=SURFACE, foreground=FG, padding=(12, 8),
                    borderwidth=0, relief='flat', focuscolor=ACCENT, focusthickness=1)
    style.map('TButton', background=[('disabled', SURFACE), ('pressed', tokens['pressed']), ('active', tokens['hover'])],
              foreground=[('disabled', tokens['disabled']), ('!disabled', FG)])
    style.configure('Accent.TButton', background=ACCENT, foreground=tokens['accent_fg'],
                    font=(FONT, 10, 'bold'), padding=(18, 10), borderwidth=0)
    style.map('Accent.TButton', background=[('disabled', SURFACE), ('pressed', tokens['accent_pressed']), ('active', tokens['accent_hover'])],
              foreground=[('disabled', tokens['disabled']), ('!disabled', tokens['accent_fg'])])
    style.configure('Subtle.TButton', background=BG, foreground=MUTED, padding=(12, 9))
    style.map('Subtle.TButton', background=[('pressed', SURFACE), ('active', PANEL)],
              foreground=[('disabled', tokens['disabled']), ('active', FG), ('!disabled', MUTED)])
    style.configure('Compact.TButton', padding=(10, 6), font=(FONT, 9))
    style.configure('Icon.TButton',padding=3,width=0,background=BG,borderwidth=0)
    style.map('Icon.TButton',background=[('pressed',tokens['pressed']),('active',tokens['hover'])])
    style.configure('SelectedIcon.TButton',padding=3,width=0,background=tokens['selection'],borderwidth=0)
    style.map('SelectedIcon.TButton',background=[('pressed',tokens['pressed']),('active',tokens['hover']),('!disabled',tokens['selection'])])
    style.configure('Toolbar.TEntry',padding=3)
    style.configure('TEntry', fieldbackground=INPUT, foreground=FG, insertcolor=ACCENT,
                    selectbackground=tokens['selection'], selectforeground=FG, padding=(9,6), borderwidth=1)
    style.map('TEntry', bordercolor=[('focus', ACCENT)],
              foreground=[('disabled', MUTED)], fieldbackground=[('disabled', SURFACE)])
    style.configure('TCombobox', fieldbackground=INPUT, background=SURFACE, foreground=FG,
                    arrowcolor=MUTED, padding=(9,6), borderwidth=1, arrowsize=16)
    style.configure('Filter.TCombobox',padding=(8,5),arrowsize=16)
    style.map('TCombobox', fieldbackground=[('readonly', INPUT), ('disabled', SURFACE)],
              foreground=[('disabled', MUTED), ('readonly', FG)],
              selectbackground=[('readonly', INPUT)], selectforeground=[('readonly', FG)],
              bordercolor=[('focus', ACCENT)], background=[('active', tokens['hover'])])
    for option, value in {'background': PANEL, 'foreground': FG,
                          'selectBackground': tokens['selection'], 'selectForeground': FG}.items():
        root.option_add('*TCombobox*Listbox.' + option, value)
    style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=FG,
                    rowheight=max(36,round(24*float(root.tk.call('tk','scaling')))), borderwidth=0, font=(FONT, 10))
    style.map('Treeview', background=[('selected', tokens['selection'])], foreground=[('selected', FG)])
    style.configure('Treeview.Heading', background=SURFACE, foreground=MUTED,
                    padding=(8, 9), font=(FONT, 10, 'bold'), relief='flat')
    style.map('Treeview.Heading', background=[('active', tokens['hover'])], foreground=[('active', FG)])
    style.configure('TNotebook', background=BG, borderwidth=0, tabmargins=(0, 0, 0, 12))
    # Button.border supplies a flat filled surface without clam's raised tab
    # outline. Keep Notebook.focus/label so keyboard focus and tab events work.
    style.layout('TNotebook.Tab', [('Button.border', {'sticky': 'nswe', 'children': [
        ('Notebook.padding', {'sticky': 'nswe', 'children': [
            ('Notebook.focus', {'sticky': 'nswe', 'children': [
                ('Notebook.label', {'sticky': ''})]})]})]})])
    style.configure('TNotebook.Tab', background=BG, foreground=MUTED,
                    padding=(18, 11), borderwidth=0, relief='flat', font=(FONT, 10),
                    lightcolor=BG, darkcolor=BG, bordercolor=BG, focuscolor=ACCENT)
    style.map('TNotebook.Tab', background=[('selected', tokens['selection']), ('active', SURFACE)],
              foreground=[('selected', FG), ('active', FG)],
              lightcolor=[('selected', tokens['selection']), ('active', SURFACE)],
              darkcolor=[('selected', tokens['selection']), ('active', SURFACE)],
              bordercolor=[('selected', tokens['selection']), ('active', SURFACE)])
    style.configure('Horizontal.TScale', background=BG, troughcolor=LINE,
                    bordercolor=LINE, lightcolor=ACCENT, darkcolor=LINE)
    style.configure('TScrollbar', background=tokens['scroll'], troughcolor=BG,
                    arrowcolor=MUTED, borderwidth=0, arrowsize=12)
    style.map('TScrollbar', background=[('active', MUTED), ('pressed', ACCENT)])
    style.configure('TProgressbar', background=ACCENT, troughcolor=INPUT, borderwidth=0)
    style.configure('TPanedwindow', background=BG, sashwidth=12)
    for selector in ('TCheckbutton', 'TRadiobutton'):
        style.configure(selector, background=BG, foreground=FG, padding=(0, 4),
                        indicatorbackground=INPUT, indicatorforeground=tokens['accent_fg'])
        style.map(selector, background=[('active', BG)], foreground=[('disabled', MUTED), ('active', FG)],
                  indicatorbackground=[('selected', ACCENT), ('active', SURFACE)])
    style.configure('TLabelframe', background=BG, bordercolor=LINE, borderwidth=1)
    style.configure('TLabelframe.Label', background=BG, foreground=MUTED, font=(FONT, 10, 'bold'))
    style.configure('Nav.TButton', background=BG, foreground=MUTED, padding=(15, 12),
                    borderwidth=0, font=(FONT, 11))
    style.map('Nav.TButton', background=[('active', PANEL)], foreground=[('active', FG), ('!disabled', MUTED)])
    style.configure('ActiveNav.TButton', background=SURFACE, foreground=FG,
                    padding=(15, 12), borderwidth=0, font=(FONT, 11, 'bold'))
    style.map('ActiveNav.TButton', background=[('active', tokens['hover'])], foreground=[('!disabled', FG)])
    from ui_controls import install_controls
    install_controls(root,style,{key:globals()[key] for key in _CORE},tokens)
    root._paperquick_theme = CURRENT_SKIN
    _queue_window_chrome(root)
    return style


def _colorref(color):
    return int(color[1:3], 16) | int(color[3:5], 16) << 8 | int(color[5:7], 16) << 16


def window_chrome(window):
    """Match this application's own Windows title bar to the selected palette."""
    import os
    if os.name != 'nt':
        return
    try:
        if not window.winfo_exists():
            return
        import ctypes
        from ctypes import wintypes
        window.update_idletasks()
        user32 = ctypes.windll.user32
        user32.GetParent.restype = wintypes.HWND
        hwnd = user32.GetParent(wintypes.HWND(window.winfo_id()))
        for attribute, value in ((20, int(_luminance(BG) < .5)),
                                 (35, _colorref(BG)), (36, _colorref(FG))):
            setting = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), attribute,
                ctypes.byref(setting), ctypes.sizeof(setting))
    except (AttributeError, OSError, tk.TclError):
        pass


def _queue_window_chrome(window):
    """Coalesce initialization callbacks; page switches do not accumulate timers."""
    if getattr(window, '_paperquick_chrome_pending', False):
        return
    window._paperquick_chrome_pending = True
    def apply():
        window._paperquick_chrome_pending = False
        window_chrome(window)
    window.after_idle(apply)


def _style_window_tree(widget):
    if isinstance(widget, (tk.Tk, tk.Toplevel)):
        _apply_opacity(widget)
        signature = (BG, FG)
        if getattr(widget, '_paperquick_chrome_palette', None) != signature:
            widget._paperquick_chrome_palette = signature
            _queue_window_chrome(widget)
    for child in widget.winfo_children():
        _style_window_tree(child)


def emblem(parent, size=52):
    from pathlib import Path
    try:
        path = Path(__file__).parent / 'assets' / 'assistant-64.png'
        photo = tk.PhotoImage(master=parent, file=path)
        if size < 45:
            photo = photo.subsample(2)
        label = tk.Label(parent, image=photo, bg=BG, width=size, height=size)
        label.image = photo
        return label
    except (OSError, tk.TclError):
        pass
    canvas = tk.Canvas(parent, width=size, height=size, bg=BG, highlightthickness=0)
    canvas.create_polygon(size*.5, 3, size-4, size*.26, size-4, size*.73,
                          size*.5, size-3, 4, size*.73, 4, size*.26,
                          outline=ACCENT, fill=PANEL, width=1.5)
    canvas.create_text(size/2, size/2, text='P', fill=ACCENT,
                       font=('Segoe UI', int(size*.42), 'bold'))
    return canvas


def window_icon(window):
    from pathlib import Path
    try:
        photo = tk.PhotoImage(master=window, file=Path(__file__).parent / 'assets' / 'assistant-64.png')
        window.iconphoto(True, photo)
        window._paperquick_icon = photo
    except (OSError, tk.TclError):
        pass


def style_dialog(window):
    window.configure(bg=BG)
    _apply_opacity(window)
    window_icon(window)
    window._paperquick_chrome_palette = (BG, FG)
    _queue_window_chrome(window)


def skin_opacity(name=None):
    """Glass is a palette treatment; all windows remain fully opaque."""
    return 1.0


def _apply_opacity(window):
    try:
        window.attributes('-alpha', skin_opacity())
    except tk.TclError:
        pass


def opening_animation(window):
    """Keep the startup hook without exposing underlying windows during a fade."""
    _apply_opacity(window)
