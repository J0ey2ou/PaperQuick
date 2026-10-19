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
        'checks':['single-row reader and comparison','toolbar icons bundled','automatic settings persistence','existing library and unknown preferences retained','Word helpers present','ChatGPT bridge bundled without browser launch','cross-page document crop contains both pages'],
        'background_only':True},ensure_ascii=False,indent=2),'utf-8')
