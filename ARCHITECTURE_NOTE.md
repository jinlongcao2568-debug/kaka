# 标准仓库架构说明

本总包已经按统一正式路径整理完成。

## 现行正式路径

- `docs/L0.md`
- `docs/D1_研发_Codex执行手册.md` ~ `docs/D14_AI模型治理规范.md`
- `docs/裁决总表.md`
- `contracts/*`
- `handoff/*`
- `scripts/*`
- `control/*`

## 自动化入口原则

- `scripts/*.ps1` 是薄入口和运维按钮，不是状态机本体。
- 正式自动化入口统一登记在 `control/automation_entrypoint_registry.yaml`。
- 入口登记由 `scripts/audit-automation-entrypoints.ps1` 审计；审计通过后，系统才能明确哪些入口替代人工记忆、哪些只是诊断或辅助工具。
- 业务状态机、证据门、匹配门、调度和投影逻辑必须沉淀在 `src/`、`contracts/`、`handoff/`、`control/`，不能只散落在脚本名和会话记录里。
- 普通 direct-dev 下，如果 `control/current_task.yaml` 仍是已完成历史包，不得把它误当 active packet；Stage1-6 当前 focus 以 `control/stage1_6_priority_execution_plan.yaml#current_focus` 为准。
- Stage1-6/P0 自动化入口必须读取 `control/automation_entrypoint_registry.yaml` 的实际 `entrypoint_id`，不得用未登记的 `product_autonomous_*` 等概念名替代。
- 当前没有 `control/product_runtime_agent_registry.yaml`，也没有顶层 `NEEDS_AUTH` 强制枚举；对应能力应按现有 registry 和授权状态字段表达。

## archive 说明

`archive/generated_rounds/` 仅用于保留此前交付给你的历史生成稿、round 包和 zip 导出，
不作为现行正式引用面。


