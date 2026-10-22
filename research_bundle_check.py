"""Disposable, hidden research-workspace verification in the frozen executable."""
from pathlib import Path
import tkinter as tk
from unittest.mock import patch


def run(instance,folder):
    from library_core import Library
    from fulltext_index import FulltextIndex
    from workspace_state import WorkspaceStore
    from research_store import ResearchStore
    from reading_resume import ReadingResumeStore
    from library_backup import create_backup,restore_backup
    from project_handoff import export_project_handoff,inspect_project_handoff,import_project_handoff
    from project_ai import retrieve_sources,validate_answer
    import json
    folder=Path(folder);directory=instance.library_directory
    library=Library(directory)
    try:
        project=library.create_project('Frozen research workflow')
        source=folder/'research.txt';source.write_text('Evidence reveals measurable treatment improvement.\n\nMore trials are needed.',encoding='utf-8')
        paper=library.import_document(source,project);attachment=library.primary_attachment(paper)
    finally:library.close()
    store=WorkspaceStore(directory)
    try:
        store.set_question(project,'What improves treatment outcomes?')
        store.save_todo(project,'Verify original sources');store.enqueue(project,[paper])
        store.save_view('Frozen smart view',{'project':project,'columns':['title','year']})
        assert len(store.view_records(store.views()[0]['criteria']))==1
    finally:store.close()
    FulltextIndex(directory).update(project=project)
    hits=FulltextIndex(directory).search('treatment',project=project)
    assert hits and hits[0]['locator_kind']=='paragraph' and hits[0]['page'] is None
    sources=retrieve_sources(directory,'treatment',project,[paper])
    response=json.dumps({'answer':'Treatment improved [S1].','citations':[{'id':'S1','quote':'measurable treatment improvement'}]})
    assert validate_answer(response,sources)['claims_verified'] is False
    store=ResearchStore(directory)
    try:
        card=store.save_card({'project':project,'paper':paper,'attachment':attachment['id'],'quote':'measurable treatment improvement','interpretation':'Needs critical review','verified':False})
        store.save_section({'project':project,'title':'Evidence summary','body':'Review draft','evidence':[card['id']]})
        store.save_decision(project,paper,'title_abstract','include')
    finally:store.close()
    ReadingResumeStore(directory).save(paper,attachment['id'],page=0,scale=1.3,logical=True,paragraph=1)
    assert ReadingResumeStore(directory).last()['paragraph']==1
    backup=folder/'frozen-research-backup.zip';create_backup(directory,backup);restore_backup(backup,folder/'restored-research')
    bundle=folder/'frozen-research-handoff.zip';export_project_handoff(directory,project,bundle)
    assert inspect_project_handoff(bundle)['papers']==1
    result=import_project_handoff(bundle,folder/'handoff-research');assert paper in result['paper_map']
    original=tk.Toplevel.__init__
    def hidden(window,*args,**kwargs):original(window,*args,**kwargs);window.withdraw()
    with patch.object(tk.Toplevel,'__init__',hidden):
        instance.show_page('workspace');assert instance.workspace_page.store.question(project)
        windows=[instance.open_fulltext(project),instance.open_research(project),instance.open_project_ai(project),instance.open_handoff(project),instance.open_maintenance()]
        instance.root.update_idletasks()
        assert all(not w.win.winfo_ismapped() for w in windows)
        for window in windows:window.close()
    return ['smart views and project workbench','page/paragraph fulltext index','citation verification without API requests',
            'evidence and outline persistence','reading session restore','complete backup/restore','project handoff roundtrip','hidden research windows']
