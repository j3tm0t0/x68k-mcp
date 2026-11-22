"""Read the fixed original page backend and optionally attach editorial references."""
import base64
import json
import os
from reference_overlay import attach
from release_switch import enabled


def handler(event,context):
    custom=getattr(getattr(context,'client_context',None),'custom',None) or {}
    if custom.get('bedrockAgentCoreToolName')!='knowledge___get_page':return {'error':'Unknown tool'}
    if not isinstance(event,dict) or set(event)!={'source_id','pdf_page'}:return {'error':'Pass source_id and pdf_page'}
    source_id,page=event['source_id'],event['pdf_page']
    if not isinstance(source_id,str) or type(page) is not int or page<1:return {'error':'Invalid source_id or PDF page'}
    import boto3
    client_context=base64.b64encode(json.dumps({'custom':{'bedrockAgentCoreToolName':'knowledge___get_page'}}).encode()).decode()
    response=boto3.client('lambda').invoke(FunctionName=os.environ['BASE_PAGE_FUNCTION'],InvocationType='RequestResponse',ClientContext=client_context,Payload=json.dumps(event).encode())
    if response.get('FunctionError'):return {'error':'Base reference is unavailable'}
    value=json.loads(response['Payload'].read())
    if 'error' in value:return value
    return attach(value,source_id,page) if enabled() else value
