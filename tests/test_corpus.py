import json
import tempfile
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path

from x68k_knowledge.corpus import Knowledge, build_index, chunk_spans, normalize
from x68k_knowledge.sqlite_export import export_sqlite


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.corpora = []
        for source_id in ["book-a", "book-b"]:
            corpus = self.root / source_id
            corpus.mkdir()
            source = dict(id=source_id, title=source_id, sha256="abc123", path="books/input.pdf")
            source.update(scope_note="Variant-specific peripheral reference", part_numbers=["TEST-IC"],
                          related_issues=["https://github.com/example/project/issues/1"])
            (corpus / "manifest.json").write_text(json.dumps(dict(source=source)))
            text = "割 り込み レジ スタ $E8001B\nFM BG C++ _B_PRINT\nDMA 転送"
            page = dict(source_id=source_id, pdf_page=4, printed_page=None, text=text)
            chunk = dict(page, id=f"{source_id}:p4:c0", start_char=0, end_char=len(text))
            (corpus / "pages.jsonl").write_text(json.dumps(page) + "\n")
            (corpus / "chunks.jsonl").write_text(json.dumps(chunk) + "\n")
            self.corpora.append(corpus)
        self.db = self.root / "knowledge.sqlite3"
        build_index(self.corpora, self.db)
        self.knowledge = Knowledge(self.db)

    def test_japanese_and_ocr_spaces(self):
        self.assertEqual(len(self.knowledge.search("割り込み レジスタ")), 2)
        self.assertEqual(self.knowledge.search("割り込み 存在しない"), [])
        self.assertEqual(normalize("ＡＤＰＣＭ\nレ ジスタ"), "adpcmレジスタ")

    def test_short_terms_symbols_and_literal_query(self):
        for query in ["FM", "BG", "FM BG", "FM $E8001B", "$E8001B", "C++", "_B_PRINT"]:
            with self.subTest(query=query):
                self.assertEqual(len(self.knowledge.search(query)), 2)
        for query in ['" OR "', "*", "';DROP", "%", "x OR nonexistent"]:
            with self.subTest(query=query):
                self.assertEqual(self.knowledge.search(query), [])

    def test_source_filter_page_and_read_only(self):
        result = self.knowledge.search("割り込み", source_id="book-b")
        self.assertEqual([r["source_id"] for r in result], ["book-b"])
        self.assertEqual(result[0]["source_uri"], "books/input.pdf#page=4")
        self.assertEqual(result[0]["scope_note"], "Variant-specific peripheral reference")
        self.assertEqual(result[0]["part_numbers"], ["TEST-IC"])
        self.assertEqual(result[0]["related_issues"], ["https://github.com/example/project/issues/1"])
        self.assertEqual(self.knowledge.page("book-a", 4)["pdf_page"], 4)
        with self.assertRaises(ValueError):
            self.knowledge.page("book-a", 999)
        with self.assertRaises(Exception):
            with self.knowledge.connect() as conn:
                conn.execute("DELETE FROM pages")

    def test_rebuild_idempotent_and_failed_build_preserves_previous(self):
        build_index(self.corpora, self.db)
        self.assertEqual(len(self.knowledge.sources()), 2)
        with self.assertRaises(Exception):
            build_index([self.corpora[0], self.corpora[0]], self.db)
        self.assertEqual(len(self.knowledge.search("DMA")), 2)

    def test_bounds(self):
        for query in ["", " " * 5, "x" * 501, " ".join(["x"] * 17)]:
            with self.assertRaises(ValueError):
                self.knowledge.search(query)
        for limit in [0, -1, 21]:
            with self.assertRaises(ValueError):
                self.knowledge.search("DMA", limit)

    def test_sqlite_logical_export_preserves_rowids_and_search(self):
        output = self.root / "corpus.sql"
        export_sqlite(self.db, output)
        exported_db = self.root / "exported.sqlite3"
        with closing(sqlite3.connect(exported_db)) as conn:
            conn.executescript(output.read_text())
        actual = Knowledge(exported_db)
        self.assertEqual(actual.sources(), self.knowledge.sources())
        self.assertEqual(actual.search("割り込み FM"), self.knowledge.search("割り込み FM"))
        self.assertNotIn("CREATE TABLE 'chunk_fts_data'", output.read_text())
        with self.assertRaises(ValueError):
            export_sqlite(self.db, self.db)

    def test_chunks_cover_original_with_progress_even_at_high_overlap(self):
        text = ("line with whitespace\n" * 200) + "end"
        for overlap in [0, 20, 99]:
            spans = list(chunk_spans(text, 100, overlap))
            self.assertEqual(spans[0][0], 0)
            self.assertEqual(spans[-1][1], len(text))
            for (start, end), (next_start, next_end) in zip(spans, spans[1:]):
                self.assertLess(start, next_start)
                self.assertLessEqual(next_start, end)
                self.assertGreater(next_end, end)
        for size, overlap in [(99, 0), (100, 100), (100, -1)]:
            with self.assertRaises(ValueError):
                list(chunk_spans(text, size, overlap))


if __name__ == "__main__":
    unittest.main()
