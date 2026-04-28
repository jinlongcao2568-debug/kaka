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
- 本图承接 `PTL-I100-OPEN-CAPABILITY-BASELINE`：除自动退款执行和禁止的非公开 / 灰色能力外，产品必需能力都是目标能力，必须逐级受控开放。
- 本图中的 `blocked-by-default` 表示未通过 provider config、sandbox、approval、audit、operator action、field allowlist/masking、dedicated current_task 与验收前不能 live，不表示永久不做。
- 本图不放开 `external release`，不放开 `Stage 8 real execution`，不放开 `Stage 9 real payment / delivery / refund`；自动退款执行不实现，只保留 manual exception / approval-audit / governed review。
- 各阶段保留 1 个最贴近的导航候选 `packet_id`；更集中的近端候选提示统一放在第 3 节。

## 1.1 现实对齐说明

- 本仓库当前不是“从零补 skeleton”的起点，而是已经存在 Stage1-9 的 internal governed runtime。
- Stage1-5 当前代码现状统一按 `PARTIAL_RUNTIME` 理解；Stage6-9 当前代码现状统一按 `HEAVY_RUNTIME` 理解；`PTL-INT` 仍是 `PARTIAL_RUNTIME` 的内部消费封装。
- Stage8 / Stage9 的现状是 internal governed runtime，不是 live execution；真实触达、真实支付、真实交付是目标能力，但 `external release`、`Stage 8 real execution`、`Stage 9 real payment / delivery / refund` 继续保持 blocked-by-default / governed / approval-gated，直到 dedicated task 与验收放行。
- 自动退款执行不属于目标能力；退款只允许作为 manual exception record、manual approval/audit 与 governed review 处理。
- 当前 active packet 以 `control/current_task.yaml` 为准；本轮 active packet 为 `PTL-I100-138-real-public-snapshot-to-parser-pilot`，承接 137 已能生成的真实公开 snapshot，验证 HTML/PDF snapshot 进入 Stage3 parser/readback；parser 输出必须保持 `UNVERIFIED`、review-required、不可客户可见，不放开任意 crawler、登录/验证码/反爬绕过、public software release、未审批 live provider、真实下载、真实退款或自动退款。
- `PTL-I100-118R-final-product-operational-reacceptance` 已完成并本地提交：`f977b5b`；`PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout` 已完成并本地提交：`106c4a1`，受控真实世界 e2e closeout 已闭合。当前 132 处理前端实际可用性检查中发现的“只有入口、缺产品化工作台”问题。
- 118R 已把剩余真实运营缺口登记为 127-131 五个完整任务并已完成；132 是后续前端产品化强化包，不重开 Stage1-9 runtime。`PTL-I100-127-owner-operator-frontend-and-customer-portal` 已补 owner console / customer artifact portal，`PTL-I100-128-real-public-source-field-validation-and-coverage` 已补 114A-114I 受控手工公开样本字段覆盖报告，`PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund` 已补 provider binding matrix / credential redaction / sandbox evidence / callback validation / kill-switch readback，`PTL-I100-130-llm-assisted-parsing-review-and-sales-governance` 已补受治理 model-assist readback，`PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout` 已补受控真实世界 e2e closeout。
- `PTL-I100-111F-open-capability-registry-route-doc-sync` 已完成并本地提交：`1c403c7`；它只同步开放能力基线到注册表、路线图、D1-D14 补表和测试，不再是 current active packet。
- `PTL-INT-internal-preview-productization-strengthening` scoped-execution 已完成并提交：`f788a2b`；它不再是 current active packet，也不再是 current_mainline_next_candidate。
- Stage1-9 + INT 产品主线、`PTL-I100-112-production-platform-infrastructure` 至 126 的受控能力包，以及 `PTL-I100-127` 至 `PTL-I100-131` 已完成；当前进入 132 前端产品化强化阶段；closeout 成立范围仍是 owner-operated controlled use，不等于 public software release。
- 当前没有自动 next candidate；132 结束后产品主线候选池应进入 completed/no-auto-activation 状态。
- post-118R 方向选择当前只作导航提示，不自动决定执行顺序，也不自动放行任何 provider/live 执行。
- `Stage7 模块边界重构` 对应的 scoped-execution 包 `PTL-S7-module-boundary-refactor` 已完成并提交：`2601482`；该方向当前不再 recommended_now，且不是 current active packet。
- 当前 129 已由 `control/current_task.yaml` 激活并完成实现；本导航图只同步近端提示，不决定后续 130 或任何模型/provider/live 执行顺序。
- `PTL-GOV-116-mainline-candidate-shift-to-INT` 已完成并提交：`209c4cd`；它不再是 current active packet，仅作为把 current_mainline_next_candidate 推进到 `PTL-INT` 的历史控制面参照。
- `PTL-S89-outreach-writeback-delivery-governance` scoped-execution 已完成并提交：`c36dd9d`；它不再是 current active packet，也不再是 current_mainline_next_candidate。
- `PTL-S78-contact-candidate-compliance-preview` scoped-execution 已完成并提交；它不再是 current active packet，也不再是 current_mainline_next_candidate。
- 本轮只做 `PTL-I100-138-real-public-snapshot-to-parser-pilot` 的 Stage2 snapshot 到 Stage3 parser/readback 受控验证与对应控制面/测试同步；不改 D1-D14 正文 / contracts / handoff / scripts / fixtures / Stage1/4/5/6/7/8/9 runtime / storage runtime / shared runtime，不把 parser 输出升格为 Stage4 verified fact、Stage5 rule hit 或客户可见结论，不放开 external release、未审批 Stage8 live send、未审批 Stage9 live payment/delivery、真实下载、真实退款、自动退款或真实外部模型调用。
- `PTL-S56-project-fact-review-report` scoped-execution 已完成并已提交；它不再是 current active packet，也不再是 current_mainline_next_candidate。
- `PTL-S45-rule-evidence-dual-gate` scoped-execution 已完成并 closeout；它不再是 current active packet，也不再是 current_mainline_next_candidate。
- `PTL-S34-object-lineage-verification-handoff` scoped-execution 已完成并 closeout；它不再是 current active packet，也不再是 current_mainline_next_candidate。
- `PTL-S23-public-chain-to-parser-contract` scoped-execution 已完成并 closeout；它不再是 current active packet，也不再是 current_mainline_next_candidate。
- `PTL-S12-source-route-clock-authority` scoped-execution 已完成并 closeout；它不再是 current active packet，也不再是 current_mainline_next_candidate。
- `control/product_task_library.yaml` 只提供候选池；`current_mainline_next_candidate` 不决定当前执行顺序。
- 本文件仍是纯导航图 / candidate navigation asset，不是状态源、执行顺序源、执行日志或完整 backlog；主线闭合说明只用于近端导航提示。
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

- 阶段目标：在 governed internal 边界内形成联系人、触达计划与触达记录，并保持 candidate 与 execution 语义分层；真实销售触达是目标能力，但必须逐级 gated。
- 正式输入：`sales_lead`、`saleable_opportunity`、`multi_competitor_collection`、`legal_action_actor_profile`、`procurement_decision_actor_profile`、`buyer_fit`、`challenger_buyer_fit`、`offer_recommendation` 以及联系来源策略、合规矩阵与 cadence 规则。
- 正式输出：`contact_candidate_collection`、`contact_selection_trace`、`contact_target`、`outreach_plan`、`touch_record`。
- 上游 handoff：`handoff/stage7_to_stage8/contract.json`
- 下游 handoff：`handoff/stage8_to_stage9/contract.json`
- 正式边界：只允许在 governed internal 边界内形成 candidate、selection、plan 与 touch 记录；真实触达必须通过 provider config、sandbox、approval、audit、模板、频控、退订、operator action 与 dedicated current_task 验收后才能 live，不直接外发高限制字段。
- 相关 contracts / tests：`contracts/sales/contact_compliance_matrix.json`；`contracts/sales/contact_source_policy_catalog.json`；`contracts/sales/outreach_cadence_catalog.json`；`contracts/schemas/contact_candidate_collection.schema.json`；`contracts/schemas/contact_selection_trace.schema.json`；`tests/test_stage8_resolution_closure.py`
- 导航候选 `task_id`：`PTL-S78-contact-candidate-compliance-preview`

## 2.9 Stage 9 订单、支付、交付与治理反馈

- 阶段目标：在 internal governed 边界内形成订单、支付、交付、结果事件与治理反馈回写闭环；真实收款、扣款、交付、发票/收据、对账是目标能力，但必须逐级 gated。
- 正式输入：`contact_target`、`outreach_plan`、`touch_record`、`saleable_opportunity` 与 Stage 8/9 handoff。
- 正式输出：`order_record`、`payment_record`、`delivery_record`、`opportunity_outcome_event`、`governance_feedback_event`。
- 上游 handoff：`handoff/stage8_to_stage9/contract.json`
- 下游 handoff：无，主链终点。
- 正式边界：只允许 internal preview / governed writeback；真实 payment / delivery 必须通过 provider config、sandbox、approval、audit、operator action、field allowlist/masking 与 dedicated current_task 验收后才能 live；自动退款执行不实现，退款只保留 manual exception / approval-audit / governed review；不把 projected mutation 写成默认持久化执行。
- 相关 contracts / tests：`contracts/governance/writeback_impact_policy.json`；`contracts/sales/outcome_taxonomy_catalog.json`；`contracts/schemas/delivery_record.schema.json`；`tests/test_stage9_impact_executor.py`
- 导航候选 `task_id`：`PTL-S89-outreach-writeback-delivery-governance`

## 3. 近端导航提示

> 下列候选仅作“下一步可能去哪里看”的导航提示。  
> 它们不是当前任务源，不决定执行顺序，也不代表完整 backlog。实际选包以 `control/current_task.yaml`、`control/product_task_library.yaml` 为准。  
> 近端提示应同时结合 `product_task_library` 的任务顺序、`current_task` 当前窗口与对应任务的 `existing_code_state`。  
> `scripts/check-state-alignment.ps1` 会把本节近端候选与 `control/product_task_library.yaml` 当前任务池做轻量对照；若明显落后，只给 `WARNING` 提示，不阻断。
> 同步触发采用 suggestion-only：脚本只提示“应复核近端候选”，不自动修改路线图正文，也不让 `check-final-gate` 因近端候选滞后而失败。

- 当前 active packet：`PTL-I100-138-real-public-snapshot-to-parser-pilot`；本轮把真实来源验证从“Stage2 snapshot/readback”推进到“Stage3 parser/readback pilot”，默认不执行任意 crawler、未审批 live provider 调用或真实客户下载。
- 当前候选池 next candidate：`PTL-I100-138-real-public-snapshot-to-parser-pilot` 已进入 active；完成后不自动激活下一包。
- post-118R 方向选择当前只作导航提示，不自动决定执行顺序，也不自动进入 provider/live 执行。
- `PTL-I100-127-owner-operator-frontend-and-customer-portal`：已补实际操作台、客户 artifact 门户、审批审计可视化和客户授权下载入口。
- `PTL-I100-128-real-public-source-field-validation-and-coverage`：已用受控手工公开 snapshot 验证 114A-114I source adapters、Stage3 parser 和 Stage4 public verification，不绕登录/验证码/反爬；真实站点实战仍留给 131 或后续按站点 dedicated packet。
- `PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund`：已接企业微信、邮件、短信/电话、CRM、报价、支付、交付 provider binding/readback；自动退款仍不实现，真实调用仍需审批/审计/operator action。
- `PTL-I100-130-llm-assisted-parsing-review-and-sales-governance`：已接入受治理的大模型辅助解析、复核、证据摘要和销售话术草稿 readback；模型输出不得直接成为事实或客户结论，不调用真实外部模型 provider。
- `PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout`：在 127-130 完成后跑受控真实世界端到端试点，已作为产品 closeout 门完成。
- `PTL-I100-132-owner-operator-frontend-productization-workbench`：在前端实机检查后补产品化工作台、Stage1-9 运营总览、客户门户空状态和红线可视化。
- `PTL-I100-133A-real-public-entry-url-fetcher-and-allowlist`：已完成第一批真实公开总入口 fetcher，覆盖全国公共资源交易平台交易查询、中国政府采购网中央公告/中标公告等总入口。
- `PTL-I100-133B-national-verification-source-entry-fetchers`：已完成国家级核验入口 fetch/readback，覆盖四库一平台 home/company/person/project 以及 Credit China / GSXT 官方入口，把 `200+SPA 壳`、`412`、`521` 等真实运行状态统一压到受控 readback/fail-closed。
- `PTL-I100-133C-representative-local-platform-entry-fetchers`：已完成代表性地方平台入口 fetch/readback，覆盖北京市主平台、北京工程建设入口、北京经开区分平台和广东省 portal，区分“直接 HTML 成功入口”和“200 但只返回前端壳页的 portal”。
- `PTL-I100-134-owner-task-runner-real-source-ui`：已完成并提交；把 owner console 接到 133A-133D 的 allowlisted real public fetcher，上线 internal-only profile catalog、capture 触发和 repository-backed readback，不引入新前端栈。
- `PTL-I100-135-owner-real-source-task-workbench`：已完成并提交；把真实公开源抓取升级为 owner 可连续操作的任务工作台，补 run list、状态、snapshot/readback 链接和失败关闭状态可见性。
- `PTL-I100-136-real-public-url-fetcher-bulk-hardening`：已完成并提交 `ee9f354`；一次性硬化当前登记的 14 个入口 URL 和 2 个附件 URL，修复 TLS fallback、HTTP 状态分类、SPA/弱正文 fail-closed 和成功 snapshot/readback。
- `PTL-I100-137-degraded-real-public-site-hardening`：已完成并提交 `36b242d`；对 136 中 JZSC、CreditChina、GSXT、广东省/云浮等 degraded profile 做站点级公开路径硬化或稳定 fail-closed 分类。
- `PTL-I100-138-real-public-snapshot-to-parser-pilot`：当前 active；把已成功固定的真实公开 HTML/PDF snapshot 送入 Stage3 parser/readback，证明 source slice、confidence、parser audit 和 UNVERIFIED/review-required 边界，不生成 verified fact、rule hit 或客户可见材料。
- Stage7 模块边界重构：对应的 scoped-execution 包 `PTL-S7-module-boundary-refactor` 已完成并提交 `2601482`；该方向当前不再 recommended_now，只作为已闭合近端历史参照。
- 132 已由 dedicated current_task 激活；本轮完成后不自动进入新任务。推荐理由：先让 owner 实际操作界面匹配已闭合的后端能力，再做更深的实战验证或 UI 迭代。
- Internal preview 产品化强化（`PTL-INT-internal-preview-productization-strengthening`）：已完成 scoped-execution 并提交 `f788a2b`；不再是 current active packet，也不再是 current_mainline_next_candidate，仅作为该方向的已闭合历史参照；不是 external release 或客户平台放行。
- `PTL-S89-outreach-writeback-delivery-governance`：已完成 scoped-execution 并提交 `c36dd9d`；不再是 current_mainline_next_candidate，仅作为 Stage8-9 触达记录、回写、交付与治理反馈闭合的近端历史参照。
- `PTL-S78-contact-candidate-compliance-preview`：已完成并提交；不再是 current_mainline_next_candidate，仅作为 Stage7-8 联系候选、合规判定与预览闭合的近端历史参照。

历史控制面参照：`PTL-GOV-116-mainline-candidate-shift-to-INT` 已完成并提交 `209c4cd`，只用于说明 current_mainline_next_candidate 如何推进到 `PTL-INT`，不作为近端候选或当前执行顺序来源。

主线闭合提示：本文件仍只提供近端导航提示；不提供状态源、执行顺序源、完整 backlog 或 release 放行。`external release`、`Stage 8 real execution`、`Stage 9 real payment / delivery / refund` 红线不变；blocked-by-default 只表示受控开放条件未满足前不能 live，不表示真实触达、支付或交付永久不做。自动退款执行不实现。
