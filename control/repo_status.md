# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-I100-112A-production-platform-storage-seam (ACTIVE; production platform infrastructure first knife. This packet implements storage backend seam / SQLAlchemy-Postgres opt-in readiness / infra health-readback only. It does not activate real provider calls, real outreach, real payment gateway, real charge, real delivery, real refund, automated refund execution, external release, or push)
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
- Automated refund execution remains excluded; refund handling is manual exception record, manual approval/audit, and governed review only

Product Open Capability Baseline:
- Policy id: PTL-I100-OPEN-CAPABILITY-BASELINE.
- The sold product is evidence packs / lead packs; the software is owner-operated tooling and customer artifact access, not the sold software product itself.
- Except automated refund execution and prohibited non-public/gray capabilities, all business capabilities needed to sell evidence packs are target capabilities and must be implemented through staged controlled opening.
- "Blocked by default" means not live until provider config, sandbox, approval, audit, operator action, field allowlist/masking, and the dedicated current_task packet pass; it does not mean the capability is permanently out of product scope.
- PTL-I100-118 full product operational acceptance is the closure gate for declaring the registered product gaps complete.

Current 112A Scope:
- Activate PTL-I100-112A as the first implementation slice of PTL-I100-112-production-platform-infrastructure.
- Implement production storage backend seam and SQLAlchemy/Postgres opt-in readiness/readback.
- Preserve default json-file behavior and sqlite opt-in behavior.
- Require fast-fail/no-silent-fallback for unsupported or misconfigured production backends.
- Expose storage/infra health/readiness through existing Settings/API bootstrap surfaces.
- Keep migration execution, Redis/worker runtime, object storage, Docker Compose, monitoring dashboards, real provider calls, real outreach, real payment, real delivery, and automated refund out of this first slice.

Recently Closed:
- PTL-I100-111F-open-capability-registry-route-doc-sync completed and committed locally: 1c403c7. It synchronized PTL-I100-OPEN-CAPABILITY-BASELINE into product_module_registry, AX9S route navigation, D1-D14 appendix tables, and tests.
- PTL-I100-111A provider adapter config/sandbox/readback seam is completed via commit c279fd5. It did not call real providers or execute live touch/payment/delivery/refund.

Allowed Actions (current):
- update src/shared/settings.py storage/infra readiness for 112A
- update src/storage/db.py and add storage SQLAlchemy/Postgres seam files listed by current_task
- update src/api/main.py bootstrap/readback only if needed for storage/infra readiness projection
- update control/product_module_registry.yaml only if new runtime files must be registered
- update targeted tests listed in control/current_task.yaml
- run required checks and commit locally if all checks pass and the actual diff remains inside the current task packet

Forbidden Actions (current):
- Any contracts/** change
- Any handoff/** change
- Any scripts/** change
- Any fixtures/** change
- Any Stage1-9 business runtime change
- Any src/storage/models/** change
- Any true external/live provider call
- Any real production database migration or unauthorized production DB connection
- Any Redis/worker full runtime, object storage, Docker Compose runtime, or monitoring dashboard implementation in 112A
- Any change that loosens external release / Stage8 / Stage 8 / Stage9 / Stage 9 redlines
- Any change that adds formal business object, enum, release gate, or exception semantics
- Any real LeadPack external delivery or client-visible formal export/page release
- Any real touch, payment, delivery, or refund
- Any automated refund program
- Any push

State Semantics:
- READY_FOR_POST-REPAIR_MAINLINE_SELECTION means the repo can enter formal mainline selection; it does not by itself change external release, Stage8, or Stage9 boundaries.
- READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT remains the scoped conditional-go for internal LeadOps development.
- current_task -> product_task_library -> repo_status is the only active-source priority.
- control/current_task.yaml is the only active execution source.
- control/product_task_library.yaml remains the product mainline task pool and candidate source; it does not replace control/current_task.yaml as the active execution source.
- docs/AX9S_开发执行路由图.md is a pure route-map candidate navigation asset; it does not act as current task source, state source, execution log, full backlog, or execution-order authority.
- PTL-I100-112A is active; later 112 slices for queue/worker, object storage, Docker/Compose, and monitoring require separate dedicated current_task packets.
- PTL-I100-111B/111C/111D/111E and PTL-I100-113 through PTL-I100-121 remain registered task-pool candidates. None is active until control/current_task.yaml explicitly activates it.
- Execution-level management and reporting should use the P1 -> P8 ladder in control/product_task_library.yaml rather than direction labels such as Stage8 governed touch 深化 / Stage9 governed delivery 深化.
- Canonical readiness is unchanged by this activation.
- External leadpack delivery remains gated by approval + audit chain.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.

Current Scoped-Execution Required Checks:
- git status --short --untracked-files=all
- python -m unittest tests.test_storage_concurrency -v
- python -m unittest tests.test_api_transport_bootstrap -v
- python -m unittest tests.test_internal_repository_boundary.TestInternalRepositoryBoundary -v
- python -m unittest tests.test_runtime_governance_guards.TestRuntimeGovernanceGuards -v
- python -m unittest tests.test_product_module_registry -v
- pwsh -NoProfile -ExecutionPolicy Bypass -Command '$paths = @(''control/current_task.yaml'',''control/repo_status.md'',''control/product_module_registry.yaml'',''docs/AX9S_开发执行路由图.md'',''src/shared/settings.py'',''src/storage/db.py'',''src/storage/sqlalchemy_backend.py'',''src/storage/sqlalchemy_schema.py'',''src/storage/production_infra_readiness.py'',''src/api/main.py'',''tests/test_storage_concurrency.py'',''tests/test_api_transport_bootstrap.py'',''tests/test_internal_repository_boundary.py'',''tests/test_runtime_governance_guards.py'',''tests/test_product_module_registry.py''); & ''scripts/check-task-packet.ps1'' -PlannedTargetPaths $paths'
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
