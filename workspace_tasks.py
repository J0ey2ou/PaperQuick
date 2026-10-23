"""Durable, bounded background jobs. This module never imports or accesses Tk."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import json
import os
import threading
import time
import uuid


class TaskCancelled(Exception):
    pass


class TaskContext:
    def __init__(self, manager, task_id, event):
        self.manager, self.task_id, self.event = manager, task_id, event

    def cancelled(self):
        return self.event.is_set()

    def check_cancelled(self):
        if self.cancelled():
            raise TaskCancelled('任务已取消。')

    def progress(self, done, total, message=''):
        self.check_cancelled()
        self.manager._progress(self.task_id, done, total, message)


class TaskManager:
    ACTIVE = frozenset(('queued', 'running'))
    RETRYABLE = frozenset(('failed', 'cancelled', 'interrupted'))

    def __init__(self, root_path, max_workers=2):
        self.root = Path(root_path).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / '.paperquick-tasks.json'
        self.lock = threading.RLock()
        self._tasks, self._workers, self._retry, self._events, self._futures = {}, {}, {}, {}, {}
        self._retry_factories = {}
        self._closed = False
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            if saved.get('schema') != 1 or not isinstance(saved.get('tasks'), list):
                raise ValueError('任务记录格式无法识别，请保留记录文件后重试。')
            for task in saved['tasks']:
                if task['status'] in self.ACTIVE:
                    task.update(status='interrupted', message='上次运行中断，可重新执行。',
                                error='程序在任务完成前退出。', updated=time.time())
                self._tasks[task['id']] = task
        self._save()
        self.executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)), thread_name_prefix='PaperQuick-task')

    def _save(self):
        temporary = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                json.dump({'schema': 1, 'tasks': list(self._tasks.values())}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def register_retry(self, kind, factory):
        """factory(metadata) returns a fresh worker; enables retries after restart."""
        with self.lock:
            self._retry_factories[kind] = factory

    def _persist_or_note(self, task):
        """Storage errors must not strand a job or hide its actual terminal result."""
        try:
            self._save()
            return True
        except Exception as exc:
            note = '任务状态尚未写入磁盘：' + str(exc)
            task['persistence_error'] = note
            if note not in task.get('error', ''):
                task['error'] = '；'.join(filter(None, (task.get('error', ''), note)))
            return False

    def submit(self, kind, label, worker, retry=None, metadata=None):
        # Reject non-serializable metadata before publishing a queued task.
        metadata = json.loads(json.dumps(metadata or {}, ensure_ascii=False))
        with self.lock:
            if self._closed:
                raise RuntimeError('任务中心已经关闭。')
            task_id = uuid.uuid4().hex
            now = time.time()
            self._tasks[task_id] = dict(id=task_id, kind=str(kind), label=str(label), status='queued',
                                       done=0, total=0, message='等待执行', error='', result=None,
                                       created=now, updated=now, metadata=metadata)
            self._workers[task_id] = worker
            self._retry[task_id] = retry or worker
            self._events[task_id] = threading.Event()
            try:
                self._save()
                self._futures[task_id] = self.executor.submit(self._run, task_id)
            except Exception as exc:
                self._tasks[task_id].update(status='failed', message='任务未能提交，修复保存位置后可重试',
                                           error='任务未能提交：' + str(exc), updated=time.time())
                self._persist_or_note(self._tasks[task_id])
                raise RuntimeError('任务未能提交：' + str(exc)) from exc
            return task_id

    def _run(self, task_id):
        with self.lock:
            task = self._tasks[task_id]
            if self._events[task_id].is_set():
                task.update(status='cancelled', message='已取消', updated=time.time())
                self._persist_or_note(task)
                return
            task.update(status='running', message='正在执行', updated=time.time())
            try:
                self._save()
            except Exception as exc:
                task.update(status='failed', message='任务尚未执行，修复保存位置后可重试',
                            error='任务启动状态未能保存：' + str(exc), updated=time.time())
                self._persist_or_note(task)
                return
        context = TaskContext(self, task_id, self._events[task_id])
        try:
            result = self._workers[task_id](context)
            result = json.loads(json.dumps(result, ensure_ascii=False, default=str))
            state, message, error = 'succeeded', '已完成', ''
        except TaskCancelled as exc:
            result, state, message, error = None, 'cancelled', '已取消', str(exc)
        except Exception as exc:
            result, state, message, error = None, 'failed', '执行失败，可重试', str(exc)
        with self.lock:
            task.update(status=state, message=message, error=error, result=result, updated=time.time())
            if state == 'succeeded':
                task['done'] = task['total']
            self._persist_or_note(task)

    def _progress(self, task_id, done, total, message):
        with self.lock:
            task = self._tasks[task_id]
            total = max(0, int(total))
            done = min(max(0, int(done)), total) if total else max(0, int(done))
            now = time.time()
            previous = task['updated']
            task.update(done=done, total=total, message=str(message), updated=now)
            # Full progress is held in memory; persist at most twice a second.
            if now - getattr(self, '_last_save', {}).get(task_id, previous - 1) >= .5 or done == total:
                if not hasattr(self, '_last_save'):
                    self._last_save = {}
                self._last_save[task_id] = now
                self._save()

    def list_tasks(self):
        with self.lock:
            result = deepcopy(sorted(self._tasks.values(), key=lambda item: item['created'], reverse=True))
            for task in result:
                task['can_cancel'] = task['status'] in self.ACTIVE and task.get('metadata', {}).get('cancellable', True) is not False
                task['can_retry'] = task.get('metadata', {}).get('retryable', True) is not False and task['status'] in self.RETRYABLE and (
                    task['id'] in self._retry or task['kind'] in self._retry_factories)
            return result

    def get_task(self, task_id):
        return next((task for task in self.list_tasks() if task['id'] == task_id), None)

    def cancel(self, task_id):
        with self.lock:
            task = self._tasks.get(task_id)
            if not task or task['status'] not in self.ACTIVE or task.get('metadata', {}).get('cancellable', True) is False:
                return False
            self._events[task_id].set()
            future = self._futures.get(task_id)
            if task['status'] == 'queued' and future and future.cancel():
                task.update(status='cancelled', message='已取消', updated=time.time())
            else:
                task['message'] = '正在取消，请等待当前步骤安全结束'
            self._persist_or_note(task)
            return True

    def retry(self, task_id):
        with self.lock:
            task = self._tasks.get(task_id)
            if not task or task['status'] not in self.RETRYABLE or task.get('metadata', {}).get('retryable', True) is False:
                raise ValueError('只有失败、取消或中断的任务可以重试。')
            worker = self._retry.get(task_id)
            if worker is None:
                factory = self._retry_factories.get(task['kind'])
                if factory is None:
                    raise ValueError('请回到原功能页面重新提交此任务。')
                worker = factory(deepcopy(task['metadata']))
            return self.submit(task['kind'], task['label'], worker, retry=worker, metadata=task['metadata'])

    def close(self, wait=False):
        with self.lock:
            if self._closed:
                return
            self._closed = True
            for task_id in list(self._tasks):
                self.cancel(task_id)
        self.executor.shutdown(wait=wait, cancel_futures=False)
