"""Single desktop instance, local command inbox and optional per-user Windows startup."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import hashlib

RUN_KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME='PaperQuick'


def startup_enabled():
    if os.name!='nt':return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as key:return bool(winreg.QueryValueEx(key,RUN_NAME)[0])
    except OSError:return False


def configure_startup(enabled,executable):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as key:
        if enabled:winreg.SetValueEx(key,RUN_NAME,0,winreg.REG_SZ,subprocess.list2cmdline([str(executable),'--background']))
        else:
            try:winreg.DeleteValue(key,RUN_NAME)
            except FileNotFoundError:pass


class Instance:
    def __init__(self,directory):
        self.directory=Path(directory);self.runtime=self.directory/'runtime';self.runtime.mkdir(exist_ok=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateMutexW.argtypes=[wintypes.LPVOID,wintypes.BOOL,wintypes.LPCWSTR];self.kernel.CreateMutexW.restype=wintypes.HANDLE
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE];self.kernel.CloseHandle.restype=wintypes.BOOL
        name='Local\\PaperQuick.Desktop.'+hashlib.sha256(str(self.directory.resolve()).lower().encode()).hexdigest()[:20]
        self.handle=self.kernel.CreateMutexW(None,False,name);error=ctypes.get_last_error()
        if not self.handle:raise ctypes.WinError(error)
        self.primary=error!=183
        if self.primary:
            self.session=uuid.uuid4().hex
            target=self.runtime/'instance.json';temp=target.with_suffix('.tmp');temp.write_text(json.dumps({'session':self.session,'pid':os.getpid()}),encoding='utf-8');temp.replace(target)

    def send(self,args):
        data=json.loads((self.runtime/'instance.json').read_text('utf-8'))
        target=self.runtime/(uuid.uuid4().hex+'.command');temp=target.with_suffix('.tmp')
        temp.write_text(json.dumps({'session':data['session'],'args':args},ensure_ascii=False),encoding='utf-8');temp.replace(target)

    def commands(self):
        for path in self.runtime.glob('*.command'):
            try:
                if path.stat().st_size>100000:continue
                data=json.loads(path.read_text('utf-8'))
                args=data.get('args',[])
                if data.get('session')==self.session and isinstance(args,list) and all(isinstance(a,str) for a in args):yield args
            except (OSError,ValueError):pass
            finally:path.unlink(missing_ok=True)

    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


class DesktopRuntime:
    def __init__(self,app,instance,background=False):
        self.app=app;self.root=app.root;self.instance=instance;self.closed=False;self.started=time.monotonic();self.background=background;self.pending=[]
        self.helper=instance.directory/'全局选词助手.exe'
        self.root.protocol('WM_DELETE_WINDOW',self.hide)
        app.desktop=self
        if self.helper.exists():subprocess.Popen([str(self.helper),str(instance.directory/'文献直达.exe')],creationflags=subprocess.CREATE_NO_WINDOW)
        if background:self.root.withdraw()
        self.root.after(200,self.poll)

    def tray_ready(self):
        try:return time.time()-(self.instance.runtime/'tray-ready').stat().st_mtime<6
        except OSError:return False

    def hide(self):
        if not self.tray_ready():self.app.status.set('托盘尚未就绪，窗口将保持打开。');self.show();return
        if self.root.grab_current():self.root.grab_current().lift();return
        try:self.app.stop_reading()
        except Exception:return
        if self.app.reader_page:
            try:self.app.reader_page.save_notes()
            except Exception:return
        if self.app.reader_page and getattr(self.app.reader_page,'reference_window',None):
            try:self.app.reader_page.reference_window.withdraw()
            except Exception:pass
        self.root.withdraw()

    def show(self):
        self.root.deiconify();self.root.lift();self.root.focus_force()

    def handle(self,args):
        if '--quit' in args:self.show();self.app.close();return
        if '--background' in args:return
        self.show()
        if '--settings' in args:self.app.settings();return
        if '--library' in args:self.app.open_library()
        if '--query' in args:
            index=args.index('--query')
            if index+1<len(args):
                if self.app.busy:self.pending.append(args);self.app.status.set('查询已排队，当前查询结束后自动开始。');return
                self.app.show_page('query');self.app.input.delete('1.0','end');self.app.input.insert('1.0',args[index+1][:20000]);self.app.auto_open='--auto-open' in args;self.app.search()

    def poll(self):
        if self.closed:return
        for args in self.instance.commands():
            self.handle(args)
            if self.closed:return
        if self.pending and not self.app.busy:self.handle(self.pending.pop(0))
        if self.background and time.monotonic()-self.started>5:
            self.background=False
            if not self.tray_ready():self.show();self.app.status.set('后台托盘启动失败，已恢复主窗口。')
        self.root.after(1000 if self.root.state()=='withdrawn' else 250,self.poll)

    def close(self):
        self.closed=True;self.instance.close()
        if self.helper.exists():subprocess.Popen([str(self.helper),'--exit'],creationflags=subprocess.CREATE_NO_WINDOW)
