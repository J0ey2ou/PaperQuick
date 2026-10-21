/* Shared file staging. Never clicks a file input, opens a picker or sends a message. */
(() => {
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const normalize=s=>(s||'').replace(/\s+/g,' ').trim();
  const types={pdf:'application/pdf',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',doc:'application/msword',txt:'text/plain',md:'text/markdown',png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg'};
  const mime=name=>types[name.split('.').pop().toLowerCase()]||'application/octet-stream';
  function compatible(input,file){
    const accept=(input.accept||'').toLowerCase().split(',').map(x=>x.trim()).filter(Boolean);
    return !accept.length||accept.some(rule=>rule==='*'||rule==='*/*'||rule===file.type||rule.startsWith('.')&&file.name.toLowerCase().endsWith(rule)||rule.endsWith('/*')&&file.type.startsWith(rule.slice(0,-1)));
  }
  function areas(editor,includeSent=false){
    if(includeSent)return [document.querySelector('main')||document.body];
    const result=[];let node=editor?.parentElement;
    const form=editor?.closest('form');if(form)result.push(form);
    for(let n=0;node&&n<6;n++,node=node.parentElement){
      if(node===document.body||node.tagName==='MAIN')break;
      if(!result.includes(node))result.push(node);
      if(form&&node===form.parentElement)break;
    }
    return result.length?result:[document.querySelector('main')||document.body];
  }
  function attachment(editor,name,includeSent=false){
    for(const area of areas(editor,includeSent)){
      if(!area)continue;
      const nodes=[...area.querySelectorAll('[data-upload-state],[data-testid*="attachment"],[data-testid*="file"],[class*="file-card"],[class*="attachment"],[class*="upload-file"],[class*="file-name"],[title],[aria-label],[data-file-name]')];
      // Plain filename cards are used by several providers, including Doubao.
      nodes.push(...[...area.querySelectorAll('*')].filter(el=>el.childElementCount===0&&normalize(el.textContent)===name));
      const node=nodes.find(el=>!el.contains(editor)&&!editor?.contains(el)&&
        (includeSent||!el.closest('[data-message-author-role],[data-testid^="conversation-turn"]'))&&
        [normalize(el.textContent),el.getAttribute('title'),el.getAttribute('aria-label'),el.getAttribute('data-file-name')].some(s=>s&&(s===name||s.includes(name))));
      if(!node)continue;
      const card=node.closest('[data-upload-state],[data-testid*="attachment"],[data-testid*="file"],[class*="file-card"],[class*="attachment"],[class*="upload-file"]')||node.parentElement||node;
      const state=(card.getAttribute('data-upload-state')||'').toLowerCase(),text=card.textContent||'';
      if(/error|failed|rejected/.test(state)||/上传失败|无法上传|上传出错|超出.{0,8}(?:限制|额度)|格式不支持|upload failed|couldn.t upload/i.test(text))return 'error';
      if(/uploading|processing|pending|queued|loading/.test(state)||card.querySelector('[role="progressbar"],[aria-busy="true"],[data-state="loading"],.animate-spin,[class*="loading"],[class*="spinner"]')||/上传中|处理中|解析中|正在上传|正在处理|正在解析|uploading|processing/i.test(text))return 'uploading';
      return 'ready';
    }
    return '';
  }
  function input(editor,file){
    const scope=areas(editor);
    return [...document.querySelectorAll('input[type="file"]')]
      .filter(el=>!el.disabled&&el.isConnected&&compatible(el,file)&&!/avatar|profile-photo/i.test((el.id||'')+' '+(el.name||'')))
      .map(el=>({el,score:(scope.some(area=>area?.contains(el))?100:0)+(el.accept?10:0)}))
      .sort((a,b)=>b.score-a.score)[0]?.el;
  }
  async function expandMenu(editor,file){
    if(input(editor,file))return;
    const scope=areas(editor);
    // Only an explicit popup toggle is safe. Never click a direct Upload/file
    // button, label, input, or menu item that could launch the OS file picker.
    for(const area of scope){
      const toggles=[...area.querySelectorAll('button[aria-haspopup="menu"],button[aria-haspopup="true"],[data-testid="composer-plus-btn"]')];
      const button=toggles.find(el=>!el.disabled&&el.getClientRects().length&&(/attach|upload|add|添加|附件|上传|更多|\+/.test((el.getAttribute('aria-label')||'')+' '+(el.getAttribute('title')||'')+' '+el.textContent)||el.getAttribute('data-testid')==='composer-plus-btn'));
      if(button){button.click();for(let n=0;n<8&&!input(editor,file);n++)await sleep(150);return;}
    }
  }
  async function stage(file,getEditor,nativeFallback){
    const state=()=>attachment(getEditor(),file.name);
    const waitSeen=async()=>{const until=Date.now()+8000;while(Date.now()<until){if(state())return true;await sleep(150);}return false;};
    const waitReady=async()=>{
      const until=Date.now()+120000;let stable=0;
      while(Date.now()<until){const value=state();
        if(value==='error')throw new Error('网页报告“'+file.name+'”上传失败，请检查网络、文件类型与附件额度；移除失败附件后重试。');
        stable=value==='ready'?stable+1:0;if(stable>=3)return;
        await sleep(250);
      }
      throw new Error('“'+file.name+'”仍在上传或解析，请稍候重试，未重复上传。');
    };
    let value=state();
    if(value==='error')throw new Error('“'+file.name+'”存在失败附件，请先在网页移除后重试。');
    if(value){await waitReady();return;}
    if(!file.size)throw new Error('附件状态已变化，请重新准备正文，未上传空文件。');
    await expandMenu(getEditor(),file);
    const transfer=new DataTransfer();transfer.items.add(file);
    const control=input(getEditor(),file);
    if(control){
      control.value='';control.files=transfer.files;
      control.dispatchEvent(new Event('input',{bubbles:true}));control.dispatchEvent(new Event('change',{bubbles:true}));
      if(await waitSeen()){await waitReady();return;}
      if(nativeFallback){try{await nativeFallback(control);if(await waitSeen()){await waitReady();return;}}catch(error){if(state()==='error')throw error;}}
    }
    // Some React uploaders ignore synthetic change, or mount only image inputs.
    // A drop on the editor bubbles to the actual composer uploader.
    const editor=getEditor();if(!editor)throw new Error('对话输入框已消失，请登录后重试。');
    for(const type of ['dragenter','dragover','drop'])editor.dispatchEvent(new DragEvent(type,{bubbles:true,cancelable:true,dataTransfer:transfer}));
    if(await waitSeen()){await waitReady();return;}
    throw new Error('网页尚未接收“'+file.name+'”。已保留问题，请展开附件菜单后点击重试；也可在网页手动上传。');
  }
  globalThis.PaperQuickUpload={mime,compatible,attachment,input,stage};
})();
