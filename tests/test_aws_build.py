import contextlib
import io
import json
import unittest
import zipfile

import test_corpus
from aws.build import build


class AwsBuildTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        test_corpus.CorpusTests.setUp(self)

    async def test_artifact_is_repeatable_contains_only_required_files_and_preserves_optional_tool_input(self):
        output=self.root/'package'
        with contextlib.redirect_stdout(io.StringIO()):await build(self.db,output)
        first=json.loads((output/'build.json').read_text())
        with contextlib.redirect_stdout(io.StringIO()):await build(self.db,output)
        self.assertEqual(first['sha256'],json.loads((output/'build.json').read_text())['sha256'])
        with zipfile.ZipFile(output/'lambda.zip') as bundle:
            self.assertEqual(set(bundle.namelist()),{'lambda_handler.py','knowledge.sqlite3','x68k_knowledge/__init__.py','x68k_knowledge/corpus.py'})
        template=json.loads((output/'stack.json').read_text())
        resources=template['Resources']
        self.assertEqual(resources['Gateway']['Properties']['AuthorizerType'],'NONE')
        tools=resources['KnowledgeTarget']['Properties']['TargetConfiguration']['Mcp']['Lambda']['ToolSchema']['InlinePayload']
        search=next(t for t in tools if t['Name']=='search_knowledge')
        self.assertEqual(search['InputSchema']['Properties']['source_id']['Type'],'string')
        self.assertNotIn('source_id',search['InputSchema']['Required'])
        self.assertNotIn('OPENAI_API_KEY',json.dumps(template))

    async def test_output_cannot_replace_input_database(self):
        with self.assertRaises(ValueError):await build(self.db,self.db.parent)
        self.assertTrue(self.db.exists())
