import copy
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from aws.reference_release import package,add_reference_release
from aws.managed_gateway import template,add_verification,configure_agentic

RUNTIME=Path(__file__).resolve().parents[1]/'aws/errata_runtime'
sys.path.insert(0,str(RUNTIME))
import reference_overlay as overlay
import reference_handler
import retrieval_overlay
import release_switch

class ReleaseTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)
  entry={'id':'p81_z2','source_id':'inside-x68000','title':'Synthetic topic','location':'fixture','printed_page':81,'candidate_pdf_page':85,'entry_type':'paired_correction','url':'https://example.test/errata#p81_z2'}
  record={'id':entry['id'],'source_id':'inside-x68000','related_pdf_pages':[85],'effective_values':{'fixture':True}}
  for name,value in [('errata-entries.json',[entry]),('effective-references.json',{'version':'fixture-v1','records':[record]}),('manifest.json',{'html_sha256':'0'*64,'target_source_sha256':'1'*64}),('release-config.json',{'baseline_instructions':'original guidance'})]:
   (self.path/name).write_text(json.dumps(value))
  self.addCleanup(overlay.dataset.cache_clear);overlay.dataset.cache_clear()
  env=patch.dict(os.environ,{'ERRATA_DATA_DIRECTORY':str(self.path),'KNOWLEDGE_ENVIRONMENT':'production','REFERENCE_RELEASE_FLAG':'/test/flag','BASE_PAGE_FUNCTION':'fixed-page'});env.start();self.addCleanup(env.stop)
  config=patch.dict(sys.modules,{'botocore.config':SimpleNamespace(Config=lambda **kwargs:kwargs)});config.start();self.addCleanup(config.stop)
 def test_switch_is_uncached_and_fails_to_original_mode(self):
  values=iter(['disabled','enabled','disabled'])
  fake=SimpleNamespace(client=lambda _,**kwargs:SimpleNamespace(get_parameter=lambda **_:{'Parameter':{'Value':next(values)}}))
  with patch.dict(sys.modules,{'boto3':fake}):self.assertEqual([release_switch.enabled() for _ in range(3)],[False,True,False])
  with patch.dict(sys.modules,{'boto3':SimpleNamespace(client=lambda _: (_ for _ in ()).throw(RuntimeError()))}):self.assertFalse(release_switch.enabled())
 def test_page_switch_preserves_original_and_uses_fixed_backend(self):
  original={'text':'Original fixture source','pdf_page':85}
  calls=[]
  def invoke(**kw):calls.append(kw);return {'Payload':io.BytesIO(json.dumps(original).encode())}
  fake=SimpleNamespace(client=lambda _:SimpleNamespace(invoke=invoke))
  context=SimpleNamespace(client_context=SimpleNamespace(custom={'bedrockAgentCoreToolName':'knowledge___get_page'}))
  with patch.dict(sys.modules,{'boto3':fake}):
   for active in [False,True,False]:
    with patch.object(reference_handler,'enabled',return_value=active):value=reference_handler.handler({'source_id':'inside-x68000','pdf_page':85},context)
    self.assertEqual(value['text'],original['text'])
    if active:self.assertEqual(value['errata_overlay_provenance']['environment'],'production')
    else:self.assertEqual(value,original)
  self.assertTrue(all(c['FunctionName']=='fixed-page' for c in calls))
 def test_response_switch_restores_old_instructions_and_native_results(self):
  init={'mcp':{'gatewayRequest':{'body':{'method':'initialize'}},'gatewayResponse':{'statusCode':200,'body':{'jsonrpc':'2.0','id':0,'result':{'instructions':'new'}}}}}
  with patch.object(retrieval_overlay,'enabled',return_value=False):out=retrieval_overlay.handler(init,None)
  self.assertEqual(out['mcp']['transformedGatewayResponse']['body']['result']['instructions'],'original guidance')
  event={'mcp':{'gatewayRequest':{'body':{'method':'tools/call','params':{'name':'managed-kb___Retrieve','arguments':{'retrievalQuery':{'text':'MFP AER'}}}}},'gatewayResponse':{'statusCode':200,'body':{'jsonrpc':'2.0','id':3,'result':{'content':[{'type':'text','text':json.dumps({'retrievalResults':[{'content':{'text':'native'}}]})}]}}}}}
  before=copy.deepcopy(event)
  for active in [True,False]:
   with patch.object(retrieval_overlay,'enabled',return_value=active):out=retrieval_overlay.handler(event,None)
   body=json.loads(out['mcp']['transformedGatewayResponse']['body']['result']['content'][0]['text'])
   self.assertEqual(body['retrievalResults'],[{'content':{'text':'native'}}]);self.assertEqual('editorial_reference_matches' in body,active)
  self.assertEqual(event,before)
 def test_packaging_is_reproducible_and_excludes_unselected_files(self):
  (self.path/'not-selected.pdf').write_bytes(b'not a release asset')
  a=package(self.path,'old',self.path/'a');b=package(self.path,'old',self.path/'b')
  self.assertEqual(a['sha256'],b['sha256'])
  import zipfile
  with zipfile.ZipFile(a['artifact']) as z:
   self.assertNotIn('not-selected.pdf',z.namelist());self.assertIn('release-config.json',z.namelist())
 def test_verification_switch_uses_immutable_baseline_or_new_calculator(self):
  import zipfile
  result=package(self.path,'old',self.path/'build');directory=self.path/'unpacked'
  with zipfile.ZipFile(result['artifact']) as z:z.extractall(directory)
  spec=importlib.util.spec_from_file_location('release_fixture',directory/'index.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  context=SimpleNamespace(client_context=SimpleNamespace(custom={'bedrockAgentCoreToolName':'verification___calculate'}))
  with patch.object(module,'enabled',return_value=True):self.assertEqual(module.handler({'expression':'2+2'},context)['exact'],'4')
  calls=[]
  def invoke(**kw):calls.append(kw);return {'Payload':io.BytesIO(b'{"baseline":true}')}
  with patch.object(module,'enabled',return_value=False),patch.dict(os.environ,{'BASE_VERIFICATION_FUNCTION':'baseline:1'}),patch.dict(sys.modules,{'boto3':SimpleNamespace(client=lambda _:SimpleNamespace(invoke=invoke))}):
   self.assertEqual(module.handler({'expression':'2+2'},context),{'baseline':True})
  self.assertEqual(calls[0]['FunctionName'],'baseline:1')
 def test_deployment_keeps_gateway_identity_and_binds_one_scoped_switch(self):
  base=configure_agentic(add_verification(template({'knowledgeBaseId':'fixture','knowledgeBaseArn':'arn:fixture'})),False)
  original=copy.deepcopy(base)
  release={'Bucket':'fixture','key':'releases/test.zip','flag_name':'/test/flag','baseline_verification_arn':'arn:aws:lambda:region:account:function:original:1','instructions':'new'}
  out=add_reference_release(base,release)['Resources']
  self.assertEqual(out['Gateway']['Properties']['Name'],original['Resources']['Gateway']['Properties']['Name'])
  self.assertEqual(out['Calculator'],original['Resources']['Calculator'])
  for name in ['ReferenceFunction','EnrichedVerification','RetrievalOverlayFunction']:
   self.assertEqual(out[name]['Properties']['Environment']['Variables']['REFERENCE_RELEASE_FLAG'],'/test/flag')
  self.assertEqual(out['ReferenceReleaseFlag']['Properties']['Value'],'disabled')
  self.assertEqual(out['Gateway']['Properties']['AuthorizerType'],'NONE')

if __name__=='__main__':unittest.main()
