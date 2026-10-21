// Owned child control only; no desktop input, clipboard APIs or browser-profile import.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;


// A raw child HWND plus a Core controller: no WinForms Form/Control parking,
// managed visibility heuristics, or reparenting of an already-created browser.
class EmbeddedChat : NativeWindow {
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr h,out Rect r);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h,out Rect r);
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr h,uint flags);
    [DllImport("user32.dll")] static extern IntPtr GetParent(IntPtr h);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h,IntPtr after,int x,int y,int w,int height,uint flags);
    [DllImport("shcore.dll")] static extern int SetProcessDpiAwareness(int awareness);
    [StructLayout(LayoutKind.Sequential)] struct Rect {public int Left,Top,Right,Bottom;}
    readonly IntPtr parent;
    readonly string profile,scripts,fixture;
    readonly ApplicationContext application=new ApplicationContext();
    readonly System.Windows.Forms.Timer timer=new System.Windows.Forms.Timer {Interval=200};
    readonly SynchronizationContext ui;
    readonly JavaScriptSerializer json=new JavaScriptSerializer {MaxJsonLength=8*1024*1024};
    readonly Dictionary<string,string> replies=new Dictionary<string,string>();
    readonly Dictionary<string,string> homes=new Dictionary<string,string>{{"chatgpt.com","/"},{"www.doubao.com","/chat/"},{"chat.deepseek.com","/"},{"gemini.google.com","/app"},{"chat.qwen.ai","/"},{"www.kimi.com","/"}};
    CoreWebView2Controller controller;
    CoreWebView2 core;
    string active="",pending="",lastDisplay="";
    bool ready=false,closed=false,fixtureVisible=true;
    int lastX=int.MinValue,lastY=int.MinValue;
    static readonly Regex descriptor=new Regex(@"^(\d{1,5})\.([A-Za-z0-9_-]{43})$");
    public EmbeddedChat(IntPtr parent,string profile,string scripts){
        this.parent=parent;this.profile=profile;this.scripts=scripts;
        fixture=Environment.GetEnvironmentVariable("PAPERQUICK_EMBEDDED_FIXTURE")??"";
        SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());ui=SynchronizationContext.Current;
        CreateHandle(new CreateParams {Parent=parent,Style=0x56000000,X=0,Y=0,Width=1,Height=1,Caption="PaperQuick embedded chat"});
        timer.Tick+=(s,e)=>{if(!IsWindow(parent)){Close();return;}try{SyncHost(false);}catch{Status("error","聊天显示通道异常，请关闭内嵌聊天后重试。");}};timer.Start();
    }
    void Close(){
        if(closed)return;closed=true;timer.Stop();timer.Dispose();
        try{if(controller!=null)controller.Close();}
        finally{controller=null;core=null;if(Handle!=IntPtr.Zero)DestroyHandle();application.ExitThread();}
    }
    bool SyncHost(bool acknowledge){
        if(closed||Handle==IntPtr.Zero||!IsWindow(parent))return false;
        if(GetParent(Handle)!=parent)throw new InvalidOperationException("Invalid native parent");
        Rect r,host;GetClientRect(parent,out r);GetWindowRect(parent,out host);
        int w=Math.Max(1,r.Right-r.Left),h=Math.Max(1,r.Bottom-r.Top);
        Rect own;GetWindowRect(Handle,out own);
        if(own.Left!=host.Left||own.Top!=host.Top||own.Right-own.Left!=w||own.Bottom-own.Top!=h)
            SetWindowPos(Handle,IntPtr.Zero,0,0,w,h,0x0014); // NOZORDER | NOACTIVATE, own child only
        bool visible=fixture!=""?fixtureVisible:IsWindowVisible(parent)&&!IsIconic(GetAncestor(parent,2));
        if(controller!=null){
            var bounds=new Rectangle(0,0,w,h);
            if(controller.Bounds!=bounds)controller.Bounds=bounds;
            if(controller.IsVisible!=visible)controller.IsVisible=visible;
            if(lastX!=host.Left||lastY!=host.Top){controller.NotifyParentWindowPositionChanged();lastX=host.Left;lastY=host.Top;}
        }
        bool usable=controller!=null&&controller.IsVisible&&controller.Bounds.Width>1&&controller.Bounds.Height>1;
        string signature=(controller!=null)+":"+visible+":"+w+":"+h;
        if(acknowledge||signature!=lastDisplay){
            lastDisplay=signature;
            string detail=acknowledge?(usable?"显示通道已就绪，当前网页未刷新，草稿和附件保持不变。":controller==null?"聊天组件正在初始化，请稍候。":"聊天面板当前不可见，请切回聊天网页页签。"):"";
            lock(Console.Out){Console.WriteLine(json.Serialize(new {state="display-state",detail=detail,attached=true,controllerReady=controller!=null,controllerVisible=controller!=null&&controller.IsVisible,width=w,height=h,renderMode="software",hostKind="native-core"}));Console.Out.Flush();}
        }
        return usable;
    }
    void Status(string state,string detail){lock(Console.Out){Console.WriteLine(json.Serialize(new {state=state,detail=detail}));Console.Out.Flush();}}
    async Task Init(){try{
        // The reader is system-DPI-aware; the helper uses the same awareness before
        // creating any HWND. Software compositing avoids cross-process GPU surfaces.
        var options=new CoreWebView2EnvironmentOptions();options.AdditionalBrowserArguments="--disable-gpu";
        var environment=await CoreWebView2Environment.CreateAsync(null,profile,options);
        if(closed)return;
        var created=await environment.CreateCoreWebView2ControllerAsync(Handle);
        if(closed){created.Close();return;}
        controller=created;core=controller.CoreWebView2;SyncHost(false);
        if(!String.IsNullOrEmpty(fixture)){
            string html=File.ReadAllText(fixture);
            core.AddWebResourceRequestedFilter("*",CoreWebView2WebResourceContext.All);
            core.WebResourceRequested+=(s,e)=>{e.Response=environment.CreateWebResourceResponse(new MemoryStream(Encoding.UTF8.GetBytes(html)),200,"OK","Content-Type: text/html; charset=utf-8");};
        }
        core.Settings.AreDevToolsEnabled=false;core.Settings.AreHostObjectsAllowed=false;
        core.Settings.IsStatusBarEnabled=false;
        core.NewWindowRequested+=(s,e)=>{e.Handled=true;Status("external-link","网页请求打开新窗口；请使用“在浏览器中打开”完成不支持的登录流程。");};
        core.NavigationStarting+=(s,e)=>{Uri u;if(!Uri.TryCreate(e.Uri,UriKind.Absolute,out u)||u.Scheme!="https") {e.Cancel=true;Status("blocked","内嵌窗口只允许 HTTPS 网页。");}};
        core.NavigationCompleted+=(s,e)=>{
            if(!e.IsSuccess)Status("error","网页加载失败（"+e.WebErrorStatus+"），请检查网络或使用浏览器入口。");
            else {SyncHost(false);Status("loaded","网页加载完成，请在下方登录或核对问题后发送。");}
        };
        core.ProcessFailed+=(s,e)=>Status("error","聊天渲染进程异常（"+e.ProcessFailedKind+"），请关闭内嵌聊天后重试。");
        core.WebMessageReceived+=async(s,e)=>{
            object id=null;
            try{
                if(Route(e.Source)==""||Route(e.Source)!=Route(core.Source))throw new Exception("当前页面没有文献接入权限。");
                var msg=json.Deserialize<Dictionary<string,object>>(e.TryGetWebMessageAsString());id=msg["id"];
                var request=(Dictionary<string,object>)msg["request"];
                var result=await Dispatch(request);
                core.PostWebMessageAsJson(json.Serialize(new {id=id,result=result}));
            }catch{if(id!=null)core.PostWebMessageAsJson(json.Serialize(new {id=id,result=new {ok=false,error="内嵌接入未完成，请重新准备选区或改用浏览器入口。"}}));}
        };
        string shim=@"(()=>{if(window.top!==window)return;const hosts=['chatgpt.com','www.doubao.com','chat.deepseek.com','gemini.google.com','chat.qwen.ai','www.kimi.com'];if(location.protocol!=='https:'||!hosts.includes(location.hostname))return;
const bridge=window.chrome.webview;let n=0;const pending=new Map();bridge.addEventListener('message',event=>{const item=pending.get(event.data.id);if(item){pending.delete(event.data.id);clearTimeout(item.timer);item.resolve(event.data.result);}});
Object.defineProperty(window.chrome,'runtime',{configurable:true,value:{id:'paperquick-embedded',onMessage:{addListener:()=>{}},sendMessage:request=>new Promise((resolve,reject)=>{const id=crypto.randomUUID()+':'+(++n);const timer=setTimeout(()=>{pending.delete(id);reject(new Error('本机连接超时，请重新准备选区。'));},25000);pending.set(id,{resolve,timer});bridge.postMessage(JSON.stringify({id,request}));})}});
"+File.ReadAllText(Path.Combine(scripts,"ai-sites.js"))+"\nif(location.hostname==='chatgpt.com'){"+File.ReadAllText(Path.Combine(scripts,"chat-content.js"))+"\n}else{"+File.ReadAllText(Path.Combine(scripts,"ai-web-content.js"))+"\n}})();";
        await core.AddScriptToExecuteOnDocumentCreatedAsync(shim);
        ready=true;Status("initialized","内嵌聊天已启动；首次请在此登录。");if(pending!="")await Navigate(pending);
    }catch(Exception error){Status("error","无法初始化内嵌网页（"+error.GetType().Name+"）。请确认已安装 WebView2 运行时，或使用浏览器 / API 模式。");Close();}}
    string Route(string value){
        Uri u;if(!Uri.TryCreate(value,UriKind.Absolute,out u)||u.Scheme!="https"||!u.IsDefaultPort||u.UserInfo!=""||!homes.ContainsKey(u.Host))return "";
        string p=u.AbsolutePath;bool conversation=Regex.IsMatch(p,@"^/(?:c|chat|app)/[a-zA-Z0-9_-]{4,150}$")||Regex.IsMatch(p,@"^/a/chat/s/[a-zA-Z0-9_-]{4,150}$");
        return p==homes[u.Host]||conversation?u.GetLeftPart(UriPartial.Path):"";
    }
    async Task Navigate(string url){
        Uri u;if(!Uri.TryCreate(url,UriKind.Absolute,out u)||Route(url)==""||!u.Fragment.StartsWith("#paperquick="))throw new Exception("Invalid handoff");
        string token=u.Fragment.Substring(12);var match=descriptor.Match(token);int port;
        if(!match.Success||!int.TryParse(match.Groups[1].Value,out port)||port<1024||port>65535)throw new Exception("Invalid token");
        if(!ready){pending=url;return;}
        SyncHost(false);
        if(active==token){Opened(url);return;}
        if(active!=""){
            string draft=await core.ExecuteScriptAsync("(()=>{const e=[...document.querySelectorAll('#prompt-textarea,textarea,[contenteditable=true][role=textbox],.ProseMirror[contenteditable=true],.ql-editor[contenteditable=true]')].find(e=>e.getClientRects().length);return !!(e&&(e.value||e.innerText||'').trim());})()");
            if(draft=="true")throw new Exception("当前对话已有草稿，已保留。请在下方网页发送或清空；若网页未显示，点击“重新显示”。");
        }
        active=token;pending="";core.Navigate(url);
        Opened(url);
    }
    void Opened(string url){lock(Console.Out){Console.WriteLine(json.Serialize(new {state="opened",detail="正在加载聊天网页；请在此登录并核对问题后发送。",url=url}));Console.Out.Flush();}}
    async Task Probe(){
        SyncHost(false);
        Console.WriteLine(json.Serialize(new {state="probe",detail="probe",attached=GetParent(Handle)==parent,controllerVisible=controller.IsVisible,
            controllerBounds=controller.Bounds.ToString(),page=await core.ExecuteScriptAsync("JSON.stringify({visibility:document.visibilityState,width:innerWidth,height:innerHeight})")}));Console.Out.Flush();
    }
    async Task<Dictionary<string,object>> Local(string token,string suffix,object body){
        var match=descriptor.Match(token);if(!match.Success)throw new Exception("Invalid token");
        var request=(HttpWebRequest)WebRequest.Create("http://127.0.0.1:"+match.Groups[1].Value+"/handoff/"+match.Groups[2].Value+suffix);
        request.Proxy=null;request.AllowAutoRedirect=false;request.Timeout=15000;request.Headers.Add("X-PaperQuick","1");
        if(body!=null){request.Method="POST";request.ContentType="application/json";var bytes=Encoding.UTF8.GetBytes(json.Serialize(body));request.ContentLength=bytes.Length;using(var stream=await request.GetRequestStreamAsync())await stream.WriteAsync(bytes,0,bytes.Length);}
        using(var response=await request.GetResponseAsync())using(var reader=new StreamReader(response.GetResponseStream()))return json.Deserialize<Dictionary<string,object>>(await reader.ReadToEndAsync());
    }
    async Task<object> Dispatch(Dictionary<string,object> request){
        string type=Convert.ToString(request["type"]),url=Route(core.Source);
        if(url=="")throw new Exception("Wrong page");
        if(type=="paperQuickChatResume"){
            string reply="";foreach(var pair in replies)if(pair.Value==url)reply=pair.Key;
            if(reply!=""&&active==reply)return new {ok=true,descriptor="",replyDescriptor=reply};
            if(active!=""){var p=await Local(active,"",null);string expected=Convert.ToString(p["url"]);if(expected=="")expected=Convert.ToString(p["home"]);if(expected==url)return new {ok=true,descriptor=active};}
            return new {ok=true,descriptor="",replyDescriptor=reply};
        }
        string token=Convert.ToString(request["descriptor"]);
        if(type=="paperQuickChatReply"){
            if(!replies.ContainsKey(token)||replies[token]!=url)throw new Exception("Reply not authorized");
            return await Local(token,"/reply",new {url=url,text=request["text"],messageId=request.ContainsKey("messageId")?request["messageId"]:""});
        }
        if(token!=active||active=="")throw new Exception("Request not authorized");
        if(type=="paperQuickChatBind"){
            var result=await Local(token,"/bind",new {url=url,primaryAttached=request.ContainsKey("primaryAttached")&&object.Equals(request["primaryAttached"],true)});
            if(replies.Count>=64)replies.Clear();replies[token]=url;return result;
        }
        if(type=="paperQuickChatStatus")return await Local(token,"/status",new {state=request["state"],detail=request.ContainsKey("detail")?request["detail"]:""});
        var payload=await Local(token,"",null);string target=Convert.ToString(payload["url"]);if(target=="")target=Convert.ToString(payload["home"]);
        if(url!=target)throw new Exception("Route mismatch");
        if(type=="paperQuickChatRoute"||type=="paperQuickChatPayload")return new {ok=true,payload=payload};
        if(type=="paperQuickChatChunk"){
            int index=Convert.ToInt32(request["index"]),part=Convert.ToInt32(request["part"]);if(index<0||part<0)throw new Exception("Invalid chunk");
            var result=await Local(token,"/file/"+index+"/"+part,null);result["ok"]=true;return result;
        }
        throw new Exception("Unknown request");
    }
    [STAThread] static void Main(string[] args){
        if(args.Length!=3)return;
        Console.SetOut(new StreamWriter(Console.OpenStandardOutput(),new UTF8Encoding(false)){AutoFlush=true});
        Console.SetIn(new StreamReader(Console.OpenStandardInput(),new UTF8Encoding(false)));
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
        try{Run(args);}catch(Exception error){
            Console.WriteLine(new JavaScriptSerializer().Serialize(new {state="error",detail="内嵌组件启动失败："+error.GetType().Name+" "+error.Message}));
            Environment.ExitCode=1;
        }
    }
    static void Run(string[] args){
        if(args.Length!=3)return;long value;if(!long.TryParse(args[0],out value))return;
        try{SetProcessDpiAwareness(1);}catch(DllNotFoundException){}catch(EntryPointNotFoundException){}
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        var host=new EmbeddedChat(new IntPtr(value),args[1],args[2]);
        var input=new Thread(()=>{
            try {
                string line;
                while((line=Console.ReadLine())!=null){
                    if(line.Length>12000)continue;
                    var command=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(line);
                    host.ui.Post(async state=>{
                        if(host.closed)return;
                        try{
                            string kind=Convert.ToString(command["type"]);
                            if(kind=="close")host.Close();
                            else if(kind=="sync-host")host.SyncHost(true);
                            else if(kind=="fixture-probe"&&host.fixture!="")await host.Probe();
                            else if(kind=="fixture-visibility"&&host.fixture!=""){host.fixtureVisible=Convert.ToBoolean(command["visible"]);host.SyncHost(false);}
                            else if(kind=="fixture-submit"&&host.fixture!="")await host.core.ExecuteScriptAsync("window.pqFixtureSubmit()");
                            else if(kind=="fixture-bind"&&host.fixture!="")await host.core.ExecuteScriptAsync("[...document.querySelector('#paperquick-ai-web').shadowRoot.querySelectorAll('button')].find(b=>b.textContent.includes('发送后绑定')).click()");
                            else if(kind=="fixture-reply"&&host.fixture!="")await host.core.ExecuteScriptAsync("(()=>{const h=document.querySelector('#paperquick-ai-web');if(!h){document.querySelector('[data-paperquick-reply]').click();return;}const range=document.createRange();range.selectNodeContents(document.querySelector('.markdown'));const s=getSelection();s.removeAllRanges();s.addRange(range);[...h.shadowRoot.querySelectorAll('button')].find(b=>b.textContent.includes('回存选中')).click();})()");
                            else await host.Navigate(Convert.ToString(command["url"]));
                        }
                        catch(Exception error){host.Status("error",error.Message.Contains("草稿")?error.Message:"无法完成本次聊天操作，请重新准备或使用浏览器入口。");}
                    },null);
                }
            }catch{}
            finally{host.ui.Post(state=>host.Close(),null);}
        });
        input.IsBackground=true;input.Start();host.ui.Post(async state=>await host.Init(),null);Application.Run(host.application);
    }
}
