# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-INT-102-p4-repository-boundary-hardening (SCOPED_EXECUTION; this window first synchronized PTL-INT-101-p3-policy-validator-boundary-split as completed in control/product_task_library.yaml and control/product_module_registry.yaml with local commit 8c7eea3, then activated P4 to perform a behavior-equivalent repository boundary responsibility split inside allowed storage/control/test paths only; public entrypoints stay in place, current_mainline_next_candidate remains unset, and this does not approve external release, Stage8 real execution, or Stage9 payment/delivery/refund)
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
- switch control/current_task.yaml active packet to PTL-INT-102-p4-repository-boundary-hardening in SCOPED_EXECUTION
- sync control/repo_status.md current workstream wording to PTL-INT-102-p4-repository-boundary-hardening
- sync control/product_task_library.yaml so PTL-INT-101-p3-policy-validator-boundary-split is COMPLETED with planning_state=COMPLETED and completed_commit=8c7eea3
- sync control/product_module_registry.yaml so SHARED-RUNTIME-POLICY-CHAIN records P3 completed and STORAGE-REPOSITORY-BOUNDARY records P4 as pending/manual-selection ledger work
- refactor only allowed repository boundary helper responsibilities under src/storage/repository_boundary.py and new helper files
- keep persist_stage_bundle(...), hydrate_stage_bundle(...), get_operational_context(...), and get_transient_preview_context(...) in src/storage/repository_boundary.py
- keep contracts/handoff/schema semantics unchanged
- keep canonical readiness as READY_FOR_POST-REPAIR_MAINLINE_SELECTION
- keep conditional-go as READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
- keep current_mainline_next_candidate unset / non-auto-activated
- keep external software release blocked
- keep external leadpack delivery approval + audit required
- keep Stage 8 real execution governed / approval-gated / blocked by default
- keep Stage 9 real payment/delivery/refund governed / approval-gated / blocked by default
- allow decision-window local commit after required checks pass
- run the required checks and stop for report

Forbidden Actions (current):
- Any docs/** or docs/AX9S_开发执行路由图.md change
- Any contracts/** change
- Any handoff/** change
- Any src/shared/** change
- Any src/stage8_outreach/** change
- Any src/stage9_delivery/** change
- Any src/storage/db.py change
- Any src/storage/repositories/** change
- Any change to control/source_blueprint_registry.yaml
- Any change to control/operator_assignment_roster_defaults.yaml
- Any change to control/review_gate_matrix.yaml
- Any change to control/release_manifest.yaml
- Any change to control/model_release_manifest.yaml
- Any change to control/external_unlock_prerequisite_state.yaml
- Any change to control/future_unlock_decision_state.yaml
- Any change to contracts/release/**
- Any change to contracts/model/**
- Any change that alters canonical readiness
- Any change that alters conditional-go
- Any change that loosens external release / Stage8 / Stage 8 / Stage9 / Stage 9 redlines
- Any change that adds formal object, enum, gate, or exception semantics
- Any automatic current_mainline_next_candidate restoration
- Any execution-window commit
- Any push
- Any automatic transition to the next packet

State Semantics:
- READY_FOR_POST-REPAIR_MAINLINE_SELECTION means the repo can enter formal mainline selection; it does not by itself change external release, Stage8, or Stage9 boundaries.
- READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT remains the scoped conditional-go for internal LeadOps development.
- current_task -> product_task_library -> repo_status is the only active-source priority.
- control/current_task.yaml is the only active execution source.
- PTL-INT-101-p3-policy-validator-boundary-split has been synchronized as COMPLETED in control/product_task_library.yaml with completed_commit=8c7eea3.
- control/product_module_registry.yaml records SHARED-RUNTIME-POLICY-CHAIN completed_packets=[PTL-INT-101-p3-policy-validator-boundary-split] while explicitly keeping future shared-runtime-dependent work possible.
- control/product_module_registry.yaml records STORAGE-REPOSITORY-BOUNDARY pending_packets=[PTL-INT-102-p4-repository-boundary-hardening]; this is a module ledger only and does not replace current_task as the active source.
- PTL-INT-102-p4-repository-boundary-hardening is now the active scoped execution packet.
- P4-P8 remain manual-selection candidates in the product task pool; active execution still depends on dedicated current_task packets.
- This P4 first cut is not an external release approval, not a Stage8 real outreach approval, and not a Stage9 payment/delivery/refund approval.
- P4 runtime_change_in_packet=IN_SCOPE authorizes only internal governed behavior-equivalent repository boundary helper split work in the allowed runtime paths; it does not authorize live execution, external release, or contract/handoff/schema changes.
- control/product_task_library.yaml remains the product mainline task pool and candidate source; it does not replace control/current_task.yaml as the active execution source.
- Execution-level management and reporting should use the P1 -> P8 ladder in control/product_task_library.yaml rather than direction labels such as Stage8 governed touch 深化 / Stage9 governed delivery 深化.
- control/product_module_registry.yaml remains an execution map and product module ledger, not a status source, not a release gate, and not a second product direction source.
- source_blueprint_registry is the only source-blueprint allowlist.
- operator_assignment_roster_defaults is the only stable roster source for stage7/8/9.
- docs/AX9S_开发执行路由图.md is a pure route-map candidate navigation asset; it does not act as current task source, state source, execution log, full backlog, or execution-order authority.
- AX9S remains unchanged in this round; it does not become a status source, execution-order source, or full backlog.
- Canonical readiness is unchanged by this round.
- External leadpack delivery remains gated by approval + audit chain.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.

Current Scoped-Execution Required Checks:
- git status --short --untracked-files=all
- pwsh -NoProfile -ExecutionPolicy Bypass -Command '$paths = @(''control/current_task.yaml'',''control/repo_status.md'',''control/product_task_library.yaml'',''control/product_module_registry.yaml'',''src/storage/repository_boundary.py'',''src/storage/repository_bundle_io.py'',''src/storage/repository_context_projection.py'',''tests/test_stage12_extractors.py'',''tests/test_product_module_registry.py'',''tests/test_internal_repository_boundary.py'',''tests/test_storage_concurrency.py'',''tests/test_internal_operational_loop.py'',''tests/test_internal_operational_hardening.py''); & ''scripts/check-task-packet.ps1'' -PlannedTargetPaths $paths'
- rg -n "def _persist_stage7_bundle|def _persist_stage8_bundle|def _persist_stage9_bundle|def _hydrate_stage7_bundle|def _hydrate_stage8_bundle|def _hydrate_stage9_bundle|def _build_operational_context|def _build_transient_preview_context|def _bundle_object_refs|def _bundle_trace_and_audit_refs|def _bundle_governed_context" src/storage/repository_boundary.py
- rg -n "hydrate_stage_bundle|persist_stage_bundle|repository_boundary|writeback|typed_object_refs|transient_preview|operational_context|work_item" tests/test_internal_repository_boundary.py tests/test_storage_concurrency.py tests/test_internal_operational_loop.py tests/test_internal_operational_hardening.py
- python -m pytest tests/test_stage12_extractors.py -q
- python -m pytest tests/test_product_module_registry.py -q
- python -m pytest tests/test_internal_repository_boundary.py -q
- python -m pytest tests/test_storage_concurrency.py -q
- python -m pytest tests/test_internal_operational_loop.py -q
- python -m pytest tests/test_internal_operational_hardening.py -q
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-task-packet.ps1
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-state-alignment.ps1
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-final-gate.ps1
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/clean-python-cache.ps1
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
