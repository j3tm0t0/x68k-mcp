"""Compare public AWS MCP tools with the packaged local reference snapshot."""
import argparse
import asyncio
import json
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from x68k_knowledge.corpus import Knowledge
from x68k_knowledge.mcp_evaluation import Pacer, exclusive_run

ROOT=Path(__file__).resolve().parents[1]


def decode(result):
    if result.isError:
        raise RuntimeError('MCP tool returned an error')
    texts=[b.text for b in result.content if b.type=='text']
    if len(texts)!=1:
        raise RuntimeError('Unexpected MCP content shape')
    value=json.loads(texts[0])
    # Gateway may represent a native JSON string as text; decode it only once.
    return json.loads(value) if isinstance(value,str) else value


async def main(endpoint):
    directory=ROOT/'tmp/mcp-evaluation'
    local=Knowledge(ROOT/'tmp/aws-build/knowledge.sqlite3')
    timings=[]
    with exclusive_run(directory/'run.lock'):
        pacer=Pacer(directory/'pacing.json')
        async with streamablehttp_client(endpoint) as (read,write,_):
            async with ClientSession(read,write) as session:
                await pacer.wait('mcp_operation',10)
                initialization=await session.initialize()
                await pacer.wait('mcp_operation',10)
                tools=await session.list_tools()
                names={t.name for t in tools.tools}
                expected={'knowledge___'+n for n in ['list_sources','search_knowledge','get_page']}
                if names!=expected:raise RuntimeError('Unexpected gateway tool names: '+str(names))
                cases=[
                 ('list_sources',{},local.sources()),
                 ('search_knowledge',{'query':'OPM timer B','source_id':'inside-x68000','limit':5},local.search('OPM timer B',5,'inside-x68000')),
                 ('get_page',{'source_id':'nxp-m68000-um','pdf_page':118},local.page('nxp-m68000-um',118)),
                 ('search_knowledge',{'query':'パンポット','source_id':'inside-x68000','limit':1},local.search('パンポット',1,'inside-x68000'))]
                for name,args,wanted in cases:
                    await pacer.wait('mcp_operation',10)
                    started=time.monotonic()
                    actual=decode(await session.call_tool('knowledge___'+name,args))
                    elapsed=time.monotonic()-started
                    if actual!=wanted:
                        (directory/'aws-smoke-mismatch.json').write_text(json.dumps({'tool':name,'actual':actual,'expected':wanted},ensure_ascii=False,indent=2))
                        raise RuntimeError('AWS/local mismatch; see ignored aws-smoke-mismatch.json')
                    timings.append({'tool':name,'arguments':args,'seconds':round(elapsed,3),'parity':'pass'})
                    print(json.dumps(timings[-1],ensure_ascii=False),flush=True)
    report={'endpoint':endpoint,'protocol':initialization.protocolVersion,'tools':sorted(names),'checks':timings}
    (directory/'aws-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--endpoint')
    args=parser.parse_args()
    endpoint=args.endpoint or json.loads((ROOT/'tmp/aws-deployment.json').read_text())['McpUrl']
    asyncio.run(main(endpoint))
