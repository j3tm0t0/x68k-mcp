"""Build a reproducible, credential-free Lambda artifact and CloudFormation template."""
import argparse
import asyncio
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

from x68k_knowledge.server import create_server

ROOT = Path(__file__).resolve().parents[1]


def cfn_schema(schema):
    if 'anyOf' in schema:
        variants = [v for v in schema['anyOf'] if v.get('type') != 'null']
        if len(variants) != 1:
            raise ValueError('Gateway cannot represent this schema union')
        schema = {**schema, **variants[0]}
    result = {'Type': schema['type']}
    if 'description' in schema:
        result['Description'] = schema['description']
    if 'properties' in schema:
        result['Properties'] = {k: cfn_schema(v) for k, v in schema['properties'].items()}
    if schema.get('required'):
        result['Required'] = schema['required']
    if 'items' in schema:
        result['Items'] = cfn_schema(schema['items'])
    return result


def template(tools, instructions):
    sub = lambda value: {'Fn::Sub': value}
    att = lambda resource, value: {'Fn::GetAtt': [resource, value]}
    ref = lambda name: {'Ref': name}
    tags = [{'Key': 'Project', 'Value': 'x68k-mcp'}]
    return {
      'AWSTemplateFormatVersion': '2010-09-09',
      'Description': 'Public read-only X68000 knowledge MCP: AgentCore Gateway and Lambda SQLite snapshot',
      'Parameters': {'ArtifactBucket': {'Type': 'String'}, 'ArtifactKey': {'Type': 'String'}},
      'Resources': {
        'LambdaRole': {'Type': 'AWS::IAM::Role', 'Properties': {
          'AssumeRolePolicyDocument': {'Version': '2012-10-17','Statement': [
            {'Effect': 'Allow','Principal': {'Service': 'lambda.amazonaws.com'},'Action': 'sts:AssumeRole'}]},
          'Policies': [{'PolicyName': 'WriteOwnLogs','PolicyDocument': {'Version': '2012-10-17','Statement': [
            {'Effect': 'Allow','Action': ['logs:CreateLogStream','logs:PutLogEvents'],
             'Resource': sub('arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/${AWS::StackName}-search:*')}]}}], 'Tags': tags}},
        'LogGroup': {'Type': 'AWS::Logs::LogGroup','Properties': {
          'LogGroupName': sub('/aws/lambda/${AWS::StackName}-search'),'RetentionInDays': 7}},
        'SearchFunction': {'Type': 'AWS::Lambda::Function','DependsOn': 'LogGroup','Properties': {
          'FunctionName': sub('${AWS::StackName}-search'),'Runtime': 'python3.13','Architectures': ['x86_64'],
          'Handler': 'lambda_handler.handler','Role': att('LambdaRole','Arn'),
          'MemorySize': 256,'Timeout': 15,
          'Code': {'S3Bucket': ref('ArtifactBucket'),'S3Key': ref('ArtifactKey')},
          'Environment': {'Variables': {'PYTHONDONTWRITEBYTECODE': '1'}},'Tags': tags}},
        'GatewayRole': {'Type': 'AWS::IAM::Role','Properties': {
          'AssumeRolePolicyDocument': {'Version': '2012-10-17','Statement': [{
            'Effect': 'Allow','Principal': {'Service': 'bedrock-agentcore.amazonaws.com'},'Action': 'sts:AssumeRole',
            'Condition': {'StringEquals': {'aws:SourceAccount': ref('AWS::AccountId')},
                          'ArnLike': {'aws:SourceArn': sub('arn:${AWS::Partition}:bedrock-agentcore:${AWS::Region}:${AWS::AccountId}:gateway/*')}}}]},
          'Policies': [{'PolicyName': 'InvokeKnowledgeFunction','PolicyDocument': {'Version': '2012-10-17','Statement': [{
            'Effect': 'Allow','Action': 'lambda:InvokeFunction','Resource': att('SearchFunction','Arn')}]}}], 'Tags': tags}},
        'Gateway': {'Type': 'AWS::BedrockAgentCore::Gateway','Properties': {
          'Name': 'x68k-knowledge','Description': 'Public read-only X68000 development references',
          'AuthorizerType': 'NONE','RoleArn': att('GatewayRole','Arn'),'ProtocolType': 'MCP',
          'ProtocolConfiguration': {'Mcp': {'SupportedVersions': ['2025-03-26'], 'Instructions': instructions}},
          'Tags': {'Project': 'x68k-mcp'}}},
        'KnowledgeTarget': {'Type': 'AWS::BedrockAgentCore::GatewayTarget','Properties': {
          'GatewayIdentifier': att('Gateway','GatewayIdentifier'),'Name': 'knowledge',
          'Description': 'Portable SQLite FTS reference snapshot',
          'CredentialProviderConfigurations': [{'CredentialProviderType': 'GATEWAY_IAM_ROLE'}],
          'TargetConfiguration': {'Mcp': {'Lambda': {'LambdaArn': att('SearchFunction','Arn'),
                                                   'ToolSchema': {'InlinePayload': tools}}}}}},
        'RequestLimit': {'Type': 'AWS::BedrockAgentCore::GatewayRateLimit','DependsOn': 'KnowledgeTarget','Properties': {
          'GatewayIdentifier': att('Gateway','GatewayIdentifier'),'RateLimitId': 'knowledge-requests',
          'Description': 'Public read-only target: maximum 60 tool requests per minute',
          'DimensionKeys': ['targetName'],'Entries': [{'Dimensions': {'targetName': 'knowledge'},
                                                     'Requests': [{'Rate': 60,'Period': 'minute'}]}]}},
      },
      'Outputs': {'McpUrl': {'Value': att('Gateway','GatewayUrl')},
                  'FunctionName': {'Value': ref('SearchFunction')},
                  'GatewayId': {'Value': att('Gateway','GatewayIdentifier')}},
    }


async def build(db, output):
    output.mkdir(parents=True, exist_ok=True)
    snapshot = output/'knowledge.sqlite3'
    if snapshot.resolve() == db.resolve():
        raise ValueError('Build output must not replace the source database')
    snapshot.unlink(missing_ok=True)
    with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)) as source:
        with closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
    server = create_server(db)
    instructions = server.instructions
    if not instructions or len(instructions)>2048:
        raise ValueError('Gateway instructions must be 1..2048 characters')
    tools = [{'Name': t.name, 'Description': t.description or '', 'InputSchema': cfn_schema(t.inputSchema)}
             for t in await server.list_tools()]
    (output/'stack.json').write_text(json.dumps(template(tools,instructions),ensure_ascii=False,indent=2)+'\n')
    artifact=output/'lambda.zip'
    files={'lambda_handler.py':ROOT/'aws/lambda_handler.py','knowledge.sqlite3':snapshot,
           'x68k_knowledge/__init__.py':ROOT/'src/x68k_knowledge/__init__.py',
           'x68k_knowledge/corpus.py':ROOT/'src/x68k_knowledge/corpus.py'}
    with zipfile.ZipFile(artifact,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for name,path in files.items():
            info=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            bundle.writestr(info,path.read_bytes())
    digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
    result={'artifact':str(artifact),'artifact_key':f'lambda/{digest}.zip','sha256':digest,
            'compressed_bytes':artifact.stat().st_size,'tools':[t['Name'] for t in tools]}
    (output/'build.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,default=ROOT/'data/knowledge.sqlite3')
    parser.add_argument('--output',type=Path,default=ROOT/'tmp/aws-build');args=parser.parse_args()
    asyncio.run(build(args.db,args.output))
