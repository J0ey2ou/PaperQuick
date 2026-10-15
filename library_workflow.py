"""Durable import undo, recoverable removal, and explicit document relationships."""
from pathlib import Path
import json
import shutil
import time
import uuid


class LibraryWorkflow:
    def workflow_schema(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS import_batches(id TEXT PRIMARY KEY,at REAL,project TEXT,state TEXT,data TEXT);
        CREATE TABLE IF NOT EXISTS paper_trash(id TEXT PRIMARY KEY,at REAL,state TEXT,data TEXT);
        CREATE TABLE IF NOT EXISTS paper_relations(id TEXT PRIMARY KEY,source TEXT,target TEXT,label TEXT,created REAL,UNIQUE(source,target,label));
        CREATE TABLE IF NOT EXISTS graph_groups(id TEXT PRIMARY KEY,label TEXT NOT NULL,shape TEXT NOT NULL,created REAL);
        CREATE TABLE IF NOT EXISTS graph_group_members(group_id TEXT,paper TEXT,PRIMARY KEY(group_id,paper));
        ''')
        self.db.commit()

    def _snapshot(self, rid):
        row=self.db.execute('SELECT * FROM papers WHERE id=?',(rid,)).fetchone()
        if not row:return None
        return {'paper':dict(row),'memberships':[dict(r) for r in self.db.execute('SELECT * FROM memberships WHERE paper=?',(rid,))],
                'attachments':[dict(r) for r in self.db.execute('SELECT * FROM attachments WHERE paper=?',(rid,))]}

    def import_batch(self, paths, project):
        """Journal each selected file; undo never overwrites subsequently edited papers."""
        self.project(project)
        batch=uuid.uuid4().hex;entries=[];errors=[]
        with self.db:self.db.execute('INSERT INTO import_batches VALUES(?,?,?,?,?)',(batch,time.time(),project,'running','[]'))
        before={r['id']:self._snapshot(r['id']) for r in self.db.execute('SELECT id FROM papers')}
        for path in paths:
            try:
                rid=self.import_document(path,project)
                after=self._snapshot(rid);entries.append({'source':str(path),'id':rid,'before':before.get(rid),'after':after});before[rid]=after
            except Exception as exc:
                errors.append(f'{Path(path).name}：{exc}')
                # A failed file may have created a metadata-only entry; journal it too.
                for row in self.db.execute('SELECT id FROM papers').fetchall():
                    if row['id'] not in before:
                        after=self._snapshot(row['id']);entries.append({'source':str(path),'id':row['id'],'before':None,'after':after});before[row['id']]=after
                    else:
                        after=self._snapshot(row['id'])
                        if after!=before[row['id']]:entries.append({'source':str(path),'id':row['id'],'before':before[row['id']],'after':after});before[row['id']]=after
            with self.db:self.db.execute('UPDATE import_batches SET data=? WHERE id=?',(json.dumps(entries,ensure_ascii=False),batch))
        with self.db:self.db.execute("UPDATE import_batches SET state='ready' WHERE id=?",(batch,))
        return {'batch':batch,'count':len(paths)-len(errors),'errors':errors}

    def latest_import(self):
        row=self.db.execute("SELECT * FROM import_batches WHERE state IN ('ready','running') ORDER BY at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def _managed_path(self, relative):
        path=(self.root/relative).resolve()
        if not path.is_relative_to(self.root) or path==self.root:raise ValueError('文件位置不在文献库中。')
        return path

    def _move_to_trash(self, attachments, token):
        moved=[]
        try:
            for a in attachments:
                if a.get('kind')=='link':continue
                source=self._managed_path(a['path'])
                if not source.is_file():continue
                target=self._managed_path('trash/'+token+'/'+a['path']);target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():raise ValueError('恢复区中已有同名文件，请重新操作。')
                source.rename(target);moved.append((source,target))
        except Exception:
            self._restore_moves(moved);raise
        return moved

    @staticmethod
    def _restore_moves(moved):
        for source,target in reversed(moved):
            source.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and not source.exists():target.rename(source)

    def undo_import(self, batch=None):
        row=self.db.execute('SELECT * FROM import_batches WHERE id=?',(batch,)).fetchone() if batch else self.latest_import()
        if not row or row['state'] not in ('ready','running'):raise ValueError('没有可以撤回的导入记录。')
        entries=json.loads(row['data']);restored=0;kept=set()
        # Repeated imports of the same paper are reversed in file order.
        for entry in reversed(entries):
            rid=entry['id'];current=self._snapshot(rid)
            if rid in kept:continue
            if current is None:continue
            comparable=lambda x:{k:v for k,v in x.items() if k!='paper'}|{'paper':{k:v for k,v in x['paper'].items() if k!='updated'}}
            from library_core import digest
            files_changed=any(a.get('sha') and self._managed_path(a['path']).is_file() and digest(self._managed_path(a['path']))!=a['sha'] for a in current['attachments'])
            if comparable(current)!=comparable(entry['after']) or files_changed:kept.add(rid);continue
            old=entry['before'];old_ids={a['id'] for a in (old or {}).get('attachments',[])}
            added=[a for a in current['attachments'] if a['id'] not in old_ids]
            moved=self._move_to_trash(added,'import-'+row['id']+'-'+uuid.uuid4().hex[:8])
            try:
                with self.db:
                    self.db.execute('DELETE FROM attachments WHERE paper=?',(rid,));self.db.execute('DELETE FROM memberships WHERE paper=?',(rid,))
                    if old:
                        p=old['paper'];self.db.execute('UPDATE papers SET data=?,primary_project=?,updated=? WHERE id=?',(p['data'],p['primary_project'],time.time(),rid))
                        for a in old['attachments']:self._insert_row('attachments',a)
                        for m in old['memberships']:self._insert_row('memberships',m)
                    else:
                        self.db.execute('DELETE FROM papers WHERE id=?',(rid,));self.db.execute('DELETE FROM sync_map WHERE paper=?',(rid,))
                    self.log('undo-import',{'batch':row['id'],'paper':rid})
            except Exception:self._restore_moves(moved);raise
            restored+=1
        with self.db:self.db.execute("UPDATE import_batches SET state='undone' WHERE id=?",(row['id'],))
        return {'restored':restored,'kept':len(kept)}

    def _insert_row(self, table, row):
        row=dict(row)
        if table=='reading_sessions' and self.db.execute('SELECT 1 FROM reading_sessions WHERE id=?',(row['id'],)).fetchone():row.pop('id')
        if table=='sync_map' and self.db.execute('SELECT 1 FROM sync_map WHERE source=? AND external_id=?',(row['source'],row['external_id'])).fetchone():return
        keys=list(row);self.db.execute('INSERT INTO '+table+' ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')',tuple(row[k] for k in keys))

    def remove_papers(self, ids):
        token=uuid.uuid4().hex;items=[]
        for rid in dict.fromkeys(ids):
            item=self._snapshot(rid)
            if not item:continue
            item['sessions']=[dict(r) for r in self.db.execute('SELECT * FROM reading_sessions WHERE paper=?',(rid,))]
            item['sync']=[dict(r) for r in self.db.execute('SELECT * FROM sync_map WHERE paper=?',(rid,))]
            item['relations']=[dict(r) for r in self.db.execute('SELECT * FROM paper_relations WHERE source=? OR target=?',(rid,rid))]
            items.append(item)
        moved=self._move_to_trash([a for x in items for a in x['attachments']],token)
        try:
            with self.db:
                self.db.execute('INSERT INTO paper_trash VALUES(?,?,?,?)',(token,time.time(),'removed',json.dumps(items,ensure_ascii=False)))
                for x in items:
                    rid=x['paper']['id']
                    for table in ('attachments','memberships','sync_map','reading_sessions'):self.db.execute('DELETE FROM '+table+' WHERE paper=?',(rid,))
                    self.db.execute('DELETE FROM paper_relations WHERE source=? OR target=?',(rid,rid));self.db.execute('DELETE FROM papers WHERE id=?',(rid,))
                self.log('remove-papers',{'trash':token,'papers':[x['paper']['id'] for x in items]})
        except Exception:self._restore_moves(moved);raise
        return len(items)

    def restore_removed(self):
        row=self.db.execute("SELECT * FROM paper_trash WHERE state='removed' ORDER BY at DESC LIMIT 1").fetchone()
        if not row:raise ValueError('没有待恢复的文献。')
        items=json.loads(row['data']);moved=[]
        try:
            for x in items:
                if self._snapshot(x['paper']['id']):raise ValueError('文献已存在，不能重复恢复。')
                for a in x['attachments']:
                    if a.get('kind')=='link':continue
                    target=self._managed_path(a['path']);source=self._managed_path('trash/'+row['id']+'/'+a['path'])
                    if not source.exists():continue
                    if target.exists():raise ValueError('原位置有同名文件，尚未恢复。请先为该文件改名。')
                    target.parent.mkdir(parents=True,exist_ok=True);source.rename(target);moved.append((target,source))
            with self.db:
                for x in items:
                    self._insert_row('papers',x['paper'])
                    for table,key in [('memberships','memberships'),('attachments','attachments'),('reading_sessions','sessions'),('sync_map','sync')]:
                        for data in x[key]:self._insert_row(table,data)
                    for data in x['relations']:
                        if not self.db.execute('SELECT 1 FROM paper_relations WHERE id=?',(data['id'],)).fetchone():self._insert_row('paper_relations',data)
                self.db.execute("UPDATE paper_trash SET state='restored' WHERE id=?",(row['id'],))
        except Exception:self._restore_moves(moved);raise
        return len(items)

    def relate(self, source, target, label='相关文献'):
        self.get(source);self.get(target)
        if source==target:raise ValueError('请选择另一篇文献。')
        label=str(label).strip()
        if not label or len(label)>160:raise ValueError('请填写 1–160 字的关联原因。')
        with self.db:
            existing=self.db.execute('SELECT id FROM paper_relations WHERE ((source=? AND target=?) OR (source=? AND target=?)) AND label=?',(source,target,target,source,label)).fetchone()
            if not existing:self.db.execute('INSERT INTO paper_relations VALUES(?,?,?,?,?)',(uuid.uuid4().hex,source,target,label,time.time()))
        return target

    def relation_edges(self, ids):
        return [{'source':r['source'],'target':r['target'],'kind':'related','weight':1,'label':r['label']} for r in self.db.execute('SELECT * FROM paper_relations') if r['source'] in ids and r['target'] in ids]

    def create_graph_group(self, papers, label, shape='rectangle'):
        papers=list(dict.fromkeys(papers));label=str(label).strip()
        if len(papers)<2:raise ValueError('请至少选中两篇已入库文献。')
        if not label or len(label)>160:raise ValueError('请填写 1–160 字的关联原因。')
        if shape not in ('rectangle','ellipse'):raise ValueError('请选择框选或圈选。')
        for rid in papers:self.get(rid)
        gid=uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO graph_groups VALUES(?,?,?,?)',(gid,label,shape,time.time()))
            self.db.executemany('INSERT INTO graph_group_members VALUES(?,?)',[(gid,rid) for rid in papers])
        return gid

    def graph_groups(self, ids=None):
        result=[]
        for row in self.db.execute('SELECT * FROM graph_groups ORDER BY created'):
            group=dict(row)
            members=[r[0] for r in self.db.execute('SELECT m.paper FROM graph_group_members m JOIN papers p ON p.id=m.paper WHERE m.group_id=?',(row['id'],))]
            group['members']=[rid for rid in members if ids is None or rid in ids]
            if group['members']:result.append(group)
        return result

    def rename_graph_group(self, gid, label):
        label=str(label).strip()
        if not label or len(label)>160:raise ValueError('请填写 1–160 字的关联原因。')
        with self.db:self.db.execute('UPDATE graph_groups SET label=? WHERE id=?',(label,gid))

    def remove_graph_group(self,gid):
        with self.db:
            self.db.execute('DELETE FROM graph_group_members WHERE group_id=?',(gid,))
            self.db.execute('DELETE FROM graph_groups WHERE id=?',(gid,))

    def replace_document(self, rid, aid, staged, expected_sha):
        from library_core import digest,document_metadata
        record=self.get(rid);a=next(a for a in record['attachments'] if a['id']==aid)
        target=self._managed_path(a['path']);staged=Path(staged).resolve()
        if digest(target)!=expected_sha:raise ValueError('文件已经更新，请重新打开后编辑。')
        metadata=document_metadata(staged);backup=self._managed_path('versions/'+aid+'/'+uuid.uuid4().hex+target.suffix)
        backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,backup)
        temporary=target.with_name('.editing-'+uuid.uuid4().hex+target.suffix)
        try:
            shutil.copy2(staged,temporary);temporary.replace(target)
            with self.db:
                self.db.execute('UPDATE attachments SET sha=? WHERE id=?',(digest(target),aid))
                if a['role']=='primary':
                    data=json.loads(self.db.execute('SELECT data FROM papers WHERE id=?',(rid,)).fetchone()[0]);data.update(text=metadata.get('text',''),references=metadata.get('references',[]))
                    self.db.execute('UPDATE papers SET data=?,updated=? WHERE id=?',(json.dumps(data,ensure_ascii=False),time.time(),rid))
                self.log('edit-document',{'paper':rid,'attachment':aid,'backup':str(backup.relative_to(self.root))})
        except Exception:
            shutil.copy2(backup,target);raise
        finally:temporary.unlink(missing_ok=True)
        return target
