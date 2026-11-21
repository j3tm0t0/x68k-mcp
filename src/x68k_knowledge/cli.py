import argparse
import json
from pathlib import Path

from .corpus import Knowledge, build_index, ingest


def main():
    parser = argparse.ArgumentParser(description="X68000 local knowledge corpus")
    sub = parser.add_subparsers(dest="command", required=True)
    convert = sub.add_parser("ingest")
    convert.add_argument("pdf", type=Path)
    convert.add_argument("--source", required=True, type=Path)
    convert.add_argument("--output", required=True, type=Path)
    notes = sub.add_parser("ingest-notes", help="Ingest curated web notes with source URL")
    notes.add_argument("notes", type=Path)
    notes.add_argument("--source", required=True, type=Path)
    notes.add_argument("--output", required=True, type=Path)
    tables = sub.add_parser("ingest-tables", help="Attach edition-bound structured tables checked against page images")
    tables.add_argument("tables", type=Path)
    tables.add_argument("--corpus", required=True, type=Path)
    tables.add_argument("--db", type=Path, default=Path("data/knowledge.sqlite3"))
    tables.add_argument("--sql-output", type=Path, default=Path("tmp/structured-tables.sql"))
    index = sub.add_parser("index")
    index.add_argument("corpora", type=Path, nargs="+")
    index.add_argument("--db", type=Path, default=Path("data/knowledge.sqlite3"))
    navigation = sub.add_parser('refresh-navigation-index', help='Index page-scoped source guide topics without changing original text')
    navigation.add_argument('--db', type=Path, default=Path('data/knowledge.sqlite3'))
    navigation.add_argument('--sql-output', type=Path, default=Path('tmp/navigation-index.sql'))
    export = sub.add_parser("export-sqlite", help="Export the local corpus as SQLite SQL")
    export.add_argument("--db", type=Path, default=Path("data/knowledge.sqlite3"))
    export.add_argument("--output", type=Path, default=Path("data/knowledge.sql"))
    for command in ["search", "page", "serve"]:
        p = sub.add_parser(command)
        p.add_argument("--db", type=Path, default=Path("data/knowledge.sqlite3"))
        if command == "search":
            p.add_argument("query")
            p.add_argument("--limit", type=int, default=5)
            p.add_argument("--source-id")
        elif command == "page":
            p.add_argument("source_id")
            p.add_argument("pdf_page", type=int)
    args = parser.parse_args()
    if args.command == "ingest":
        result = ingest(args.pdf, args.output, json.loads(args.source.read_text()))
        result = {k: v for k, v in result.items() if k != "quality"}
    elif args.command == "ingest-notes":
        from .notes import ingest_notes
        result = ingest_notes(args.notes, args.output, json.loads(args.source.read_text()))
    elif args.command == "ingest-tables":
        from .tables import attach_tables
        result = attach_tables(args.tables, args.corpus, args.db, args.sql_output)
    elif args.command == "index":
        build_index(args.corpora, args.db)
        result = {"db": str(args.db), "sources": Knowledge(args.db).sources()}
    elif args.command == 'refresh-navigation-index':
        from .navigation import refresh_navigation_index
        result = refresh_navigation_index(args.db, args.sql_output)
    elif args.command == "export-sqlite":
        from .sqlite_export import export_sqlite
        result = export_sqlite(args.db, args.output)
    elif args.command == "search":
        result = Knowledge(args.db).search(args.query, args.limit, args.source_id)
    elif args.command == "page":
        result = Knowledge(args.db).page(args.source_id, args.pdf_page)
    else:
        from .server import serve
        serve(args.db)
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
