/* ChatGPT DOM adapter: stage drafts/files only. Never press Send or read cookies. */
(() => {
  let busy = false, current = null, panel, status, retry, watch, binding = false;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const route = () => location.origin + location.pathname;
  const normalize = text => (text || '').replace(/\s+/g, ' ').trim();
  const isConversation = () => /^\/c\/[a-zA-Z0-9-]{8,100}$/.test(location.pathname);
  const composer = () => document.querySelector('#prompt-textarea[contenteditable="true"], textarea#prompt-textarea, [data-testid="composer"] [contenteditable="true"]');

  function notice(text, canRetry = false) {
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'paperquick-chat-status';
      const shadow = panel.attachShadow({mode: 'closed'});
      const box = document.createElement('div');
      box.style.cssText = 'position:fixed;right:20px;top:20px;z-index:2147483647;max-width:380px;padding:14px 18px;border:1px solid #a7c7e8;border-radius:12px;background:#f4f9ff;color:#163758;font:14px/1.6 system-ui;box-shadow:0 6px 28px #0002';
      status = document.createElement('div');
      retry = document.createElement('button'); retry.textContent = '重试准备选区';
      retry.onclick = () => { if (current?.prepared) saveBinding(); else if (current) deliver(current.descriptor); };
      const close = document.createElement('button'); close.textContent = '收起';
      close.onclick = () => { panel.hidden = true; };
      for (const button of [retry, close]) button.style.cssText = 'margin:8px 8px 0 0;padding:4px 10px;cursor:pointer';
      box.append(status, retry, close); shadow.append(box); document.documentElement.append(panel);
    }
    panel.hidden = false; status.textContent = '文献直达 · ' + text; retry.hidden = !canRetry;
  }

  async function rpc(type, extra = {}) {
    const result = await chrome.runtime.sendMessage({type: 'paperQuickChat' + type, ...extra});
    if (!result?.ok) throw new Error(result?.error || '扩展连接中断，请重新加载扩展后再试。');
    return result;
  }

  async function waitFor(find, timeout = 30000) {
    const until = Date.now() + timeout;
    while (Date.now() < until) { const value = find(); if (value) return value; await sleep(250); }
    throw new Error('尚未找到可用输入框或文件控件。请先登录 ChatGPT；网页更新时可能需要调整扩展。');
  }

  function draftText(editor) {
    return ('value' in editor ? editor.value : editor.innerText || editor.textContent || '').trim();
  }

  function fillDraft(editor, text) {
    if (draftText(editor)) throw new Error('对话框已有未发送文字，请先发送或清空，再点“重试准备选区”。');
    if (editor.tagName === 'TEXTAREA') {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(editor, text);
    } else {
      // Plain DOM text, never HTML from a paper. Works with the ProseMirror editor.
      editor.replaceChildren(...text.split('\n').map(line => {
        const p = document.createElement('p'); p.textContent = line;
        if (!line) p.append(document.createElement('br'));
        return p;
      }));
    }
    editor.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
  }

  function composerArea(editor) { return editor.closest('form') || editor.parentElement?.parentElement; }
  function attachmentPresent(editor, name) {
    const area = composerArea(editor);
    if (!area) return false;
    // A filename in the draft itself is not evidence of an attachment.
    return [...area.querySelectorAll('[data-testid*="attachment"], [data-testid*="file"], [aria-label], [title]')]
      .some(node => !editor.contains(node) && !node.contains(editor) &&
        [node.textContent, node.getAttribute('aria-label'), node.getAttribute('title')].some(text => text?.includes(name)));
  }

  async function fileInput(editor) {
    let input = document.querySelector('input[type="file"]:not([accept^="image/"])');
    if (input) return input;
    const area = composerArea(editor);
    const add = area?.querySelector('[data-testid="composer-plus-btn"], button[aria-label*="Attach"], button[aria-label*="添加"], button[aria-label*="附件"]');
    if (add) {
      add.click(); await sleep(200);
      const menu = [...document.querySelectorAll('[role="menuitem"]')].find(el => /upload|add photos|添加照片|上传文件|添加文件/i.test(el.textContent || ''));
      // Avoid opening the OS file picker: only use an input already mounted by the menu.
      input = document.querySelector('input[type="file"]:not([accept^="image/"])');
      if (!input && menu) {
        throw new Error('网页未提供可自动附加的文件控件。请用网页附件菜单手动上传正文，再重试文字填入。');
      }
    }
    if (!input) throw new Error('未找到文件控件。请先展开 ChatGPT 的附件菜单，再点击重试。');
    return input;
  }

  async function attach(editor, payload, request) {
    const missing = payload.files.map((file, index) => ({...file, index})).filter(file => !attachmentPresent(editor, file.name));
    if (!missing.length) return;
    let input;
    try { input = await fileInput(editor); } catch (_) { /* Use the web composer's drop handler below. */ }
    // Some file inputs accept images only; do not silently feed a PDF into those.
    if (input?.accept && !/pdf|document|\*|\.txt|\.docx/i.test(input.accept) && missing.some(file => file.primary)) {
      throw new Error('当前附件控件仅支持图片，请展开可上传文档的附件入口后重试。');
    }
    for (const file of missing) {
      const chunks = [];
      for (let part = 0; part < file.chunks; part++) {
        const {data} = await rpc('Chunk', {descriptor: request, index: file.index, part});
        chunks.push(Uint8Array.from(atob(data), ch => ch.charCodeAt(0)));
      }
      const types = {pdf: 'application/pdf', docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', txt: 'text/plain', md: 'text/markdown', png: 'image/png'};
      const transfer = new DataTransfer();
      transfer.items.add(new File(chunks, file.name, {type: types[file.name.split('.').pop().toLowerCase()] || 'application/octet-stream'}));
      if (input?.isConnected) {
        input.files = transfer.files;
        input.dispatchEvent(new Event('change', {bubbles: true}));
      } else {
        editor.dispatchEvent(new DragEvent('dragenter', {bubbles: true, cancelable: true, dataTransfer: transfer}));
        editor.dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: transfer}));
        editor.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: transfer}));
      }
      await waitFor(() => attachmentPresent(editor, file.name), 12000);
    }
  }

  async function saveBinding() {
    if (!current?.prepared || binding || !isConversation()) return;
    // A conversation URL by itself is insufficient: wait until this draft was sent.
    const editor = composer();
    if (!editor || draftText(editor)) return;
    const messages = [...document.querySelectorAll('[data-message-author-role="user"]')];
    const latest = messages.at(-1);
    if (!latest || latest === current.previousMessage) return;
    const sentTurn = latest.closest('[data-testid^="conversation-turn"]') || latest.parentElement || latest;
    const sentText = normalize(sentTurn.innerText || sentTurn.textContent);
    if (!sentText.includes(current.lastDraft)) return;
    const primary = current.payload.files.find(file => file.primary);
    binding = true;
    try {
      await rpc('Bind', {descriptor: current.descriptor, primaryAttached: !!(primary && current.primaryAttached && sentText.includes(primary.name))});
      current.editor?.removeEventListener('input', current.trackDraft);
      current = null;
      notice('对话已与这篇文献绑定，下次选区将继续此对话。');
      clearInterval(watch); watch = null;
    } catch (error) { clearInterval(watch); watch = null; notice('对话绑定未完成：' + error.message, true); }
    finally { binding = false; }
  }

  async function deliver(request, suppliedPayload) {
    if (busy) throw new Error('当前选区仍在准备，请稍后再试。');
    if (current?.prepared) {
      await saveBinding();
      if (current?.prepared && request !== current.descriptor) throw new Error('上一选区尚未发送，请先发送或完成当前操作。');
    }
    busy = true;
    current = {descriptor: request, prepared: false};
    try {
      const payload = suppliedPayload || (await rpc('Payload', {descriptor: request})).payload;
      current.payload = payload;
      const expected = payload.url || 'https://chatgpt.com/';
      if (route() !== expected) throw new Error('当前页面已切换，请回阅读页重新打开选区。');
      notice('正在准备选区和文献附件，请保持软件运行。');
      const editor = await waitFor(composer);
      current.previousMessage = [...document.querySelectorAll('[data-message-author-role="user"]')].at(-1);
      if (draftText(editor)) throw new Error('对话框已有未发送文字，请先发送或清空，再点“重试准备选区”。');
      await attach(editor, payload, request);
      fillDraft(editor, payload.prompt);
      current.lastDraft = normalize(payload.prompt);
      current.editor = editor;
      current.trackDraft = () => { const text = normalize(draftText(editor)); if (current?.prepared && text) current.lastDraft = text; };
      editor.addEventListener('input', current.trackDraft);
      current.primaryAttached = payload.files.some(file => file.primary && attachmentPresent(editor, file.name));
      current.prepared = true;
      notice('已填入选区并准备附件，请核对上传状态后点击发送。');
      clearInterval(watch); watch = setInterval(saveBinding, 1500);
    } catch (error) { notice(error.message, true); }
    finally { busy = false; }
  }

  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id || message?.type !== 'paperQuickChatDeliver') return false;
    (async () => {
      if (current?.prepared) await saveBinding();
      if (busy || current?.prepared) throw new Error('原对话尚有未发送选区，请先完成后再重试。');
      deliver(message.descriptor);
      return {ok: true};
    })().then(respond, error => respond({ok: false, error: error.message}));
    return true;
  });

  async function begin() {
    const value = /^#paperquick=(\d{1,5}\.[A-Za-z0-9_-]{43})$/.exec(location.hash)?.[1];
    try {
      if (value) {
        const result = await rpc('Route', {descriptor: value});
        if (!result.redirected) {
          history.replaceState(history.state, '', location.pathname + location.search);
          await deliver(value, result.payload);
        }
      } else if (!current) {
        const result = await rpc('Resume');
        if (result.descriptor) await deliver(result.descriptor);
      }
    } catch (error) { current = value ? {descriptor: value} : null; notice(error.message, !!value); }
  }
  addEventListener('hashchange', begin);
  begin();
})();
