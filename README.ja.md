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

## 機能概要

James は単なるマルチエージェントチャットではなく、完全な研究オペレーティングシステムです：10以上のモデルプロバイダ、25以上のメッセージングプラットフォーム、60以上の組み込みツール、ハードウェア制御（Arduino、STM32、Raspberry Pi）、神経科学の脳エンコーディングモデル（TRIBE v2）、ナレッジグラフ、セマンティックメモリなど。詳細は英語版 [`README.md` - What It Does](README.md#what-it-does) をご覧ください。

## 対象ユーザー

R.A.I.N. Lab は、もっともらしいだけでなく、根拠を持って説明できる答えを必要とする人のために作られています。

| 役割 | R.A.I.N. Lab でできること |
| --- | --- |
| 創業者・プロダクトリーダー | ロードマップや予算を確定する前に、構造化された議論で戦略的意思決定をストレステスト |
| 研究者・アナリスト | 競合する仮説を比較し、意見の相違を保持し、監査可能な推論の記録を残す |
| オペレーター・技術チーム | 混沌とした議論を、レビュー・共有・再実行可能な検証済みの成果物に変換 |

## 他ツールとの違い

| 一般的な研究ツール | R.A.I.N. Lab |
| --- | --- |
| 論文リストを返す | ディベートを返す |
| 最初にもっともらしい答えを正解とする | 証拠で解決されるまで意見の相違を保持 |
| 1つの視点、1つのモデル | 異なる専門知識と制約を持つ4つの声 |
| クラウドファースト | 完全ローカル実行可能 |

## ローカル・プライベートワークフロー

R.A.I.N. Lab はお使いのハードウェア上で完全に動作します。[LM Studio](https://lmstudio.ai/) または [Ollama](https://ollama.com/) でローカルモデルを接続すれば、クラウド通信・テレメトリ・データ共有は一切ありません。

## クイックスタート

**ライブデモ：** [rainlabteam.vercel.app](https://rainlabteam.vercel.app/) — セットアップ不要

```bash
python rain_lab.py
```

Windows の場合：`INSTALL_RAIN.cmd` をダブルクリック。
macOS/Linux の場合：`./install.sh` を実行。

実行コマンドや設定の詳細は docs ハブとリファレンスを参照してください。

## 動作要件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（推奨）または pip
- Rust ツールチェーン（オプション、ZeroClaw ランタイムレイヤー用）
- [LM Studio](https://lmstudio.ai/) または [Ollama](https://ollama.com/) によるローカルモデル（オプション — デモモードではモデル不要）

## ドキュメント

| | |
|---|---|
| **はじめに** | [ここから開始](START_HERE.md) -- [初心者ガイド](docs/getting-started/README.md) -- [ワンクリックインストール](docs/one-click-bootstrap.md) -- [トラブルシューティング](docs/troubleshooting.md) |
| **論文** | [研究アーカイブ](https://topherchris420.github.io/research/) |
| **他の言語** | [English](README.md) -- [简体中文](README.zh-CN.md) -- [Русский](README.ru.md) -- [Français](README.fr.md) -- [Tiếng Việt](README.vi.md) |

## 開発者向け

アーキテクチャ、拡張ポイント、コントリビューションについては、英語版 [`README.md` - For Developers](README.md#for-developers)、[ARCHITECTURE.md](ARCHITECTURE.md)、[CLAUDE.md](CLAUDE.md) を参照してください。

## 謝辞

R.A.I.N. Lab の基盤となる Rust ランタイムエンジンを提供してくださった **ZeroClaw** チームに特別な感謝を。詳細は `crates/` ディレクトリをご覧ください。

---

**ライセンス：** MIT -- [Vers3Dynamics](https://vers3dynamics.com/)
