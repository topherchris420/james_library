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

## クイックスタート

```bash
python rain_lab.py
```

実行コマンドや設定の詳細は docs ハブとリファレンスを参照してください。

## 機能一覧（Capabilities At A Glance）

このページは入口です。ランタイム全体の機能面（コマンド、チャネル、プロバイダー、運用、セキュリティ、ハードウェア）は次のリファレンスを参照してください。

| 機能領域 | できること | 公式リファレンス |
| --- | --- | --- |
| CLI と自動化 | オンボーディング、agent、gateway/daemon、service、診断、estop、cron、skills、更新 | [Commands Reference](docs/reference/cli/commands-reference.md) |
| チャネルとメッセージング | マルチチャネル配信、allowlist、webhook/polling モード、チャネル別設定 | [Channels Reference](docs/reference/api/channels-reference.md) |
| プロバイダーとモデルルーティング | ローカル/クラウドプロバイダー、エイリアス、認証環境変数、モデル更新手順 | [Providers Reference](docs/reference/api/providers-reference.md) |
| 設定とランタイム契約 | 設定スキーマと動作保証 | [Config Reference](docs/reference/api/config-reference.md) |
| 運用とトラブルシューティング | Runbook、デプロイパターン、診断と障害復旧 | [Operations Runbook](docs/ops/operations-runbook.md), [Troubleshooting](docs/ops/troubleshooting.md) |
| セキュリティモデル | サンドボックス、ポリシー境界、監査方針 | [Security Docs Hub](docs/security/README.md) |
| ハードウェアと周辺機器 | ボード設定と周辺機器ツール設計 | [Hardware Docs Hub](docs/hardware/README.md) |

## 次に読むべき資料（Who Should Read What Next）

- **新規ユーザー / 初回体験**：[`START_HERE.md`](START_HERE.md) から始め、次に [`docs/getting-started/README.md`](docs/getting-started/README.md) を参照。
- **運用担当 / デプロイ担当**：[`docs/ops/operations-runbook.md`](docs/ops/operations-runbook.md) と [`docs/ops/troubleshooting.md`](docs/ops/troubleshooting.md) を優先。
- **インテグレーター / 拡張開発者**：[`docs/reference/cli/commands-reference.md`](docs/reference/cli/commands-reference.md)、[`docs/reference/api/config-reference.md`](docs/reference/api/config-reference.md)、[`docs/reference/api/providers-reference.md`](docs/reference/api/providers-reference.md)、[`docs/reference/api/channels-reference.md`](docs/reference/api/channels-reference.md) を優先。
