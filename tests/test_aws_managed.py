import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from aws.managed import export, data_template
from aws.managed_gateway import template, INSTRUCTIONS


class ManagedExportTests(unittest.TestCase):
    def test_page_metadata_and_annotations_survive_without_pdf_or_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=root/'input.sqlite3';conn=sqlite3.connect(db)
            conn.executescript('CREATE TABLE sources(id TEXT, metadata TEXT); CREATE TABLE pages(source_id TEXT,pdf_page INTEGER,metadata TEXT); CREATE TABLE chunks(id TEXT,source_id TEXT,pdf_page INTEGER,metadata TEXT);')
            source={'id':'test','title':'Manual','sha256':'a'*64,'url':'https://example.org/manual','content_guide':[]}
            page={'text':'unreviewed source','structured_tables':[{'id':'t','rows':[{'software':False}]}]}
            conn.execute('INSERT INTO sources VALUES (?,?)',('test',json.dumps(source)))
            conn.execute('INSERT INTO pages VALUES (?,?,?)',('test',7,json.dumps(page)))
            conn.commit();conn.close()
            self.assertEqual(export(db,root/'export'),1)
            files=sorted((root/'export').rglob('*.*'))
            self.assertEqual({p.suffix for p in files},{'.txt','.json'})
            text=(root/'export/test/p0007.txt').read_text()
            self.assertIn('PDF page (1-based): 7',text)
            self.assertIn('"software": false',text)
            self.assertIn('NOT human review',text)
            metadata=json.loads((root/'export/test/p0007.txt.metadata.json').read_text())
            self.assertEqual(metadata['metadataAttributes']['pdf_page'],7)
            self.assertEqual(metadata['metadataAttributes']['source_id'],'test')
            self.assertEqual(set(source),{'id','title','sha256','url','content_guide'})

    def test_native_gateway_binds_kb_and_limits_costly_tools(self):
        resources=template({'knowledgeBaseId':'ABC','knowledgeBaseArn':'arn:test'})['Resources']
        configurations=resources['ManagedTarget']['Properties']['TargetConfiguration']['Mcp']['Connector']['Configurations']
        self.assertEqual(configurations[0]['ParameterValues']['knowledgeBaseId'],'ABC')
        self.assertEqual(configurations[0]['ParameterOverrides'],[{'Path':'$.retrievalQuery.text','Visible':True}])
        self.assertEqual(configurations[1]['ParameterValues']['agenticRetrieveConfiguration']['maxAgentIteration'],3)
        self.assertLessEqual(len(INSTRUCTIONS),2048)
        self.assertEqual(resources['RateLimit']['Properties']['Entries'][0]['Requests'][0]['Rate'],6)
        bucket=data_template()['Resources']['Documents']['Properties']
        self.assertTrue(all(bucket['PublicAccessBlockConfiguration'].values()))
