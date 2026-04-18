# Auto-Drive Guardrails (Controlled)

1. Codex may continuously advance the following without additional confirmation:
   - Control package completion, contract skeletons, schema-aligned placeholders, and repo-wide skeleton generation.
   - API empty routes/schemas and storage empty repositories/models.
   - Cross-file reference alignment between docs, contracts, handoff, and control.
   - Current scope is internal leadops platform development; no external software release by default.

2. The following actions are limited to skeleton only (no real implementation):
   - Stage1-Stage9 service logic, rule execution, gate evaluation, evidence grading.
   - Any model/release/exception processing beyond catalog and policy placeholders.

3. The following files are append-only (fill tables only; do not change正文):
   - docs/D1_研发_Codex执行手册.md
   - docs/D2_正式对象契约与字段字典.md
   - docs/D3_正式规则码总表与判定说明书.md
   - docs/D6_字段策略字典与客户交付字段规范.md
   - docs/D7_对象级交付矩阵与外发治理规范.md
   - docs/D8_真实竞争者识别可售对象与销售推进规范.md
   - docs/D9_联系对象与销售触达规范.md
   - docs/D10_订单支付交付与治理反馈规范.md
   - docs/D11_测试验收与金标回归清单.md
   - docs/D12_部署发布与运行治理规范.md
   - docs/D13_公开可查边界能力清单.md
   - docs/D14_AI模型治理规范.md

4. Mandatory stop-and-report points:
   - After completing control package updates.
   - After generating all stage1-9 skeletons.
   - After running release/governance scripts (validate-contracts, run-golden, run-governance-contracts, check-release).

5. Actions requiring human confirmation before proceeding:
   - Any change to approval_chain_state.yaml or exception_chain_state.yaml real values.
   - Any move from skeleton stage to minimal implementation design.
   - Any modification that touches delivery matrix, field policy, or approval chain semantics.

6. Transition allowed from "Skeleton Stage" to "Minimal Implementation Design" only when:
   - Control real values are confirmed (owners + approval/exception states).
   - Scripts validate-contracts, run-golden, run-governance-contracts, check-release all pass.
   - C-group enum freeze is manually confirmed.

7. Transition allowed from "Minimal Implementation Design" to "Real Implementation" only when:
   - Formal go/no-go sign-off is completed in docs/正式业务代码开发开工裁决页.md.
   - All release gates, exception policies, and model governance assets have confirmed real values.
   - No D-tier leakage, no unresolved blockers in control/repo_status.md.

Explicit allowances (current):
- Full repo skeleton generation.
- API empty skeleton.
- Storage empty skeleton.
- Minimal implementation design.

Explicitly forbidden (current):
- Real business implementation.
- Database schema creation, migrations, or table operations.
- External system calls or integrations.
- Production release logic or deployment.
- External software release or unaudited leadpack delivery.

Additional constraints:
- C-group enum freeze must complete before any real release/exception/model implementation.
- Any new enum/object/path must follow docs and contracts as the single source of truth.
