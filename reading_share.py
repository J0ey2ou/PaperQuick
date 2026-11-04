"""Local, factual reading cards. Only explicitly selected public fields are exported."""
from datetime import date
from functools import lru_cache
from pathlib import Path
import math
import os
import re
import uuid

from PIL import Image, ImageDraw, ImageFont, ImageOps

THEMES = {'书页花园': ('reading-garden.png', '#f6f2e8', '#fffdf7', '#243c32', '#667367', '#b1975e'),
          '静夜书海': ('reading-night.png', '#101e30', '#1b2b40', '#f1eddf', '#aab9ca', '#d2b98a')}


def _text(value, limit=10000):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value or ''))[:limit].strip()


def _seconds(value):
    try:return max(0, float(value)) if math.isfinite(float(value)) else 0
    except (ValueError, TypeError):return 0


def paper_share_data(library, rid):
    record = library.get(rid)
    seconds = library.db.execute('SELECT COALESCE(SUM(MAX(0,end-start)),0) FROM reading_sessions WHERE paper=?', (rid,)).fetchone()[0]
    return {'kind': 'paper', 'date': date.today().isoformat(), 'papers': [record], 'seconds': seconds}


def share_model(data, include_notes=False, include_abstract=True, include_time=True, caption=''):
    """Whitelist fields, dropping local paths, internal IDs, images and hidden notes."""
    papers=[]
    for source in data.get('papers', []):
        paper = {key: _text(source.get(key)) for key in ('title','authors','year','venue','doi')}
        paper['title'] = paper['title'] or '未命名文献'
        if include_time:paper['seconds'] = _seconds(source.get('seconds'))
        if include_abstract:paper['abstract'] = _text(source.get('abstract') or source.get('content'))
        if include_notes:
            paper['notes'] = _text(source.get('notes'))
            paper['annotations'] = [{'quote':_text(a.get('quote')), 'text':_text(a.get('text'))}
                                    for a in source.get('annotations', []) if isinstance(a, dict)]
        papers.append(paper)
    model = {'kind': 'paper' if data.get('kind') == 'paper' else 'recap', 'date': _text(data.get('date'), 30),
             'end_date': _text(data.get('end_date') or data.get('date'), 30), 'papers': papers,
             'caption': _text(caption, 180), 'include_time': bool(include_time), 'include_notes': bool(include_notes)}
    if include_time:model['seconds'] = _seconds(data.get('seconds'))
    return model


@lru_cache(maxsize=32)
def _font(size, bold=False):
    windir=Path(os.environ.get('WINDIR','C:/Windows'))
    candidates=[windir/'Fonts'/('msyhbd.ttc' if bold else 'msyh.ttc'), windir/'Fonts/simhei.ttf',
                Path('/System/Library/Fonts/PingFang.ttc'), Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    for candidate in candidates:
        if candidate.is_file():return ImageFont.truetype(str(candidate),size)
    raise RuntimeError('分享图片需要中文字体，请安装微软雅黑、黑体或 Noto Sans CJK 后重试。')


def wrapped_lines(draw, text, font, width, maximum):
    lines=[]
    # A long note must not delay a preview. Visible cards always mark truncation.
    value=_text(text, max(2000,maximum*160)); truncated=len(str(text or '').strip())>len(value)
    for paragraph in value.splitlines() or ['']:
        line=''
        for char in paragraph:
            if line and draw.textlength(line+char,font=font)>width:
                lines.append(line);line=char
            else:line+=char
        lines.append(line)
    if len(lines)>maximum:truncated=True;lines=lines[:maximum]
    if truncated and lines:
        line=lines[-1]
        while line and draw.textlength(line+'…',font=font)>width:line=line[:-1]
        lines[-1]=line+'…'
    return lines[:maximum]


def _block(draw, text, x, y, width, size, color, maximum=5, bold=False, spacing=12):
    font=_font(size,bold)
    for line in wrapped_lines(draw,text,font,width,maximum):
        draw.text((x,y),line,font=font,fill=color);y+=size+spacing
    return y


def _time(seconds):
    minutes=int(_seconds(seconds)//60)
    if seconds and minutes==0:return '不足 1 分钟'
    return f'{minutes//60} 小时 {minutes%60} 分钟' if minutes>=60 else f'{minutes} 分钟'


def card_count(model):
    return 1 if model['kind']=='paper' else max(1, math.ceil(len(model['papers'])/4))


def render_card(model, theme='书页花园', page=0):
    if theme not in THEMES:raise ValueError('请选择有效的分享样式。')
    count=card_count(model)
    if not 0<=page<count:raise ValueError('分享图片页码超出范围。')
    asset,bg,panel,ink,muted,accent=THEMES[theme]
    single=model['kind']=='paper'; image=Image.new('RGB',(1080,1600),bg);draw=ImageDraw.Draw(image)
    source=Path(__file__).resolve().parent/'assets/share'/asset
    with Image.open(source) as art:
        header=ImageOps.fit(art.convert('RGB'),(1080,590),centering=(.5,.65));image.paste(header,(0,0))
    draw.text((66,48),'PaperQuick  /  READING JOURNAL',font=_font(24),fill=ink)
    draw.text((64,100),'这一篇，值得读' if single else '让阅读留下回响',font=_font(54,True),fill=ink)
    period=model['date'] if model['end_date']==model['date'] else model['date']+' — '+model['end_date']
    draw.text((68,182),period,font=_font(26),fill=ink)
    if model.get('caption'):_block(draw,model['caption'],68,236,590,25,ink,3)
    draw.rounded_rectangle((40,546,1040,1530),radius=30,fill=panel)
    y=580
    if single:
        paper=model['papers'][0] if model['papers'] else {'title':'尚未选择文献'}
        y=_block(draw,paper['title'],76,y,928,40,ink,5,True)+16
        meta=' · '.join(paper.get(k,'') for k in ('authors','year','venue') if paper.get(k))
        if meta:y=_block(draw,meta,78,y,920,23,muted,2)+12
        if paper.get('doi'):y=_block(draw,'DOI  '+paper['doi'],78,y,920,22,muted,2)+10
        if model['include_time']:
            draw.text((78,y),'累计阅读  '+_time(model['seconds']),font=_font(24),fill=accent);y+=54
        if paper.get('abstract'):
            draw.text((78,y),'文献摘要',font=_font(24,True),fill=accent);y+=42
            y=_block(draw,paper['abstract'],78,y,920,28,ink,4 if model['include_notes'] else 8)+24
        if model['include_notes']:
            notes=paper.get('notes','')
            quotes=['\n'.join(filter(None,(a['quote'],a['text']))) for a in paper.get('annotations',[]) if a['quote'] or a['text']]
            value='\n'.join(filter(None,[notes,*quotes]))
            if value:
                draw.text((78,y),'我的笔记与摘录',font=_font(24,True),fill=accent);y+=42
                y=_block(draw,value,78,y,920,28,ink,max(1,min(8,(1470-y)//40)))
        if not paper.get('abstract') and not (model['include_notes'] and (paper.get('notes') or paper.get('annotations'))):
            y=_block(draw,'读过，思考过。\n让每一篇研究，成为下一次发现的起点。',78,y+30,880,30,muted,4)
    else:
        draw.text((78,y),f"{len(model['papers'])} 篇文献",font=_font(38,True),fill=ink)
        if model['include_time']:draw.text((480,y+8),'阅读 '+_time(model['seconds']),font=_font(26),fill=accent)
        y+=78
        selected=model['papers'][page*4:page*4+4]
        if not selected:_block(draw,'这段时间还没有阅读记录。\n从下一篇感兴趣的研究开始。',78,y+35,900,32,muted,4)
        for index,paper in enumerate(selected,page*4+1):
            draw.text((78,y),f'{index:02}',font=_font(24,True),fill=accent)
            _block(draw,paper['title'],140,y-3,855,29,ink,2,True)
            detail=paper.get('notes') if model['include_notes'] else ''
            if model['include_notes'] and not detail:
                detail='；'.join('\n'.join(filter(None,(a['quote'],a['text']))) for a in paper.get('annotations',[]))
            detail=detail or paper.get('abstract') or ('DOI '+paper['doi'] if paper.get('doi') else '文献阅读记录')
            _block(draw,detail,140,y+82,850,23,muted,2)
            y+=202
            if index%4:draw.line((140,y-20,995,y-20),fill=accent,width=1)
    height=min(1600,max(1100,y+170)) if single else 1600
    if height<1600:
        draw.rectangle((0,height-120,1080,1600),fill=bg)
        draw.rounded_rectangle((40,height-160,1040,height-70),radius=30,fill=panel)
        draw.rectangle((40,height-160,1040,height-120),fill=panel)
        result=image.crop((0,0,1080,height));image.close();image=result;draw=ImageDraw.Draw(image)
    note='含个人笔记与摘录' if model['include_notes'] else '未包含个人笔记与摘录'
    draw.text((64,height-48),note,font=_font(21),fill=muted)
    draw.text((790,height-48),f'PaperQuick  ·  {page+1}/{count}',font=_font(21),fill=muted)
    return image


def save_cards(model, destination, theme='书页花园'):
    """Create new files only. No original documents or embedded image metadata."""
    path=Path(destination)
    if path.suffix.lower()!='.png':path=path.with_suffix('.png')
    count=card_count(model)
    paths=[path] if count==1 else [path.with_name(f'{path.stem}-{n+1:02d}.png') for n in range(count)]
    if any(p.exists() for p in paths):raise FileExistsError('同名图片已存在，请换一个文件名。')
    created=[];staged=[]
    try:
        for n,target in enumerate(paths):
            temporary=target.with_name('.'+target.name+'.'+uuid.uuid4().hex+'.tmp');staged.append(temporary)
            with temporary.open('xb') as output:
                with render_card(model,theme,n) as image:image.save(output,format='PNG')
                output.flush();os.fsync(output.fileno())
        for temporary,target in zip(staged,paths):
            # Windows rename and POSIX hard-link both reject existing destinations.
            if os.name=='nt':os.rename(temporary,target)
            else:os.link(temporary,target)
            created.append(target)
        return paths
    except Exception:
        for target in created:target.unlink(missing_ok=True)
        raise
    finally:
        for temporary in staged:temporary.unlink(missing_ok=True)
