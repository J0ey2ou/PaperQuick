import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from library_core import Library
from fulltext_index import FulltextIndex
from project_ai import retrieve_sources, build_prompt, validate_answer, verify_sources, ask, history


class Context:
    def __init__(self):self.event=threading.Event()
    def check_cancelled(self):
        if self.event.is_set():raise ValueError('cancelled')
    def progress(self,*args):self.check_cancelled()


class ProjectAITests(unittest.TestCase):
    def fixture(self,base):
        directory=base/'library';library=Library(directory)
        try:
            project=library.create_project('Evidence');path=base/'source.txt'
            path.write_text('Study shows substantial improvement in treatment outcomes.\n\nFurther trials are required to confirm these findings.',encoding='utf-8')
            rid=library.import_document(path,project)
        finally:library.close()
        FulltextIndex(directory).update(project=project)
        return directory,project,rid

    def test_scoped_retrieval_strict_quotes_and_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,project,rid=self.fixture(Path(tmp));sources=retrieve_sources(directory,'treatment',project,[rid])
            self.assertEqual(len(sources),1);self.assertEqual(sources[0]['locator_kind'],'paragraph')
            prompt=build_prompt('What were the findings?',sources);self.assertIn(sources[0]['excerpt'],prompt)
            good={'answer':'Treatment outcomes improved [S1].','citations':[{'id':'S1','quote':'substantial improvement in treatment outcomes'}]}
            result=validate_answer(json.dumps(good),sources);self.assertFalse(result['claims_verified'])
            for bad in ({**good,'answer':'Unknown [S99].'},{**good,'citations':[{'id':'S1','quote':'made up quote here'}]},{'answer':'Not supported','citations':[]}):
                with self.assertRaises(ValueError):validate_answer(json.dumps(bad),sources)
            with self.assertRaisesRegex(ValueError,'段落'):
                validate_answer(json.dumps({**good,'answer':'Supported [S1].\n\nUnsupported factual paragraph.'}),sources)
            verify_sources(directory,sources)
            (directory/sources[0]['path']).write_text('changed',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'变化'):verify_sources(directory,sources)

    def test_explicit_request_saved_only_after_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,project,rid=self.fixture(Path(tmp));sources=retrieve_sources(directory,'treatment',project,[rid])
            raw=json.dumps({'answer':'Improved [S1].','citations':[{'id':'S1','quote':'substantial improvement in treatment outcomes'}]})
            with patch('project_ai.load_profile',return_value={'endpoint':'https://example.invalid/v1','model':'test','stream':False}),patch('project_ai.get_key',return_value='test-only'),patch('project_ai.complete',return_value=raw) as request:
                self.assertFalse(history(directory,project));request.assert_not_called()
                result=ask(directory,project,'custom','What improved?',sources,Context())
                self.assertEqual(len(history(directory,project)),1);self.assertEqual(result['citation_check'],'passed')
                request.return_value='{"answer":"invented","citations":[]}'
                with self.assertRaises(ValueError):ask(directory,project,'custom','Again?',sources,Context())
                self.assertEqual(len(history(directory,project)),1)

    def test_queued_request_rejects_changed_profile_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,project,rid=self.fixture(Path(tmp));sources=retrieve_sources(directory,'treatment',project,[rid])
            with patch('project_ai.load_profile',return_value={'endpoint':'https://changed.invalid/v1','model':'changed','stream':False}),patch('project_ai.get_key') as key,patch('project_ai.complete') as request:
                with self.assertRaisesRegex(ValueError,'排队期间'):
                    ask(directory,project,'custom','What improved?',sources,Context(),expected_profile=('https://approved.invalid/v1','approved-model'))
                request.assert_not_called();key.assert_not_called();self.assertFalse(history(directory,project))
