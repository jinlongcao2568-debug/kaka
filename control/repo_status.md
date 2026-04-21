# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-GOV-106-mainline-candidate-shift-test-alignment (scoped-execution; current active packet via control/current_task.yaml; this round is the minimal governance/test alignment packet that keeps the 4 PTL-GOV-105 control/docs changes as baseline dirty paths, updates control/current_task.yaml and control/repo_status.md, and fixes only tests/test_stage12_extractors.py stale assertions for the already-shifted current_mainline_next_candidate; no product_task_library or AX9S semantic change in this round, no PTL-S23 activation, no runtime/contracts/handoff/scripts changes, no readiness change, no external release / Stage8 live execution / Stage9 live payment-delivery opening)
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
- Internal leadops development under the new controlled development system
- scoped-execution for PTL-GOV-106-mainline-candidate-shift-test-alignment within declared_changed_paths / allowed_modification_paths only
- minimal governance/test alignment that keeps PTL-GOV-105's 4 control/docs changes as baseline dirty paths and fixes only tests/test_stage12_extractors.py stale assertions
- current_task is the unique active execution source
- product_task_library remains the product mainline task pool and is not modified in this round; PTL-GOV-105's product_task_library change remains baseline only
- source_blueprint_registry remains the source-blueprint allowlist and is not modified in this scoped-execution round
- operator_assignment_roster_defaults remains the stable stage7/8/9 roster source and is not modified in this scoped-execution round
- AX9S route map remains a candidate navigation asset and navigation-only product phase map; it is not modified in this round and only remains as baseline dirty path from PTL-GOV-105

Forbidden Actions (current):
- Any claim that scoped-execution changes canonical readiness
- Any attempt to use historical task_packet_library as the current task source
- Any change outside declared_changed_paths / allowed_modification_paths
- Any product_task_library or AX9S edit in this round
- Any activation of PTL-S23
- Any runtime, contracts, handoff, or scripts change
- Any test change outside tests/test_stage12_extractors.py
- Any Stage3+ runtime change
- Any Stage8 / Stage9 runtime, contract, handoff, or execution change
- Any new formal object, enum, gate, or exception semantics
- External software release or unaudited leadpack delivery
- Production release logic or deployment
- Real outreach/payment/delivery execution without manual approval and governance gates
- Automatic commit

State Semantics:
- READY_FOR_POST-REPAIR_MAINLINE_SELECTION means the repo can enter formal mainline selection; it does not by itself change external release, Stage8, or Stage9 boundaries.
- READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT remains the scoped conditional-go for internal LeadOps development.
- current_task -> product_task_library -> repo_status is the only active-source priority.
- control/current_task.yaml is the only active execution source.
- PTL-GOV-106-mainline-candidate-shift-test-alignment is the current active packet through control/current_task.yaml.
- This round is minimal governance/test alignment only; it does not re-open PTL-GOV-105 work or change product_task_library / AX9S semantics.
- PTL-GOV-105's 4 control/docs changes remain in the worktree as baseline dirty paths and are intentionally retained.
- PTL-S12-source-route-clock-authority scoped-execution remains completed and closeout remains recorded, but that completion does not change canonical readiness.
- product_task_library only carries product mainline tasks for future selection and scoped packet derivation; PTL-GOV-106 is not inserted into that task pool.
- product_task_library current_mainline_next_candidate metadata continues to point to PTL-S23-public-chain-to-parser-contract, but it does not decide execution order by itself.
- PTL-S23-public-chain-to-parser-contract is the next mainline candidate only; it is not activated and is not the current active packet.
- source_blueprint_registry is the only source-blueprint allowlist.
- operator_assignment_roster_defaults is the only stable roster source for stage7/8/9.
- docs/AX9S_开发执行路由图.md is a pure route-map candidate navigation asset; it does not act as current task source, state source, execution log, full backlog, or execution-order authority.
- route-map near-end sync is warning-only: state alignment may emit a prompt when AX9S hints lag behind product_task_library, but that prompt is not a release blocker.
- Canonical readiness is unchanged by this scoped-execution round.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.

Script Check Summary (PTL-GOV-105 closeout attempt before this alignment packet):
- doctor.ps1: PASS
- check-task-packet.ps1: PASS
- check-state-alignment.ps1: PASS
- validate-contracts.ps1: PASS
- run-golden.ps1: PASS
- run-governance-contracts.ps1: PASS
- lint-drift.ps1: PASS
- check-handoff-dependencies.ps1: PASS
- python tests/run_tests.py: FAIL (isolated to stale test assertions in tests/test_stage12_extractors.py)
- check-final-gate.ps1: FAIL (due to the same stale test assertions)

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
- Source blueprint registry: control/source_blueprint_registry.yaml
- Operator roster defaults: control/operator_assignment_roster_defaults.yaml
- Auto dev task packet template: docs/自动开发任务包模板.md
