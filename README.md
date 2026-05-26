# kaka

真实公开市场机会发现与候选公示后证据包商业化系统。

## 日常入口

- [`START_HERE.md`](START_HERE.md)：新手和 AI 代理先从这里开始。
- [`DEV_MODE.md`](DEV_MODE.md)：开发、测试、sandbox、dry-run、pilot 与生产 live 的边界。
- [`MINIMAL_PRODUCT_PATH.md`](MINIMAL_PRODUCT_PATH.md)：先做出最小可用产品的路线。
- [`AGENTS.md`](AGENTS.md)：AI 代理默认工作规则。

默认不要遍历完整 `docs/`。普通开发、补功能、修 bug 或跑验证，先读上面几个入口和当前要改的代码/测试。

## 目录

- `src/`：核心实现。
- `tests/`：单元测试、契约测试和回归测试。
- `scripts/`：本地命令入口和运维按钮；脚本不是状态机本体。
- `docs/`：正式文档、专题说明和状态板。
- `contracts/`：机器契约。
- `control/`：任务、状态、门禁、入口登记和审计资产。
- `handoff/`：阶段间 handoff 机器资产。
- `fixtures/`：样本数据。
- `archive/`：历史稿，不作为默认入口。

## 自动化短指针

- 正式自动化入口登记在 `control/automation_entrypoint_registry.yaml`。
- Stage1-6 direct-dev 当前 focus 以 `control/stage1_6_priority_execution_plan.yaml#current_focus` 为准。
- Stage1-6/P0 常用入口：`stage1_6_real_public_pressure_runner`、`stage4_release_evidence_bridge_builder`、`stage6_review_cycle_runner`。
- 授权/登录态缺失：若顶层没有 `NEEDS_AUTH` 枚举，用 `BLOCKED` / `NEEDS_BROWSER` 加 `authorization_readiness_state=LOGIN_OR_SSO_REQUIRED` 和 `operator_next_action` 表达。

## 本地验证

默认用隔离的 json-file 测试环境，避免被本机数据库环境变量污染：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/invoke-local-json-test-env.ps1 python -m unittest <相关测试> -v
```

只有改了 contracts/control/docs 同步语义时再跑：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/validate-contracts.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-state-alignment.ps1
```
