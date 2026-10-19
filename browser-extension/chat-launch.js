// Only a capability-bearing local connection page may initiate a ChatGPT handoff.
(() => {
  const match=/^\/handoff\/([A-Za-z0-9_-]{43})\/open$/.exec(location.pathname);
  if(location.protocol!=='http:'||location.hostname!=='127.0.0.1'||!match)return;
  const request=location.port+'.'+match[1];
  const start=async()=>{
    if(!document.querySelector('meta[name="paperquick-handoff"][content="1"]'))return;
    try{
      const result=await chrome.runtime.sendMessage({type:'paperQuickChatLaunch',descriptor:request});
      if(!result?.ok)throw new Error(result?.error||'扩展连接未完成，请刷新本页重试。');
    }catch(error){
      const status=document.querySelector('#status');if(status)status.textContent='连接未完成：'+error.message;
    }
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
