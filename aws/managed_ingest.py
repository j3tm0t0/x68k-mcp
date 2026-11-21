"""Ingest preprocessed page documents through the native Bedrock document API."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from aws.deploy import run_aws

ROOT=Path(__file__).resolve().parents[1]


def document(path,root):
    metadata=json.loads(path.with_suffix('.txt.metadata.json').read_text())['metadataAttributes']
    attrs=[]
    for key,value in metadata.items():
        kind='NUMBER' if type(value) in (int,float) else 'BOOLEAN' if type(value) is bool else 'STRING'
        field={'NUMBER':'numberValue','BOOLEAN':'booleanValue','STRING':'stringValue'}[kind]
        attrs.append({'key':key,'value':{'type':kind,field:value}})
    return {'content':{'dataSourceType':'CUSTOM','custom':{'customDocumentIdentifier':{'id':path.relative_to(root).as_posix()},'sourceType':'IN_LINE','inlineContent':{'type':'TEXT','textContent':{'data':path.read_text()}}}},'metadata':{'type':'IN_LINE_ATTRIBUTE','inlineAttributes':attrs}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document',action='append');parser.add_argument('--all',action='store_true')
    args=parser.parse_args()
    if bool(args.document)==args.all:parser.error('Select --document paths or --all')
    out=ROOT/'tmp/bedrock-managed';root=out/'documents';state=json.loads((out/'deployment.json').read_text())
    aws=lambda *a,**kw:run_aws(state['profile'],state['region'],*a,**kw)
    sources=json.loads(aws('bedrock-agent','list-data-sources','--knowledge-base-id',state['knowledgeBaseId']))['dataSourceSummaries']
    matches=[s for s in sources if s['name']=='verified-page-ingestion']
    if len(matches)>1:raise RuntimeError('Multiple custom ingestion sources')
    if not matches:
        config={'type':'MANAGED_KNOWLEDGE_BASE_CONNECTOR','managedKnowledgeBaseConnectorConfiguration':{'connectorParameters':{'type':'CUSTOM','version':'1','aclEnabled':False}}}
        request=out/'create-custom-source.json'
        request.write_text(json.dumps({'knowledgeBaseId':state['knowledgeBaseId'],'name':'verified-page-ingestion','dataSourceConfiguration':config,'dataDeletionPolicy':'DELETE'}))
        created=json.loads(aws('bedrock-agent','create-data-source','--cli-input-json','file://'+str(request)))
        (out/'custom-datasource.json').write_text(json.dumps(created,indent=2))
        print('Custom source created; run again once AVAILABLE. No documents sent.',flush=True);return
    ds=matches[0];state['customDataSourceId']=ds['dataSourceId']
    (out/'deployment.json').write_text(json.dumps(state,indent=2))
    status=json.loads(aws('bedrock-agent','get-data-source','--knowledge-base-id',state['knowledgeBaseId'],'--data-source-id',ds['dataSourceId']))['dataSource']['status']
    if status!='AVAILABLE':raise RuntimeError('Custom source not AVAILABLE: '+status)
    paths=sorted(root.rglob('*.txt')) if args.all else [root/p for p in args.document]
    for p in paths:
        if not p.resolve().is_relative_to(root.resolve()):raise ValueError('Document outside export root')
    manifest_path=out/f"direct-ingestion-{state['knowledgeBaseId']}-{ds['dataSourceId']}.json"
    legacy=out/'direct-ingestion.json'
    if not manifest_path.exists() and legacy.exists() and (out/'last-ingest-response.json').exists():
        last=json.loads((out/'last-ingest-response.json').read_text()).get('documentDetails',[])
        if last and all(r.get('knowledgeBaseId')==state['knowledgeBaseId'] and r.get('dataSourceId')==ds['dataSourceId'] for r in last):
            manifest_path.write_text(legacy.read_text())
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    pending=[]
    for p in paths:
        digest=hashlib.sha256(p.read_bytes()+p.with_suffix('.txt.metadata.json').read_bytes()).hexdigest()
        key=p.relative_to(root).as_posix()
        if manifest.get(key,{}).get('sha256')!=digest:pending.append((p,key,digest))
    for offset in range(0,len(pending),10):
        batch=pending[offset:offset+10]
        request={'knowledgeBaseId':state['knowledgeBaseId'],'dataSourceId':ds['dataSourceId'],'documents':[document(p,root) for p,_,_ in batch]}
        path=out/'ingest-request.json';path.write_text(json.dumps(request,ensure_ascii=False))
        result=json.loads(aws('bedrock-agent','ingest-knowledge-base-documents','--cli-input-json','file://'+str(path)))
        (out/'last-ingest-response.json').write_text(json.dumps(result,indent=2))
        details=result.get('documentDetails',[])
        if len(details)!=len(batch) or any(d['status'] in ('FAILED','IGNORED') for d in details):
            raise RuntimeError('Some documents were not accepted; inspect ignored last-ingest-response.json')
        for _,key,digest in batch:manifest[key]={'sha256':digest,'accepted':True}
        manifest_path.write_text(json.dumps(manifest,indent=2));legacy.write_text(json.dumps(manifest,indent=2))
        print(json.dumps({'accepted':len(batch),'accepted_total':len(manifest),'statuses':sorted({d['status'] for d in details})}),flush=True)
        if offset+10<len(pending):time.sleep(1)
    print(json.dumps({'accepted_documents':len(manifest),'unchanged':len(paths)-len(pending)}),flush=True)


if __name__=='__main__':main()
