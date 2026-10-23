"""Run unit/hidden-widget checks with desktop interaction disabled."""
from pathlib import Path
import argparse,gc,json,os,subprocess,sys,tempfile,unittest
from contextlib import ExitStack
from unittest.mock import patch
import tkinter as tk

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE));sys.path.insert(0,str(BASE/'tests'));sys.path.insert(0,str(BASE/'build/vendor'))
temp=BASE/'build/test-temp';temp.mkdir(parents=True,exist_ok=True)
os.environ['TMP']=os.environ['TEMP']=str(temp)
for flag in ('PAPERQUICK_DOCUMENT_CONVERSION_TEST','PAPERQUICK_WORD_INTEGRATION_TEST'):os.environ.pop(flag,None)

def forbidden(*args,**kwargs):raise AssertionError('Desktop interaction is disabled during background verification')

class BackgroundResult(unittest.TextTestResult):
    def stopTest(self,test):
        super().stopTest(test)
        # Collect destroyed hidden-window cycles on their owning test thread.
        # Automatic GC stays enabled; failures and callback errors remain visible.
        gc.collect()

def run(pattern='test_*.py',report=None):
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
        for target in ('webbrowser.open','os.startfile','PIL.ImageGrab.grab','PIL.ImageGrab.grabclipboard','embedded_chat.EmbeddedChat.open'):
            stack.enter_context(patch(target,forbidden))
        stack.enter_context(patch('ui_theme.window_chrome'))
        suite=unittest.defaultTestLoader.discover(str(BASE/'tests'),pattern=pattern)
        result=unittest.TextTestRunner(verbosity=2,resultclass=BackgroundResult).run(suite)
        if callback_errors:
            import traceback
            for kind,value,tb in callback_errors:traceback.print_exception(kind,value,tb)
            print(f'FAILED: {len(callback_errors)} unhandled Tk callback errors',file=sys.stderr)
        if report:
            Path(report).write_text(json.dumps(dict(tests=result.testsRun,failures=len(result.failures),
                errors=len(result.errors),skipped=len(result.skipped),callback_errors=len(callback_errors))),encoding='utf-8')
        return result.wasSuccessful() and not callback_errors

def run_isolated(pattern):
    """Keep separate modules' Tcl interpreters out of one another's GC lifetime."""
    totals=dict(tests=0,failures=0,errors=0,skipped=0,callback_errors=0)
    passed=True
    modules=sorted((BASE/'tests').glob(pattern))
    if not modules:
        print(f'No test modules match {pattern}',file=sys.stderr)
        return False
    with tempfile.TemporaryDirectory(prefix='background-reports-',dir=temp) as folder:
        for module in modules:
            report=Path(folder)/(module.stem+'.json')
            command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),module.name,
                     '--single-process','--report',str(report)]
            try:
                child=subprocess.run(command,cwd=BASE,timeout=300,stdin=subprocess.DEVNULL,
                    stdout=sys.stdout,stderr=sys.stderr,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                passed=child.returncode==0 and passed
            except subprocess.TimeoutExpired:
                print(f'FAILED: {module.name} exceeded the isolated 300 second limit',file=sys.stderr)
                passed=False
            if report.is_file():
                result=json.loads(report.read_text('utf-8'))
                for key in totals:totals[key]+=result[key]
            else:
                totals['errors']+=1
                passed=False
                print(f'FAILED: {module.name} did not finish with a test report',file=sys.stderr)
    print('\nIsolated background verification: '+json.dumps(dict(modules=len(modules),**totals,passed=passed)),flush=True)
    return passed

if __name__=='__main__':
    import faulthandler
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pattern',nargs='?',default='test_*.py')
    parser.add_argument('--single-process',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--report',help=argparse.SUPPRESS)
    args=parser.parse_args()
    # Native Tk lifetime is per process; retain stacks if a module stalls.
    if args.single_process or not any(char in args.pattern for char in '*?['):
        faulthandler.dump_traceback_later(120,repeat=True)
    try:
        ok=run(args.pattern,args.report) if args.single_process or not any(char in args.pattern for char in '*?[') else run_isolated(args.pattern)
        sys.exit(0 if ok else 1)
    finally:faulthandler.cancel_dump_traceback_later()
