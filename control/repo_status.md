# Repo Status

Current Phase: PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT
Current Readiness Conclusion: READY_FOR_POST-REPAIR_MAINLINE_SELECTION
Current Conditional-Go: READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
Current Workstream: PTL-GOV-116-mainline-candidate-shift-to-INT (SCOPED_EXECUTION; governance-only mainline candidate shift from PTL-S89 to PTL-INT; do not activate PTL-INT; no runtime, contracts, handoff, or scripts change; canonical readiness unchanged; external software release remains blocked; external leadpack delivery remains approval + audit gated; Stage8 real execution and Stage9 real payment/delivery/refund remain governed / approval-gated / blocked by default)
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
- switch control/current_task.yaml active packet to PTL-GOV-116-mainline-candidate-shift-to-INT
- advance control/product_task_library.yaml current_mainline_next_candidate from PTL-S89-outreach-writeback-delivery-governance to PTL-INT-internal-preview-surface-envelope
- mark PTL-S89-outreach-writeback-delivery-governance as COMPLETED / planning_state COMPLETED / is_current_mainline_next_candidate false
- mark PTL-INT-internal-preview-surface-envelope as CANDIDATE / REALITY_ALIGNMENT_QUEUED / is_current_mainline_next_candidate true
- sync control/repo_status.md, docs/AX9S_开发执行路由图.md, and tests/test_stage12_extractors.py to the new candidate pointer and navigation wording
- keep canonical readiness as READY_FOR_POST-REPAIR_MAINLINE_SELECTION
- keep conditional-go as READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT
- run the required checks and stop for report

Forbidden Actions (current):
- Any work outside PTL-GOV-116-mainline-candidate-shift-to-INT scoped-execution in this round
- Any change outside declared_changed_paths / allowed_modification_paths
- Any change to AGENTS.md
- Any change to docs/L0.md, docs/裁决总表.md, docs/D1_研发_Codex执行手册.md, docs/D2_正式对象契约与字段字典.md, docs/D3_正式规则码总表与判定说明书.md, docs/D4_OpenAPI接口契约.md, docs/D5_页面导出与人工复核规范.md, docs/D6_字段策略字典与客户交付字段规范.md, docs/D7_对象级交付矩阵与外发治理规范.md, docs/D8_真实竞争者识别可售对象与销售推进规范.md, docs/D9_联系对象与销售触达规范.md, docs/D10_订单支付交付与治理反馈规范.md, docs/D11_测试验收与金标回归清单.md, docs/D12_部署发布与运行治理规范.md, docs/D13_公开可查边界能力清单.md, docs/D14_AI模型治理规范.md
- Any change to scripts/**
- Any change to src/**
- Any change to contracts/**
- Any change to handoff/**
- Any change to control/product_module_registry.yaml
- Any change to control/milestone_status.yaml
- Any change to control/source_blueprint_registry.yaml
- Any change to control/operator_assignment_roster_defaults.yaml
- Any change to control/review_gate_matrix.yaml
- Any change to control/automation_task_packet_rules.yaml
- Any change to tests/** outside tests/test_stage12_extractors.py
- Any change that alters canonical readiness
- Any change that loosens external release / Stage8 / Stage9 redlines
- Any change that turns AX9S into a status source, execution-order source, or full backlog
- Automatic commit

State Semantics:
- READY_FOR_POST-REPAIR_MAINLINE_SELECTION means the repo can enter formal mainline selection; it does not by itself change external release, Stage8, or Stage9 boundaries.
- READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT remains the scoped conditional-go for internal LeadOps development.
- current_task -> product_task_library -> repo_status is the only active-source priority.
- control/current_task.yaml is the only active execution source.
- PTL-S78-contact-candidate-compliance-preview scoped-execution has completed and committed as b4a704b.
- PTL-GOV-115-mainline-candidate-shift-to-S89 completed and committed as ced9c96.
- PTL-S89-outreach-writeback-delivery-governance scoped-execution has completed and committed as c36dd9d.
- control/product_task_library.yaml current_mainline_next_candidate is now PTL-INT-internal-preview-surface-envelope.
- PTL-INT-internal-preview-surface-envelope is a candidate-pool pointer only; it does not auto-activate as the current execution packet.
- PTL-GOV-116-mainline-candidate-shift-to-INT is the current active packet through control/current_task.yaml.
- PTL-S89-outreach-writeback-delivery-governance is completed; it is no longer the current active packet and no longer the current_mainline_next_candidate.
- control/product_task_library.yaml remains the product mainline task pool and candidate source; it does not replace control/current_task.yaml as the active execution source.
- control/product_module_registry.yaml is an execution map and product module ledger, not a status source, not a release gate, and not a second product direction source.
- source_blueprint_registry is the only source-blueprint allowlist.
- operator_assignment_roster_defaults is the only stable roster source for stage7/8/9.
- docs/AX9S_开发执行路由图.md is a pure route-map candidate navigation asset; it does not act as current task source, state source, execution log, full backlog, or execution-order authority.
- Canonical readiness is unchanged by this scoped-execution round.
- External release remains blocked; Stage8 real execution remains blocked by default; Stage9 real payment/delivery/refund remains blocked by default.

Current Scoped-Execution Required Checks:
- git status --short --untracked-files=all
- pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-task-packet.ps1 -PlannedTargetPaths 'control/current_task.yaml','control/repo_status.md','control/product_task_library.yaml','docs/AX9S_开发执行路由图.md','tests/test_stage12_extractors.py'
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
