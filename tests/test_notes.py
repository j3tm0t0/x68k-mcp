import hashlib
import tempfile
import unittest
from pathlib import Path

from x68k_knowledge.corpus import Knowledge, build_index, records
from x68k_knowledge.sqlite_export import export_sqlite
from x68k_knowledge.notes import ingest_notes


class NotesTests(unittest.TestCase):
    def test_web_notes_keep_source_url_and_do_not_invent_pdf_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "notes.md"
            text = "# Peripheral notes\n\nPCM69 の制御と DMA。\n" * 50
            path.write_text(text)
            source = dict(id="web-notes", title="Notes", kind="web-notes", url="https://example.com/reference")
            corpus = root / "corpus"
            manifest = ingest_notes(path, corpus, source)
            self.assertEqual(manifest["page_count"], 0)
            self.assertEqual(manifest["source"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(list(records(corpus / "pages.jsonl")), [])
            for chunk in records(corpus / "chunks.jsonl"):
                self.assertIsNone(chunk["pdf_page"])
                self.assertEqual(chunk["text"], text[chunk["start_char"]:chunk["end_char"]])
            db = root / "search.sqlite3"
            build_index([corpus], db)
            k = Knowledge(db)
            hit = k.search("PCM69 DMA", 1)[0]
            self.assertIsNone(hit["pdf_page"])
            self.assertEqual(hit["source_uri"], source["url"])
            self.assertEqual(hit["source_kind"], "web-notes")
            with self.assertRaises(ValueError):
                k.page(source["id"], 1)
            export_sqlite(db, root / "export.sql")

    def test_empty_or_unattributed_notes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "notes.md"
            path.write_text(" ")
            source = dict(id="notes", kind="web-notes", url="https://example.com")
            with self.assertRaises(ValueError):
                ingest_notes(path, root / "output", source)
            path.write_text("Some text")
            with self.assertRaises(ValueError):
                ingest_notes(path, root / "output", dict(source, url="file:///tmp/input"))
