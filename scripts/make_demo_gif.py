"""Turn recorded extension frames into an annotated, looping usage example."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1]
font_path = Path('C:/Windows/Fonts/msyh.ttc')
font = ImageFont.truetype(str(font_path), 27)
small = ImageFont.truetype(str(font_path), 17)
steps = [
    ('01-source', '① 收到导师 / 合作者发来的文献信息', 1800),
    ('02-selected', '② 选中英文论文标题，发起右键查询', 2200),
    ('03-query', '③ 自动带入标题，开始匹配论文', 1400),
    ('04-candidate', '④ 结果陆续显示，链接出现即可点击', 2000),
    ('05-fulltext', '⑤ 找到开放 PDF，自动打开原文入口', 2800),
    ('06-links', '⑥ 结果页保留其他版本，也能复制链接', 2400),
]
frames, durations = [], []
for name, caption, duration in steps:
    shot = Image.open(root / 'build' / 'demo-frames' / (name + '.png')).convert('RGB')
    frame = Image.new('RGB', (960, 820), '#f3f6fa')
    frame.paste(shot, (0, 74))
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, 0, 959, 73), fill='#172c45')
    draw.text((24, 20), caption, font=font, fill='white')
    draw.text((24, 794), '公开论文流程演示 · 使用固定示例数据，不代表实际检索网速', font=small, fill='#5d6f84')
    frames.append(frame.quantize(colors=128))
    durations.append(duration)
target = root / 'docs' / 'images' / 'demo.gif'
target.parent.mkdir(parents=True, exist_ok=True)
frames[0].save(target, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True, disposal=2)
with Image.open(target) as check:
    assert check.n_frames == len(steps)
    assert check.info.get('loop') == 0
assert target.stat().st_size < 2 * 1024 * 1024
print(f'Demo GIF saved: {len(steps)} frames, {sum(durations) / 1000:.1f} seconds, {target.stat().st_size} bytes')
