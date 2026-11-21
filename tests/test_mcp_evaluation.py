"""No API keys or network: exercise the real agent/judge orchestration with fakes."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from x68k_knowledge.mcp_evaluation import (
    DIMENSIONS, EvaluationError, OpenAI, Pacer, agent_answer, answer_hard_errors, exclusive_run,
    case_question, judge_verdict, local_api_key, output_text, run_case, write_report,
)
from x68k_knowledge.quality import CASES, QualityError, validate

ROOT = Path(__file__).resolve().parents[1]


def message(text):
    return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': text}]}]}


def call(name='search_knowledge', arguments=None):
    return {'status': 'completed', 'output': [
        {'type': 'reasoning', 'id': 'rs_fake', 'summary': []},
        {'type': 'function_call', 'call_id': 'call_fake', 'name': name,
         'arguments': json.dumps({'query': '画面'} if arguments is None else arguments)}]}


def grade():
    return {**dict.fromkeys(DIMENSIONS, 4), 'critical_errors': [],
            'unsupported_claims': [], 'missing_facts': [], 'reason': '具体的で出典と一致する。'}


def evidence(value=None):
    return {'content': [{'type': 'text', 'text': json.dumps(
        [{'source_id': 'inside-x68000', 'pdf_page': 171, 'text': 'retrieved evidence'}]
        if value is None else value)}]}


class FakeAPI:
    def __init__(self, responses):
        self.responses, self.payloads, self.usage = list(responses), [], []

    async def respond(self, payload):
        self.payloads.append(copy.deepcopy(payload))
        self.usage.append({'model': payload['model'], 'input_tokens': 1, 'output_tokens': 1})
        return self.responses.pop(0)


class FakeClock:
    def __init__(self):
        self.now, self.sleeps = 1000, []

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def pacer(self, path=None):
        return Pacer(path, clock=lambda: self.now, sleep=self.sleep)


class FakeSession:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(model_dump=lambda **kw: evidence())


TOOLS = [SimpleNamespace(name='search_knowledge', description='actual server description',
                         inputSchema={'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}),
         SimpleNamespace(name='write_file', description='not allowed', inputSchema={})]


class OfflineAnswers(unittest.TestCase):
    def test_actual_answers_and_known_failures(self):
        fixture = json.loads((ROOT / 'tests/fixtures/quality-answers.json').read_text())
        self.assertEqual({r['case'] for r in fixture['records'] if r['expected'] == 'pass'}, set(CASES))
        for record in fixture['records']:
            with self.subTest(case=record['case'], expected=record['expected'], origin=record['origin']):
                if record['expected'] == 'pass':
                    validate(record['case'], record['answer'])
                else:
                    with self.assertRaises(QualityError):
                        validate(record['case'], record['answer'])

    def test_missing_or_incorrect_citations_cannot_borrow_correct_source_text(self):
        fixture = json.loads((ROOT / 'tests/fixtures/quality-answers.json').read_text())
        base = next(r['answer'] for r in fixture['records'] if r['case'] == 'crtc-sync' and r['expected'] == 'pass')
        for alteration in ('empty', 'uncited', 'wrong-page', 'wrong-source', 'invalid-index'):
            with self.subTest(alteration=alteration), self.assertRaises(QualityError):
                answer = copy.deepcopy(base)
                if alteration == 'empty':
                    answer.update(paragraphs=[], tables=[])
                elif alteration == 'uncited':
                    for block in answer['paragraphs'] + answer['tables']:
                        block['citations'] = []
                elif alteration == 'wrong-page':
                    for source in answer['sources']:
                        source['pdf_page'] = 1
                elif alteration == 'wrong-source':
                    for source in answer['sources']:
                        source['source_id'] = 'different-book'
                else:
                    answer['paragraphs'][0]['citations'] = [True]
                validate('crtc-sync', answer)

    def test_rubric_case_coverage(self):
        cases = json.loads((ROOT / 'evals/rubrics.json').read_text())['cases']
        self.assertTrue(set(CASES) <= set(cases))
        for case_id, reference in cases.items():
            self.assertTrue(case_question(case_id, reference))
            self.assertTrue(reference['required_facts'])
            self.assertTrue(reference['source_pages'])
            if case_id not in CASES:
                self.assertTrue(reference['source_id'])

    def test_correct_facts_do_not_excuse_extra_contradictions(self):
        fixture = json.loads((ROOT / 'tests/fixtures/quality-answers.json').read_text())
        base = next(r['answer'] for r in fixture['records'] if r['case'] == 'crtc-sync' and r['expected'] == 'pass')
        for text in ('R20は$E80020。', 'R20の同期対象はbit0〜7。', 'R0の同期対象はbit8〜10。'):
            with self.subTest(text=text), self.assertRaises(QualityError):
                answer = copy.deepcopy(base)
                answer['paragraphs'].append({'text': text, 'citations': [1]})
                validate('crtc-sync', answer)


class EvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_prefix_preserves_real_tool_name_and_normalizes_evidence(self):
        tool = SimpleNamespace(name='knowledge___search_knowledge', description='AWS search', inputSchema=TOOLS[0].inputSchema)
        api=FakeAPI([call(name=tool.name),message('回答'),message(json.dumps(grade()))])
        session=FakeSession()
        result=await run_case(api,session,[tool],'screen-modes',{},FakeClock().pacer())
        self.assertEqual(result['status'],'pass')
        self.assertEqual(session.calls[0][0],tool.name)
        self.assertEqual(result['trace'][0]['name'],'search_knowledge')
        self.assertEqual(result['trace'][0]['mcp_tool_name'],tool.name)
        self.assertEqual(api.payloads[0]['tools'][0]['name'],tool.name)

    async def test_malformed_judge_keeps_answer_trace_and_is_never_a_pass(self):
        api = FakeAPI([call(), message('保存する実回答'), message('not JSON')])
        result = await run_case(api, FakeSession(), TOOLS, 'screen-modes', {}, FakeClock().pacer())
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error_stage'], 'judge')
        self.assertEqual(result['answer'], '保存する実回答')
        self.assertTrue(result['trace'])
        self.assertIsNone(result['grade'])
        self.assertEqual(result['judge_output'], 'not JSON')
        self.assertEqual(len(api.payloads), 3)

    async def test_oversized_evidence_explains_how_to_retry_with_a_smaller_limit(self):
        class LargeThenSmallSession(FakeSession):
            async def call_tool(self, name, arguments):
                self.calls.append((name, arguments))
                value = evidence([{'source_id': 'book', 'text': 'x' * 50000}]) if len(self.calls) == 1 else evidence()
                return SimpleNamespace(model_dump=lambda **kw: value)
        api = FakeAPI([call(arguments={'query': 'LSL', 'limit': 20}),
                       call(arguments={'query': 'LSL', 'limit': 3}), message('回答')])
        session = LargeThenSmallSession()
        _, trace = await agent_answer(api, session, TOOLS, '質問', FakeClock().pacer())
        self.assertTrue(trace[0]['is_error'])
        self.assertIn('limit 3', trace[0]['result']['message'])
        self.assertFalse(trace[1]['is_error'])
        self.assertNotIn('x' * 1000, json.dumps(api.payloads[1]))

    async def test_catalog_question_keeps_reference_facts_out_of_agent_input(self):
        reference = {'question': 'MC68000の命令の時間を教えて', 'required_facts': ['PRIVATE GOLD 12'], 'source_pages': [122]}
        api = FakeAPI([call(), message('回答'), message(json.dumps(grade()))])
        result = await run_case(api, FakeSession(), TOOLS, 'new-catalog-case', reference, FakeClock().pacer())
        self.assertEqual(result['question'], reference['question'])
        self.assertNotIn('PRIVATE GOLD', json.dumps(api.payloads[0]))
        self.assertIn('PRIVATE GOLD', api.payloads[-1]['input'])
        self.assertGreaterEqual(result['timings']['answer_excluding_wait_seconds'], 0)
        self.assertGreaterEqual(result['timings']['mcp_round_trip_seconds'], 0)
        self.assertIn('judge_seconds', result['timings'])

    async def test_actual_judge_false_positive_is_overridden_by_fixed_check(self):
        fixture = json.loads((ROOT / 'tests/fixtures/mcp-screen-judge-false-positive.json').read_text())
        api = FakeAPI([call(), message(fixture['answer']), message(json.dumps(fixture['judge_grade']))])
        result = await run_case(api, FakeSession(), TOOLS, 'screen-modes', {}, FakeClock().pacer())
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['grade']['satisfaction'], 4)
        self.assertTrue(result['hard_errors'])

    async def test_agent_uses_discovered_tools_then_independent_judge_gets_gold(self):
        reference = {'required_facts': ['GOLD SECRET SENTINEL'], 'source_pages': [999]}
        api = FakeAPI([call(), message('実際の回答'), message(json.dumps(grade()))])
        session, clock = FakeSession(), FakeClock()
        result = await run_case(api, session, TOOLS, 'screen-modes', reference, clock.pacer(),
                                server_instructions='REAL MCP SERVER GUIDANCE')
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(session.calls, [('search_knowledge', {'query': '画面'})])
        self.assertEqual(api.payloads[0]['input'], [{'role': 'user', 'content': CASES['screen-modes'].question}])
        self.assertEqual(api.payloads[0]['tools'][0]['description'], 'actual server description')
        self.assertEqual(len(api.payloads[0]['tools']), 1)
        self.assertIn('reasoning', [i['type'] for i in api.payloads[1]['input'] if 'type' in i])
        self.assertIn('function_call_output', [i['type'] for i in api.payloads[1]['input'] if 'type' in i])
        for payload in api.payloads[:2]:
            self.assertNotIn('GOLD SECRET SENTINEL', json.dumps(payload))
            self.assertIn('REAL MCP SERVER GUIDANCE', payload['instructions'])
            self.assertEqual(payload['model'], 'gpt-5.4-mini')
        judge = api.payloads[-1]
        self.assertEqual(judge['model'], 'gpt-5.4')
        self.assertNotIn('tools', judge)
        self.assertTrue(judge['text']['format']['strict'])
        self.assertEqual(json.loads(judge['input'])['reference'], reference)
        self.assertEqual(json.loads(judge['input'])['mcp_trace'], result['trace'])

    async def test_unknown_tools_and_nonobject_arguments_never_execute(self):
        for response in (call('write_file'), call(arguments=[])):
            session = FakeSession()
            api = FakeAPI([response, message('回答')])
            _, trace = await agent_answer(api, session, TOOLS, '質問', FakeClock().pacer())
            self.assertEqual(session.calls, [])
            self.assertTrue(trace[0]['is_error'])

    async def test_call_budget_stops_real_tool_execution(self):
        api = FakeAPI([call(), call(), message('回答')])
        session = FakeSession()
        with self.assertRaises(EvaluationError):
            await agent_answer(api, session, TOOLS, '質問', FakeClock().pacer(), max_calls=1)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(len(api.payloads), 2)
        self.assertEqual(api.payloads[1]['tools'], [])
        self.assertIn('research tool budget is now exhausted',api.payloads[1]['instructions'])

    async def test_incomplete_answer_does_not_call_judge_or_retry(self):
        api = FakeAPI([{'status': 'incomplete', 'output': []}])
        with self.assertRaises(EvaluationError):
            await run_case(api, FakeSession(), TOOLS, 'screen-modes', {}, FakeClock().pacer())
        self.assertEqual(len(api.payloads), 1)

    async def test_pacing_persists_and_case_spacing_is_separate(self):
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pacing.json'
            pacer = clock.pacer(path)
            await pacer.wait('mcp_operation', 10)
            await clock.pacer(path).wait('mcp_operation', 10)
            await pacer.wait('case_start', 60)
            await pacer.wait('case_start', 60)
        self.assertEqual(clock.sleeps, [10, 60])
        self.assertEqual(pacer.wait_seconds, 60)

    async def test_transport_disables_storage_and_never_retries(self):
        class Client:
            def __init__(self):
                self.calls = []
            async def post(self, url, **kw):
                self.calls.append((url, kw))
                return SimpleNamespace(status_code=429)
        client = Client()
        with self.assertRaisesRegex(EvaluationError, 'HTTP 429'):
            await OpenAI(client, 'fake-not-a-key').respond({'model': 'test', 'store': True})
        self.assertEqual(len(client.calls), 1)
        self.assertFalse(client.calls[0][1]['json']['store'])


class VerdictTests(unittest.TestCase):
    def test_live_answer_regressions_keep_failures_and_final_success(self):
        fixture = json.loads((ROOT / 'tests/fixtures/mcp-live-answer-regressions.json').read_text())
        trace = [{'name': 'search_knowledge', 'is_error': False, 'result': evidence()}]
        for record in fixture['records']:
            with self.subTest(origin=record['origin'], case=record['case']):
                errors = answer_hard_errors(record['case'], record['answer'])
                self.assertEqual(bool(errors), record['expected_hard_error'])
                passed = judge_verdict(record['grade'], trace) and not errors
                self.assertEqual('pass' if passed else 'fail', record['expected_status'])

    def test_screen_mapping_check_accepts_complete_combinations(self):
        fixture = json.loads((ROOT / 'tests/fixtures/mcp-screen-judge-false-positive.json').read_text())
        self.assertTrue(answer_hard_errors('screen-modes', fixture['answer']))
        text = '|実画面|表示画面|色数とページ数|\n|---|---|---|\n'
        text += '\n'.join(f'|512×512|{r}|65536色×1ページ、256色×2ページ、16色×4ページ|'
                          for r in ('512×512', '512×256', '256×256'))
        self.assertEqual(answer_hard_errors('screen-modes', text), [])
        self.assertEqual(answer_hard_errors('dmac-addresses', fixture['answer']), [])

    def test_local_key_is_read_as_data_without_executing_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            self.assertEqual(local_api_key(path), '')
            path.write_text('UNRELATED=value\nexport OPENAI_API_KEY="$(never-execute)"\n')
            self.assertEqual(local_api_key(path), '$(never-execute)')

    def test_perfect_judge_cannot_pass_empty_error_or_missing_retrieval(self):
        valid = {'name': 'search_knowledge', 'is_error': False, 'result': evidence()}
        self.assertTrue(judge_verdict(grade(), [valid]))
        for trace in ([], [{**valid, 'is_error': True}], [{**valid, 'name': 'list_sources'}],
                      [{**valid, 'result': evidence([])}], [{**valid, 'result': evidence({'error': 'not found'})}]):
            with self.subTest(trace=trace):
                self.assertFalse(judge_verdict(grade(), trace))
        for field in ('critical_errors', 'unsupported_claims', 'missing_facts'):
            self.assertFalse(judge_verdict({**grade(), field: ['問題']}, [valid]))
        for dimension in DIMENSIONS:
            self.assertFalse(judge_verdict({**grade(), dimension: 2}, [valid]))

    def test_malformed_scores_fail_closed(self):
        for bad in ({}, {**grade(), 'accuracy': True}, {**grade(), 'reason': ''}, {**grade(), 'accuracy': 5}):
            with self.assertRaises(QualityError):
                judge_verdict(bad, [])
        with self.assertRaises(EvaluationError):
            output_text({'status': 'incomplete'})

    def test_exclusive_lock_and_report_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with exclusive_run(path / 'run.lock'):
                with self.assertRaises(EvaluationError):
                    with exclusive_run(path / 'run.lock'):
                        pass
            report = path / 'report.json'
            write_report([{'case': 'screen-modes', 'status': 'fail', 'answer': '回答', 'grade': grade()}],
                         report, endpoint='https://example.test/mcp', rubric_version='test')
            self.assertEqual(json.loads(report.read_text())['records'][0]['status'], 'fail')
            self.assertIn('回答', report.with_suffix('.md').read_text())
