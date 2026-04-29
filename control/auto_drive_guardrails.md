# Auto-Drive Guardrails (Controlled)

1. Codex may continuously advance ordinary internal development without additional task-packet activation when the work is low-risk direct-dev:
   - Code fixes, test fixes, documentation sync, local scripts, and small machine-asset consistency updates.
   - Stage1-Stage9 internal implementation work that does not perform live external execution and does not alter release, approval/audit, schema/migration, or cross-stage machine-contract semantics.
   - Cross-file reference alignment between docs, contracts, handoff, and control.
   - Current scope is internal leadops platform development; no external software release by default.

2. The following actions require controlled task packet / review gate before execution:
   - External release or live external execution.
   - Real outreach, real payment, real delivery, real refund, high-restriction field release, or automated refund enablement.
   - Approval/audit semantics changes, release/readiness gate semantic changes, schema/migration, or cross-stage machine-contract changes.

3. D documents are not append-only by default. They may be edited in正文 or supplements when aligning with AGENTS, human current instructions, code facts, or machine assets; do not create a second formal semantics source.

4. Mandatory stop-and-report points:
   - After completing control package updates.
   - After generating all stage1-9 skeletons.
   - After running release/governance scripts (validate-contracts, run-golden, run-governance-contracts, check-release).

5. Actions requiring human confirmation before proceeding:
   - Any change to approval_chain_state.yaml or exception_chain_state.yaml real values.
   - Any move from ordinary internal execution to live/external execution.
   - Any modification that touches delivery matrix, field policy, or approval chain semantics.

6. Ordinary direct-dev validation:
   - Run the smallest relevant scripts/tests for the touched surface.
   - If a required gate fails because it encodes old AGENTS-incompatible semantics, update the test or gate to the correct current口径 before re-running.

7. Controlled/live transition:
   - Use dedicated task packet / review gate.
   - Confirm release gates, exception policies, approval/audit chain, provider config, sandbox/live-pilot requirements, and operator action before any live external effect.
   - No D-tier leakage, no unresolved live/release blockers in control/repo_status.md.

Explicit allowances (current):
- Ordinary internal code/test/script/document/control implementation.
- Cross-file docs/contracts/handoff/control synchronization.
- Capability development in authorized internal, sandbox, or explicit test environments.

Explicitly forbidden (current):
- Unapproved live external execution.
- Irreversible database migrations or production table operations without explicit approval.
- External system calls or integrations.
- Production release logic or deployment.
- External software release or unaudited leadpack delivery.

Additional constraints:
- C-group enum freeze must complete before any real release/exception/model implementation.
- Any new enum/object/path must follow docs and contracts as the single source of truth.
