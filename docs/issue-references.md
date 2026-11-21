# pix68k-dev の issue と部品仕様の対応

対象リポジトリは **j3tm0t0/pix68k-dev**。ローカル `pix68k` の origin と GitHub API で確認した。
2026-11-18 時点の記録。issue 本文やコメント、他エミュレータのコードはコーパスに入れていない。
検索結果の `related_issues` に対応 URL、`part_numbers` に型番、`scope_note` に適用範囲を返す。

| 資料 / 出典 ID | PDF ページ | 関連 issue | 入手元 |
| --- | ---: | --- | --- |
| MSM6258/MSM6258V / `oki-msm6258` | 38 | [#221](https://github.com/j3tm0t0/pix68k-dev/issues/221) | [OKI 原本の保存版](https://www.elektronikjk.pl/elementy_czynne/IC/MSM6258.pdf) |
| MC68030 User's Manual / `nxp-m68030-um` | 599 | [#210](https://github.com/j3tm0t0/pix68k-dev/issues/210) | [NXP 配布版](https://www.nxp.com/docs/en/reference-manual/MC68030UM.pdf) |
| MC68881/MC68882 User's Manual / `nxp-m68881-um` | 409 | [#210](https://github.com/j3tm0t0/pix68k-dev/issues/210)、[#109 の68881ボード項目](https://github.com/j3tm0t0/pix68k-dev/issues/109) | [NXP 配布版](https://www.nxp.com/docs/en/reference-manual/MC68881UM.pdf) |
| Zilog SCC User's Manual / `zilog-scc-1992` | 324 | [#110](https://github.com/j3tm0t0/pix68k-dev/issues/110) | [Zilog 原本の保存版](https://bitsavers.trailing-edge.com/components/zilog/_dataBooks/SCC_Users_Manual_1992.pdf) |
| DP8390D/NS32490D / `national-dp8390d` | 56 | [#109](https://github.com/j3tm0t0/pix68k-dev/issues/109) | [National Semiconductor 原本の保存版](https://megaburken.net/~patrik/DP8390D.pdf) |

issue #110 は確認時点では closed。他の3件は open。関連資料としての対応は状態にかかわらず保持する。

## 版と適用範囲

- MC68030 は表紙の **Third Edition / MC68030UM/AD REV 2** と原本の1990年表記を記録した。配布サイト上の版・年と混同しない。
- MC68881/68882 は **Second Edition / 1989**。MC68040/68060 の内蔵 FPU、X68030 の基板構成とは区別する。
- SCC は **Q4/92**。Z8530 を明記する原本を選んだ。CMOS SCC や ESCC の拡張を Z8530 に一律適用しない。
- DP8390 は **DP8390D/NS32490D、July 1995** の資料。互換チップや Neptune-X の配線・アドレスデコード、ホストのネットワーク実装は別途確認する。
- MSM6258 は型番と本文を確認したが、出版年・版は確証がないため設定していない。内蔵変換器、基板上のフィルタ、ホストのリサンプリングを分けて検証する。

メーカーサイトで現行配布を確認できなかった資料は保存版を使用し、配布元とメーカーを別のメタデータに記録した。
PDF は既存のテキスト層を抽出したもの。抽出文字の被覆と位置を検証したが、全図表・数値の校正は未実施。
資料の収録は issue の原因特定や実装完了を意味しない。

## 検索例

```sh
uv run --no-sync x68k-knowledge search 'filter' --source-id oki-msm6258
uv run --no-sync x68k-knowledge search 'PTEST' --source-id nxp-m68030-um
uv run --no-sync x68k-knowledge search 'FRESTORE' --source-id nxp-m68881-um
uv run --no-sync x68k-knowledge search 'WR9' --source-id zilog-scc-1992
uv run --no-sync x68k-knowledge search 'Remote DMA' --source-id national-dp8390d
```

## 再取り込み

各 PDF は `books/oki/MSM6258.pdf`、`books/nxp/MC68030UM.pdf`、`books/nxp/MC68881UM.pdf`、
`books/zilog/SCC_Users_Manual_1992.pdf`、`books/national/DP8390D.pdf` に保存している。
取得 URL は同じ出典 ID の `sources/<id>.json` を参照する。

たとえば MSM6258 を再抽出する場合：

```sh
uv run --no-sync x68k-knowledge ingest books/oki/MSM6258.pdf \
  --source sources/oki-msm6258.json --output data/oki-msm6258
```

索引を再構築するときは、既存資料を落とさないようコーパスをすべて指定する（README参照）。
