"""Upload exported page text and start one ingestion job (no automatic polling)."""
import json
from pathlib import Path
from aws.deploy import run_aws

ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'tmp/bedrock-managed';state=json.loads((out/'deployment.json').read_text())
    aws=lambda *a,**kw:run_aws(state['profile'],state['region'],*a,**kw)
    kb=json.loads(aws('bedrock-agent','get-knowledge-base','--knowledge-base-id',state['knowledgeBaseId']))['knowledgeBase']
    if kb['status']!='ACTIVE':raise RuntimeError('Knowledge base not ACTIVE: '+kb['status'])
    aws('s3','sync',str(out/'documents'),f"s3://{state['Bucket']}/documents/",'--only-show-errors',capture=False)
    sources=json.loads(aws('bedrock-agent','list-data-sources','--knowledge-base-id',state['knowledgeBaseId']))['dataSourceSummaries']
    account=state['knowledgeBaseArn'].split(':')[4]
    request={'knowledgeBaseId':state['knowledgeBaseId'],'name':'page-text','dataDeletionPolicy':'DELETE',
      'dataSourceConfiguration':{'type':'MANAGED_KNOWLEDGE_BASE_CONNECTOR','managedKnowledgeBaseConnectorConfiguration':{'connectorParameters':{
        'type':'S3','version':'1','connectionConfiguration':{'bucketName':state['Bucket'],'bucketOwnerAccountId':account},
        'filterConfiguration':{'inclusionPrefixes':['documents/'],'inclusionPatterns':['.*[.]txt']}}}},
      'vectorIngestionConfiguration':{'parsingConfiguration':{'parsingStrategy':'SMART_PARSING'}}}
    path=out/'datasource-request.json'
    if sources:
        if len(sources)!=1 or sources[0]['name']!='page-text':raise RuntimeError('Unexpected data source')
        ds=json.loads(aws('bedrock-agent','get-data-source','--knowledge-base-id',state['knowledgeBaseId'],'--data-source-id',sources[0]['dataSourceId']))['dataSource']
        params=ds['dataSourceConfiguration']['managedKnowledgeBaseConnectorConfiguration']['connectorParameters']
        if isinstance(params,str):params=json.loads(params)
        if params.get('filterConfiguration',{}).get('inclusionPatterns')!=['.*[.]txt']:
            request['dataSourceId']=ds['dataSourceId'];path.write_text(json.dumps(request))
            ds=json.loads(aws('bedrock-agent','update-data-source','--cli-input-json','file://'+str(path)))['dataSource']
    else:
        path.write_text(json.dumps(request))
        ds=json.loads(aws('bedrock-agent','create-data-source','--cli-input-json','file://'+str(path)))['dataSource']
    state['dataSourceId']=ds['dataSourceId'];(out/'deployment.json').write_text(json.dumps(state,indent=2))
    if ds['status']!='AVAILABLE':
        print(json.dumps({'dataSourceId':ds['dataSourceId'],'status':ds['status'],'next':'Run this module again once AVAILABLE; no ingestion started.'}));return
    jobs=json.loads(aws('bedrock-agent','list-ingestion-jobs','--knowledge-base-id',state['knowledgeBaseId'],'--data-source-id',ds['dataSourceId']))['ingestionJobSummaries']
    active=[j for j in jobs if j['status'] in ('STARTING','IN_PROGRESS')]
    if active:print(json.dumps(active));return
    job=json.loads(aws('bedrock-agent','start-ingestion-job','--knowledge-base-id',state['knowledgeBaseId'],'--data-source-id',ds['dataSourceId']))['ingestionJob']
    (out/'ingestion.json').write_text(json.dumps(job,indent=2));print(json.dumps(job),flush=True)


if __name__=='__main__':main()
