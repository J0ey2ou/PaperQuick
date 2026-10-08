const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const browser = await chromium.launch({channel: 'chromium', headless: true});
  const context = await browser.newContext({permissions: ['clipboard-read', 'clipboard-write']});
  try {
    const page = await context.newPage();
    const failures = []; page.on('pageerror', error => failures.push(error.message));
    await page.goto(pathToFileURL(path.resolve('推送文案.html')).href);
    await page.locator('#rich').click();
    await page.waitForFunction(() => document.getElementById('status').textContent.includes('已复制'));
    const clipboard = await page.evaluate(async () => {
      const items = await navigator.clipboard.read(), item = items[0];
      return {types: item.types, html: await (await item.getType('text/html')).text(), text: await navigator.clipboard.readText()};
    });
    assert.ok(clipboard.types.includes('text/html'));
    assert.ok(clipboard.html.includes('data:image/png;base64,'));
    assert.ok(clipboard.html.includes('data:image/gif;base64,'));
    assert.ok(clipboard.text.includes('https://github.com/J0ey2ou/PaperQuick'));
    await page.locator('#text').click();
    const plain = await page.evaluate(() => navigator.clipboard.readText());
    for (const phrase of ['Word / PDF / 微信电脑版','Ctrl + Alt + J','edge://extensions','公众号验证']) assert.ok(plain.includes(phrase));
    assert.ok(!plain.includes('非实时测速')); // Media captions are not included in pure-copy text.
    const gif = await page.locator('#gif-download').getAttribute('href');
    assert.ok(gif.startsWith('data:image/gif;base64,'));
    assert.deepEqual(Buffer.from(gif.split(',')[1],'base64'),fs.readFileSync('docs/images/demo.gif'));
    await page.locator('#image').click();
    await page.waitForFunction(() => document.getElementById('status').textContent.includes('已复制截图'));
    assert.ok(await page.evaluate(async () => (await navigator.clipboard.read())[0].types.includes('image/png')));
    assert.deepEqual(failures, []);
    await page.screenshot({path:'build/promo-preview.png',fullPage:true});
    fs.writeFileSync('build/promo-check.json', JSON.stringify({passed:true,richText:true,embeddedScreenshot:true,embeddedGif:true,gifDownload:true,expandedInstructions:true,plainText:true,imageCopy:true}));
    console.log('Promo passed: expanded instructions, rich text + GIF + screenshot, media download and PNG clipboard');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
