# 完全ページ取得用のAWS Lambda＋SQLite

AWSネイティブMCPの `knowledge___get_page` は、この読み取り専用Lambdaを参照する。Lambda単独版のGatewayはローカルと同じキーワード検索も提供するが、公開READMEの主接続先は [AWSネイティブ版](aws-native.md)。

## デプロイ

ローカルの `data/knowledge.sqlite3` を先に作る。原本PDF・キーは配布物に含めず、SQLiteとPython実装を非公開S3からLambdaへ配置する。

```sh
uv run --no-sync python -m aws.deploy --profile my-profile --region ap-northeast-1
```

`--profile` の既定は `AWS_PROFILE`、未設定なら `default`。同名の既存スタックはProjectタグを確認する。配布物はハッシュ付きS3キーを使い、再デプロイ時にDBを更新する。CLIから取り込み前の原本はアップロードしない。

| ファイル | 役割 |
| --- | --- |
| `aws/artifacts-stack.json` | 非公開の配布物S3 |
| `aws/build.py` | SQLiteと実装からLambda ZIP・CloudFormationを生成 |
| `aws/deploy.py` | スタック作成・更新とデプロイ後のヘルス確認 |
| `aws/lambda_handler.py` | Gatewayからの読み取りツール呼び出し |

状態は `tmp/aws-deployment.json`、生成物は `tmp/aws-build/` に保存し、Gitへは入れない。ネイティブGatewayのページ取得先は同一アカウント・リージョンの `x68k-knowledge-aws-search`。関数名を変える場合は `aws.managed_gateway` 側も合わせる。

## 検証と取り扱い

```sh
make test
# 明示的にデプロイ先MCPへ接続。10秒以上の操作間隔を維持する
uv run --no-sync python -m aws.smoke
```

SQLiteは読み取り専用接続、検索件数と入力長を制限する。元ページ本文は返すため、データの非公開保存と公開ツールの返却範囲は分けて扱う。認証なしGatewayを作るので、投入データの利用条件と公開意図を先に確認する。

`--keep-failed` は初期構築の診断用。スタック削除時のGateway・Lambda・IAMと、Retainで保持する配布物S3の扱いは別。誤って稼働中のデータやスタックを消さない。
