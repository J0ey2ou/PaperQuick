"""Frozen-build verification using only withdrawn windows and disposable data."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch


def run(root,report):
    root.withdraw()
    import app
    from app_version import VERSION,PROJECT_URL
    from library_core import Library
    from preferences import load_preferences,save_preferences
    from attachment_ui import AttachmentPreview
    from document_conversion import converter_path
    from word_bridge import bridge_path
    import sys
    report=Path(report)
    with tempfile.TemporaryDirectory(dir=report.parent) as temp:
        folder=Path(temp)
        save_preferences(folder/'settings.json',{'preserved_option':True})
        lib=Library(folder/'本地文献库');rid=lib.save({'title':'Upgrade fixture','notes':'Retained notes'});lib.close()
        with patch('app.app_dir',return_value=folder),patch('ui_theme.window_chrome'),patch('desktop_runtime.startup_enabled',return_value=False),patch.object(app.App,'start_selection_helper') as helper,patch('webbrowser.open') as browser:
            instance=app.App(root);instance.settings()
            instance.settings_vars['skin'].set('极简浅色');instance.settings_vars['marker_size'].set('26')
            instance.settings_template.delete('1.0','end');instance.settings_template.insert('1.0','Saved template')
            instance.show_page('reader');root.update_idletasks()
            labels={item['label'] for item in instance.reader_page.toolbar.items}
            assert {'截图到笔记','框选图片供 ChatGPT 讨论','保存笔记','嵌入参考文献'}<=labels
            assert instance.reader_page.toolbar.winfo_reqheight()==40
            preview=AttachmentPreview(instance.reader_page.frame,folder/'本地文献库',lambda:None)
            assert len(preview.toolbar.items)==7;preview.close()
            assert load_preferences(folder/'settings.json')['skin']=='极简浅色'
            assert load_preferences(folder/'settings.json')['preserved_option']
            lib=Library(folder/'本地文献库')
            assert lib.setting('reader_marker_size')==26 and lib.setting('research_note_template')=='Saved template'
            assert lib.get(rid)['notes']=='Retained notes';lib.close()
            lib=Library(folder/'本地文献库')
            try:
                parent=lib.create_project('Research');child=lib.create_project('Methods',parent)
                lib.set_project_rules(child,'method');lib.save({'tags':['method'],'rating':5},rid=rid)
                assert lib.records(parent)[0]['id']==rid and lib.get(rid)['rating']==5
            finally:lib.close()
            assert instance.updater.status.get()
            from chat_prompt_ui import render_chat_prompt,DEFAULT_CHAT_PROMPT
            assert '《Fixture》' in render_chat_prompt(DEFAULT_CHAT_PROMPT,{'title':'Fixture'})
            from word_citations import plan_changes
            from citation_styles import format_document
            operations,formatted=plan_changes({'fields':[],'selection':{'start':0,'end':0}},[{'id':'citation-fixture','title':'Fictional research','authors':'Alice Smith','year':'2025'}],'apa','insert',[{'id':'citation-fixture','title':'Fictional research','authors':'Alice Smith','year':'2025'}],locator='2–3')
            assert operations['append_bibliography']['kind']=='bibliography' and 'Fictional research' in formatted['plain_bibliography']
            from chat_bridge import ChatBridge
            source=folder/'fixture.txt';source.write_text('Isolated ChatGPT bridge fixture',encoding='utf-8')
            lib=Library(folder/'本地文献库')
            try:chat_rid=lib.import_document(source)
            finally:lib.close()
            bridge=ChatBridge(folder/'本地文献库')
            try:
                url=bridge.prepare(chat_rid,quote='Selected fixture text')
                token=url.split('#paperquick=')[1].split('.',1)[1]
                assert len(bridge.payload(token)['files'])==1
                assert bridge.open_url(url).startswith('http://127.0.0.1:')
                assert b'paperquick-handoff' in bridge.connection_page(token)
            finally:bridge.close()
            # Exercise the installed worker/UI import path, including failures and
            # repeated imports. An exception must not silently stop queue polling.
            instance.open_library();library_window=instance.library_window
            valid=folder/'worker.txt';valid.write_text('Frozen worker import fixture','utf-8')
            invalid=folder/'bad.pdf';invalid.write_text('<html>not a PDF</html>','utf-8')
            import time
            with patch.object(library_window,'chat_full_paper'),patch('library_ui.messagebox.showwarning'):
                pid=library_window.library.projects()[0]['id']
                for selected_files in ([invalid,valid],[valid]):
                    library_window.batch_import(selected_files,pid)
                    deadline=time.monotonic()+12
                    while library_window.busy and time.monotonic()<deadline:root.update();time.sleep(.02)
                    assert not library_window.busy
                    assert library_window.tree.selection()
                imported=library_window.library.get(library_window.tree.selection()[0])
                assert imported['attachments']
            reader=instance.reader_page
            reader.events.put(('open',0,imported['id']));reader.poll()
            assert library_window.tree.exists(imported['id'])
            # Frozen imports must discover the PDF export/link and tag modules.
            from annotation_export import export_pdf
            from document_links import destination
            from tag_ui import tag_picker
            assert callable(export_pdf) and callable(destination) and callable(tag_picker)
            from doi_identity import extract_document_doi
            assert extract_document_doi('','doi:10.1136/bmjopen-2012-\n002007')=='10.1136/bmjopen-2012-002007'
            assert callable(library_window.library.recover_import_identity)
            assert callable(instance.reader_page.document_canvas.control_wheel)
            assert callable(ChatBridge.require_document_upload)
            native=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'embedded-browser'
            assert (native/'EmbeddedChat.exe').is_file() and (native/'WebView2Loader.dll').is_file()
            assert (native.parent/'browser-extension/chat-content.js').is_file() and (native.parent/'browser-extension/ai-web-content.js').is_file()
            assert all(instance.library_window.tree.heading(k,'command') for k in instance.library_window.tree['columns'])
            from ai_reading import context_prompt,protect_secret,load_profile,AIHistory
            from ai_providers import PROVIDERS,api_endpoint
            from ai_reading_ui import AISettings
            assert set(('chatgpt','doubao','deepseek','gemini','qwen','kimi'))<=set(PROVIDERS)
            assert instance.reader_page.ai_panel.frame in [instance.reader_page.notebook.nametowidget(p) for p in instance.reader_page.notebook.tabs()]
            assert '第 2 页' in context_prompt('Fixture','selected','Explain',1)
            protected=protect_secret('frozen-fixture');assert protect_secret(protected,True)=='frozen-fixture'
            assert api_endpoint(load_profile(folder/'本地文献库','deepseek')['endpoint']).endswith('/chat/completions')
            from pypdf import PdfWriter
            from pypdf.generic import DecodedStreamObject,NameObject
            writer=PdfWriter()
            for color in (b'1 0 0',b'0 0 1'):
                page=writer.add_blank_page(300,400);stream=DecodedStreamObject()
                stream.set_data(color+b' rg 0 0 300 400 re f')
                page[NameObject('/Contents')]=writer._add_object(stream)
            pdf=folder/'pages.pdf'
            with pdf.open('wb') as stream:writer.write(stream)
            reader=instance.reader_page;reader.path=pdf;reader.scale=1
            reader.document_canvas.layout={0:(18,18,300,400),1:(18,460,300,400)}
            selected={'regions':[{'page':0,'rect':[0,0,.5,.5]},{'page':1,'rect':[0,0,.5,.5]}]}
            combined=reader.document_canvas.selection_image(selected)
            assert combined.size==(150,416)
            assert combined.getpixel((20,20))==(255,0,0)
            assert combined.getpixel((20,400))==(0,0,255)
            helper.assert_not_called();browser.assert_not_called()
            assert converter_path().is_file() and bridge_path().is_file()
            instance.close()
    report.write_text(json.dumps({'passed':True,'version':VERSION,'project':PROJECT_URL,'frozen':bool(getattr(sys,'frozen',False)),
        'checks':['single-row reader and comparison','toolbar icons bundled','automatic settings persistence','existing library and unknown preferences retained','Word helpers present','ChatGPT bridge bundled without browser launch','cross-page document crop contains both pages','tags and nested projects','ratings persisted','whole-paper prompt template','Word CSL citation and automatic bibliography plan','settings updater bundled'],
        'background_only':True},ensure_ascii=False,indent=2),'utf-8')
