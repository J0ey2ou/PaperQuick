// Record the real extension UI using a public-paper fixture, without touching a user browser.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const TITLE = 'Highly accurate protein structure prediction with AlphaFold';
const DOI = '10.1038/s41586-021-03819-2';
const CR = {DOI, title:[TITLE], author:[{given:'John',family:'Jumper'}], published:{'date-parts':[[2021]]}, 'container-title':['Nature']};
const PMC = {title:TITLE,doi:DOI,pubYear:'2021',authorString:'John Jumper 等',pmcid:'PMC8371605',isOpenAccess:'Y',fullTextUrlList:{fullTextUrl:[{availabilityCode:'OA',documentStyle:'pdf',url:'https://europepmc.org/articles/PMC8371605?pdf=render'}]}};
(async () => {
  const frames = path.join(root,'build','demo-frames'); fs.mkdirSync(frames,{recursive:true});
  const profile = fs.mkdtempSync(path.join(root,'build','demo-profile-'));
  const context = await chromium.launchPersistentContext(profile,{channel:'chromium',headless:true,viewport:{width:960,height:720},args:['--disable-extensions-except='+path.join(root,'browser-extension'),'--load-extension='+path.join(root,'browser-extension')]});
  const capture = async (page, name) => page.screenshot({path:path.join(frames,name+'.png')});
  try {
    await context.route('https://api.crossref.org/**', async route => { await new Promise(r=>setTimeout(r,1400)); await route.fulfill({json:{message:route.request().url().includes('/works?')?{items:[CR]}:CR}}); });
    await context.route('https://www.ebi.ac.uk/**', async route => { await new Promise(r=>setTimeout(r,3000)); await route.fulfill({json:{resultList:{result:[PMC]}}}); });
    await context.route('https://export.arxiv.org/**',route=>route.fulfill({contentType:'application/xml',body:'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'}));
    // Never fetch or redistribute the paper itself: only verify the opened destination URL.
    await context.route('https://europepmc.org/**',route=>route.fulfill({contentType:'text/html',body:'<p>Public-paper full-text destination (test fixture)</p>'}));
    const worker=context.serviceWorkers()[0] || await context.waitForEvent('serviceworker');
    const id=new URL(worker.url()).host;
    const source=await context.newPage();
    await source.setContent(`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>body{background:#f3f6fa;color:#172c45;font:18px/1.9 'Microsoft YaHei UI',sans-serif;margin:0}main{margin:75px auto;width:790px;background:white;border:1px solid #dce4ef;border-radius:16px;padding:32px;box-sizing:border-box}h1{font-size:27px}p{margin:20px 0}.title{font-size:23px;font-weight:bold;line-height:1.6}.tag{color:#215cce;font-size:15px}::selection{background:#b9d3ff}</style><main><div class="tag">导师 / 合作者发来的文献信息 · 示例</div><h1>这篇论文值得读一下</h1><p id="paper-title" class="title">${TITLE}</p><p>John Jumper 等 · Nature · 2021<br>DOI：${DOI}</p><p>在网页里选中英文论文标题，就可以从文献直达的右键入口发起查询。</p></main></html>`);
    await capture(source,'01-source');
    await source.locator('#paper-title').evaluate(el=>{const range=document.createRange();range.selectNodeContents(el);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);});
    await capture(source,'02-selected');
    const controller=await context.newPage();
    await controller.goto(`chrome-extension://${id}/results.html`);
    await controller.waitForFunction(()=>document.documentElement.dataset.ready==='true');
    const next=context.waitForEvent('page').catch(()=>null);
    // Same launch function that the actual context-menu click handler calls.
    const response=await controller.evaluate(async title=>chrome.runtime.sendMessage({type:'paperQuickLookup',info:{selectionText:title,pageUrl:'https://paperquick.example/public-demo'}}),TITLE);
    assert.equal(response.ok,true,response.error);
    const result=await next;
    assert.ok(result,'extension created results tab');
    await result.waitForLoadState('domcontentloaded');
    await result.locator('#query').waitFor();
    await capture(result,'03-query');
    await result.locator('.card h2').waitFor();
    assert.equal(await result.locator('.card h2').first().textContent(),TITLE);
    await capture(result,'04-candidate');
    await result.waitForFunction(()=>document.getElementById('status').textContent.includes('已自动打开'));
    await result.waitForFunction(()=>document.getElementById('status').dataset.busy==='false');
    await result.waitForFunction(async()=> (await chrome.tabs.query({})).some(tab=>tab.url==='https://europepmc.org/articles/PMC8371605?pdf=render' || tab.pendingUrl==='https://europepmc.org/articles/PMC8371605?pdf=render'));
    await capture(result,'05-fulltext');
    await result.locator('.card a').first().focus();
    await capture(result,'06-links');
    fs.writeFileSync(path.join(frames,'recording.json'),JSON.stringify({passed:true,fixture:true,title:TITLE,doi:DOI,openedPdf:true,extensionId:id,frames:6},null,2));
    console.log('Demo recorded: selected title → actual extension launch → partial result → PDF link and automatic-open status');
  } finally {await context.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
