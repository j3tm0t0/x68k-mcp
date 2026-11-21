"""Report actual document index states, separate from accepted upload checkpoints."""
import json
from collections import Counter
from pathlib import Path
from aws.deploy import run_aws

ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'tmp/bedrock-managed';state=json.loads((out/'deployment.json').read_text())
    result=json.loads(run_aws(state['profile'],state['region'],'bedrock-agent','list-knowledge-base-documents',
      '--knowledge-base-id',state['knowledgeBaseId'],'--data-source-id',state['customDataSourceId'],'--output','json'))
    (out/'document-status.json').write_text(json.dumps(result,indent=2))
    counts=dict(Counter(row['status'] for row in result['documentDetails']))
    expected=state['documents'];indexed=counts.get('INDEXED',0)
    summary={'knowledgeBaseId':state['knowledgeBaseId'],'dataSourceId':state['customDataSourceId'],
      'expected_documents':expected,'listed_documents':len(result['documentDetails']),'states':counts,
      'fully_indexed':indexed==expected and sum(counts.values())==expected,
      'failed_documents':[r for r in result['documentDetails'] if r['status'] in ('FAILED','PARTIALLY_INDEXED','IGNORED')]}
    (out/'index-status.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
