"""Refresh derived FTS context from edition-bound source navigation metadata."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .corpus import indexed_text


def refresh_navigation_index(db: Path, sql_output: Path):
    def quote(value):
        return "'" + value.replace("'", "''") + "'"

    with closing(sqlite3.connect(db)) as conn:
        rows = conn.execute('SELECT c.id,c.metadata,c.search_text,s.metadata FROM chunks c JOIN sources s ON s.id=c.source_id').fetchall()
        updates, sources = [], {}
        for chunk_id, raw, previous, raw_source in rows:
            chunk, source = json.loads(raw), json.loads(raw_source)
            text = indexed_text(chunk, source)
            if text == previous:
                continue
            sources[source['id']] = source['sha256']
            identifier = quote(chunk_id)
            updates.extend([
                f'UPDATE chunks SET search_text={quote(text)} WHERE id={identifier};',
                f'DELETE FROM chunk_fts WHERE rowid IN (SELECT rowid FROM chunks WHERE id={identifier});',
                f'INSERT INTO chunk_fts(rowid,search_text) SELECT rowid,search_text FROM chunks WHERE id={identifier};',
            ])
        if updates:
            guards = [f"EXISTS(SELECT 1 FROM sources WHERE id={quote(source_id)} AND json_extract(metadata,'$.sha256')={quote(sha)})"
                      for source_id, sha in sorted(sources.items())]
            guard = "SELECT json(CASE WHEN " + ' AND '.join(guards) + " THEN 'true' ELSE 'navigation_source_mismatch' END);"
            patch = '\n'.join([guard, *updates]) + '\n'
            conn.executescript('BEGIN;\n' + patch + 'COMMIT;\n')
        else:
            patch = '-- Navigation search index is already current.\n'
    sql_output.parent.mkdir(parents=True, exist_ok=True)
    sql_output.write_text(patch)
    return {'updated_chunks': len(updates)//3, 'sources': sorted(sources), 'sql_output': str(sql_output)}
