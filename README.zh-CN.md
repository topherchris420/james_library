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

## James 的完整能力

James 不仅仅是多代理聊天 — 它是一个完整的研究操作系统：10+ 模型提供商、25+ 消息平台、60+ 内置工具、硬件外设控制（Arduino、STM32、树莓派）、神经科学脑编码模型（TRIBE v2）、知识图谱、语义记忆等。完整列表请参阅英文主页 [`README.md` - What You Can Do](README.md#what-you-can-do)。

## 适用人群

R.A.I.N. Lab 面向需要经得起推敲的答案的人，而不仅仅是听起来不错的答案。

| 角色 | 使用 R.A.I.N. Lab 可以做什么 |
| --- | --- |
| 创始人和产品负责人 | 在投入路线图或预算之前，通过结构化辩论压力测试战略决策 |
| 研究人员和分析师 | 对比竞争假设、保留分歧，并记录可审计的推理路径 |
| 运营和技术团队 | 将混乱的讨论转化为可验证的输出，便于审查、共享和重放 |

实际效果是减少"AI 说的"式的死胡同。你可以从一个问题出发，让多个代理挑战假设，将未解决的冲突路由到验证流程，最终得到一个可以自信地展示给他人的结果。

## 快速开始

```bash
python rain_lab.py
```

更多命令与配置说明请参考文档中心与运行时参考文档。

## 实际效果展示

提出一个原始的研究问题。观看四位专家代理 — James（首席科学家）、Jasmine（博士后质疑者）、Luca（几何学家）和 Elena（逻辑学家）— 实时辩论。

```
TOPIC: Could a "Phononic Morphogenetic Field" — precise acoustic interference patterns
guiding matter assembly like DNA guides cell growth — actually work?

**James:** ...phononic frequency combs could act like an acoustic blueprint for
molecular organization. The missing link between quantum coherence and biological
assembly?

**Jasmine:** Hold on. Cymatic patterns are *static* — they don't adapt to errors
or material changes the way DNA does. And the energy density needed exceeds
current acoustic levitation by *orders of magnitude*. Where's the thermal
dissipation analysis?

**Luca:** The geometry is compelling though. Wavelength spacing in phononic
combs (ωₙ₊₁ - ωₙ = 2πc/λ) parallels scalar field gradients in relic field
tomography. But macroscopic assembly requires E > 10⁴⁵ J — far beyond reach.

**Elena:** The math is elegant but the premise has a fatal flaw. The energy
density violates the Landauer limit by multiple orders of magnitude. Current
systems operate ~10³ times lower. Without experimental validation at that
scale, this remains speculation.

[Meeting continues — James responds, Jasmine pushes back, consensus forms...]
```

加入一场研究会议，探索分歧，带着下一步行动方案离开 — 而不仅仅是链接。

---

## 结果质量与可信性

### 结果质量（基准化）

R.A.I.N. Lab 在 CI 中持续跟踪工程质量，并公开指标定义、基线与目标（例如：panic 次数、unwrap 次数、测试波动率、关键路径覆盖率）。

- 质量指标契约：[`docs/project/quality-metrics.md`](docs/project/quality-metrics.md)
- 质量报告生成器：[`scripts/ci/quality_metrics_report.py`](scripts/ci/quality_metrics_report.py)

对于研究结果评估，我们建议同时发布可复现的前后对比评测产物（任务集、基线、评分标准、结果文件），并与上述质量报告一起提供。

### 可信 + 隐私说明

R.A.I.N. Lab 采用本地优先设计，并默认启用安全设置：

- 支持本地/私有工作流路径与本地模型路由选项
- 网关默认绑定 localhost，开启配对机制，并禁用公网绑定
- 渠道访问采用默认拒绝（deny-by-default）的 allowlist 策略
- 高价值密钥采用静态加密存储（encrypted-at-rest）

当前行为对应的安全文档：

- [`docs/security/README.md`](docs/security/README.md)
- [`docs/reference/api/config-reference.md`](docs/reference/api/config-reference.md)
