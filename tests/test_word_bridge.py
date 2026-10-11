import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

import word_bridge


class WordTransportTests(unittest.TestCase):
    def invoke(self, response=None, failure=None):
        def run(args, **kwargs):
            self.assertTrue(kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW)
            request = json.loads(Path(args[1]).read_text('utf-8'))
            self.assertEqual(request['action'], 'snapshot')
            if failure:
                raise failure
            if response is not None:
                Path(args[2]).write_text(json.dumps(response), encoding='utf-8')
            return subprocess.CompletedProcess(args, 0)
        with patch.object(Path, 'is_file', side_effect=lambda: True), patch('word_bridge.subprocess.run', side_effect=run):
            return word_bridge.snapshot()

    @unittest.skipUnless(os.name == 'nt', 'Windows-only transport')
    def test_snapshot_response_is_not_changed(self):
        snapshot = {'document': {'name': 'New document'}, 'fields': [], 'fingerprint': 'abc'}
        self.assertEqual(self.invoke({'ok': True, 'result': snapshot}), snapshot)

    @unittest.skipUnless(os.name == 'nt', 'Windows-only transport')
    def test_customer_error_is_preserved(self):
        with self.assertRaisesRegex(word_bridge.WordBridgeError, '请先打开'):
            self.invoke({'ok': False, 'error': '请先打开 Word。', 'detail': 'Internal COM trace'})

    @unittest.skipUnless(os.name == 'nt', 'Windows-only transport')
    def test_timeout_instructs_check_before_retry(self):
        with self.assertRaisesRegex(word_bridge.WordBridgeError, '检查文档'):
            self.invoke(failure=subprocess.TimeoutExpired(['WordBridge.exe'], 90))

    @unittest.skipUnless(os.name == 'nt', 'Windows-only transport')
    def test_incomplete_success_is_readable(self):
        with self.assertRaisesRegex(word_bridge.WordBridgeError, '返回信息不完整'):
            self.invoke({'ok': True})

    def test_apply_passes_expected_snapshot_and_operations(self):
        expected = {'fingerprint': 'document-version'}
        changes = {'insert': {'kind': 'citation', 'payload': {'id': '123'}, 'result_rtf': r'{\rtf1 [1]}'}}
        with patch('word_bridge._call', return_value={'fields': []}) as call:
            self.assertEqual(word_bridge.apply(expected, changes), {'fields': []})
            call.assert_called_once_with({'action': 'apply', 'snapshot': expected, 'operations': changes})

    def test_frozen_helper_is_loaded_from_bundle(self):
        with patch.object(word_bridge.sys, '_MEIPASS', 'D:/bundle', create=True):
            self.assertEqual(word_bridge.bridge_path(), Path('D:/bundle/word-integration/WordBridge.exe'))

    @unittest.skipUnless(os.name == 'nt' and os.environ.get('PAPERQUICK_WORD_INTEGRATION_TEST') == '1', 'Explicit isolated Word integration test')
    def test_real_word_owns_only_unsaved_test_document(self):
        result = word_bridge.isolated_selftest()
        self.assertTrue(result['passed'])
        self.assertFalse(result['document_saved'])
        self.assertIn('multi-edit atomic undo', result['checks'])
        self.assertIn('zero-write failure preserves prior undo', result['checks'])
        self.assertIn('locked parent control preserves prior edit', result['checks'])
        self.assertIn('lock-only mutation rollback', result['checks'])
        self.assertIn('partial write rollback preserves prior edit', result['checks'])

    @unittest.skipUnless(os.name == 'nt' and os.environ.get('PAPERQUICK_WORD_INTEGRATION_TEST') == '1', 'Explicit isolated Word integration test')
    def test_real_csl_plans_render_and_renumber_in_word(self):
        from word_citations import plan_changes
        records = [
            {'id': 'alpha', 'title': 'Fictional nutrition follow-up', 'year': '2024', 'authors_structured': [{'family': 'Smith', 'given': 'Amy'}], 'venue': 'Demo Research', 'volume': '12', 'issue': '2', 'pages': '23-29', 'doi': '10.9999/demo.alpha'},
            {'id': 'beta', 'title': '示例研究：膳食与健康', 'year': '2023', 'authors_structured': [{'family': '张', 'given': '华'}], 'venue': '示例研究杂志', 'volume': '8', 'issue': '1', 'pages': '3-9', 'language': 'zh-CN'},
            {'id': 'gamma', 'title': 'A replacement study', 'year': '2025', 'authors_structured': [{'family': 'Jones', 'given': 'Brian'}], 'venue': 'Demo Science', 'volume': '2', 'issue': '4', 'pages': '18-26'},
        ]
        for style in ('apa', 'vancouver-nlm', 'china-national-standard-gb-t-7714-2015-numeric'):
            with self.subTest(style=style):
                snapshot = {'fields': [], 'selection': {'start': 1000, 'end': 1000}}
                batches = []

                def step(action, selected=None, target=None, before=None):
                    if before:
                        point = next(f['start'] for f in snapshot['fields'] if f['id'] == before) - 1
                    else:
                        point = max([f['end'] for f in snapshot['fields']] or [0]) + 100
                    snapshot['selection'] = {'start': point, 'end': point}
                    operations, formatted = plan_changes(snapshot, records, style, action, selected, target)
                    fields = [deepcopy(f) for f in snapshot['fields'] if f['id'] not in operations.get('remove', [])]
                    for update in operations.get('updates', []):
                        next(f for f in fields if f['id'] == update['id'])['payload'] = deepcopy(update['payload'])
                    new = operations.get('insert')
                    if new:
                        fields.append({'id': new['payload']['id'], 'kind': new['kind'], 'payload': deepcopy(new['payload']), 'start': point})
                    fields.sort(key=lambda f: f['start'])
                    for index, field in enumerate(fields):
                        field.update(start=(index+1)*100, end=(index+1)*100+50)
                    expected = {f['id']: formatted['plain_citations'][f['id']] if f['kind'] == 'citation' else formatted['plain_bibliography'] for f in fields}
                    batch = {'label': style + ' ' + action, 'style_id': style, 'operations': operations, 'expected_plain': expected, 'cursor': 'before' if before else 'end', 'anchor': before}
                    if action == 'bibliography' and style == 'apa':
                        batch.update(check_italic='Demo Research', check_hanging=True)
                    if action == 'bibliography' and style == 'china-national-standard-gb-t-7714-2015-numeric':
                        batch.update(check_superscript=True)
                    batches.append(batch)
                    snapshot['fields'] = fields
                    return new['payload']['id'] if new else None

                alpha = step('insert', [records[0]])
                beta = step('insert', [records[1]], before=alpha)
                step('bibliography')
                step('replace', [records[2]], target=alpha)
                step('remove', target=beta)
                step('remove', target=alpha)
                result = word_bridge.isolated_selftest(timeout=180, batches=batches)
                self.assertTrue(result['passed'])
                self.assertEqual(len(result['checks']), 6)
                self.assertFalse(result['document_saved'])


if __name__ == '__main__':
    unittest.main()
