"""One bounded, replaceable rendering queue per reader, with no Tk ownership."""
import threading
from collections import OrderedDict
from pdf_reader_core import file_version,DocumentChangedError


class PageRenderQueue:
    def __init__(self,render):
        self.render=render;self.lock=threading.Lock();self.jobs=OrderedDict()
        self.running=False;self.revision=0;self.active=None;self.wanted=set()

    def cancel(self):
        with self.lock:
            self.revision+=1;self.jobs.clear();self.wanted.clear()

    def request(self,path,scale,sign,generation,pages,events):
        """Latest viewport replaces queued work; visible pages precede prefetch."""
        with self.lock:
            jobs=OrderedDict()
            self.wanted={(sign,page) for page in pages[:8]}
            for page in pages[:8]:
                key=(sign,page)
                if self.active and self.active[:2]==(self.revision,key):continue
                jobs[key]=(self.revision,path,scale,sign,generation,page,events)
            self.jobs=jobs
            if self.running or not jobs:return
            self.running=True
        threading.Thread(target=self._run,daemon=True).start()

    def _run(self):
        while True:
            with self.lock:
                if not self.jobs:self.running=False;self.active=None;return
                key,job=self.jobs.popitem(last=False)
                revision,path,scale,sign,generation,page,events=job
                self.active=(revision,key)
            try:
                version=sign[4] if len(sign)>4 else None
                if version is not None and file_version(path)!=version:raise DocumentChangedError()
                data=self.render(path,page,scale)
                if version is not None and file_version(path)!=version:raise DocumentChangedError()
                error=None
            except Exception as exc:data=None;error=str(exc)
            with self.lock:
                current=revision==self.revision and key in self.wanted
                self.active=None
            if current:events.put(('canvas-page',generation,(sign,page,data,error)))
