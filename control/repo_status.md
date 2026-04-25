# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-I100-117-rule-factory-expansion-and-golden-cases (ACTIVE; Stage5 rule factory expansion and golden cases. This packet may update contracts/rules/rule_catalog.json and src/stage5_rules_evidence/** to expand rule registration, enabled/status/version metadata, input/output contracts, dependency fields/evidence, evidence binding, rule priority, conflict/degrade handling, audit/readback, coverage report, and golden cases. It does not modify schemas/enums/gates/exceptions, bypass evidence gate, treat inference as fact, call real providers, perform real outreach, payment, charge, delivery, refund, automated refund execution, external release, or push)
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
- Project manager active-conflict judgement remains public-source only; same-name matches, missing completion status, missing contract time, or weak evidence must degrade to manual review.
- Stage5 rule outputs remain evidence-gated; rule factory expansion must not bypass evidence_gate_decision / rule_gate_decision / review_request.

Product Open Capability Baseline:
- Policy id: PTL-I100-OPEN-CAPABILITY-BASELINE.
- The sold product is evidence packs / lead packs; the software is owner-operated tooling and customer artifact access, not the sold software product itself.
- Except automated refund execution and prohibited non-public/gray capabilities, all business capabilities needed to sell evidence packs are target capabilities and must be implemented through staged controlled opening.
- "Blocked by default" means not live until provider config, sandbox, approval, audit, operator action, field allowlist/masking, and the dedicated current_task packet pass; it does not mean the capability is permanently out of product scope.
- PTL-I100-118 full product operational acceptance is the closure gate for declaring the registered product gaps complete.

Current 117 Scope:
- Activate PTL-I100-117 as the Stage5 rule factory expansion and golden cases packet after PTL-I100-116A completion.
- Expand Stage5 within the existing RuleEvidenceEngine / RuleRunner / EvidenceBuilder / GateEvaluator architecture; do not create a second rule runtime.
- Consume contracts/rules/rule_catalog.json as the formal rule directory and expose rule registration, enabled/status/version metadata, input/output contracts, dependency fields/evidence, evidence binding, confidence, reason, audit/readback, priority, conflict/degrade status, coverage report, and golden cases.
- Target capability state is INTERNAL_READY/readback; do not modify schemas/enums/gates/exceptions, Stage4 verification logic, Stage6 product facts, customer-visible delivery, or legal conclusions.
- Keep private/gray source collection, non-public personnel privacy data, login/captcha/anti-bot bypass, uncontrolled live crawling, real provider calls, real outreach, real payment, real delivery, real refund, automated refund, and external release out of this slice.

Recently Closed:
- PTL-I100-116A-project-manager-active-conflict-vertical-slice completed and committed locally: 7fba84a. It added a public-source project-manager active-conflict readback carrier, same-name disambiguation trace, time-window overlap judgement, evidence chain, manual review recommendation, and objection-value summary without new Stage2 source adapters, non-public personnel data, illegal identity lookup, same-name-as-fact, customer-visible legal conclusions, real providers, outreach, payment, delivery, refund, automated refund, external release, or push.
- PTL-I100-116-stage4-public-verification-adapters completed and committed locally: 511cd30. It added Stage4 public verification adapter/readback carrier for 8 public verification directions, evidence grade, confidence, source/snapshot refs, failure taxonomy, and fail-closed review behavior without 116A active-conflict judgement, Stage5 rule hits, Stage6 product facts, customer-visible legal conclusions, real providers, outreach, payment, delivery, refund, automated refund, external release, or push.
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
- update contracts/rules/rule_catalog.json and src/stage5_rules_evidence/** for the 117 rule factory expansion only
- update control/product_module_registry.yaml only if new Stage5 runtime/test files must be registered
- update control/current_task.yaml, control/repo_status.md, control/product_task_library.yaml, and control/product_acceptance_checklist.yaml for 117 status
- update targeted tests listed in control/current_task.yaml
- run required checks and commit locally if all checks pass and the actual diff remains inside the current task packet

Forbidden Actions (current):
- Any docs/** change
- Any contracts/** change except contracts/rules/rule_catalog.json
- Any handoff/** change
- Any scripts/** change
- Any fixtures/** change
- Any Stage1, Stage2, Stage3, Stage4, or Stage6-9 business runtime change
- Any contracts file outside contracts/rules/rule_catalog.json
- Any src/storage/models/** change
- Any docker compose up, container execution, live deployment, migration, or unauthorized production DB connection
- Any private/gray source collection, login bypass, captcha bypass, anti-bot bypass, source allowlist bypass, uncontrolled live crawling, or new source collection
- Any schema/enum/gate/exception semantic addition
- Any evidence gate or rule gate bypass
- Any inference treated as verified fact
- Any rule output treated as customer-visible legal conclusion or external assertion
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
- PTL-I100-113, PTL-I100-114A through PTL-I100-114I, PTL-I100-115, PTL-I100-116, and PTL-I100-116A are completed; PTL-I100-117 is active as the Stage5 rule factory expansion and golden cases packet. PTL-I100-119A through PTL-I100-121 and PTL-I100-118 remain registered task-pool candidates. None is active until control/current_task.yaml explicitly activates it.
- Execution-level management and reporting should use the P1 -> P8 ladder in control/product_task_library.yaml rather than direction labels such as Stage8 governed touch 深化 / Stage9 governed delivery 深化.
- Canonical readiness is unchanged by this activation.
- External leadpack delivery remains gated by approval + audit chain.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.

Current Scoped-Execution Required Checks:
- git status --short --untracked-files=all
- python -m unittest tests.test_stage5_rule_factory_expansion -v
- python -m unittest tests.test_stage56_evaluators -v
- python -m unittest tests.test_project_manager_active_conflict_vertical_slice -v
- python -m unittest tests.test_stage12_extractors -v
- python -m unittest tests.test_internal_chain.TestInternalChain -v
- python -m unittest tests.test_runtime_governance_guards.TestRuntimeGovernanceGuards -v
- python -m unittest tests.test_product_module_registry -v
- python -m unittest tests.test_product_acceptance_checklist -v
- pwsh -NoProfile -ExecutionPolicy Bypass -Command '$paths = @(''control/current_task.yaml'',''control/repo_status.md'',''control/product_task_library.yaml'',''control/product_module_registry.yaml'',''control/product_acceptance_checklist.yaml'',''contracts/rules/rule_catalog.json'',''src/stage5_rules_evidence/**'',''tests/test_stage5_rule_factory_expansion.py'',''tests/test_stage56_evaluators.py'',''tests/test_project_manager_active_conflict_vertical_slice.py'',''tests/test_stage12_extractors.py'',''tests/test_internal_chain.py'',''tests/test_runtime_governance_guards.py'',''tests/test_product_module_registry.py'',''tests/test_product_acceptance_checklist.py''); & ''scripts/check-task-packet.ps1'' -PlannedTargetPaths $paths'
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
