"""Generate fictional data for visual QA; never include the user's library."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_core import Library
from graph_view import write_graph
from pypdf import PdfWriter
base=Path(__file__).resolve().parents[1]
lib=Library(base/'build'/'demo-library')
if not lib.records():
    first=lib.create_project('队列与疾病预测');second=lib.create_project('蛋白结构与机制')
    titles=['Population cohort and cardiovascular risk prediction','Multimorbidity patterns in longitudinal population cohorts','Protein structure prediction and molecular mechanisms','Genetic determinants of protein structure variation','Clinical prediction using population health records','Molecular structure networks and disease mechanisms']
    for i,title in enumerate(titles):
        rid=lib.save({'title':title,'authors':'Demo Author','year':str(2021+i%4),'doi':f'10.9999/demo{i}',
                      'abstract':title+' health research prediction association structure mechanisms', 'status':'已读' if i%3==0 else '未读',
                      'text':f'References\n10.9999/demo{(i+1)%6}\n'},first if i in (0,1,4) else second)
        if i in (0,2,4):
            p=lib.root/f'demo-{i}.pdf';w=PdfWriter();w.add_blank_page(100,100);w.add_metadata({'/Title':title})
            with p.open('wb') as f:w.write(f)
            lib.attach(rid,p,extract=False)
    lib.assign(lib.records()[0]['id'],first)
source=lib.root/'reading-demo.pdf'
sys.path.insert(0,str(base/'tests'))
from test_reader import text_pdf
text_pdf(source)
rid=lib.save({'title':'Local literature reading demo','authors':'Demo Researcher','year':'2026','doi':'10.9999/reading-demo',
              'abstract':'A fictional document for demonstrating local PDF reading, notes, references and graph candidates.'},first if not lib.records() else lib.projects()[1]['id'])
lib.attach(rid,source,extract=True)
write_graph(lib,destination=base/'build'/'demo-graph.html');lib.close()
print('Fictional demo graph generated.')
