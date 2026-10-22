from pathlib import Path
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from workspace_tasks import TaskManager


def wait_for(manager, task_id, statuses=('succeeded', 'failed', 'cancelled'), timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        task = manager.get_task(task_id)
        if task['status'] in statuses:
            return task
        time.sleep(.01)
    raise AssertionError('Task did not reach expected state: ' + str(manager.get_task(task_id)))


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = TaskManager(self.root, max_workers=2)

    def tearDown(self):
        self.manager.close(wait=True)
        self.temp.cleanup()

    def test_concurrency_limit_queue_cancel_and_persisted_results(self):
        gate = threading.Event()
        lock = threading.Lock()
        running = []
        owner_thread = threading.get_ident()
        def worker(context):
            self.assertNotEqual(threading.get_ident(), owner_thread)
            with lock:
                running.append(context.task_id)
            context.progress(1, 2, 'worker active')
            if not gate.wait(5):
                raise RuntimeError('test gate timed out')
            context.check_cancelled()
            return {'result': 'done'}
        ids = [self.manager.submit('test', str(index), worker) for index in range(3)]
        try:
            wait_for(self.manager, ids[0], ('running',))
            wait_for(self.manager, ids[1], ('running',))
            self.assertEqual(len(running), 2)
            self.assertEqual(self.manager.get_task(ids[2])['status'], 'queued')
            self.assertTrue(self.manager.cancel(ids[2]))
        finally:
            gate.set()
        for task_id in ids[:2]:
            self.assertEqual(wait_for(self.manager, task_id)['result'], {'result': 'done'})
        self.assertEqual(wait_for(self.manager, ids[2])['status'], 'cancelled')
        self.assertEqual(len(running), 2)
        self.assertEqual(len(json.loads(self.manager.path.read_text(encoding='utf-8'))['tasks']), 3)

    def test_running_cancel_and_failure_retry_use_fresh_tasks(self):
        def cancellable(context):
            while True:
                context.check_cancelled()
                time.sleep(.005)
        task_id = self.manager.submit('cancel', 'cancel', cancellable)
        wait_for(self.manager, task_id, ('running',))
        self.manager.cancel(task_id)
        self.assertEqual(wait_for(self.manager, task_id)['status'], 'cancelled')
        attempts = []
        def fail_once(context):
            attempts.append(1)
            if len(attempts) == 1:
                raise ValueError('retry me')
            return 'recovered'
        failed = self.manager.submit('retry', 'retry', fail_once)
        self.assertEqual(wait_for(self.manager, failed)['error'], 'retry me')
        new_id = self.manager.retry(failed)
        self.assertNotEqual(failed, new_id)
        self.assertEqual(wait_for(self.manager, new_id)['result'], 'recovered')
        self.assertEqual(self.manager.get_task(failed)['status'], 'failed')

    def test_restart_marks_unfinished_interrupted_and_metadata_factory_retries(self):
        self.manager.close(wait=True)
        now = time.time()
        records = [dict(id='lost', kind='recover', label='crash test', status='running', done=2, total=9,
                        message='working', error='', result=None, created=now, updated=now, metadata={'value': 7})]
        (self.root / '.paperquick-tasks.json').write_text(json.dumps({'schema': 1, 'tasks': records}), encoding='utf-8')
        self.manager = TaskManager(self.root)
        self.assertEqual(self.manager.get_task('lost')['status'], 'interrupted')
        self.assertFalse(self.manager.get_task('lost')['can_retry'])
        self.manager.register_retry('recover', lambda data: lambda context: data['value'])
        self.assertTrue(self.manager.get_task('lost')['can_retry'])
        restored = self.manager.retry('lost')
        self.assertEqual(wait_for(self.manager, restored)['result'], 7)

    def test_non_cancellable_task_finishes_on_close_and_cannot_be_retried(self):
        gate = threading.Event()
        def worker(context):
            gate.wait(5)
            self.assertFalse(context.cancelled())
            raise ValueError('non-repeatable failure')
        task_id = self.manager.submit('import', 'legacy import', worker,
                                      metadata={'cancellable': False, 'retryable': False})
        wait_for(self.manager, task_id, ('running',))
        self.assertFalse(self.manager.cancel(task_id))
        self.assertFalse(self.manager.get_task(task_id)['can_cancel'])
        self.manager.close(wait=False)
        gate.set()
        self.assertEqual(wait_for(self.manager, task_id)['status'], 'failed')
        self.assertFalse(self.manager.get_task(task_id)['can_retry'])
        with self.assertRaises(ValueError):
            self.manager.retry(task_id)

    def test_submission_storage_failure_is_visible_terminal_and_retryable(self):
        worker = Mock(return_value='recovered')
        with patch.object(self.manager, '_save', side_effect=OSError('disk-full')), \
                patch.object(self.manager.executor, 'submit') as submit:
            with self.assertRaisesRegex(RuntimeError, '任务未能提交'):
                self.manager.submit('test', 'submission failure', worker)
            submit.assert_not_called()
        failed = self.manager.list_tasks()[0]
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('disk-full', failed['error'])
        self.assertTrue(failed['can_retry'])
        self.assertNotIn(failed['id'], self.manager._futures)
        self.assertFalse(self.manager.cancel(failed['id']))
        worker.assert_not_called()
        recovered = self.manager.retry(failed['id'])
        self.assertEqual(wait_for(self.manager, recovered)['result'], 'recovered')

    def test_start_storage_failure_never_executes_worker_or_strands_running_state(self):
        worker = Mock(return_value='recovered')
        original = self.manager._save
        def fail_running():
            if any(task['status'] == 'running' for task in self.manager._tasks.values()):
                raise OSError('read-only folder')
            original()
        with patch.object(self.manager, '_save', side_effect=fail_running):
            task_id = self.manager.submit('test', 'start failure', worker)
            failed = wait_for(self.manager, task_id)
            self.manager._futures[task_id].result(timeout=5)
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('任务启动状态未能保存', failed['error'])
        worker.assert_not_called()
        saved = json.loads(self.manager.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['tasks'][0]['status'], 'failed')
        recovered = self.manager.retry(task_id)
        self.assertEqual(wait_for(self.manager, recovered)['result'], 'recovered')

    def test_completed_result_remains_success_when_terminal_persistence_fails(self):
        original = self.manager._save
        def fail_completion():
            if any(task['status'] == 'succeeded' for task in self.manager._tasks.values()):
                raise OSError('completion write failed')
            original()
        with patch.object(self.manager, '_save', side_effect=fail_completion):
            task_id = self.manager.submit('test', 'published output', lambda context: {'path': 'already-published'})
            finished = wait_for(self.manager, task_id)
            self.manager._futures[task_id].result(timeout=5)
        self.assertEqual(finished['status'], 'succeeded')
        self.assertEqual(finished['result']['path'], 'already-published')
        self.assertIn('completion write failed', finished['error'])
        self.assertFalse(finished['can_retry'])


if __name__ == '__main__':
    unittest.main()
