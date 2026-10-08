"""Show a public-paper example for documentation screenshots; no network or settings writes."""
import json
from pathlib import Path
import sys
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App
from paper_finder import Paper, Result

root = tk.Tk()
root.withdraw()
app = App(root)
app.email = ''
root.title('文献直达 · 使用演示')
example = json.loads(Path('live-check.json').read_text('utf-8'))[0]['papers'][0]
paper = Paper(example['title'], example['doi'], 'John Jumper 等', '2021', 'Nature', 'Crossref')
for link in example['links']:
    paper.add_link('开放 PDF' if link['kind'] == 'pdf' else '开放原文' if link['kind'] == 'fulltext' else '出版社 / DOI', link['url'], link['kind'], link['source'], '开放版本' if link['kind'] != 'publisher' else '可能需要机构权限')
app.input.insert('1.0', example['title'])
app.result = Result(example['title'], [paper])
app.copy_button.configure(state='normal')
app.render(app.result)
app.status.set('示例：找到 AlphaFold 论文与开放原文入口')
root.after(1200, root.deiconify)
root.mainloop()
