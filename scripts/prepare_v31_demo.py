"""Enrich the isolated fictional demo for public screenshots, never the real library."""
from pathlib import Path
import sys
from datetime import datetime,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_core import Library
lib=Library(Path(__file__).resolve().parents[1]/'build'/'demo-library')
rid=next(r['id'] for r in lib.records() if r['title']=='Local literature reading demo')
lib.save({'notes':'【虚构示例 / 演示数据】\n\n研究问题\n如何把文献查询、课题归档与阅读记录连接起来？\n\n主要观察\n• 在同一个工作区完成整理与阅读。\n• 笔记、批注和阅读时长保存在本地。\n\n第 1 页：右键可以新建笔记或批注。\n\n下一步\n从参考文献继续查找相关研究。'},rid=rid)
yesterday=datetime.now().replace(hour=14,minute=0,second=0,microsecond=0)-timedelta(days=1)
with lib.db:
    lib.db.execute('DELETE FROM reading_sessions')
    for i,p in enumerate([lib.get(rid)]+[p for p in lib.records() if p['id']!=rid][:2]):
        start=yesterday.timestamp()+i*1800
        lib.db.execute('INSERT INTO reading_sessions(paper,start,end) VALUES(?,?,?)',(p['id'],start,start+[1080,720,540][i]))
lib.close()
print('Fictional demo notes and yesterday reading sessions prepared.')
