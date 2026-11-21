"""Page-image table annotations. Original OCR stays immutable and edition-bound."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from .corpus import indexed_text, records, write_json


def materialize(bundle: dict, source: dict, pages: dict[int, dict]):
    if bundle.get("schema_version") != 1 or bundle.get("source_id") != source["id"]:
        raise ValueError("Table schema/source mismatch")
    if bundle.get("source_sha256") != source["sha256"]:
        raise ValueError("Table source SHA256 mismatch: check the PDF edition")
    number = bundle.get("pdf_page")
    if type(number) is not int or number < 1 or number not in pages:
        raise ValueError("Table requires an existing 1-based PDF page")
    for field in ("origin_label", "review_status", "review_method", "scope_note"):
        if not isinstance(bundle.get(field), str) or not bundle[field].strip():
            raise ValueError(f"Missing table provenance: {field}")
    tables = bundle.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ValueError("At least one structured table required")
    notes = bundle.get("notes", [])
    if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
        raise ValueError("Table notes must be strings")
    page = dict(pages[number])
    provenance = {k: bundle[k] for k in (
        "source_sha256", "pdf_page", "origin_label", "review_status", "review_method", "scope_note")}
    heading = (f"出典: {source['title']} PDF {number}, {bundle['origin_label']}\n"
               f"構造化情報の状態: {bundle['review_status']}\n{bundle['review_method']}\n{bundle['scope_note']}\n")
    ids, chunks, texts = set(), [], []
    for table in tables:
        table_id = table.get("id", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", table_id) or table_id in ids:
            raise ValueError("Structured table IDs must be unique lowercase slugs")
        ids.add(table_id)
        if not isinstance(table.get("title"), str) or not table["title"].strip():
            raise ValueError("Structured table needs a title")
        columns, rows = table.get("columns"), table.get("rows")
        if not isinstance(columns, list) or not columns or not isinstance(rows, list) or not rows:
            raise ValueError("Table needs columns and rows")
        keys = [c.get("key") for c in columns]
        if any(not isinstance(k, str) or not k for k in keys) or len(set(keys)) != len(keys):
            raise ValueError("Column keys must be nonempty and unique")
        if any(not isinstance(c.get("label"), str) or not c["label"] for c in columns):
            raise ValueError("Column labels required")
        lines = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(keys):
                raise ValueError("Row cells must match the column keys")
            cells = []
            for column in columns:
                value = row[column["key"]]
                if not (value is None or type(value) in (str, bool, int) or
                        isinstance(value, list) and all(isinstance(v, str) for v in value)):
                    raise ValueError("Cells must be strings, integers, booleans, null or string arrays")
                label = "未記載・該当なし" if value is None else "対応あり" if value is True else "対応なし" if value is False else " / ".join(value) if isinstance(value, list) else str(value)
                if type(value) is int and column.get("unit"):
                    label += column["unit"]
                cells.append(f"{column['label']}={label}")
            lines.append("; ".join(cells))
        text = heading + table["title"] + "\n" + "\n".join(lines) + "\n" + "\n".join(notes)
        texts.append(text)
        chunks.append(dict(id=f"{source['id']}:{source['sha256'][:12]}:p{number:04d}:table:{table_id}",
                           source_id=source["id"], pdf_page=number, printed_page=page.get("printed_page"),
                           start_char=None, end_char=None, record_type="structured-table", text=text,
                           structured_tables=[table], table_provenance=provenance,
                           quality_flags=["structured_from_page_image", "not_human_reviewed"]))
    page.update(structured_tables=tables, structured_table_text="\n\n".join(texts), table_provenance=provenance)
    return page, chunks


def merge_corpus_tables(corpus: Path, source: dict, pages: list[dict], chunks: list[dict]):
    by_page = {page["pdf_page"]: page for page in pages}
    for path in sorted((corpus / "structured_tables").glob("*.json")):
        page, additions = materialize(json.loads(path.read_text()), source, by_page)
        by_page[page["pdf_page"]] = page
        chunks.extend(additions)
    return list(by_page.values()), chunks


def attach_tables(path: Path, corpus: Path, db: Path, sql_output: Path):
    source = json.loads((corpus / "manifest.json").read_text())["source"]
    bundle = json.loads(path.read_text())
    pages = {page["pdf_page"]: page for page in records(corpus / "pages.jsonl")}
    page, chunks = materialize(bundle, source, pages)
    number = page["pdf_page"]

    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    source_id, sha = quote(source["id"]), quote(source["sha256"])
    where = f"source_id={source_id} AND pdf_page={number}"
    selected = f"{where} AND json_extract(metadata,'$.record_type')='structured-table'"
    # Fail before mutations if the remote/local database has a different edition.
    sql = [f"SELECT json(CASE WHEN EXISTS(SELECT 1 FROM sources WHERE id={source_id} AND json_extract(metadata,'$.sha256')={sha}) AND EXISTS(SELECT 1 FROM pages WHERE {where}) THEN 'true' ELSE 'table_source_mismatch' END);",
           f"DELETE FROM chunk_fts WHERE rowid IN (SELECT rowid FROM chunks WHERE {selected});",
           f"DELETE FROM chunks WHERE {selected};"]
    for chunk in chunks:
        metadata = quote(json.dumps(chunk, ensure_ascii=False))
        sql.append(f"INSERT INTO chunks(id,source_id,pdf_page,metadata,search_text) VALUES ({quote(chunk['id'])},{source_id},{number},{metadata},{quote(indexed_text(chunk, source))});")
        sql.append("INSERT INTO chunk_fts(rowid,search_text) SELECT rowid,search_text FROM chunks WHERE id=" + quote(chunk["id"]) + ";")
    updates = []
    for key in ("structured_tables", "table_provenance"):
        updates.extend([quote("$." + key), "json(" + quote(json.dumps(page[key], ensure_ascii=False)) + ")"])
    updates.extend([quote("$.structured_table_text"), quote(page["structured_table_text"])])
    sql.append(f"UPDATE pages SET metadata=json_set(metadata,{','.join(updates)}) WHERE {where};")
    patch = "\n".join(sql) + "\n"
    with closing(sqlite3.connect(db)) as conn:
        conn.executescript("BEGIN;\n" + patch + "COMMIT;\n")
    destination = corpus / "structured_tables" / f"p{number:04d}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_json(destination, bundle)
    sql_output.parent.mkdir(parents=True, exist_ok=True)
    sql_output.write_text(patch)
    return dict(source_id=source["id"], pdf_page=number, structured_tables=len(chunks),
                sql_output=str(sql_output), review_status=bundle["review_status"])
