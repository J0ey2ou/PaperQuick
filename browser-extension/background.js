import {readPage} from './page-reader.js';

async function menus() {
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({id: 'selection', title: '查找文献并打开原文：%s', contexts: ['selection']});
  chrome.contextMenus.create({id: 'page', title: '查找当前页面中的论文', contexts: ['page']});
}
chrome.runtime.onInstalled.addListener(menus);
chrome.runtime.onStartup.addListener(menus);

export async function launch(info, tab) {
  const request = {query: (info.selectionText || '').trim().slice(0, 20000), sourceUrl: info.pageUrl || tab?.url || '', source: info.selectionText ? 'selection' : 'page', createdAt: Date.now()};
  // 只有查询整个页面时才读取当前页；选词查询不读取周围正文。
  if (!request.query && tab?.id != null) {
    try {
      const values = await chrome.scripting.executeScript({target: {tabId: tab.id, frameIds: [info.frameId || 0]}, func: readPage});
      request.page = values[0]?.result;
    } catch (_) {
      request.error = '这个页面不允许扩展读取。请选中论文标题后右键查询，或直接在查询页粘贴标题 / DOI。';
    }
  }
  const key = 'query-' + crypto.randomUUID();
  // 仅本次浏览器会话临时保存，打开结果后立即移除；无持久查询历史。
  await chrome.storage.session.set({[key]: request});
  await chrome.tabs.create({url: chrome.runtime.getURL('results.html') + '#' + key});
}
chrome.contextMenus.onClicked.addListener((info, tab) => launch(info, tab).catch(console.error));
chrome.action.onClicked.addListener(tab => launch({}, tab).catch(console.error));
// 扩展自己的页面也可发起一次查询；不向外部网站公开消息入口。
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || message?.type !== 'paperQuickLookup') return false;
  launch(message.info || {}, sender.tab).then(() => respond({ok: true}), error => respond({ok: false, error: error.message}));
  return true;
});
