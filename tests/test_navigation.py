import json
import shutil
import sqlite3
import unittest

import test_corpus
from x68k_knowledge.corpus import Knowledge, build_index
from x68k_knowledge.navigation import refresh_navigation_index


class NavigationIndexTests(unittest.TestCase):
    def setUp(self):
        test_corpus.CorpusTests.setUp(self)
        self.corpus=self.corpora[0]
        self.manifest=json.loads((self.corpus/'manifest.json').read_text())
        self.manifest['source']['content_guide']=[{'topic':"OPM timer B's period",'pdf_pages':[4], 'keywords':['タイマB','周期']}]
        (self.corpus/'manifest.json').write_text(json.dumps(self.manifest))
        with sqlite3.connect(self.db) as conn:
            conn.execute('UPDATE sources SET metadata=? WHERE id=?',
                         (json.dumps(self.manifest['source']),'book-a'))
        self.sql=self.root/'navigation.sql'

    def test_context_retrieval_and_patch_rebuild_parity_without_rewriting_text(self):
        original=self.knowledge.page('book-a',4)['text']
        self.assertEqual(self.knowledge.search('OPM timer B'),[])
        remote=self.root/'remote.sqlite3'
        shutil.copy2(self.db,remote)
        result=refresh_navigation_index(self.db,self.sql)
        self.assertEqual(result['updated_chunks'],1)
        with sqlite3.connect(remote) as conn:
            conn.executescript(self.sql.read_text())
        hits=self.knowledge.search('OPM timer B')
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0]['source_id'],'book-a')
        self.assertIn("OPM timer B's period",' '.join(hits[0]['navigation_context']))
        self.assertEqual(self.knowledge.search('タイマB 周期'),hits)
        self.assertEqual(hits[0]['text'],original)
        self.assertEqual(self.knowledge.page('book-a',4)['text'],original)
        self.assertEqual(self.knowledge.page('book-a',4)['navigation_context'], ["OPM timer B's period タイマB 周期"])
        self.assertNotIn('navigation_context',self.knowledge.search('FM',source_id='book-b')[0])
        self.assertEqual(Knowledge(remote).search('OPM timer B'),hits)
        rebuilt=self.root/'rebuilt.sqlite3'
        build_index(self.corpora,rebuilt)
        self.assertEqual(Knowledge(rebuilt).search('OPM timer B'),hits)
        self.assertEqual(refresh_navigation_index(self.db,self.sql)['updated_chunks'],0)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM chunk_fts').fetchone()[0],2)

    def test_patch_rejects_wrong_edition_before_changing_index(self):
        remote=self.root/'wrong.sqlite3';shutil.copy2(self.db,remote)
        refresh_navigation_index(self.db,self.sql)
        with sqlite3.connect(remote) as conn:
            conn.execute("UPDATE sources SET metadata=json_set(metadata,'$.sha256','different') WHERE id='book-a'")
            conn.commit()
            before=conn.execute('SELECT search_text FROM chunks ORDER BY id').fetchall()
            with self.assertRaises(sqlite3.OperationalError):conn.executescript(self.sql.read_text())
            self.assertEqual(conn.execute('SELECT search_text FROM chunks ORDER BY id').fetchall(),before)
