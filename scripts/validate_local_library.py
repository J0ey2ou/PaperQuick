"""Use a user-selected source read-only; all writes stay in workspace test copies."""
import json
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_core import Library,digest
import endnote_sync
from graph_view import write_graph

base=Path(__file__).resolve().parents[1]
source=Path(sys.argv[1]).resolve()
report_dir=base/'build'/'endnote-validation';report_dir.mkdir(parents=True,exist_ok=True)
before={str(p.relative_to(source.parent)):digest(p) for p in [source,*source.with_suffix('.Data').rglob('*')] if p.is_file()}
copy=report_dir/'Validation.enl'
if not copy.exists():endnote_sync.copy_pair(source,copy)
lib=Library(report_dir/'isolated-library')
pid=lib.create_project('Validation import')
start=time.monotonic();plan=endnote_sync.preview(lib,copy)
imported=endnote_sync.import_only(lib,plan,pid)
remote,_=endnote_sync.read_library(copy)
for mapping in lib.db.execute('SELECT external_id,paper FROM sync_map WHERE source=?',(str(copy.resolve()),)).fetchall():
    lib.save({'doi':remote[mapping['external_id']]['doi']},rid=mapping['paper'])
lib.set_setting('endnote_source',str(copy))
records=lib.records();report={'source_records':len(endnote_sync.read_library(source)[0]),'local_records':len(records),'imported_now':imported,'local_pdfs':sum(len(r['attachments']) for r in records),'import_seconds':round(time.monotonic()-start,2)}
# Validate offline exchange without writing proprietary EndNote indices.
plan=endnote_sync.preview(lib,copy)
choices={(e['external_id'],field):'local' for e in plan['entries'] for field in e['conflicts']}
out=report_dir/('Exchange-'+str(int(time.time())))
endnote_sync.export_exchange(lib,plan,out,choices)
tree=ET.parse(out/'完整文献库.xml')
assert len(tree.findall('.//record'))==report['source_records']
assert len(tree.findall('.//pdf-urls/url'))==report['local_pdfs']
report['exchange_records']=len(tree.findall('.//record'));report['exchange_pdfs']=report['local_pdfs'];report['exchange_package']=str(out)
write_graph(lib);report['graph']=lib.graph()['summary'];lib.close()
after={str(p.relative_to(source.parent)):digest(p) for p in [source,*source.with_suffix('.Data').rglob('*')] if p.is_file()}
assert before==after;report['source_pair_unchanged']=True
(report_dir/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps(report,ensure_ascii=True,indent=2))
