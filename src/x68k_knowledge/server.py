"""Local, stdio-only MCP interface. Raw retrieval is for the local user."""
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .corpus import Knowledge


def create_server(db: Path):
    knowledge = Knowledge(db)
    server = FastMCP("x68k-knowledge", instructions=(
        "X68000 development reference retrieval. Search with short keywords, not long questions. "
        "Space-separated terms are ANDed; try variants for OCR mistakes (OPM/0PM). "
        "Use source topics/content_guide to choose the manual and CPU section. Start with one distinctive keyword and limit 5; if empty, remove terms or change the source, not add guessed numbers. Read located sections with get_page. "
        "For CPU timing tables, check each page's navigation_context and CPU section; include the requested CPU in the query when needed. Same numeric entries from another CPU do not establish target-CPU timing. "
        "For calculations, distinguish user-given assumptions, retrieved definitions and derived results. Do not claim the source explicitly states a user assumption or inference. Name the source figure type without implying complete schematic or board inspection. "
        "Results include unreviewed OCR and optional image-checked structured_tables. Cite title and PDF page. Respect table_provenance.review_status: AI image checks are not human review. Prefer explicit structured cell relationships to OCR alignment. "
        "Tools return extracted text, not images. Do not claim visual verification of raw OCR. "
        "Search hits include all annotated tables on the same page. Preserve lists and conditions; never pair independent table rows by position. Keep display/scan conditions separate from VRAM/color/page configurations. "
        "For supported-mode lists, explicitly identify hardware capability and OS/library support for the listed modes, including false flags and exceptions. Do not collapse them into an ambiguous supported label or defer material restrictions to a follow-up. "
        "Observe scope_note and part_numbers for peripheral variants. related_issues links development issues. "
        "Web notes have null pdf_page; cite their source URL and distinguish notes from upstream text. "
        "Use get_page for adjacent context; verify register addresses, bits and code against the PDF. "
        "Answer technical facts in your own words; distinguish source statements from inferences."
    ))

    @server.tool()
    def list_sources() -> list[dict]:
        """List corpus sources, provenance, CPU scope and optional content_guide section/page navigation."""
        return knowledge.sources()

    @server.tool()
    def search_knowledge(query: str, limit: int = 5, source_id: str | None = None) -> list[dict]:
        """Search text and page-scoped catalog topics; spaces mean AND. limit 1..20.

        Start with ONE distinctive term and limit 5. Do not AND synonyms or
        guessed constants; on no hits, remove terms or change the manual.
        Read located pages with get_page.

        structured_tables includes ALL annotated tables on the matched page.
        Within their annotated scope, use explicit rows and list-valued cells over
        OCR alignment. Never pair independent table rows by position; display/scan
        conditions and VRAM/color/page configurations are separate dimensions.
        For supported configurations, report hardware capability and OS/library
        support separately, preserving false flags and identifying the affected
        modes. Include material restrictions in this answer.
        """
        return knowledge.search(query, limit, source_id)

    @server.tool()
    def get_page(source_id: str, pdf_page: int) -> dict:
        """Read one original OCR page locally. pdf_page is 1-based, not printed pagination."""
        return knowledge.page(source_id, pdf_page)

    return server


def serve(db: Path):
    create_server(db).run(transport="stdio")
