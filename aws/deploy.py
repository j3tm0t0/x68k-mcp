"""Build and deploy the read-only AWS MCP with an explicitly selected AWS profile."""
import argparse
import os
import asyncio
import json
import subprocess
from pathlib import Path

from aws.build import ROOT, build


def run_aws(profile, region, *arguments, capture=True):
    result=subprocess.run(['aws','--profile',profile,'--region',region,*arguments],
                          text=True,capture_output=capture)
    if result.returncode:
        raise RuntimeError('AWS command failed: '+ ' '.join(arguments[:3]) + ('\n'+result.stderr if capture else ''))
    return result.stdout.strip() if capture else ''


def check_stack_owner(profile,region,name):
    result=subprocess.run(['aws','--profile',profile,'--region',region,'cloudformation','describe-stacks','--stack-name',name,'--output','json'],text=True,capture_output=True)
    if result.returncode:
        if 'does not exist' in result.stderr:
            return
        raise RuntimeError('Cannot inspect existing stack '+name)
    stack=json.loads(result.stdout)['Stacks'][0]
    if not any(t['Key']=='Project' and t['Value']=='x68k-mcp' for t in stack.get('Tags',[])):
        raise RuntimeError('Existing stack is not owned by this project: '+name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',default=os.environ.get('AWS_PROFILE', 'default'));parser.add_argument('--region',default='ap-northeast-1')
    parser.add_argument('--stack-name',default='x68k-knowledge-aws')
    parser.add_argument('--db',type=Path,default=ROOT/'data/knowledge.sqlite3')
    parser.add_argument('--keep-failed',action='store_true',help='Keep newly created resources for diagnosing a failed deployment')
    args=parser.parse_args()
    output=ROOT/'tmp/aws-build';artifact_stack='x68k-knowledge-artifacts'
    for stack in (artifact_stack,args.stack_name):check_stack_owner(args.profile,args.region,stack)
    asyncio.run(build(args.db,output))
    manifest=json.loads((output/'build.json').read_text())
    run_aws(args.profile,args.region,'cloudformation','deploy','--template-file',str(ROOT/'aws/artifacts-stack.json'),
            '--stack-name',artifact_stack,'--tags','Project=x68k-mcp','--no-fail-on-empty-changeset',capture=False)
    outputs=json.loads(run_aws(args.profile,args.region,'cloudformation','describe-stacks','--stack-name',artifact_stack,'--query','Stacks[0].Outputs','--output','json'))
    bucket=next(o['OutputValue'] for o in outputs if o['OutputKey']=='BucketName')
    run_aws(args.profile,args.region,'s3','cp',manifest['artifact'],f"s3://{bucket}/{manifest['artifact_key']}",'--only-show-errors',capture=False)
    run_aws(args.profile,args.region,'cloudformation','validate-template','--template-body','file://'+str(output/'stack.json'))
    run_aws(args.profile,args.region,'cloudformation','deploy','--template-file',str(output/'stack.json'),
            '--stack-name',args.stack_name,'--capabilities','CAPABILITY_IAM',
            '--parameter-overrides',f'ArtifactBucket={bucket}',f"ArtifactKey={manifest['artifact_key']}",
            '--tags','Project=x68k-mcp','--no-fail-on-empty-changeset',
            *(['--disable-rollback'] if args.keep_failed else []),capture=False)
    outputs=json.loads(run_aws(args.profile,args.region,'cloudformation','describe-stacks','--stack-name',args.stack_name,'--query','Stacks[0].Outputs','--output','json'))
    values={o['OutputKey']:o['OutputValue'] for o in outputs}
    values.update(profile=args.profile,region=args.region,stack_name=args.stack_name,
                  artifact_bucket=bucket,artifact_key=manifest['artifact_key'],artifact_sha256=manifest['sha256'])
    (ROOT/'tmp/aws-deployment.json').write_text(json.dumps(values,indent=2)+'\n')
    print(json.dumps(values,ensure_ascii=False,indent=2),flush=True)
    payload=output/'health-request.json';payload.write_text('{"__health":true}')
    result=output/'health-response.json'
    response=json.loads(run_aws(args.profile,args.region,'lambda','invoke','--function-name',values['FunctionName'],
                               '--payload','fileb://'+str(payload),str(result),'--output','json'))
    if response.get('FunctionError'):
        raise RuntimeError('Lambda health failed; inspect tmp/aws-build/health-response.json')
    print('Lambda health: '+result.read_text(),flush=True)


if __name__=='__main__':main()
