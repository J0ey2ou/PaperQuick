"""Background checks; workers never access Tk or the reader's connection."""
import queue
import threading
from library_core import Library
from literature_tracking import TrackingStore, run_check


class TrackingCoordinator:
    def __init__(self, root, directory, fetcher=None):
        self.root=root;self.directory=directory;self.fetcher=fetcher
        self.busy=set();self.events=queue.Queue();self.listeners=[];self.closed=False
        self.last_message='';self._scan_running=False
        self.poll_id=root.after(400,self._poll)
        self.schedule_id=root.after(25000,self._schedule)

    def check(self, topic_id):
        if self.closed or topic_id in self.busy:return False
        self.busy.add(topic_id);directory=self.directory()
        def work():
            lib=None
            try:
                lib=Library(directory);result=run_check(TrackingStore(lib),topic_id,fetcher=self.fetcher)
            except Exception:
                result={'status':'failed','message':'这次没有完成查找，请稍后重试。'}
            finally:
                if lib:lib.close()
            self.events.put(('done',topic_id,result))
        threading.Thread(target=work,daemon=True).start();return True

    def _schedule(self):
        if self.closed:return
        if not self._scan_running:
            self._scan_running=True;directory=self.directory()
            def scan():
                lib=None
                try:
                    lib=Library(directory);ids=[t['id'] for t in TrackingStore(lib).due_topics()]
                except Exception:ids=[]
                finally:
                    if lib:lib.close()
                self.events.put(('due',ids,None))
            threading.Thread(target=scan,daemon=True).start()
        self.schedule_id=self.root.after(900000,self._schedule)

    def _poll(self):
        if self.closed:return
        try:
            while True:
                kind,value,result=self.events.get_nowait()
                if kind=='due':
                    self._scan_running=False
                    for topic_id in value:self.check(topic_id)
                else:
                    self.busy.discard(value);self.last_message=result.get('message','查找完成。')
                    for listener in tuple(self.listeners):listener(value,result)
        except queue.Empty:pass
        self.poll_id=self.root.after(400,self._poll)

    def close(self):
        self.closed=True;self.listeners.clear()
        for identifier in (self.poll_id,self.schedule_id):
            try:self.root.after_cancel(identifier)
            except Exception:pass
