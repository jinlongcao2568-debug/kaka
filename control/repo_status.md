# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-INT-internal-preview-productization-strengthening (SCOPED_EXECUTION; post-mainline strengthening packet from the post_mainline_selection recommended direction; this round productizes the existing internal preview PARTIAL_RUNTIME only across preview surface envelope, repository-backed replay precedence, and operator-loop projection / replay contract; keep control/product_task_library.yaml unchanged with the existing MAINLINE_COMPLETE closeout record and no automatic next candidate; do not change control/product_module_registry.yaml or docs/AX9S_开发执行路由图.md; do not change contracts / handoff / scripts; do not change Stage7/8/9 business implementation; canonical readiness unchanged; external software release remains blocked; external leadpack delivery remains approval + audit required; Stage 8 real execution and Stage 9 real payment/delivery/refund remain governed / approval-gated / blocked by default)
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
- switch control/current_task.yaml active packet to PTL-INT-internal-preview-productization-strengthening SCOPED_EXECUTION
- sync control/repo_status.md current workstream wording to PTL-INT-internal-preview-productization-strengthening (SCOPED_EXECUTION)
- strengthen preview surface envelope in src/api/projections.py
- strengthen repository-backed replay precedence in src/storage/repository_boundary.py
- strengthen operator-loop projection / replay contract in src/storage/operator_loop_contracts.py
- update only the allowed internal preview / repository / API transport / operational loop tests
- keep control/product_task_library.yaml unchanged, with current_mainline_next_candidate staying as the existing MAINLINE_COMPLETE closeout record with task_id=null and packet_id=null
- keep control/product_module_registry.yaml unchanged
- keep docs/AX9S_开发执行路由图.md unchanged
- keep canonical readiness as READY_FOR_POST-REPAIR_MAINLINE_SELECTION
- keep conditional-go as READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
- keep external software release blocked
- keep external leadpack delivery approval + audit required
- keep Stage8 / Stage 8 real execution governed / approval-gated / blocked by default
- keep Stage9 / Stage 9 real payment/delivery/refund governed / approval-gated / blocked by default
- run the required checks and stop for report

Forbidden Actions (current):
- Any work outside PTL-INT-internal-preview-productization-strengthening scoped-execution in this round
- Any contract / handoff / script / AX9S / product_task_library / product_module_registry change
- Any src/shared, src/api/routes, src/api/schemas, src/storage/repositories, or stage1-9 runtime change outside the allowed preview/API/storage boundary files
- Any tests/** change outside the explicitly allowed test files
- Any change outside declared_changed_paths / allowed_modification_paths
- Any change to AGENTS.md
- Any change to docs/**
- Any change to src/shared/**
- Any change to src/api/routes/**
- Any change to src/api/schemas/**
- Any change to src/stage1_tasking/**
- Any change to src/stage2_ingestion/**
- Any change to src/stage3_parsing/**
- Any change to src/stage4_verification/**
- Any change to src/stage5_rules_evidence/**
- Any change to src/stage6_fact_review/**
- Any change to src/stage7_sales/**
- Any change to src/stage8_outreach/**
- Any change to src/stage9_delivery/**
- Any change to src/storage/repositories/**
- Any change to tests/** outside the explicit allowed list
- Any change to control/milestone_status.yaml
- Any change to control/source_blueprint_registry.yaml
- Any change to control/operator_assignment_roster_defaults.yaml
- Any change to control/review_gate_matrix.yaml
- Any change to control/automation_task_packet_rules.yaml
- Any change to control/ax9s_scoped_task_packet_template.yaml
- Any change that alters canonical readiness
- Any change that loosens external release / Stage8 / Stage 8 / Stage9 / Stage 9 redlines
- Any automatic next-mainline selection or current_mainline_next_candidate restoration
- Automatic commit

State Semantics:
- READY_FOR_POST-REPAIR_MAINLINE_SELECTION means the repo can enter formal mainline selection; it does not by itself change external release, Stage8, Stage 8, Stage9, or Stage 9 boundaries.
- READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT remains the scoped conditional-go for internal LeadOps development.
- current_task -> product_task_library -> repo_status is the only active-source priority.
- control/current_task.yaml is the only active execution source.
- PTL-GOV-120-post-mainline-direction-advance-to-INT has completed and committed as be0b0b9.
- post_mainline_selection currently recommends Internal preview 产品化强化.
- PTL-INT-internal-preview-productization-strengthening is now the active post-mainline strengthening packet in SCOPED_EXECUTION mode.
- This scoped-execution round changes only the declared internal preview control/runtime/test files; it does not change product_task_library, product_module_registry, AX9S, contracts, handoff, scripts, routes, schemas, repositories, shared runtime, or Stage7/8/9 business implementation.
- control/product_task_library.yaml current_mainline_next_candidate remains a MAINLINE_COMPLETE closeout record with no task_id and no packet_id.
- There is no automatic next candidate after this closeout.
- Any follow-on new mainline or external unlock must be opened as a separate task packet and manually confirmed.
- control/product_task_library.yaml remains the product mainline task pool and candidate source; it does not replace control/current_task.yaml as the active execution source.
- control/product_module_registry.yaml remains an execution map and product module ledger, not a status source, not a release gate, and not a second product direction source; this scoped-execution round does not modify it.
- source_blueprint_registry is the only source-blueprint allowlist.
- operator_assignment_roster_defaults is the only stable roster source for stage7/8/9.
- docs/AX9S_开发执行路由图.md is a pure route-map candidate navigation asset; it does not act as current task source, state source, execution log, full backlog, or execution-order authority.
- AX9S is unchanged in this scoped-execution round; it does not become a status source, execution-order source, or full backlog.
- Canonical readiness is unchanged by this scoped-execution round.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.
- External software release remains blocked.
- Stage 8 real execution remains governed / approval-gated / blocked by default.
- Stage 9 real payment/delivery/refund remains governed / approval-gated / blocked by default.

Current Scoped-Execution Required Checks:
- git status --short --untracked-files=all
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-task-packet.ps1 -PlannedTargetPaths 'control/current_task.yaml','control/repo_status.md','src/api/projections.py','src/storage/repository_boundary.py','src/storage/operator_loop_contracts.py','tests/test_internal_surface_preview.py','tests/test_internal_repository_boundary.py','tests/test_api_transport_bootstrap.py','tests/test_internal_operational_loop.py','tests/test_internal_operational_hardening.py'
- python -m pytest tests/test_internal_surface_preview.py -q
- python -m pytest tests/test_internal_repository_boundary.py -q
- python -m pytest tests/test_api_transport_bootstrap.py -q
- python -m pytest tests/test_internal_operational_loop.py -q
- python -m pytest tests/test_internal_operational_hardening.py -q
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
