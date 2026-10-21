"""Wrapped DOI collision regression: different articles must stay independent."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from types import SimpleNamespace
from library_core import Library,pdf_metadata,digest
from doi_identity import extract_document_doi,complete_doi


def paper(path,title,suffix):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    writer=PdfWriter();page=writer.add_blank_page(600,800)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(f'BT /F1 12 Tf 40 750 Td 20 TL ({title}) Tj T* (doi:10.1136/bmjopen-2012-) Tj T* ({suffix}) Tj ET'.encode('ascii'))
    page[NameObject('/Contents')]=writer._add_object(stream);writer.add_metadata({'/Title':title})
    with path.open('wb') as out:writer.write(out)


class ImportIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.lib=Library(self.base/'store')
        self.a=self.base/'APHID.pdf';self.b=self.base/'Secondary.pdf'
        paper(self.a,'APHID protocol','001503');paper(self.b,'Secondary preventive care','002007')
    def tearDown(self):self.lib.close();self.temp.cleanup()

    def test_wrapped_dois_and_incomplete_prefix_are_not_dedup_keys(self):
        self.assertEqual(pdf_metadata(self.b)['doi'],'10.1136/bmjopen-2012-002007')
        a=self.lib.import_pdf(self.a);b=self.lib.import_pdf(self.b)
        self.assertNotEqual(a,b);self.assertEqual(len(self.lib.records()),2)
        for rid in (a,b):self.assertEqual(len(self.lib.get(rid)['attachments']),1)
        x=self.lib.save({'title':'Uncertain one','doi':'10.1136/bmjopen-2012-'})
        y=self.lib.save({'title':'Uncertain two','doi':'10.1136/bmjopen-2012-'})
        self.assertNotEqual(x,y)

    def test_doi_prefix_cannot_join_a_heading_or_different_metadata_source(self):
        self.assertEqual(extract_document_doi('10.1136/bmjopen-2012-','Introduction\nNo identifier here'),'')
        self.assertEqual(extract_document_doi('','doi:10.1136/bmjopen-2012-\nABSTRACT'), '')
        self.assertEqual(extract_document_doi('','http://dx.doi.org/10.1136/\nbmjopen-2012-002007).'),'10.1136/bmjopen-2012-002007')

    def test_legacy_false_merge_is_recovered_with_notes_and_original_files_kept(self):
        rid=self.lib.import_pdf(self.a);primary=self.lib.primary_attachment(rid)
        self.lib.add_attachment(rid,self.b);bad=next(a for a in self.lib.get(rid)['attachments'] if a['id']!=primary['id'])
        annotations=[{'id':'main','attachment':primary['id'],'text':'Main note'}, {'id':'secondary','attachment':bad['id'],'text':'Secondary note'}]
        self.lib.save({'doi':'10.1136/bmjopen-2012-','title':'Secondary preventive care','display_name':'Custom APHID display','notes':'Keep research notes','annotations':annotations},rid=rid)
        original_sha=digest(self.b)
        result=self.lib.import_batch([self.b],self.lib.get(rid)['primary_project']);new=result['paper_ids'][0]
        self.assertNotEqual(rid,new);self.assertEqual(result['details'][0]['state'],'recovered')
        old=self.lib.get(rid);fresh=self.lib.get(new)
        self.assertEqual(old['title'],'APHID protocol');self.assertEqual(old['display_name'],'Custom APHID display')
        self.assertEqual(old['notes'],'Keep research notes');self.assertEqual(old['doi'],'10.1136/bmjopen-2012-001503')
        self.assertEqual([a['id'] for a in old['annotations']],['main'])
        self.assertEqual([a['id'] for a in fresh['annotations']],['secondary'])
        self.assertEqual(self.lib.primary_attachment(new)['id'],bad['id'])
        self.assertEqual(fresh['doi'],'10.1136/bmjopen-2012-002007')
        self.assertTrue(self.lib.setting('identity-recovery:'+fresh['identity_recovery']))
        self.assertEqual(self.lib.import_pdf(self.b),new);self.assertEqual(digest(self.b),original_sha)
        self.assertEqual(self.lib.undo_import(result['batch'])['kept'],1)
        self.assertTrue((self.lib.root/bad['path']).is_file())
        again=self.lib.import_batch([self.b],fresh['primary_project'])
        self.assertEqual(again['details'][0]['state'],'linked')

    def test_control_wheel_zooms_and_plain_wheel_scrolls(self):
        from reader_canvas import DocumentCanvas
        from reader_ui import ReaderPage
        canvas=Mock();owner=SimpleNamespace(canvas=canvas,path=Path('fixture.pdf'),scale=1.,closed=False,loading=False,zoom=Mock())
        owner.zoom.side_effect=lambda factor:setattr(owner,'scale',owner.scale*factor)
        dc=DocumentCanvas(owner);owner.document_canvas=dc;dc.context=Mock(return_value=(0,[.2,.6]))
        ctrl=SimpleNamespace(state=4,delta=120,x=40,y=80)
        self.assertTrue(dc.control_wheel(ctrl));dc.apply_wheel_zoom();owner.zoom.assert_called_once_with(1.12)
        self.assertEqual(dc.zoom_anchor['point'],[.2,.6])
        self.assertFalse(dc.control_wheel(SimpleNamespace(state=0,delta=120)))

    def test_reupload_preserves_conversation_and_supplies_primary_again(self):
        from chat_bridge import ChatBridge
        rid=self.lib.import_pdf(self.a);bridge=ChatBridge(self.lib.root)
        try:
            url=bridge.prepare(rid,quote='First selection');token=url.split('#paperquick=')[1].split('.',1)[1]
            conversation='https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc';bridge.bind(token,conversation,True)
            second=bridge.prepare(rid,quote='Another selection');token2=second.split('#paperquick=')[1].split('.',1)[1]
            self.assertFalse(bridge.payload(token2)['files'])
            bridge.require_document_upload(rid)
            reupload=bridge.prepare(rid,quote='Read the main file again');token3=reupload.split('#paperquick=')[1].split('.',1)[1]
            self.assertTrue(reupload.startswith(conversation+'#'));self.assertTrue(bridge.payload(token3)['files'][0]['primary'])
        finally:bridge.close()
