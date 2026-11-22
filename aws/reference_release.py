"""Package private reference data and add a reversible release to the native Gateway."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from aws.managed_gateway import verification_code
from aws.deploy import run_aws

ROOT=Path(__file__).resolve().parents[1]
FLAG='/x68k-mcp/reference-enrichment'
DATA_FILES=('errata-entries.json','effective-references.json','manifest.json')


def package(data_dir,baseline_instructions,output):
    data_dir=Path(data_dir);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    entries=json.loads((data_dir/'errata-entries.json').read_text())
    effective=json.loads((data_dir/'effective-references.json').read_text())
    assert isinstance(entries,list) and effective['records'] and effective['version']
    assert len({r['id'] for r in entries})==len(entries)
    assert {r['id'] for r in effective['records']} <= {r['id'] for r in entries}
    code=verification_code()+'''
from reference_overlay import attach,catalog
from release_switch import enabled,invoke_baseline
_generated_handler=handler
def handler(event,context):
    custom=getattr(getattr(context,'client_context',None),'custom',None) or {}
    tool=custom.get('bedrockAgentCoreToolName')
    if tool not in {'verification___list_sources','verification___read_tables','verification___calculate'}:return {'error':'Unknown tool'}
    if not enabled():return invoke_baseline(event,context,'BASE_VERIFICATION_FUNCTION')
    value=_generated_handler(event,context)
    if tool=='verification___list_sources' and isinstance(value,list):return catalog(value)
    if tool=='verification___read_tables' and isinstance(value,dict) and 'error' not in value:return attach(value,event['source_id'],event['pdf_page'])
    return value
'''
    files={'index.py':code.encode(),'release-config.json':json.dumps({'baseline_instructions':baseline_instructions}).encode()}
    files.update({name:(data_dir/name).read_bytes() for name in DATA_FILES})
    files.update({p.name:p.read_bytes() for p in (ROOT/'aws/errata_runtime').glob('*.py') if p.name!='__init__.py'})
    artifact=output/'reference-release.zip'
    with zipfile.ZipFile(artifact,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,content in sorted(files.items()):
            info=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,content)
    digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
    return {'artifact':str(artifact),'key':f'releases/reference/{digest}.zip','sha256':digest,'data_version':effective['version'],'entry_count':len(entries),'reviewed_count':len(effective['records']),'flag_name':FLAG,'feature_flag_value':'disabled'}


def add_reference_release(stack,release):
    r=stack['Resources'];att=lambda name,key:{'Fn::GetAtt':[name,key]};sub=lambda value:{'Fn::Sub':value}
    if release.get('baseline_calculator_resource'):
        r['Calculator']=release['baseline_calculator_resource']
    flag=release['flag_name'];bucket=release['Bucket'];key=release['key']
    base=r['ReferenceTarget']['Properties']['TargetConfiguration']['Mcp']['Lambda']['LambdaArn']
    baseline=release['baseline_verification_arn']
    # All data and code are immutable artifacts; only this flag changes the active behavior.
    r['ReferenceReleaseFlag']={'Type':'AWS::SSM::Parameter','Properties':{'Name':flag,'Type':'String','Value':release.get('feature_flag_value','disabled'),'Description':'enabled: reviewed references; disabled: immutable original behavior','Tags':{'Project':'x68k-mcp'}}}
    flag_arn=sub('arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter'+flag)
    for role in ['ReferenceRole','EnrichedVerificationRole','RetrievalOverlayRole']:
        statements=[{'Effect':'Allow','Action':'ssm:GetParameter','Resource':flag_arn}]
        if role=='ReferenceRole':statements.append({'Effect':'Allow','Action':'lambda:InvokeFunction','Resource':base})
        if role=='EnrichedVerificationRole':statements.append({'Effect':'Allow','Action':'lambda:InvokeFunction','Resource':baseline})
        if role=='RetrievalOverlayRole':statements.append({'Effect':'Allow','Action':['logs:CreateLogGroup','logs:CreateLogStream','logs:PutLogEvents'],'Resource':sub('arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/x68k-knowledge-reference-*')})
        r[role]={'Type':'AWS::IAM::Role','Properties':{'AssumeRolePolicyDocument':{'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'lambda.amazonaws.com'},'Action':'sts:AssumeRole'}]},'Policies':[{'PolicyName':'ScopedReferenceRelease','PolicyDocument':{'Version':'2012-10-17','Statement':statements}}]}}
    for logical,handler,role,suffix,extra in [
        ('ReferenceFunction','reference_handler.handler','ReferenceRole','page',{'BASE_PAGE_FUNCTION':base}),
        ('EnrichedVerification','index.handler','EnrichedVerificationRole','verification',{'BASE_VERIFICATION_FUNCTION':baseline}),
        ('RetrievalOverlayFunction','retrieval_overlay.handler','RetrievalOverlayRole','retrieval',{})]:
        r[logical]={'Type':'AWS::Lambda::Function','DependsOn':'ReferenceReleaseFlag','Properties':{'FunctionName':'x68k-knowledge-reference-'+suffix,'Runtime':'python3.13','Handler':handler,'Role':att(role,'Arn'),'MemorySize':256,'Timeout':20,'Code':{'S3Bucket':bucket,'S3Key':key},'Environment':{'Variables':{'REFERENCE_RELEASE_FLAG':flag,'KNOWLEDGE_ENVIRONMENT':'production',**extra}}}}
    r['ReferenceTarget']['Properties']['TargetConfiguration']['Mcp']['Lambda']['LambdaArn']=att('ReferenceFunction','Arn')
    r['VerificationTarget']['Properties']['TargetConfiguration']['Mcp']['Lambda']['LambdaArn']=att('EnrichedVerification','Arn')
    gateway=r['Gateway']['Properties']
    gateway['ProtocolConfiguration']['Mcp']['Instructions']=release['instructions']
    gateway['InterceptorConfigurations']=[{'InterceptionPoints':['RESPONSE'],'InputConfiguration':{'PassRequestHeaders':False},'Interceptor':{'Lambda':{'Arn':att('RetrievalOverlayFunction','Arn')}}}]
    policies=r['GatewayRole']['Properties']['Policies'][0]['PolicyDocument']['Statement']
    policies[:]=[s for s in policies if s.get('Resource') not in [base,att('Calculator','Arn')]]
    policies.extend({'Effect':'Allow','Action':'lambda:InvokeFunction','Resource':att(name,'Arn')} for name in ['ReferenceFunction','EnrichedVerification','RetrievalOverlayFunction'])
    stack['Outputs']['ReferenceReleaseFlag']={'Value':{'Ref':'ReferenceReleaseFlag'}}
    return stack


def set_enabled(state_path,value):
    state_path=Path(state_path);state=json.loads(state_path.read_text());release=state['reference_release']
    run_aws(state['profile'],state['region'],'ssm','put-parameter','--name',release['flag_name'],'--type','String','--value',value,'--overwrite')
    release['feature_flag_value']=value;state_path.write_text(json.dumps(state,indent=2))
    print(json.dumps({'reference_release':value,'data_version':release['data_version'],'flag_name':release['flag_name']}))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--enable',action='store_true');p.add_argument('--disable',action='store_true');p.add_argument('--state',type=Path,default=ROOT/'tmp/bedrock-managed/deployment.json');a=p.parse_args()
    if a.enable==a.disable:p.error('Select exactly one of --enable or --disable')
    set_enabled(a.state,'enabled' if a.enable else 'disabled')

if __name__=='__main__':main()
