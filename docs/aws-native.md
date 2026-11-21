# AWSネイティブMCP

公開MCPは [https://x68k-mcp.j3tm0t0.dev/mcp](https://x68k-mcp.j3tm0t0.dev/mcp)。CloudFrontから東京リージョンのAgentCore Gatewayへ転送し、Bedrock Managed Knowledge Baseで資料を検索する。

## 構成

- Bedrock Managed Knowledge Base: ページ単位テキストの埋め込み、全文・意味のハイブリッド検索、管理されたリランキング。
- AgentCore Gateway: 認証なしのStreamable HTTP MCP。検索対象KBは管理者設定に固定。
- `managed-kb___Retrieve`: 関連箇所5件を取得する標準コネクター。
- `knowledge___get_page`: 読み取り専用SQLiteを持つLambdaから、抽出本文と注釈を1ページ取得。
- `verification___list_sources` / `read_tables` / `calculate`: 資料目次、全行の構造化表、制限したASTとFractionによる有理数の計算。
- CloudFront＋ACM: 独自ドメインのHTTPS。MCP応答・エラーはキャッシュせず、Host以外のリクエストヘッダーとクエリを転送する。

モデルはMCPクライアント側で動く。MCPサーバーにはOpenAI等のAPIキーを置かない。生成機能付きAgenticRetrieveStreamは画面モードの網羅性が不十分だったため、既定で無効にしている。[品質記録](aws-native-quality.md)

## 自分のAWS環境へデプロイ

AWS CLIと必要な権限、[ローカルで取り込んだ資料と検索DB](local-development.md)が必要。デプロイ・取り込み・検索にはAWS料金が発生する。公開サービスの利用だけなら、この作業は不要。

各コマンドはリポジトリルートから実行する。プロファイルは `--profile` または `AWS_PROFILE` を使用し、未指定時はAWS CLIの `default`。

```sh
# 例のプロファイル名は自分の環境に合わせる
uv run --no-sync python -m aws.deploy --profile my-profile --region ap-northeast-1
uv run --no-sync python -m aws.managed --profile my-profile --region ap-northeast-1
```

先にLambda＋SQLite版を作るのは、Native版の完全ページ取得がそのLambdaを参照するため。`aws.deploy` は非公開配布用S3・Lambda・Gatewayを、`aws.managed` は非公開文書用S3・IAM・Managed KBを作成する。既存リソースはProjectタグで所有を確認する。Lambda＋SQLite版の詳細は [こちら](aws.md)。

生成した状態はGit対象外の `tmp/aws-deployment.json` と `tmp/bedrock-managed/deployment.json` に保存する。AWSアカウント固有のID・ARN・バケット名はこの状態から読む。別環境で状態を使い回さない。

```sh
uv run --no-sync python -m aws.managed_ingest --all
uv run --no-sync python -m aws.managed_status
uv run --no-sync python -m aws.managed_gateway --verification --no-agentic
```

初回のCustomデータソース作成後、AVAILABLEになるまで待ち、案内に従って取り込みを再実行する。MANAGED型の直接取り込みは実APIで確認した10文書ずつ。ハッシュが同じ受理済み文書は再送しない。受理済みとINDEXEDは区別し、`managed_status` で全文書の索引化と失敗0を確認する。大量データを何度も再取り込みしない。

標準S3コネクターは初期検証で完了0件になったため、現在はCustom connectorとIngestKnowledgeBaseDocumentsを使う。`aws.managed_sync` は診断用で、通常の取り込みには使わない。

## 入力と公開範囲

AWSへ取り込むのは既存の抽出テキスト、出典と対象CPU、構造化注釈。原本PDF・ページ画像・APIキーは取り込まない。ページは1始まりのPDF位置、Webメモは元URLを保持する。元本文とAI注釈を区別し、注釈を校正済み全文として扱わない。

S3は公開しない。投入する資料の利用条件と、サービスでの提供範囲は [資料の扱い](content-policy.md) を参照。

既定の検索ターゲット制限は毎分6回、ページ取得・検証ターゲットは毎分30回。利用量と費用はデプロイ先で管理する。

## 独自ドメイン

ACM証明書をus-east-1で用意し、DNS検証を完了させてから `aws/custom-domain-stack.json` をデプロイする。公開サービスはユーザー指定のワイルドカード証明書を使用。自分の環境では対象ホストを含む証明書ARNを指定する。

```sh
aws cloudformation deploy \
  --template-file aws/custom-domain-stack.json \
  --stack-name x68k-knowledge-custom-domain \
  --parameter-overrides \
    DomainName=mcp.example.com \
    GatewayHostname=YOUR_GATEWAY.gateway.bedrock-agentcore.ap-northeast-1.amazonaws.com \
    CertificateArn=YOUR_ISSUED_CERTIFICATE_ARN \
  --region us-east-1 --profile my-profile --no-fail-on-empty-changeset
```

出力のDistributionDomainへDNSのCNAME等を向ける。GatewayHostnameにはスキームや `/mcp` を付けない。公開URLの `/mcp` はそのまま転送し、OriginPathで二重に足さない。CertificateArnを空にした初期構築はCloudFront標準ドメインのみで、独自ドメインの完成ではない。

新旧DNSが併存する移行中は両方に検証・接続レコードを入れる。DNS委任・DNSSECの移行手順は、元のDNS管理者とレジストラの手順に従う。個人ドメインの移行記録や証明書ARNはこのリポジトリに保存しない。

接続確認はTLS検証を有効にした実HTTPのinitializeとtools/listで行う。有料検索の追加呼び出しは不要。[AWSの独自ドメイン手順](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-custom-domains.html)

## 費用・参考資料

Managed KB、Gateway、S3、Lambda、CloudFront、DNS等にはそれぞれ料金が発生する。利用量と最新料金を確認する。[Bedrock料金](https://aws.amazon.com/bedrock/pricing/)

[Managed Knowledge Base](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-build-managed.html)、[Custom connector](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-custom.html)、[標準MCPコネクター](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-managed-kb.html)
