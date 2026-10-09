"""Deterministic, user-configurable node highlighting shared by both graph views."""
import math
import re

DEFAULT={'mode':'downloaded','low':'#7088a7','high':'#41d9e6','candidate':'#bf9afb',
         'read_weight':1.0,'citation_weight':1.0,'download_weight':2.0}

def validate_style(values):
    result=dict(DEFAULT);result.update(values)
    if result['mode'] not in ('downloaded','read_count','citation_count','custom'):raise ValueError('请选择有效高亮模式。')
    for key in ('low','high','candidate'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(result[key])):raise ValueError('颜色格式应为 #RRGGBB。')
    for key in ('read_weight','citation_weight','download_weight'):
        result[key]=float(result[key])
        if not math.isfinite(result[key]) or not 0<=result[key]<=10:raise ValueError('权重须在 0–10 之间。')
    return result

def score(node,style):
    mode=style['mode']
    if mode=='downloaded':return float(bool(node.get('pdf')))
    if mode in ('read_count','citation_count'):return math.log1p(max(0,float(node.get(mode,0))))
    return (math.log1p(max(0,float(node.get('read_count',0))))*style['read_weight']+
            math.log1p(max(0,float(node.get('citation_count',0))))*style['citation_weight']+
            bool(node.get('pdf'))*style['download_weight'])

def appearance(node,style,maximum=1):
    if not node.get('in_library',True):return style['candidate'],5
    ratio=min(1,score(node,style)/max(1,maximum))
    first=[int(style['low'][i:i+2],16) for i in (1,3,5)];second=[int(style['high'][i:i+2],16) for i in (1,3,5)]
    color='#'+''.join(f'{round(a+(b-a)*ratio):02x}' for a,b in zip(first,second))
    return color,4+ratio*4
