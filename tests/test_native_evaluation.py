import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from x68k_knowledge.mcp_evaluation import ALLOWED_TOOLS,canonical_tool_name,has_evidence,agent_answer,answer_hard_errors,run_case,EvaluationError,output_text,render_answer_text
from test_mcp_evaluation import FakeAPI,FakeClock,FakeSession,message,call,grade


class NativeEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def test_native_evidence_requires_successful_passage_with_source_metadata(self):
        value={'retrievalResults':[{'content':{'text':'A real passage'},'metadata':{'source_id':'manual','pdf_page':7}}]}
        def trace(v):return {'name':'retrieve_reference','is_error':False,'result':{'content':[{'type':'text','text':json.dumps(v)}]}}
        self.assertTrue(has_evidence(trace(value)))
        self.assertTrue(has_evidence(trace(json.dumps(value))))
        self.assertFalse(has_evidence(trace({'retrievalResults':[]})))
        self.assertFalse(has_evidence(trace({'retrievalResults':[{'content':{'text':'unsourced'}}]})))
        error=trace(value);error['is_error']=True
        self.assertFalse(has_evidence(error))
        self.assertIn(canonical_tool_name('managed-kb___Retrieve'),ALLOWED_TOOLS)
        self.assertNotIn(canonical_tool_name('other___Retrieve'),ALLOWED_TOOLS)

    async def test_native_agent_uses_semantic_guidance_and_real_tool_name(self):
        name='managed-kb___Retrieve'
        tool=SimpleNamespace(name=name,description='Hybrid search',inputSchema={'type':'object'})
        api=FakeAPI([call(name,{'retrievalQuery':{'text':'MC68000 multiply timing'}}),message('出典のある回答')])
        class Session:
            async def call_tool(self,name,arguments):
                return SimpleNamespace(model_dump=lambda **kw:{'content':[{'type':'text','text':json.dumps({'retrievalResults':[{'content':{'text':'passage'},'metadata':{'source_id':'manual'}}]})}]})
        answer,trace=await agent_answer(api,Session(),[tool],'question',FakeClock().pacer())
        self.assertEqual(answer,'出典のある回答')
        self.assertEqual(trace[0]['name'],'retrieve_reference')
        self.assertEqual(trace[0]['mcp_tool_name'],name)
        self.assertIn('natural-language query',api.payloads[0]['instructions'])
        self.assertNotIn('Spaces mean AND:',api.payloads[0]['instructions'])
        self.assertTrue(has_evidence(trace[0]))

    def test_actual_pseudo_tool_text_is_rejected_even_when_a_judge_misses_it(self):
        self.assertTrue(answer_hard_errors('m68000-mulu-ea','to=functions.knowledge___get_page \n{"pdf_page":107} 両方38クロック'))
        self.assertEqual(answer_hard_errors('m68000-mulu-ea','出典のある回答'),[])

    async def test_native_run_cannot_pass_without_exercising_native_retrieval(self):
        tools=[SimpleNamespace(name='managed-kb___Retrieve',description='Hybrid retrieval',inputSchema={'type':'object'}),
               SimpleNamespace(name='knowledge___get_page',description='Page read',inputSchema={'type':'object'})]
        api=FakeAPI([call('knowledge___get_page',{'source_id':'inside-x68000','pdf_page':171}),message('回答'),message(json.dumps(grade()))])
        result=await run_case(api,FakeSession(),tools,'screen-modes',{},FakeClock().pacer(),answer_effort='medium')
        self.assertEqual(result['status'],'fail')
        self.assertTrue(result['hard_errors'])
        self.assertEqual(result['answer_effort'],'medium')
        self.assertEqual(api.payloads[0]['reasoning']['effort'],'medium')
        self.assertEqual(result['hard_check_version'],3)

    async def test_budget_final_answer_has_structured_boundary_without_more_tools(self):
        tool=SimpleNamespace(name='search_knowledge',description='Search',inputSchema={'type':'object'})
        api=FakeAPI([call(),message(json.dumps({'answer':'取得済み根拠に基づく回答'}))])
        session=FakeSession()
        answer,trace=await agent_answer(api,session,[tool],'質問',FakeClock().pacer(),max_calls=1)
        self.assertEqual(answer,'取得済み根拠に基づく回答')
        self.assertEqual(len(session.calls),1)
        self.assertEqual(len(trace),1)
        self.assertEqual(api.payloads[-1]['tools'],[])
        self.assertTrue(api.payloads[-1]['text']['format']['strict'])
        bad=FakeAPI([call(),message('to=functions.knowledge___get_page {...}')])
        with self.assertRaises(EvaluationError):
            await agent_answer(bad,FakeSession(),[tool],'質問',FakeClock().pacer(),max_calls=1)

    def test_actual_software_support_error_is_rejected_without_a_model_call(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/native-screen-support-regressions.json').read_text())
        for record in fixture['records']:
            with self.subTest(origin=record['origin']):
                self.assertEqual(bool(answer_hard_errors(record['case'],record['answer'])),record['expected']=='fail')

    def test_actual_responses_commentary_is_not_concatenated_with_final_json(self):
        response={'status':'completed','output':[
            {'type':'message','phase':'commentary','content':[{'type':'output_text','text':'{"answer":"tool fragment"}'}]},
            {'type':'message','phase':'final_answer','content':[{'type':'output_text','text':'{"answer":"final answer"}'}]}]}
        self.assertEqual(json.loads(output_text(response)),{'answer':'final answer'})
        self.assertEqual(output_text({'status':'completed','output':response['output'][:1]}),'')

    def test_serialized_markdown_linebreaks_do_not_rewrite_code_or_values(self):
        raw=r'周波数\n\n|値|単位|\n|7.8125|kHz|\n\nコード `"\n"` は保持'
        rendered=render_answer_text(raw)
        self.assertIn('\n\n|値|単位|\n|7.8125|kHz|',rendered)
        self.assertIn(r'`"\n"`',rendered)
        self.assertEqual(render_answer_text(r'Cの\nは改行'),r'Cの\nは改行')
