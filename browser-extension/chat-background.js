// Restricted, capability-based bridge. Never proxy arbitrary URLs or local paths.
export function descriptor(value) {
  const match = /^(\d{1,5})\.([A-Za-z0-9_-]{43})$/.exec(value || '');
  if (!match || +match[1] < 1024 || +match[1] > 65535) throw new Error('无效的文献直达选区地址。');
  return {port: +match[1], token: match[2]};
}

export function chatRoute(value) {
  try {
    const url = new URL(value);
    if (url.origin !== 'https://chatgpt.com') return '';
    if (url.pathname === '/') return url.origin + '/';
    if (/^\/c\/[a-zA-Z0-9-]{8,100}$/.test(url.pathname)) return url.origin + url.pathname;
  } catch (_) { /* invalid URL */ }
  return '';
}

async function localRequest(value, suffix = '', body) {
  const {port, token} = descriptor(value);
  if (suffix && !/^\/(?:file\/\d+\/\d+|bind)$/.test(suffix)) throw new Error('无效请求。');
  const response = await fetch(`http://127.0.0.1:${port}/handoff/${token}${suffix}`, {
    method: body ? 'POST' : 'GET', cache: 'no-store', credentials: 'omit', redirect: 'error',
    headers: {'X-PaperQuick': '1', ...(body ? {'Content-Type': 'application/json'} : {})},
    ...(body ? {body: JSON.stringify(body)} : {}), signal: AbortSignal.timeout(15000)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '本地文献请求未完成。');
  return result;
}

async function route(message, sender) {
  const tabId = sender.tab.id;
  const request = message.descriptor;
  descriptor(request);
  const payload = await localRequest(request);
  const mapKey = 'chat-tab:' + payload.key;
  const saved = (await chrome.storage.session.get(mapKey))[mapKey];
  if (saved?.tabId != null && saved.tabId !== tabId) {
    let previous;
    try { previous = await chrome.tabs.get(saved.tabId); } catch (_) { /* closed tab */ }
    const expected = payload.url || 'https://chatgpt.com/';
    if (previous && chatRoute(previous.url) === expected) {
      const accepted = await chrome.tabs.sendMessage(previous.id, {type: 'paperQuickChatDeliver', descriptor: request});
      if (!accepted?.ok) throw new Error(accepted?.error || '原对话仍在处理选区，请完成后重试。');
      await chrome.tabs.update(previous.id, {active: true});
      // Only the newly opened, token-bearing handoff tab is disposable.
      await chrome.tabs.remove(tabId);
      return {ok: true, redirected: true};
    }
  }
  const expected = payload.url || 'https://chatgpt.com/';
  if (chatRoute(sender.url) !== expected) throw new Error('对话地址不匹配，请从文献阅读页重新打开。');
  await chrome.storage.session.set({[mapKey]: {tabId}, ['chat-pending:' + tabId]: {descriptor: request, route: expected}});
  return {ok: true, payload};
}

export function installChatBridge() {
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !sender.tab ||
        !chatRoute(sender.url) || !message?.type?.startsWith('paperQuickChat')) return false;
    const execute = async () => {
      const pendingKey = 'chat-pending:' + sender.tab.id;
      if (message.type === 'paperQuickChatRoute') return route(message, sender);
      if (message.type === 'paperQuickChatResume') {
        const saved = (await chrome.storage.session.get(pendingKey))[pendingKey];
        return {ok: true, descriptor: saved?.route === chatRoute(sender.url) ? saved.descriptor : ''};
      }
      if (message.type === 'paperQuickChatPayload') {
        const payload = await localRequest(message.descriptor);
        const expected = payload.url || 'https://chatgpt.com/';
        if (chatRoute(sender.url) !== expected) throw new Error('当前页面已切换，请重新打开选区。');
        await chrome.storage.session.set({[pendingKey]: {descriptor: message.descriptor, route: expected}});
        return {ok: true, payload};
      }
      if (message.type === 'paperQuickChatChunk') {
        if (!Number.isSafeInteger(message.index) || message.index < 0 ||
            !Number.isSafeInteger(message.part) || message.part < 0) throw new Error('无效附件分块。');
        return {ok: true, ...await localRequest(message.descriptor, `/file/${message.index}/${message.part}`)};
      }
      if (message.type === 'paperQuickChatBind') {
        const url = chatRoute(sender.url);
        if (!url || url.endsWith('/')) throw new Error('请先发送一条消息，形成可保存的普通对话。');
        await localRequest(message.descriptor, '/bind', {url, primaryAttached: message.primaryAttached === true});
        await chrome.storage.session.remove(pendingKey);
        return {ok: true};
      }
      throw new Error('无效的 ChatGPT 请求。');
    };
    execute().then(respond, error => respond({ok: false, error: error.message || '请保持文献直达运行，并重新右键打开选区。'}));
    return true;
  });
}
