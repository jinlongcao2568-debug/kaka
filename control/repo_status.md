# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-INT-internal-preview-surface-envelope (SCOPED_EXECUTION; internal preview mainline closure on existing PARTIAL_RUNTIME; close internal preview surface envelope / repository-backed replay / operator-loop projection only; sync AX9S and stage12 extractor current active packet / near-end hints; do not change Stage7/8/9 business implementation; do not change contracts / handoff / scripts; do not change product_task_library / product_module_registry; canonical readiness unchanged; external software release remains blocked; external leadpack delivery remains approval + audit required; Stage8 real execution and Stage9 real payment/delivery/refund remain governed / approval-gated / blocked by default)
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
- keep control/current_task.yaml active packet as PTL-INT-internal-preview-surface-envelope and switch it from ACTIVATION_ONLY to SCOPED_EXECUTION
- sync control/repo_status.md current workstream to PTL-INT-internal-preview-surface-envelope (SCOPED_EXECUTION)
- close internal preview surface envelope / repository-backed replay / operator-loop projection within the declared 12-file scope
- sync docs/AX9S_开发执行路由图.md and tests/test_stage12_extractors.py to the current PTL-INT active packet / near-end hint wording
- keep canonical readiness as READY_FOR_POST-REPAIR_MAINLINE_SELECTION
- keep conditional-go as READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
- run the required checks and stop for report

Forbidden Actions (current):
- Any work outside PTL-INT-internal-preview-surface-envelope scoped-execution in this round
- Any change outside declared_changed_paths / allowed_modification_paths
- Any change to AGENTS.md
- Any change to docs/L0.md, docs/裁决总表.md, docs/D1_研发_Codex执行手册.md, docs/D2_正式对象契约与字段字典.md, docs/D3_正式规则码总表与判定说明书.md, docs/D4_OpenAPI接口契约.md, docs/D5_页面导出与人工复核规范.md, docs/D6_字段策略字典与客户交付字段规范.md, docs/D7_对象级交付矩阵与外发治理规范.md, docs/D8_真实竞争者识别可售对象与销售推进规范.md, docs/D9_联系对象与销售触达规范.md, docs/D10_订单支付交付与治理反馈规范.md, docs/D11_测试验收与金标回归清单.md, docs/D12_部署发布与运行治理规范.md, docs/D13_公开可查边界能力清单.md, docs/D14_AI模型治理规范.md, docs/自动开发任务包模板.md
- Any change to scripts/**
- Any change to contracts/**
- Any change to handoff/**
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
- Any change to control/product_task_library.yaml
- Any change to control/product_module_registry.yaml
- Any change to control/milestone_status.yaml
- Any change to control/source_blueprint_registry.yaml
- Any change to control/operator_assignment_roster_defaults.yaml
- Any change to control/review_gate_matrix.yaml
- Any change to control/automation_task_packet_rules.yaml
- Any change to tests/** outside tests/test_internal_surface_preview.py, tests/test_internal_repository_boundary.py, tests/test_api_transport_bootstrap.py, tests/test_internal_operational_loop.py, tests/test_internal_operational_hardening.py, tests/test_stage12_extractors.py
- Any change that alters canonical readiness
- Any change that loosens external release / Stage8 / Stage9 redlines
- Any change that turns internal preview into external-ready / customer-platform release
- Automatic commit

State Semantics:
- READY_FOR_POST-REPAIR_MAINLINE_SELECTION means the repo can enter formal mainline selection; it does not by itself change external release, Stage8, or Stage9 boundaries.
- READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT remains the scoped conditional-go for internal LeadOps development.
- current_task -> product_task_library -> repo_status is the only active-source priority.
- control/current_task.yaml is the only active execution source.
- PTL-S89-outreach-writeback-delivery-governance scoped-execution has completed and committed as c36dd9d.
- PTL-GOV-116-mainline-candidate-shift-to-INT has completed and committed as 209c4cd.
- control/product_task_library.yaml current_mainline_next_candidate remains PTL-INT-internal-preview-surface-envelope.
- PTL-INT-internal-preview-surface-envelope remains the current active packet and is now entering SCOPED_EXECUTION through control/current_task.yaml.
- PTL-INT scoped-execution is limited to internal preview surface envelope / repository-backed replay / operator-loop projection closure on existing PARTIAL_RUNTIME.
- PTL-INT does not authorize Stage7/8/9 business implementation change, external release, or customer-platform release.
- control/product_task_library.yaml remains the product mainline task pool and candidate source; it does not replace control/current_task.yaml as the active execution source.
- control/product_module_registry.yaml is an execution map and product module ledger, not a status source, not a release gate, and not a second product direction source.
- source_blueprint_registry is the only source-blueprint allowlist.
- operator_assignment_roster_defaults is the only stable roster source for stage7/8/9.
- docs/AX9S_开发执行路由图.md is a pure route-map candidate navigation asset; it does not act as current task source, state source, execution log, full backlog, or execution-order authority.
- AX9S and stage12 extractor may be synchronized only to the current PTL-INT active packet / near-end hint wording in this round.
- Canonical readiness is unchanged by this scoped-execution round.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.

Current Scoped-Execution Required Checks:
- git status --short --untracked-files=all
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-task-packet.ps1 -PlannedTargetPaths 'control/current_task.yaml','control/repo_status.md','docs/AX9S_开发执行路由图.md','src/api/projections.py','src/storage/repository_boundary.py','src/storage/operator_loop_contracts.py','tests/test_internal_surface_preview.py','tests/test_internal_repository_boundary.py','tests/test_api_transport_bootstrap.py','tests/test_internal_operational_loop.py','tests/test_internal_operational_hardening.py','tests/test_stage12_extractors.py'
- python -m pytest tests/test_internal_surface_preview.py -q
- python -m pytest tests/test_internal_repository_boundary.py -q
- python -m pytest tests/test_api_transport_bootstrap.py -q
- python -m pytest tests/test_internal_operational_loop.py -q
- python -m pytest tests/test_internal_operational_hardening.py -q
- python -m pytest tests/test_stage12_extractors.py -q
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
