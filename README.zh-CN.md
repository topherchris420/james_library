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

## 功能概要

James 不仅仅是多代理聊天 — 它是一个完整的研究操作系统：10+ 模型提供商、25+ 消息平台、60+ 内置工具、硬件外设控制（Arduino、STM32、树莓派）、神经科学脑编码模型（TRIBE v2）、知识图谱、语义记忆等。完整列表请参阅英文主页 [`README.md` - What It Does](README.md#what-it-does)。

## 适用人群

R.A.I.N. Lab 面向需要经得起推敲的答案的人，而不仅仅是听起来不错的答案。

| 角色 | 使用 R.A.I.N. Lab 可以做什么 |
| --- | --- |
| 创始人和产品负责人 | 在投入路线图或预算之前，通过结构化辩论压力测试战略决策 |
| 研究人员和分析师 | 对比竞争假设、保留分歧，并记录可审计的推理路径 |
| 运营和技术团队 | 将混乱的讨论转化为可验证的输出，便于审查、共享和重放 |

## 与其他工具的区别

| 典型研究工具 | R.A.I.N. Lab |
| --- | --- |
| 返回论文列表 | 返回一场辩论 |
| 把第一个看似合理的答案当作正确答案 | 保留分歧直到有证据能解决它 |
| 一个视角、一个模型 | 四种不同专业和约束的声音 |
| 云端优先 | 完全可以在本地运行 |

## 本地与私密工作流

R.A.I.N. Lab 可以完全在你自己的硬件上运行。通过 [LM Studio](https://lmstudio.ai/) 或 [Ollama](https://ollama.com/) 连接本地模型，无需任何云端调用、遥测或数据共享。

## 快速开始

**在线演示：** [rainlabteam.vercel.app](https://rainlabteam.vercel.app/) — 无需安装

```bash
python rain_lab.py
```

Windows 用户：双击 `INSTALL_RAIN.cmd`。
macOS/Linux 用户：运行 `./install.sh`。

更多命令与配置说明请参考文档中心与运行时参考文档。

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip
- Rust 工具链（可选，用于 ZeroClaw 运行时层）
- 通过 [LM Studio](https://lmstudio.ai/) 或 [Ollama](https://ollama.com/) 提供的本地模型（可选 — 演示模式无需模型）

## 文档

| | |
|---|---|
| **快速入门** | [从这里开始](START_HERE.md) -- [新手指南](docs/getting-started/README.md) -- [一键安装](docs/one-click-bootstrap.md) -- [故障排除](docs/troubleshooting.md) |
| **论文** | [研究档案](https://topherchris420.github.io/research/) |
| **其他语言** | [English](README.md) -- [日本語](README.ja.md) -- [Русский](README.ru.md) -- [Français](README.fr.md) -- [Tiếng Việt](README.vi.md) |

## 开发者

架构、扩展点及贡献说明请参阅英文 [`README.md` - For Developers](README.md#for-developers)，以及 [ARCHITECTURE.md](ARCHITECTURE.md) 和 [CLAUDE.md](CLAUDE.md)。

## 致谢

特别感谢 **ZeroClaw** 团队提供的 Rust 运行时引擎，它是 R.A.I.N. Lab 的底层核心。详见 `crates/` 目录。

---

**许可证：** MIT -- [Vers3Dynamics](https://vers3dynamics.com/)
