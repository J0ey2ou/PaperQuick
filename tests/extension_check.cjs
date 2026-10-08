// 在独立临时 Chromium 配置中测试真实扩展；不修改用户 Edge / Chrome。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const TITLE = 'Highly accurate protein structure prediction with AlphaFold';
const DOI = '10.1038/s41586-021-03819-2';
const CR = {DOI, title: [TITLE], author: [{given: 'John', family: 'Jumper'}], published: {'date-parts': [[2021]]}, 'container-title': ['Nature']};
const PMC = {title: TITLE, doi: DOI, pubYear: '2021', pmcid: 'PMC8371605', isOpenAccess: 'Y', fullTextUrlList: {fullTextUrl: [{availabilityCode: 'OA', documentStyle: 'pdf', url: 'https://example.org/open.pdf'}]}};
(async () => {
  const profile = fs.mkdtempSync(path.join(root, 'build', 'extension-test-'));
  const context = await chromium.launchPersistentContext(profile, {channel: 'chromium', headless: true, args: ['--disable-extensions-except=' + path.join(root, 'browser-extension'), '--load-extension=' + path.join(root, 'browser-extension')]});
  const failures = [], checks = [];
  try {
    context.on('page', page => page.on('pageerror', error => failures.push(error.message)));
    await context.route('https://api.crossref.org/**', route => route.fulfill({json: route.request().url().includes('/works?') ? {message: {items: [CR]}} : {message: CR}}));
    await context.route('https://www.ebi.ac.uk/**', route => route.fulfill({json: {resultList: {result: [PMC]}}}));
    await context.route('https://export.arxiv.org/**', route => route.fulfill({contentType: 'application/xml', body: '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'}));
    await context.route('https://api.semanticscholar.org/**', route => route.fulfill({status: 429, json: {message: 'limited'}}));
    await context.route('https://example.org/**', route => route.fulfill({contentType: 'text/html', body: '<p>Test open full text</p>'}));
    let worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker');
    const id = new URL(worker.url()).host;
    // onInstalled may run just after the service worker becomes visible.
    await worker.evaluate(async () => {
      for (let attempt = 0; attempt < 50; attempt++) {
        try {
          await chrome.contextMenus.update('selection', {enabled: true});
          await chrome.contextMenus.update('page', {enabled: true});
          if (!chrome.contextMenus.onClicked.hasListeners()) throw new Error('menu listener missing');
          return;
        } catch (error) {
          if (attempt === 49) throw error;
          await new Promise(resolve => setTimeout(resolve, 100));
        }
      }
    });
    checks.push('Real MV3 service worker and both context menus registered');
    const page = await context.newPage();
    await page.goto(`chrome-extension://${id}/results.html`);
    await page.waitForFunction(() => document.documentElement.dataset.ready === 'true');
    const engine = await page.evaluate(async () => {
      const e = await import('./engine.js');
      const links = [{url: 'https://doi.org/10.1/test', kind: 'publisher'}, {url: 'https://example.org/open.pdf', kind: 'pdf'}];
      const title = 'Exact title for testing';
      const paper = {title, doi: '10.1000/a', links};
      return {
        doi: e.extractDois('https://doi.org/10.1000/test?utm_source=wx#ref')[0],
        exact: e.automaticTarget({query: title, papers: [paper], fromPage: false}),
        ambiguous: e.automaticTarget({query: title, papers: [paper, {...paper, doi: '10.1000/b'}], fromPage: false}),
        approximate: e.automaticTarget({query: 'Exact title', papers: [paper], fromPage: false}),
        refs: e.automaticTarget({query: 'news', papers: [paper], fromPage: true}),
        unsafe: e.safeUrl('javascript:alert(1)'),
        separate: e.merge([paper, {...paper, doi: '10.1000/b'}], title).length,
        xml: e.parseArxiv('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Attention Is All You Need</title><id>http://arxiv.org/abs/1706.03762v7</id><published>2017</published></entry></feed>')[0].links[0].url
      };
    });
    assert.deepEqual(engine, {doi: '10.1000/test', exact: 'https://example.org/open.pdf', ambiguous: '', approximate: '', refs: '', unsafe: false, separate: 2, xml: 'https://arxiv.org/pdf/1706.03762v7'});
    checks.push('DOI parsing, unique match, ambiguous-title safety, reference safety, PDF priority, arXiv XML');
    const readers = await page.evaluate(async () => {
      const {readPage} = await import('./page-reader.js');
      document.body.innerHTML = '<meta property="og:title" content="推送标题"><div id="js_content">论文：10.1000/right</div><aside>10.1000/wrong</aside>';
      const article = readPage();
      document.body.innerHTML = '<p>环境异常，完成验证后继续</p>';
      const blocked = readPage();
      return {text: article.text, blocked: blocked.blocked, empty: blocked.text === ''};
    });
    assert.equal(readers.text, '论文：10.1000/right'); assert.equal(readers.blocked, true); assert.equal(readers.empty, true);
    checks.push('Loaded WeChat article reader scopes body and recognizes verification pages');
    await page.goto(`chrome-extension://${id}/results.html`);
    // 使用真实后台入口，创建结果页并自动打开正确原文。
    const resultPromise = context.waitForEvent('page').catch(() => null);
    const response = await page.evaluate(async title => chrome.runtime.sendMessage({type: 'paperQuickLookup', info: {selectionText: title, pageUrl: 'https://example.org/source'}}), TITLE);
    assert.equal(response.ok, true, response.error);
    const resultPage = await resultPromise;
    assert.ok(resultPage, 'background launch created a results tab');
    await resultPage.waitForFunction(() => document.getElementById('status')?.textContent.includes('已自动打开'), null, {timeout: 30000});
    await resultPage.waitForFunction(async () => (await chrome.tabs.query({})).some(p => p.url === 'https://example.org/open.pdf' || p.pendingUrl === 'https://example.org/open.pdf'), null, {timeout: 10000});
    assert.equal(await resultPage.locator('.card h2').first().textContent(), TITLE);
    await resultPage.waitForFunction(() => document.getElementById('status').dataset.busy === 'false');
    assert.equal(await resultPage.locator('.notes').count(), 0); // Already open: no repeated DOI enrichment.
    assert.equal(await resultPage.evaluate(async () => Object.keys(await chrome.storage.session.get(null)).length), 0);
    await resultPage.screenshot({path: path.join(root, 'extension-preview.png'), fullPage: true});
    checks.push('Selection → result tab → auto-open correct PDF, skip redundant enrichment, temporary query removed');
    // 公众号已在浏览器正常打开：使用当前已显示正文查询，避开桌面 HTTP 读页限制。
    const key = 'query-test-wechat';
    await worker.evaluate(async ({key, doi}) => chrome.storage.session.set({[key]: {source: 'page', query: '', page: {title: '科学推送', dois: [doi], text: '正文', blocked: false}, sourceUrl: 'https://mp.weixin.qq.com/s/test'}}), {key, doi: DOI});
    const recovered = await context.newPage();
    await recovered.goto(`chrome-extension://${id}/results.html#${key}`);
    await recovered.waitForFunction(() => document.getElementById('status')?.textContent.includes('已自动打开'), null, {timeout: 30000});
    await recovered.waitForFunction(() => document.getElementById('status').dataset.busy === 'false');
    assert.match(await recovered.locator('.notes').textContent(), /限流/);
    assert.equal(await recovered.locator('.card h2').first().textContent(), TITLE);
    checks.push('Verified current-page DOI → open full text');
    const timing = await recovered.evaluate(async ({doi, title, cr, pmc}) => {
      const e = await import('./engine.js'), original = globalThis.fetch;
      const snapshots = [], started = performance.now();
      globalThis.fetch = async url => {
        const metadata = String(url).includes('crossref');
        await new Promise(resolve => setTimeout(resolve, metadata ? 400 : 20));
        return new Response(JSON.stringify(metadata ? {message: cr} : String(url).includes('ebi.ac.uk') ? {resultList: {result: [pmc]}} : {}), {status: 200});
      };
      try {
        const result = await e.lookup({query: doi}, '', () => {}, r => snapshots.push({at: performance.now() - started, target: e.automaticTarget(r), title: r.papers[0].title}));
        let applied = 0;
        const notes = [], stageStart = performance.now();
        await e.runStage([{name: 'slow fixture', run: () => new Promise(resolve => setTimeout(() => resolve({}), 180)), apply: () => applied++}], 30, notes);
        const stageMs = performance.now() - stageStart;
        await new Promise(resolve => setTimeout(resolve, 220));
        return {firstMs: snapshots[0].at, pdfMs: snapshots.find(x => x.target.endsWith('/open.pdf')).at, firstTitle: snapshots[0].title, finalTitle: result.papers[0].title, stageMs, lateApplied: applied, slowNote: notes.some(x => x.includes('响应较慢'))};
      } finally { globalThis.fetch = original; }
    }, {doi: DOI, title: TITLE, cr: CR, pmc: PMC});
    assert.ok(timing.firstMs < 100);
    assert.ok(timing.pdfMs < 350);
    assert.equal(timing.firstTitle, DOI);
    assert.equal(timing.finalTitle, TITLE);
    assert.ok(timing.stageMs < 160);
    assert.equal(timing.lateApplied, 0);
    assert.equal(timing.slowNote, true);
    checks.push('Immediate identifier links; PDF before slow metadata; deadline discards late responses');
    assert.deepEqual(failures, []);
    fs.writeFileSync(path.join(root, 'extension-check.json'), JSON.stringify({passed: true, checks, timing}, null, 2));
    console.log(JSON.stringify({passed: true, checks}));
  } finally { await context.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
