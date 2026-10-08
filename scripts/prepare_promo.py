"""Build self-contained WeChat copy materials, with the demo GIF and screenshot embedded."""
from pathlib import Path
import base64
import html
import re

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/J0ey2ou/PaperQuick'
RELEASE = REPO + '/releases/latest'
TITLE = '导师发来的论文，选一下就能找到原文入口'
blocks = [
    ('p', '导师发来一段文献引用，合作者转来一篇科研推送，群里又有人推荐了一篇论文。真正开始阅读前，常常还要做一串重复操作：复制标题、切换窗口、搜索、核对论文，再找 PDF 或全文入口。'),
    ('p', '我做了一个小工具「**文献直达 · PaperQuick**」，把这些步骤接起来。收到文献信息后，尽量在当前阅读场景里完成查询，把时间留给读论文。'),
    ('h2', '选一次，自动接起后面的检索流程'),
    ('p', '**选中英文论文标题 / DOI → 右键或按一次快捷键 → 自动匹配论文 → 查找原文入口 → 匹配明确时自动打开网站。**'),
    ('p', '支持完整英文论文标题、DOI、arXiv 编号 / 链接，也支持可以读取正文的科研推送链接。结果里会显示标题、作者、年份和原文链接，方便核对；同名、近似或多篇候选时，由你确认后再打开。'),
    ('gif', '操作流程演示：选词 → 查询 → 原文入口。公开论文示例数据，非实时测速；动图未展示原生右键菜单。'),
    ('h2', '三种用法，接上你已有的阅读习惯'),
    ('h3', '① 复制文献信息，粘贴并查找'),
    ('p', '打开桌面软件，复制标题、DOI 或链接，点击 **“粘贴并查找”**。也可以手动粘贴后点 **“查找原文”**，或按 **Ctrl + Enter**。开放 PDF、全文页和出版社入口会陆续显示，链接出现就可以点击；单个链接、全部结果都能复制。'),
    ('h3', '② Word / PDF / 微信电脑版，选中后按快捷键'),
    ('p', '点击软件里的 **“全局快捷键”**，或者双击 **“全局选词助手.exe”**，助手会驻留系统托盘。回到原软件，选中可复制的英文论文标题或 DOI，按状态栏 / 托盘显示的组合键，就能发起查询。无需每次先打开软件再粘贴。'),
    ('h3', '③ Edge / Chrome 网页里，选中后右键'),
    ('p', '在地址栏打开 **edge://extensions** 或 **chrome://extensions**，开启开发者模式，选择 **“加载已解压的扩展”**，加载软件包里的 **browser-extension** 文件夹。之后选中标题 / DOI，右键选择 **“查找文献并打开原文”** 即可。'),
    ('p', '也可以在已打开的推送页面右键 **“查找当前页面中的论文”**，或点击扩展图标。浏览器扩展独立工作，无需先启动桌面软件；更新文件后，在扩展管理页点 **“重新加载”**。'),
    ('screenshot', '文献直达浏览器扩展实际界面：AlphaFold 公开论文示例。'),
    ('h2', '从下载到第一次查询，只需这几步'),
    ('ol', [
        '打开下方 GitHub 下载页，下载 Windows 软件包，并**解压整个压缩包**。',
        '双击 **文献直达.exe**。保留同目录的助手、扩展文件夹和使用说明。',
        '复制一篇论文的完整英文标题或 DOI，点 **“粘贴并查找”**，体验第一次查询。',
        '想进一步减少复制粘贴，就启用全局快捷键，或给浏览器加载一次扩展。'
    ]),
    ('p', '**无需安装 Python，无需注册账号。** 软件包中有中英文 README 和完整操作说明，可按自己的使用场景设置。'),
    ('h2', '快捷键，可以换成你习惯的组合'),
    ('ol', [
        '主界面点 **“设置”**，点击快捷键输入框。',
        '按下你想使用的组合，也可手动填写，例如 **Ctrl + Alt + J**。',
        '点击 **“保存并启用”**，立即生效，重启后继续使用。'
    ]),
    ('p', '也可右键系统托盘图标 → **“自定义快捷键…”**。支持至少两个修饰键（Ctrl / Alt / Shift）+ 字母、数字或 F1–F24。新组合被占用时，会提示并保留原快捷键。默认尝试 Ctrl + Alt + F；占用时会尝试 Ctrl + Alt + Shift + F、Ctrl + Alt + F8，请以实际显示值为准。'),
    ('h2', '原文入口先到，其他版本陆续补齐'),
    ('p', '单一 DOI 查询先打开 DOI / 出版社入口；arXiv 编号先打开 PDF，其他开放版本在后台补齐。标题查询有结果就显示；唯一完全匹配时，优先打开已找到的开放 PDF / 全文入口。接口较慢时，还可点 **“直接学术搜索”**，自动把当前标题带入 Google Scholar，不用再复制一次。'),
    ('h2', '遇到公众号验证，也能接着查'),
    ('p', '先在浏览器打开推送，手动完成验证，确保正文已经显示。然后选中其中的英文论文标题 / DOI 查询；装好扩展后，也能直接右键查询当前页面。只有中文新闻标题时，建议找到正文里的英文论文标题；一篇推送含多篇论文或参考文献时，请核对候选。'),
    ('h2', '使用时，记住这几件事'),
    ('ul', [
        '**需要联网。** 标题 / DOI 会发送到文献检索服务；粘贴网页链接时会读取该网页。软件不保存查询历史，不监听鼠标，不显示跟随浮窗，也不自动开机启动。',
        '**原文入口不等于保证免费全文。** 预印本、作者稿可能与正式版本不同，付费文献可能需要学校 / 机构订阅。软件提供地址，由浏览器打开或下载，不自动保存论文文件。',
        '**选词需要可复制文字。** 扫描版 PDF 需要 OCR，禁复制或管理员权限窗口可能无法读取。快捷键触发时会复制本次选词，剪贴板会变为该文字。',
        '**基础功能无需配置邮箱。** 可选填写 Unpaywall 联系邮箱，补充更多开放版本；邮箱会随 DOI 查询发送到该服务。'
    ]),
    ('p', '把“收到文献 → 找到原文入口”变成一个顺手的动作。少切几次窗口，少做几次重复搜索，多留一点时间读论文。'),
    ('h2', '下载与操作说明'),
    ('p', '**GitHub 源码 + 中英文 README：** ' + REPO),
    ('p', '**Windows 软件包下载：** ' + RELEASE),
]


def inline(value):
    value = html.escape(value)
    value = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', value)
    return re.sub(r'https://github\.com/[^\s<]+', lambda m: '<a href="' + m.group() + '">' + m.group() + '</a>', value)


def media(kind):
    filename = 'demo.gif' if kind == 'gif' else 'browser.png'
    mime = 'image/gif' if kind == 'gif' else 'image/png'
    return 'data:' + mime + ';base64,' + base64.b64encode((ROOT / 'docs' / 'images' / filename).read_bytes()).decode()


parts = ['<h1>' + html.escape(TITLE) + '</h1>']
markdown = ['# ' + TITLE]
plain = [TITLE]
for tag, content in blocks:
    if tag in ('gif', 'screenshot'):
        parts.append('<figure><img data-kind="' + tag + '" src="' + media(tag) + '" alt="' + ('文献直达选词查询动图' if tag == 'gif' else '文献直达使用截图') + '"><figcaption>' + html.escape(content) + '</figcaption></figure>')
        markdown.append('![' + content + '](docs/images/' + ('demo.gif' if tag == 'gif' else 'browser.png') + ')')
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
document.getElementById('download').href=picture.src;document.getElementById('gif-download').href=animation.src;
const text=()=>{let value=post.innerText;post.querySelectorAll('figcaption').forEach(c=>value=value.replace(c.innerText,''));return value.trim();};
const fallback=()=>{const s=window.getSelection(),r=document.createRange();r.selectNodeContents(post);s.removeAllRanges();s.addRange(r);const ok=document.execCommand('copy');s.removeAllRanges();return ok;};
document.getElementById('rich').onclick=async()=>{
 try{const clone=post.cloneNode(true);clone.querySelectorAll('p,li').forEach(e=>e.style.cssText='font-size:16px;line-height:1.85;margin:14px 0;');clone.querySelectorAll('h2').forEach(e=>e.style.cssText='font-size:21px;line-height:1.55;margin:28px 0 14px;');clone.querySelectorAll('img').forEach(e=>e.style.cssText='max-width:100%;height:auto;');await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([clone.innerHTML],{type:'text/html'}),'text/plain':new Blob([text()],{type:'text/plain'})})]);status.textContent='已复制完整图文，包含截图与动图。编辑器若过滤媒体，请用“保存截图 / 保存动图”单独上传。';}
 catch(e){status.textContent=fallback()?'已复制图文；若媒体被过滤，请保存后单独插入。':'复制受限，请选中文案手动复制，并保存图片 / 动图。';}
};
document.getElementById('text').onclick=async()=>{try{await navigator.clipboard.writeText(text());status.textContent='已复制完整纯文案。';}catch(e){status.textContent=fallback()?'已复制，请粘贴并检查格式。':'请选中文案手动复制。';}};
document.getElementById('image').onclick=async()=>{try{const blob=await(await fetch(picture.src)).blob();await navigator.clipboard.write([new ClipboardItem({'image/png':blob})]);status.textContent='已复制截图，可粘贴到聊天或编辑器。';}catch(e){status.textContent='图片复制受限，请点击“保存截图”。';}};
</script></body></html>'''
(ROOT / '推送文案.html').write_text(page, 'utf-8')
print(f'Promotion updated: {len(plain_text)} characters, GIF + screenshot embedded')
