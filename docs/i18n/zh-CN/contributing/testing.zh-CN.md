# 测试指南

R.A.I.N. 采用基于文件系统组织的五级 Rust 测试分类体系，且必经质量门禁现在通过同一个入口同时校验 Python 与 Web 表面。

## 规范验证入口

如果希望在本地运行与 GitHub Actions 相同的验证类别，请使用以下命令：

```bash
# GitHub Actions 使用的原生质量门禁
bash scripts/ci/quality_gate.sh all

# 面向本地贡献者的可发现 Docker 包装命令
./dev/ci.sh all
```

规范门禁拆分为以下类别：

| 类别 | 执行内容 |
|---|---|
| `rust` | `cargo fmt --all -- --check`、`cargo clippy --locked --all-targets -- -D warnings`、`cargo nextest run --locked`、`cargo check --all-features --locked`、`cargo build --profile ci --locked` |
| `python` | 安装 Python 依赖、`ruff check . --output-format=full`、`pytest tests -v -ra --tb=long`，以及在存在 `python/R.A.I.N._tools` 时运行 `python/tests` |
| `web` | `npm ci --prefix web`、可选的 `npm run lint --prefix web`、可选的 `npm run test --prefix web`、`npm run build --prefix web` |
| `governance` | 当变更文件触发时，运行文档导航一致性、架构边界与 Markdown 质量检查 |

你可以直接运行 `bash scripts/ci/quality_gate.sh <category>` 执行单个类别，也可以通过 `./dev/ci.sh <category>` 在 Docker 中执行。

## Rust 测试分类

| 级别 | 测试内容 | 外部边界 | 目录 |
|-------|--------------|-------------------|-----------|
| **单元（Unit）** | 单个函数/结构体 | 所有内容都被模拟 | `src/**/*.rs` 中的 `#[cfg(test)]` 块，或独立的 `src/**/tests.rs` 文件 |
| **组件（Component）** | 边界内的单个子系统 | 子系统为真实实现，其他所有内容被模拟 | `tests/component/` |
| **集成（Integration）** | 多个内部组件组合在一起 | 内部为真实实现，外部 API 被模拟 | `tests/integration/` |
| **系统（System）** | 跨所有内部边界的完整请求→响应流程 | 仅外部 API 被模拟 | `tests/system/` |
| **实时（Live）** | 使用真实外部服务的完整栈 | 无模拟，标记为 `#[ignore]` | `tests/live/` |

## 目录结构

| 目录 | 级别 | 描述 | 运行命令 |
|-----------|-------|-------------|-------------|
| `src/**/*.rs` | 单元 | 与源代码共存的 `#[cfg(test)]` 块或独立的 `tests.rs` 文件 | `cargo test --lib` |
| `tests/component/` | 组件 | 单个子系统，真实实现，边界被模拟 | `cargo test --test component` |
| `tests/integration/` | 集成 | 多个组件组合在一起 | `cargo test --test integration` |
| `tests/system/` | 系统 | 完整的渠道→代理→渠道流程 | `cargo test --test system` |
| `tests/live/` | 实时 | 真实外部服务，标记为 `#[ignore]` | `cargo test --test live -- --ignored` |
| `tests/manual/` | — | 人工驱动的测试脚本（shell、Python） | 直接运行 |
| `tests/support/` | — | 共享模拟基础设施（非测试二进制文件） | — |
| `tests/fixtures/` | — | 测试数据文件（JSON 追踪、媒体文件） | — |
| `python/tests/` | Python | 当存在 `python/R.A.I.N._tools` 时，对 `R.A.I.N.-tools` 伴生包进行覆盖 | `cd python && pytest tests -v -ra --tb=long` |
| `web/` | Web | 前端构建验证 | `npm ci --prefix web && npm run build --prefix web` |

## 如何运行检查

```bash
# 运行与 GitHub Actions 等价的完整原生门禁
bash scripts/ci/quality_gate.sh all

# 在本地 CI 容器中运行同一门禁
./dev/ci.sh all

# 仅运行 CI 使用的 Rust 门禁
bash scripts/ci/quality_gate.sh rust

# 仅运行 CI 使用的 Python 门禁
bash scripts/ci/quality_gate.sh python

# 仅运行 CI 使用的 Web 门禁
bash scripts/ci/quality_gate.sh web

# 仅运行 CI 使用的治理/文档门禁
bash scripts/ci/quality_gate.sh governance

# 运行所有 Rust 测试（单元 + 组件 + 集成 + 系统）
cargo test

# 仅运行单元测试
cargo test --lib

# 运行组件测试
cargo test --test component

# 运行集成测试
cargo test --test integration

# 运行系统测试
cargo test --test system

# 运行实时测试（需要 API 凭证）
cargo test --test live -- --ignored

# 在某个级别内过滤测试
cargo test --test integration agent
```

## 如何添加新测试

1. **测试单个隔离的子系统？** → `tests/component/`
2. **测试多个组件协同工作？** → `tests/integration/`
3. **测试完整消息流程？** → `tests/system/`
4. **需要真实 API 密钥？** → `tests/live/` 并标记为 `#[ignore]`
5. **测试 Python 伴生包？** → 在 `python/R.A.I.N._tools` 下添加源码，并在 `python/tests/` 中补充覆盖。
6. **测试 Web UI？** → 在 `web/package.json` 中添加或更新脚本，使 `web` 质量门禁自动拾取。

创建测试文件后，将其添加到对应的 `mod.rs` 中，并使用 `tests/support/` 中的共享基础设施。

## 共享基础设施（`tests/support/`）

所有测试二进制文件都包含 `mod support;`，可以通过 `crate::support::*` 访问共享模拟。

| 模块 | 内容 |
|--------|----------|
| `mock_provider.rs` | `MockProvider`（FIFO 脚本化）、`RecordingProvider`（捕获请求）、`TraceLlmProvider`（JSON 夹具重放） |
| `mock_tools.rs` | `EchoTool`、`CountingTool`、`FailingTool`、`RecordingTool` |
| `mock_channel.rs` | `TestChannel`（捕获发送内容、记录输入事件） |
| `helpers.rs` | `make_memory()`、`make_observer()`、`build_agent()`、`text_response()`、`tool_response()`、`StaticMemoryLoader` |
| `trace.rs` | `LlmTrace`、`TraceTurn`、`TraceStep` 类型 + `LlmTrace::from_file()` |
| `assertions.rs` | 用于声明式追踪断言的 `verify_expects()` |

### 用法

```rust
use crate::support::{MockProvider, EchoTool, CountingTool};
use crate::support::helpers::{build_agent, text_response, tool_response};
```

## JSON 追踪测试夹具

追踪夹具是存储在 `tests/fixtures/traces/` 中的 JSON 文件格式 LLM 响应脚本。它们用声明式对话脚本替代了内联模拟设置。

### 工作原理

1. `TraceLlmProvider` 加载夹具并实现 `Provider` 特征
2. 每个 `provider.chat()` 调用按 FIFO 顺序返回夹具中的下一步
3. 真实工具正常执行（例如 `EchoTool` 处理参数）
4. 所有轮次结束后，`verify_expects()` 检查声明式断言
5. 如果代理调用提供商的次数超过步骤数，测试失败

### 夹具格式

```json
{
  "model_name": "test-name",
  "turns": [
    {
      "user_input": "User message",
      "steps": [
        {
          "response": {
            "type": "text",
            "content": "LLM response",
            "input_tokens": 20,
            "output_tokens": 10
          }
        }
      ]
    }
  ],
  "expects": {
    "response_contains": ["expected text"],
    "tools_used": ["echo"],
    "max_tool_calls": 1
  }
}
```

**响应类型：** `"text"`（纯文本）或 `"tool_calls"`（LLM 请求工具执行）。

**期望字段：** `response_contains`、`response_not_contains`、`tools_used`、`tools_not_used`、`max_tool_calls`、`all_tools_succeeded`、`response_matches`（正则表达式）。

## 实时测试约定

- 所有实时测试必须标记为 `#[ignore]`
- 使用 `env::var("R.A.I.N._TEST_*")` 获取凭证
- 运行命令：`cargo test --test live -- --ignored --nocapture`

## 手动测试（`tests/manual/`）

无法通过 `cargo test` 自动化的人工驱动测试脚本：

| 目录/文件 | 作用 |
|---|---|
| `manual/telegram/` | Telegram 集成测试套件、冒烟测试、消息生成器 |
| `manual/test_dockerignore.sh` | 验证 `.dockerignore` 排除敏感路径 |

Telegram 特定的测试细节请参见 [testing-telegram.md](./testing-telegram.zh-CN.md)。
