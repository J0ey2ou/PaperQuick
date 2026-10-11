"""Actual PaperQuick UI with a new, entirely fictional library on every run.

Run with build/vendor on PYTHONPATH:
  D:\\py\\python.exe scripts/preview_documents_ui.py reader
Modes: reader, convert, summary, attachments, library, graph.
Use --prepare-only to create fixtures and render review PNGs without opening UI.
"""
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import json
import os
import sys
import tempfile
import textwrap
from unittest.mock import patch
import zipfile

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE));sys.path.insert(0,str(BASE/'build'/'vendor'))
from library_core import Library
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject

BLUE=(.13,.29,.45);INK=(.12,.16,.2);MUTED=(.39,.45,.51);PALE=(.93,.96,.98)

def document_pdf(path,supplement=False):
    writer=PdfWriter()
    for page_number in range(2):
        page=writer.add_blank_page(612,792);commands=[]
        fonts={}
        for name,base in [('F1','Helvetica'),('F2','Helvetica-Bold')]:
            fonts[NameObject('/'+name)]=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/'+base)}))
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject(fonts)})
        def text(x,y,value,size=12,bold=False,color=INK):
            value=str(value).replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            commands.append(f'{color[0]} {color[1]} {color[2]} rg BT /'+('F2' if bold else 'F1')+f' {size} Tf 1 0 0 1 {x} {y} Tm ({value}) Tj ET')
        def rectangle(x,y,w,h,color):commands.append(f'{color[0]} {color[1]} {color[2]} rg {x} {y} {w} {h} re f')
        def rule(y):rectangle(46,y,520,1,(.78,.83,.88))
        def paragraph(value,y,size=12,width=78):
            for line in textwrap.wrap(value,width):text(46,y,line,size);y-=19
            return y
        text(46,753,'PAPERQUICK  /  RESEARCH WORKSPACE',10,True,BLUE)
        text(435,753,'FICTIONAL EXAMPLE',8,False,MUTED);rule(734)
        if not supplement and page_number==0:
            text(46,696,'Sleep regularity and cognitive health',26,True)
            text(46,660,'in young adults',26,True)
            text(46,630,'A. Lin, M. Chen and J. Rivera  |  2026',11,False,MUTED)
            rectangle(46,562,520,42,PALE);text(62,578,'A study designed for reading, annotation and comparison',12,True,BLUE)
            text(46,532,'Abstract',15,True)
            paragraph('This fictional study explores how consistent sleep patterns relate to attention and daily well-being. We illustrate a longitudinal research workflow with repeated observations and a transparent analysis plan.',505)
            text(46,414,'Study design',15,True)
            paragraph('Participants completed short daily assessments over four weeks. Sleep regularity, attention scores and contextual factors were examined together. Supplementary Table S1 describes the measures and timing.',386)
            text(46,290,'Reading the evidence',15,True)
            for x,number,label in [(46,'4 weeks','Observation period'),(222,'3 measures','Repeated assessments'),(398,'2 files','Linked supplements')]:
                rectangle(x,199,164,65,PALE);text(x+12,235,number,18,True,BLUE);text(x+12,214,label,10,False,MUTED)
            paragraph('Reader note: compare the measurement definitions in the supplement before interpreting the reported associations.',158,11,82)
        elif not supplement:
            text(46,696,'Results and interpretation',25,True)
            text(46,660,'A structured example for literature review',12,False,MUTED)
            text(46,605,'Key observations',15,True)
            paragraph('Regularity and duration capture different dimensions of sleep. In this example, the interpretation considers both within-person patterns and differences between participants.',575)
            text(46,470,'What to check in the supplement',15,True)
            for y,number,line in [(432,'01','Outcome definitions and measurement windows'),(390,'02','Covariate selection and sensitivity analyses'),(348,'03','Missing observations and exclusion criteria')]:
                text(46,y,number,14,True,BLUE);text(83,y,line,12)
            text(46,270,'Limitations',15,True)
            paragraph('These illustrative pages contain no real study findings. They are included solely to demonstrate local reading, notes and attachment comparison.',240)
            text(46,145,'References',15,True)
            text(46,116,'[1] Example Research Group. A fictional study protocol. 2026.',10,False,MUTED)
        elif page_number==0:
            text(46,696,'Supplementary material',26,True)
            text(46,659,'Study protocol and measurement tables',18,False,BLUE)
            text(46,627,'Linked to: Sleep regularity and cognitive health',11,False,MUTED)
            rectangle(46,560,520,43,PALE);text(62,576,'Table S1  |  Measures and assessment schedule',13,True,BLUE)
            headers=[('Measure',46),('Timing',284),('Source',427)]
            for label,x in headers:text(x+9,524,label,11,True)
            rows=[('Sleep regularity','Daily','Sleep diary'),('Sleep duration','Daily','Sleep diary'),('Attention score','Weekly','Brief assessment'),('Daily well-being','Daily','Questionnaire'),('Contextual factors','Baseline','Survey')]
            for i,row in enumerate(rows):
                y=482-i*43
                if i%2==0:rectangle(46,y-12,520,39,PALE)
                for value,x in zip(row,(55,293,436)):text(x,y,value,11)
            text(46,210,'Why read this alongside the paper?',15,True)
            paragraph('The supplement makes the measurement choices explicit. Keep it beside the main paper while reviewing the methods, and turn each document independently.',181)
        else:
            text(46,696,'Supplementary checks',26,True)
            text(46,658,'Table S2  |  Sensitivity analysis plan',17,False,BLUE)
            for y,title,desc in [(575,'Alternative windows','Compare weekly and daily summaries.'),(463,'Missing observations','Describe completeness before exclusions.'),(351,'Covariate choices','Review the role of baseline contextual factors.')]:
                rectangle(46,y-75,520,112,PALE);text(62,y,title,15,True,BLUE);text(62,y-29,desc,11)
            paragraph('All values and descriptions in this demonstration are fictional. Use the attachment list to add your own protocol, tables, data or related links.',181)
        rule(64);text(46,43,'Demonstration material - no real participants or research findings',8,False,MUTED);text(540,43,str(page_number+1),9,False,MUTED)
        stream=DecodedStreamObject();stream.set_data('\n'.join(commands).encode('ascii'));page[NameObject('/Contents')]=writer._add_object(stream)
    writer.add_metadata({'/Title':'Supplementary material - fictional example' if supplement else 'Sleep regularity and cognitive health in young adults','/Author':'PaperQuick demonstration'})
    with path.open('wb') as output:writer.write(output)

def word_document(path):
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:rPr><w:b/><w:sz w:val="36"/></w:rPr><w:t>Study protocol - fictional example</w:t></w:r></w:p><w:p><w:r><w:t>Sleep regularity and cognitive health in young adults</w:t></w:r></w:p><w:p><w:r><w:t>This document demonstrates a linked Word attachment. It contains no real study data.</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:body></w:document>')

def fixtures():
    base=BASE/'build'/'document-ui-demo';base.mkdir(parents=True,exist_ok=True)
    work=Path(tempfile.mkdtemp(prefix='preview-',dir=base));directory=work/'library'
    main=work/'research-paper.pdf';supplement=work/'supplement.pdf';word=work/'protocol.docx'
    document_pdf(main);document_pdf(supplement,True);word_document(word)
    lib=Library(directory)
    try:
        project=lib.create_project('睡眠与认知健康');rid=lib.import_pdf(main,project)
        lib.save({'title':'Sleep regularity and cognitive health in young adults','authors':'Lin, A.; Chen, M.; Rivera, J.','year':'2026','keywords':'sleep regularity; cognitive health; longitudinal study','abstract':'这是一篇演示文献：围绕睡眠规律、注意力与日常健康，展示如何对照正文和补充材料梳理研究方法。内容与数据均为虚构。','notes':'我的阅读记录\n\n研究问题：睡眠规律是否与注意力表现有关？\n方法核对：结合补充表 S1 检查测量时间与变量定义。\n下一步：继续检索纵向研究与测量工具。'},rid=rid)
        lib.add_attachment(rid,supplement,label='补充材料 · 表格与方法');lib.add_attachment(rid,word,label='研究方案 · Word');lib.add_attachment_link(rid,'https://example.com/supplement','补充材料网页（演示）')
        a=lib.primary_attachment(rid);lib.save({'annotations':[{'id':'demo-mark','attachment':a['id'],'page':0,'rect':[.075,.548,.91,.575],'color':'#ffd65c','kind':'框选高亮','text':'对照补充表检查变量定义与测量时间。','quote':'Supplementary Table S1 describes the measures and timing.','created':1}]},rid=rid)
        ids=[rid]
        for title,notes,keywords in [('Measuring daily attention in longitudinal research','关注重复测量的安排，以及缺失数据如何处理。','attention; longitudinal study; repeated measures'),('Sleep timing and well-being: a research framework','区分睡眠时长和睡眠规律，避免混淆不同研究问题。','sleep regularity; well-being; cognitive health')]:
            ids.append(lib.save({'title':title,'authors':'Example Research Group','year':'2026','abstract':'虚构演示文献，用于展示阅读回顾与主题关键词整理。','notes':notes,'keywords':keywords},project))
        yesterday=(datetime.now()-timedelta(days=1)).replace(hour=14,minute=0,second=0,microsecond=0).timestamp()
        with lib.db:
            for i,paper in enumerate(ids):lib.db.execute('INSERT INTO reading_sessions(paper,start,end) VALUES(?,?,?)',(paper,yesterday+i*3600,yesterday+i*3600+[1320,1080,780][i]))
        attachment=next(a for a in lib.get(rid)['attachments'] if a.get('label')=='补充材料 · 表格与方法')
    finally:lib.close()
    data={'directory':str(directory),'work':str(work),'main':str(main),'supplement':str(supplement),'word':str(word),'rid':rid,'attachment':attachment,'pid':os.getpid()}
    (BASE/'build'/'document-ui-preview.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return data

def run():
    parser=argparse.ArgumentParser();parser.add_argument('mode',nargs='?',default='reader',choices=['reader','convert','summary','attachments','library','graph']);parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args();data=fixtures()
    if args.prepare_only:
        from pdf_reader_core import render_page
        for name in ('main','supplement'):
            for page in range(2):render_page(data[name],page,1.3).save(Path(data['work'])/f'{name}-{page+1}.png')
        print(json.dumps(data,ensure_ascii=False));return
    import tkinter as tk
    from app import App
    from ui_theme import apply_skin
    root=tk.Tk()
    # App resolves preferences and its initial library under this fictional workspace.
    with patch('app.app_dir',return_value=Path(data['work'])):app=App(root)
    app.library_directory=Path(data['directory']);app.preferences={};app.email='';app.skin=apply_skin(root,'极简浅色');root.geometry('1400x920+50+25');root.title('文献直达 · 功能演示')
    app.open_reader(data['rid'])
    def ready():
        reader=app.reader_page
        if reader.loading or not reader.count:root.after(100,ready);return
        if args.mode=='reader':reader.compare_attachment(data['attachment'])
        elif args.mode=='convert':reader.conversion();reader.conversion_window.win.geometry('760x550+370+195')
        elif args.mode=='summary':app.show_summary()
        elif args.mode=='attachments':reader.attachment_panel()
        else:app.show_page(args.mode)
        apply_skin(root,'极简浅色')
    root.after(250,ready);root.mainloop()

if __name__=='__main__':run()
