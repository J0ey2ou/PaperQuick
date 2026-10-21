"""Recover legacy false merges only when two local PDFs prove different full DOIs."""
import json,re,time,uuid
from pathlib import Path
from doi_identity import complete_doi


class ImportIdentity:
    def recover_import_identity(self, attachment, source):
        record=self.get(attachment['paper']);old_doi=record.get('doi','')
        truncated=bool(re.match(r'^10\.\d{4,9}/',old_doi) and not complete_doi(old_doi))
        if not (truncated or record.get('identity_recovered_from')) or attachment['role']=='primary':return None
        primary=self.primary_attachment(record['id'])
        if not primary or primary['id']==attachment['id'] or primary.get('kind')!='pdf':return None
        from library_core import pdf_metadata,FIELDS,digest
        try:
            incoming=pdf_metadata(source);original=pdf_metadata(self._managed_path(primary['path']))
        except (ValueError,OSError):return None
        if original.get('title')==Path(primary['path']).stem and primary.get('original'):
            original['title']=Path(primary['original']).stem
        if not complete_doi(incoming.get('doi')) or not complete_doi(original.get('doi')) or incoming['doi']==original['doi']:return None
        if digest(source)!=attachment['sha'] or digest(self._managed_path(primary['path']))!=primary['sha']:raise ValueError('归档原文已改变，请重新关联后再恢复文献身份。')
        rid=uuid.uuid4().hex;recovery=uuid.uuid4().hex
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            current=self.get(record['id'])
            row=self.db.execute('SELECT * FROM attachments WHERE id=?',(attachment['id'],)).fetchone()
            if not row or row['paper']!=record['id'] or row['role']=='primary':raise ValueError('导入条目已改变，请重试。')
            current_primary=self.primary_attachment(record['id'])
            if not current_primary or current_primary['id']!=primary['id'] or current_primary['sha']!=primary['sha']:raise ValueError('正文已改变，请重试。')
            # Store the exact previous data before changing only proven identity fields.
            backup={'original':self._snapshot(record['id']),'new_paper':rid,'moved_attachment':attachment['id'],'created':time.time()}
            self.db.execute('INSERT INTO config VALUES(?,?)',('identity-recovery:'+recovery,json.dumps(backup,ensure_ascii=False)))
            old_data=json.loads(self.db.execute('SELECT data FROM papers WHERE id=?',(record['id'],)).fetchone()[0])
            annotations=old_data.get('annotations',[])
            moved=[a for a in annotations if a.get('attachment')==attachment['id']]
            old_data['annotations']=[a for a in annotations if a.get('attachment')!=attachment['id']]
            old_data.update({k:original[k] for k in ('title','doi','year','text','references') if k in original})
            if original.get('authors'):old_data['authors']=original['authors']
            old_data['identity_recovered_from']=old_data.get('identity_recovered_from') or old_doi
            data=dict(incoming,annotations=moved,identity_recovery=recovery)
            for field in FIELDS:data.setdefault(field,'未读' if field=='status' else '')
            self.db.execute('INSERT INTO papers VALUES(?,?,?,?)',(rid,json.dumps(data,ensure_ascii=False),current['primary_project'],time.time()))
            self.db.execute("UPDATE attachments SET paper=?,role='primary' WHERE id=?",(rid,attachment['id']))
            self.db.execute('INSERT INTO memberships SELECT ?,project FROM memberships WHERE paper=?',(rid,record['id']))
            self.db.execute('UPDATE papers SET data=?,updated=? WHERE id=?',(json.dumps(old_data,ensure_ascii=False),time.time(),record['id']))
            self.log('recover-import-identity',{'recovery':recovery,'source_paper':record['id'],'new_paper':rid,'attachment':attachment['id']})
        return rid
