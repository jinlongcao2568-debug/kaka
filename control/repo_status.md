# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-I100-113-stage1-scheduler-production-loop (ACTIVE; Stage1 scheduler production loop. This packet may implement internal task scheduling, execution windows, route/source family consumption, durable queue readback, retry, pause/resume, conflict detection, and audit logs. It does not fetch real external sources, connect real providers, bypass public/source governance, run Stage2 crawlers, perform real outreach, payment, charge, delivery, refund, automated refund execution, external release, or push)
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
- Real external source fetch remains blocked until dedicated Stage2 source adapter packets

Product Open Capability Baseline:
- Policy id: PTL-I100-OPEN-CAPABILITY-BASELINE.
- The sold product is evidence packs / lead packs; the software is owner-operated tooling and customer artifact access, not the sold software product itself.
- Except automated refund execution and prohibited non-public/gray capabilities, all business capabilities needed to sell evidence packs are target capabilities and must be implemented through staged controlled opening.
- "Blocked by default" means not live until provider config, sandbox, approval, audit, operator action, field allowlist/masking, and the dedicated current_task packet pass; it does not mean the capability is permanently out of product scope.
- PTL-I100-118 full product operational acceptance is the closure gate for declaring the registered product gaps complete.

Current 113 Scope:
- Activate PTL-I100-113 as the Stage1 scheduler production loop packet.
- Implement internal scheduler task creation, execution windows, source family / route graph / clock authority consumption, queue readback, retry, pause/resume, conflict detection, and scheduling audit.
- Stage1 may emit explicit Stage2 handoff intent, but this packet must not perform real Stage2 fetch or crawler execution.
- Use public/source blueprint governance; do not add private, gray, login-gated, captcha-bypass, or anti-bot-bypass source behavior.
- Keep real provider calls, real outreach, real payment, real delivery, real refund, automated refund, and external release out of this slice.

Recently Closed:
- PTL-I100-112F-monitoring-alerting-readiness completed and committed locally: 0fe9212. It added internal monitoring / alerting / incident readiness, persistence/readback, and stale-ref fail-closed behavior without connecting external observability/APM/paging providers, sending real alerts, running incident automation, opening real provider calls, real outreach, real payment, real delivery, real refund, automated refund execution, external release, or push.
- PTL-I100-112E-backup-restore-rollback-readiness completed and committed locally: bea524b. It added local backup manifest, restore dry-run, rollback readiness, and audit/readback projection without connecting external backup services, performing destructive restore, running migration, opening real provider calls, real outreach, real payment, real delivery, real refund, automated refund execution, external release, or push.
- PTL-I100-112D-docker-compose-health-readiness completed and committed locally: c8ace6f. It added Docker/Compose local stack definition and health/readiness projection without running containers, connecting external services, executing migration, opening real provider calls, real outreach, real payment, real delivery, real refund, automated refund execution, external release, or push.
- PTL-I100-112C-object-storage-snapshot-durability completed and committed locally: 52d2ad3.
- PTL-I100-112B-production-queue-worker-durability completed and committed locally: 1f2471d.
- PTL-I100-112A-production-platform-storage-seam completed and committed locally: e3870ab.
- PTL-I100-ACCEPTANCE-CHECKLIST-SYNC completed and committed locally: 421816d.
- PTL-I100-111F-open-capability-registry-route-doc-sync completed and committed locally: 1c403c7.
- PTL-I100-111A provider adapter config/sandbox/readback seam is completed via commit c279fd5.

Allowed Actions (current):
- update Stage1 scheduler files listed by current_task
- update storage queue/repository files listed by current_task only for Stage1 scheduler readback/persistence
- update Stage1 API route/schema/bootstrap files listed by current_task only if needed for scheduler readback
- update control/product_module_registry.yaml only if new Stage1/storage/runtime files must be registered
- update control/current_task.yaml, control/repo_status.md, control/product_task_library.yaml, and control/product_acceptance_checklist.yaml for 113 activation/status
- update targeted tests listed in control/current_task.yaml
- run required checks and commit locally if all checks pass and the actual diff remains inside the current task packet

Forbidden Actions (current):
- Any docs/** change
- Any contracts/** change
- Any handoff/** change
- Any scripts/** change
- Any fixtures/** change
- Any Stage2-9 business runtime change
- Any src/storage/models/** change
- Any docker compose up, container execution, live deployment, migration, or unauthorized production DB connection
- Any real external source fetch, private/gray source collection, login bypass, captcha bypass, anti-bot bypass, or source allowlist bypass
- Any true external/live provider call
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
- PTL-I100-112 is completed through 112A-112F; production/live pilots still require later dedicated packets.
- PTL-I100-113 is active; PTL-I100-114 through PTL-I100-121 and PTL-I100-118 remain registered task-pool candidates. None is active until control/current_task.yaml explicitly activates it.
- Execution-level management and reporting should use the P1 -> P8 ladder in control/product_task_library.yaml rather than direction labels such as Stage8 governed touch 深化 / Stage9 governed delivery 深化.
- Canonical readiness is unchanged by this activation.
- External leadpack delivery remains gated by approval + audit chain.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.

Current Scoped-Execution Required Checks:
- git status --short --untracked-files=all
- python -m unittest tests.test_stage1_scheduler -v
- python -m unittest tests.test_stage12_extractors -v
- python -m unittest tests.test_internal_chain.TestInternalChain -v
- python -m unittest tests.test_internal_repository_boundary.TestInternalRepositoryBoundary -v
- python -m unittest tests.test_api_transport_bootstrap -v
- python -m unittest tests.test_runtime_governance_guards.TestRuntimeGovernanceGuards -v
- python -m unittest tests.test_product_module_registry -v
- python -m unittest tests.test_product_acceptance_checklist -v
- pwsh -NoProfile -ExecutionPolicy Bypass -Command '$paths = @(''control/current_task.yaml'',''control/repo_status.md'',''control/product_task_library.yaml'',''control/product_module_registry.yaml'',''control/product_acceptance_checklist.yaml'',''src/stage1_tasking/__init__.py'',''src/stage1_tasking/scheduler.py'',''src/stage1_tasking/service.py'',''src/stage1_tasking/models.py'',''src/storage/worker_queue.py'',''src/storage/repositories/__init__.py'',''src/storage/repositories/worker_queue_repo.py'',''src/storage/repositories/stage1_scheduler_repo.py'',''src/api/routes/stage1.py'',''src/api/schemas/stage1.py'',''src/api/main.py'',''tests/test_stage1_scheduler.py'',''tests/test_stage12_extractors.py'',''tests/test_internal_chain.py'',''tests/test_internal_repository_boundary.py'',''tests/test_api_transport_bootstrap.py'',''tests/test_runtime_governance_guards.py'',''tests/test_product_module_registry.py'',''tests/test_product_acceptance_checklist.py''); & ''scripts/check-task-packet.ps1'' -PlannedTargetPaths $paths'
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
