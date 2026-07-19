# ARCHITECTURE NOTE

本文件只保留架构补充说明，不作为日常入口。普通开发先看 `START_HERE.md`。

## 当前原则

- `scripts/*.ps1` 是薄入口和运维按钮，不是状态机本体。
- 正式自动化入口登记在 `control/automation_entrypoint_registry.yaml`。
- 业务状态机、证据门、匹配门、调度和投影逻辑应落在 `src/`、`contracts/`、`handoff/`、`control/`。
- 普通 direct-dev 不要求先切 `control/current_task.yaml`。
- 当前没有 `control/product_runtime_agent_registry.yaml`；除非先明确建立，否则不要把它当成必须维护的状态源。

## 运行边界补充

- 内部 API 的网络边界是 bearer token；健康检查公开，其他路径在 token 未配置时 fail-closed。请求体中的布尔字段不能充当 operator 身份、审批或下载授权。
- Operator 文件路径只能落在 `KAKA_OPERATOR_INPUT_ROOT` / `KAKA_OPERATOR_ARTIFACT_ROOT` 控制的目录中；HTTP 请求不能指定任意宿主机路径。
- 公共 URL 读取在传输前拒绝私网、回环、链路本地、保留地址和非标准端口；重定向/浏览器子请求保持同主机，最终 URL 与响应大小在持久化前再次校验。
- Worker 队列状态变更和审计事件是一个原子提交；审计事件具有数据库唯一约束。JSON 文件后端通过跨进程锁和写前重载避免多 session 丢写，但生产多实例仍优先使用迁移后的 SQL 后端。
- HTTP 创建类接口必须先通过正式对象 Schema，再持久化并返回 created / idempotent replay 状态；preview 字样不能替代持久化语义。
- Docker/Compose 是本地可运行的内部 API 载体，不改变 `DEV_MODE.md` 中生产 live、真实触达、支付、交付和退款的门禁。

更多路线和执行方式见 `START_HERE.md`、`DEV_MODE.md`、`MINIMAL_PRODUCT_PATH.md`。
