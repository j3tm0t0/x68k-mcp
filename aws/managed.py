"""Managed Bedrock KB provisioning and page-preserving export (no PDF/key upload)."""
import argparse
import os
import hashlib
import json
import sqlite3
from pathlib import Path
from aws.deploy import run_aws, check_stack_owner

ROOT=Path(__file__).resolve().parents[1]


def data_template():
    return {'AWSTemplateFormatVersion':'2010-09-09','Resources':{
      'Documents':{'Type':'AWS::S3::Bucket','DeletionPolicy':'Retain','UpdateReplacePolicy':'Retain','Properties':{
        'PublicAccessBlockConfiguration':dict(BlockPublicAcls=True,IgnorePublicAcls=True,BlockPublicPolicy=True,RestrictPublicBuckets=True),
        'BucketEncryption':{'ServerSideEncryptionConfiguration':[{'ServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]}}},
      'IngestRole':{'Type':'AWS::IAM::Role','Properties':{
        'AssumeRolePolicyDocument':{'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'bedrock.amazonaws.com'},'Action':'sts:AssumeRole','Condition':{'StringEquals':{'aws:SourceAccount':{'Ref':'AWS::AccountId'}},'ArnLike':{'aws:SourceArn':{'Fn::Sub':'arn:${AWS::Partition}:bedrock:${AWS::Region}:${AWS::AccountId}:knowledge-base/*'}}}}]},
        'Policies':[{'PolicyName':'ReadOwnDocuments','PolicyDocument':{'Version':'2012-10-17','Statement':[
          {'Effect':'Allow','Action':['s3:ListBucket'],'Resource':{'Fn::GetAtt':['Documents','Arn']}},
          {'Effect':'Allow','Action':['s3:GetObject'],'Resource':{'Fn::Sub':'${Documents.Arn}/documents/*'}}]}}]}}},
      'Outputs':{'Bucket':{'Value':{'Ref':'Documents'}},'RoleArn':{'Value':{'Fn::GetAtt':['IngestRole','Arn']}}}}


def export(db, destination):
    destination.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect('file:'+str(db.resolve())+'?mode=ro',uri=True)
    sources={sid:json.loads(meta) for sid,meta in conn.execute('SELECT id,metadata FROM sources')}
    count=0
    for sid,page,meta in conn.execute('SELECT source_id,pdf_page,metadata FROM pages ORDER BY source_id,pdf_page'):
        source=sources[sid];record=json.loads(meta)
        lines=[f"Source ID: {sid}",f"Title: {source['title']}",f"PDF page (1-based): {page}",
               f"Source URL: {source.get('url','')}",f"Source SHA256: {source.get('sha256','')}"]
        from x68k_knowledge.corpus import navigation_context
        lines += ['\nCatalog navigation (editorial, not source quotation):',*navigation_context(source,page)]
        if record.get('structured_tables'):
            lines += ['\nImage-checked annotations. AI checks, NOT human review. Prefer these relationships within their stated scope.',record.get('structured_table_text') or json.dumps(record['structured_tables'],ensure_ascii=False,indent=2)]
        lines += ['\nUnreviewed extracted source text; OCR alignment/numerical errors possible:',record.get('text','')]
        target=destination/sid/f'p{page:04d}.txt';target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text('\n'.join(lines))
        metadata={'metadataAttributes':{'source_id':sid,'source_title':source['title'],'pdf_page':page,'review_status':'unreviewed_ocr_with_scoped_ai_annotations' if record.get('structured_tables') else 'unreviewed_ocr'}}
        target.with_suffix('.txt.metadata.json').write_text(json.dumps(metadata,ensure_ascii=False))
        count+=1
    for sid,meta in conn.execute('SELECT source_id,metadata FROM chunks WHERE pdf_page IS NULL ORDER BY id'):
        source=sources[sid];chunk=json.loads(meta)
        target=destination/sid/'web-notes.txt';target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(f"Source ID: {sid}\nTitle: {source['title']}\nSource URL: {source.get('url','')}\nScope: {source.get('scope_note','')}\n\n"+chunk['text'])
        target.with_suffix('.txt.metadata.json').write_text(json.dumps({'metadataAttributes':{'source_id':sid,'source_title':source['title'],'source_url':source.get('url',''),'review_status':source.get('review_status','unreviewed')}},ensure_ascii=False))
        count+=1
    conn.close()
    print(json.dumps({'documents':count,'directory':str(destination)}),flush=True)
    return count


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',default=os.environ.get('AWS_PROFILE', 'default'));parser.add_argument('--region',default='ap-northeast-1')
    parser.add_argument('--export-only',action='store_true')
    args=parser.parse_args();out=ROOT/'tmp/bedrock-managed';out.mkdir(parents=True,exist_ok=True)
    count=export(ROOT/'data/knowledge.sqlite3',out/'documents')
    if args.export_only:return
    aws=lambda *a,**kw:run_aws(args.profile,args.region,*a,**kw)
    stack='x68k-knowledge-native-data';check_stack_owner(args.profile,args.region,stack)
    template=out/'data-stack.json';template.write_text(json.dumps(data_template()))
    aws('cloudformation','deploy','--stack-name',stack,'--template-file',str(template),'--capabilities','CAPABILITY_IAM','--tags','Project=x68k-mcp','--no-fail-on-empty-changeset',capture=False)
    outputs=json.loads(aws('cloudformation','describe-stacks','--stack-name',stack,'--query','Stacks[0].Outputs','--output','json'))
    values={o['OutputKey']:o['OutputValue'] for o in outputs}
    existing=json.loads(aws('bedrock-agent','list-knowledge-bases','--output','json'))['knowledgeBaseSummaries']
    matched=[k for k in existing if k['name']=='x68k-knowledge-native']
    if matched:
        kb=json.loads(aws('bedrock-agent','get-knowledge-base','--knowledge-base-id',matched[0]['knowledgeBaseId']))['knowledgeBase']
        tags=json.loads(aws('bedrock-agent','list-tags-for-resource','--resource-arn',kb['knowledgeBaseArn']))['tags']
        if tags.get('Project')!='x68k-mcp':raise ValueError('Knowledge base belongs to another project')
    else:
        request={'name':'x68k-knowledge-native','description':'X68000 page-preserving references and scoped annotations','roleArn':values['RoleArn'],
          'knowledgeBaseConfiguration':{'type':'MANAGED','managedKnowledgeBaseConfiguration':{'embeddingModelType':'MANAGED'}},'tags':{'Project':'x68k-mcp'}}
        path=out/'create-kb.json';path.write_text(json.dumps(request))
        kb=json.loads(aws('bedrock-agent','create-knowledge-base','--cli-input-json','file://'+str(path)))['knowledgeBase']
    values.update(knowledgeBaseId=kb['knowledgeBaseId'],knowledgeBaseArn=kb['knowledgeBaseArn'],region=args.region,profile=args.profile,documents=count)
    (out/'deployment.json').write_text(json.dumps(values,indent=2))
    print(json.dumps(values),flush=True)


if __name__=='__main__':main()
