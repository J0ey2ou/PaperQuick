// Real DOM/File/DataTransfer regressions. Headless, isolated, no live providers/input/clipboard/screenshots.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..');const descriptor='54321.'+'a'.repeat(43);
const sites={chatgpt:'https://chatgpt.com/',doubao:'https://www.doubao.com/chat/',deepseek:'https://chat.deepseek.com/',gemini:'https://gemini.google.com/app',qwen:'https://chat.qwen.ai/',kimi:'https://www.kimi.com/'};
const data=Buffer.from('%PDF-1.4\nIsolated PDF upload bytes.\n%%EOF');
const scenarios=process.argv[2]?[process.argv[2]]:['mixed','menu','ignored','plain','delayed','error'];
function fixture(mode){return `<!doctype html><meta charset=utf-8><style>body{margin:0}main{padding:8px}form{width:100%;box-sizing:border-box}#prompt-textarea{white-space:pre-wrap;overflow-wrap:anywhere;min-height:100px;max-height:200px;overflow:auto}button{max-width:100%}</style><main><div id=composer-shell><form><div id="prompt-textarea" class="ql-editor ProseMirror" contenteditable=true role=textbox></div><button type=button aria-haspopup=menu aria-label="添加附件">+</button></form><div id=files></div></div><input id=images type=file accept="image/*" hidden>${mode==='menu'?'':'<input id=documents type=file accept=".pdf,application/pdf" hidden>'}</main>
<script>window.received=[];window.wrong=0;window.sent=0;const mode=${JSON.stringify(mode)};const files=document.querySelector('#files');
async function accept(file){window.received.push({name:file.name,type:file.type,text:await file.text()});const chip=document.createElement('div');
if(mode==='plain'){chip.title=file.name;chip.textContent='fixture-pa…pdf';}else{chip.dataset.testid='attachment';chip.dataset.uploadState='uploading';chip.textContent=file.name;}
const show=()=>{files.append(chip);if(mode!=='plain')setTimeout(()=>chip.dataset.uploadState=mode==='error'?'error':'complete',150);};setTimeout(show,mode==='delayed'?5200:0);}
function input(){const el=document.querySelector('#documents');el.onchange=e=>{if(mode!=='ignored')for(const file of e.target.files)accept(file);};}
document.querySelector('#images').onchange=e=>window.wrong++;
if(document.querySelector('#documents'))input();
document.querySelector('button').onclick=()=>{if(!document.querySelector('#documents')){const el=document.createElement('input');el.id='documents';el.type='file';el.accept='.pdf';el.hidden=true;document.querySelector('main').append(el);input();}};
document.querySelector('form').ondragover=e=>e.preventDefault();document.querySelector('form').ondrop=e=>{e.preventDefault();for(const file of e.dataTransfer.files)accept(file);};
</script>`;}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHAT_TEST_BROWSER||'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',args:['--no-first-run','--disable-background-networking']});
 const results=[];
 try{for(const scenario of scenarios)for(const [provider,url] of Object.entries(sites)){
  const page=await browser.newPage({viewport:{width:340,height:580}});await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:fixture(scenario)}));
  await page.goto(url+'#paperquick='+descriptor);await page.evaluate(({descriptor,base64,home,embedded})=>{
   window.statuses=[];window.__paperQuickEmbedded=embedded;
   window.chrome={runtime:{id:'fixture',onMessage:{addListener(){}},sendMessage:async message=>{
    if(message.type.endsWith('Status')){statuses.push(message);return {ok:true};}
    if(message.type.endsWith('Ui'))return {ok:true};
    if(message.type.endsWith('Chunk'))return {ok:true,data:base64};
    if(message.type.endsWith('Route')||message.type.endsWith('Payload'))return {ok:true,payload:{url:'',home,prompt:'Selected passage. Filename fixture-paper.pdf in draft is not an attachment.',files:[{name:'fixture-paper.pdf',size:atob(base64).length,chunks:1,primary:true}]}};
    return {ok:true};
   }}};
  },{descriptor,base64:data.toString('base64'),home:url,embedded:true});
  for(const file of ['ai-sites.js','ai-upload.js',provider==='chatgpt'?'chat-content.js':'ai-web-content.js'])await page.addScriptTag({path:path.join(root,'browser-extension',file)});
  const expected=scenario==='error'?'upload-error':'ready';await page.waitForFunction(expected=>window.statuses.some(s=>s.state===expected),expected,{timeout:25000});
  const state=await page.evaluate(()=>({received,wrong,sent,overlay:!!document.querySelector('#paperquick-ai-web,#paperquick-chat-status'),draft:document.querySelector('[contenteditable]').innerText,scrollWidth:document.documentElement.scrollWidth,width:innerWidth}));
  assert.equal(state.wrong,0,provider+' must not stage PDF through image picker');assert.equal(state.received.length,1,provider+' must upload exactly once');assert.equal(state.received[0].text,data.toString());assert.equal(state.received[0].type,'application/pdf');assert.equal(state.sent,0);assert.equal(state.overlay,false);assert.match(state.draft,/Selected passage/);assert(state.scrollWidth<=state.width);
  results.push({provider,scenario,passed:true,pdfBytesVerified:true,noOverlay:true,noAutoSend:true});console.log(JSON.stringify(results.at(-1)));await page.close();
 }
 // External browser UI is in normal document flow, including narrow viewports.
 for(const provider of ['doubao','chatgpt']){
  const page=await browser.newPage({viewport:{width:320,height:580}});const url=sites[provider];await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:fixture('mixed')}));await page.goto(url+'#paperquick='+descriptor);
  await page.evaluate(({home,base64})=>{window.statuses=[];window.chrome={runtime:{id:'fixture',onMessage:{addListener(){}},sendMessage:async m=>m.type.endsWith('Route')?{ok:true,payload:{home,url:'',prompt:'Selected passage',files:[]}}:{ok:true}}};},{home:url,base64:data.toString('base64')});
  for(const file of ['ai-sites.js','ai-upload.js',provider==='chatgpt'?'chat-content.js':'ai-web-content.js'])await page.addScriptTag({path:path.join(root,'browser-extension',file)});
  await page.waitForSelector(provider==='chatgpt'?'#paperquick-chat-status':'#paperquick-ai-web');const layout=await page.evaluate(()=>{const host=document.querySelector('#paperquick-chat-status,#paperquick-ai-web');const panel=host.shadowRoot.firstElementChild;const a=host.getBoundingClientRect(),b=document.querySelector('main').getBoundingClientRect();return {position:getComputedStyle(panel).position,bottom:a.bottom,mainTop:b.top,width:document.documentElement.scrollWidth,viewport:innerWidth};});assert.equal(layout.position,'relative');assert(layout.mainTop>=layout.bottom-1);assert(layout.width<=layout.viewport);await page.close();
 }
 fs.writeFileSync(path.join(root,'build/ai-upload-'+(process.argv[2]||'all')+'-check.json'),JSON.stringify({passed:true,headless:true,results,externalPanelInFlow:true},null,2));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
