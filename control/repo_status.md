# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund (ACTIVE; binds WeCom/email/SMS/phone/CRM/quote/payment/delivery provider targets through unified provider config, credential redaction, sandbox evidence, callback validation, and kill-switch/suspension readback. This does not execute real external provider calls in default tests and does not implement automated refunds.)
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
- PTL-I100-118R is completed and registered the remaining real-world product gaps as PTL-I100-127 through PTL-I100-131.
- PTL-I100-127 has added owner/customer frontend surfaces.
- PTL-I100-128 validates controlled manual public snapshots and must not weaken public-source boundary redlines.
- PTL-I100-129 binds real provider targets but must not execute a real external provider call during default implementation/tests.
- No private/gray source, login bypass, captcha bypass, anti-bot bypass, uncontrolled live crawler, unapproved real provider call, unapproved real outreach, unapproved real CRM sync, unapproved real quote send, unapproved real payment capture/charge, unapproved real delivery fulfillment, unapproved real customer download, real refund, or automated refund may run during 129.

Product Open Capability Baseline:
- Policy id: PTL-I100-OPEN-CAPABILITY-BASELINE.
- The sold product is evidence packs / lead packs; the software is owner-operated tooling and customer artifact access, not the sold software product itself.
- Except automated refund execution and prohibited non-public/gray capabilities, all business capabilities needed to sell evidence packs are target capabilities and must be implemented through staged controlled opening.
- "Blocked by default" means not live until provider config, sandbox, approval, audit, operator action, field allowlist/masking, and the dedicated current_task packet pass; it does not mean the capability is permanently out of product scope.
- PTL-I100-118R is the completed post-122/126 reacceptance packet; PTL-I100-129 is the active implementation packet for real provider binding after 127/128 completed.

Current 129 Scope:
- Register and expose explicit provider bindings for WeCom robot, email, SMS/phone, CRM, quote, payment, and delivery.
- Prove provider credentials are redacted, rotation metadata is visible, sandbox evidence and callback validation are replayable, and kill-switch/suspension fail closed.
- Ensure Stage7/8/9 consume the same provider binding summary while keeping provider calls gated and automated refund absent.
- Do not perform default real external provider network calls, bulk sends, real payment capture/charge, real delivery fulfillment, real refund, or automated refund.

Recently Closed:
- PTL-I100-128-real-public-source-field-validation-and-coverage completed and committed locally: 595cd1d.
- PTL-I100-127-owner-operator-frontend-and-customer-portal completed and committed locally: ab1fd01.
- PTL-I100-118S-route-map-post-118r-sync completed and committed locally: 87df294.
- PTL-I100-118R-final-product-operational-reacceptance completed and committed locally: f977b5b; product closeout remains DO_NOT_PRODUCTION_CLOSEOUT and follow-up tasks PTL-I100-127 through PTL-I100-131 are registered.
- PTL-I100-126-production-live-dependency-and-drill-approval completed and committed locally: fc52e19; closeout committed locally: d8608ef.
- PTL-I100-123-approved-payment-delivery-provider-execution-no-auto-refund completed and committed locally: 7fb9e13.
- PTL-I100-124-customer-visible-leadpack-delivery-approval-unlock completed and committed locally: f8c1182.
- PTL-I100-125-approved-crm-quote-provider-execution completed and committed locally: 0809322.
- PTL-I100-122-approved-sales-outreach-provider-execution completed and committed locally: f3cf7e5.
- PTL-I100-118-full-product-operational-acceptance completed product operational acceptance and recorded DO_NOT_CLOSEOUT / BLOCKED_BY_PRODUCT_OPERATIONAL_GAPS via 866f9bf; follow-up tasks 122-126 were registered and later completed.
- PTL-I100-112 through PTL-I100-121C and PTL-I100-111A/B/C/D/E, 113-117, 119/119A are completed as recorded in control/product_task_library.yaml.

Allowed Actions (current):
- Update only 129 provider binding/control/test paths declared in control/current_task.yaml.
- Add provider binding matrix, credential redaction/rotation metadata, sandbox evidence, callback validation, kill-switch/suspension readback, and Stage7/8/9 carrier consumption.
- Run required checks and commit locally if all checks pass and the actual diff remains inside the current task packet.

Forbidden Actions (current):
- Any docs/** change outside docs/AX9S_开发执行路由图.md.
- Any contracts/** change.
- Any handoff/** change.
- Any scripts/** change.
- Any src/** runtime change outside the 129 provider binding paths declared in control/current_task.yaml.
- Any private/gray source access, login bypass, captcha bypass, anti-bot bypass, or uncontrolled live crawler.
- Any schema/enum/gate/exception semantic addition.
- Any external software release.
- Any unapproved real provider call, real outreach, real CRM sync, real quote send, real payment/delivery/refund, real customer download, or automated refund during implementation/tests.
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
- python -m unittest tests.test_real_provider_binding -v
- python -m unittest tests.test_provider_adapter_config -v
- python -m unittest tests.test_stage7_runtime_closure -v
- python -m unittest tests.test_stage8_resolution_closure -v
- python -m unittest tests.test_stage9_impact_executor.TestStage9ImpactExecutor -v
- python -m unittest tests.test_internal_chain.TestInternalChain -v
- python -m unittest tests.test_internal_repository_boundary.TestInternalRepositoryBoundary -v
- python -m unittest tests.test_api_transport_bootstrap -v
- python -m unittest tests.test_runtime_governance_guards.TestRuntimeGovernanceGuards -v
- python -m unittest tests.test_product_module_registry -v
- python -m unittest tests.test_product_acceptance_checklist -v
- python -m unittest tests.test_product_operability_gap_matrix -v
- python -m unittest tests.test_full_product_operational_acceptance -v
- python -m unittest tests.test_stage12_extractors -v
- python -m unittest tests.test_external_unlock_prerequisites -v
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
