"""Layout and wheel handling shared by pages and scrolling forms."""
import tkinter as tk
from tkinter import ttk


def scrollable_page(parent,padding=(0,12)):
    host=ttk.Frame(parent);canvas=tk.Canvas(host,highlightthickness=0)
    scroll=ttk.Scrollbar(host,command=canvas.yview);scroll.pack(side='right',fill='y')
    canvas.configure(yscrollcommand=scroll.set);canvas.pack(fill='both',expand=True)
    content=ttk.Frame(canvas,padding=padding);item=canvas.create_window((0,0),window=content,anchor='nw')
    def size(_=None):
        if not canvas.winfo_exists():return
        canvas.itemconfigure(item,width=max(1,canvas.winfo_width()),height=max(content.winfo_reqheight(),canvas.winfo_height()))
        canvas.configure(scrollregion=canvas.bbox('all'))
    content.bind('<Configure>',size);canvas.bind('<Configure>',size)
    return host,content


def flow_bar(frame, gap=6):
    """Wrap action buttons rather than allowing pack to clip the last buttons."""
    pending = [None]
    rows = []
    def arrange():
        pending[0] = None
        if not frame.winfo_exists():return
        padding = frame.tk.splitlist(frame.cget('padding'))
        left = frame.winfo_pixels(str(padding[0])) if padding else 0
        right = frame.winfo_pixels(str(padding[2])) if len(padding) > 2 else left
        width = max(1, frame.winfo_width() - left - right); x = 0; row = 0; column = 0
        children = [child for child in frame.winfo_children() if child not in rows]
        for child in children:
            if child.winfo_manager() == 'pack':child.pack_forget()
            elif child.winfo_manager() == 'grid':child.grid_forget()
        for child in children:
            requested = child.winfo_reqwidth() + gap
            if x and x + requested > width:row += 1; column = 0; x = 0
            if row == len(rows):
                rows.append(ttk.Frame(frame, style=frame.cget('style') or 'TFrame'))
                # These row frames are geometry masters, not widget parents.
                # Keep them below the earlier-created buttons in Tk's stack.
                rows[-1].lower()
            # A separate geometry master keeps each row's column widths local;
            # widget ownership stays with the original frame and its callers.
            child.grid(in_=rows[row], row=0, column=column, padx=(0,gap), pady=3, sticky='w')
            x += requested; column += 1
        for index, container in enumerate(rows):
            if children and index <= row:container.grid(row=index, column=0, sticky='w')
            else:container.grid_remove()
    def schedule(_=None):
        if pending[0] is None:pending[0] = frame.after_idle(arrange)
    frame.bind('<Configure>', schedule, add='+');schedule()
    def cleanup(event):
        if event.widget is frame and pending[0] is not None:
            frame.after_cancel(pending[0]);pending[0]=None
    frame.bind('<Destroy>',cleanup,add='+')


def wheel_units(widget, delta):
    remainder = getattr(widget, '_wheel_remainder', 0) - delta / 120
    units = int(remainder)
    widget._wheel_remainder = remainder - units
    return units


def install_scrolling(root):
    """Route wheel events over a form's children to its enclosing canvas.

    Native Text/Listbox/Treeview controls keep their own class bindings; no
    pointer, focus, keyboard, or system-wide input hook is involved.
    """
    root=root._root()
    if getattr(root, '_paperquick_scrolling', False):return
    root._paperquick_scrolling = True
    def route(event):
        target = event.widget
        if isinstance(target, (tk.Text, tk.Listbox, ttk.Treeview, ttk.Combobox, ttk.Spinbox)):
            # Native scrollable children consume their wheel first. Short form
            # inputs should allow the enclosing form to scroll.
            if isinstance(target, (ttk.Combobox, ttk.Spinbox)):return
            try:
                if tuple(map(float,target.yview())) != (0.0,1.0):return
            except tk.TclError:return
        while target is not None:
            if isinstance(target, tk.Canvas):
                try:
                    if target.cget('scrollregion') and tuple(map(float,target.yview())) != (0.0,1.0):
                        delta = getattr(event,'delta',0) or (120 if getattr(event,'num',0)==4 else -120)
                        units = wheel_units(target,delta)
                        if not float(target.cget('yscrollincrement')):target.configure(yscrollincrement=28)
                        if units:target.yview_scroll(units,'units')
                        return 'break'
                except tk.TclError:return
            target = getattr(target, 'master', None)
    root.bind_all('<MouseWheel>', route, add='+')
    root.bind_all('<Button-4>', route, add='+');root.bind_all('<Button-5>', route, add='+')
    root._paperquick_wheel_route=route
