# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-I100-116-stage4-public-verification-adapters (ACTIVE; Stage4 public verification adapter first cut. This packet may consume Stage3 UNVERIFIED parsed field carriers and Stage2 snapshot refs to produce public-source verification carriers, source refs, snapshot refs, evidence grade, confidence, provider/version, failure taxonomy, and review flags. It does not implement 116A project-manager active-project conflict vertical slice, Stage5 rule decisions, Stage6 product facts, real providers, real outreach, payment, charge, delivery, refund, automated refund execution, external release, or push)
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
- Real external source fetch remains gated by dedicated Stage2 source adapter packets; 114A-114I only open allowlisted/sandbox public-source adapter readback, not uncontrolled live crawling
- Stage3 parser output remains unverified until Stage4 verification; parser carriers must not be written as final facts or customer-visible conclusions.
- Stage4 verification remains public-source only and review-gated for weak, ambiguous, conflicting, or non-replayable evidence.

Product Open Capability Baseline:
- Policy id: PTL-I100-OPEN-CAPABILITY-BASELINE.
- The sold product is evidence packs / lead packs; the software is owner-operated tooling and customer artifact access, not the sold software product itself.
- Except automated refund execution and prohibited non-public/gray capabilities, all business capabilities needed to sell evidence packs are target capabilities and must be implemented through staged controlled opening.
- "Blocked by default" means not live until provider config, sandbox, approval, audit, operator action, field allowlist/masking, and the dedicated current_task packet pass; it does not mean the capability is permanently out of product scope.
- PTL-I100-118 full product operational acceptance is the closure gate for declaring the registered product gaps complete.

Current 116 Scope:
- Activate PTL-I100-116 as the Stage4 public verification adapter packet after PTL-I100-115 completion.
- Consume Stage3 UNVERIFIED parsed carriers and Stage2 snapshot refs to produce public-source verification carriers with object, source, result, verification time, URL, snapshot id, evidence grade, confidence, visibility, provider/version, failure reason, and review flag.
- Target capability state is SANDBOX_READY/readback; do not perform 116A project-manager active-project conflict vertical slice, Stage5 rule hits, Stage6 productization, customer-visible delivery, or final legal conclusion.
- Weak public evidence, ambiguous identifiers, source conflicts, missing replayable snapshots, or missing target identifiers must degrade to review without fabricating facts.
- Keep private/gray source collection, login/captcha/anti-bot bypass, uncontrolled live crawling, real provider calls, real outreach, real payment, real delivery, real refund, automated refund, and external release out of this slice.

Recently Closed:
- PTL-I100-115-stage3-real-parser-ocr-attachments completed and committed locally: 4eca3f3. It added Stage3 real parser carrier/readback seam for HTML/PDF/OCR/Word/Excel/unknown attachment handling, field slices, raw text, locators, confidence, parser audit, parse error taxonomy, and review flags while keeping parser output UNVERIFIED and not customer-visible.
- PTL-I100-114-stage2-real-public-source-adapters completed and committed locally through final subpacket 114I: af13a96. The Stage2 public source adapter series now covers 114A-114I allowlisted/sandbox public-source capture/readback without private/gray collection, login/captcha/anti-bot bypass, uncontrolled live crawling, provider calls, outreach, payment, delivery, refund, automated refund, external release, or push.
- PTL-I100-114I-industry-authority-filing-pages completed and committed locally: af13a96. It extended the Stage2 public source adapter seam for industry authority construction permit, contract filing, completion acceptance, and performance filing carriers, filing type, source coverage report, raw snapshot metadata, source health, retry/timeout/degrade, and fail-closed replay without private/gray collection, login/captcha/anti-bot bypass, uncontrolled live crawling, provider calls, outreach, payment, delivery, refund, automated refund, external release, or push.
- PTL-I100-114H-tenderer-public-notice-pages completed and committed locally: 9e9c033. It extended the Stage2 public source adapter seam for tenderer/procurer/owner owner/correction/candidate/award-result notice carriers, authority lineage, notice type, weak-lineage degrade, raw snapshot metadata, source health, retry/timeout/degrade, and fail-closed replay without private/gray collection, login/captcha/anti-bot bypass, uncontrolled live crawling, provider calls, outreach, payment, delivery, refund, automated refund, external release, or push.
- PTL-I100-114G-tender-agency-public-sites completed and committed locally: a4f71bb. It extended the Stage2 public source adapter seam for tender agency tender/correction/candidate/award-result notice carriers, agency lineage, notice type, raw snapshot metadata, source health, retry/timeout/degrade, and fail-closed replay without private/gray collection, login/captcha/anti-bot bypass, uncontrolled live crawling, provider calls, outreach, payment, delivery, refund, automated refund, external release, or push.
- PTL-I100-114F-government-procurement-public-sites completed and committed locally: 3f6bf5f. It extended the Stage2 public source adapter seam for government procurement public site notice, result, and attachment carriers without private/gray collection, login/captcha/anti-bot bypass, uncontrolled live crawling, provider calls, outreach, payment, delivery, refund, automated refund, external release, or push.
- PTL-I100-114E-national-enterprise-credit-publicity-system completed and committed locally: e93b503. It extended the Stage2 public source adapter seam for national enterprise credit publicity system public enterprise, registration, and abnormal-operation records without private/gray collection, login/captcha/anti-bot bypass, uncontrolled live crawling, provider calls, outreach, payment, delivery, refund, automated refund, external release, or push.
- PTL-I100-114D-credit-china-public-records completed and committed locally: e75a461. It extended the Stage2 public source adapter seam for Credit China public credit, administrative penalty, and credit exception records without private/gray collection, login/captcha/anti-bot bypass, uncontrolled live crawling, provider calls, outreach, payment, delivery, refund, automated refund, external release, or push.
- PTL-I100-114C-national-construction-market-platform completed and committed locally: 2c403d6. It extended the Stage2 public source adapter seam for national construction market platform public enterprise/personnel/project records without private/gray collection, login/captcha/anti-bot bypass, uncontrolled live crawling, provider calls, outreach, payment, delivery, refund, automated refund, external release, or push.
- PTL-I100-114B-provincial-bidding-platforms completed and committed locally: 6b4f91b. It extended the Stage2 public source adapter seam for provincial bidding platform public notice/attachment sources without private/gray collection, login/captcha/anti-bot bypass, uncontrolled live crawling, provider calls, outreach, payment, delivery, refund, automated refund, external release, or push.
- PTL-I100-114A-local-public-resource-trading-centers completed and committed locally: 7de630d. It added Stage2 public source adapter seam, controlled sandbox transport, raw HTML/PDF/attachment snapshot metadata, object-storage-backed replay, source health, retry/timeout/rate-limit/degrade carriers, and public-boundary tests without private/gray collection, login/captcha/anti-bot bypass, uncontrolled live crawling, provider calls, outreach, payment, delivery, refund, automated refund, external release, or push.
- PTL-I100-113-stage1-scheduler-production-loop completed and committed locally: ce733ba. It added Stage1 scheduler task creation, execution windows, H-01 authority consumption, durable queue readback, lease/retry/pause/resume/dead-letter, replay, audit refs, and explicit Stage2 handoff intent without executing real Stage2 fetch, private/gray collection, provider calls, outreach, payment, delivery, refund, automated refund, external release, or push.
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
- update Stage4 verification files listed by current_task for the 116 public verification adapter first cut only
- update local object storage / repository boundary files listed by current_task only when needed for replayable snapshot refs or verification readback
- update control/product_module_registry.yaml only if new Stage4/verification/runtime files must be registered
- update control/current_task.yaml, control/repo_status.md, control/product_task_library.yaml, and control/product_acceptance_checklist.yaml for 116 status
- update targeted tests listed in control/current_task.yaml
- run required checks and commit locally if all checks pass and the actual diff remains inside the current task packet

Forbidden Actions (current):
- Any docs/** change
- Any contracts/** change
- Any handoff/** change
- Any scripts/** change
- Any fixtures/** change
- Any Stage1, Stage2, Stage3, or Stage5-9 business runtime change
- Any src/storage/models/** change
- Any docker compose up, container execution, live deployment, migration, or unauthorized production DB connection
- Any private/gray source collection, login bypass, captcha bypass, anti-bot bypass, source allowlist bypass, uncontrolled live crawling, or new source collection
- Any 116A project-manager active-project conflict vertical slice
- Any Stage4 verification output treated as Stage5 rule hit, legal conclusion, or customer-visible final assertion
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
- PTL-I100-113, PTL-I100-114A through PTL-I100-114I, and PTL-I100-115 are completed; PTL-I100-116 is active as the Stage4 public verification adapter packet. PTL-I100-116A through PTL-I100-121 and PTL-I100-118 remain registered task-pool candidates. None is active until control/current_task.yaml explicitly activates it.
- Execution-level management and reporting should use the P1 -> P8 ladder in control/product_task_library.yaml rather than direction labels such as Stage8 governed touch 深化 / Stage9 governed delivery 深化.
- Canonical readiness is unchanged by this activation.
- External leadpack delivery remains gated by approval + audit chain.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.

Current Scoped-Execution Required Checks:
- git status --short --untracked-files=all
- python -m unittest tests.test_stage4_public_verification_adapters -v
- python -m unittest tests.test_stage12_extractors -v
- python -m unittest tests.test_internal_chain.TestInternalChain -v
- python -m unittest tests.test_internal_repository_boundary.TestInternalRepositoryBoundary -v
- python -m unittest tests.test_runtime_governance_guards.TestRuntimeGovernanceGuards -v
- python -m unittest tests.test_product_module_registry -v
- python -m unittest tests.test_product_acceptance_checklist -v
- pwsh -NoProfile -ExecutionPolicy Bypass -Command '$paths = @(''control/current_task.yaml'',''control/repo_status.md'',''control/product_task_library.yaml'',''control/product_module_registry.yaml'',''control/product_acceptance_checklist.yaml'',''src/stage4_verification/**'',''src/storage/object_storage.py'',''src/storage/repositories/__init__.py'',''src/storage/repositories/object_storage_repo.py'',''src/storage/repository_boundary.py'',''tests/test_stage4_public_verification_adapters.py'',''tests/test_stage12_extractors.py'',''tests/test_internal_chain.py'',''tests/test_internal_repository_boundary.py'',''tests/test_runtime_governance_guards.py'',''tests/test_product_module_registry.py'',''tests/test_product_acceptance_checklist.py''); & ''scripts/check-task-packet.ps1'' -PlannedTargetPaths $paths'
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
