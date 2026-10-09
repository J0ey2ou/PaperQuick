import sys,tempfile
from pathlib import Path
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from desktop_runtime import Instance,DesktopRuntime
from app import App

base=Path(__file__).resolve().parents[1]/'build'/'runtime-tests';base.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=base) as temp:
    first=Instance(temp);assert first.primary
    second=Instance(temp);assert not second.primary
    second.send(['--query','Test title','--auto-open']);second.close()
    assert list(first.commands())==[['--query','Test title','--auto-open']]
    assert not list(first.commands())
    root=tk.Tk();app=App(root);app.library_directory=Path(temp)/'store'
    desktop=DesktopRuntime(app,first);root.update()
    # Missing tray must never strand the window in the background.
    desktop.hide();assert root.state()!='withdrawn'
    (first.runtime/'tray-ready').write_text('test',encoding='utf-8')
    desktop.hide();assert root.state()=='withdrawn'
    desktop.handle([]);assert root.state()!='withdrawn'
    desktop.handle(['--library']);assert app.current_page=='library'
    app.close();assert desktop.closed
    third=Instance(temp);assert third.primary;third.close()
print('Runtime passed: single instance / query forwarding / tray readiness guard / hide and restore / library command / release lock on exit')
