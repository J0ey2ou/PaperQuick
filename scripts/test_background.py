"""Run unit/hidden-widget checks with desktop interaction disabled."""
from pathlib import Path
import os,sys,unittest
from contextlib import ExitStack
from unittest.mock import patch
import tkinter as tk

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE));sys.path.insert(0,str(BASE/'tests'));sys.path.insert(0,str(BASE/'build/vendor'))
temp=BASE/'build/test-temp';temp.mkdir(parents=True,exist_ok=True)
os.environ['TMP']=os.environ['TEMP']=str(temp)
for flag in ('PAPERQUICK_DOCUMENT_CONVERSION_TEST','PAPERQUICK_WORD_INTEGRATION_TEST'):os.environ.pop(flag,None)

def forbidden(*args,**kwargs):raise AssertionError('Desktop interaction is disabled during background verification')

def run(pattern='test_*.py'):
    callback_errors=[]
    original_tk=tk.Tk.__init__;original_top=tk.Toplevel.__init__;original_destroy=tk.Tk.destroy
    def hidden_tk(self,*args,**kwargs):
        original_tk(self,*args,**kwargs);self.withdraw()
        self.report_callback_exception=lambda kind,value,tb:callback_errors.append((kind,value,tb))
    def hidden_top(self,*args,**kwargs):original_top(self,*args,**kwargs);self.withdraw()
    def cleanup(self):
        for job in self.tk.splitlist(self.tk.call('after','info')):self.tk.call('after','cancel',job)
        original_destroy(self)
    with ExitStack() as stack:
        stack.enter_context(patch.object(tk.Tk,'__init__',hidden_tk))
        stack.enter_context(patch.object(tk.Toplevel,'__init__',hidden_top))
        stack.enter_context(patch.object(tk.Tk,'destroy',cleanup))
        for method in ('focus_set','focus_force','lift','tkraise'):stack.enter_context(patch.object(tk.Misc,method,lambda *a,**k:None))
        stack.enter_context(patch.object(tk.Wm,'deiconify',lambda *a,**k:None))
        for method in ('clipboard_append','clipboard_clear','clipboard_get'):stack.enter_context(patch.object(tk.Misc,method,forbidden))
        for target in ('webbrowser.open','os.startfile','PIL.ImageGrab.grab','PIL.ImageGrab.grabclipboard'):
            stack.enter_context(patch(target,forbidden))
        stack.enter_context(patch('ui_theme.window_chrome'))
        suite=unittest.defaultTestLoader.discover(str(BASE/'tests'),pattern=pattern)
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        if callback_errors:
            import traceback
            for kind,value,tb in callback_errors:traceback.print_exception(kind,value,tb)
            print(f'FAILED: {len(callback_errors)} unhandled Tk callback errors',file=sys.stderr)
        return result.wasSuccessful() and not callback_errors

if __name__=='__main__':sys.exit(0 if run(sys.argv[1] if len(sys.argv)>1 else 'test_*.py') else 1)
