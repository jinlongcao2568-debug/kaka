# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-GOV-113-mainline-candidate-shift-to-S7 (SCOPED_EXECUTION; governance pointer fix only; shifts control/product_task_library.yaml current_mainline_next_candidate from PTL-S67-saleable-opportunity-derivation to PTL-S7-price-competitor-offer-resolution; syncs tests/test_stage12_extractors.py assertions; does not enter product runtime, does not modify Stage7 business implementation, contracts, handoff, scripts, src, AX9S, or canonical readiness; does not open external release / Stage8 live execution / Stage9 live payment-delivery)
Current Full-Repair Program Status: FULL_REPAIR_COMPLETE_REVIEW_READY (program control state only; FF-18-S1 only records final state-source alignment and does not change repo readiness)
Candidate Gap Active: false
Strategic Branch Active: false
Closure Review Active: false
Closure Review Completed: true
Mainline Selection Ready: true
C-group Enum Freeze: CONFIRMED
Capability Adjudication Source: D13 能力总表与放行边界总表 (统一能力消费与放行裁决来源)

Current Blockers:
- External leadpack delivery remains gated by approval + audit chain
- External software release remains blocked
- Stage 8 real execution remains governed / approval-gated / blocked by default
- Stage 9 real payment/delivery/refund remains governed / approval-gated / blocked by default

Allowed Actions (current):
- Internal leadops development under the controlled development system
- scoped-execution for PTL-GOV-113-mainline-candidate-shift-to-S7 within declared_changed_paths / allowed_modification_paths only
- switch control/current_task.yaml active packet to PTL-GOV-113-mainline-candidate-shift-to-S7
- update control/product_task_library.yaml candidate-pool pointer from PTL-S67-saleable-opportunity-derivation to PTL-S7-price-competitor-offer-resolution
- mark PTL-S67-saleable-opportunity-derivation completed and no longer current_mainline_next_candidate
- mark PTL-S7-price-competitor-offer-resolution as current_mainline_next_candidate only
- update tests/test_stage12_extractors.py next-candidate assertions
- run the required checks and stop for report

Forbidden Actions (current):
- Any work outside PTL-GOV-113-mainline-candidate-shift-to-S7 scoped-execution in this round
- Any change outside declared_changed_paths / allowed_modification_paths
- Any change to forbidden_modification_paths targets
- Any change to AGENTS.md, docs/**, scripts/**, src/**, contracts/**, handoff/**, or paths outside current task allowed_modification_paths
- Any change to docs/AX9S_开发执行路由图.md
- Any change to control/product_module_registry.yaml
- Any change to control/milestone_status.yaml
- Any change to control/source_blueprint_registry.yaml
- Any change to control/operator_assignment_roster_defaults.yaml
- Any change to control/review_gate_matrix.yaml
- Any change to control/automation_task_packet_rules.yaml
- Any claim that this scoped-execution round changes canonical readiness
- Any scripts change in this round
- Any runtime / contracts / handoff / Stage7 business implementation change in this round
- Any new formal object, enum, gate, or exception semantics
- External software release or unaudited leadpack delivery
- Production release logic or deployment
- Generated or executed real contact_target / outreach / payment / delivery
- Real outreach/payment/delivery execution without manual approval and governance gates
- Automatic commit

State Semantics:
- READY_FOR_POST-REPAIR_MAINLINE_SELECTION means the repo can enter formal mainline selection; it does not by itself change external release, Stage8, or Stage9 boundaries.
- READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT remains the scoped conditional-go for internal LeadOps development.
- current_task -> product_task_library -> repo_status is the only active-source priority.
- control/current_task.yaml is the only active execution source.
- PTL-GOV-113-mainline-candidate-shift-to-S7 is the current scoped-execution active packet through control/current_task.yaml.
- control/product_task_library.yaml remains the product mainline task pool and candidate source; it does not activate scoped-execution by itself.
- PTL-S67-saleable-opportunity-derivation scoped-execution has already completed and committed; it is no longer the current active packet and is no longer current_mainline_next_candidate.
- PTL-S7-price-competitor-offer-resolution is only the current_mainline_next_candidate in the candidate pool; it is not automatically the current execution packet.
- This round does not activate PTL-S7, does not enter PTL-S7 scoped-execution, and does not change runtime.
- control/product_module_registry.yaml is an execution map and product module ledger, not a status source, not a release gate, and not a second product direction source.
- source_blueprint_registry is the only source-blueprint allowlist.
- operator_assignment_roster_defaults is the only stable roster source for stage7/8/9.
- docs/AX9S_开发执行路由图.md is a pure route-map candidate navigation asset; it does not act as current task source, state source, execution log, full backlog, or execution-order authority.
- Canonical readiness is unchanged by this scoped-execution round.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.

Current Scoped-Execution Required Checks:
- python -m pytest tests/test_stage12_extractors.py -q
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-task-packet.ps1
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-state-alignment.ps1
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-final-gate.ps1
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/clean-python-cache.ps1
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
