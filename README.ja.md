# x68k-mcp

[English](README.md) | 日本語

X68000の開発・エミュレータ実装に必要な情報を、AIから出典付きで調べるためのMCPサーバーです。

Inside X68000、M68000系CPU／FPUのマニュアル、周辺チップのデータシートなどを検索し、仕様の確認に使うページや表を取得できます。画面モード、命令サイクル、レジスタ、音源まわりの調査を想定しています。

**公開MCP：[`https://x68k-mcp.j3tm0t0.dev/mcp`](https://x68k-mcp.j3tm0t0.dev/mcp)**

Streamable HTTP対応のMCPクライアントから利用できます。サーバーへの接続にアカウントやAPIキーは不要です。回答を生成するAIはクライアント側のものを使うため、その利用条件・料金は各クライアントに従います。

## 使い始める

### Claude Code

```sh
claude mcp add --transport http --scope user x68k-mcp \
  https://x68k-mcp.j3tm0t0.dev/mcp
```

登録後、Claude Codeの `/mcp` で接続状態を確認できます。`--scope user` はユーザー全体への登録です。設定方法の詳細は [Claude Code公式ドキュメント](https://code.claude.com/docs/en/mcp) を参照してください。

### その他のMCPクライアント

| 項目 | 設定 |
| --- | --- |
| 名前 | `x68k-mcp` |
| URL | `https://x68k-mcp.j3tm0t0.dev/mcp` |
| トランスポート | Streamable HTTP |
| 認証 | なし |

クライアント固有のMCPサーバー追加画面に設定してください。MCPのURLはAPIの接続先であり、ブラウザで開く検索画面とは異なります。

## こんな質問に

接続したAIに、例えば次のように聞いてみてください。

- 「X68000のグラフィック画面モードを、解像度・色数・ページ数・IOCS対応に分けて表にして」
- 「MC68000の `MULU.W D0,D1` と `MULU.W (A0),D1` の最小サイクル数は？ 実効アドレス計算も含めて」
- 「OPMのタイマBを `$80` に設定した場合の周期は？ クロック4MHzとして式も示して」
- 「MSM6258のサンプリング周波数は、クロックと分周設定でどう変わる？」
- 「MC68030でRESETしたとき、ATCはフラッシュされる？」

機種・CPU・動作条件を添えると、別世代の仕様との取り違えを減らせます。「このMCPで調べ、資料名とPDFページを付けて」と指定すると、根拠を追いやすくなります。

## できること

- 自然言語による資料検索。AWSのBedrock Managed Knowledge Baseで全文・意味のハイブリッド検索を行います。
- 資料一覧と章・図表の案内から、対象CPUやチップに合う出典を探す。
- 検索結果の断片に加え、出典ページの抽出テキストと注釈を取得する。
- 対応するページでは、構造化された表の全行を取得する。
- [Inside X68000の非公式正誤表](https://kg68k.github.io/InsideX68000-errata/InsideX68000.html)を別出典として参照し、重点確認した訂正には刷・機種の適用条件を添える。
- サイクル数やタイマ周期などを、有理数による計算ツールで検算する。

MCPサーバーが調査材料と計算結果を返し、接続したAIがそれらを使って回答します。英語・日本語で質問できます。英語の回答が必要な場合は、接続先のAIに英語で回答するよう指定してください。

### 公開MCPのツール

| ツール | 用途 |
| --- | --- |
| `verification___list_sources` | 資料一覧、対象CPU、章・構造化表の所在を確認 |
| `managed-kb___Retrieve` | 自然言語で関連箇所を検索 |
| `knowledge___get_page` | PDFページの抽出本文と注釈を取得 |
| `verification___read_tables` | 対応ページの構造化表を全行取得 |
| `verification___calculate` | 式を検算し、途中値と結果を取得 |

目次で対象を絞り、検索で関連箇所を見つけ、ページや表で条件を確認する使い方を想定しています。計算ツールは式を計算するもので、式や単位、適用条件そのものの正しさは出典で確認します。

## 収録資料

2026-11-22時点で12資料、PDF 3,229ページとWebメモ1件を収録しています。

| 分野 | 資料 |
| --- | --- |
| X68000本体 | Inside X68000 |
| 68000系命令・基本CPU | M68000 Family Programmer’s Reference Manual、MC68000 User’s Manual |
| 68030・MMU | MC68030 User’s Manual |
| 68060 | MC68060 User’s Manual、追補、デバイスエラッタ |
| FPU | MC68881/MC68882 User’s Manual |
| ADPCM | OKI MSM6258 |
| シリアル | Zilog SCC資料（Z8530系） |
| ネットワーク | National DP8390D |
| 拡張ハードウェア | GORRY氏のTS-6BGA開発ページに基づくWebメモ |

出典URL、文書の版、CPUの適用範囲などは [`sources/`](sources/) に記録しています。[部品資料の詳細](docs/issue-references.md)・[TS-6BGAメモ](docs/ts6bga.md)

## 出典と回答品質

出典のPDFページは**1始まりのPDF上の位置**です。紙面に印刷されたページ番号とは異なる場合があります。手元の原本を確認するときは、この違いに注意してください。Webメモは元ページのURLを出典にします。

OCR・抽出テキストには誤りがあり、全ページの校正は終わっていません。画面モードや命令サイクルなど優先度の高い表から構造化を進めており、現在は7ページ・10表です。これらはAIによる原本画像との照合で、人手による校正済みとは区別しています。[表の構造化](docs/structured-tables.md)

品質確認では、LLMが実際に本番MCPを呼んで回答し、別の上位モデルが正確さ・根拠・網羅性・実用性・満足度を採点します。代表19問と条件を変えた追加2問の最新回答は、全5項目で4点満点でした。選定したケースの結果であり、初回成功率や未知の質問全般の正確さを示すものではありません。以前の失敗も記録しています。[改善内容と検証範囲](docs/aws-native-quality.md)

レジスタの番地・ビット位置、数値、コードを実装に使う際は、対象機種・CPU・資料の版と原本を確認してください。資料にない条件は、確認できない範囲として扱います。

## ローカルで動かす

自分で用意した資料を取り込み、SQLite FTS5による全文検索とstdio MCPを動かせます。公開AWSネイティブ版とはツール構成が異なります。

Python 3.11以上、[uv](https://docs.astral.sh/uv/)、Popplerの `pdftotext`、FTS5 trigram対応SQLiteが必要です。

```sh
# macOSでPopplerが未導入の場合
brew install poppler

uv sync --locked

uv run --no-sync x68k-knowledge ingest 'books/Inside X 68000.pdf' \
  --source sources/inside-x68000.json --output data/inside-x68000
uv run --no-sync x68k-knowledge index data/inside-x68000
uv run --no-sync x68k-knowledge search 'DMAC'
uv run --no-sync x68k-knowledge serve --db data/knowledge.sqlite3
```

`serve` はstdio接続用です。通常はMCPクライアントから起動します。原本PDFや検索DBはリポジトリに含まれていないので、クローン直後に公開サービスと同じデータが揃うわけではありません。

複数資料の取り込み、公式PDFの取得例、stdio接続設定は [ローカル開発手順](docs/local-development.md) を参照してください。`index` は指定した全コーパスからDBを置き換えるため、追加時も収録するコーパスをすべて指定します。

## 開発・運用

```sh
uv sync --locked
make test
```

通常テストはオフラインで、有料モデルや本番MCPを呼びません。実LLMによる品質確認は明示的な手動実行に分け、呼び出し間隔と実行件数を制限しています。[評価方法](docs/quality-evaluation.md)

| ドキュメント | 内容 |
| --- | --- |
| [AWSネイティブ版](docs/aws-native.md) | 公開MCP、取り込み、CloudFront、ワイルドカード証明書 |
| [AWS Lambda＋SQLite版](docs/aws.md) | 同じ全文検索データを使う比較用実装 |
| [取り込みの優先度](docs/priority-assessment.md) | 構造化する資料・表の選び方と残る課題 |
| [データ設計](docs/knowledge-plan.md) | 収録方針と拡張候補 |
| [公開repoの範囲](docs/repository-layout.md) | 含めるファイルと非公開データの区別 |

## 資料の取り扱い

このリポジトリには、原本PDF、抽出全文、検索DB、APIキーを含めません。`books/`・`data/`・`tmp/`・`.env` はGit対象外です。資料は各自、利用条件を確認して用意してください。

各資料の権利はそれぞれの権利者に帰属します。利用条件は出典ごとに確認してください。メーカー公開資料やWeb上の情報を、公開されていることだけで自由に再配布できるものとは扱いません。[資料・公開データの扱い](docs/content-policy.md)

## ライセンス

コードは [MIT License](LICENSE)。出典資料そのものの権利・利用条件はこのライセンスに含まれません。構造化注釈、資料メタデータ、評価データの位置付けは [NOTICE.md](NOTICE.md) を参照してください。個人環境の設定や稼働中サービスの管理情報は公開ファイルに含めません。
