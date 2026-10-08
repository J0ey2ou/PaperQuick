// 该函数会注入到用户主动查询的当前页，不依赖外部绑定。
export function readPage() {
  const meta = name => [...document.querySelectorAll('meta')].filter(x => (x.name || x.getAttribute('property') || '').toLowerCase() === name).map(x => x.content).filter(Boolean);
  const content = document.querySelector('#js_content') || document.querySelector('article') || document.body;
  const text = (content?.innerText || '').slice(0, 100000);
  const title = meta('citation_title')[0] || document.querySelector('#activity-name')?.innerText?.trim() || meta('og:title')[0] || document.title;
  const blocked = !document.querySelector('#js_content') && /环境异常|访问过于频繁|完成验证后|请在微信客户端打开/.test(text) && !meta('citation_title').length;
  return {title, citationTitle: meta('citation_title')[0] || '', dois: [...meta('citation_doi'), ...meta('dc.identifier'), ...meta('dc.identifier.doi')], text: blocked ? '' : text, links: blocked ? [] : [...(content?.querySelectorAll('a[href]') || [])].slice(0, 250).map(x => x.href), pdfs: meta('citation_pdf_url'), blocked, url: location.href};
}
