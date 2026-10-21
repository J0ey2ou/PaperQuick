// Full six-provider MV3 -> loopback -> reader inbox integration, all sites isolated.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');const readline=require('node:readline');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),pending=[];
const mode=process.argv[2]||'baseline';
const backend=spawn(process.env.PYTHON||'python',['-u','tests/chat_bridge_fixture.py'],{cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe']});
let errors='';backend.stderr.on('data',data=>errors+=data);
readline.createInterface({input:backend.stdout}).on('line',line=>pending.shift()?.(JSON.parse(line)));
const issue=data=>new Promise(resolve=>{pending.push(resolve);backend.stdin.write(JSON.stringify(data)+'\n');});
const sites={chatgpt:['https://chatgpt.com','/c/12345678-abcd'],doubao:['https://www.doubao.com','/chat/12345678'],deepseek:['https://chat.deepseek.com','/a/chat/s/12345678'],gemini:['https://gemini.google.com','/app/12345678'],qwen:['https://chat.qwen.ai','/c/12345678'],kimi:['https://www.kimi.com','/chat/12345678']};
let context,phase='initializing';const reports=[];
const deadline=setTimeout(()=>{console.error('Integration deadline: '+phase);backend.kill();context?.close();process.exit(1);},150000);
function fixture(conversation){return `<!doctype html><meta charset="utf-8"><main>
<form><div id="prompt-textarea" class="ql-editor ProseMirror" contenteditable="true" role="textbox">${mode==='draft'?'Existing unsent draft':''}</div><div id="files"></div></form>${mode==='missing-upload'?'':'<input type="file" accept="application/pdf" hidden>'}
<script>
const editor=document.querySelector('[contenteditable]');window.sent=0;window.uploads=0;
const input=document.querySelector('input');if(input)input.onchange=event=>{for(const file of event.target.files){const chip=document.createElement('div');chip.dataset.testid='attachment';chip.dataset.uploadState='uploading';chip.textContent=file.name;document.querySelector('#files').append(chip);setTimeout(()=>{chip.dataset.uploadState=${JSON.stringify(mode==='failed-upload'?'error':'complete')};window.uploads++},150)}};
window.sendFixture=()=>{const turn=document.createElement('article');turn.dataset.testid='conversation-turn-1';const user=document.createElement('div');user.dataset.messageAuthorRole='user';user.textContent=editor.innerText;turn.append(user,...document.querySelector('#files').children);document.querySelector('main').prepend(turn);editor.replaceChildren();history.pushState(null,'',${JSON.stringify(conversation)});window.sent++;
const assistant=document.createElement('div');assistant.dataset.messageAuthorRole='assistant';assistant.dataset.messageId='fixture-answer';const text=document.createElement('div');text.className='markdown';text.id='answer';text.textContent='Isolated assistant answer for this literature.';assistant.append(text);turn.append(assistant);};
</script></main>`;}
async function waitState(state){
 const until=Date.now()+18000;let latest;
 while(Date.now()<until){latest=await issue({status:true});if(latest.state===state)return;await new Promise(r=>setTimeout(r,150));}
 throw new Error('Expected '+state+', got '+JSON.stringify(latest));
}
(async()=>{
 const base=path.join(root,'build/ai-web-integration');fs.mkdirSync(base,{recursive:true});
 const profile=fs.mkdtempSync(path.join(base,'profile-'));
 context=await chromium.launchPersistentContext(profile,{executablePath:process.env.CHAT_TEST_BROWSER||'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true,args:['--no-first-run','--no-default-browser-check','--disable-extensions-except='+path.join(root,'browser-extension'),'--load-extension='+path.join(root,'browser-extension')],serviceWorkers:'allow'});
 await context.route('**/*',async route=>{
   const url=new URL(route.request().url());if(url.hostname==='127.0.0.1')return route.continue();
   const site=Object.values(sites).find(s=>url.origin===s[0]);if(!site)return route.abort();
   return route.fulfill({contentType:'text/html',body:fixture(site[1])});
 });
 for(const [provider,[origin,conversation]] of Object.entries(mode==='baseline'?sites:{doubao:sites.doubao})){
   phase=provider+' preparing';const handoff=await issue({provider,reply_mode:'ai',local:true});
   const page=await context.newPage();await page.goto(handoff.url,{waitUntil:'commit'});
   if(mode!=='baseline'){
     await waitState(mode==='draft'?'error':'upload-error');assert.equal(await page.evaluate(()=>window.sent),0);
     const draft=await page.locator('[contenteditable]').innerText();
     if(mode==='draft'){assert.equal(draft,'Existing unsent draft');assert.equal(await page.evaluate(()=>window.uploads),0);}
     else assert.match(draft,/Selected passage/);
     reports.push({provider,mode,passed:true,draft_preserved:true,auto_sent:false});console.log(JSON.stringify(reports.at(-1)));await page.close();continue;
   }
   await waitState('ready');
   assert((await page.locator('[contenteditable]').innerText()).includes('Selected passage'));assert.equal(await page.evaluate(()=>window.sent),0);assert.equal(await page.evaluate(()=>window.uploads),1);
   await page.evaluate(()=>window.sendFixture());
   if(provider!=='chatgpt')await page.evaluate(()=>[...document.querySelector('#paperquick-ai-web').shadowRoot.querySelectorAll('button')].find(b=>b.textContent.includes('发送后绑定')).click());
   await waitState('bound');
   phase=provider+' returning reply';
   await page.evaluate(()=>{const range=document.createRange();range.selectNodeContents(document.querySelector('#answer'));const selection=getSelection();selection.removeAllRanges();selection.addRange(range);});
   if(provider==='chatgpt'){
     await page.waitForSelector('[data-paperquick-reply]');await page.locator('[data-paperquick-reply]').evaluate(button=>button.click());
   }else await page.evaluate(()=>[...document.querySelector('#paperquick-ai-web').shadowRoot.querySelectorAll('button')].find(b=>b.textContent.includes('回存选中')).click());
   let inbox=[];const until=Date.now()+8000;
   while(Date.now()<until){inbox=await issue({inbox:provider});if(inbox.length)break;await new Promise(r=>setTimeout(r,150));}
   assert.equal(inbox.length,1,provider+' reply must reach source inbox');assert.match(inbox[0].answer,/Isolated assistant answer/);assert.equal(inbox[0].provider,provider);
   phase=provider+' reusing conversation';
   const next=await issue({provider,reply_mode:'ai',quote:'Second selected passage',local:true});assert.equal(next.files.length,0);
   const launch=await context.newPage();await launch.goto(next.url,{waitUntil:'commit'});await waitState('ready');
   assert.equal(page.url(),origin+conversation);assert.match(await page.locator('[contenteditable]').innerText(),/Second selected passage/);assert.equal(await page.evaluate(()=>window.sent),1);
   reports.push({provider,passed:true,upload:true,inbox:true,reused:true,auto_sent:false});console.log(JSON.stringify(reports.at(-1)));await page.close();
 }
 fs.writeFileSync(path.join(root,'build/ai-web-'+(mode==='baseline'?'integration':mode)+'-check.json'),JSON.stringify({passed:true,isolated:true,providers:reports},null,2));
})().catch(error=>{console.error(phase,error,errors);process.exitCode=1;}).finally(async()=>{clearTimeout(deadline);await context?.close();backend.stdin.write('{"stop":true}\n');backend.stdin.end();});
