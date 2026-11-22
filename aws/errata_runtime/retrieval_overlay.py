"""RESPONSE-only enrichment: editorial local lookup alongside unchanged native results."""
import copy,json,re
from reference_overlay import effective_data
from release_switch import enabled, baseline_instructions
# Topic aliases are general reference navigation, independent of evaluation questions.
TOPICS={
'p81_z2':[(5,'AER'),(5,'active edge'),(5,'アクティブエッジ'),(2,'エッジ'),(2,'MFP'),(2,'GPIP')],
'p94_ucrwl_l2':[(5,'UCR'),(5,'WL'),(5,'word length'),(4,'文字長'),(2,'USART'),(2,'MFP')],
'p96_z11':[(6,'RSR'),(5,'receiver status'),(5,'レシーバステータス')],
'p49_reqg_l4':[(6,'REQG'),(5,'リクエストジェネレーション'),(4,'オートリクエスト'),(2,'DMAC'),(2,'GCR')],
'p54_z18':[(6,'CPR'),(5,'チャンネル優先度'),(3,'優先度'),(2,'DMAC')],
'p233_z54':[(5,'HD'),(3,'CRTC'),(3,'水平'),(3,'768'),(2,'R20')],
'p88_delay_l2':[(3,'MFP'),(2,'タイマ'),(2,'timer'),(3,'プリスケーラ'),(3,'prescaler'),(3,'ディレイモード')],
'p174_bg_l6':[(5,'PCG'),(4,'パターン'),(4,'パタン')],
'p202_z27':[(6,'テキストアクセスマスク'),(5,'アクセスマスク'),(6,'R23'),(4,'text mask')],
'p267_z6':[(3,'OPM'),(3,'YM2151'),(2,'ステータス'),(2,'status'),(2,'オーバーフロー'),(2,'overflow')],
'p296':[(3,'ADPCM'),(4,'PAN'),(4,'パンポット'),(2,'左'),(2,'右'),(2,'left'),(2,'right')],
'p393_isr_l9':[(4,'I/Oコントローラ'),(4,'I/O controller'),(3,'割り込み要求状態'),(2,'割り込み'),(2,'上位'),(2,'下位')]}
REQUIRED_TOPIC={
 'p296':('ADPCM','PCM PAN','PPI','8255'),
 'p393_isr_l9':('I/Oコントローラ','I/O コントローラ','I/O controller','I/O interrupt','IO controller')}
def contains(query,alias):
 alias=alias.casefold()
 return bool(re.search(r'(?<![a-z0-9_])'+re.escape(alias)+r'(?![a-z0-9_])',query)) if alias.isascii() else alias in query
def matches(query):
 query=query.casefold();scored=[]
 for record in effective_data()['records']:
  required=REQUIRED_TOPIC.get(record['id'])
  if required and not any(contains(query,alias) for alias in required):continue
  score=0
  for weight,alias in TOPICS.get(record['id'],[]):
   alias=alias.casefold()
   found=contains(query,alias)
   if found:score+=weight
  if score>=5:scored.append((score,record['id'],record))
 return [dict(r,editorial_match_score=score) for score,_,r in sorted(scored,key=lambda x:(-x[0],x[1]))[:3]]
def handler(event,context):
 # Contract diagnostics contain types/keys only, never headers, queries or source text.
 m=event.get('mcp') or {};g=m.get('gatewayResponse');q=(m.get('gatewayRequest') or {}).get('body')
 print(json.dumps({'event':'interceptor_contract','response_type':type(g).__name__,'response_keys':list(g) if isinstance(g,dict) else [],'status':g.get('statusCode') if isinstance(g,dict) else None,'body_type':type(g.get('body')).__name__ if isinstance(g,dict) else None,'request_type':type(q).__name__,'method':q.get('method') if isinstance(q,dict) else None}))
 mcp=event['mcp'];response=copy.deepcopy(mcp['gatewayResponse']);request=(mcp.get('gatewayRequest') or {}).get('body') or {}
 if isinstance(request,str):
  try:request=json.loads(request)
  except ValueError:request={}
 if not isinstance(request,dict):request={}
 body=response.get('body')
 active=enabled()
 if not active and request.get('method')=='initialize' and isinstance(body,dict) and isinstance(body.get('result'),dict):
  body['result']['instructions']=baseline_instructions()
 if active and request.get('method')=='tools/call' and request.get('params',{}).get('name')=='managed-kb___Retrieve' and isinstance(body,dict):
  arguments=request['params'].get('arguments',{});query=arguments.get('retrievalQuery',{}).get('text','')
  # Connector exposes retrievalQuery.text; tolerate a root text field, never parse other tool inputs.
  if not query:query=arguments.get('text','')
  if isinstance(query,str) and isinstance(body.get('result'),dict) and not body['result'].get('isError'):
   records=matches(query)
   if records:
    content=body['result'].get('content')
    if isinstance(content,list):
     extra={'editorial_reference_matches':records,'reference_data_version':effective_data()['version'],'retrieval_notice':'Separate curated editorial data with evidence/adoption scope. These are local topic matches, not additional Bedrock semantic results; native retrievalResults are unchanged. Matching scores measure topic overlap, not truth.'}
     for block in content:
      if block.get('type')!='text':continue
      try:
       native=json.loads(block.get('text',''));wrapped=isinstance(native,str)
       if wrapped:native=json.loads(native)
      except (ValueError,TypeError):continue
      if isinstance(native,dict) and 'retrievalResults' in native:
       text=json.dumps({**extra,**native},ensure_ascii=False)
       block['text']=json.dumps(text,ensure_ascii=False) if wrapped else text
       break
 # Input includes read-only transport fields (and sometimes a null statusCode).
 # Return only documented overrides; omitted headers retain the original headers.
 transformed={'body':response.get('body',{}),'statusCode':response.get('statusCode') or 200}
 return {'interceptorOutputVersion':'1.0','mcp':{'transformedGatewayResponse':transformed}}
