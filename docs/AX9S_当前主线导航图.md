# AX9S 当前主线导航图

> 本文件是**纯导航图**，也是**候选导航资产**（candidate navigation asset），只负责阶段 1-9 的导航摘要。
> 本文件**非当前任务源**、**非状态源**、**非执行日志**、**非完整 backlog**。本文件不是状态源，也不是执行顺序源。
> `control/current_task.yaml` 负责 task packet / scoped subpacket 窗口的唯一**当前 active 执行任务**；普通 direct-dev 不要求先切换当前包。
> `control/product_task_library.yaml` 只负责下一候选来源。
> 本文件中的近端候选只作导航提示，不决定执行顺序。受控窗口的实际 active 包以 `control/current_task.yaml` 为准；候选池参考 `control/product_task_library.yaml`。
> `scripts/check-state-alignment.ps1` 只会对本文件第 3 节与 `product_task_library` 的近端偏移做轻机制提示；该同步策略是 `suggestion-only`，并保留 `manual_planning_review` 作为人工复核触发词；若明显落后，只给 `WARNING`，不阻断。
> 本文件不改写 `L0.md`、`裁决总表.md`、`D1-D14`、`contracts/*`、`handoff/*` 的正式语义。

## 1. 导航口径

- 本图承接 `PTL-I100-OPEN-CAPABILITY-BASELINE`：普通产品能力可按 direct-dev 或较大 grouped work batch 推进；live/external/release/机器契约窗口再进入受控 task packet；自动退款执行不实现。
- 关键历史同步锚点保留为：`PTL-I100-111F-open-capability-registry-route-doc-sync`、`PTL-I100-112-production-platform-infrastructure`、`PTL-I100-118R-final-product-operational-reacceptance`。
- `controlled-opening-required` 表示未通过 provider config、sandbox、approval、audit、operator action、field allowlist/masking、controlled-opening gate 与验收前不能 live，不表示永久不做。
- 招投标方向以 `docs/业务方向_候选公示后证据包与投前预测双线契约.md` 和 `contracts/evaluation/business_direction_strategy_contract.json` 为准：候选后证据包是核心商业主线，默认从近期 `07 中标候选人公示` 入池；投前预测只适用于近期 `02/03/04` 且投标截止/开标未过的项目；若出现 `05 开标信息`，投前预测即转开标后/候选后路线；下载解析前必须先生成 `AnalysisStrategyPlan v1`。
- 普通开发默认最小读序：`AGENTS.md` -> `专题_Stage1-7_缺口收口与优先级清单.md` -> `AX9S_Stage1-9_执行矩阵与子漏斗.md`；只有做 Stage4/5 时再读 `AX9S_Stage4-5_核验双闸门SOP.md`，只有做 Stage7 商业层时再读两份 SKU 专题。

## 2. 阶段主链

本节只告诉代理“该去哪里读”，不重复 L1 产品主图、L2 执行矩阵或 L3 SOP 的正文。阶段输入、输出、失败回退和验收细节分别以对应文档为准。

| Stage | 看哪份主文档 | Handoff | 当前导航候选 |
|---|---|---|---|
| Stage1 来源/候选池 | `docs/专题_Stage1-2_来源覆盖与采集路由.md`、`docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` | `handoff/stage1_to_stage2/contract.json` | `PTL-S12-source-route-clock-authority` |
| Stage2 公开采集/流程矩阵 | `docs/专题_Stage1-2_来源覆盖与采集路由.md`、`docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` | `handoff/stage2_to_stage3/contract.json` | `PTL-S23-public-chain-to-parser-contract` |
| Stage3 解析/字段血缘 | `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` | `handoff/stage3_to_stage4/contract.json` | `PTL-S34-object-lineage-verification-handoff` |
| Stage4 公开核验 | `docs/AX9S_Stage4-5_核验双闸门SOP.md` | `handoff/stage4_to_stage5/contract.json` | `PTL-S45-rule-evidence-dual-gate` |
| Stage5 规则证据双闸门 | `docs/AX9S_Stage4-5_核验双闸门SOP.md` | `handoff/stage5_to_stage6/contract.json` | `PTL-S45-rule-evidence-dual-gate` |
| Stage6 统一事实/报告 | `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` | `handoff/stage6_to_stage7/contract.json` | `PTL-S56-project-fact-review-report` |
| Stage7 商业承接 | `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`、D8/D10 | `handoff/stage7_to_stage8/contract.json` | `PTL-S7-price-competitor-offer-resolution` |
| Stage8 触达准备 | D9/D13 与自动化动作门禁 | `handoff/stage8_to_stage9/contract.json` | `PTL-S78-contact-candidate-compliance-preview` |
| Stage9 交付治理 | D10/D13 与自动化动作门禁 | 无 | `PTL-S89-outreach-writeback-delivery-governance` |

## 3. 近端导航提示

> 下列内容只作导航提示，不决定执行顺序，也不代表完整 backlog。受控窗口实际选包以 `control/current_task.yaml`、`control/product_task_library.yaml` 为准；普通 direct-dev 按 AGENTS 执行。

| 项 | 当前导航结论 |
|---|---|
| active packet | 无自动激活的产品主线包；普通开发按 direct-dev，受控/live/机器契约窗口再看 `control/current_task.yaml`。 |
| next candidate | 无自动 next candidate；后续按人类当前目标选择一个可验收闭环。 |
| 近期历史锚点 | `PTL-I100-127-owner-operator-frontend-and-customer-portal`、`PTL-I100-128-real-public-source-field-validation-and-coverage`、`PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund`、`PTL-I100-130-llm-assisted-parsing-review-and-sales-governance`、`PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout`、`PTL-I100-132-owner-operator-frontend-productization-workbench` 均已完成；132 已完成；后续 UI/工作台迭代不因历史受控任务记录而被强制小包。 |
| 当前能力背景 | `PTL-I100-143D-business-decision-architecture-and-hook-lead-roadmap-sync`、`PTL-I100-143E-autonomous-source-strategy-d-doc-sync`、`PTL-I100-144-market-scan-opportunity-discovery-engine`、`PTL-I100-145-source-blueprint-orchestration-and-capture-plan`、`PTL-I100-146-evidence-risk-and-hard-defect-verification-strategy`、`PTL-I100-147-commercial-value-buyer-fit-and-hook-lead-engine`、`PTL-I100-148-productized-autonomous-operator-workbench`、`PTL-I100-149-real-sample-autonomous-opportunity-acceptance`，以及 `PTL-I100-150-public-web-adaptive-capture-hardening-and-failure-escalation`、`PTL-I100-151-public-web-captcha-automated-resolution-and-resume` 已作为历史能力背景保留；其中 `143E` 继续约束“全国聚合平台只作为一级发现，北京不进入首批商业线索试点”，`150` 对应“公开网抓取失败自动升级”，`151` 对应验证码/挑战自动续跑。 |
| 历史详单 | 历史 PTL 顺序、完成态和 committed refs 以 `control/product_task_library.yaml`、`control/product_module_registry.yaml` 和 `archive/non_current_docs/*` 为准；本导航图不再维护长历史清单。 |

主线闭合提示：本文件仍只提供近端导航提示；不提供状态源、执行顺序源、完整 backlog 或 release 放行。`external release`、`Stage 8 real execution`、`Stage 9 real payment / delivery / refund` 受控开放要求不变；controlled-opening-required 只表示受控开放条件未满足前不能 live，不表示真实触达、支付或交付永久不做。自动退款执行不实现。
