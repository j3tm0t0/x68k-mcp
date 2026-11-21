"""Logical SQLite export. Never dump SQLite's FTS internal/shadow tables."""
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from .corpus import Knowledge


def export_sqlite(db: Path, output: Path):
    if db.resolve() == output.resolve():
        raise ValueError("SQL output must not overwrite the input database")
    output.parent.mkdir(parents=True, exist_ok=True)
    tables = ("sources", "pages", "chunks", "chunk_fts")
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        staging = Path(temp) / "export.sql"
        with Knowledge(db).connect() as conn, staging.open("w", encoding="utf-8") as stream:
            stream.write("-- Local reference corpus: includes source text. Not a public dataset.\n")
            for table in reversed(tables):
                stream.write(f"DROP TABLE IF EXISTS {table};\n")
            for table in tables:
                schema = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()
                if not schema:
                    raise ValueError(f"Missing table: {table}")
                stream.write(schema[0] + ";\n")
            for table in tables[:-1]:
                columns = ",".join(["rowid"] + [r[1] for r in conn.execute(f"PRAGMA table_info({table})")])
                for row in conn.execute(f"SELECT rowid,* FROM {table} ORDER BY rowid"):
                    values = ",".join(conn.execute("SELECT quote(?)", (value,)).fetchone()[0] for value in row)
                    stream.write(f"INSERT INTO {table} ({columns}) VALUES ({values});\n")
            stream.write("INSERT INTO chunk_fts(rowid,search_text) SELECT rowid,search_text FROM chunks;\n")
            stream.write("INSERT INTO chunk_fts(chunk_fts) VALUES ('optimize');\n")
        # Reparse the complete export before replacing a previous one.
        with closing(sqlite3.connect(":memory:")) as check:
            check.executescript(staging.read_text(encoding="utf-8"))
        staging.replace(output)
    return {"output": str(output), "bytes": output.stat().st_size, "purpose": "local-reference"}
