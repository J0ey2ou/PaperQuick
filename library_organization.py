"""Tags, nested projects and reversible automatic memberships in the local library."""
import re

READING_STATES = ('未读', '在读', '已读', '待读', '搁置')


def normalize_tags(value):
    parts = re.split(r'[;,；，、\n]+', value) if isinstance(value, str) else list(value or [])
    result = []
    for part in parts:
        tag = re.sub(r'\s+', ' ', str(part)).strip()
        if len(tag) > 60:
            raise ValueError('每个标签最多 60 字。')
        if tag and tag.casefold() not in {t.casefold() for t in result}:
            result.append(tag)
    if len(result) > 50:
        raise ValueError('每篇文献最多设置 50 个标签。')
    return result


class LibraryOrganization:
    def all_tags(self):
        tags = {}
        for record in self.records():
            for tag in record.get('tags',[]):tags.setdefault(tag.casefold(),tag)
        for row in self.db.execute('SELECT tag FROM project_tag_rules'):
            tags.setdefault(row[0].casefold(),row[0])
        return sorted(tags.values(),key=str.casefold)

    def change_tag(self, old, new=None):
        """Rename/merge or delete a tag and its automatic project rules atomically."""
        old_tags=normalize_tags([old]);new_tags=normalize_tags([new]) if new is not None else []
        if not old_tags or (new is not None and not new_tags):raise ValueError('请填写标签名称。')
        key=old_tags[0].casefold();replacement=new_tags[0] if new_tags else None
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            projects=[r[0] for r in self.db.execute('SELECT project FROM project_tag_rules WHERE tag=?',(key,))]
            self.db.execute('DELETE FROM project_tag_rules WHERE tag=?',(key,))
            if replacement:
                self.db.executemany('INSERT OR IGNORE INTO project_tag_rules VALUES(?,?)',[(pid,replacement.casefold()) for pid in projects])
            changed=0
            for record in self.records():
                tags=record.get('tags',[])
                if any(t.casefold()==key for t in tags):
                    tags=normalize_tags([replacement if t.casefold()==key else t for t in tags if t.casefold()!=key or replacement])
                    import json,time
                    row=self.db.execute('SELECT data FROM papers WHERE id=?',(record['id'],)).fetchone()
                    data=json.loads(row[0]);data['tags']=tags
                    self.db.execute('UPDATE papers SET data=?,updated=? WHERE id=?',(json.dumps(data,ensure_ascii=False),time.time(),record['id']))
                    changed+=1
                self.sync_tag_memberships(record['id'],tags,record['primary_project'])
            self.log('change-tag',{'old':old,'new':replacement,'count':changed})
        return changed

    def organization_schema(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if 'parent' not in {r['name'] for r in self.db.execute('PRAGMA table_info(projects)')}:
                self.db.execute("ALTER TABLE projects ADD COLUMN parent TEXT NOT NULL DEFAULT ''")
            self.db.execute('CREATE TABLE IF NOT EXISTS project_tag_rules(project TEXT,tag TEXT,PRIMARY KEY(project,tag))')
            self.db.execute('CREATE TABLE IF NOT EXISTS tag_memberships(paper TEXT,project TEXT,PRIMARY KEY(paper,project))')

    def project_descendants(self, pid):
        self.project(pid)
        children = {}
        for project in self.projects():
            children.setdefault(project.get('parent', ''), []).append(project['id'])
        found, pending = set(), [pid]
        while pending:
            node = pending.pop()
            if node in found:
                continue
            found.add(node); pending.extend(children.get(node, []))
        return found

    def project_rules(self, pid):
        self.project(pid)
        return [r[0] for r in self.db.execute('SELECT tag FROM project_tag_rules WHERE project=? ORDER BY rowid', (pid,))]

    def set_project_rules(self, pid, tags):
        self.project(pid); tags = normalize_tags(tags)
        with self.db:
            self.db.execute('DELETE FROM project_tag_rules WHERE project=?', (pid,))
            self.db.executemany('INSERT INTO project_tag_rules VALUES(?,?)', [(pid, t.casefold()) for t in tags])
            for row in self.db.execute('SELECT id,data,primary_project FROM papers').fetchall():
                import json
                self.sync_tag_memberships(row['id'], json.loads(row['data']).get('tags', []), row['primary_project'])

    def sync_tag_memberships(self, rid, tags, primary):
        keys = {t.casefold() for t in normalize_tags(tags)}
        desired = {row['project'] for row in self.db.execute('SELECT * FROM project_tag_rules') if row['tag'] in keys}
        tracked = {row[0] for row in self.db.execute('SELECT project FROM tag_memberships WHERE paper=?', (rid,))}
        for pid in tracked - desired:
            if pid != primary:
                self.db.execute('DELETE FROM memberships WHERE paper=? AND project=?', (rid, pid))
            self.db.execute('DELETE FROM tag_memberships WHERE paper=? AND project=?', (rid, pid))
        for pid in desired:
            if not self.db.execute('SELECT 1 FROM memberships WHERE paper=? AND project=?', (rid, pid)).fetchone():
                self.db.execute('INSERT INTO memberships VALUES(?,?)', (rid, pid))
                self.db.execute('INSERT OR IGNORE INTO tag_memberships VALUES(?,?)', (rid, pid))

    def document_location(self, rid, original=False):
        """Resolve only an existing local main document; a link is never a path."""
        attachment = self.primary_attachment(rid)
        if not attachment:
            raise ValueError('这篇文献还没有已下载的正文。')
        path = self._managed_path(attachment['path'])
        if original:
            from pathlib import Path
            path = Path(attachment.get('original') or '')
        if not path.is_file():
            raise ValueError('文件已不在原位置，请重新关联正文。')
        return path.resolve()
