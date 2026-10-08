import {lookup, automaticTarget, safeUrl, normalize} from './engine.js';
const $ = id => document.getElementById(id);
let busy = false;
const elem = (tag, text, cls) => { const e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; };
function render(result) {
  $('results').replaceChildren();
  for (const paper of result.papers) {
    const card = elem('article', '', 'card');
    card.append(elem('div', result.precise ? '标识符匹配 · 请核对版本' : (normalize(paper.title) === normalize(result.query) ? '标题匹配 · 请核对作者' : '检索候选 · 请核对'), 'tag'), elem('h2', paper.title), elem('div', [paper.year, paper.venue, paper.authors].filter(Boolean).join(' · '), 'muted'));
    if (paper.doi) card.append(elem('div', 'DOI: ' + paper.doi, 'muted'));
    if (!paper.links.some(x => ['pdf', 'fulltext'].includes(x.kind))) card.append(elem('p', result.complete === false ? '正在补充开放版本；出版社入口已可打开。' : '本次未找到开放原文，可通过学校 / 机构权限访问出版社。', 'warn'));
    for (const link of paper.links) {
      if (!safeUrl(link.url)) continue;
      const row = elem('div', '', 'row'), anchor = elem('a', link.label + ' ↗', 'link');
      anchor.href = link.url; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer';
      const copy = elem('button', '复制'); copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(link.url); copy.textContent = '已复制'; } catch { $('status').textContent = '复制受限，可右键链接复制地址。'; } });
      row.append(anchor, copy, elem('small', [link.source, link.note].filter(Boolean).join(' · '))); card.append(row);
    }
    $('results').append(card);
  }
  if (result.notes.length) $('results').append(elem('p', result.notes.join('\n'), 'notes'));
}
async function search(input) {
  if (busy) return;
  busy = true; $('search').disabled = true; $('status').dataset.busy = 'true';
  $('results').replaceChildren(); $('status').textContent = '正在查找…';
  const started = performance.now();
  let opened = false, opening = null;
  const show = result => {
    render(result);
    $('status').textContent = `找到 ${result.papers.length} 篇文献 / 候选 · ${((performance.now() - started) / 1000).toFixed(1)} 秒` + (result.complete === false ? ' · 正在补充，可直接打开' : '');
    const target = !opened && $('auto').checked ? automaticTarget(result) : '';
    if (target) {
      opened = true;
      opening = chrome.tabs.create({url: target, active: true}).catch(() => {
        $('status').textContent = '自动打开失败，请点击下方原文链接。';
      });
    }
    if (opened) $('status').textContent += ' · 已自动打开原文入口';
    else if (result.complete && $('auto').checked) $('status').textContent += ' · 请核对候选后打开';
  };
  try {
    const result = await lookup(input, $('email').value.trim(), text => $('status').textContent = text, show);
    show(result);
    if (opening) await opening;
  } catch (error) {
    $('status').textContent = '需要补充文献信息';
    $('results').append(elem('div', error.name === 'AbortError' ? '服务连接超时，请稍后重试。' : error.message, 'error'));
    if (input.sourceUrl && safeUrl(input.sourceUrl)) { const a = elem('a', '打开原推送 ↗', 'link'); a.href = input.sourceUrl; a.target = '_blank'; a.rel = 'noopener'; $('results').append(a); }
  } finally { busy = false; $('search').disabled = false; $('status').dataset.busy = 'false'; }
}
$('search').addEventListener('click', () => search({query: $('query').value, source: 'selection'}));
$('scholar').addEventListener('click', () => {
  const query = $('query').value.trim();
  if (query) chrome.tabs.create({url: 'https://scholar.google.com/scholar?' + new URLSearchParams({q: query}), active: true}).catch(() => { $('status').textContent = '浏览器未能打开学术搜索，请重试。'; });
  else $('status').textContent = '请先粘贴论文标题或 DOI。';
});
$('query').addEventListener('keydown', event => { if (event.ctrlKey && event.key === 'Enter') $('search').click(); });
$('save').addEventListener('click', async () => {
  if (!$('email').checkValidity()) { $('email').reportValidity(); return; }
  await chrome.storage.local.set({email: $('email').value.trim(), auto: $('auto').checked});
  $('status').textContent = '设置已保存';
});
const settings = await chrome.storage.local.get(['email', 'auto']);
$('email').value = settings.email || ''; $('auto').checked = settings.auto !== false;
const key = location.hash.slice(1);
if (key.startsWith('query-')) {
  const data = await chrome.storage.session.get(key); const input = data[key];
  await chrome.storage.session.remove(key); history.replaceState(null, '', location.pathname);
  if (input) { $('query').value = input.query || input.page?.citationTitle || input.page?.title || ''; await search(input); }
  else $('status').textContent = '临时查询已过期，请重新右键查询或粘贴标题。';
}
document.documentElement.dataset.ready = 'true';
