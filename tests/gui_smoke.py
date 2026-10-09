"""创建真实 Tk 窗口，检查结果/错误状态；不访问网络、不写设置。"""
from pathlib import Path
import sys
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App
from paper_finder import Paper, Result, BrowserPageRequired

root = tk.Tk()
root.withdraw()
app = App(root)
paper = Paper("Highly accurate protein structure prediction with AlphaFold", "10.1038/s41586-021-03819-2", "John Jumper 等", "2021", "Nature", "Crossref")
paper.add_link("开放 PDF", "https://example.org/test.pdf", "pdf", "Europe PMC", "开放版本")
paper.add_link("出版社 / DOI", "https://doi.org/10.1038/s41586-021-03819-2", "publisher", "Crossref")
opened = []
app.open_url = opened.append
app.open_link = lambda paper,link:opened.append(link.url)
app.auto_open = True
app.busy = True
app.events.put(("partial", Result(paper.doi, [paper], complete=False)))
app.poll()
assert app.busy
assert str(app.copy_button.cget("state")) == "normal"
assert len(opened) == 1
app.events.put(("partial", Result(paper.doi, [paper], complete=False)))
app.poll()
assert len(opened) == 1
app.events.put(("result", Result(paper.title, [paper], ["一个服务连接失败，其他结果保留。"])))
app.poll()
root.update_idletasks()
assert "1 篇" in app.status.get()
assert str(app.copy_button.cget("state")) == "normal"
assert len(app.cards.winfo_children()) == 2
assert not app.busy
assert len(opened) == 1
app.events.put(("error", "请粘贴英文论文标题。"))
app.poll()
assert app.status.get() == "查询未完成"
assert str(app.search_button.cget("state")) == "normal"
assert str(app.progress.cget("mode")) == "determinate"
app.events.put(("browser-required", BrowserPageRequired("https://mp.weixin.qq.com/s/test")))
app.poll()
root.update_idletasks()
assert "浏览器" in app.status.get()
assert app.result is None
assert str(app.copy_button.cget("state")) == "disabled"
frame = app.cards.winfo_children()[0]
buttons = frame.winfo_children()[-1].winfo_children()
assert len(buttons) == 3
assert "打开推送" in buttons[0].cget("text")
app.settings()
assert app.current_page=='settings'
panel = app.settings_panel
entries = [child for child in panel.winfo_children() if child.winfo_class() == 'TEntry']
assert len(entries) == 2
assert 'Ctrl' in entries[0].get()
assert any(child.winfo_class() == 'TButton' and child.cget('text') == '保存并启用' for child in panel.winfo_children())
app.settings_page.destroy()
root.destroy()
print("GUI smoke passed: initial / results / partial-service note / error / buttons")
