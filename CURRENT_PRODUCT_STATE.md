# CURRENT PRODUCT STATE

本文件是 2026-07-19 全面评审、连续修复和全量回归后的当前产品状态摘要。它只回答“现在开发到什么程度”，不作为新门禁。

## 审计证据

- 当前审计范围：`src/`、`tests/`、`scripts/`、`contracts/`、`control/`、`docs/`、`handoff/`、`fixtures/`、`migrations/`、容器/Compose、CI 和根入口文件。
- Python 测试规模：195 个测试文件、1962 个 `test*` 函数。
- 运行路由读回：FastAPI 当前挂载 72 条应用路由；业务操作登记读回为 66 个，其中 26 个写操作全部有请求体契约；另有内部登录页和浏览器 session 的 POST/GET/DELETE 共 4 条认证路由。
- 全量隔离回归：`python tests/run_tests.py` 通过 1943 个测试，跳过 9 个可选能力测试，失败 0。
- 关键相关回归：API 与 operator console 定向组合 37 项通过，另有 5 个 subtests；真实浏览器登录、异步读回、CSRF 写请求和退出流程通过。
- 容器实跑：默认 API 镜像以非 root 用户 `kaka` 运行；未认证页面跳转内部登录页，签名 `HttpOnly`/`SameSite=Strict` Cookie 可进入操作台，无 CSRF 写请求返回 403，退出后页面重新跳转登录；容器 `pip check` 通过。
- 依赖与静态检查：默认 API 镜像 `pip check` 通过；生产代码 E9、未定义符号和重复字典键检查通过。
- 契约与状态检查：`validate-contracts.ps1`、`check-state-alignment.ps1`、`docker compose config --quiet`、`git diff --check` 通过。

审计机器资产在 `tmp/full_product_audit/`，其中：

- `current_holographic_inventory.json`
- `current_runtime_route_readback.json`
- `current_product_degree_summary.json`

这些 2026-05-26 资产只保留为历史审计证据；当前数字以上述 2026-07-17 实际读回和回归结果为准，它们都不是产品运行状态源。

## 当前结论

当前仓库不是空架子。它已经有一条较重的内部 owner-operated 证据包 / 线索包产品链：

1. Stage1-6 已有内部编排、公开来源抓取/快照/解析/核验/规则/复核和证据包读回。
2. Stage7 已有可售机会、buyer fit、报价/CRM/LeadPack 候选和交付候选读回。
3. Stage8 已有联系人合规、触达 outbox、sandbox/provider readiness、审批审计和失败回放。
4. Stage9 已有订单、支付、交付、结果回写、治理反馈、退款异常和受控自动退款测试边界。
5. Operator console 和 customer artifact portal 已经存在，能展示 owner 工作台、客户 artifact 读回、下载门禁和运行投影。
6. 内部 HTTP API 已有服务端 bearer 鉴权；标准浏览器可用签名 `HttpOnly` 短时会话和 CSRF 进入 operator console，Bearer 不进入 URL 或浏览器存储；受控文件根、请求/响应契约和 Stage9 正式对象持久化已接入，请求布尔值不能冒充 operator 授权。
7. Worker 队列领取/审计提交已原子化，JSON 后端具备跨进程锁和写前重载；公共 URL 获取具备私网/重定向/子请求/响应体大小 fail-closed 边界。
8. PTL-I100-149 真实公开样本自主机会验收已完成，当前状态是 `READY_FOR_POST-REPAIR_MAINLINE_SELECTION`。

## 仍不能误写成已经完成的事

- 不能说已经开放 public software release。
- 不能说真实客户下载、真实触达、真实支付、真实交付、真实退款已经默认 live。
- 不能把 approved/live-pilot/readback 当成无门禁生产执行。
- 不能把内部 API 可运行、容器健康或鉴权通过写成 public software release / 客户可用。
- 不能把 `control/current_task.yaml` 当成当前 active packet；它现在是已完成历史 packet carrier。
- 不能把 Stage1-5 direct HTTP transport 当成已开放 live transport；当前正式入口仍是 Stage1-6 internal orchestration 和 operator surfaces。

## 开发程度判断

- 产品骨架：高完成度，已经不是“只写文档”。
- 内部 owner 操作闭环：可用，HTTP 与容器入口已经硬化，但仍以 governed/readback/approval/sandbox 为主。
- 自主机会发现到商业 hook：已完成真实样本验收，但仍需要继续做稳定性、样本覆盖、操作效率和真实运营硬化。
- 外部触达、支付、交付、退款：目标能力存在，测试态和受控试点可开发；生产 live 必须有授权、审批、审计、operator action、对账和回滚/暂停。
- 当前最现实的下一步：围绕 Stage1-6 当前 focus `P0_STAGE4_RELEASE_EVIDENCE_CHAIN` 和 owner console 的真实样本操作效率做小步功能开发；多实例持久运行优先采用已迁移 SQL 后端，不把 JSON 文件后端当成生产数据库。

## 入口使用建议

普通开发只需要：

1. 读 `START_HERE.md`、`DEV_MODE.md`、本文件和当前要改的代码/测试。
2. 按 `DEV_MODE` 做最小可运行改动。
3. 跑相关测试。
4. 只在改 contracts/control/docs 同步语义时跑正式状态检查。

不要因为仓库里存在大量历史 D 文档、task packet、review gate 或 release gate，就阻断普通功能开发。
