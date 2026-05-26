# 标准仓库总包

本仓库服务于**真实公开市场机会发现 + 证据包商业化的运营系统**。目标是从真实公开来源发现项目候选，完成候选解析、证据核验、商业价值判断、证据包生成和销售推进。

## 新手入口

普通开发先看 [`START_HERE.md`](START_HERE.md)、[`DEV_MODE.md`](DEV_MODE.md) 和 [`MINIMAL_PRODUCT_PATH.md`](MINIMAL_PRODUCT_PATH.md)。这三个文件解释轻量开发、`DEV_MODE / TEST_MODE / PROD_LIVE_MODE` 边界，以及下一步怎样先做出最小产品。

默认不要遍历 `docs/` 全部文件。普通开发、补功能、修 bug 或跑验证，先读：

1. `START_HERE.md`
2. `DEV_MODE.md`
3. `MINIMAL_PRODUCT_PATH.md`
4. `AGENTS.md`
5. 当前要改的 `src/`、`tests/`、`scripts/` 文件

只有改正式对象、规则、字段、交付、发布、模型、公开边界时，才按需读取 `docs/L0.md`、`docs/裁决总表.md` 和相关 D 文档。

## 顶层目录

- `docs/`：正式文档、专题说明、状态板和体检报告。
- `contracts/`：机器契约。
- `handoff/`：stage handoff 机器资产。
- `scripts/`：薄入口/运维按钮；脚本不是状态机本体。
- `control/`：状态、入口登记、任务库、审批/例外/引用索引。
- `archive/`：历史生成稿和迁移说明，不作为当前默认入口。

## 当前业务摘要

- 核心商业主线是候选公示后证据包；投前预测是辅助线。
- 默认从工作日 72 小时内的近期 `07 中标候选人公示` 入池。
- 投前预测只用于近期 `02/03/04` 且投标截止/开标未过；一旦出现 `05 开标信息`，投前预测已经来不及，必须转开标后/候选后路线。
- 近期 `07` 项目缺 11/12 不阻断当前证据包销售窗口。
- 下载和解析前先做 `AnalysisStrategyPlan v1`。
- 候选后负责人核验先走 `ResponsiblePersonEarlyProbe v1`：多候选人、联合体按候选行绑定；缺证书号先公司优先补证，再姓名枚举兜底；`08` 不默认下载或解析。
- 公开注册信息只能表述匹配/不匹配，不能判断“是不是本人”。
- 广东/重点省份核验按 `GuangdongLocalVerificationProbe v1` 和 `MajorRegionQueryProbe v1` 收口；重点省份为浙江、四川、江苏、湖北、山东、湖南、河南，默认 `PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED`。
- 负责人未释放宽筛按 `PRIOR_AWARD_AND_CANDIDATE_OVERLAP_TRIAGE`：先查 `data.ggzy.gov.cn` 和 `bid_show`，再按命中地区定向补证，不默认全省施工许可、竣工、合同备案全量扫描。
- 项目负责人未释放 / 在建履约冲突只能形成线索和证据不足说明，不得直接写“无在建”或“无风险”。

方向契约：`docs/业务方向_候选公示后证据包与投前预测双线契约.md`。机器契约：`contracts/evaluation/business_direction_strategy_contract.json`。

原“专题_SKU重构收口清单.md”已退出现行引用面；历史内容并入 `docs/专题_SKU分层与分类裁决.md`。

## 自动化入口

正式自动化入口登记在 `control/automation_entrypoint_registry.yaml`，并由 `scripts/audit-automation-entrypoints.ps1` 审计。`scripts/*.ps1` 只负责设置路径、环境变量和调用 Python 模块；业务状态机、证据门、匹配门、调度和投影逻辑应落在 `src/`、`contracts/`、`handoff/`、`control/`。

Stage1-6 direct-dev 当前 focus 以 `control/stage1_6_priority_execution_plan.yaml#current_focus` 为准。当前 Stage1-6/P0 正式入口包括：`stage1_6_real_public_pressure_runner`、`stage4_release_evidence_bridge_builder`、`guangdong_local_field_query_probe`、`guangdong_gdcic_openplatform_query_probe`、`stage6_review_cycle_runner`、`stage16_p13b_continuation_runner`。

当前仓库没有 `control/product_runtime_agent_registry.yaml`；新增 runtime 单元时，先使用现有 registry 和 module/control 资产。

授权/登录态缺失按现有契约表达；若顶层状态枚举没有 `NEEDS_AUTH`，使用 `BLOCKED` / `NEEDS_BROWSER` 加 `authorization_readiness_state=LOGIN_OR_SSO_REQUIRED` 和 `operator_next_action`，不要为了口号新增 enum。

## 本地验证

默认 direct-dev、`unittest`、脚本回归都走 `json-file`，不要依赖当前 shell 里遗留的 `KAKA_STORAGE_DATABASE_URL`。

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/invoke-local-json-test-env.ps1 python -m unittest <相关测试> -v
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/audit-automation-entrypoints.ps1
```

只有需要正式契约同步时再跑：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/validate-contracts.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-state-alignment.ps1
```
