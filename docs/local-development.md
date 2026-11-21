# ローカルでの取り込みとMCP起動

公開MCPの利用にはこのセットアップは不要。自分で用意した資料をローカルで取り込み、SQLite全文検索とstdio MCPを動かすための手順。公開AWSネイティブ版の意味検索・検算ツールとは構成が異なる。

## セットアップ

Python 3.11 以上、[uv](https://docs.astral.sh/uv/)、Poppler の `pdftotext` が必要。
Python の SQLite は FTS5 と trigram tokenizer を利用できる版（SQLite 3.34 以上）を使う。

```sh
# macOS: Poppler がない場合
brew install poppler

uv sync --locked
```

## 取り込みと検索

リポジトリのルートで実行する。

```sh
uv run --no-sync x68k-knowledge ingest 'books/Inside X 68000.pdf' \
  --source sources/inside-x68000.json \
  --output data/inside-x68000

uv run --no-sync x68k-knowledge index data/inside-x68000

uv run --no-sync x68k-knowledge search 'DMAC'
uv run --no-sync x68k-knowledge search 'ADPCM レジスタ' --limit 3
uv run --no-sync x68k-knowledge search '$E8001B'
uv run --no-sync x68k-knowledge page inside-x68000 100
```

公式仕様書を追加する場合（ダウンロードした PDF も `books/` 以下で Git 対象外）：

```sh
mkdir -p books/nxp
curl --fail --location --output books/nxp/M68000PRM.pdf \
  https://www.nxp.com/docs/en/reference-manual/M68000PRM.pdf
curl --fail --location --output books/nxp/MC68000UM.pdf \
  https://www.nxp.com/docs/en/reference-manual/MC68000UM.pdf

uv run --no-sync x68k-knowledge ingest books/nxp/M68000PRM.pdf \
  --source sources/nxp-m68000-prm.json --output data/nxp-m68000-prm
uv run --no-sync x68k-knowledge ingest books/nxp/MC68000UM.pdf \
  --source sources/nxp-m68000-um.json --output data/nxp-m68000-um
uv run --no-sync x68k-knowledge index \
  data/inside-x68000 data/nxp-m68000-prm data/nxp-m68000-um

uv run --no-sync x68k-knowledge search 'MOVEM' --source-id nxp-m68000-prm
uv run --no-sync x68k-knowledge search 'Bus Error' --source-id nxp-m68000-um
```

M68000 ファミリー全体の仕様には、MC68000 で使えない命令・モードもある。
検索結果の `cpu_scope_note` と原文の対応 CPU 表記を確認する。

68060 の資料も追加する場合：

```sh
curl --fail --location --output books/nxp/MC68060UM.pdf \
  https://www.nxp.com/docs/en/data-sheet/MC68060UM.pdf
curl --fail --location --output books/nxp/MC68060UMAD.pdf \
  https://www.nxp.com/docs/en/reference-manual/MC68060UMAD.pdf
curl --fail --location --output books/nxp/MC68060DE.pdf \
  https://www.nxp.com/docs/en/errata/MC68060DE.pdf

uv run --no-sync x68k-knowledge ingest books/nxp/MC68060UM.pdf \
  --source sources/nxp-m68060-um.json --output data/nxp-m68060-um
uv run --no-sync x68k-knowledge ingest books/nxp/MC68060UMAD.pdf \
  --source sources/nxp-m68060-umad.json --output data/nxp-m68060-umad
uv run --no-sync x68k-knowledge ingest books/nxp/MC68060DE.pdf \
  --source sources/nxp-m68060-errata.json --output data/nxp-m68060-errata
uv run --no-sync x68k-knowledge index \
  data/inside-x68000 data/nxp-m68000-prm data/nxp-m68000-um \
  data/nxp-m68060-um data/nxp-m68060-umad data/nxp-m68060-errata

uv run --no-sync x68k-knowledge search 'Unimplemented' --source-id nxp-m68060-um
uv run --no-sync x68k-knowledge search 'I11' --source-id nxp-m68060-errata
```

68060 の本体マニュアル・追補・デバイスエラッタは別の出典として保存する。
追補は本文表記の Rev 0.1（1998-03-25）、エラッタは Rev 4.0（1996-10-18）。
エラッタは CPU の派生品とマスクセットごとに適用が異なる。
資料間の関係はメタデータと `cpu_scope_note` に記録するが、訂正の優先順位を検索結果に自動適用する機能はまだない。

検索語の空白は AND 条件。同じチャンクにすべての語が含まれる結果を返す。
長い質問文より `ラスタコピー`、`割り込み`、`DMAC` のような短い語で検索する。
記号もリテラル扱いで、FTS の演算子は受け付けない。
`$` を含むアドレスはシェルで展開されないようシングルクォートで囲む。
全角・半角、大文字・小文字、OCR に入った空白は検索用データで吸収する。
`OPM` と `0PM` のような誤認識は補正していないため、見つからなければ表記を変えて再検索する。
`FM` / `BG` など 2 文字以下の語も検索できるが、部分一致の走査になる。

複数資料の索引を作る場合は、**収録したいコーパスをすべて**指定する。
`index` は追記ではなく、新しい DB を作って置き換える。

```sh
uv run --no-sync x68k-knowledge index data/inside-x68000 data/another-book
uv run --no-sync x68k-knowledge search 'DMAC' --source-id inside-x68000
```

## MCP クライアントから使う

```sh
uv run --no-sync x68k-knowledge serve --db data/knowledge.sqlite3
```

これは stdio 接続用なので、通常は MCP クライアントにプロセスを起動させる。
接続設定の例（`/absolute/path/to/x68k-mcp` は実際の絶対パスに置換）：

```json
{
  "mcpServers": {
    "x68k-knowledge": {
      "command": "/absolute/path/to/x68k-mcp/.venv/bin/x68k-knowledge",
      "args": [
        "serve",
        "--db",
        "/absolute/path/to/x68k-mcp/data/knowledge.sqlite3"
      ]
    }
  }
}
```

クライアント固有の設定ファイル名・登録方法はそのクライアントに従う。
検索結果の `source_uri` は原本の相対パスと PDF ページ位置。原本を開く場合はリポジトリのルートから解決する。
`pdf_page` は PDF の 1 始まりのページ位置で、印刷ページとは異なる。
`printed_page` は今回の本ではオフセットによる推定値。引用位置の基準には `pdf_page` を使う。

| ツール | 用途 |
| --- | --- |
| `list_sources()` | 資料・来歴・ライセンス・校正状況を確認 |
| `search_knowledge(query, limit=5, source_id=null)` | ページ情報付きのチャンク検索（最大20件） |
| `get_page(source_id, pdf_page)` | 原文 OCR を1ページ取得して前後関係を確認 |


## Webメモの取り込みと全資料の索引化

Webメモの元URLと適用範囲は [TS-6BGAメモ](ts6bga.md) を参照。

```sh
uv run --no-sync x68k-knowledge ingest-notes docs/ts6bga.md \
  --source sources/gorry-ts6bga-notes.json --output data/gorry-ts6bga-notes

uv run --no-sync x68k-knowledge index \
  data/inside-x68000 data/nxp-m68000-prm data/nxp-m68000-um \
  data/nxp-m68060-um data/nxp-m68060-umad data/nxp-m68060-errata \
  data/oki-msm6258 data/nxp-m68030-um data/nxp-m68881-um \
  data/zilog-scc-1992 data/national-dp8390d data/gorry-ts6bga-notes
```
