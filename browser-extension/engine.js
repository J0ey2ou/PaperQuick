export const normalize = text => String(text || '').normalize('NFKC').toLowerCase().replace(/<[^>]*>/g, '').replace(/[^\p{L}\p{N}]/gu, '');
export function safeUrl(url) { try { const u = new URL(url); return ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password; } catch { return false; } }
export function extractDois(text) {
  try { text = decodeURIComponent(String(text)); } catch { text = String(text); }
  text = text.replace(/https?:\/\/[^\s<>"，。]+/g, value => { try { const u = new URL(value); return /10\.\d{4,9}\//i.test(u.pathname) ? u.pathname : value; } catch { return value; } });
  const found = [];
  for (let doi of text.match(/10\.\d{4,9}\/[^\s<>"，。；）]+/gi) || []) {
    doi = doi.replace(/[.,;:!?\]}”’]+$/, '');
    while (doi.endsWith(')') && (doi.match(/\)/g) || []).length > (doi.match(/\(/g) || []).length) doi = doi.slice(0, -1);
    if (!found.some(x => x.toLowerCase() === doi.toLowerCase())) found.push(doi);
  }
  return found;
}
const arxivId = text => String(text).match(/(?:arxiv\s*:\s*|arxiv\.org\/(?:abs|pdf)\/|10\.48550\/arxiv\.)(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?\/\d{7}(?:v\d+)?)/i)?.[1];
const api = (url, params) => url + '?' + new URLSearchParams(params);
export async function request(url, asText = false, stageSignal) {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (stageSignal?.aborted) controller.abort();
  stageSignal?.addEventListener('abort', cancel, {once: true});
  const timer = setTimeout(cancel, 12000);
  try {
    const response = await fetch(url, {signal: controller.signal, credentials: 'omit'});
    if (!response.ok) throw new Error(response.status === 429 ? '服务暂时限流，请稍后重试' : `HTTP ${response.status}`);
    return asText ? await response.text() : await response.json();
  } finally { clearTimeout(timer); stageSignal?.removeEventListener('abort', cancel); }
}
function add(paper, label, url, kind, source, note = '') {
  if (safeUrl(url) && !paper.links.some(x => x.url === url)) paper.links.push({label, url, kind, source, note});
}
function crPaper(x) {
  const p = {title: x.title?.[0] || x.DOI, doi: x.DOI || '', authors: (x.author || []).slice(0, 3).map(a => [a.given, a.family].filter(Boolean).join(' ')).join(', '), year: String(x.published?.['date-parts']?.[0]?.[0] || x.issued?.['date-parts']?.[0]?.[0] || ''), venue: x['container-title']?.[0] || '', origin: 'Crossref', links: []};
  if (p.doi) add(p, '出版社 / DOI', 'https://doi.org/' + p.doi, 'publisher', 'Crossref', '可能需要机构订阅');
  for (const link of x.link || []) if (link['content-type'] === 'application/pdf') add(p, '出版社 PDF', link.URL, 'publisher', 'Crossref', '可能需要订阅');
  return p;
}
function pmcLinks(p, x) {
  for (const link of x.fullTextUrlList?.fullTextUrl || []) {
    if (link.availabilityCode === 'OA' || link.availability === 'Open access') {
      const pdf = link.documentStyle?.toLowerCase() === 'pdf';
      add(p, pdf ? '开放 PDF' : '开放原文', link.url, pdf ? 'pdf' : 'fulltext', 'Europe PMC', '服务标注的开放版本');
    }
  }
  if (x.pmcid && x.isOpenAccess === 'Y') add(p, 'PMC 原文 / 下载', `https://pmc.ncbi.nlm.nih.gov/articles/${x.pmcid}/`, 'fulltext', 'Europe PMC');
}
function pmcPaper(x) {
  const p = {title: x.title, doi: x.doi || '', authors: x.authorString || '', year: x.pubYear || '', venue: x.journalInfo?.journal?.title || '', origin: 'Europe PMC', links: []};
  pmcLinks(p, x);
  if (p.doi) add(p, '出版社 / DOI', 'https://doi.org/' + p.doi, 'publisher', 'Europe PMC', '可能需要机构订阅');
  return p;
}
const pmc = async (query, signal) => (await request(api('https://www.ebi.ac.uk/europepmc/webservices/rest/search', {query, format: 'json', resultType: 'core', pageSize: 5}), false, signal)).resultList?.result || [];
export function parseArxiv(xml) {
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  if (doc.querySelector('parsererror')) throw new Error('arXiv 返回内容无法解析');
  return [...doc.getElementsByTagNameNS('http://www.w3.org/2005/Atom', 'entry')].map(entry => {
    const tag = name => entry.getElementsByTagNameNS('http://www.w3.org/2005/Atom', name)[0]?.textContent || '';
    const url = tag('id').replace(/^http:/, 'https:');
    if (!url.includes('arxiv.org/abs/')) return null;
    const p = {title: tag('title').replace(/\s+/g, ' ').trim(), doi: entry.getElementsByTagNameNS('http://arxiv.org/schemas/atom', 'doi')[0]?.textContent || '', authors: [...entry.getElementsByTagNameNS('http://www.w3.org/2005/Atom', 'name')].slice(0, 3).map(x => x.textContent).join(', '), year: tag('published').slice(0, 4), venue: 'arXiv', origin: 'arXiv', links: []};
    add(p, 'arXiv PDF', url.replace('/abs/', '/pdf/'), 'pdf', 'arXiv', '预印本版本');
    add(p, 'arXiv 原文页', url, 'fulltext', 'arXiv', '预印本版本');
    return p;
  }).filter(Boolean);
}
let lastArxiv = 0;
async function arxiv(query, ident = '', signal) {
  const wait = Math.max(0, 3000 - (Date.now() - lastArxiv));
  if (wait) await new Promise(resolve => setTimeout(resolve, wait));
  lastArxiv = Date.now();
  return parseArxiv(await request(api('https://export.arxiv.org/api/query', ident ? {id_list: ident} : {search_query: `ti:"${query.replaceAll('"', ' ')}"`, max_results: 3}), true, signal));
}
function similarity(a, b) {
  a = normalize(a); b = normalize(b);
  if (a === b) return 1;
  if (!a || !b) return 0;
  const grams = s => { const m = new Map(); for (let i = 0; i < s.length - 1; i++) m.set(s.slice(i, i + 2), (m.get(s.slice(i, i + 2)) || 0) + 1); return m; };
  const left = grams(a), right = grams(b);
  let same = 0; for (const [key, n] of left) same += Math.min(n, right.get(key) || 0);
  return 2 * same / (a.length + b.length - 2 || 1);
}
export function merge(papers, query) {
  const result = [];
  for (const p of papers) {
    if (!p.title) continue;
    // 不把相同标题、不同 DOI 的论文合并；这样自动打开不会混淆同名论文。
    const old = result.find(x => (x.doi && p.doi && x.doi.toLowerCase() === p.doi.toLowerCase()) || ((!x.doi || !p.doi) && normalize(x.title) === normalize(p.title) && (!x.authors || !p.authors || normalize(x.authors) === normalize(p.authors))));
    if (old) { for (const link of p.links) add(old, link.label, link.url, link.kind, link.source, link.note); }
    else { p.score = similarity(query, p.title); result.push(p); }
  }
  return result.sort((a, b) => b.score - a.score).slice(0, 5);
}
export function automaticTarget(result) {
  if (result.matchesReady === false) return '';
  let paper;
  if (result.precise && result.papers.length === 1) paper = result.papers[0];
  else if (!result.fromPage) {
    const exact = result.papers.filter(x => normalize(x.title) === normalize(result.query));
    if (exact.length === 1) paper = exact[0];
  }
  if (!paper) return '';
  return [...paper.links].sort((a, b) => ({pdf: 0, fulltext: 1, publisher: 2}[a.kind] - {pdf: 0, fulltext: 1, publisher: 2}[b.kind])).find(x => safeUrl(x.url) && (result.complete !== false || result.precise || ['pdf', 'fulltext'].includes(x.kind)))?.url || '';
}
// Only settled responses within the stage window may modify results.
export async function runStage(jobs, budget, notes, publish = () => {}, hasResult) {
  if (!jobs.length) return;
  const controller = new AbortController(), pending = new Set(jobs);
  let closed = false, timer;
  const tasks = jobs.map(job => Promise.resolve().then(() => job.run(controller.signal)).then(data => {
    if (closed) return;
    job.apply(data); publish();
  }).catch(error => { if (!closed) notes.push(job.name + '：' + error.message); }).finally(() => pending.delete(job)));
  try {
    await Promise.race([Promise.all(tasks), new Promise(resolve => { timer = setTimeout(() => { if (hasResult && !hasResult()) timer = setTimeout(resolve, Math.max(0, 14000 - budget)); else resolve(); }, budget); })]);
  } finally {
    closed = true; clearTimeout(timer);
    for (const job of pending) notes.push(job.name + '：响应较慢，本次已跳过；可再次查询补充。');
    controller.abort();
  }
}
const hasOpen = p => p.links.some(x => ['pdf', 'fulltext'].includes(x.kind));
function identifierPaper(doi, ident = '') {
  const p = {title: ident ? 'arXiv:' + ident : doi, doi, origin: ident ? 'arXiv' : 'DOI', links: []};
  if (ident) {
    add(p, 'arXiv PDF', 'https://arxiv.org/pdf/' + ident, 'pdf', 'arXiv', '预印本版本；入口由编号生成');
    add(p, 'arXiv 原文页', 'https://arxiv.org/abs/' + ident, 'fulltext', 'arXiv', '预印本');
  } else add(p, '出版社 / DOI', 'https://doi.org/' + doi, 'publisher', 'DOI', '由 DOI 生成的入口；请核对论文信息');
  return p;
}
function metadata(p, fresh) {
  const links = p.links, doi = p.doi;
  Object.assign(p, fresh, {links, doi: doi || fresh.doi});
  for (const link of fresh.links) add(p, link.label, link.url, link.kind, link.source, link.note);
}
function oaJobs(p, email, semantic) {
  if (!p.doi) return [];
  const jobs = [{name: 'Europe PMC', run: signal => pmc(`DOI:"${p.doi}"`, signal), apply: items => {
    for (const x of items) if (x.doi?.toLowerCase() === p.doi.toLowerCase()) { pmcLinks(p, x); if (p.title === p.doi) { p.title = x.title; p.authors = x.authorString; p.year = x.pubYear; } }
  }}];
  if (semantic) jobs.push({name: 'Semantic Scholar', run: signal => request('https://api.semanticscholar.org/graph/v1/paper/DOI:' + encodeURIComponent(p.doi) + '?fields=title,openAccessPdf,externalIds', false, signal), apply: x => {
    if (x.openAccessPdf?.url) add(p, '开放 PDF', x.openAccessPdf.url, 'pdf', 'Semantic Scholar', '开放版本，可能为作者稿');
    if (p.title === p.doi && x.title) p.title = x.title;
    const id = x.externalIds?.ArXiv;
    if (id && /^[\w.-]+(?:\/\d{7})?$/.test(id)) add(p, 'arXiv PDF', 'https://arxiv.org/pdf/' + id, 'pdf', 'Semantic Scholar', '预印本');
  }});
  if (email) jobs.push({name: 'Unpaywall', run: signal => request(api('https://api.unpaywall.org/v2/' + encodeURIComponent(p.doi), {email}), false, signal), apply: x => {
    for (const loc of [x.best_oa_location, ...(x.oa_locations || [])].filter(Boolean).slice(0, 5)) {
      add(p, '开放 PDF', loc.url_for_pdf, 'pdf', 'Unpaywall', loc.version);
      add(p, '开放原文', loc.url_for_landing_page, 'fulltext', 'Unpaywall', loc.version);
    }
  }});
  return jobs;
}
export async function lookup(input, email = '', progress = () => {}, onResult = () => {}) {
  if (input.error) throw new Error(input.error);
  let query = (input.query || '').trim(), notes = [], papers = [], precise = false;
  const fromPage = input.source === 'page';
  if (fromPage && (!input.page || input.page.blocked)) throw new Error('页面尚未显示推送正文。请在原标签页完成验证后，再右键查询当前页面。');
  if (query.length > 20000) throw new Error('请选择具体的论文标题或 DOI。');
  let dois = extractDois(query), ident = arxivId(query);
  if (fromPage) {
    const page = input.page;
    dois = extractDois((page.dois || []).join(' '));
    const meta = dois.length > 0;
    if (!meta) dois = extractDois(page.text + '\n' + (page.links || []).join('\n'));
    ident = arxivId(page.text + '\n' + (page.links || []).join('\n'));
    precise = meta && dois.length === 1;
    query = page.citationTitle || page.title || '';
    if (dois.length > 1) notes.push('页面含多个 DOI，可能包括参考文献；请核对结果。');
    if (!dois.length && !ident && !page.citationTitle) notes.push('网页标题仅用于检索候选；可选中正文中的英文论文标题重新查找。');
  } else precise = dois.length === 1 || !!ident;
  let matchesReady = !!(dois.length || ident);
  const snapshot = complete => structuredClone({query, papers, notes: [...new Set(notes)], precise, fromPage, complete, matchesReady});
  const publish = () => { if (papers.length) onResult(snapshot(false)); };
  const identifiers = !!(dois.length || ident);
  progress('正在并行查询，结果到达即可打开…');
  if (identifiers) {
    const jobs = [];
    for (const [index, doi] of (dois.length ? dois.slice(0, 5) : ['']).entries()) {
      const id = /^10\.48550\/arxiv\./i.test(doi) ? arxivId(doi) : (!dois.length ? ident : '');
      const p = identifierPaper(doi, id); papers.push(p);
      if (id) jobs.push({name: 'arXiv', run: signal => arxiv('', id, signal), apply: values => { if (values[0]) metadata(p, values[0]); }});
      else {
        jobs.push({name: 'Crossref', run: signal => request('https://api.crossref.org/works/' + encodeURIComponent(doi), false, signal), apply: data => metadata(p, crPaper(data.message))});
        jobs.push(...oaJobs(p, email, index === 0));
      }
    }
    publish();
    await runStage(jobs, 14000, notes, publish);
  } else {
    if (/^https?:\/\//i.test(query)) throw new Error('选中的是推送链接。请先打开推送，然后右键“查找当前页面中的论文”，或选中英文标题 / DOI 查询。');
    if (query.length < 5 || query.length > 1000) throw new Error('请选择完整论文标题或 DOI，避免选择整篇推送。');
    const found = [];
    const accept = values => { found.push(...values); papers = merge(found, query); };
    await runStage([
      {name: 'Crossref', run: signal => request(api('https://api.crossref.org/works', {'query.title': query, rows: 10, select: 'DOI,title,author,published,container-title,link'}), false, signal), apply: x => accept((x.message?.items || []).map(crPaper))},
      {name: 'Europe PMC', run: signal => pmc(`TITLE:"${query.replaceAll('"', ' ')}"`, signal), apply: x => accept(x.map(pmcPaper))},
      {name: 'arXiv', run: signal => arxiv(query, '', signal), apply: accept}
    ], 5000, notes, publish, () => papers.length > 0);
    matchesReady = true; publish();
  }
  if (!papers.length) throw new Error('没有找到文献。请尝试英文论文标题或 DOI。' + (notes.length ? '\n' + notes.join('\n') : ''));
  if (!identifiers) {
    progress('已有结果可直接打开，正在补充开放原文…');
    await runStage(papers.slice(0, 3).flatMap((p, i) => hasOpen(p) ? [] : oaJobs(p, email, i === 0)), 6000, notes, publish);
  }
  for (const p of papers) p.links.sort((a, b) => ({pdf: 0, fulltext: 1, publisher: 2}[a.kind] - {pdf: 0, fulltext: 1, publisher: 2}[b.kind]));
  return snapshot(true);
}
