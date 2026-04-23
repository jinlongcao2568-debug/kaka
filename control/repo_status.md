# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-INT-104-p8-observability-operator-workbench (SCOPED_EXECUTION; this window first synchronized PTL-INT-103-p7-stage1-to-stage5-contract-runtime-completion as completed in control/product_task_library.yaml and control/product_module_registry.yaml with local commit 2dbfb12, then activated P8 to perform a behavior-equivalent operator/workbench observability split inside allowed api/storage-control/test paths only; src/api/projections.py remains the orchestrator, src/storage/operator_loop_contracts.py remains the public operator-loop module, public response shape stays unchanged, current_mainline_next_candidate remains unset, and this does not approve external release, Stage8 real execution, or Stage9 payment/delivery/refund)
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
- sync control/product_task_library.yaml so PTL-INT-103-p7-stage1-to-stage5-contract-runtime-completion is COMPLETED with planning_state=COMPLETED and completed_commit=2dbfb12
- sync control/product_module_registry.yaml so Stage1/Stage2 runtime ledger records P7 completed while preserving PARTIAL_RUNTIME and non-live semantics
- switch control/current_task.yaml active packet to PTL-INT-104-p8-observability-operator-workbench in SCOPED_EXECUTION
- sync control/repo_status.md current workstream wording to PTL-INT-104-p8-observability-operator-workbench
- refactor only allowed observability/projection helper responsibilities under src/api/projections.py, src/api/workbench_observability.py, src/storage/operator_loop_contracts.py, and src/storage/operator_workbench_projection.py
- keep src/api/projections.py as orchestrator / envelope assembler and src/storage/operator_loop_contracts.py as the public operator-loop module
- keep blocked reason / trace refs / governed context / workbench replay / pending action semantics behavior-equivalent
- keep API public response shape unchanged
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
- Any src/storage/repository_boundary.py change
- Any change to control/source_blueprint_registry.yaml
- Any change to control/operator_assignment_roster_defaults.yaml
- Any change to control/review_gate_matrix.yaml
- Any change to control/release_manifest.yaml
- Any change to control/model_release_manifest.yaml
- Any change to control/external_unlock_prerequisite_state.yaml
- Any change to control/future_unlock_decision_state.yaml
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
- PTL-INT-103-p7-stage1-to-stage5-contract-runtime-completion has been synchronized as COMPLETED in control/product_task_library.yaml with completed_commit=2dbfb12.
- control/product_module_registry.yaml records Stage1/Stage2 completed_packets including PTL-INT-103-p7-stage1-to-stage5-contract-runtime-completion while explicitly preserving PARTIAL_RUNTIME and non-live semantics; this must not be interpreted as "Stage1-5 all follow-up work is permanently complete."
- PTL-INT-104-p8-observability-operator-workbench is now the active scoped execution packet.
- P8 remains the last manual-selection product task in the product task pool; active execution still depends on this dedicated current_task packet.
- This P8 first cut is not an external release approval, not a Stage8 real outreach approval, and not a Stage9 payment/delivery/refund approval.
- P8 runtime_change_in_packet=IN_SCOPE authorizes only internal governed behavior-equivalent operator/workbench observability helper split work in the allowed runtime paths; it does not authorize live execution, external release, or contract/handoff/schema changes.
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
- pwsh -NoProfile -ExecutionPolicy Bypass -Command '$paths = @(''control/current_task.yaml'',''control/repo_status.md'',''control/product_task_library.yaml'',''control/product_module_registry.yaml'',''src/api/projections.py'',''src/api/workbench_observability.py'',''src/storage/operator_loop_contracts.py'',''src/storage/operator_workbench_projection.py'',''tests/test_stage12_extractors.py'',''tests/test_product_module_registry.py'',''tests/test_internal_surface_preview.py'',''tests/test_internal_operational_loop.py'',''tests/test_internal_operational_hardening.py'',''tests/test_internal_repository_boundary.py''); & ''scripts/check-task-packet.ps1'' -PlannedTargetPaths $paths'
- rg -n "blocked_reasons|trace_refs|workbench_replay|operator_loop_projection|governed_context|pending_actions|pending_button_flows|action_history_count|queue_materialized" src/api/projections.py src/storage/operator_loop_contracts.py tests/test_internal_surface_preview.py tests/test_internal_operational_loop.py tests/test_internal_operational_hardening.py tests/test_internal_repository_boundary.py
- python -m pytest tests/test_stage12_extractors.py -q
- python -m pytest tests/test_product_module_registry.py -q
- python -m pytest tests/test_internal_surface_preview.py -q
- python -m pytest tests/test_internal_operational_loop.py -q
- python -m pytest tests/test_internal_operational_hardening.py -q
- python -m pytest tests/test_internal_repository_boundary.py -q
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
