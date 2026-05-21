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

## archive 说明

`archive/generated_rounds/` 仅用于保留此前交付给你的历史生成稿、round 包和 zip 导出，
不作为现行正式引用面。


