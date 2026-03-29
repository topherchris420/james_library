# R.A.I.N. Lab ドキュメント入口（日本語）

<p align="center">
  <a href="https://github.com/topherchris420/james_library/actions/workflows/ci.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/tests.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/tests.yml/badge.svg?branch=main" alt="Tests" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml/badge.svg?branch=main" alt="Docs" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml/badge.svg?branch=main" alt="Security Audit" /></a>
</p>

> このページは日本語向けのリポジトリ入口です。README と docs ハブ構成に合わせています。

## ナビゲーション

- 英語メイン：[`README.md`](README.md)
- ドキュメントハブ（日本語）：[`docs/README.ja.md`](docs/README.ja.md)
- 統合目次：[`docs/SUMMARY.md`](docs/SUMMARY.md)

## プロジェクト構成クイックマップ

- **R.A.I.N. Lab**：エンドユーザー向けの製品体験
- **James Library**：Python の研究/ワークフローレイヤー
- **R.A.I.N.**：Rust ランタイムレイヤー（`R.A.I.N.` crate）

実行フロー：`ユーザー -> R.A.I.N. Lab インターフェース -> R.A.I.N. ランタイム -> James Library 研究ワークフロー -> モデル/Provider API`

## 対象ユーザー

R.A.I.N. Lab は、もっともらしいだけでなく、根拠を持って説明できる答えを必要とする人のために作られています。

| 役割 | R.A.I.N. Lab でできること |
| --- | --- |
| 創業者・プロダクトリーダー | ロードマップや予算を確定する前に、構造化された議論で戦略的意思決定をストレステスト |
| 研究者・アナリスト | 競合する仮説を比較し、意見の相違を保持し、監査可能な推論の記録を残す |
| オペレーター・技術チーム | 混沌とした議論を、レビュー・共有・再実行可能な検証済みの成果物に変換 |

実際には、「AIがそう言った」で終わる行き止まりが減ります。一つの質問から始めて、複数のエージェントに前提を検証させ、未解決の対立を検証プロセスに回し、自信を持って他者に提示できる結果を得ることができます。

## クイックスタート

```bash
python rain_lab.py
```

実行コマンドや設定の詳細は docs ハブとリファレンスを参照してください。
