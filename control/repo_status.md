# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-I100-144-market-scan-opportunity-discovery-engine (ACTIVE; implements the internal Stage1 market scan opportunity discovery engine and readback before Stage2 capture plan orchestration. This does not enable real website fetch, arbitrary crawler, provider execution, customer download, refund, automated refund, or public software release.)
Current Full-Repair Program Status: FULL_REPAIR_COMPLETE_REVIEW_READY
Candidate Gap Active: false
Strategic Branch Active: false
Closure Review Active: false
Closure Review Completed: true
Mainline Selection Ready: true
C-group Enum Freeze: CONFIRMED
Capability Adjudication Source: control/product_task_library.yaml#open_capability_policy and D13 能力总表与放行边界总表

Current Blockers:
- External software release remains blocked.
- Stage 8 real execution remains governed / approval-gated / blocked by default; PTL-I100-122 only proves approved controlled-provider readback and keeps real provider execution gated.
- Stage 9 real payment/delivery/refund remains governed / approval-gated / blocked by default; PTL-I100-123 only proves approved controlled-provider readback and keeps automated refund excluded.
- Automated refund execution remains excluded; refund handling is manual exception record, manual approval/audit, and governed review only.
- PTL-I100-143G is completed and registered the public-web capture escalation, captcha suspend/resume, and implementation order before runtime packets continue.
- PTL-I100-144 may only implement internal market scan opportunity discovery/readback; Stage2 fetch, crawler execution, captcha bypass, customer-visible claims, provider calls, payment/delivery/refund, and public release remain blocked.

Product Open Capability Baseline:
- Policy id: PTL-I100-OPEN-CAPABILITY-BASELINE.
- The sold product is evidence packs / lead packs; the software is owner-operated tooling and customer artifact access, not the sold software product itself.
- Except automated refund execution and prohibited non-public/gray capabilities, all business capabilities needed to sell evidence packs are target capabilities and must be implemented through staged controlled opening.
- "Blocked by default" means not live until provider config, sandbox, approval, audit, operator action, field allowlist/masking, and the dedicated current_task packet pass; it does not mean the capability is permanently out of product scope.

Current 144 Scope:
- Score and classify public notice candidates by region, project type, amount band, notice stage, objection window, competitor signal, and critical field completeness.
- Emit opportunity candidates, analysis priority, why_analyze, why_skip, review reasons, run controller, stage state machine, and next action readback.
- Persist and replay the market scan carrier through repository-backed readback.
- Keep manual URL picking out of the primary flow.
- Keep real public fetch, uncontrolled crawler, login/captcha/anti-bot bypass, customer-visible claims, and live external execution disabled.

Recently Closed:
- PTL-I100-143G-public-web-capture-doc-sync-and-order-review completed and committed locally: 64efed4.
- PTL-I100-143F-public-web-capture-and-captcha-task-pool-sync completed and committed locally: 5f71320.
- PTL-I100-132-owner-operator-frontend-productization-workbench completed and committed locally before the 143 series.

Allowed Actions (current):
- Update only paths declared in control/current_task.yaml for PTL-I100-144.
- Implement Stage1 market scan/readback and associated repository/API helper/test surfaces.
- Run required checks and commit locally if all checks pass and the actual diff remains inside the current task packet.

Forbidden Actions (current):
- Any docs/** change.
- Any contracts/** change.
- Any handoff/** change.
- Any scripts/** change.
- Any Stage2-9 runtime, shared runtime, storage db schema, migrations, Docker/compose, or fixture change during 144.
- Any private/gray source access, login bypass, captcha bypass, anti-bot bypass, or uncontrolled live crawler.
- Any schema/enum/gate/exception semantic addition.
- Any external software release.
- Any unapproved real provider call, real model provider call, real outreach, real CRM sync, real quote send, real payment/delivery/refund, real customer download, or automated refund during implementation/tests.
- Any push.

State Semantics:
- READY_FOR_POST-REPAIR_MAINLINE_SELECTION means the repo can enter formal mainline selection; it does not by itself change external release, Stage8, or Stage9 boundaries.
- READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT remains the scoped conditional-go for internal LeadOps development.
- current_task -> product_task_library -> repo_status is the only active-source priority.
- control/current_task.yaml is the only active execution source.
- control/product_task_library.yaml remains the product mainline task pool and candidate source; it does not replace control/current_task.yaml as the active execution source.
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
- pwsh -NoProfile -ExecutionPolicy Bypass -Command '$paths = git -c core.quotePath=false ls-files --modified --others --exclude-standard; & ''scripts/check-task-packet.ps1'' -PlannedTargetPaths $paths'
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
