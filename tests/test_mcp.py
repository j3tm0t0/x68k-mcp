"""Real stdio client/server handshake and tool calls (no network)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from x68k_knowledge.corpus import build_index
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_tools(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        corpus = root / "test-manual"
        corpus.mkdir()
        text = "Synthetic test register $E8001B; not extracted book text."
        source = dict(id="test-manual", title="Synthetic manual", sha256="synthetic", path="test.pdf")
        page = dict(source_id=source["id"], pdf_page=1, printed_page=None, text=text)
        chunk = dict(page, id="test-chunk", start_char=0, end_char=len(text))
        (corpus / "manifest.json").write_text(json.dumps(dict(source=source)))
        (corpus / "pages.jsonl").write_text(json.dumps(page) + "\n")
        (corpus / "chunks.jsonl").write_text(json.dumps(chunk) + "\n")
        db = root / "knowledge.sqlite3"
        build_index([corpus], db)
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "x68k_knowledge.cli", "serve", "--db", str(db)],
            env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual({t.name for t in tools.tools}, {"list_sources", "search_knowledge", "get_page"})
                sources = await session.call_tool("list_sources", {})
                self.assertFalse(sources.isError)
                result = await session.call_tool("search_knowledge", {"query": "$E8001B", "limit": 1})
                self.assertFalse(result.isError)
                data = result.structuredContent
                # FastMCP wraps non-object structured results under `result`.
                hits = data["result"] if data else json.loads(result.content[0].text)
                self.assertEqual(hits[0]["pdf_page"], 1)
                page = await session.call_tool("get_page", {"source_id": "test-manual", "pdf_page": 1})
                self.assertFalse(page.isError)
                page_data = page.structuredContent or json.loads(page.content[0].text)
                self.assertIn("E8001B", page_data["text"])
                invalid = await session.call_tool("search_knowledge", {"query": "DMA", "limit": 100})
                self.assertTrue(invalid.isError)
