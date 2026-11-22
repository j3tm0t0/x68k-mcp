# x68k-mcp

English | [日本語](README.ja.md)

An MCP server for researching X68000 development and emulator implementation, with citations to the source manuals.

Search **Inside X68000**, M68000-family CPU/FPU manuals, and peripheral datasheets. Find the pages and tables behind display modes, instruction timings, register values, and audio hardware behavior.

**Public MCP endpoint: [`https://x68k-mcp.j3tm0t0.dev/mcp`](https://x68k-mcp.j3tm0t0.dev/mcp)**

Connect with any MCP client that supports Streamable HTTP. No account or API key is required to access this server. Your MCP client's AI generates the answers, so its own terms and usage charges still apply.

## Quick start

### Claude Code

```sh
claude mcp add --transport http --scope user x68k-mcp \
  https://x68k-mcp.j3tm0t0.dev/mcp
```

Use `/mcp` in Claude Code to check the connection. `--scope user` makes the server available across your projects. See the [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp) for configuration details.

### Other MCP clients

| Setting | Value |
| --- | --- |
| Name | `x68k-mcp` |
| URL | `https://x68k-mcp.j3tm0t0.dev/mcp` |
| Transport | Streamable HTTP |
| Authentication | None |

Add these settings in your client's MCP configuration. The endpoint is an API for MCP clients, rather than a browser search page.

## Example questions

Ask your connected AI:

- “List the X68000 graphics display modes, separating resolution, color depth, page count, and IOCS support.”
- “What are the minimum cycle counts for `MULU.W D0,D1` and `MULU.W (A0),D1` on the MC68000? Include effective-address calculation time.”
- “What is the OPM timer B period with register value `$80`, assuming a 4 MHz clock? Show the calculation.”
- “How do the MSM6258 clock and divider settings affect its sampling rate?”
- “Does RESET flush the ATC on the MC68030?”

Include the machine, CPU, and operating conditions to help distinguish specifications across generations. Ask the AI to **use this MCP and cite the manual title, PDF page, and relevant table** so you can check the original before using a value in code.

You can ask in English or Japanese. Some sources and annotations are in Japanese; for English answers, ask your AI client to answer in English.

## What it provides

- Natural-language search using full-text and semantic hybrid retrieval through AWS Bedrock Managed Knowledge Base.
- A source catalog with CPU scope, chapter navigation, and structured-table locations.
- Page text and annotations to check the context around a search result.
- Complete structured-table rows for supported pages.
- Separate [unofficial Inside X68000 errata](https://kg68k.github.io/InsideX68000-errata/InsideX68000.html) references and selected reviewed corrections, retaining edition and machine-specific conditions.
- Exact rational arithmetic for checking instruction timings, timer periods, and other calculations.

The server supplies reference material and calculation results; your connected AI uses them to write its answer.

### Public MCP tools

| Tool | Purpose |
| --- | --- |
| `verification___list_sources` | List references, CPU scope, chapter navigation, and available structured tables |
| `managed-kb___Retrieve` | Search for relevant passages using natural language |
| `knowledge___get_page` | Read a PDF page's extracted text and annotations |
| `verification___read_tables` | Retrieve all structured-table rows for a supported page |
| `verification___calculate` | Evaluate an expression and return intermediate and final results |

The intended workflow is to locate the relevant manual, search for a passage, then check the page or table and its conditions. The calculator verifies arithmetic; formulas, units, and applicability still need to be checked against the source.

## Included references

As of November 22, 2026: **12 references, covering 3,229 PDF pages and one set of web notes.**

| Area | References |
| --- | --- |
| X68000 hardware | Inside X68000 |
| 68000-family instructions and base CPU | M68000 Family Programmer’s Reference Manual; MC68000 User’s Manual |
| 68030 and MMU | MC68030 User’s Manual |
| 68060 | MC68060 User’s Manual, addendum, and device errata |
| FPU | MC68881/MC68882 User’s Manual |
| ADPCM | OKI MSM6258 |
| Serial communications | Zilog SCC documentation for the Z8530 family |
| Networking | National DP8390D |
| Expansion hardware | Technical notes based on GORRY’s TS-6BGA development page |

Source URLs, document revisions, and CPU scope are recorded in [`sources/`](sources/). See the [peripheral reference notes](docs/issue-references.md) and [TS-6BGA notes](docs/ts6bga.md) for details (Japanese).

## Citations and answer quality

Citations can identify the **manual, PDF page, and relevant table**, rather than just the document. For example, MC68000 `MULU.W` timing is covered by **Table 8-4, PDF p.120**, with effective-address timing in **Table 8-1, PDF p.118** of the MC68000 User’s Manual.

PDF pages are **1-based positions in the PDF file** and may differ from the printed page numbers. Web notes cite the original URL. How citations are displayed or linked depends on your MCP client and the source.

Extracted text and OCR can contain errors; the full collection has not been proofread. Structured annotations currently cover **10 tables across 7 pages**, prioritizing display modes, instruction timings, and other useful hardware details. These have been checked against page images by AI, which is distinct from human proofreading. See [structured tables](docs/structured-tables.md) (Japanese).

Quality evaluation uses an LLM to call the production MCP and answer a question, then a separate, more capable model to grade accuracy, grounding, completeness, usefulness, and satisfaction. The latest answers for 19 representative questions and 2 questions with changed conditions scored 4/4 in all five categories. These are results for selected cases, not a first-attempt success rate or an accuracy claim for arbitrary questions. Earlier failures are retained. See the [evaluation results and scope](docs/aws-native-quality.md) (Japanese).

Before using a register address, bit position, numeric value, or code in an implementation, check the original reference, its revision, and the applicable CPU or machine.

## Run locally

You can ingest your own references and run SQLite FTS5 full-text search with a stdio MCP server. Its tool set differs from the public AWS-native service.

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Poppler's `pdftotext`, and SQLite with FTS5 trigram support.

```sh
# macOS, if Poppler is not installed
brew install poppler

uv sync --locked

uv run --no-sync x68k-knowledge ingest 'books/Inside X 68000.pdf' \
  --source sources/inside-x68000.json --output data/inside-x68000
uv run --no-sync x68k-knowledge index data/inside-x68000
uv run --no-sync x68k-knowledge search 'DMAC'
uv run --no-sync x68k-knowledge serve --db data/knowledge.sqlite3
```

`serve` uses stdio and is normally launched by your MCP client. Original PDFs and search databases are not included in this repository, so cloning it does not give you the public service's corpus.

See the [local development guide](docs/local-development.md) (Japanese) for multiple-source ingestion, official PDF download examples, and stdio configuration. `index` replaces the database using all specified corpora; include every corpus you want to keep when rebuilding.

## Development and deployment

```sh
uv sync --locked
make test
```

Regular tests run offline and do not call paid models or the production MCP. Live LLM evaluation is a separate, explicit operation with limits on request frequency and case count. See [quality evaluation](docs/quality-evaluation.md) (Japanese).

The detailed guides below are currently in Japanese.

| Guide | Contents |
| --- | --- |
| [AWS-native MCP](docs/aws-native.md) | Public MCP, ingestion, CloudFront, and certificates |
| [AWS Lambda + SQLite](docs/aws.md) | Read-only page retrieval used by the native MCP |
| [Ingestion priorities](docs/priority-assessment.md) | How references and tables are selected; remaining work |
| [Data design](docs/knowledge-plan.md) | Coverage and expansion plans |
| [Repository scope](docs/repository-layout.md) | Public files and locally managed data |

## Reference material

This repository does not include original PDFs, extracted full text, search databases, or API keys. `books/`, `data/`, `tmp/`, and `.env` are excluded from Git. Obtain references separately and check their usage conditions.

Rights in source materials remain with their respective rights holders. Manufacturer PDFs and material available on the web are not assumed to be freely redistributable. See the [reference material policy](docs/content-policy.md) (Japanese).

## License

The code is available under the [MIT License](LICENSE). This license does not grant rights to the source manuals themselves. See [NOTICE.md](NOTICE.md) (Japanese) for the distinction between software, reference metadata, structured annotations, and evaluation data. Personal deployment settings and operational identifiers are kept outside the public repository.
