# R.A.I.N. Lab 文档入口（简体中文）

<p align="center">
  <a href="https://github.com/topherchris420/james_library/actions/workflows/ci.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/tests.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/tests.yml/badge.svg?branch=main" alt="Tests" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml/badge.svg?branch=main" alt="Docs" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml/badge.svg?branch=main" alt="Security Audit" /></a>
</p>

> 本页是仓库的中文入口页，对齐主 README 与文档中心的信息架构。

## 导航

- 英文主入口：[`README.md`](README.md)
- 文档中心（中文）：[`docs/README.zh-CN.md`](docs/README.zh-CN.md)
- 统一目录：[`docs/SUMMARY.md`](docs/SUMMARY.md)

## 项目身份速览（Quick Map）

- **R.A.I.N. Lab**：面向最终用户的一体化产品体验
- **James Library**：Python 研究与工作流层
- **R.A.I.N.**：Rust 运行时层（`R.A.I.N.` crate）

运行路径：`用户 -> R.A.I.N. Lab 界面 -> R.A.I.N. 运行时 -> James Library 研究工作流 -> 模型/Provider API`

## 快速开始

```bash
python rain_lab.py
```

更多命令与配置说明请参考文档中心与运行时参考文档。

## 能力速览（Capabilities At A Glance）

本页是入口。完整运行时能力（命令、通道、Provider、运维、安全、硬件）请参考下表链接。

| 能力领域 | 你可以获得什么 | 规范文档 |
| --- | --- | --- |
| CLI 与自动化 | 引导、agent、gateway/daemon、service、诊断、estop、cron、skills、更新 | [Commands Reference](docs/reference/cli/commands-reference.md) |
| 通道与消息 | 多通道投递、allowlist、webhook/polling 模式、按通道配置 | [Channels Reference](docs/reference/api/channels-reference.md) |
| Provider 与模型路由 | 本地/云 Provider、别名、认证环境变量、模型刷新流程 | [Providers Reference](docs/reference/api/providers-reference.md) |
| 配置与运行时契约 | 配置结构与行为保证 | [Config Reference](docs/reference/api/config-reference.md) |
| 运维与故障排查 | Runbook、部署模式、诊断与故障恢复 | [Operations Runbook](docs/ops/operations-runbook.md), [Troubleshooting](docs/ops/troubleshooting.md) |
| 安全模型 | 沙箱、策略边界、审计姿态 | [Security Docs Hub](docs/security/README.md) |
| 硬件与外设 | 开发板接入与外设工具设计 | [Hardware Docs Hub](docs/hardware/README.md) |

## 我应该先读什么（Who Should Read What Next）

- **新用户 / 首次体验**：从 [`START_HERE.md`](START_HERE.md) 开始，然后阅读 [`docs/getting-started/README.md`](docs/getting-started/README.md)。
- **运维 / 部署负责人**：优先阅读 [`docs/ops/operations-runbook.md`](docs/ops/operations-runbook.md) 与 [`docs/ops/troubleshooting.md`](docs/ops/troubleshooting.md)。
- **集成方 / 二次开发者**：优先阅读 [`docs/reference/cli/commands-reference.md`](docs/reference/cli/commands-reference.md)、[`docs/reference/api/config-reference.md`](docs/reference/api/config-reference.md)、[`docs/reference/api/providers-reference.md`](docs/reference/api/providers-reference.md)、[`docs/reference/api/channels-reference.md`](docs/reference/api/channels-reference.md)。
