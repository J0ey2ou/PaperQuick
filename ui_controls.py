"""Palette-aware ttk surfaces with independent drawing and content insets."""
from PIL import Image, ImageDraw, ImageTk


def install_controls(root, style, palette, tokens):
    root = root._root()
    cache = getattr(root, '_paperquick_control_images', {})
    root._paperquick_control_images = cache
    signature = ''.join(value.lstrip('#') for value in palette.values())

    def element(role, kind, size, fill, outline=None, radius=8, border=8,
                hover=None, pressed=None):
        key = signature + role
        name = 'PQ' + signature + '.' + role + '.' + kind
        if key in cache:
            return name
        images = []
        states = ('normal', 'active', 'pressed', 'disabled', 'focus',
                  'focus_active', 'focus_pressed')
        for state in states:
            color = fill
            if 'active' in state:
                color = hover or fill
            if 'pressed' in state:
                color = pressed or hover or fill
            if state == 'disabled':
                color = palette['SURFACE']
            image = Image.new('RGBA', (size[0]*3, size[1]*3))
            draw = ImageDraw.Draw(image)
            line = palette['ACCENT'] if state.startswith('focus') else outline
            if state == 'disabled':
                line = None
            draw.rounded_rectangle((1, 1, size[0]*3-2, size[1]*3-2),
                                   radius=radius*3, fill=color, outline=line,
                                   width=3 if line else 1)
            images.append(ImageTk.PhotoImage(image.resize(size, Image.Resampling.LANCZOS), master=root))
        # border is only the nine-slice drawing boundary. It must not also
        # shrink the label area; each style supplies its own content padding.
        style.element_create(name, 'image', images[0], ('disabled', images[3]),
                             ('focus', 'pressed', images[6]), ('focus', 'active', images[5]),
                             ('focus', images[4]), ('pressed', images[2]), ('active', images[1]),
                             border=border, padding=0, sticky='nsew')
        cache[key] = images
        return name

    surfaces = [
        ('TButton', 'secondary', palette['SURFACE'], tokens['hover'], tokens['pressed'], None),
        ('Accent.TButton', 'primary', palette['ACCENT'], tokens['accent_hover'], tokens['accent_pressed'], None),
        ('Subtle.TButton', 'subtle', palette['BG'], tokens['hover'], tokens['pressed'], None),
        ('Icon.TButton', 'icon', palette['BG'], tokens['hover'], tokens['pressed'], None),
        ('SelectedIcon.TButton', 'selected_icon', tokens['selection'], tokens['pressed'], tokens['pressed'], palette['ACCENT']),
        ('Nav.TButton', 'nav', palette['BG'], palette['SURFACE'], tokens['pressed'], None),
        ('ActiveNav.TButton', 'active_nav', tokens['selection'], tokens['hover'], tokens['pressed'], palette['LINE']),
    ]
    for selector, role, fill, hover, pressed, outline in surfaces:
        surface = element(role, 'border', (28, 28), fill, outline=outline,
                          hover=hover, pressed=pressed)
        style.layout(selector, [(surface, {'sticky': 'nsew', 'children': [
            ('Button.padding', {'sticky': 'nsew', 'children': [
                ('Button.label', {'sticky': ''})]})]})])
        style.configure(selector, borderwidth=0, relief='flat', focusthickness=0, anchor='center')

    def arrow(role, color):
        key = signature + role
        name = 'PQ' + signature + '.' + role + '.downarrow'
        if key not in cache:
            images = []
            for ink in (color, tokens['disabled']):
                image = Image.new('RGBA', (54, 72))
                ImageDraw.Draw(image).line([(15, 30), (27, 42), (39, 30)], fill=ink, width=5, joint='curve')
                images.append(ImageTk.PhotoImage(image.resize((18, 24), Image.Resampling.LANCZOS), master=root))
            cache[key] = images
            style.element_create(name, 'image', images[0], ('disabled', images[1]), sticky='')
        return name

    menu_surface = element('secondary', 'border', (28, 28), palette['SURFACE'])
    menu_arrow = arrow('menu_arrow', palette['FG'])
    style.layout('TMenubutton', [(menu_surface, {'sticky': 'nsew', 'children': [
        ('Menubutton.padding', {'sticky': 'nsew', 'children': [
            (menu_arrow, {'side': 'right', 'sticky': 'ns'}),
            ('Menubutton.label', {'sticky': ''})]})]})])

    field = element('input', 'field', (28, 28), palette['INPUT'], outline=palette['LINE'], radius=7)
    combo_arrow = arrow('combo_arrow', palette['MUTED'])
    style.layout('TCombobox', [(field, {'sticky': 'nsew', 'children': [
        (combo_arrow, {'side': 'right', 'sticky': 'ns'}),
        ('Combobox.padding', {'sticky': 'nsew', 'children': [
            ('Combobox.textarea', {'sticky': 'nsew'})]})]})])
    style.layout('TEntry', [(field, {'sticky': 'nsew', 'children': [
        ('Entry.padding', {'sticky': 'nsew', 'children': [
            ('Entry.textarea', {'sticky': 'nsew'})]})]})])
    style.layout('TSpinbox', [(field, {'sticky': 'nsew', 'children': [
        ('null', {'side': 'right', 'children': [
            ('Spinbox.uparrow', {'side': 'top', 'sticky': 'e'}),
            ('Spinbox.downarrow', {'side': 'bottom', 'sticky': 'e'})]}),
        ('Spinbox.padding', {'sticky': 'nsew', 'children': [
            ('Spinbox.textarea', {'sticky': 'nsew'})]})]})])
    style.configure('TCombobox', arrowsize=12, borderwidth=0, padding=(10, 7))
    style.configure('TEntry', borderwidth=0, padding=(10, 7))
    for orientation in ('Vertical', 'Horizontal'):
        thumb = element('scroll'+orientation, 'thumb', (10, 32) if orientation == 'Vertical' else (32, 10),
                        tokens['scroll'], radius=5, border=4, hover=palette['MUTED'], pressed=palette['ACCENT'])
        style.layout(orientation+'.TScrollbar', [(orientation+'.Scrollbar.trough', {'sticky': 'nswe', 'children': [
            (thumb, {'expand': 1, 'sticky': 'nswe'})]})])
        style.configure(orientation+'.TScrollbar', width=10, arrowsize=10, borderwidth=0,
                        troughcolor=palette['BG'], background=palette['BG'], lightcolor=palette['BG'],
                        darkcolor=palette['BG'], bordercolor=palette['BG'])
    slider = element('scale', 'slider', (20, 20), palette['PANEL'], outline=palette['ACCENT'], radius=10, border=0)
    for orientation in ('Horizontal', 'Vertical'):
        style.layout(orientation+'.TScale', [(orientation+'.Scale.trough', {'sticky': 'we' if orientation == 'Horizontal' else 'ns', 'children': [
            (slider, {'side': 'left' if orientation == 'Horizontal' else 'top', 'sticky': ''})]})])
        style.configure(orientation+'.TScale', background=palette['BG'], troughcolor=palette['LINE'], borderwidth=0,
                        bordercolor=palette['BG'], lightcolor=palette['BG'], darkcolor=palette['BG'])
