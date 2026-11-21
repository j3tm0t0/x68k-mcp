import unittest
from types import SimpleNamespace
from aws.verification import read_tables,SOURCES
from aws.managed_gateway import verification_code,add_verification,template,configure_agentic


class ScopedTableTests(unittest.TestCase):
    def test_full_table_keeps_both_frequencies_unsupported_and_independent_vram(self):
        result=read_tables('inside-x68000',171)
        modes=result['tables'][0]
        self.assertEqual(len(modes['rows']),8)
        self.assertTrue(all(row['software'] is False for row in modes['rows'] if row['display']=='512×256'))
        self.assertEqual(sum('512×256' in line and '対応なし' in line for line in modes['markdown'].splitlines()),2)
        self.assertEqual(len(result['tables'][1]['rows']),4)
        self.assertEqual(result['review_status'],'image_checked_by_ai_not_human_reviewed')
        self.assertEqual(read_tables('inside-x68000',172)['tables'],[])

    def test_packaged_inline_handler_uses_same_math_and_tables_without_other_files(self):
        namespace={};exec(compile(verification_code(),'inline-verification','exec'),namespace)
        context=SimpleNamespace(client_context=SimpleNamespace(custom={'bedrockAgentCoreToolName':'verification___read_tables'}))
        self.assertEqual(namespace['handler']({'source_id':'inside-x68000','pdf_page':171},context),read_tables('inside-x68000',171))
        context.client_context.custom['bedrockAgentCoreToolName']='verification___calculate'
        self.assertEqual(namespace['handler']({'expression':'1024*16/4000'},context)['decimal'],'4.096')
        context.client_context.custom['bedrockAgentCoreToolName']='other___read_tables'
        self.assertIn('error',namespace['handler']({'source_id':'inside-x68000','pdf_page':171},context))
        stack=add_verification(template({'knowledgeBaseId':'ABC','knowledgeBaseArn':'arn:test'}))
        self.assertLessEqual(len(stack['Resources']['Gateway']['Properties']['ProtocolConfiguration']['Mcp']['Instructions']),2048)

        self.assertEqual(len(stack['Resources']['RateLimit']['Properties']['Entries']),3)
        self.assertEqual(sum(r['Type']=='AWS::BedrockAgentCore::GatewayRateLimit' for r in stack['Resources'].values()),1)

    def test_incomplete_agentic_generation_is_disabled_by_default_configuration(self):
        stack=configure_agentic(add_verification(template({'knowledgeBaseId':'ABC','knowledgeBaseArn':'arn:test'})),False)
        resources=stack['Resources']
        configurations=resources['ManagedTarget']['Properties']['TargetConfiguration']['Mcp']['Connector']['Configurations']
        self.assertEqual([c['Name'] for c in configurations],['Retrieve'])
        self.assertFalse(any(s['Action']=='bedrock:AgenticRetrieveStream' for s in resources['GatewayRole']['Properties']['Policies'][0]['PolicyDocument']['Statement']))
        self.assertNotIn('AgenticRetrieveStream',resources['Gateway']['Properties']['ProtocolConfiguration']['Mcp']['Instructions'])

    def test_catalog_distinguishes_full_image_annotations_from_raw_ocr_tables(self):
        catalog={source['id']:source for source in SOURCES}
        self.assertIn(171,catalog['inside-x68000']['image_checked_table_pages'])
        maps=[entry for entry in catalog['inside-x68000']['image_checked_table_catalog'] if entry['pdf_page']==33]
        self.assertIn('dmac-register-address-map',[t['id'] for t in maps[0]['tables']])
        self.assertNotIn('rows',str(maps))
        self.assertEqual(catalog['oki-msm6258']['image_checked_table_pages'],[])
