"""Read-only reference tools behind Amazon Bedrock AgentCore Gateway."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from x68k_knowledge.corpus import Knowledge

DB = Path(os.environ.get('KNOWLEDGE_DB', str(Path(__file__).with_name('knowledge.sqlite3'))))
ALLOWED = {'list_sources', 'search_knowledge', 'get_page'}


def _error(message):
    return {'error': {'code': 'invalid_arguments', 'message': message}}


def handler(event, context):
    custom = getattr(getattr(context, 'client_context', None), 'custom', None) or {}
    qualified = custom.get('bedrockAgentCoreToolName', '')
    if not qualified and event == {'__health': True}:
        with closing(sqlite3.connect(':memory:')) as probe:
            probe.execute("CREATE VIRTUAL TABLE probe USING fts5(text,tokenize='trigram')")
        with Knowledge(DB).connect() as conn:
            return {'sqlite_version': sqlite3.sqlite_version, 'fts5_trigram': True,
                    'sources': conn.execute('SELECT count(*) FROM sources').fetchone()[0],
                    'chunks': conn.execute('SELECT count(*) FROM chunks').fetchone()[0]}
    tool = qualified.removeprefix('knowledge___')
    if qualified != 'knowledge___' + tool or tool not in ALLOWED:
        return _error('Unknown tool')
    if not isinstance(event, dict):
        return _error('Arguments must be an object')
    knowledge = Knowledge(DB)
    try:
        if tool == 'list_sources':
            if event:
                return _error('list_sources takes no arguments')
            return knowledge.sources()
        if tool == 'search_knowledge':
            if set(event) - {'query', 'limit', 'source_id'}:
                return _error('Unexpected search arguments')
            query, limit, source = event.get('query'), event.get('limit', 5), event.get('source_id')
            if not isinstance(query, str) or type(limit) is not int or not 1 <= limit <= 20:
                return _error('query must be a string; limit must be an integer from 1 to 20')
            if source is not None and not isinstance(source, str):
                return _error('source_id must be a string')
            return knowledge.search(query, limit, source)
        if set(event) != {'source_id', 'pdf_page'}:
            return _error('get_page requires source_id and pdf_page')
        if not isinstance(event['source_id'], str) or type(event['pdf_page']) is not int or event['pdf_page'] < 1:
            return _error('source_id must be a string; pdf_page must be a positive integer')
        return knowledge.page(event['source_id'], event['pdf_page'])
    except ValueError as error:
        # Knowledge only emits controlled validation messages, not SQL text.
        return _error(str(error))
    except sqlite3.Error:
        return {'error': {'code': 'backend_unavailable', 'message': 'Reference index is unavailable'}}
