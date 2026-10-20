// Actual MV3/content-script/HTTP integration in a disposable, strictly headless profile.
// No desktop input, screenshots, clipboard, user browser profiles or live ChatGPT requests.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const readline = require('node:readline');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const pending = [];
const backend = spawn(process.env.PYTHON || 'python', ['-u', path.join(__dirname, 'chat_bridge_fixture.py')], {cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe']});
let backendError='';backend.stderr.on('data', data => {backendError+=data;});
readline.createInterface({input:backend.stdout}).on('line', line => {const resolve=pending.shift();if(resolve)resolve(JSON.parse(line));});
backend.on('exit', code => {if(code)console.error('Fixture backend exited:',code,backendError);});
const issue = args => new Promise(resolve => {pending.push(resolve);backend.stdin.write(JSON.stringify(args)+'\n');});
const waitState=async state=>{
  const deadline=Date.now()+10000;
  let last;
  while(Date.now()<deadline){last=await issue({status:true});if(last.state===state)return;await new Promise(resolve=>setTimeout(resolve,200));}
  throw new Error('Expected bridge state: '+state+'; actual: '+JSON.stringify(last));
};
const checks=[];
let context;
const mode=process.argv[2]||'baseline';

function fixture({stripHash=false,plainChip=false,noInput=false,hiddenComposer=false,remount=false,nativeEditor=false,rejectText=false}={}) {
  return `<!doctype html><meta charset="utf-8"><title>Isolated chat composer fixture</title>
  ${stripHash?'<script>history.replaceState(null,"",location.pathname)</script>':''}
  ${hiddenComposer?'<textarea id="prompt-textarea" hidden></textarea>':''}
  <main><form><div><div id="prompt-textarea" class="ProseMirror" contenteditable="true"><p><br></p></div></div>
  <div id="attachments"></div><button type="button" data-testid="composer-plus-btn">Add</button></form>
  ${noInput?'':'<input type="file" multiple accept="application/pdf,image/png" hidden>'}</main>
  <script>
  window.fixture={uploads:[],draft:'',sends:0};
  let editor=document.querySelector('[contenteditable=true]');
  function track(event){
    ${rejectText?"setTimeout(()=>{editor.replaceChildren();window.fixture.draft='';},100);":''}
    ${nativeEditor?"if(!event.isTrusted){editor.replaceChildren();window.fixture.draft='';return}":''}
    window.fixture.draft=editor.innerText.trim();
    ${remount?"if(!window.fixture.remounted){window.fixture.remounted=true;setTimeout(()=>{const replacement=editor.cloneNode(false);editor.replaceWith(replacement);editor=replacement;editor.addEventListener('input',track);window.fixture.draft='';},700)}":''}
  }
  editor.addEventListener('input',track);
  async function upload(files){for(const file of files){
    const form=new FormData();form.append('file',file);
    const chip=document.createElement('div');chip.className='fixture-attachment';
    ${plainChip?'':"chip.setAttribute('data-testid','attachment');"}
    chip.textContent=file.name;chip.dataset.uploadState='uploading';document.querySelector('#attachments').append(chip);
    const response=await fetch('/paperquick-test-upload',{method:'POST',body:form});
    if(!response.ok){chip.dataset.uploadState='error';chip.textContent+=' Upload failed';return}
    window.fixture.uploads.push({name:file.name,size:file.size,sha:await crypto.subtle.digest('SHA-256',await file.arrayBuffer()).then(hash=>[...new Uint8Array(hash)].map(n=>n.toString(16).padStart(2,'0')).join(''))});
    chip.dataset.uploadState='complete';
  }}
  document.querySelector('input[type=file]')?.addEventListener('change',event=>upload([...event.target.files]));
  editor.addEventListener('dragover',event=>event.preventDefault());
  editor.addEventListener('drop',event=>{event.preventDefault();upload([...event.dataTransfer.files])});
  document.querySelector('form').addEventListener('submit',event=>{event.preventDefault();window.fixture.sends++});
  window.sendFixture=()=>{
    const turn=document.createElement('article');turn.setAttribute('data-testid','conversation-turn-1');
    const message=document.createElement('div');message.setAttribute('data-message-author-role','user');message.textContent=editor.innerText;
    turn.append(message,...document.querySelector('#attachments').children);document.querySelector('main').prepend(turn);
    editor.replaceChildren();window.fixture.draft='';window.fixture.sends++;
    history.pushState(null,'','/c/12345678-1234-1234-1234-123456789abc');
  };
  </script>`;
}

(async()=>{
  const profiles=path.join(root,'build/chat-integration');fs.mkdirSync(profiles,{recursive:true});
  const profile=fs.mkdtempSync(path.join(profiles,'profile-'));
  const executable=process.env.CHAT_TEST_BROWSER || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
  const extensionArgs=mode==='no-extension'?[]:['--disable-extensions-except='+path.join(root,'browser-extension'),'--load-extension='+path.join(root,'browser-extension')];
  context=await chromium.launchPersistentContext(profile,{executablePath:executable,headless:true,args:[
    '--no-first-run','--no-default-browser-check',...extensionArgs],serviceWorkers:'allow'});
  if(mode!=='no-extension'){
    const worker=context.serviceWorkers()[0]||await context.waitForEvent('serviceworker',{timeout:15000});
    assert(worker.url().startsWith('chrome-extension://'));
  }
  const errors=[];context.on('page',page=>page.on('pageerror',error=>errors.push(error.message)));
  const uploads=[];
  await context.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.hostname==='127.0.0.1'){await route.continue();return;}
    if(url.origin!=='https://chatgpt.com'){await route.abort();return;}
    if(new URL(route.request().url()).pathname==='/paperquick-test-upload'){
      uploads.push(route.request().postDataBuffer());
      await route.fulfill({status:mode==='upload-failure'?500:200,contentType:'application/json',body:'{}'});return;
    }
    await route.fulfill({contentType:'text/html',body:fixture({stripHash:mode==='stripped-hash',plainChip:mode==='plain-chip',noInput:mode==='drop',hiddenComposer:mode==='hidden-composer',remount:mode==='remount',nativeEditor:mode==='native-editor',rejectText:mode==='reject-text'})});
  });
  // Block all unrelated external requests; only fixture documents reach the bridge.
  const handoff=await issue({image:mode!=='whole-paper',whole:mode==='whole-paper',local:['local-launch','no-extension','reuse','whole-paper'].includes(mode)});
  const page=await context.newPage();await page.goto(handoff.url,{waitUntil:'commit'});
  if(mode==='no-extension'){
    await page.waitForSelector('#setup');
    assert((await page.locator('textarea').inputValue()).includes('Selected passage'));
    assert((await page.locator('#setup').textContent()).includes('加载解压缩的扩展'));
    assert.equal((await issue({status:true})).state,'waiting-extension');
    checks.push('Missing extension shows setup steps and preserves selected text on a local page');
  }else if(mode==='reject-text'){
    await waitState('error');
    assert.equal(await page.locator('[contenteditable=true]').innerText(),'');
    assert.equal(uploads.length,0);
    checks.push('A webpage that discards input reports failure and never claims the selection or attachments are ready');
  }else if(mode==='upload-failure'){
    await page.waitForFunction(()=>window.fixture?.draft.includes('Selected passage'),{},{timeout:20000});
    await waitState('upload-error');
    assert((await page.evaluate(()=>window.fixture.draft)).includes('Selected passage'));
    checks.push('Upload failure reports its cause while selected text remains in the input box');
  }else{
  await page.waitForFunction(prompt=>window.fixture?.draft.replace(/\s+/g,' ').trim()===prompt.replace(/\s+/g,' ').trim(),handoff.prompt,{timeout:20000});
  await page.waitForFunction(count=>window.fixture.uploads.length===count,handoff.files.length,{timeout:15000});
  const result=await page.evaluate(()=>window.fixture);
  assert.equal(result.sends,0);
  assert.equal(result.uploads[0].sha,handoff.sourceSha256);
  assert.equal(result.uploads[0].name,handoff.files[0].name);
  if(handoff.files[1])assert.equal(result.uploads[1].name,handoff.files[1].name);
  assert.equal(uploads.length,handoff.files.length);
  assert(uploads[0].includes(Buffer.from('%PDF-')));
  assert.equal(errors.length,0,errors.join('\n'));
  checks.push('Real MV3 worker fetches the Python bridge and transfers exact PDF bytes');
  checks.push('Real file input/drop sends document and image to the isolated upload fixture');
  checks.push('Selected text enters the browser contenteditable; no message is sent');
  await waitState('ready');
  if(mode==='whole-paper'){
    assert(result.draft.includes('通篇解读'));
    assert(result.draft.includes('研究设计、数据或样本、关键方法'));
    assert(!result.draft.includes('第 1 页'));
    checks.push('The configurable Chinese whole-paper prompt and exact primary PDF reach the web composer without sending');
  }
  if(['hidden-composer','remount','native-editor'].includes(mode)){
    await new Promise(resolve=>setTimeout(resolve,1400));
    assert((await page.locator('[contenteditable=true]').innerText()).includes('Selected passage'));
    if(mode==='hidden-composer')assert.equal(await page.locator('textarea[hidden]').inputValue(),'');
    checks.push('Visible rich-text editor retains the selection through hidden controls, native editing and hydration');
  }
  if(['cleared-draft','retry-route','preserve-draft'].includes(mode)){
    const next=await issue({quote:'A second passage from the same paper.',local:true});
    if(mode==='cleared-draft')await page.evaluate(()=>{
      document.querySelector('[contenteditable=true]').replaceChildren();window.fixture.draft='';
    });
    const incoming=await context.newPage();await incoming.goto(next.url,{waitUntil:'commit'});
    if(mode!=='cleared-draft'){
      await incoming.waitForSelector('#paperquick-chat-status',{state:'attached'});
      await new Promise(resolve=>setTimeout(resolve,500));
      assert((await page.locator('[contenteditable=true]').innerText()).includes('Selected passage'));
      assert.equal(context.pages().filter(p=>p.url().startsWith('https://chatgpt.com/')).length,2);
      checks.push('An actual unsent draft stays untouched and its incoming handoff stays open');
      if(mode==='retry-route'){
        await page.evaluate(()=>{document.querySelector('[contenteditable=true]').replaceChildren();window.fixture.draft='';});
        // Dispatch within the fixture DOM across extension isolated worlds;
        // no mouse, keyboard, OS input or foreground window control.
        await incoming.locator('#paperquick-chat-status').evaluate(node=>node.shadowRoot.querySelector('button').dispatchEvent(new Event('click')));
      }
    }
    if(mode!=='preserve-draft'){
      await page.waitForFunction(()=>window.fixture?.draft.includes('A second passage'),{},{timeout:20000});
      await waitState('ready');
      if(!incoming.isClosed())await incoming.waitForEvent('close',{timeout:5000});
      assert.equal(context.pages().filter(p=>p.url().startsWith('https://chatgpt.com/')).length,1);
      assert.equal((await page.evaluate(()=>window.fixture)).uploads.length,2);
      checks.push('An empty composer releases the stale lock; retry routes back to the original tab');
    }
  }
  if(mode==='reply'){
    await page.evaluate(()=>window.sendFixture());await waitState('bound');
    await page.evaluate(()=>{
      const assistant=document.createElement('article');assistant.setAttribute('data-message-author-role','assistant');assistant.setAttribute('data-message-id','reply-1');
      assistant.innerHTML='<div class="markdown"><p>Method explanation from the isolated fixture.</p><p>第二段解释。</p></div>';
      document.querySelector('main').append(assistant);
    });
    await page.waitForSelector('[data-paperquick-reply]');
    await page.locator('[data-paperquick-reply]').evaluate(button=>button.dispatchEvent(new Event('click')));
    await page.waitForFunction(()=>document.querySelector('[data-paperquick-reply]')?.textContent==='已保存到文献批注');
    const annotations=await issue({annotations:true});assert.equal(annotations.length,1);
    assert.equal(annotations[0].kind,'ChatGPT 批注');assert(annotations[0].text.includes('Method explanation'));
    assert(annotations[0].text.includes('第二段解释'));assert.equal(annotations[0].page,0);
    assert.equal((await page.evaluate(()=>window.fixture)).sends,1);
    checks.push('A real extension return button saves only the selected assistant reply through HTTP into the originating local PDF annotation');
  }
  if(mode==='reuse'){
    await page.evaluate(()=>window.sendFixture());
    await waitState('bound');
    const next=await issue({quote:'A second passage from the same paper.',local:true});
    assert.equal(next.files.length,0,'A sent and bound primary document must not be uploaded again');
    assert(next.url.startsWith('http://127.0.0.1:'));
    const incoming=await context.newPage();await incoming.goto(next.url,{waitUntil:'commit'});
    await page.waitForFunction(()=>window.fixture?.draft.includes('A second passage'),{},{timeout:20000});
    await waitState('ready');
    if(!incoming.isClosed())await incoming.waitForEvent('close',{timeout:5000});
    assert.equal((await page.evaluate(()=>window.fixture)).uploads.length,2);
    assert.equal(context.pages().filter(p=>p.url().startsWith('https://chatgpt.com/')).length,1);
    checks.push('After sending the fixture message, the same document reuses its bound tab without reuploading the primary');
  }
  }
  const report={passed:true,mode,headless:true,isolated_profile:true,user_profiles_accessed:false,checks};
  fs.writeFileSync(path.join(root,'build/chat-integration-'+mode+'-check.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
})().catch(async error=>{
  console.error(error.stack);
  if(context)for(const p of context.pages()){
    try{console.error(JSON.stringify(await p.evaluate(()=>({url:location.origin+location.pathname,fixture:window.fixture,editor:document.querySelector('[contenteditable=true]')?.innerText}))))}catch(_){}
  }
  console.error(JSON.stringify(await issue({status:true})));
  process.exitCode=1;
}).finally(async()=>{
  if(context)await context.close();
  backend.stdin.end(JSON.stringify({stop:true})+'\n');
});
