"""Import/reply/link regressions in disposable libraries and withdrawn widgets."""
import json
from pathlib import Path
import tempfile,time,tkinter as tk,unittest
from unittest.mock import patch,Mock
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
from library_core import Library
from chat_bridge import ChatBridge,REPLY_TTL
from document_links import destination
from test_library import pdf
from test_library_documents import docx


class ResearchWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.lib=Library(self.base/'store');self.pid=self.lib.create_project('Research')
        self.source=self.base/'研究 paper.pdf';pdf(self.source)
    def tearDown(self):self.lib.close();self.temp.cleanup()

    def test_mixed_import_errors_duplicate_retries_and_journal(self):
        bad=self.base/'broken.pdf';bad.write_text('<html>Download login required</html>')
        word=self.base/'Word.docx';docx(word)
        txt=self.base/'笔记.txt';txt.write_text('Temporary fixture','utf-8')
        result=self.lib.import_batch([bad,self.source,word,txt,self.source],self.pid)
        self.assertEqual(result['count'],4);self.assertEqual(len(result['errors']),1)
        self.assertEqual(len(result['paper_ids']),3)
        self.assertEqual([d['state'] for d in result['details']],['error','imported','imported','imported','linked'])
        self.assertEqual(self.lib.setting('last_import_report')['files'][0]['state'],'error')
        again=self.lib.import_batch([self.source],self.pid)
        self.assertEqual(again['count'],1);self.assertEqual(len(self.lib.records()),3)
        # Original batch undo preserves repeated-file ordering and new Word/TXT imports.
        self.lib.undo_import(result['batch']);self.assertFalse(self.lib.records())

    def test_tag_rename_merge_and_delete_include_rules(self):
        rid=self.lib.import_pdf(self.source);other=self.lib.create_project('Tagged')
        self.lib.set_project_rules(other,'old');self.lib.save({'tags':['Old','keep']},rid=rid)
        self.assertIn(other,self.lib.get(rid)['projects'])
        self.lib.change_tag('OLD','keep')
        self.assertEqual(self.lib.get(rid)['tags'],['keep']);self.assertEqual(self.lib.project_rules(other),['keep'])
        self.lib.change_tag('keep')
        self.assertEqual(self.lib.all_tags(),[]);self.assertNotIn(other,self.lib.get(rid)['projects'])
        self.lib.assign(rid,other);self.lib.save({'tags':['manual']},rid=rid)
        self.lib.set_project_rules(other,'manual');self.lib.change_tag('manual')
        self.assertIn(other,self.lib.get(rid)['projects'])

    def test_reply_http_scoped_deduplicated_and_preserves_local_edits(self):
        rid=self.lib.import_pdf(self.source);attachment=self.lib.primary_attachment(rid)
        bridge=ChatBridge(self.lib.root);url='https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc'
        try:
            handoff=bridge.prepare(rid,quote='Evidence',page=0,anchor={'rect':[.1,.2,.4,.3],'quote':'Evidence'})
            descriptor=handoff.split('#paperquick=')[1];token=descriptor.split('.',1)[1]
            bridge.bind(token,url,True)
            body={'url':url,'text':'A useful explanation\n第二段解释。','messageId':'answer-1'}
            request=Request(f'http://127.0.0.1:{bridge.server.server_port}/handoff/{token}/reply',data=json.dumps(body).encode(),headers={'X-PaperQuick':'1','Content-Type':'application/json'})
            with build_opener(ProxyHandler({})).open(request) as response:result=json.load(response)
            self.assertTrue(result['ok']);self.assertTrue(bridge.reply(token,**{'url':url,'text':body['text'],'message_id':'answer-1'})['duplicate'])
            reply=self.lib.get(rid)['annotations'][0]
            self.assertEqual(reply['attachment'],attachment['id']);self.assertEqual(reply['rect'],[.1,.2,.4,.3])
            self.assertEqual(reply['quote'],'Evidence')
            manual={'id':'manual','attachment':attachment['id'],'page':0,'rect':[0,0,0,0],'text':'Retained'}
            merged=self.lib.merge_annotations(rid,[manual],())
            self.assertEqual({a['id'] for a in merged},{manual['id'],reply['id']})
            # A later selection cannot retarget a previously issued return capability.
            bridge.prepare(rid,quote='Other evidence',page=0,anchor={'rect':[.7,.7,.8,.8]})
            bridge.reply(token,url,'Another explanation','answer-2')
            self.assertEqual(self.lib.get(rid)['annotations'][-1]['rect'],[.1,.2,.4,.3])
            with self.assertRaises(ValueError):bridge.reply(token,'https://chatgpt.com/c/87654321-1234','bad','x')
            bridge.reply_sessions[token]['created']-=REPLY_TTL+1
            with self.assertRaises(ValueError):bridge.reply(token,url,'expired','x')
        finally:bridge.close()

    def test_pdf_position_links_validate_attachment_and_page(self):
        rid=self.lib.import_pdf(self.source)
        target=destination(self.lib,rid,0,(.12,.73),quote='Clipping')
        self.assertEqual(target['target_point'],[.12,.73])
        with self.assertRaises(ValueError):destination(self.lib,rid,1)
        with self.assertRaises(ValueError):destination(self.lib,rid,0,(0,1.5))
        with self.assertRaises(ValueError):destination(self.lib,rid,attachment_id='missing')

    def test_exported_pdf_contains_native_comment_and_remote_page_link(self):
        from annotation_export import export_pdf
        from pypdf import PdfReader
        from library_core import digest
        rid=self.lib.import_pdf(self.source);target_file=self.base/'target.pdf';pdf(target_file,'Target')
        target=self.lib.import_pdf(target_file);aid=self.lib.primary_attachment(rid)['id']
        annotations=[{'id':'reply','attachment':aid,'page':0,'rect':[.1,.1,.1,.1],'kind':'ChatGPT 批注','text':'回复 explanation'},
                     {'id':'link','attachment':aid,'page':0,'rect':[.2,.2,.2,.2],'kind':'关联文献','text':'Clipping',**destination(self.lib,target,0,(.2,.6))}]
        self.lib.merge_annotations(rid,annotations)
        source_digest=digest(self.source);output=self.base/'annotated.pdf'
        result=export_pdf(self.lib,rid,aid,output);self.assertEqual(result['comments'],1);self.assertEqual(result['links'],1)
        reader=PdfReader(output);items=[r.get_object() for r in reader.pages[0]['/Annots']]
        self.assertEqual(items[0]['/Contents'],'回复 explanation')
        self.assertEqual(items[1]['/A']['/S'],'/GoToR');self.assertEqual(items[1]['/A']['/D'][0],0)
        self.assertAlmostEqual(float(items[1]['/A']['/D'][3]),40)
        self.assertEqual(digest(self.source),source_digest)
        with self.assertRaises(ValueError):export_pdf(self.lib,rid,aid,self.lib.root/'overwrite.pdf')

    def test_actual_worker_import_refreshes_and_continues_after_callback_error(self):
        from library_ui import LibraryWindow
        root=tk.Tk();root.withdraw();window=LibraryWindow(root,self.lib.root,embedded=True)
        def pump(condition,timeout=8):
            until=time.monotonic()+timeout
            while condition() and time.monotonic()<until:root.update();time.sleep(.01)
            self.assertFalse(condition(),'Background task did not complete')
        try:
            with patch.object(window,'chat_full_paper'),patch('library_ui.messagebox.showwarning'):
                window.search.set('does not match');window.status_filter.set('已读')
                window.batch_import([self.source],self.pid);pump(lambda:window.busy)
                self.assertEqual(len(window.tree.get_children()),1)
                rid=window.tree.get_children()[0];self.assertEqual(window.tree.selection(),(rid,))
                # A failed UI completion callback must not permanently stop polling.
                def fail(_):raise ValueError('fixture completion error')
                window.run('fixture',lambda lib:None,fail);pump(lambda:window.busy)
                window.batch_import([self.source],self.pid);pump(lambda:window.busy)
                self.assertEqual(len(window.tree.get_children()),1)
                window.search.set('no match');pump(lambda:bool(window.tree.get_children()))
                window.search.set('');pump(lambda:not window.tree.get_children())
        finally:window.close();root.destroy()

    def test_reader_import_notifies_an_existing_library_page(self):
        import app
        root=tk.Tk();root.withdraw()
        try:
            with patch('app.app_dir',return_value=self.base),patch.object(app.App,'start_selection_helper'),patch('desktop_runtime.startup_enabled',return_value=False):
                instance=app.App(root);instance.open_library();self.assertFalse(instance.library_window.tree.get_children())
                instance.show_page('reader');reader=instance.reader_page
                source=self.base/'reading.txt';source.write_text('Imported from the reader','utf-8')
                lib=Library(instance.library_directory)
                try:rid=lib.import_document(source)
                finally:lib.close()
                reader.events.put(('open',0,rid));reader.poll()
                self.assertTrue(instance.library_window.tree.exists(rid))
                instance.show_page('library');self.assertTrue(instance.library_window.tree.exists(rid))
                instance.close()
        finally:
            try:root.destroy()
            except tk.TclError:pass

    def test_heading_and_filter_metrics_at_high_dpi_and_form_wheel(self):
        from library_ui import LibraryWindow
        from ui_theme import install_theme,FONT
        from tkinter.font import Font
        from types import SimpleNamespace
        root=tk.Tk();root.withdraw()
        try:
            for scaling in (1.3333,2.0,2.6667):
                root.tk.call('tk','scaling',scaling);install_theme(root)
                window=LibraryWindow(root,self.lib.root,embedded=True);root.update_idletasks()
                heading=Font(root,font=(FONT,10,'bold'))
                for col in window.tree['columns']:
                    self.assertGreaterEqual(window.tree.column(col,'minwidth'),heading.measure(window.tree.heading(col,'text'))+20)
                body=Font(root,font=window.tag_filter_box.cget('font'))
                self.assertGreaterEqual(window.tag_filter_box.winfo_reqheight(),body.metrics('linespace')+6)
                self.assertTrue(window.tree.cget('xscrollcommand'))
                self.assertEqual(window.tag_filter_box.master.master.grid_slaves(row=0,column=1)[0].cget('textvariable'),str(window.search))
                window.close()
            canvas=tk.Canvas(root,height=100,width=200);canvas.configure(scrollregion=(0,0,200,2000))
            label=tk.Label(canvas,text='Form child');canvas.create_window((0,0),window=label);canvas.yview_moveto(0)
            old=canvas.yview()[0]
            for _ in range(4):root._paperquick_wheel_route(SimpleNamespace(widget=label,delta=-30,num=0))
            self.assertGreater(canvas.yview()[0],old)
        finally:
            if 'window' in locals() and window.win.winfo_exists():window.close()
            root.destroy()

    def test_incoming_reply_refresh_and_pdf_link_navigation(self):
        from reader_ui import ReaderPage
        root=tk.Tk();root.withdraw();reader=ReaderPage(root,self.lib.root,lambda _:None,lambda _:None)
        source_id=self.lib.import_pdf(self.source);second=self.base/'second.pdf'
        from test_reader import text_pdf
        text_pdf(second);target_id=self.lib.import_pdf(second)
        def pump(test,timeout=10):
            until=time.monotonic()+timeout
            while test() and time.monotonic()<until:root.update();time.sleep(.02)
            self.assertFalse(test())
        try:
            reader.open(source_id);pump(lambda:reader.loading)
            self.lib.append_chat_reply(source_id,self.lib.primary_attachment(source_id)['id'],{'page':0,'rect':[.1,.1,.2,.2]},'Returned reply','https://chatgpt.com/c/12345678-1234','message')
            reader._annotation_checked=0;reader.sync_incoming_annotations()
            self.assertEqual(len(reader.annotation_list.get_children()),1)
            self.assertEqual(reader.annotations[0]['text'],'Returned reply')
            target=destination(self.lib,target_id,1,(.1,.7));reader.open_link_location(target)
            pump(lambda:reader.loading or getattr(reader,'_pending_location',None) is not None)
            self.assertEqual(reader.rid,target_id);self.assertIn('第 2 页',reader.status.get())
        finally:reader.close();root.destroy()

if __name__=='__main__':unittest.main()
