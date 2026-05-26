# CURRENT PRODUCT STATE

本文件是 2026-05-26 全息审计后的当前产品状态摘要。它只回答“现在开发到什么程度”，不作为新门禁。

## 审计证据

- 当前审计范围：`src/`、`tests/`、`scripts/`、`contracts/`、`control/`、`docs/`、`handoff/`、`fixtures/`、`migrations/` 和根入口文件。
- 机器逐行遍历结果：930 个文件，433181 行，19892717 bytes，读取错误 0。
- Python 代码规模：521 个 Python 文件，580 个 class，9567 个函数，其中 1924 个测试函数。
- 运行路由读回：FastAPI 当前挂载 63 条路由，其中 Stage6-9 transport operations 32 个，operator/customer access operations 22 个，operator frontend operations 8 个。
- 全量本地回归：`python tests/run_tests.py` 通过 1903 个测试，跳过 1 个可选 PostgreSQL 集成测试。
- 契约与状态检查：`validate-contracts.ps1`、`check-state-alignment.ps1`、`git diff --check` 通过。

审计机器资产在 `tmp/full_product_audit/`，其中：

- `current_holographic_inventory.json`
- `current_runtime_route_readback.json`
- `current_product_degree_summary.json`

这些资产用于证明文件遍历、路由读回和产品状态聚合；它们不是产品运行状态源。

## 当前结论

当前仓库不是空架子。它已经有一条较重的内部 owner-operated 证据包 / 线索包产品链：

1. Stage1-6 已有内部编排、公开来源抓取/快照/解析/核验/规则/复核和证据包读回。
2. Stage7 已有可售机会、buyer fit、报价/CRM/LeadPack 候选和交付候选读回。
3. Stage8 已有联系人合规、触达 outbox、sandbox/provider readiness、审批审计和失败回放。
4. Stage9 已有订单、支付、交付、结果回写、治理反馈、退款异常和受控自动退款测试边界。
5. Operator console 和 customer artifact portal 已经存在，能展示 owner 工作台、客户 artifact 读回、下载门禁和运行投影。
6. PTL-I100-149 真实公开样本自主机会验收已完成，当前状态是 `READY_FOR_POST-REPAIR_MAINLINE_SELECTION`。

## 仍不能误写成已经完成的事

- 不能说已经开放 public software release。
- 不能说真实客户下载、真实触达、真实支付、真实交付、真实退款已经默认 live。
- 不能把 approved/live-pilot/readback 当成无门禁生产执行。
- 不能把 `control/current_task.yaml` 当成当前 active packet；它现在是已完成历史 packet carrier。
- 不能把 Stage1-5 direct HTTP transport 当成已开放 live transport；当前正式入口仍是 Stage1-6 internal orchestration 和 operator surfaces。

## 开发程度判断

- 产品骨架：高完成度，已经不是“只写文档”。
- 内部 owner 操作闭环：可用，但仍以 governed/readback/approval/sandbox 为主。
- 自主机会发现到商业 hook：已完成真实样本验收，但仍需要继续做稳定性、样本覆盖、操作效率和真实运营硬化。
- 外部触达、支付、交付、退款：目标能力存在，测试态和受控试点可开发；生产 live 必须有授权、审批、审计、operator action、对账和回滚/暂停。
- 当前最现实的下一步：不要继续扩文档；围绕 Stage1-6 当前 focus `P0_STAGE4_RELEASE_EVIDENCE_CHAIN` 和 owner console 的真实样本操作效率做小步功能开发。

## 入口使用建议

普通开发只需要：

1. 读 `START_HERE.md`、`DEV_MODE.md`、本文件和当前要改的代码/测试。
2. 按 `DEV_MODE` 做最小可运行改动。
3. 跑相关测试。
4. 只在改 contracts/control/docs 同步语义时跑正式状态检查。

不要因为仓库里存在大量历史 D 文档、task packet、review gate 或 release gate，就阻断普通功能开发。
