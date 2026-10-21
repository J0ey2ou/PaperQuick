/* ChatGPT DOM adapter: stage drafts/files only. Never press Send or read cookies. */
(() => {
  // Capture before the site's startup scripts normalize history/hash routes.
  const initialDescriptor=/^#paperquick=(\d{1,5}\.[A-Za-z0-9_-]{43})$/.exec(location.hash)?.[1];
  let busy = false, current = null, panel, status, retry, watch, binding = false;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const route = () => location.origin + location.pathname;
  const normalize = text => (text || '').replace(/\s+/g, ' ').trim();
  const isConversation = () => /^\/c\/[a-zA-Z0-9-]{8,100}$/.test(location.pathname);
  let replyContext=null,replyObserver=null,replyTimer=null;
  function enableReplies(descriptor) {
    replyContext={descriptor,url:route(),user:[...document.querySelectorAll('[data-message-author-role="user"]')].at(-1)};
    if(!replyObserver){
      replyObserver=new MutationObserver(()=>{
        if(replyTimer)return;
        replyTimer=setTimeout(()=>{replyTimer=null;scanReplies();},350);
      });
      replyObserver.observe(document.documentElement,{childList:true,subtree:true});
    }
    scanReplies();
  }
  function scanReplies(){
    const context=replyContext;
    if(!context||route()!==context.url||!isConversation())return;
    for(const message of document.querySelectorAll('[data-message-author-role="assistant"]')){
      if(message.querySelector('[data-paperquick-reply]'))continue;
      if(!context.user||!(context.user.compareDocumentPosition(message)&Node.DOCUMENT_POSITION_FOLLOWING))continue;
      if(document.querySelector('[data-testid="stop-button"],button[aria-label="Stop streaming"]'))continue;
      const button=document.createElement('button');button.type='button';button.dataset.paperquickReply='1';
      button.textContent='存为文献批注';button.title='保存到文献直达中本次讨论的原选区 / 页码';
      button.style.cssText='display:block;margin:12px 0 4px;padding:7px 12px;border:1px solid #c9d8d0;border-radius:8px;background:#f3f7f4;color:#295c47;font:13px/1.5 system-ui;cursor:pointer';
      button.onclick=async()=>{
        button.disabled=true;button.textContent='正在回存…';
        try{
          if(route()!==context.url)throw new Error('对话已切换，请重新连接文献。');
          const body=message.querySelector('.markdown')||message;
          const clone=body.cloneNode(true);clone.querySelectorAll('button,[data-paperquick-reply]').forEach(item=>item.remove());
          const text=(clone.innerText||clone.textContent||'').trim();
          const messageId=message.getAttribute('data-message-id')||message.closest('[data-testid^="conversation-turn"]')?.getAttribute('data-testid')||'';
          await rpc('Reply',{descriptor:context.descriptor,text,messageId});
          button.textContent='已保存到文献批注';
        }catch(error){button.disabled=false;button.textContent='重试回存批注';notice(error.message);}
      };
      message.append(button);
    }
  }
  const composer = () => [...document.querySelectorAll('#prompt-textarea[contenteditable="true"], textarea#prompt-textarea, [data-testid="composer"] [contenteditable="true"], .ProseMirror[contenteditable="true"]')]
    .filter(editor => {
      const style = getComputedStyle(editor);
      return editor.isConnected && !editor.disabled && !editor.readOnly &&
        !editor.closest('[hidden], [inert], [aria-hidden="true"]') &&
        style.display !== 'none' && style.visibility === 'visible' &&
        [...editor.getClientRects()].some(rect => rect.width > 0 && rect.height > 0);
    }).sort((a, b) => Number(b.isContentEditable) - Number(a.isContentEditable))[0];

  function notice(text, canRetry = false) {
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'paperquick-chat-status';
      const shadow = panel.attachShadow({mode: 'open'});
      const box = document.createElement('div');
      box.style.cssText = 'position:fixed;right:20px;top:20px;z-index:2147483647;max-width:380px;padding:14px 18px;border:1px solid #a7c7e8;border-radius:12px;background:#f4f9ff;color:#163758;font:14px/1.6 system-ui;box-shadow:0 6px 28px #0002';
      status = document.createElement('div');
      retry = document.createElement('button'); retry.textContent = '重试准备选区';
      const close = document.createElement('button'); close.textContent = '收起';
      close.onclick = () => { panel.hidden = true; };
      for (const button of [retry, close]) button.style.cssText = 'margin:8px 8px 0 0;padding:4px 10px;cursor:pointer';
      box.append(status, retry, close); shadow.append(box); document.documentElement.append(panel);
    }
    panel.hidden = false; status.textContent = '文献直达 · ' + text; retry.hidden = !canRetry;
    retry.onclick = typeof canRetry === 'function' ? canRetry : () => current && deliver(current.descriptor);
  }

  async function rpc(type, extra = {}) {
    const result = await chrome.runtime.sendMessage({type: 'paperQuickChat' + type, ...extra});
    if (!result?.ok) throw new Error(result?.error || '扩展连接中断，请重新加载扩展后再试。');
    return result;
  }

  async function report(state,detail='') {
    if(!current)return;
    try{await rpc('Status',{descriptor:current.descriptor,state,detail:detail.slice(0,600)});}catch(_){}
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
      // Use the browser's editing transaction so rich-text state observes the input.
      // This acts only inside this webpage; it uses no keyboard or clipboard APIs.
      const selection = document.getSelection(), range = document.createRange();
      range.selectNodeContents(editor); selection.removeAllRanges(); selection.addRange(range);
      if (document.execCommand('insertText', false, text) && draftText(editor)) return;
      // Fallback for browsers without the editing command. Always insert plain text.
      editor.replaceChildren(...text.split('\n').map(line => {
        const p = document.createElement('p'); p.textContent = line;
        if (!line) p.append(document.createElement('br'));
        return p;
      }));
    }
    editor.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
  }

  async function stageText(payload) {
    // Hydration can replace an editor after a successful-looking DOM mutation.
    // Require a live, visible editor with stable text before acknowledging delivery.
    let stable = null;
    for (let attempt = 0; attempt < 4; attempt++) {
      const editor = await waitFor(composer);
      if (!draftText(editor)) {
        fillDraft(editor, payload.prompt);
        if (draftText(editor) && normalize(draftText(editor)) !== normalize(payload.prompt))
          throw new Error('网页未完整保留选中文字，请核对输入框后重试。');
      }
      else if (!current.textFilled || (editor !== current.editor && normalize(draftText(editor)) !== current.lastDraft))
        throw new Error('对话框已有未发送文字，请先发送或清空，再点“重试准备选区”。');
      const expected = normalize(draftText(editor));
      if (!expected) continue;
      current.editor = editor; current.textFilled = true; current.lastDraft = expected;
      stable = editor;
      for (let n = 0; n < 8; n++) {
        await sleep(150);
        if (composer() !== editor || !draftText(editor)) { stable = null; break; }
      }
      if (stable) return stable;
    }
    throw new Error('网页尚未保留选中文字，请等待输入框加载完成后重试。');
  }

  function forgetCurrent() {
    current?.editor?.removeEventListener('input', current.trackDraft);
    current = null; clearInterval(watch); watch = null;
  }

  function composerArea(editor) { return editor.closest('form') || editor.parentElement?.parentElement; }
  function attachmentState(editor, name) {
    const area = composerArea(editor);
    if (!area) return '';
    // A filename in the draft itself is not evidence of an attachment.
    const node=[...area.querySelectorAll('*')].reverse().find(node=>!editor.contains(node)&&!node.contains(editor)&&
      ([name].some(value=>normalize(node.textContent)===value||normalize(node.textContent).startsWith(value+' '))||
        [node.getAttribute('aria-label'),node.getAttribute('title')].some(text=>text?.includes(name))));
    if(!node)return '';
    const item=node.closest('[data-upload-state], [data-testid*="attachment"], [data-testid*="file"]')||node.parentElement||node;
    const state=item.getAttribute('data-upload-state')||'';
    if(state==='error'||/upload failed|couldn.t upload|上传失败|无法上传|上传出错/i.test(item.textContent))return 'error';
    if(['uploading','processing','pending','queued','loading'].includes(state)||item.querySelector?.('[role="progressbar"], [aria-busy="true"], [data-state="loading"], .animate-spin')||/uploading|processing|正在上传|正在处理|上传中|处理中/i.test(item.textContent))return 'uploading';
    return 'ready';
  }
  const attachmentPresent=(editor,name)=>['ready','uploading'].includes(attachmentState(editor,name));

  async function fileInput(editor) {
    let input = document.querySelector('input[type="file"]');
    if (input) return input;
    const area = composerArea(editor);
    const add = area?.querySelector('[data-testid="composer-plus-btn"], button[aria-label*="Attach"], button[aria-label*="添加"], button[aria-label*="附件"]');
    if (add) {
      add.click(); await sleep(200);
      const menu = [...document.querySelectorAll('[role="menuitem"]')].find(el => /upload|add photos|添加照片|上传文件|添加文件/i.test(el.textContent || ''));
      // Avoid opening the OS file picker: only use an input already mounted by the menu.
      input = document.querySelector('input[type="file"]');
      if (!input && menu) {
        throw new Error('网页未提供可自动附加的文件控件。请用网页附件菜单手动上传正文，再重试文字填入。');
      }
    }
    if (!input) throw new Error('未找到文件控件。请先展开 ChatGPT 的附件菜单，再点击重试。');
    return input;
  }

  async function attach(editor, payload, request) {
    const stateOf=name=>attachmentState(composer()||editor,name);
    const waitComplete=async file=>{
      await waitFor(()=>{
        const state=stateOf(file.name);
        if(state==='error')throw new Error('ChatGPT 未能上传“'+file.name+'”。请检查网络与附件额度，移除失败附件后重试；选中文字会保留。');
        return state==='ready';
      },120000);
    };
    for (const [index,file] of payload.files.entries()) {
      const existing=stateOf(file.name);
      if(existing==='ready')continue;
      if(existing==='uploading'){await waitComplete(file);continue;}
      if(existing==='error')throw new Error('“'+file.name+'”的上次上传失败。请在 ChatGPT 移除失败附件后再点重试。');
      const chunks = [];
      for (let part = 0; part < file.chunks; part++) {
        let response;
        for(let attempt=0;attempt<3;attempt++){
          try{response=await rpc('Chunk',{descriptor:request,index,part});break;}
          catch(error){if(attempt===2)throw error;await sleep(250*2**attempt);}
        }
        const {data} = response;
        chunks.push(Uint8Array.from(atob(data), ch => ch.charCodeAt(0)));
      }
      if(chunks.reduce((total,chunk)=>total+chunk.byteLength,0)!==file.size)throw new Error('本地正文传输不完整，请保持软件运行后重试。');
      const types = {pdf: 'application/pdf', docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', txt: 'text/plain', md: 'text/markdown', png: 'image/png'};
      const mime=types[file.name.split('.').pop().toLowerCase()]||'application/octet-stream';
      try { await fileInput(composer()||editor); } catch (_) { /* Drop is the fallback; no OS file picker. */ }
      let accepted=false;
      for(let attempt=0;attempt<2&&!accepted;attempt++){
      const live=await waitFor(composer);
      // Re-query after every attachment: the app may replace the input element.
      const inputs=[...document.querySelectorAll('input[type="file"]')];
      const input=inputs.find(node=>!node.accept||node.accept.split(',').some(rule=>{
        rule=rule.trim().toLowerCase();return rule==='*/*'||rule===mime||file.name.toLowerCase().endsWith(rule)||
          (rule.endsWith('/*')&&mime.startsWith(rule.slice(0,-1)));
      }))||null;
      const transfer = new DataTransfer();
      transfer.items.add(new File(chunks, file.name, {type: types[file.name.split('.').pop().toLowerCase()] || 'application/octet-stream'}));
      if (input?.isConnected && attempt===0) {
        input.value='';
        input.files = transfer.files;
        input.dispatchEvent(new Event('change', {bubbles: true}));
      } else {
        live.dispatchEvent(new DragEvent('dragenter', {bubbles: true, cancelable: true, dataTransfer: transfer}));
        live.dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: transfer}));
        live.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: transfer}));
      }
      const until=Date.now()+3500;
      while(Date.now()<until){
        const state=stateOf(file.name);
        if(state==='error')throw new Error('ChatGPT 未能上传“'+file.name+'”，选中文字已保留，请检查网络和附件额度。');
        if(state){accepted=true;break;}
        await sleep(150);
      }
      }
      if(!accepted)throw new Error('网页尚未接收“'+file.name+'”。请等待附件菜单加载后重试；没有自动发送消息。');
      await waitComplete(file);
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
    const pending = current;
    binding = true;
    try {
      await rpc('Bind', {descriptor: current.descriptor, primaryAttached: !!(primary && current.primaryAttached && sentText.includes(primary.name))});
      if (current !== pending) return;
      enableReplies(current.descriptor);
      forgetCurrent();
      notice('对话已与这篇文献绑定，下次选区将继续此对话。');
      clearInterval(watch); watch = null;
    } catch (error) { clearInterval(watch); watch = null;await report('error',error.message);notice('对话绑定未完成：' + error.message, true); }
    finally { binding = false; }
  }

  async function deliver(request, suppliedPayload) {
    if (busy || binding) return {ok: false, error: '当前选区仍在准备，请稍后点击重试。'};
    busy = true;
    try {
      await saveBinding();
      if (current && request !== current.descriptor) {
        const live = await waitFor(composer);
        if (draftText(live)) throw new Error('原对话输入框有未发送文字，请发送或清空后点击重试。');
        // A cleared/remounted input is not an unsent draft, whatever the old flag says.
        forgetCurrent();
      }
    } catch (error) { busy = false; return {ok: false, error: error.message}; }
    const retrying=current?.descriptor===request;
    current = retrying?{...current,prepared:false}:{descriptor: request, prepared: false};
    try {
      const payload = suppliedPayload || (await rpc('Payload', {descriptor: request})).payload;
      current.payload = payload;
      const expected = payload.url || 'https://chatgpt.com/';
      if (route() !== expected) throw new Error('当前页面已切换，请回阅读页重新打开选区。');
      notice('正在准备选区和文献附件，请保持软件运行。');
      await report('waiting-composer');
      current.previousMessage = [...document.querySelectorAll('[data-message-author-role="user"]')].at(-1);
      const previousEditor = current.editor, previousTracker = current.trackDraft;
      let editor = await stageText(payload);
      await report('text-ready');
      current.lastDraft = normalize(draftText(editor));
      if(previousEditor&&previousEditor!==editor){previousEditor.removeEventListener('input',previousTracker);current.trackDraft=null;}
      current.editor = editor;
      if(!current.trackDraft){
        current.trackDraft = () => { if(current?.editor){const text = normalize(draftText(current.editor));if(text)current.lastDraft=text;} };
        editor.addEventListener('input', current.trackDraft);
      }
      try{
        if(payload.files.length)await report('uploading');
        await attach(editor,payload,request);
      }catch(error){
        current.prepared=false;
        await report('upload-error',error.message);
        notice('选中文字已填入；附件未完成：'+error.message,true);
        return {ok: false, error: error.message, reported: true};
      }
      if (composer() !== editor || !draftText(editor)) editor = await stageText(payload);
      current.primaryAttached = payload.files.some(file => file.primary && attachmentState(composer()||editor, file.name)==='ready');
      current.prepared = true;
      await report('ready');
      notice('已填入选区并准备附件，请核对上传状态后点击发送。');
      clearInterval(watch); watch = setInterval(saveBinding, 1500);
      return {ok: true};
    } catch (error) { await report('error',error.message);notice(error.message, true);return {ok: false, error: error.message, reported: true}; }
    finally { busy = false; }
  }

  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id || message?.type !== 'paperQuickChatDeliver') return false;
    deliver(message.descriptor).then(respond, error => respond({ok: false, error: error.message}));
    return true;
  });

  let initialConsumed = false;
  async function begin(forced) {
    const value = typeof forced === 'string' ? forced :
      /^#paperquick=(\d{1,5}\.[A-Za-z0-9_-]{43})$/.exec(location.hash)?.[1]||(!initialConsumed?initialDescriptor:'');
    initialConsumed = true;
    try {
      if (value) {
        const result = await rpc('Route', {descriptor: value});
        if (!result.redirected) {
          history.replaceState(history.state, '', location.pathname + location.search);
          const accepted = await deliver(value, result.payload);
          if (!accepted.ok && !accepted.reported) throw new Error(accepted.error);
        }
      } else if (!current) {
        const result = await rpc('Resume');
        if (result.descriptor) await deliver(result.descriptor);
        else if(result.replyDescriptor)enableReplies(result.replyDescriptor);
      }
    } catch (error) {
      if(value)try{await rpc('Status',{descriptor:value,state:'error',detail:error.message});}catch(_){}
      notice(error.message, value ? () => begin(value) : false);
    }
  }
  addEventListener('hashchange', begin);
  begin();
})();
