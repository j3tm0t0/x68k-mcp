import json
import unittest
from aws.managed_agentic_grade import rendered_answer
from x68k_knowledge.mcp_evaluation import has_evidence,canonical_tool_name,ALLOWED_TOOLS


class AgenticResultTests(unittest.TestCase):
    def test_rendering_uses_actual_passage_metadata_without_rewriting_model_answer(self):
        body={'result':{'results':[{'content':{'text':'retrieved passage'},'metadata':{'source_id':'manual','source_title':'Manual','pdf_page':7}}],
                        'generatedResponse':{'answer':'回答[1]','citations':[]}}}
        result={'content':[{'type':'text','text':json.dumps(body)}]}
        raw,rendered=rendered_answer(result)
        self.assertEqual(raw,'回答[1]')
        self.assertIn('Manual PDF 7ページ',rendered)
        self.assertTrue(has_evidence({'name':'agentic_retrieve_reference','result':result}))
        self.assertNotIn(canonical_tool_name('managed-kb___AgenticRetrieveStream'),ALLOWED_TOOLS)

    def test_generated_text_alone_is_not_retrieval_evidence(self):
        result={'content':[{'type':'text','text':json.dumps({'generatedResponse':{'answer':'根拠なし'}})}]}
        self.assertFalse(has_evidence({'name':'agentic_retrieve_reference','result':result}))
        with self.assertRaises(ValueError):rendered_answer({'content':[{'type':'text','text':'not JSON'}]})
