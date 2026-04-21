# 《AX9S 开发执行路由图（阶段 1-9 版本）》

> 本文件是**纯导航图**，也是**候选导航资产**（candidate navigation asset），只负责阶段 1-9 的导航摘要。  
> 本文件**非当前任务源**、**非状态源**、**非执行日志**、**非完整 backlog**。  
> `control/current_task.yaml` 负责唯一**当前 active 执行任务**，是唯一 active task source。  
> `control/product_task_library.yaml` 只负责下一候选来源。  
> 本文件中的近端候选只作导航提示，不决定执行顺序。实际 active 包以 `control/current_task.yaml` 为准；候选池参考 `control/product_task_library.yaml`。  
> `scripts/check-state-alignment.ps1` 只会对本文件第 3 节与 `product_task_library` 的近端偏移做轻机制提示；若明显落后，只给 `WARNING`，不阻断。  
> 当 `product_task_completed`、`product_task_blocked`、`product_task_inserted_or_reordered`、`route_map_changed`、`L0_or_D_doc_semantic_change`、`release_or_regression_gap_confirmed`、`every_3_product_tasks_completed`、`manual_planning_review` 这些事件发生时，应主动运行 `scripts/check-state-alignment.ps1` 复核是否需要更新本文件第 3 节的近端导航提示。  
> 本文件不改写 `L0.md`、`裁决总表.md`、`D1-D14`、`contracts/*`、`handoff/*` 的正式语义。

## 1. 导航口径

- 本图只表达阶段 1-9 主链该如何理解、上下游怎么衔接、每阶段消费什么和产出什么。
- 本图不表达当前 phase/readiness 数值快照，不替代 `control/repo_status.md`、`control/milestone_status.yaml`。
- 本图不放开 `external release`，不放开 `Stage 8 real execution`，不放开 `Stage 9 real payment / delivery / refund`。
- 各阶段保留 1 个最贴近的导航候选 `packet_id`；更集中的近端候选提示统一放在第 3 节。

## 1.1 现实对齐说明

- 本仓库当前不是“从零补 skeleton”的起点，而是已经存在 Stage1-9 的 internal governed runtime。
- Stage1-5 当前代码现状统一按 `PARTIAL_RUNTIME` 理解；Stage6-9 当前代码现状统一按 `HEAVY_RUNTIME` 理解；`PTL-INT` 仍是 `PARTIAL_RUNTIME` 的内部消费封装。
- Stage8 / Stage9 的现状是 internal governed runtime，不是 live execution；`external release`、`Stage 8 real execution`、`Stage 9 real payment / delivery / refund` 继续保持 blocked / governed / approval-gated。
- 当前 active packet 以 `control/current_task.yaml` 为准；当前 active packet 为 `PTL-GOV-105-mainline-candidate-shift`；`PTL-S23-public-chain-to-parser-contract` 是 `current_mainline_next_candidate`，不是自动激活的当前执行包。
- `PTL-S12-source-route-clock-authority` scoped-execution 已完成并 closeout；它不再是 current active packet，也不再是 current_mainline_next_candidate。
- `control/product_task_library.yaml` 只提供候选池；`current_mainline_next_candidate` 不决定当前执行顺序。
- 路线图中的近端提示只说明“当前最值得查看和对齐的主线位置”，不等于“这些阶段还没有任何 runtime”。
- 近端提示应同时参考 `control/product_task_library.yaml` 的主线顺序、`control/current_task.yaml` 的当前窗口，以及各任务的 `existing_code_state`；不得脱离现状把近端导航误读成 zero-to-one 开发路线。

## 2. 阶段主链

## 2.1 Stage 1 任务编排与来源/路由治理

- 阶段目标：确定任务入口、来源族、路由策略、默认路由与 fallback 路由，为公开链采集建立唯一上游 authority。
- 正式输入：`task_record`、`task_execution_context`、来源族与路由策略输入。
- 正式输出：`task_execution_context`、`project_identity_strategy`、`clock_strategy_profile`、`execution_context`、`review_lane`、`source_registry_id`、`route_policy_id`、`default_route`、`fallback_route`。
- 上游 handoff：无，主链起点。
- 下游 handoff：`handoff/stage1_to_stage2/contract.json`
- 正式边界：只负责来源 authority 与路由 authority；不直接生成客户可见结论，不把自身写成状态源。
- 相关 contracts / tests：`contracts/governance/source_registry.json`；`contracts/governance/route_policy_catalog.json`；`contracts/governance/stage12_extractor_contract.json`；`tests/test_stage12_extractors.py`
- 导航候选 `task_id`：`PTL-S12-source-route-clock-authority`

## 2.2 Stage 2 公开链采集、窗口期、版本/时钟裁决

- 阶段目标：把采集结果固化为可回链的公开链、版本链、时钟链与固定件，为后续解析和核验提供唯一事实入口。
- 正式输入：`task_execution_context`、`project_identity_strategy`、`clock_strategy_profile`、`execution_context` 以及采集载体、窗口期与版本链规则。
- 正式输出：`public_chain`、`notice_version_chain`、`clock_chain_profile`、`fixation_bundle`。
- 上游 handoff：`handoff/stage1_to_stage2/contract.json`
- 下游 handoff：`handoff/stage2_to_stage3/contract.json`
- 正式边界：只形成可回链公开链、版本链与时钟链；不覆盖 Stage 1 authority，不直接产出客户可见结论。
- 相关 contracts / tests：`contracts/schemas/public_chain.schema.json`；`contracts/schemas/notice_version_chain.schema.json`；`contracts/schemas/clock_chain_profile.schema.json`；`tests/test_stage12_extractors.py`
- 导航候选 `task_id`：`PTL-S23-public-chain-to-parser-contract`

## 2.3 Stage 3 结构化解析与关键对象抽取

- 阶段目标：把公开链内容转成可消费的结构化对象，并保留字段来源链与对象归一基础。
- 正式输入：`public_chain`、`notice_version_chain`、`clock_chain_profile`、`fixation_bundle`。
- 正式输出：`project_base`、`field_lineage_record`、`bidder_candidate`、`project_manager`。
- 上游 handoff：`handoff/stage2_to_stage3/contract.json`
- 下游 handoff：`handoff/stage3_to_stage4/contract.json`
- 正式边界：只负责结构化解析与 lineage 固化；不新造第二套对象体系，不绕过 lineage 直接供页面或销售消费。
- 相关 contracts / tests：`contracts/schemas/project_base.schema.json`；`contracts/schemas/field_lineage_record.schema.json`；`contracts/schemas/bidder_candidate.schema.json`；`contracts/schemas/project_manager.schema.json`；`tests/test_internal_chain.py`
- 导航候选 `task_id`：`PTL-S34-object-lineage-verification-handoff`

## 2.4 Stage 4 关键对象定向公开核验与冲突预判

- 阶段目标：围绕关键对象完成公开核验、冲突识别、攻击面整理与核验画像形成。
- 正式输入：`project_base`、`field_lineage_record`、`bidder_candidate`、`project_manager`。
- 正式输出：`public_attack_surface`、`focus_bidder_verification_profile`、`pseudo_competitor_signal_set`、`evidence_grade_profile`。
- 上游 handoff：`handoff/stage3_to_stage4/contract.json`
- 下游 handoff：`handoff/stage4_to_stage5/contract.json`
- 正式边界：只负责公开核验、冲突预判与核验画像；不直接生成商业对象，不绕开 Stage 5 双闸门。
- 相关 contracts / tests：`contracts/schemas/public_attack_surface.schema.json`；`contracts/schemas/focus_bidder_verification_profile.schema.json`；`contracts/schemas/pseudo_competitor_signal_set.schema.json`；`contracts/schemas/evidence_grade_profile.schema.json`；`tests/test_internal_chain.py`
- 导航候选 `task_id`：`PTL-S45-rule-evidence-dual-gate`

## 2.5 Stage 5 规则与证据双闸门

- 阶段目标：把规则命中与证据可见性收口为统一双闸门，决定结果是升级、降级还是转复核。
- 正式输入：`public_attack_surface`、`focus_bidder_verification_profile`、`pseudo_competitor_signal_set`、`evidence_grade_profile` 以及规则目录、证据对象与治理约束。
- 正式输出：`rule_hit`、`evidence`、`rule_gate_decision`、`evidence_gate_decision`、`review_request`。
- 上游 handoff：`handoff/stage4_to_stage5/contract.json`
- 下游 handoff：`handoff/stage5_to_stage6/contract.json`
- 正式边界：必须保持双闸门共同成立；不得把截图、OCR 或模型摘要写成唯一主证，不得跳过复核请求。
- 相关 contracts / tests：`contracts/schemas/rule_gate_decision.schema.json`；`contracts/schemas/evidence_gate_decision.schema.json`；`contracts/testing/golden_cases.json`；`tests/test_stage56_evaluators.py`
- 导航候选 `task_id`：`PTL-S45-rule-evidence-dual-gate`

## 2.6 Stage 6 人工复核、统一事实、真实竞争者识别与正式报告

- 阶段目标：把前五阶段结果汇聚为唯一统一事实中枢，并形成复核队列、真实竞争者画像与正式报告对象。
- 正式输入：`rule_hit`、`evidence`、`rule_gate_decision`、`evidence_gate_decision`、`review_request`、人工复核结果与治理状态。
- 正式输出：`project_fact`、`legal_action_recommendation`、`review_queue_profile`、`challenger_candidate_profile`、`report_record`。
- 上游 handoff：`handoff/stage5_to_stage6/contract.json`
- 下游 handoff：`handoff/stage6_to_stage7/contract.json`
- 正式边界：`project_fact` 是唯一统一事实中枢；Stage 6 不写成状态源，Stage 7 也不得反向成为统一事实来源。
- 相关 contracts / tests：`contracts/schemas/project_fact.schema.json`；`contracts/schemas/review_queue_profile.schema.json`；`contracts/schemas/report_record.schema.json`；`tests/test_stage56_evaluators.py`
- 导航候选 `task_id`：`PTL-S56-project-fact-review-report`

## 2.7 Stage 7 商业承接与可售对象

- 阶段目标：在不突破统一事实边界的前提下，形成可售机会、买方匹配、行动主体与推荐方案。
- 正式输入：`project_fact`、`legal_action_recommendation`、`review_queue_profile`、`challenger_candidate_profile`、`report_record`。
- 正式输出：`multi_competitor_collection`、`legal_action_actor_profile`、`procurement_decision_actor_profile`、`buyer_fit`、`challenger_buyer_fit`、`offer_recommendation`、`sales_lead`、`saleable_opportunity`。
- 上游 handoff：`handoff/stage6_to_stage7/contract.json`
- 下游 handoff：`handoff/stage7_to_stage8/contract.json`
- 正式边界：只允许消费 Stage 6 正式对象形成商业对象；不得越过 `project_fact` 直接生成机会，不得把推荐面写成对外 release。
- 相关 contracts / tests：`contracts/sales/buyer_fit_scorecard.json`；`contracts/sales/lead_value_scoring_catalog.json`；`contracts/sales/price_normalization_catalog.json`；`contracts/schemas/saleable_opportunity.schema.json`；`contracts/schemas/sales_lead.schema.json`；`contracts/schemas/schema_catalog.json`；`tests/test_stage7_runtime_closure.py`
- 导航候选 `task_id`：`PTL-S7-price-competitor-offer-resolution`

## 2.8 Stage 8 联系对象与销售触达编排

- 阶段目标：在 governed internal 边界内形成联系人、触达计划与触达记录，并保持 candidate 与 execution 语义分层。
- 正式输入：`sales_lead`、`saleable_opportunity`、`multi_competitor_collection`、`legal_action_actor_profile`、`procurement_decision_actor_profile`、`buyer_fit`、`challenger_buyer_fit`、`offer_recommendation` 以及联系来源策略、合规矩阵与 cadence 规则。
- 正式输出：`contact_candidate_collection`、`contact_selection_trace`、`contact_target`、`outreach_plan`、`touch_record`。
- 上游 handoff：`handoff/stage7_to_stage8/contract.json`
- 下游 handoff：`handoff/stage8_to_stage9/contract.json`
- 正式边界：只允许在 governed internal 边界内形成 candidate、selection、plan 与 touch 记录；不放开 real execution，不直接外发高限制字段。
- 相关 contracts / tests：`contracts/sales/contact_compliance_matrix.json`；`contracts/sales/contact_source_policy_catalog.json`；`contracts/sales/outreach_cadence_catalog.json`；`contracts/schemas/contact_candidate_collection.schema.json`；`contracts/schemas/contact_selection_trace.schema.json`；`tests/test_stage8_resolution_closure.py`
- 导航候选 `task_id`：`PTL-S78-contact-candidate-compliance-preview`

## 2.9 Stage 9 订单、支付、交付与治理反馈

- 阶段目标：在 internal governed 边界内形成订单、支付、交付、结果事件与治理反馈回写闭环。
- 正式输入：`contact_target`、`outreach_plan`、`touch_record`、`saleable_opportunity` 与 Stage 8/9 handoff。
- 正式输出：`order_record`、`payment_record`、`delivery_record`、`opportunity_outcome_event`、`governance_feedback_event`。
- 上游 handoff：`handoff/stage8_to_stage9/contract.json`
- 下游 handoff：无，主链终点。
- 正式边界：只允许 internal preview / governed writeback；不放开 real payment / delivery / refund，不把 projected mutation 写成默认持久化执行。
- 相关 contracts / tests：`contracts/governance/writeback_impact_policy.json`；`contracts/sales/outcome_taxonomy_catalog.json`；`contracts/schemas/delivery_record.schema.json`；`tests/test_stage9_impact_executor.py`
- 导航候选 `task_id`：`PTL-S89-outreach-writeback-delivery-governance`

## 3. 近端导航提示

> 下列候选仅作“下一步可能去哪里看”的导航提示。  
> 它们不是当前任务源，不决定执行顺序，也不代表完整 backlog。实际选包以 `control/current_task.yaml`、`control/product_task_library.yaml` 为准。  
> 近端提示应同时结合 `product_task_library` 的任务顺序、`current_task` 当前窗口与对应任务的 `existing_code_state`。  
> `scripts/check-state-alignment.ps1` 会把本节近端候选与 `control/product_task_library.yaml` 当前任务池做轻量对照；若明显落后，只给 `WARNING` 提示，不阻断。
> 同步触发采用 suggestion-only：脚本只提示“应复核近端候选”，不自动修改路线图正文，也不让 `check-final-gate` 因近端候选滞后而失败。

- `PTL-S23-public-chain-to-parser-contract`：current_mainline_next_candidate；这里只提示 Stage2-3 公开链到结构化解析输入闭合的近端导航位置，不自动激活为当前执行包。
- `PTL-S34-object-lineage-verification-handoff`：最贴近 Stage3-4 对象 lineage 与公开核验移交闭合。
- `PTL-S45-rule-evidence-dual-gate`：最贴近 Stage4-5 规则与证据双闸门闭合。
- `PTL-S56-project-fact-review-report`：最贴近统一事实、复核队列与报告闭合。
- `PTL-S67-saleable-opportunity-derivation`：最贴近 Stage6-7 可售机会对象推导闭合。

