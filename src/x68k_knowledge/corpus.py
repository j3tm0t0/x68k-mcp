"""Portable corpus: immutable page text, derived chunks, rebuildable SQLite."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import tempfile
import unicodedata
from contextlib import closing
from pathlib import Path


def normalize(text: str) -> str:
    """Compact OCR whitespace only in the search representation."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def chunk_spans(text: str, size: int = 1400, overlap: int = 200):
    if size < 100 or not 0 <= overlap < size:
        raise ValueError("size >= 100 and 0 <= overlap < size required")
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            newline = text.rfind("\n", start + size // 2, end)
            if newline >= 0 and newline + 1 - overlap > start:
                end = newline + 1
        if text[start:end].strip():
            yield start, end
        if end == len(text):
            break
        start = end - overlap


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def ingest(pdf: Path, output: Path, source: dict, size=1400, overlap=200):
    source = dict(source)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", source["id"]):
        raise ValueError("source id must be a lowercase slug")
    if source["kind"] not in {"book", "manual"}:
        raise ValueError("PDF ingestion supports kind=book or manual")
    # Validate before extraction, even for empty input.
    list(chunk_spans("", size, overlap))
    with tempfile.TemporaryDirectory() as temp:
        text_file = Path(temp) / "layout.txt"
        subprocess.run(
            ["pdftotext", "-enc", "UTF-8", "-layout", str(pdf), str(text_file)],
            check=True,
        )
        full_text = text_file.read_text(encoding="utf-8")
    texts = full_text.split("\f")
    if texts[-1] == "":
        texts.pop()
    if not texts or not any(t.strip() for t in texts):
        raise ValueError("No text layer found; OCR is required before ingestion")
    with pdf.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    source["sha256"] = digest
    source["path"] = pdf.as_posix()
    source["extraction"] = "pdftotext -enc UTF-8 -layout"
    source["extraction_version"] = subprocess.run(
        ["pdftotext", "-v"], capture_output=True, text=True, check=True
    ).stderr.splitlines()[0]
    pages, chunks = [], []
    offset = source.get("printed_page_offset")
    for number, text in enumerate(texts, 1):
        # A candidate label, never an authoritative inferred printed page number.
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        footer = lines[-1] if lines and re.fullmatch(r"\d{1,4}", lines[-1]) else None
        flags = []
        if len(text.strip()) < 40:
            flags.append("sparse_text")
        if "\ufffd" in text:
            flags.append("replacement_character")
        printed = number - offset if offset is not None and 1 <= number - offset <= source.get("printed_page_end", 99999) else None
        if printed is not None and footer != str(printed):
            flags.append("printed_page_unconfirmed")
        page = dict(source_id=source["id"], pdf_page=number, printed_page=printed,
                    printed_page_basis="configured_offset" if printed is not None else None,
                    footer_candidate=footer, text=text, quality_flags=flags)
        pages.append(page)
        for index, (start, end) in enumerate(chunk_spans(text, size, overlap)):
            chunks.append(dict(
                id=f"{source['id']}:{digest[:12]}:p{number:04d}:c{index:03d}",
                source_id=source["id"], pdf_page=number, printed_page=printed,
                start_char=start, end_char=end, text=text[start:end],
                quality_flags=flags,
            ))
    output.mkdir(parents=True, exist_ok=True)
    for name, records in [("pages.jsonl", pages), ("chunks.jsonl", chunks)]:
        (output / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    (output / "book.md").write_text(
        f"# {source['title']}\n\n抽出テキスト未校正。図表・コード・数値は原本照合が必要。\n\n" + "\n".join(
            f"## PDF page {p['pdf_page']}\n\n```text\n{p['text']}\n```\n" for p in pages
        )
    )
    manifest = dict(schema_version=1, source=source, page_count=len(pages),
                    chunk_count=len(chunks), character_count=sum(map(len, texts)),
                    chunking=dict(size=size, overlap=overlap, unit="unicode_characters"),
                    quality=dict(status=source.get("review_status", "unreviewed_extracted_text"), flagged_pages=[
                        dict(pdf_page=p["pdf_page"], flags=p["quality_flags"])
                        for p in pages if p["quality_flags"]
                    ]))
    write_json(output / "manifest.json", manifest)
    return manifest


def records(path):
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def navigation_context(source, pdf_page):
    """Page-scoped catalog topics are derived search context, never book quotes."""
    return [entry['topic'] + (' ' + ' '.join(entry.get('keywords', [])) if entry.get('keywords') else '')
            for entry in source.get('content_guide', []) if pdf_page in entry.get('pdf_pages', [])]


def indexed_text(chunk, source):
    return normalize('\n'.join([*navigation_context(source, chunk.get('pdf_page')), chunk['text']]))


def build_index(corpora: list[Path], db: Path):
    """Build a fresh snapshot then atomically replace the previous database."""
    db.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=db.parent) as temp:
        staging = Path(temp) / "knowledge.sqlite3"
        with closing(sqlite3.connect(staging)) as conn:
            conn.executescript('''
                CREATE TABLE sources(id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
                CREATE TABLE pages(source_id TEXT, pdf_page INTEGER, metadata TEXT NOT NULL,
                    PRIMARY KEY(source_id, pdf_page));
                CREATE TABLE chunks(id TEXT PRIMARY KEY, source_id TEXT, pdf_page INTEGER,
                    metadata TEXT NOT NULL, search_text TEXT NOT NULL);
                CREATE VIRTUAL TABLE chunk_fts USING fts5(search_text, tokenize='trigram');
            ''')
            for corpus in corpora:
                manifest = json.loads((corpus / "manifest.json").read_text())
                source = manifest["source"]
                conn.execute("INSERT INTO sources VALUES (?,?)", (source["id"], json.dumps(source, ensure_ascii=False)))
                from .tables import merge_corpus_tables
                pages, chunks = merge_corpus_tables(corpus, source,
                    list(records(corpus / "pages.jsonl")), list(records(corpus / "chunks.jsonl")))
                for page in pages:
                    conn.execute("INSERT INTO pages VALUES (?,?,?)", (source["id"], page["pdf_page"], json.dumps(page, ensure_ascii=False)))
                for chunk in chunks:
                    text = indexed_text(chunk, source)
                    cur = conn.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (chunk["id"], source["id"], chunk["pdf_page"], json.dumps(chunk, ensure_ascii=False), text))
                    conn.execute("INSERT INTO chunk_fts(rowid,search_text) VALUES (?,?)", (cur.lastrowid, text))
            conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('optimize')")
            conn.commit()
        staging.replace(db)


class Knowledge:
    def __init__(self, db: Path):
        self.db = db.resolve()

    def connect(self):
        conn = sqlite3.connect(self.db.as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    def sources(self):
        with self.connect() as conn:
            return [json.loads(r[0]) for r in conn.execute("SELECT metadata FROM sources ORDER BY id")]

    def page(self, source_id: str, pdf_page: int):
        with self.connect() as conn:
            row = conn.execute("SELECT p.metadata,s.metadata AS source FROM pages p JOIN sources s ON s.id=p.source_id WHERE p.source_id=? AND p.pdf_page=?", (source_id, pdf_page)).fetchone()
            if row is None:
                raise ValueError("Unknown source/page")
            page = json.loads(row[0])
            context = navigation_context(json.loads(row['source']), pdf_page)
            if context:
                page['navigation_context'] = context
                page['navigation_context_note'] = 'Catalog topic labels for this page; not quotations from the source. Read the actual text for specifications.'
            return page

    def search(self, query: str, limit: int = 5, source_id: str | None = None):
        if not 1 <= limit <= 20 or len(query) > 500:
            raise ValueError("limit must be 1..20 and query at most 500 characters")
        terms = [normalize(t) for t in query.split() if normalize(t)]
        if not terms or len(terms) > 16:
            raise ValueError("query must contain 1..16 whitespace-separated keywords")
        long_terms = [t for t in terms if len(t) >= 3]
        conditions, params = [], []
        join = ""
        ranking = "c.rowid"
        if long_terms:
            join = "JOIN chunk_fts ON chunk_fts.rowid=c.rowid"
            conditions.append("chunk_fts MATCH ?")
            params.append(" AND ".join('"' + t.replace('"', '""') + '"' for t in long_terms))
            ranking = "bm25(chunk_fts), c.rowid"
        # Short terms (FM, BG, etc.) need a literal substring fallback.
        for term in terms:
            if len(term) < 3:
                conditions.append("instr(c.search_text,?)>0")
                params.append(term)
        if source_id:
            conditions.append("c.source_id=?")
            params.append(source_id)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(f"SELECT c.metadata, s.metadata AS source, "
                "json_extract(p.metadata,'$.structured_tables') AS page_tables, "
                "json_extract(p.metadata,'$.structured_table_text') AS page_table_text, "
                "json_extract(p.metadata,'$.table_provenance') AS page_provenance "
                f"FROM chunks c {join} JOIN sources s ON s.id=c.source_id "
                "LEFT JOIN pages p ON p.source_id=c.source_id AND p.pdf_page=c.pdf_page "
                f"WHERE {' AND '.join(conditions)} ORDER BY CASE WHEN json_extract(c.metadata,'$.record_type')='structured-table' THEN 0 ELSE 1 END, {ranking} LIMIT ?", params).fetchall()
        results = []
        structured_matches = {}
        for row in rows:
            chunk = json.loads(row['metadata'])
            if chunk.get('record_type') == 'structured-table':
                key = (chunk['source_id'], chunk['pdf_page'])
                structured_matches.setdefault(key, []).extend(t['id'] for t in chunk['structured_tables'])
        included = set()
        for row in rows:
            chunk, source = json.loads(row["metadata"]), json.loads(row["source"])
            context = navigation_context(source, chunk.get('pdf_page'))
            if context:
                chunk['navigation_context'] = context
                chunk['navigation_context_note'] = 'Catalog topic labels for this page; not quotations from the source. Read the actual text for specifications.'
            key = (chunk['source_id'], chunk['pdf_page'])
            if key in structured_matches:
                if chunk.get('record_type') != 'structured-table' or key in included:
                    continue
                included.add(key)
                chunk['text'] = row['page_table_text'] or chunk['text']
            if row['page_tables']:
                chunk['matched_table_ids'] = structured_matches.get(key, [])
                chunk['structured_tables'] = json.loads(row['page_tables'])
                chunk['table_provenance'] = json.loads(row['page_provenance'])
                chunk['table_context_scope'] = 'all_annotated_tables_on_same_page'
                chunk['evidence_note'] = (
                    'For the annotated scope, use structured_tables rather than OCR text alignment. '
                    'All annotated tables from this page are included, even if only one matched. '
                    'Preserve list-valued cells and relationships; do not pair independent rows by position. '
                    'Keep display/scan conditions separate from VRAM/color/page configurations. '
                    'The OCR text remains unreviewed; annotations cover only table_provenance.scope_note.')
            chunk.update(title=source["title"], source_sha256=source["sha256"],
                         source_uri=source["url"] if source.get("kind") == "web-notes" else source["path"] + f"#page={chunk['pdf_page']}",
                         source_url=source.get("url"),
                         source_kind=source.get("kind"),
                         cpu_scope_note=source.get("cpu_scope_note"),
                         scope_note=source.get("scope_note") or source.get("cpu_scope_note"),
                         part_numbers=source.get("part_numbers", []),
                         related_issues=source.get("related_issues", []),
                         notice=source.get("notice", "未校正の抽出テキスト。数値・コード・図表は原本で確認してください。"))
            results.append(chunk)
        return results
