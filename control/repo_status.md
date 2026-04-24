# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-I100-111F-open-capability-registry-route-doc-sync (ACTIVE; docs/control synchronization only. This packet mirrors PTL-I100-OPEN-CAPABILITY-BASELINE into product_module_registry, AX9S route navigation, D1-D14 appendix tables, and tests. It does not activate PTL-I100-112, implement runtime, call providers, approve push, external release, real production samples, real touch, real payment gateway, real charge, real delivery, real refund, automated refund execution, or unapproved external/live execution)
Current Full-Repair Program Status: FULL_REPAIR_COMPLETE_REVIEW_READY
Candidate Gap Active: false
Strategic Branch Active: false
Closure Review Active: false
Closure Review Completed: true
Mainline Selection Ready: true
C-group Enum Freeze: CONFIRMED
Capability Adjudication Source: control/product_task_library.yaml#open_capability_policy and D13 能力总表与放行边界总表

Current Blockers:
- External leadpack delivery remains gated by approval + audit chain
- External software release remains blocked
- Stage 8 real execution remains governed / approval-gated / blocked by default
- Stage 9 real payment/delivery/refund remains governed / approval-gated / blocked by default

Product Open Capability Baseline:
- Policy id: PTL-I100-OPEN-CAPABILITY-BASELINE.
- The sold product is evidence packs / lead packs; the software is owner-operated tooling and customer artifact access, not the sold software product itself.
- Except automated refund execution and prohibited non-public/gray capabilities, all business capabilities needed to sell evidence packs are target capabilities and must be implemented through staged controlled opening.
- "Blocked by default" means not live until provider config, sandbox, approval, audit, operator action, field allowlist/masking, and the dedicated current_task packet pass; it does not mean the capability is permanently out of product scope.
- Real public-source collection, parsing/OCR/attachments, public verification, rule expansion, challenger identification, CRM/quote, customer-visible LeadPack/page/export, sales outreach, payment collection, charge execution, delivery fulfillment, receipt/invoice, settlement, customer access, and production monitoring are target capabilities.
- Automated refund execution is excluded. Refund handling remains manual exception record, manual approval/audit, and governed review only.
- PTL-I100-118 full product operational acceptance is the closure gate for declaring the registered product gaps complete.

Allowed Actions (current):
- sync control/product_module_registry.yaml with open_capability_policy_ref and D1-D14 authority docs
- append open capability baseline tables to D1-D14 without changing D doc body semantics
- update docs/AX9S_开发执行路由图.md navigation text so Stage8/Stage9/live capabilities read as target capabilities gated by default, not permanent out-of-scope
- update targeted tests that lock the docs/control synchronization
- keep PTL-I100-112-production-platform-infrastructure as the next recommended candidate, but do not auto-activate it
- run required checks and commit locally if all checks pass and the actual diff remains inside the current task packet

Forbidden Actions (current):
- Any src/** runtime change
- Any contracts/** change
- Any handoff/** change
- Any scripts/** change
- Any fixtures/** change
- Any change to control/product_task_library.yaml or control/product_operability_gap_matrix.yaml in this 111F packet
- Any change that alters canonical readiness
- Any change that alters conditional-go
- Any change that loosens external release / Stage8 / Stage 8 / Stage9 / Stage 9 redlines
- Any change that adds formal object, enum, gate, or exception semantics
- Any real LeadPack external delivery or client-visible formal export/page release
- Any use of real production samples or external live data
- Any external/live execution
- Any real touch, payment, delivery, or refund
- Any automated refund program
- Any push

State Semantics:
- READY_FOR_POST-REPAIR_MAINLINE_SELECTION means the repo can enter formal mainline selection; it does not by itself change external release, Stage8, or Stage9 boundaries.
- READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT remains the scoped conditional-go for internal LeadOps development.
- current_task -> product_task_library -> repo_status is the only active-source priority.
- control/current_task.yaml is the only active execution source.
- control/product_task_library.yaml remains the product mainline task pool and candidate source; it does not replace control/current_task.yaml as the active execution source.
- PTL-I100-111A provider adapter config/sandbox/readback seam is completed via commit c279fd5. It did not call real providers or execute live touch/payment/delivery/refund.
- PTL-I100-111F-open-capability-registry-route-doc-sync is the active docs/control sync packet. It does not implement PTL-I100-112 production infrastructure.
- PTL-I100-112 is the next recommended candidate after reassessment because production durability and audit/worker foundations should precede real data and provider execution.
- PTL-I100-111B/111C/111D/111E and PTL-I100-113 through PTL-I100-121 are registered as task-pool candidates for the open production/product gaps; 114A-114I source-family subpackets and 111C1-111C4 package-type subpackets are explicit. None is active until control/current_task.yaml explicitly activates it.
- PTL-I100 execution-level management should use the PTL-I100 task_ids in control/product_task_library.yaml; each task requires a dedicated current_task packet before implementation.
- Execution-level management and reporting should use the P1 -> P8 ladder in control/product_task_library.yaml rather than direction labels such as Stage8 governed touch 深化 / Stage9 governed delivery 深化.
- source_blueprint_registry is the only source-blueprint allowlist.
- operator_assignment_roster_defaults is the only stable roster source for stage7/8/9.
- docs/AX9S_开发执行路由图.md is a pure route-map candidate navigation asset; it does not act as current task source, state source, execution log, full backlog, or execution-order authority.
- Canonical readiness is unchanged by this round.
- External leadpack delivery remains gated by approval + audit chain.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.

Current Scoped-Execution Required Checks:
- git status --short --untracked-files=all
- python -m unittest tests.test_open_capability_doc_sync -v
- python -m unittest tests.test_product_module_registry -v
- python -m unittest tests.test_stage12_extractors -v
- python -m unittest tests.test_external_unlock_prerequisites -v
- python -m unittest tests.test_post_repair_state_sync -v
- python -m unittest tests.test_product_operability_gap_matrix -v
- pwsh -NoProfile -ExecutionPolicy Bypass -Command '$paths = @(''control/current_task.yaml'',''control/repo_status.md'',''control/product_module_registry.yaml'',''docs/AX9S_开发执行路由图.md'',''docs/D1_研发_Codex执行手册.md'',''docs/D2_正式对象契约与字段字典.md'',''docs/D3_正式规则码总表与判定说明书.md'',''docs/D4_OpenAPI接口契约.md'',''docs/D5_页面导出与人工复核规范.md'',''docs/D6_字段策略字典与客户交付字段规范.md'',''docs/D7_对象级交付矩阵与外发治理规范.md'',''docs/D8_真实竞争者识别可售对象与销售推进规范.md'',''docs/D9_联系对象与销售触达规范.md'',''docs/D10_订单支付交付与治理反馈规范.md'',''docs/D11_测试验收与金标回归清单.md'',''docs/D12_部署发布与运行治理规范.md'',''docs/D13_公开可查边界能力清单.md'',''docs/D14_AI模型治理规范.md'',''tests/test_open_capability_doc_sync.py'',''tests/test_product_module_registry.py''); & ''scripts/check-task-packet.ps1'' -PlannedTargetPaths $paths'
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-task-packet.ps1
- python tests/run_tests.py
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-state-alignment.ps1
- git diff --check
- git status --short --untracked-files=all

Automation Guardrails:
- Action matrix: control/automation_action_matrix.yaml
- Review gate matrix: control/review_gate_matrix.yaml
- Stop conditions: control/automation_stop_conditions.yaml
- Task packet rules: control/automation_task_packet_rules.yaml

Navigation Assets:
- Execution routing map (candidate navigation asset, not status source): docs/AX9S_开发执行路由图.md
- Product mainline task pool: control/product_task_library.yaml
- Product module registry (execution map, not status source): control/product_module_registry.yaml
- Source blueprint registry: control/source_blueprint_registry.yaml
- Operator roster defaults: control/operator_assignment_roster_defaults.yaml
- Auto dev task packet template: docs/自动开发任务包模板.md
