import copy
import json
import sqlite3
import unittest
from pathlib import Path

import test_corpus
from x68k_knowledge.corpus import Knowledge, build_index
from x68k_knowledge.tables import attach_tables, materialize


class StructuredTableTests(unittest.TestCase):
    def setUp(self):
        test_corpus.CorpusTests.setUp(self)
        self.bundle = dict(schema_version=1, source_id="book-a", source_sha256="abc123",
                           pdf_page=4, origin_label="table 1", review_status="image_checked_by_ai_not_human_reviewed",
                           review_method="Page image checked; no human review", scope_note="Test table",
                           tables=[dict(id="display-modes", title="画面モード",
                                        columns=[dict(key="mode", label="表示"), dict(key="supported", label="IOCS")],
                                        rows=[dict(mode="512×256", supported=False)])])
        self.path = self.root / "table.json"
        self.sql = self.root / "tables.sql"

    def attach(self):
        self.path.write_text(json.dumps(self.bundle))
        return attach_tables(self.path, self.corpora[0], self.db, self.sql)

    def test_structured_cells_search_and_immutable_ocr(self):
        before = self.knowledge.page("book-a", 4)["text"]
        raw = (self.corpora[0] / "pages.jsonl").read_bytes()
        self.attach()
        hit = self.knowledge.search("画面モード", source_id="book-a")[0]
        self.assertEqual(hit["record_type"], "structured-table")
        self.assertIs(hit["structured_tables"][0]["rows"][0]["supported"], False)
        self.assertIsNone(hit["start_char"])
        self.assertEqual(hit["pdf_page"], 4)
        self.assertIn("IOCS=対応なし", hit["text"])
        self.assertEqual(self.knowledge.page("book-a", 4)["text"], before)
        self.assertEqual((self.corpora[0] / "pages.jsonl").read_bytes(), raw)

    def test_idempotent_patch_rebuild_and_sqlite_delta_parity(self):
        remote = self.root / "remote.sqlite3"
        build_index(self.corpora, remote)
        self.attach()
        self.attach()
        with sqlite3.connect(remote) as conn:
            conn.executescript(self.sql.read_text())
            conn.executescript(self.sql.read_text())
        self.assertEqual(Knowledge(remote).search("画面モード"), self.knowledge.search("画面モード"))
        self.assertEqual(Knowledge(remote).page("book-a", 4), self.knowledge.page("book-a", 4))
        rebuild = self.root / "rebuilt.sqlite3"
        build_index(self.corpora, rebuild)
        self.assertEqual(Knowledge(rebuild).search("画面モード"), self.knowledge.search("画面モード"))
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM chunks").fetchone()[0], 3)

    def test_search_keeps_nonmatching_sibling_tables_and_partial_page_ocr(self):
        sibling = dict(id='colors', title='Color configurations',
                       columns=[dict(key='colors', label='色数'), dict(key='display_sizes', label='表示解像度')],
                       rows=[dict(colors=256, display_sizes=['512×512', '512×256', '256×256'])])
        self.bundle['tables'].append(sibling)
        self.attach()
        hits = self.knowledge.search('画面モード', limit=1, source_id='book-a')
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit['matched_table_ids'], ['display-modes'])
        self.assertEqual(hit['structured_tables'], self.bundle['tables'])
        self.assertIn('Color configurations', hit['text'])
        self.assertEqual(hit['table_context_scope'], 'all_annotated_tables_on_same_page')
        raw = self.knowledge.search('DMA', source_id='book-a')[0]
        self.assertIn('DMA 転送', raw['text'])
        self.assertEqual(raw['structured_tables'], self.bundle['tables'])
        self.assertEqual(raw['matched_table_ids'], [])
        other = self.knowledge.search('DMA', source_id='book-b')[0]
        self.assertNotIn('structured_tables', other)

    def test_search_collapses_structured_matches_and_omits_same_page_ocr_duplicates(self):
        sibling = copy.deepcopy(self.bundle['tables'][0])
        sibling.update(id='other-table', title='画面モード 別表')
        self.bundle['tables'].append(sibling)
        self.attach()
        raw = dict(id='raw-table',source_id='book-a',pdf_page=4,text='画面モード CORRUPT_OCR_TABLE')
        with sqlite3.connect(self.db) as conn:
            cursor = conn.execute('INSERT INTO chunks VALUES (?,?,?,?,?)',
                (raw['id'],'book-a',4,json.dumps(raw),'画面モードcorrupt_ocr_table'))
            conn.execute('INSERT INTO chunk_fts(rowid,search_text) VALUES (?,?)',
                (cursor.lastrowid,'画面モードcorrupt_ocr_table'))
        hits = self.knowledge.search('画面モード',limit=20,source_id='book-a')
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0]['matched_table_ids'],['display-modes','other-table'])
        self.assertNotIn('CORRUPT_OCR_TABLE', json.dumps(hits))
        self.assertIn('別表',hits[0]['text'])

    def test_wrong_edition_page_or_misaligned_row_rejected(self):
        source = self.knowledge.sources()[0]
        pages = {4: self.knowledge.page("book-a", 4)}
        for mutation in [dict(source_sha256="wrong"), dict(pdf_page=5), dict(pdf_page=True)]:
            with self.assertRaises(ValueError):
                materialize(dict(self.bundle, **mutation), source, pages)
        malformed = copy.deepcopy(self.bundle)
        malformed["tables"][0]["rows"][0].pop("supported")
        with self.assertRaises(ValueError):
            materialize(malformed, source, pages)

    def test_remote_edition_guard_precedes_mutation(self):
        self.attach()
        remote = self.root / "other-edition.sqlite3"
        build_index(self.corpora, remote)
        with sqlite3.connect(remote) as conn:
            conn.execute("UPDATE sources SET metadata=json_set(metadata,'$.sha256','different') WHERE id='book-a'")
            conn.commit()
            before = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
            with self.assertRaises(sqlite3.OperationalError):
                conn.executescript(self.sql.read_text())
            self.assertEqual(conn.execute("SELECT count(*) FROM chunks").fetchone()[0], before)

    def test_page171_color_cells_are_independent_of_display_resolution(self):
        bundle = json.loads((Path(__file__).resolve().parents[1] / "tables/inside-x68000-p0171.json").read_text())
        display, vram = bundle["tables"]
        row = next(r for r in display["rows"] if r["display"] == "512×256" and r["horizontal_khz"] == 31)
        self.assertTrue(row["hardware"])
        self.assertFalse(row["software"])
        self.assertEqual(row["scan"], "二度読み")
        scan = next(r for r in display["rows"] if r["display"] == "512×512" and r["horizontal_khz"] == 31)
        self.assertNotEqual(scan["scan"], "インターレース")
        for colors, pages in [(65536, 1), (256, 2), (16, 4)]:
            mode = next(r for r in vram["rows"] if r["colors"] == colors and r["pages"] == pages)
            self.assertEqual(mode["virtual_screen"], "512×512")
            self.assertEqual(mode["display_sizes"], ["512×512", "512×256", "256×256"])

    def test_sound_pan_resistors_keep_decimal_points_and_limit_corrections_to_their_locations(self):
        bundle = json.loads((Path(__file__).resolve().parents[1] / 'tables/inside-x68000-p0264.json').read_text())
        rows = bundle['tables'][0]['rows']
        self.assertEqual([row['resistance_ohms'] for row in rows], [4700, 1500, 2200])
        self.assertIn('PPI', rows[0]['location'])
        self.assertIn('上段', rows[1]['location'])
        self.assertIn('下段', rows[2]['location'])
        self.assertIn('機械的', '\n'.join(bundle['notes']))
        self.assertIn('LPF', bundle['scope_note'])

    def test_m68000_ea_operand_size_and_multiply_footnote(self):
        bundle=json.loads((Path(__file__).resolve().parents[1]/'tables/nxp-m68000-um-p0118.json').read_text())
        values={(r['addressing_mode'],r['operand_size']):r['clock_periods'] for r in bundle['tables'][0]['rows']}
        self.assertEqual(values[('Dn','Byte/Word')],0)
        self.assertEqual(values[('(An)','Byte/Word')],4)
        self.assertEqual(values[('(An)','Long')],8)
        self.assertIn('MC68010',bundle['scope_note'])
        self.assertIn('MULU.W', '\n'.join(bundle['notes']))

    def test_mulu_maximum_is_not_a_fixed_time_and_derived_examples_follow_popcount(self):
        bundle=json.loads((Path(__file__).resolve().parents[1]/'tables/nxp-m68000-um-p0120.json').read_text())
        formula,examples=bundle['tables']
        self.assertEqual(formula['rows'][0]['base_clock_formula'],'38 + 2*n')
        self.assertEqual(formula['rows'][0]['maximum_base_clocks'],70)
        for row in examples['rows']:
            bits=int(row['source_word'][1:],16).bit_count()
            self.assertEqual(row['popcount16'],bits)
            self.assertEqual(row['base_clock_periods'],38+2*bits)
        values={r['source_word']:r['base_clock_periods'] for r in examples['rows']}
        self.assertEqual(values['$0000'],38)
        self.assertEqual(values['$FFFF'],70)
        self.assertEqual(values['$5555'],54)

    def test_crtc_register_addresses_and_synchronization_ranges(self):
        root = Path(__file__).resolve().parents[1] / "tables"
        bundle = json.loads((root / "inside-x68000-p0237.json").read_text())
        crtc, video = bundle["tables"][0]["rows"]
        self.assertEqual(crtc["address"], "$E80028")
        self.assertEqual(crtc["bits"], ["8", "9", "10"])
        self.assertEqual(video["address"], "$E82400")
        self.assertEqual(video["bits"], ["0", "1", "2"])
        self.assertIn("未解決", " ".join(bundle["notes"]))

    def test_video_r0_codes_keep_binary_literals_and_undefined_case(self):
        root = Path(__file__).resolve().parents[1] / "tables"
        rows = json.loads((root / "inside-x68000-p0238.json").read_text())["tables"][0]["rows"]
        col = {r["binary_code"]: r["meaning"] for r in rows if r["field"] == "COL"}
        self.assertEqual(col, {"00": "16色モード", "01": "256色モード", "10": "未定義", "11": "65536色モード"})

    def test_dmac_channel2_addresses_and_gcr_channel_exception(self):
        root = Path(__file__).resolve().parents[1] / "tables"
        tables = json.loads((root / "inside-x68000-p0033.json").read_text())["tables"]
        regs = {r["register"]: r for r in tables[1]["rows"]}
        self.assertIn("チャンネル2=$E8408A", regs["MTC"]["addresses"])
        self.assertIn("チャンネル2=$E8408C", regs["MAR"]["addresses"])
        self.assertIn("チャンネル2=$E84094", regs["DAR"]["addresses"])
        self.assertEqual(regs["GCR"]["addresses"], ["チャンネル3=$E840FF"])
        self.assertEqual(regs["CCR"]["offset"], "$07")
        self.assertEqual(len(regs["CCR"]["addresses"]), 4)

    def test_dmac_odd_byte_offsets_and_mapped_word_spans(self):
        root = Path(__file__).resolve().parents[1] / "tables"
        tables = json.loads((root / "inside-x68000-p0033.json").read_text())["tables"]
        regs = {r["register"]: r for r in tables[1]["rows"]}
        for name in ["CER", "OCR", "CCR", "NIV", "EIV", "MFC", "CPR", "DFC", "BFC", "GCR"]:
            self.assertEqual(int(regs[name]["offset"][1:], 16) % 2, 1)
        self.assertEqual(regs["MAR"]["allocated_bytes"], 4)
        self.assertEqual(regs["MTC"]["allocated_bytes"], 2)
