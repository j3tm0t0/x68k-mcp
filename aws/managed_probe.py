"""One paced native MCP query, saving source text only in ignored local logs."""
import argparse
import asyncio
import json
import time
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from x68k_knowledge.mcp_evaluation import Pacer,exclusive_run

ROOT=Path(__file__).resolve().parents[1]


async def main(query,agentic=False):
    state=json.loads((ROOT/'tmp/bedrock-managed/deployment.json').read_text())
    out=ROOT/'tmp/mcp-evaluation'
    with exclusive_run(out/'run.lock'):
        pacer=Pacer(out/'pacing.json')
        async with streamablehttp_client(state['McpUrl']) as (read,write,_):
            async with ClientSession(read,write) as session:
                await pacer.wait('mcp_operation',10);await session.initialize()
                await pacer.wait('mcp_operation',10);tools=await session.list_tools()
                print(json.dumps([{'name':t.name,'schema':t.inputSchema} for t in tools.tools]),flush=True)
                if not query:return
                if agentic:await pacer.wait('case_start',60)
                await pacer.wait('mcp_operation',10)
                tool='managed-kb___AgenticRetrieveStream' if agentic else 'managed-kb___Retrieve'
                arguments={'messages':[{'role':'user','content':{'text':query}}]} if agentic else {'retrievalQuery':{'text':query}}
                started=time.monotonic()
                result=await asyncio.wait_for(session.call_tool(tool,arguments),timeout=180)
                value=result.model_dump(mode='json',exclude_none=True)
                path=out/('native-agentic-probe.json' if agentic else 'native-probe.json')
                path.write_text(json.dumps(value,ensure_ascii=False,indent=2))
                path.with_suffix('.meta.json').write_text(json.dumps({'endpoint':state['McpUrl'],'tool':tool,'query':query,'seconds':round(time.monotonic()-started,3)},ensure_ascii=False,indent=2))
                print(json.dumps({'isError':result.isError,'saved':str(path),'preview':str(value)[:1000]},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--query');parser.add_argument('--agentic',action='store_true')
    args=parser.parse_args();asyncio.run(main(args.query,args.agentic))
