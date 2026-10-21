"""Small macOS platform layer, isolated from the installed Windows build."""
import base64
import os
from pathlib import Path
import subprocess
import sys


def data_directory():
    result=Path.home()/'Library'/'Application Support'/'PaperQuick'
    result.mkdir(parents=True,exist_ok=True)
    return result


def resources():return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))


def protect_secret(value,decrypt=False):
    """AES-GCM with a wrapping key held in the user's macOS login Keychain."""
    try:
        from keyring.backends.macOS import Keyring
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        keyring=Keyring();encoded=keyring.get_password('com.paperquick.desktop','ai-wrapping-key')
        if not encoded:
            if decrypt:raise ValueError('钥匙串中没有对应密钥，请重新填写 API Key。')
            encoded=base64.b64encode(os.urandom(32)).decode('ascii')
            keyring.set_password('com.paperquick.desktop','ai-wrapping-key',encoded)
        cipher=AESGCM(base64.b64decode(encoded,validate=True))
        if decrypt:
            if not value.startswith('mac-keychain-v1:'):raise ValueError('请在此 Mac 重新填写 API Key，不能直接使用 Windows 密钥。')
            raw=base64.b64decode(value.split(':',1)[1],validate=True)
            return cipher.decrypt(raw[:12],raw[12:],b'PaperQuick AI').decode('utf-8')
        nonce=os.urandom(12)
        return 'mac-keychain-v1:'+base64.b64encode(nonce+cipher.encrypt(nonce,value.encode('utf-8'),b'PaperQuick AI')).decode('ascii')
    except Exception:
        raise ValueError('无法访问 macOS 登录钥匙串，请允许 PaperQuick 访问后重新填写 API Key；不会保存明文。') from None


def open_file(path,*args,**kwargs):
    subprocess.Popen(['/usr/bin/open',str(Path(path).resolve())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def configure():
    if sys.platform!='darwin':return
    if not hasattr(os,'startfile'):os.startfile=open_file
    import ai_reading
    ai_reading.protect_secret=protect_secret
    import update_ui,macos_updates
    update_ui.app_updates=macos_updates
    import app
    app.app_dir=data_directory
    def helper(self):self.status.set('Mac 版暂不提供跨应用选词助手；可使用阅读页选文右键、浏览器扩展或粘贴查询。')
    app.App.start_selection_helper=helper
    def extension_help(self):
        import webbrowser
        webbrowser.open((resources()/'右键插件安装.html').as_uri())
    app.App.extension_help=extension_help
    import desktop_runtime
    desktop_runtime.configure_startup=lambda *args,**kwargs:None
    import tkinter as tk
    from tkinter import ttk
    original_bind=tk.Misc.bind
    def bind(widget,sequence=None,func=None,add=None):
        result=original_bind(widget,sequence,func,add)
        if sequence=='<Button-3>' and func:
            def context(event):func(event);return 'break'
            original_bind(widget,'<Button-2>',context,add)
            original_bind(widget,'<Control-Button-1>',context,add)
        return result
    tk.Misc.bind=bind
    original=app.App.__init__
    def init(self,root):
        original(self,root);root.geometry('1200x800');root.minsize(1000,680)
        self.status.set('macOS 试用构建 · 按要求未做功能测试 · 关闭窗口即正常退出')
        root.createcommand('tk::mac::Quit',self.close)
        root.bind_all('<Command-q>',lambda _:self.close(),add='+')
        def command(event):
            if isinstance(event.widget,(tk.Text,tk.Entry,ttk.Entry)):
                action={'c':'<<Copy>>','v':'<<Paste>>','x':'<<Cut>>','z':'<<Undo>>','a':'<<SelectAll>>'}.get(event.keysym.lower())
                if action:event.widget.event_generate(action);return 'break'
        for key in ('c','v','x','z','a'):root.bind_all('<Command-'+key+'>',command,add='+')
    app.App.__init__=init
