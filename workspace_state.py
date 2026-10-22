"""Persistent smart views and a small project workbench; no GUI or network."""
import json
import time
import uuid
from library_core import Library
from library_table import TableState, values
from library_organization import READING_STATES


class WorkspaceStore:
    def __init__(self, directory):
        self.library = Library(directory)
        self.db = self.library.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS workspace_views(id TEXT PRIMARY KEY,name TEXT NOT NULL,data TEXT NOT NULL,updated REAL);
        CREATE TABLE IF NOT EXISTS workspace_projects(project TEXT PRIMARY KEY,question TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS workspace_todos(id TEXT PRIMARY KEY,project TEXT NOT NULL,title TEXT NOT NULL,done INTEGER NOT NULL DEFAULT 0,due TEXT NOT NULL DEFAULT '',updated REAL);
        CREATE TABLE IF NOT EXISTS workspace_queue(project TEXT NOT NULL,paper TEXT NOT NULL,position INTEGER NOT NULL,PRIMARY KEY(project,paper));
        ''')

    def close(self):self.library.close()

    def save_view(self, name, criteria, view_id=None):
        name = str(name).strip()
        if not name or len(name)>100:raise ValueError('视图名称需要 1–100 字。')
        data = self.validate_view(criteria)
        view_id = view_id or uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO workspace_views VALUES(?,?,?,?)', (view_id,name,json.dumps(data,ensure_ascii=False),time.time()))
        return view_id

    def validate_view(self, data):
        if not isinstance(data,dict):raise ValueError('智能视图条件必须为对象。')
        result = {key:data.get(key,default) for key,default in (
            ('project',None),('query',''),('status','全部状态'),('rating','全部评分'),('tag','全部标签'),
            ('download','全部'),('year_from',''),('year_to',''),('sort_key',None),('descending',False),('filters',{}),('columns',[]))}
        if result['project']:self.library.project(result['project'])
        for key in ('query','status','rating','tag','download'):
            if not isinstance(result[key],str) or len(result[key])>10000:raise ValueError('智能视图文字条件不正确。')
        if result['status'] not in ('全部状态',*READING_STATES):raise ValueError('不支持的阅读状态。')
        if result['rating'] not in ('全部评分','未评分',*[f'{n} 星及以上' for n in range(1,6)],*[f'{n}星及以上' for n in range(1,6)]):raise ValueError('评分筛选条件不正确。')
        if result['download'] not in ('全部','已归档','待添加'):raise ValueError('全文筛选条件不正确。')
        if type(result['descending']) is not bool:raise ValueError('排序方向必须为布尔值。')
        for key in ('year_from','year_to'):
            if result[key] and (not str(result[key]).isdigit() or not 1000<=int(result[key])<=9999):raise ValueError('年份需要 4 位数字。')
        if result['year_from'] and result['year_to'] and int(result['year_from'])>int(result['year_to']):raise ValueError('开始年份不能晚于结束年份。')
        if result['sort_key'] not in (None,*values({},{})):raise ValueError('不支持的排序列。')
        if not isinstance(result['filters'],dict) or set(result['filters'])-set(values({},{})):raise ValueError('不支持的筛选列。')
        filters={}
        for key,criterion in result['filters'].items():
            if not isinstance(criterion,dict) or set(criterion)-{'values','contains'}:raise ValueError('列筛选条件格式不正确。')
            chosen=criterion.get('values',[]);query=criterion.get('contains','')
            if not isinstance(chosen,list) or len(chosen)>10000 or not all(isinstance(v,str) for v in chosen) or not isinstance(query,str):raise ValueError('列筛选值必须为文字列表。')
            filters[key]={'values':list(dict.fromkeys(chosen)),'contains':query}
        result['filters']=filters
        if not isinstance(result['columns'],(list,tuple)) or set(result['columns'])-set(values({},{})):raise ValueError('不支持的显示列。')
        result['columns']=list(dict.fromkeys(result['columns']))
        if result['columns'] and 'title' not in result['columns']:result['columns'].insert(0,'title')
        return result

    def views(self):
        return [dict(id=r['id'],name=r['name'],criteria=json.loads(r['data'])) for r in self.db.execute('SELECT * FROM workspace_views ORDER BY updated DESC')]

    def delete_view(self, view_id):
        with self.db:self.db.execute('DELETE FROM workspace_views WHERE id=?',(view_id,))

    def view_records(self, criteria):
        criteria=self.validate_view(criteria)
        records=self.library.records(criteria['project'],summary=True)
        projects={p['id']:p['name'] for p in self.library.projects()}
        rows={r['id']:values(r,projects) for r in records}
        table=TableState();table.filters=criteria['filters'];table.sort_key=criteria['sort_key'];table.descending=criteria['descending']
        return [r for r in table.ordered(records,rows) if self.matches(r,rows[r['id']],criteria,table)]

    @staticmethod
    def matches(r,row,c,table=None):
        if table and not table.matches(row):return False
        if str(c.get('query','')).casefold() not in ' '.join(str(r.get(k,'')) for k in ('title','display_name','doi','authors','keywords','tags')).casefold():return False
        if c.get('status','全部状态')!='全部状态' and r.get('status')!=c['status']:return False
        rating=c.get('rating','全部评分');score=r.get('rating',0)
        if rating=='未评分' and score:return False
        if '星及以上' in rating and score<int(rating[0]):return False
        if c.get('tag','全部标签')!='全部标签' and c['tag'] not in r.get('tags',[]):return False
        if c.get('download','全部')!='全部' and row['pdf']!=c['download']:return False
        for key,compare in (('year_from',lambda a,b:a>=b),('year_to',lambda a,b:a<=b)):
            if c.get(key) and (not str(r.get('year','')).isdigit() or not compare(int(r['year']),int(c[key]))):return False
        return True

    def question(self, project):
        self.library.project(project)
        row=self.db.execute('SELECT question FROM workspace_projects WHERE project=?',(project,)).fetchone()
        return row[0] if row else ''

    def set_question(self, project, text):
        self.library.project(project)
        if len(text)>20000:raise ValueError('研究问题最多 20000 字。')
        with self.db:self.db.execute('INSERT OR REPLACE INTO workspace_projects VALUES(?,?)',(project,text))

    def todos(self, project):
        return [dict(r) for r in self.db.execute('SELECT * FROM workspace_todos WHERE project=? ORDER BY done,due="",due,updated',(project,))]

    def save_todo(self, project, title, due='', todo_id=None, done=False):
        self.library.project(project);title=str(title).strip()
        if not title or len(title)>1000:raise ValueError('待办标题需要 1–1000 字。')
        if due:
            from datetime import date
            try:date.fromisoformat(due)
            except ValueError:raise ValueError('日期格式为 YYYY-MM-DD。') from None
        todo_id=todo_id or uuid.uuid4().hex
        existing=self.db.execute('SELECT project FROM workspace_todos WHERE id=?',(todo_id,)).fetchone()
        if existing and existing['project']!=project:raise ValueError('不能覆盖其他课题的待办。')
        with self.db:self.db.execute('INSERT OR REPLACE INTO workspace_todos VALUES(?,?,?,?,?,?)',(todo_id,project,title,int(bool(done)),due,time.time()))
        return todo_id

    def delete_todo(self, todo_id):
        with self.db:self.db.execute('DELETE FROM workspace_todos WHERE id=?',(todo_id,))

    def enqueue(self, project, papers):
        self.library.project(project)
        with self.db:
            if not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
            position=self.db.execute('SELECT COALESCE(MAX(position),0) FROM workspace_queue WHERE project=?',(project,)).fetchone()[0]
            for rid in papers:
                record=self.library.get(rid)
                if not set(record['projects']) & self.library.project_descendants(project):raise ValueError('阅读队列文献必须属于该课题或子课题。')
                position+=1
                self.db.execute('INSERT OR IGNORE INTO workspace_queue VALUES(?,?,?)',(project,rid,position))

    def queue(self, project):
        records={r['id']:r for r in self.library.records(project,summary=True)}
        return [records[r[0]] for r in self.db.execute('SELECT paper FROM workspace_queue WHERE project=? ORDER BY position,paper',(project,)) if r[0] in records]

    def dequeue(self, project, rid):
        with self.db:self.db.execute('DELETE FROM workspace_queue WHERE project=? AND paper=?',(project,rid))

    def export_project(self, project):
        scope=self.library.project_descendants(project)
        return {'schema':1,'projects':[{'project':pid,'question':self.question(pid),'todos':self.todos(pid),'queue':[r['id'] for r in self.queue(pid)]} for pid in sorted(scope)],
                'views':[v for v in self.views() if v['criteria'].get('project') in scope]}

    def import_project(self, payload, project_map, paper_map):
        if not isinstance(payload,dict) or payload.get('schema')!=1:raise ValueError('工作台交接格式不支持。')
        if not isinstance(payload.get('projects',[]),list) or not isinstance(payload.get('views',[]),list):raise ValueError('工作台交接列表不正确。')
        projects=[];views=[]
        for data in payload.get('projects',[]):
            pid=project_map.get(data['project'])
            if not pid:raise ValueError('工作台课题缺少交接映射。')
            self.library.project(pid);question=data.get('question','')
            if not isinstance(question,str) or len(question)>20000:raise ValueError('研究问题格式或长度不正确。')
            old=self.question(pid)
            if old and old!=question:raise ValueError('目标课题已有不同的研究问题，请导入新课题。')
            todos=[]
            for task in data.get('todos',[]):
                title=task.get('title','');due=task.get('due','');done=task.get('done',False)
                if not isinstance(title,str) or not title.strip() or len(title)>1000 or type(done) not in (bool,int) or done not in (0,1):raise ValueError('待办数据格式不正确。')
                if due:
                    from datetime import date
                    try:date.fromisoformat(due)
                    except (ValueError,TypeError):raise ValueError('待办日期格式不正确。') from None
                todos.append((uuid.uuid4().hex,pid,title.strip(),int(done),due,time.time()))
            queue=[];scope=self.library.project_descendants(pid)
            for rid in data.get('queue',[]):
                if rid not in paper_map:raise ValueError('阅读队列文献缺少交接映射。')
                target=paper_map[rid]
                if not set(self.library.get(target)['projects']) & scope:raise ValueError('交接阅读队列超出课题范围。')
                if target not in queue:queue.append(target)
            projects.append((pid,question,todos,queue))
        for view in payload.get('views',[]):
            criteria=dict(view['criteria']);source=criteria.get('project')
            if source not in project_map:raise ValueError('智能视图课题缺少交接映射，未扩大为全库。')
            criteria['project']=project_map[source];criteria=self.validate_view(criteria)
            name=view.get('name','')
            if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('智能视图名称格式不正确。')
            views.append((uuid.uuid4().hex,name.strip(),json.dumps(criteria,ensure_ascii=False),time.time()))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            for pid,question,todos,queue in projects:
                self.db.execute('INSERT OR REPLACE INTO workspace_projects VALUES(?,?)',(pid,question))
                self.db.executemany('INSERT INTO workspace_todos VALUES(?,?,?,?,?,?)',todos)
                position=self.db.execute('SELECT COALESCE(MAX(position),0) FROM workspace_queue WHERE project=?',(pid,)).fetchone()[0]
                self.db.executemany('INSERT OR IGNORE INTO workspace_queue VALUES(?,?,?)',[(pid,rid,position+i+1) for i,rid in enumerate(queue)])
            self.db.executemany('INSERT INTO workspace_views VALUES(?,?,?,?)',views)
