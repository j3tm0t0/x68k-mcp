"""A single uncached runtime switch; disabled/error paths use immutable baselines."""
import base64
import json
import os
from pathlib import Path


def enabled():
    name=os.environ.get('REFERENCE_RELEASE_FLAG')
    if not name:return False
    try:
        import boto3
        from botocore.config import Config
        client=boto3.client('ssm',config=Config(connect_timeout=1,read_timeout=1,retries={'total_max_attempts':1}))
        return client.get_parameter(Name=name)['Parameter']['Value']=='enabled'
    except Exception:
        # Keep the original reference service usable if configuration is unavailable.
        return False


def baseline_instructions():
    directory=Path(os.environ.get('ERRATA_DATA_DIRECTORY',str(Path(__file__).parent)))
    return json.loads((directory/'release-config.json').read_text())['baseline_instructions']


def invoke_baseline(event,context,environment_key):
    import boto3
    custom=getattr(getattr(context,'client_context',None),'custom',None) or {}
    name=custom.get('bedrockAgentCoreToolName')
    response=boto3.client('lambda').invoke(
        FunctionName=os.environ[environment_key],InvocationType='RequestResponse',
        ClientContext=base64.b64encode(json.dumps({'custom':{'bedrockAgentCoreToolName':name}}).encode()).decode(),
        Payload=json.dumps(event).encode())
    if response.get('FunctionError'):return {'error':'Baseline reference is unavailable'}
    return json.loads(response['Payload'].read())
