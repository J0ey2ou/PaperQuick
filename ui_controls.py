"""Palette-aware, antialiased ttk surfaces and quiet scrollbars."""
from PIL import Image,ImageDraw,ImageTk


def install_controls(root,style,palette,tokens):
    root=root._root();cache=getattr(root,'_paperquick_control_images',{})
    root._paperquick_control_images=cache
    signature=''.join(palette[k].lstrip('#') for k in ('BG','SURFACE','INPUT','ACCENT'))
    def element(role,kind,size,fill,outline=None,radius=8,border=8):
        key=signature+role;name='PQ'+signature+'.'+role+'.'+kind
        if key in cache:return name
        images=[]
        for state in ('normal','active','pressed','disabled','focus'):
            color=fill
            if role=='secondary':color={'active':tokens['hover'],'pressed':tokens['pressed']}.get(state,fill)
            if role=='primary':color={'active':tokens['accent_hover'],'pressed':tokens['accent_pressed']}.get(state,fill)
            if state=='disabled':color=palette['SURFACE']
            if role.startswith('scroll') and state in ('active','pressed'):color=palette['MUTED'] if state=='active' else palette['ACCENT']
            image=Image.new('RGBA',(size[0]*3,size[1]*3));draw=ImageDraw.Draw(image)
            line=palette['ACCENT'] if state=='focus' else outline
            draw.rounded_rectangle((1,1,size[0]*3-2,size[1]*3-2),radius=radius*3,fill=color,outline=line,width=3 if line else 1)
            images.append(ImageTk.PhotoImage(image.resize(size,Image.Resampling.LANCZOS),master=root))
        style.element_create(name,'image',images[0],('disabled',images[3]),('pressed',images[2]),('active',images[1]),('focus',images[4]),border=border,sticky='nsew')
        cache[key]=images;return name
    for selector,role in [('TButton','secondary'),('Accent.TButton','primary'),('Subtle.TButton','subtle')]:
        fill=palette['SURFACE'] if role=='secondary' else palette['BG'] if role=='subtle' else palette['ACCENT']
        surface=element(role,'border',(28,28),fill,radius=8)
        style.layout(selector,[(surface,{'sticky':'nsew','children':[('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})]})])
        style.configure(selector,borderwidth=0,relief='flat',focusthickness=0)
    field=element('input','field',(28,28),palette['INPUT'],outline=palette['LINE'],radius=7)
    arrow_key=signature+'arrow';arrow_name='PQ'+signature+'.Combobox.downarrow'
    if arrow_key not in cache:
        image=Image.new('RGBA',(54,72));draw=ImageDraw.Draw(image);draw.line([(12,30),(27,45),(42,30)],fill=palette['MUTED'],width=5,joint='curve')
        arrow=ImageTk.PhotoImage(image.resize((18,24),Image.Resampling.LANCZOS),master=root);cache[arrow_key]=[arrow]
        style.element_create(arrow_name,'image',arrow,sticky='')
    style.layout('TCombobox',[(field,{'sticky':'nsew','children':[(arrow_name,{'side':'right','sticky':'ns'}),('Combobox.padding',{'sticky':'nsew','children':[('Combobox.textarea',{'sticky':'nsew'})]})]})])
    style.layout('TEntry',[(field,{'sticky':'nsew','children':[('Entry.padding',{'sticky':'nsew','children':[('Entry.textarea',{'sticky':'nsew'})]})]})])
    style.configure('TCombobox',arrowsize=12,borderwidth=0,padding=(10,7))
    style.configure('TEntry',borderwidth=0,padding=(10,7))
    for orientation in ('Vertical','Horizontal'):
        thumb=element('scroll'+orientation,'thumb',(10,32) if orientation=='Vertical' else (32,10),tokens['scroll'],radius=5,border=4)
        style.layout(orientation+'.TScrollbar',[(orientation+'.Scrollbar.trough',{'sticky':'nswe','children':[(thumb,{'expand':1,'sticky':'nswe'})]})])
        style.configure(orientation+'.TScrollbar',width=10,arrowsize=10,borderwidth=0,troughcolor=palette['BG'],background=palette['BG'],lightcolor=palette['BG'],darkcolor=palette['BG'],bordercolor=palette['BG'])
    slider=element('scale','slider',(20,20),palette['PANEL'],outline=palette['ACCENT'],radius=10,border=0)
    for orientation in ('Horizontal','Vertical'):
        style.layout(orientation+'.TScale',[(orientation+'.Scale.trough',{'sticky':'we' if orientation=='Horizontal' else 'ns','children':[(slider,{'side':'left' if orientation=='Horizontal' else 'top','sticky':''})]})])
        style.configure(orientation+'.TScale',background=palette['BG'],troughcolor=palette['LINE'],borderwidth=0,bordercolor=palette['BG'],lightcolor=palette['BG'],darkcolor=palette['BG'])
