// Restricted, capability-based bridge. Never proxy arbitrary URLs or local paths.
import './ai-sites.js';
export function descriptor(value) {
  const match = /^(\d{1,5})\.([A-Za-z0-9_-]{43})$/.exec(value || '');
  if (!match || +match[1] < 1024 || +match[1] > 65535) throw new Error('无效的文献直达选区地址。');
  return {port: +match[1], token: match[2]};
}

export function chatRoute(value) {
  try {
    const url = new URL(value);
    if(url.username||url.password||url.port)return '';
    for(const site of Object.values(globalThis.PaperQuickAISites)){
      const home=new URL(site.home);
      if(url.origin===home.origin&&(url.pathname===home.pathname||site.conversation.test(url.pathname)))return url.origin+url.pathname;
    }
  } catch (_) { /* invalid URL */ }
  return '';
}

async function currentRoute(sender){
  // MessageSender.url can remain the document's initial URL after pushState.
  // ChatGPT creates /c/... without replacing that document.
  const tab=await chrome.tabs.get(sender.tab.id);
  const route=chatRoute(tab.url);
  if(!route)throw new Error('当前标签页已离开 ChatGPT。');
  return route;
}

async function localRequest(value, suffix = '', body) {
  const {port, token} = descriptor(value);
  if (suffix && !/^\/(?:file\/\d+\/\d+|bind|status|reply)$/.test(suffix)) throw new Error('无效请求。');
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
    const expected = payload.url || payload.home || 'https://chatgpt.com/';
    if (previous && chatRoute(previous.url) === expected) {
      const accepted = await chrome.tabs.sendMessage(previous.id, {type: 'paperQuickChatDeliver', descriptor: request});
      if (!accepted?.ok) throw new Error(accepted?.error || '原对话仍在处理选区，请完成后重试。');
      await chrome.tabs.update(previous.id, {active: true});
      // Only the newly opened, token-bearing handoff tab is disposable.
      await chrome.tabs.remove(tabId);
      return {ok: true, redirected: true};
    }
  }
  const expected = payload.url || payload.home || 'https://chatgpt.com/';
  if (await currentRoute(sender) !== expected) throw new Error('对话地址不匹配，请从文献阅读页重新打开。');
  await chrome.storage.session.set({[mapKey]: {tabId}, ['chat-pending:' + tabId]: {descriptor: request, route: expected}});
  return {ok: true, payload};
}

export function installChatBridge() {
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !sender.tab || !message?.type?.startsWith('paperQuickChat')) return false;
    let launcher=false;
    try{
      const url=new URL(sender.url),match=/^\/handoff\/([A-Za-z0-9_-]{43})\/open$/.exec(url.pathname);
      launcher=message.type==='paperQuickChatLaunch'&&url.protocol==='http:'&&url.hostname==='127.0.0.1'&&
        !!match&&message.descriptor===url.port+'.'+match[1];
    }catch(_){}
    if(!launcher&&!chatRoute(sender.url))return false;
    const execute = async () => {
      const pendingKey = 'chat-pending:' + sender.tab.id;
      if(launcher){
        const payload=await localRequest(message.descriptor);
        const expected=payload.url||payload.home||'https://chatgpt.com/';
        if(!chatRoute(expected))throw new Error('文献对话地址无效。');
        await chrome.storage.session.set({[pendingKey]:{descriptor:message.descriptor,route:expected}});
        await localRequest(message.descriptor,'/status',{state:'extension-connected'});
        await chrome.tabs.update(sender.tab.id,{url:expected+'#paperquick='+message.descriptor});
        return {ok:true};
      }
      if (message.type === 'paperQuickChatRoute') return route(message, sender);
      if (message.type === 'paperQuickChatResume') {
        const saved = (await chrome.storage.session.get(pendingKey))[pendingKey];
        const replyKey='chat-reply:'+sender.tab.id;
        const reply=(await chrome.storage.session.get(replyKey))[replyKey];
        const url=await currentRoute(sender);
        return {ok: true, descriptor: saved?.route === url ? saved.descriptor : '',replyDescriptor:reply?.route===url?reply.descriptor:''};
      }
      if(message.type==='paperQuickChatReply'){
        const url=await currentRoute(sender),key='chat-replies:'+sender.tab.id;
        const allowed=(await chrome.storage.session.get(key))[key]||[];
        if(!allowed.some(item=>item.descriptor===message.descriptor&&item.route===url))throw new Error('当前对话没有这篇文献的回存授权，请从阅读器重新连接。');
        if(typeof message.text!=='string'||!message.text.trim()||message.text.length>100000)throw new Error('请选择一条有效回复（最多 10 万字）。');
        return await localRequest(message.descriptor,'/reply',{url,text:message.text,messageId:String(message.messageId||'').slice(0,200)});
      }
      if (message.type === 'paperQuickChatPayload') {
        const payload = await localRequest(message.descriptor);
        const expected = payload.url || payload.home || 'https://chatgpt.com/';
        if (await currentRoute(sender) !== expected) throw new Error('当前页面已切换，请重新打开选区。');
        await chrome.storage.session.set({[pendingKey]: {descriptor: message.descriptor, route: expected}});
        return {ok: true, payload};
      }
      if (message.type === 'paperQuickChatChunk') {
        if (!Number.isSafeInteger(message.index) || message.index < 0 ||
            !Number.isSafeInteger(message.part) || message.part < 0) throw new Error('无效附件分块。');
        const payload=await localRequest(message.descriptor);
        if(await currentRoute(sender)!==(payload.url||payload.home||'https://chatgpt.com/'))throw new Error('当前页面与文献请求不匹配。');
        return {ok: true, ...await localRequest(message.descriptor, `/file/${message.index}/${message.part}`)};
      }
      if(message.type==='paperQuickChatStatus')return {ok:true,...await localRequest(message.descriptor,'/status',{state:message.state,detail:message.detail||''})};
      if (message.type === 'paperQuickChatBind') {
        const url = await currentRoute(sender);
        if (!url || url.endsWith('/')) throw new Error('请先发送一条消息，形成可保存的普通对话。');
        await localRequest(message.descriptor, '/bind', {url, primaryAttached: message.primaryAttached === true});
        const reply={descriptor:message.descriptor,route:url},key='chat-replies:'+sender.tab.id;
        const allowed=(await chrome.storage.session.get(key))[key]||[];
        await chrome.storage.session.set({['chat-reply:'+sender.tab.id]:reply,[key]:[...allowed.filter(item=>item.descriptor!==message.descriptor).slice(-63),reply]});
        await chrome.storage.session.remove(pendingKey);
        return {ok: true};
      }
      throw new Error('无效的 ChatGPT 请求。');
    };
    execute().then(respond, error => respond({ok: false, error: error.message || '请保持文献直达运行，并重新右键打开选区。'}));
    return true;
  });
}
