"""Independently grade a saved native Agentic response; never regenerate it."""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path
import httpx
from x68k_knowledge.mcp_evaluation import (
    OpenAI,JUDGE_INSTRUCTIONS,JUDGE_SCHEMA,local_api_key,output_text,judge_verdict,
    answer_hard_errors,write_report,exclusive_run,
)

ROOT=Path(__file__).resolve().parents[1]


def rendered_answer(result):
    for block in result.get('content',[]):
        if block.get('type')!='text':continue
        try:value=json.loads(block['text'])
        except (ValueError,TypeError):continue
        if isinstance(value,str):value=json.loads(value)
        body=value.get('result',value) if isinstance(value,dict) else {}
        raw=body.get('generatedResponse',{}).get('answer')
        if not isinstance(raw,str) or not raw.strip():continue
        citations=[]
        for row in body.get('results',[]):
            meta=row.get('metadata',{});title=meta.get('source_title');page=meta.get('pdf_page')
            if title and isinstance(page,(int,float)):
                citation=f"{title} PDF {int(page)}ページ"
                if citation not in citations:citations.append(citation)
        rendered=raw+('\n\n取得した出典（検索結果のメタデータ）:\n'+'\n'.join('- '+c for c in citations) if citations else '')
        return raw,rendered
    raise ValueError('No generated Agentic answer found')


async def main(args):
    result=json.loads(args.input.read_text());meta=json.loads(args.input.with_suffix('.meta.json').read_text())
    raw,answer=rendered_answer(result)
    rubric=json.loads((ROOT/'evals/rubrics.json').read_text());reference=rubric['cases'][args.case]
    key=os.environ.get('OPENAI_API_KEY','').strip() or local_api_key(ROOT/'.env')
    if not key:raise ValueError('Missing local API key')
    trace=[{'name':'agentic_retrieve_reference','mcp_tool_name':meta['tool'],
      'arguments':{'messages':[{'role':'user','content':{'text':meta['query']}}]},'is_error':bool(result.get('isError')),
      'elapsed_seconds':meta['seconds'],'result':result}]
    with exclusive_run(ROOT/'tmp/mcp-evaluation/run.lock'):
        async with httpx.AsyncClient() as client:
            api=OpenAI(client,key);started=time.monotonic()
            response=await api.respond({'model':'gpt-5.4','instructions':JUDGE_INSTRUCTIONS,
              'input':json.dumps({'question':meta['query'],'candidate_answer':answer,'reference':reference,'mcp_trace':trace},ensure_ascii=False),
              'reasoning':{'effort':'medium'},'max_output_tokens':4000,
              'text':{'format':{'type':'json_schema','name':'mcp_user_satisfaction','strict':True,'schema':JUDGE_SCHEMA}}})
            grade=json.loads(output_text(response));hard=answer_hard_errors(args.case,answer)
            status='pass' if judge_verdict(grade,trace) and not hard else 'fail'
            record={'case':args.case,'question':meta['query'],'answer_model':'bedrock-managed-agentic (model undisclosed)',
              'judge_model':'gpt-5.4','status':status,'answer':answer,'native_raw_answer':raw,'trace':trace,'grade':grade,
              'hard_errors':hard,'hard_check_version':2,'agentic_tool_seconds':meta['seconds'],
              'judge_seconds':round(time.monotonic()-started,3),'usage':api.usage}
            write_report([record],args.output,endpoint=meta['endpoint'],rubric_version=rubric['version'])
            print(json.dumps({'status':status,'grade':grade},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    parser.add_argument('--case',required=True);parser.add_argument('--input',type=Path,default=ROOT/'tmp/mcp-evaluation/native-agentic-probe.json')
    parser.add_argument('--output',type=Path,default=ROOT/'tmp/mcp-evaluation/native-agentic-grade.json')
    args=parser.parse_args()
    if not args.live:parser.error('Grading calls a paid model; pass --live explicitly')
    asyncio.run(main(args))
