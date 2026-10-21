"""Native rendering regression on a private Windows desktop, never the input desktop.
No SwitchDesktop, foreground operations, screenshots, input or clipboard APIs.
All provider traffic is intercepted by local HTML fixtures.
"""
import ctypes,json,subprocess,sys,time,uuid
from ctypes import wintypes
from pathlib import Path

def child(name,report):
 import os,traceback
 base=Path(__file__).resolve().parents[1]
 sys.path[:0]=[str(base),str(base/'tests'),str(base/'build/vendor')]
 # run_provider checks the actual desktop identity before creating Tk.
 os.environ['PAPERQUICK_TEST_DESKTOP']=name
 try:
  ctypes.windll.shcore.SetProcessDpiAwareness(1)
  from test_embedded_chat import EmbeddedTests
  test=EmbeddedTests()
  test.run_provider('chatgpt',mapped=True)
  test.run_provider('deepseek',mapped=True)
  report.write_text(json.dumps({'passed':True,'isolated_desktop':True,'providers':['chatgpt','deepseek'],'checks':['offset notebook host and native renderer visibility','tab hide and restore','Core controller and DOM visibility','resize and draft preservation','upload, reply and reuse'],'user_desktop_switched':False,'screenshots_or_input':False},indent=2),'utf-8')
 except:
  report.write_text(json.dumps({'passed':False,'isolated_desktop':True,'error':traceback.format_exc()},indent=2),'utf-8');raise

def parent():
 class STARTUPINFO(ctypes.Structure):
  _fields_=[('cb',wintypes.DWORD),('lpReserved',wintypes.LPWSTR),('lpDesktop',wintypes.LPWSTR),('lpTitle',wintypes.LPWSTR),('dwX',wintypes.DWORD),('dwY',wintypes.DWORD),('dwXSize',wintypes.DWORD),('dwYSize',wintypes.DWORD),('dwXCountChars',wintypes.DWORD),('dwYCountChars',wintypes.DWORD),('dwFillAttribute',wintypes.DWORD),('dwFlags',wintypes.DWORD),('wShowWindow',wintypes.WORD),('cbReserved2',wintypes.WORD),('lpReserved2',ctypes.c_void_p),('hStdInput',wintypes.HANDLE),('hStdOutput',wintypes.HANDLE),('hStdError',wintypes.HANDLE)]
 class PROCESSINFO(ctypes.Structure):
  _fields_=[('hProcess',wintypes.HANDLE),('hThread',wintypes.HANDLE),('dwProcessId',wintypes.DWORD),('dwThreadId',wintypes.DWORD)]
 u=ctypes.WinDLL('user32',use_last_error=True);k=ctypes.WinDLL('kernel32',use_last_error=True)
 u.CreateDesktopW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p];u.CreateDesktopW.restype=wintypes.HANDLE
 u.CloseDesktop.argtypes=[wintypes.HANDLE]
 k.CreateProcessW.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,wintypes.BOOL,wintypes.DWORD,ctypes.c_void_p,wintypes.LPCWSTR,ctypes.POINTER(STARTUPINFO),ctypes.POINTER(PROCESSINFO)];k.CreateProcessW.restype=wintypes.BOOL
 k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];k.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];k.CloseHandle.argtypes=[wintypes.HANDLE]
 name='PaperQuickTests_'+uuid.uuid4().hex
 h=u.CreateDesktopW(name,None,None,0,0x10000000,None)
 if not h:raise ctypes.WinError(ctypes.get_last_error())
 report=Path('build/embedded-desktop-check.json').resolve();si=STARTUPINFO();si.cb=ctypes.sizeof(si);si.lpDesktop='WinSta0\\'+name
 pi=PROCESSINFO();command=ctypes.create_unicode_buffer(subprocess.list2cmdline([sys.executable,str(Path(__file__).resolve()),'--child',name,str(report)]))
 try:
  if not k.CreateProcessW(sys.executable,command,None,None,False,0x08000000,None,str(Path.cwd()),ctypes.byref(si),ctypes.byref(pi)):raise ctypes.WinError(ctypes.get_last_error())
  k.CloseHandle(pi.hThread)
  deadline=time.monotonic()+150
  while k.WaitForSingleObject(pi.hProcess,1000)==258:
   if time.monotonic()>deadline:raise TimeoutError('Isolated desktop verification exceeded 150 seconds')
  code=wintypes.DWORD();k.GetExitCodeProcess(pi.hProcess,ctypes.byref(code));k.CloseHandle(pi.hProcess)
  print(report.read_text('utf-8'));sys.exit(code.value)
 finally:u.CloseDesktop(h)

if __name__=='__main__':
 if len(sys.argv)==4 and sys.argv[1]=='--child':child(sys.argv[2],Path(sys.argv[3]))
 else:parent()
