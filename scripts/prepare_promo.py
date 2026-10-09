"""Build self-contained WeChat copy materials, with the demo GIF and screenshot embedded."""
from pathlib import Path
import base64
import html
import re

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/J0ey2ou/PaperQuick'
RELEASE = REPO + '/releases/latest'
from promo_content import TITLE, blocks

def inline(value):
    value = html.escape(value)
    value = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', value)
    return re.sub(r'https://github\.com/[^\s<]+', lambda m: '<a href="' + m.group() + '">' + m.group() + '</a>', value)


def media(kind):
    filename = kind.split(':',1)[1] if kind.startswith('shot:') else 'demo.gif' if kind == 'gif' else 'browser.png'
    mime = 'image/gif' if kind == 'gif' else 'image/jpeg' if filename.endswith('.jpg') else 'image/png'
    return 'data:' + mime + ';base64,' + base64.b64encode((ROOT / 'docs' / 'images' / filename).read_bytes()).decode()


parts = ['<h1>' + html.escape(TITLE) + '</h1>']
markdown = ['# ' + TITLE]
plain = [TITLE]
for tag, content in blocks:
    if tag in ('gif', 'screenshot') or tag.startswith('shot:'):
        parts.append('<figure><img data-kind="' + tag + '" src="' + media(tag) + '" alt="' + ('文献直达选词查询动图' if tag == 'gif' else '文献直达使用截图') + '"><figcaption>' + html.escape(content) + '</figcaption></figure>')
        markdown.append('![' + content + '](docs/images/' + (tag.split(':',1)[1] if tag.startswith('shot:') else 'demo.gif' if tag == 'gif' else 'browser.png') + ')')
    elif tag in ('ul', 'ol'):
        parts.append('<' + tag + '>' + ''.join('<li>' + inline(item) + '</li>' for item in content) + '</' + tag + '>')
        markdown.append('\n'.join((str(i + 1) + '. ' if tag == 'ol' else '- ') + item for i, item in enumerate(content)))
        plain.append('\n'.join((str(i + 1) + '. ' if tag == 'ol' else '• ') + item.replace('**', '') for i, item in enumerate(content)))
    else:
        parts.append('<' + tag + '>' + inline(content) + '</' + tag + '>')
        markdown.append(('## ' if tag == 'h2' else '### ' if tag == 'h3' else '') + content)
        plain.append(content.replace('**', ''))
plain_text = '\n\n'.join(plain) + '\n'
(ROOT / '推送文案.txt').write_text(plain_text, 'utf-8')
(ROOT / '推送文案.md').write_text('\n\n'.join(markdown) + '\n', 'utf-8')

page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>文献直达 · 微信图文与动图示例</title><style>body{margin:0;background:#f3f6fa;color:#172c45;font:16px/1.85 "Microsoft YaHei UI",sans-serif}main{max-width:820px;margin:24px auto;padding:0 20px}nav{display:flex;gap:10px;flex-wrap:wrap;position:sticky;top:0;padding:12px 0;background:#f3f6fa;z-index:2}button,a.action{font:inherit;font-size:14px;border:0;background:#215cce;color:white;border-radius:8px;padding:10px 15px;cursor:pointer;text-decoration:none}article{background:white;border:1px solid #dce4ef;border-radius:16px;margin:20px 0;padding:32px}h1{font-size:28px;line-height:1.45}h2{font-size:21px;line-height:1.55;margin:32px 0 14px;border-left:4px solid #215cce;padding-left:12px}h3{font-size:18px;line-height:1.6;margin:24px 0 10px}p{margin:14px 0;overflow-wrap:anywhere}li{margin:10px 0}ul,ol{padding-left:24px}figure{margin:22px 0}img{width:100%;height:auto;border-radius:8px}figcaption,#status{font-size:13px;color:#5d6f84}a{color:#215cce;overflow-wrap:anywhere}small{color:#5d6f84}@media(max-width:600px){main{padding:0 12px}article{padding:22px 18px}h1{font-size:24px}}</style></head><body><main><nav><button id="rich">一键复制图文（含动图）</button><button id="text">复制纯文案</button><button id="image">复制截图</button><a class="action" id="download" download="文献直达-使用截图.png">保存截图</a><a class="action" id="gif-download" download="文献直达-选词查询演示.gif">保存动图</a></nav><p id="status" role="status">已补充完整使用方式与动图示例。支持富文本的编辑器可复制图文；微信编辑器若过滤图片 / 动图，请保存后单独上传。</p><article id="post">''' + ''.join(parts) + '''</article><small>图文、截图和 GIF 均内嵌在本页，无需加载外部图片。演示数据仅用于展示操作流程。</small></main><script>
const post=document.getElementById('post'),status=document.getElementById('status'),picture=post.querySelector('img[data-kind="screenshot"]'),animation=post.querySelector('img[data-kind="gif"]');
document.getElementById('download').href=picture.src;
post.querySelectorAll('img[data-kind^="shot:"]').forEach((img,i)=>{const a=document.createElement('a');a.href=img.src;a.download='PaperQuick-使用截图-'+(i+1)+'.jpg';a.textContent='保存这张截图';img.parentElement.append(a);});document.getElementById('gif-download').href=animation.src;
const text=()=>{let value=post.innerText;post.querySelectorAll('figcaption,figure a').forEach(c=>value=value.replace(c.innerText,''));return value.trim();};
const fallback=()=>{const s=window.getSelection(),r=document.createRange();r.selectNodeContents(post);s.removeAllRanges();s.addRange(r);const ok=document.execCommand('copy');s.removeAllRanges();return ok;};
document.getElementById('rich').onclick=async()=>{
 try{const clone=post.cloneNode(true);clone.querySelectorAll('figure a').forEach(a=>a.remove());clone.querySelectorAll('p,li').forEach(e=>e.style.cssText='font-size:16px;line-height:1.85;margin:14px 0;');clone.querySelectorAll('h2').forEach(e=>e.style.cssText='font-size:21px;line-height:1.55;margin:28px 0 14px;');clone.querySelectorAll('img').forEach(e=>e.style.cssText='max-width:100%;height:auto;');await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([clone.innerHTML],{type:'text/html'}),'text/plain':new Blob([text()],{type:'text/plain'})})]);status.textContent='已复制完整图文，包含截图与动图。编辑器若过滤媒体，请用“保存截图 / 保存动图”单独上传。';}
 catch(e){status.textContent=fallback()?'已复制图文；若媒体被过滤，请保存后单独插入。':'复制受限，请选中文案手动复制，并保存图片 / 动图。';}
};
document.getElementById('text').onclick=async()=>{try{await navigator.clipboard.writeText(text());status.textContent='已复制完整纯文案。';}catch(e){status.textContent=fallback()?'已复制，请粘贴并检查格式。':'请选中文案手动复制。';}};
document.getElementById('image').onclick=async()=>{try{const blob=await(await fetch(picture.src)).blob();await navigator.clipboard.write([new ClipboardItem({'image/png':blob})]);status.textContent='已复制截图，可粘贴到聊天或编辑器。';}catch(e){status.textContent='图片复制受限，请点击“保存截图”。';}};
</script></body></html>'''
(ROOT / '推送文案.html').write_text(page, 'utf-8')
print(f'Promotion updated: {len(plain_text)} characters, GIF + screenshot embedded')
