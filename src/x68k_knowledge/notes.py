"""Ingest curated web notes without inventing PDF pagination."""
import hashlib
import json
import re
from pathlib import Path

from .corpus import chunk_spans, write_json


def ingest_notes(path: Path, output: Path, source: dict):
    source = dict(source)
    if source.get("kind") != "web-notes" or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", source["id"]):
        raise ValueError("web-notes kind and a lowercase source slug required")
    if not source.get("url", "").startswith(("https://", "http://")):
        raise ValueError("web notes require an upstream HTTP(S) source URL")
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    if not text.strip():
        raise ValueError("Notes must not be empty")
    digest = hashlib.sha256(raw).hexdigest()
    source.update(sha256=digest, path=path.as_posix(), extraction="curated source notes; not verbatim HTML")
    chunks = []
    for index, (start, end) in enumerate(chunk_spans(text)):
        chunks.append(dict(id=f"{source['id']}:{digest[:12]}:c{index:04d}",
                           source_id=source["id"], pdf_page=None, printed_page=None,
                           location_type="web-notes", start_char=start, end_char=end,
                           text=text[start:end], quality_flags=[]))
    output.mkdir(parents=True, exist_ok=True)
    (output / "notes.md").write_text(text, encoding="utf-8")
    (output / "pages.jsonl").write_text("", encoding="utf-8")
    (output / "chunks.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks), encoding="utf-8")
    manifest = dict(schema_version=1, source=source, page_count=0, chunk_count=len(chunks),
                    character_count=len(text), chunking=dict(size=1400, overlap=200, unit="unicode_characters"),
                    quality=dict(status=source.get("review_status", "curated_notes"), flagged_pages=[]))
    write_json(output / "manifest.json", manifest)
    return manifest
