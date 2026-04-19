# 《AX9S 开发执行路由图（阶段 1-9 版本）》

> 本文件是 **candidate navigation asset**，也是**候选导航资产**。  
> 本文件是主导航图，不是状态真源。  
> 本文件**非状态源**、**非裁决源**、**非执行日志**、**非完整 backlog**。  
> 主导航图负责指路；`control/task_packet_library.yaml` 负责候选任务；`control/current_task.yaml` 负责当前 active 执行任务；状态真源是 `control/repo_status.md` 与 `control/milestone_status.yaml`。  
> 本文件不以 `docs/AX9S_高+中任务包蓝图.md` 作为当前任务来源。

## 1. 使用规则

- 本图只表达正式阶段 1-9 主链该如何看、该往哪里走，不表达当前 phase/readiness 数值快照。
- 本图不改写 `L0.md`、`裁决总表.md`、`D1-D14`、`contracts/*`、`handoff/*` 的正式语义。
- 本图不放开 `external release`，不放开 `Stage 8 real execution`，不放开 `Stage 9 real payment / delivery / refund`。
- 本图中的近端候选 `packet_id` 只引用 `control/task_packet_library.yaml` 现有条目，不新造任务 ID。
- 本图中的“当前允许做什么 / 当前禁止做什么”只表达受控开发边界，不替代状态真源或审批结论。

## 2. 阶段主链

## 2.1 Stage 1 任务编排与来源/路由治理

- 阶段目标：确定任务入口、来源族、路由策略、默认路由与 fallback 路由，为公开链采集建立唯一上游 authority。
- 正式输入：`task_record`、`task_execution_context`、来源族与路由策略输入。
- 正式输出：`task_execution_context`、`review_lane`、`source_registry_id`、`route_policy_id`、`default_route`、`fallback_route`。
- 上游 handoff：无，主链起点。
- 下游 handoff：`handoff/stage1_to_stage2/contract.json`
- 当前允许做什么：只允许做来源 registry、route precedence、default/fallback route、validator 与 handoff 的受控收口。
- 当前禁止做什么：不得把外部 source live enable 写成默认开放；不得把 coverage 写成全国默认稳定；不得把本阶段写成状态源。
- 相关 contracts / tests：`contracts/governance/source_registry.json`；`contracts/governance/route_policy_catalog.json`；`contracts/governance/stage12_extractor_contract.json`；`tests/test_stage12_extractors.py`
- 近端候选 `packet_id`：`PKT-P1-01-stage12-rollout-precedence`

## 2.2 Stage 2 公开链采集、窗口期、版本/时钟裁决

- 阶段目标：把采集结果固化为可回链的公开链、版本链、时钟链与固定件，为后续解析和核验提供唯一事实入口。
- 正式输入：Stage 1 handoff 输出、采集载体、窗口期与版本链规则。
- 正式输出：`public_chain`、`notice_version_chain`、`clock_chain_profile`、`fixation_bundle`。
- 上游 handoff：`handoff/stage1_to_stage2/contract.json`
- 下游 handoff：`handoff/stage2_to_stage3/contract.json`
- 当前允许做什么：只允许做采集 authority、version/clock precedence、fixation 与 handoff 校验收口。
- 当前禁止做什么：不得让 raw payload 覆盖 Stage 1 authority；不得把采集结果包装为客户可见结论；不得默认放开真实外部源。
- 相关 contracts / tests：`contracts/schemas/public_chain.schema.json`；`contracts/schemas/notice_version_chain.schema.json`；`contracts/schemas/clock_chain_profile.schema.json`；`tests/test_stage12_extractors.py`
- 近端候选 `packet_id`：`PKT-P1-01-stage12-rollout-precedence`

## 2.3 Stage 3 结构化解析与关键对象抽取

- 阶段目标：把公开链内容转成可消费的结构化对象，并保留字段来源链与对象归一基础。
- 正式输入：`public_chain`、`notice_version_chain`、`clock_chain_profile`、`fixation_bundle`。
- 正式输出：`project_base`、`field_lineage_record` 以及后续核验所需的结构化抽取对象。
- 上游 handoff：`handoff/stage2_to_stage3/contract.json`
- 下游 handoff：`handoff/stage3_to_stage4/contract.json`
- 当前允许做什么：只允许做解析一致性、字段 lineage、schema 对齐与 handoff 完整性校验。
- 当前禁止做什么：不得新造第二套对象体系；不得跳过 lineage 直接供页面/销售消费；不得把解析层写成统一事实层。
- 相关 contracts / tests：`contracts/schemas/project_base.schema.json`；`contracts/schemas/field_lineage_record.schema.json`；`handoff/stage3_to_stage4/validator.json`；`tests/test_internal_chain.py`
- 近端候选 `packet_id`：`PKT-P1-01-stage12-rollout-precedence`、`PKT-P0-01-review-queue-window-scoring`

## 2.4 Stage 4 关键对象定向公开核验与冲突预判

- 阶段目标：围绕关键对象完成公开核验、冲突识别、攻击面整理与核验画像形成。
- 正式输入：`project_base`、`field_lineage_record` 与 Stage 3 抽取对象。
- 正式输出：`public_attack_surface`、`focus_bidder_verification_profile`、`evidence_grade_profile`。
- 上游 handoff：`handoff/stage3_to_stage4/contract.json`
- 下游 handoff：`handoff/stage4_to_stage5/contract.json`
- 当前允许做什么：只允许做公开核验、冲突预判、verification profile 与 handoff 的受控补齐。
- 当前禁止做什么：不得直接生成商业对象；不得越级形成正式外发结论；不得绕开 Stage 5 双闸门。
- 相关 contracts / tests：`contracts/schemas/public_attack_surface.schema.json`；`contracts/schemas/focus_bidder_verification_profile.schema.json`；`contracts/schemas/evidence_grade_profile.schema.json`；`tests/test_internal_chain.py`
- 近端候选 `packet_id`：`PKT-P0-01-review-queue-window-scoring`

## 2.5 Stage 5 规则与证据双闸门

- 阶段目标：把规则命中与证据可见性收口为统一双闸门，决定结果是升级、降级还是转复核。
- 正式输入：Stage 4 核验结果、规则目录、证据对象与治理约束。
- 正式输出：`rule_hit`、`evidence`、`rule_gate_decision`、`evidence_gate_decision`、`review_request`。
- 上游 handoff：`handoff/stage4_to_stage5/contract.json`
- 下游 handoff：`handoff/stage5_to_stage6/contract.json`
- 当前允许做什么：只允许做规则、证据、gate object、golden 与 regression 的受控收口。
- 当前禁止做什么：不得单闸门升级正式结论；不得把截图、OCR 或模型摘要写成唯一主证；不得跳过复核请求。
- 相关 contracts / tests：`contracts/schemas/rule_gate_decision.schema.json`；`contracts/schemas/evidence_gate_decision.schema.json`；`contracts/testing/golden_cases.json`；`tests/test_stage56_evaluators.py`
- 近端候选 `packet_id`：`PKT-P0-01-review-queue-window-scoring`

## 2.6 Stage 6 人工复核、统一事实、真实竞争者识别与正式报告

- 阶段目标：把前五阶段结果汇聚为唯一统一事实中枢，并形成复核队列、真实竞争者画像与正式报告对象。
- 正式输入：`rule_gate_decision`、`evidence_gate_decision`、`review_request`、人工复核结果与治理状态。
- 正式输出：`project_fact`、`legal_action_recommendation`、`review_queue_profile`、`challenger_candidate_profile`、`report_record`。
- 上游 handoff：`handoff/stage5_to_stage6/contract.json`
- 下游 handoff：`handoff/stage6_to_stage7/contract.json`
- 当前允许做什么：只允许做 `project_fact` 聚合、review queue、report、challenger profile 与 Stage 6/7 handoff 的受控闭合。
- 当前禁止做什么：不得绕开 `project_fact` 形成主判断；不得把 Stage 6 输出写成状态源；不得把 Stage 7 反向变成统一事实来源。
- 相关 contracts / tests：`contracts/schemas/project_fact.schema.json`；`contracts/schemas/review_queue_profile.schema.json`；`contracts/schemas/report_record.schema.json`；`tests/test_stage56_evaluators.py`
- 近端候选 `packet_id`：`PKT-P0-01-review-queue-window-scoring`

## 2.7 Stage 7 商业承接与可售对象

- 阶段目标：在不突破统一事实边界的前提下，形成可售机会、买方匹配、行动主体与推荐方案。
- 正式输入：`project_fact`、`challenger_candidate_profile`、`legal_action_recommendation` 以及 Stage 6 handoff。
- 正式输出：`saleable_opportunity`、`buyer_fit`、`challenger_buyer_fit`、`legal_action_actor_profile`、`procurement_decision_actor_profile`、`offer_recommendation`、`account_context`。
- 上游 handoff：`handoff/stage6_to_stage7/contract.json`
- 下游 handoff：`handoff/stage7_to_stage8/contract.json`
- 当前允许做什么：只允许做 Stage 7 商业对象、buyer fit、价值评分、价格归一、竞争者排序与 internal recommendation surface 的受控闭合。
- 当前禁止做什么：不得越过 `project_fact` 直接生成机会；不得把 recommendation 写成对外软件 release；不得放开 Stage 8/9 live path。
- 相关 contracts / tests：`contracts/sales/buyer_fit_scorecard.json`；`contracts/sales/lead_value_scoring_catalog.json`；`contracts/sales/price_normalization_catalog.json`；`tests/test_stage7_runtime_closure.py`
- 近端候选 `packet_id`：`PKT-P0-02-stage7-buyer-fit-value-derivation`、`PKT-P0-03-stage7-price-competitor-resolution`

## 2.8 Stage 8 联系对象与销售触达编排

- 阶段目标：在 governed internal 边界内形成联系人、触达计划与触达记录，并保持 candidate 与 execution 语义分层。
- 正式输入：`saleable_opportunity`、Stage 7 actor/fit 输出、联系来源策略、合规矩阵与 cadence 规则。
- 正式输出：`contact_target`、`outreach_plan`、`touch_record`。
- 上游 handoff：`handoff/stage7_to_stage8/contract.json`
- 下游 handoff：`handoff/stage8_to_stage9/contract.json`
- 当前允许做什么：只允许做 `contact_target`、candidate merge、compliance lattice、draft-only / preview / governed internal path 的受控闭合。
- 当前禁止做什么：不得放开 real execution；不得把高限制字段直接外发；不得把第三方 enrichment 或 execution vendor 写成默认 live。
- 相关 contracts / tests：`contracts/sales/contact_compliance_matrix.json`；`contracts/sales/contact_source_policy_catalog.json`；`contracts/sales/outreach_cadence_catalog.json`；`tests/test_stage8_resolution_closure.py`
- 近端候选 `packet_id`：`PKT-P0-04-stage8-compliance-lattice`、`PKT-P0-05-stage8-contact-enrichment-merge`

## 2.9 Stage 9 订单、支付、交付与治理反馈

- 阶段目标：在 internal governed 边界内形成订单、支付、交付、结果事件与治理反馈回写闭环。
- 正式输入：`contact_target`、`outreach_plan`、`touch_record` 与 Stage 8/9 handoff。
- 正式输出：`order_record`、`payment_record`、`delivery_record`、`opportunity_outcome_event`、`governance_feedback_event`。
- 上游 handoff：`handoff/stage8_to_stage9/contract.json`
- 下游 handoff：无，主链终点。
- 当前允许做什么：只允许做 typed workflow、writeback contract、governance feedback、internal preview / governed writeback 的受控闭合。
- 当前禁止做什么：不得放开 real payment / delivery / refund；不得把 projected mutation 写成默认持久化执行；不得把 Stage 9 写成 external release 放行口。
- 相关 contracts / tests：`contracts/governance/writeback_impact_policy.json`；`contracts/sales/outcome_taxonomy_catalog.json`；`contracts/schemas/delivery_record.schema.json`；`tests/test_stage9_impact_executor.py`
- 近端候选 `packet_id`：`PKT-P0-06-stage9-writeback-contract-core`、`PKT-P0-07-stage9-upstream-feedback-loop`

## 3. 跨阶段近端候选

- `PKT-P1-02-capability-canonicalization`：用于 capability canonical source、future unlock decision-only 边界与 runtime precedence 收口，不改变当前主导航图的阶段顺序。
- `PKT-P1-03-api-ui-capability-envelope`：用于 Stage 7-9 preview surface 只消费正式对象与 canonical envelope，不新增第二套主判断。
- `PKT-P1-04-generated-assertions-cadence-ladder`：用于 Stage 8 cadence ladder 与 regression 断言补强，不放开真实触达。
- `PKT-P1-05-validator-anti-drift-semanticization`：用于 validator 语义化收口，不改变任何业务对象语义。

## 4. 非主线排除项

- `R5 external unlock prerequisites` 不是当前阶段 1-9 主导航图的一部分。
- `R6 future unlock decision` 不是当前阶段 1-9 主导航图的一部分。
- `Post-R6 candidate gap` 不是当前阶段 1-9 主导航图的一部分。
- future unlock、activation prep、implementation decision readiness 只允许作为历史决策语汇或他处 machine-readable 资产的查询项，不得回写成当前主线正文。
