# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-I100-144-market-scan-opportunity-discovery-engine (ACTIVE; implements the internal market scan opportunity discovery slice with autonomous run controller, stage state machine, opportunity candidate priority, why_analyze/why_skip, and no manual URL picker as the primary flow. This packet does not execute Stage2 fetch, real provider calls, outreach, payment, delivery, refund, customer download, or public software release.)
Current Full-Repair Program Status: FULL_REPAIR_COMPLETE_REVIEW_READY
Candidate Gap Active: false
Strategic Branch Active: false
Closure Review Active: false
Closure Review Completed: true
Mainline Selection Ready: true
C-group Enum Freeze: CONFIRMED
Capability Adjudication Source: control/product_task_library.yaml#open_capability_policy and D13 能力总表与放行边界总表

Current Controlled Opening Boundaries:
- External software release is a controlled-opening capability: it requires controlled-opening gate, release checklist, approval chain, audit chain, operator action, rollback/suspension path, and passing regression before any live/public action.
- Stage 8 real execution is a controlled-opening capability: it requires provider config, sandbox pass, approval/audit, quiet-hours/frequency/opt-out enforcement, operator action, and acceptance before live execution.
- Stage 9 real payment/delivery/refund is a controlled-opening capability: payment, delivery, and real refund require provider config, sandbox/live-pilot evidence, approval/audit, operator action, reconciliation/writeback, and acceptance before live execution.
- Automated refund execution remains excluded; refund handling is manual exception record, manual approval/audit, and governed review only.
- PTL-I100-143G is completed and registered the public-web capture escalation, captcha automated challenge resolution/resume, and implementation order before runtime packets continue.
- PTL-I100-144A synchronized controlled-opening semantics and is closed; PTL-I100-144 is the active internal market scan opportunity discovery packet and does not execute provider calls, outreach, payment, delivery, refund, customer download, or public release.

Product Open Capability Baseline:
- Policy id: PTL-I100-OPEN-CAPABILITY-BASELINE.
- The sold product is evidence packs / lead packs; the software is owner-operated tooling and customer artifact access, not the sold software product itself.
- Except automated refund execution, all business capabilities needed to sell evidence packs are target capabilities and must be implemented through staged controlled opening.
- "Controlled opening" means not live until provider config, sandbox, approval, audit, operator action, field allowlist/masking, rollback/suspension, and the controlled-opening gate pass; it does not mean the capability is permanently out of product scope.

Current 144 Scope:
- Implement Stage1 market scan opportunity discovery as an internal owner-operated product slice.
- Produce opportunity candidates, analysis priority, why_analyze/why_skip/review reasons, run controller, stage state machine, and repository-backed readback.
- Keep manual URL selection out of the primary flow.
- Keep Stage2 fetch, provider calls, outreach, payment, delivery, customer download, refund, automated refund, and public release unexecuted.

Recently Closed:
- PTL-I100-144A-controlled-opening-sync closed after controlled-opening semantics and status assets were synchronized.
- PTL-I100-143G-public-web-capture-doc-sync-and-order-review completed and committed locally: 64efed4.
- PTL-I100-143F-public-web-capture-and-captcha-task-pool-sync completed and committed locally: 5f71320.
- PTL-I100-132-owner-operator-frontend-productization-workbench completed and committed locally before the 143 series.

Allowed Actions (current):
- Ordinary internal direct-dev may update paths required by the current human goal after impact localization.
- Task packet / scoped subpacket windows must update only paths declared in control/current_task.yaml for the active packet.
- Synchronize docs/control/contracts/scripts/runtime/tests from hard-boundary language to controlled-opening semantics.
- Run relevant checks and commit locally when human requested or when the scoped verification is complete; direct-dev is not blocked by missing full final gate, but unverified items must be reported.

Forbidden Actions (current):
- Any path outside control/current_task.yaml declared scope when a task packet / scoped subpacket window is active.
- Any automated refund implementation or automated refund enablement.
- Any real provider call, real model provider call, real outreach, real CRM sync, real quote send, real payment/delivery/refund, real customer download, or public release during this sync.
- Any schema/enum/gate/exception semantic addition.
- Any push.

State Semantics:
- READY_FOR_POST-REPAIR_MAINLINE_SELECTION means the repo can enter formal mainline selection; it does not by itself execute external release, Stage8, or Stage9 live actions.
- READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT remains the scoped conditional-go for internal LeadOps development.
- current_task -> product_task_library -> repo_status is the active-source priority for task packet / scoped subpacket windows.
- DIRECT_DEV_DEFAULT is the default for ordinary internal development and does not require switching control/current_task.yaml before work.
- control/current_task.yaml is the active execution source only when a task packet / scoped subpacket window is active.
- control/product_task_library.yaml remains the product mainline task pool and candidate source; it does not replace control/current_task.yaml inside task packet windows and does not block ordinary direct-dev.
- docs/AX9S_开发执行路由图.md is a pure route-map candidate navigation asset; it does not act as current task source, state source, execution log, full backlog, or execution-order authority.
- Execution-level management and reporting should use the P1 -> P8 ladder in control/product_task_library.yaml rather than direction labels such as Stage8 governed touch 深化 / Stage9 governed delivery 深化.

Current Scoped-Execution Required Checks:
- git status --short --untracked-files=all
- python -m unittest tests.test_stage1_market_scan -v
- python -m unittest tests.test_stage1_scheduler -v
- python -m unittest tests.test_api_transport_bootstrap -v
- python -m unittest tests.test_internal_repository_boundary.TestInternalRepositoryBoundary -v
- python -m unittest tests.test_runtime_governance_guards.TestRuntimeGovernanceGuards -v
- python -m unittest tests.test_product_module_registry -v
- python -m unittest tests.test_product_runtime_architecture_map -v
- python -m unittest tests.test_product_operability_gap_matrix -v
- python -m unittest tests.test_product_acceptance_checklist -v
- python -m unittest tests.test_stage12_extractors.TestStage12Extractors.test_planning_surfaces_keep_transition_safe_active_source_relationship -v
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
- Product operability gap matrix: control/product_operability_gap_matrix.yaml
- Source blueprint registry: control/source_blueprint_registry.yaml
- Operator roster defaults: control/operator_assignment_roster_defaults.yaml
- Auto dev task packet template: docs/自动开发任务包模板.md
