# ARCHITECTURE NOTE

本文件只保留架构补充说明，不作为日常入口。普通开发先看 `START_HERE.md`。

## 当前原则

- `scripts/*.ps1` 是薄入口和运维按钮，不是状态机本体。
- 正式自动化入口登记在 `control/automation_entrypoint_registry.yaml`。
- 业务状态机、证据门、匹配门、调度和投影逻辑应落在 `src/`、`contracts/`、`handoff/`、`control/`。
- 普通 direct-dev 不要求先切 `control/current_task.yaml`。
- 当前没有 `control/product_runtime_agent_registry.yaml`；除非先明确建立，否则不要把它当成必须维护的状态源。

更多路线和执行方式见 `START_HERE.md`、`DEV_MODE.md`、`MINIMAL_PRODUCT_PATH.md`。
