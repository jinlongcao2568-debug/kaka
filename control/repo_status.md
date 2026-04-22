# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-GOV-119-active-task-test-invariant-fix (SCOPED_EXECUTION; active task test invariant fix only; switch the active packet to PTL-GOV-119-active-task-test-invariant-fix; update tests/test_stage12_extractors.py so active task checks validate active execution source invariants instead of fixed current packet IDs; do not enter runtime; do not change control/product_task_library.yaml; do not change control/product_module_registry.yaml; do not change docs/AX9S_开发执行路由图.md; do not change src / contracts / handoff / scripts; canonical readiness unchanged; external software release remains blocked; external leadpack delivery remains approval + audit required; Stage8 real execution and Stage9 real payment/delivery/refund remain governed / approval-gated / blocked by default)
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
- switch control/current_task.yaml active packet to PTL-GOV-119-active-task-test-invariant-fix
- sync control/repo_status.md current workstream wording to PTL-GOV-119-active-task-test-invariant-fix (SCOPED_EXECUTION)
- update tests/test_stage12_extractors.py active task assertions from fixed packet identity checks to active execution source invariants
- keep control/product_task_library.yaml unchanged, with current_mainline_next_candidate staying as the existing MAINLINE_COMPLETE closeout record with task_id=null and packet_id=null
- keep control/product_module_registry.yaml unchanged
- keep docs/AX9S_开发执行路由图.md unchanged
- keep canonical readiness as READY_FOR_POST-REPAIR_MAINLINE_SELECTION
- keep conditional-go as READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
- run the required checks and stop for report

Forbidden Actions (current):
- Any work outside PTL-GOV-119-active-task-test-invariant-fix scoped-execution in this round
- Any change outside declared_changed_paths / allowed_modification_paths
- Any change to AGENTS.md
- Any change to control/product_task_library.yaml
- Any change to control/product_module_registry.yaml
- Any change to docs/AX9S_开发执行路由图.md
- Any change to docs/L0.md, docs/裁决总表.md, docs/D1_研发_Codex执行手册.md, docs/D2_正式对象契约与字段字典.md, docs/D3_正式规则码总表与判定说明书.md, docs/D4_OpenAPI接口契约.md, docs/D5_页面导出与人工复核规范.md, docs/D6_字段策略字典与客户交付字段规范.md, docs/D7_对象级交付矩阵与外发治理规范.md, docs/D8_真实竞争者识别可售对象与销售推进规范.md, docs/D9_联系对象与销售触达规范.md, docs/D10_订单支付交付与治理反馈规范.md, docs/D11_测试验收与金标回归清单.md, docs/D12_部署发布与运行治理规范.md, docs/D13_公开可查边界能力清单.md, docs/D14_AI模型治理规范.md, docs/自动开发任务包模板.md
- Any change to scripts/**
- Any change to contracts/**
- Any change to handoff/**
- Any change to src/**
- Any change to tests/** outside tests/test_stage12_extractors.py
- Any change to control/milestone_status.yaml
- Any change to control/source_blueprint_registry.yaml
- Any change to control/operator_assignment_roster_defaults.yaml
- Any change to control/review_gate_matrix.yaml
- Any change to control/automation_task_packet_rules.yaml
- Any change to control/ax9s_scoped_task_packet_template.yaml
- Any test assertion that binds the active packet to a fixed current packet ID
- Any change that alters canonical readiness
- Any change that loosens external release / Stage8 / Stage9 redlines
- Any change that turns internal preview into external-ready / customer-platform release
- Any automatic next-candidate restoration
- Automatic commit

State Semantics:
- READY_FOR_POST-REPAIR_MAINLINE_SELECTION means the repo can enter formal mainline selection; it does not by itself change external release, Stage8, or Stage9 boundaries.
- READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT remains the scoped conditional-go for internal LeadOps development.
- current_task -> product_task_library -> repo_status is the only active-source priority.
- control/current_task.yaml is the only active execution source.
- PTL-S12-source-route-clock-authority, PTL-S23-public-chain-to-parser-contract, PTL-S34-object-lineage-verification-handoff, PTL-S45-rule-evidence-dual-gate, PTL-S56-project-fact-review-report, PTL-S67-saleable-opportunity-derivation, PTL-S7-price-competitor-offer-resolution, PTL-S78-contact-candidate-compliance-preview, PTL-S89-outreach-writeback-delivery-governance, and PTL-INT-internal-preview-surface-envelope are completed in the product mainline pool.
- PTL-GOV-118-post-mainline-direction-selection has completed and committed as 0e02e85.
- control/product_task_library.yaml current_mainline_next_candidate remains a MAINLINE_COMPLETE closeout record with no task_id and no packet_id.
- There is no automatic next candidate after this closeout.
- Any follow-on new mainline, module split, strengthening packet, or external unlock must be opened as a separate task packet and manually confirmed.
- PTL-GOV-119-active-task-test-invariant-fix is a small governance test packet; it fixes the active task test strategy before Stage7 module boundary refactor continues.
- control/product_task_library.yaml remains the product mainline task pool and candidate source; it does not replace control/current_task.yaml as the active execution source.
- control/product_module_registry.yaml remains an execution map and product module ledger, not a status source, not a release gate, and not a second product direction source; this round does not modify it.
- Stage7 模块边界重构 remains the follow-on direction after this testing strategy root-cause fix; this round does not enter Stage7 runtime.
- source_blueprint_registry is the only source-blueprint allowlist.
- operator_assignment_roster_defaults is the only stable roster source for stage7/8/9.
- docs/AX9S_开发执行路由图.md is a pure route-map candidate navigation asset; it does not act as current task source, state source, execution log, full backlog, or execution-order authority.
- AX9S remains unchanged in this test invariant fix round.
- Canonical readiness is unchanged by this scoped-execution round.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.

Current Scoped-Execution Required Checks:
- git status --short --untracked-files=all
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-task-packet.ps1 -PlannedTargetPaths 'control/current_task.yaml','control/repo_status.md','tests/test_stage12_extractors.py'
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
