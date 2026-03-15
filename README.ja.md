# R.A.I.N. Lab ドキュメント入口（日本語）

> このページは日本語向けのリポジトリ入口です。README と docs ハブ構成に合わせています。

## ナビゲーション

- 英語メイン：[`README.md`](README.md)
- ドキュメントハブ（日本語）：[`docs/README.ja.md`](docs/README.ja.md)
- 統合目次：[`docs/SUMMARY.md`](docs/SUMMARY.md)

## プロジェクト構成クイックマップ

- **R.A.I.N. Lab**：エンドユーザー向けの製品体験
- **James Library**：Python の研究/ワークフローレイヤー
- **ZeroClaw**：Rust ランタイムレイヤー（`zeroclaw` crate）

実行フロー：`ユーザー -> R.A.I.N. Lab インターフェース -> ZeroClaw ランタイム -> James Library 研究ワークフロー -> モデル/Provider API`

## クイックスタート

```bash
python rain_lab.py
```

実行コマンドや設定の詳細は docs ハブとリファレンスを参照してください。
