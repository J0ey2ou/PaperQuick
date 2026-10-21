/* User-invoked web adapters. No auto-send, clipboard, cookies, global input or file picker. */
(() => {
  const site = Object.values(globalThis.PaperQuickAISites).find(s=>new URL(s.home).origin===location.origin);
  if(!site || location.origin==='https://chatgpt.com')return;
  const initial=/^#paperquick=(\d{1,5}\.[A-Za-z0-9_-]{43})$/.exec(location.hash)?.[1];
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const route=()=>location.origin+location.pathname;
  let current=null,busy=false,ui=null,bound='',initialConsumed=false;
  const selectors={
    '豆包':'textarea[data-testid], textarea, [contenteditable="true"][role="textbox"], .ProseMirror[contenteditable="true"]',
    'DeepSeek':'textarea#chat-input, textarea, [contenteditable="true"][role="textbox"]',
    'Gemini':'.ql-editor[contenteditable="true"], rich-textarea [contenteditable="true"], textarea',
    '千问 / Qwen':'textarea#chat-input, textarea, .ProseMirror[contenteditable="true"], [contenteditable="true"][role="textbox"]',
    'Kimi':'[contenteditable="true"][data-lexical-editor="true"], .ProseMirror[contenteditable="true"], [contenteditable="true"][role="textbox"], textarea'
  };
  const composer=()=>[...document.querySelectorAll(selectors[site.name])].find(el=>!el.disabled&&!el.readOnly&&el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden');
  const draft=el=>('value' in el?el.value:el.innerText||el.textContent||'').trim();
  const normalize=s=>s.replace(/\s+/g,' ').trim();
  async function rpc(type,extra={}){
    const result=await chrome.runtime.sendMessage({type:'paperQuickChat'+type,...extra});
    if(!result?.ok)throw new Error(result?.error||'本机连接中断，请回阅读器重新连接。');
    return result;
  }
  async function report(state,detail=''){
    if(current)try{await rpc('Status',{descriptor:current.descriptor,state,detail:detail.slice(0,600)});}catch(_){}
  }
  function notice(text){
    if(!ui){
      const host=document.createElement('div');host.id='paperquick-ai-web';const shadow=host.attachShadow({mode:'open'});
      const box=document.createElement('section');box.style.cssText='position:fixed;right:16px;top:16px;max-width:330px;padding:14px;background:#f5f9f6;color:#264636;border:1px solid #adc7b6;border-radius:10px;z-index:2147483647;font:14px/1.6 system-ui;box-shadow:0 5px 24px #0002';
      const label=document.createElement('div');box.append(label);
      const buttons={};
      for(const [id,title,action] of [
        ['retry','重试准备',()=>current&&deliver(current.descriptor)],
        ['bind','发送后绑定当前对话',()=>bindCurrent()],
        ['reply','回存选中的回答',()=>returnSelection()],
        ['close','收起',()=>{host.hidden=true;}]
      ]){
        const button=document.createElement('button');button.type='button';button.textContent=title;button.style.cssText='margin:8px 6px 0 0;padding:4px 8px;cursor:pointer';
        button.onmousedown=event=>event.preventDefault();button.onclick=()=>Promise.resolve(action()).catch(error=>notice(error.message));box.append(button);buttons[id]=button;
      }
      shadow.append(box);document.documentElement.append(host);ui={host,label,buttons};
    }
    ui.host.hidden=false;ui.label.textContent='文献直达 · '+text;
  }
  async function fill(text){
    for(let attempt=0;attempt<4;attempt++){
      let editor;
      const until=Date.now()+30000;
      while(!(editor=composer())&&Date.now()<until)await sleep(200);
      if(!editor)throw new Error('请先登录并打开文字对话输入框，再重试。');
      const existing=draft(editor);
      if(existing&&(!current.filled||normalize(existing)!==normalize(text)))throw new Error('输入框有未发送草稿，请先处理，再重试。');
      if(!existing){
        if(editor.tagName==='TEXTAREA')Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(editor,text);
        else{
          const selection=document.getSelection(),range=document.createRange();range.selectNodeContents(editor);selection.removeAllRanges();selection.addRange(range);
          if(!document.execCommand('insertText',false,text))editor.textContent=text;
        }
        editor.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));current.filled=true;
      }
      let stable=true;
      for(let n=0;n<6;n++){await sleep(180);if(composer()!==editor||normalize(draft(editor))!==normalize(text)){stable=false;break;}}
      if(stable)return editor;
    }
    throw new Error('网页未能稳定保留文字，请重试；没有发送消息。');
  }
  function attachment(name,includeSent=false){
    const editor=composer(),area=(includeSent?document.querySelector('main'):editor?.closest('form'))||editor?.closest('main')||document.querySelector('main')||document.body;
    const candidates=[...area.querySelectorAll('[data-upload-state],[data-testid*="attachment"],[data-testid*="file"],[class*="file-card"],[class*="attachment"],[class*="upload-file"],[class*="file-name"]')];
    const node=candidates.find(el=>!el.contains(editor)&&el.textContent.includes(name));
    if(!node)return '';
    if(/error|failed/.test(node.dataset.uploadState||'')||/上传失败|无法上传|upload failed/i.test(node.textContent))return 'error';
    if(/uploading|processing|pending|queued/.test(node.dataset.uploadState||'')||node.querySelector('[role="progressbar"],[aria-busy="true"],.animate-spin')||/上传中|处理中|uploading|processing/i.test(node.textContent))return 'uploading';
    return 'ready';
  }
  async function attach(payload,descriptor){
    for(let index=0;index<payload.files.length;index++){
      const metadata=payload.files[index];let state=attachment(metadata.name);
      if(!state){
        const pieces=[];let size=0;
        for(let part=0;part<metadata.chunks;part++){
          let data;
          for(let retry=0;retry<3;retry++){try{data=await rpc('Chunk',{descriptor,index,part});break;}catch(error){if(retry===2)throw error;await sleep(300*(retry+1));}}
          const piece=Uint8Array.from(atob(data.data),c=>c.charCodeAt(0));pieces.push(piece);size+=piece.length;
        }
        if(size!==metadata.size)throw new Error('正文传输不完整，请重试。');
        const extension=metadata.name.toLowerCase().split('.').at(-1);
        const mime={pdf:'application/pdf',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',png:'image/png'}[extension]||'text/plain';
        const file=new File(pieces,metadata.name,{type:mime});
        const transfer=new DataTransfer();transfer.items.add(file);
        const input=[...document.querySelectorAll('input[type="file"]')].find(el=>!el.disabled);
        if(input){input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));}
        else{
          const editor=composer();if(!editor)throw new Error('输入框已消失，请重试。');
          for(const type of ['dragenter','dragover','drop'])editor.dispatchEvent(new DragEvent(type,{bubbles:true,cancelable:true,dataTransfer:transfer}));
        }
      }
      const until=Date.now()+120000;let seen=!!state;
      while(Date.now()<until){
        state=attachment(metadata.name);
        if(state==='ready')break;
        if(state==='error')throw new Error('网页报告正文上传失败，请检查附件额度与网络后重试。');
        if(state)seen=true;
        if(!seen&&until-Date.now()<116000)throw new Error('未能确认网页接收正文。可展开附件菜单后重试，或手动上传；也可在软件中关闭“附上正文”。');
        await sleep(250);
      }
      if(state!=='ready')throw new Error('正文仍在处理，请完成后重试。');
    }
  }
  async function deliver(descriptor,payload){
    if(busy)return {ok:false,error:'当前选区仍在准备，请稍候。'};
    busy=true;
    try{
      if(current&&current.descriptor!==descriptor&&composer()&&draft(composer()))throw new Error('原对话有未发送草稿，请先处理。');
      if(current?.descriptor!==descriptor)bound='';
      current=current?.descriptor===descriptor?current:{descriptor};
      payload=payload||(await rpc('Payload',{descriptor})).payload;current.payload=payload;
      if(route()!==(payload.url||payload.home))throw new Error('对话不匹配，请回阅读器重新连接。');
      notice('正在填入问题，请保持软件运行。');await report('waiting-composer');
      await fill(payload.prompt);await report('text-ready');
      try{if(payload.files.length){await report('uploading');await attach(payload,descriptor);}}
      catch(error){await report('upload-error',error.message);notice(error.message);return {ok:false,error:error.message};}
      await fill(payload.prompt);await report('ready');current.prepared=true;
      notice('问题已填入，请核对正文后自行发送。随后点击“绑定当前对话”，选中回答文字即可回存。');return {ok:true};
    }catch(error){await report('error',error.message);notice(error.message);return {ok:false,error:error.message};}
    finally{busy=false;}
  }
  async function bindCurrent(){
    if(!current?.prepared)throw new Error('请先完成选文和附件准备。');
    if(!site.conversation.test(location.pathname))throw new Error('请先发送问题，形成普通对话后再绑定。');
    if(composer()&&draft(composer()))throw new Error('输入框仍有草稿，请发送或清空后绑定。');
    await rpc('Bind',{descriptor:current.descriptor,primaryAttached:current.payload.files.some(file=>file.primary&&attachment(file.name,true)==='ready')});
    bound=current.descriptor;notice('对话已绑定。请选中需要保存的回答文字，再点击“回存选中的回答”。');
  }
  async function returnSelection(){
    const selection=document.getSelection(),text=selection?.toString().trim();
    if(!text||text.length>100000)throw new Error('请先在网页选中需要回存的回答（最多 10 万字）。');
    if(composer()?.contains(selection.anchorNode))throw new Error('请选择回答内容，而不是输入框草稿。');
    if(!bound)await bindCurrent();
    await rpc('Reply',{descriptor:bound,text,messageId:''});notice('回答已回存，可在软件“AI 阅读”页签查看并加入笔记。');
  }
  chrome.runtime.onMessage.addListener((message,sender,respond)=>{
    if(sender.id!==chrome.runtime.id||message?.type!=='paperQuickChatDeliver')return false;
    bound='';deliver(message.descriptor).then(respond);return true;
  });
  async function begin(forced){
    const value=typeof forced==='string'?forced:/^#paperquick=(\d{1,5}\.[A-Za-z0-9_-]{43})$/.exec(location.hash)?.[1]||(!initialConsumed?initial:'');
    initialConsumed=true;
    try{
      if(value){const result=await rpc('Route',{descriptor:value});if(!result.redirected){history.replaceState(history.state,'',location.pathname+location.search);await deliver(value,result.payload);}}
      else{const result=await rpc('Resume');if(result.descriptor)await deliver(result.descriptor);else if(result.replyDescriptor){bound=result.replyDescriptor;notice('文献对话已连接，选中回答可回存。');}}
    }catch(error){notice(error.message);}
  }
  addEventListener('hashchange',()=>begin());begin();
})();
