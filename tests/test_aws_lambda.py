import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_corpus
from aws import lambda_handler
from x68k_knowledge.corpus import Knowledge


class LambdaToolsTests(unittest.TestCase):
    def setUp(self):
        test_corpus.CorpusTests.setUp(self)
        self.db_patch=patch.object(lambda_handler,'DB',self.db)
        self.db_patch.start();self.addCleanup(self.db_patch.stop)

    def call(self,name,args):
        context=SimpleNamespace(client_context=SimpleNamespace(custom={'bedrockAgentCoreToolName':name}))
        return lambda_handler.handler(args,context)

    def test_gateway_tools_reuse_readonly_search_and_page_results(self):
        self.assertEqual(self.call('knowledge___list_sources',{}),Knowledge(self.db).sources())
        self.assertEqual(self.call('knowledge___search_knowledge',{'query':'FM','limit':1}),Knowledge(self.db).search('FM',1))
        self.assertEqual(self.call('knowledge___get_page',{'source_id':'book-a','pdf_page':4}),Knowledge(self.db).page('book-a',4))

    def test_invalid_inputs_and_other_targets_cannot_access_data_or_private_health(self):
        for name,args in [('evil___get_page',{'source_id':'book-a','pdf_page':4}),
                          ('knowledge___get_page',{'__health':True}),
                          ('knowledge___get_page',{'source_id':'book-a','pdf_page':True}),
                          ('knowledge___search_knowledge',{'query':'FM','limit':True}),
                          ('knowledge___search_knowledge',{'query':'FM','limit':21}),
                          ('knowledge___search_knowledge',{'query':'FM','sql':'DROP TABLE chunks'}),
                          ('knowledge___list_sources',{'extra':1})]:
            with self.subTest(name=name,args=args):
                result=self.call(name,args)
                self.assertEqual(result['error']['code'],'invalid_arguments')
                self.assertNotIn('books/',json.dumps(result))
        self.assertEqual(len(Knowledge(self.db).sources()),2)

    def test_private_direct_invoke_can_check_sqlite_without_returning_reference_text(self):
        result=lambda_handler.handler({'__health':True},SimpleNamespace(client_context=None))
        self.assertTrue(result['fts5_trigram'])
        self.assertEqual(result['sources'],2)
        self.assertNotIn('text',result)
