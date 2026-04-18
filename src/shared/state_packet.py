from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PolicyDecision:
    policy_key: str
    decision_state: str
    outputs: dict[str, Any]
    reasons: list[str]
    trace: dict[str, Any]
    fallback_used: bool = False


@dataclass(frozen=True)
class CapabilityResolution:
    capability_family: str
    requested_action: str
    capability_mode: str
    decision: str
    review_required: bool
    blocked_reason: str | None
    trace_fields: dict[str, Any]
    governance_additions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GovernanceGuardResult:
    object_type: str
    decision_state: str
    reasons: list[str]
    trace_fields: dict[str, Any]
    governance_additions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticValidationResult:
    semantic_scope: str
    decision_state: str
    reasons: list[str]
    trace_fields: dict[str, Any]
    semantic_additions: dict[str, Any] = field(default_factory=dict)


@dataclass
class StatePacket:
    capability_mode: str
    decision_state: str = "ALLOW"
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    fallback_reasons: list[str] = field(default_factory=list)
    capability_resolutions: dict[str, CapabilityResolution] = field(default_factory=dict)
    capability_trace: list[dict[str, Any]] = field(default_factory=list)
    permission_review_reasons: list[str] = field(default_factory=list)
    permission_blocked_reasons: list[str] = field(default_factory=list)
    permission_short_circuit: bool = False
    permission_decision_state: str = "ALLOW"
    governance_trace: list[dict[str, Any]] = field(default_factory=list)
    governance_review_reasons: list[str] = field(default_factory=list)
    governance_blocked_reasons: list[str] = field(default_factory=list)
    governance_decision_state: str = "ALLOW"
    governance_additions: dict[str, dict[str, Any]] = field(default_factory=dict)
    semantic_trace: list[dict[str, Any]] = field(default_factory=list)
    semantic_review_reasons: list[str] = field(default_factory=list)
    semantic_blocked_reasons: list[str] = field(default_factory=list)
    semantic_decision_state: str = "ALLOW"
    semantic_additions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_capability_resolution(self, resolution: CapabilityResolution) -> None:
        key = f"{resolution.capability_family}:{resolution.requested_action}"
        self.capability_resolutions[key] = resolution
        self.capability_trace.append(dict(resolution.trace_fields))
        self.trace.append(dict(resolution.trace_fields))
        if resolution.decision == "BLOCK":
            self.decision_state = "BLOCK"
            self.permission_decision_state = "BLOCK"
            if resolution.blocked_reason:
                self.blocked_reasons.append(resolution.blocked_reason)
                self.permission_blocked_reasons.append(resolution.blocked_reason)
            if resolution.trace_fields.get("short_circuit"):
                self.permission_short_circuit = True
        elif resolution.decision == "REVIEW" and self.decision_state != "BLOCK":
            self.decision_state = "REVIEW"
            if self.permission_decision_state != "BLOCK":
                self.permission_decision_state = "REVIEW"
            if resolution.blocked_reason:
                self.review_reasons.append(resolution.blocked_reason)
                self.permission_review_reasons.append(resolution.blocked_reason)

    def add_governance_guard(self, result: GovernanceGuardResult) -> None:
        self.governance_trace.append(dict(result.trace_fields))
        self.trace.append(dict(result.trace_fields))
        self.governance_additions[result.object_type] = dict(result.governance_additions)
        if result.decision_state == "BLOCK":
            self.decision_state = "BLOCK"
            self.governance_decision_state = "BLOCK"
            self.blocked_reasons.extend(result.reasons)
            self.governance_blocked_reasons.extend(result.reasons)
        elif result.decision_state == "REVIEW" and self.decision_state != "BLOCK":
            self.decision_state = "REVIEW"
            if self.governance_decision_state != "BLOCK":
                self.governance_decision_state = "REVIEW"
            self.review_reasons.extend(result.reasons)
            self.governance_review_reasons.extend(result.reasons)

    def add_semantic_validation(self, result: SemanticValidationResult) -> None:
        self.semantic_trace.append(dict(result.trace_fields))
        self.trace.append(dict(result.trace_fields))
        self.semantic_additions[result.semantic_scope] = dict(result.semantic_additions)
        if result.decision_state == "BLOCK":
            self.decision_state = "BLOCK"
            self.semantic_decision_state = "BLOCK"
            self.blocked_reasons.extend(result.reasons)
            self.semantic_blocked_reasons.extend(result.reasons)
        elif result.decision_state in ("REVIEW", "HOLD") and self.decision_state != "BLOCK":
            self.decision_state = "REVIEW"
            if self.semantic_decision_state != "BLOCK":
                self.semantic_decision_state = "REVIEW"
            self.review_reasons.extend(result.reasons)
            self.semantic_review_reasons.extend(result.reasons)
        elif result.decision_state == "FALLBACK" and self.decision_state == "ALLOW":
            self.decision_state = "FALLBACK"
            if self.semantic_decision_state == "ALLOW":
                self.semantic_decision_state = "FALLBACK"
            self.fallback_reasons.extend(result.reasons)

    def add_decision(self, decision: PolicyDecision) -> None:
        self.outputs[decision.policy_key] = dict(decision.outputs)
        self.trace.append(dict(decision.trace))
        if decision.decision_state == "BLOCK":
            self.decision_state = "BLOCK"
            self.blocked_reasons.extend(decision.reasons)
        elif decision.decision_state == "REVIEW" and self.decision_state != "BLOCK":
            self.decision_state = "REVIEW"
            self.review_reasons.extend(decision.reasons)
        elif decision.decision_state == "FALLBACK" and self.decision_state == "ALLOW":
            self.decision_state = "FALLBACK"
            self.fallback_reasons.extend(decision.reasons)
        elif decision.fallback_used:
            self.fallback_reasons.extend(decision.reasons)

    def merged_outputs(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for decision_output in self.outputs.values():
            merged.update(decision_output)
        return merged

    def resolve(self, field_name: str, default: Any = None) -> Any:
        merged = self.merged_outputs()
        return merged.get(field_name, default)

    def capability_resolution(self, capability_family: str, requested_action: str) -> CapabilityResolution | None:
        key = f"{capability_family}:{requested_action}"
        return self.capability_resolutions.get(key)

    def capability_governance(self) -> list[dict[str, Any]]:
        return [dict(resolution.governance_additions) for resolution in self.capability_resolutions.values()]


__all__ = ["CapabilityResolution", "GovernanceGuardResult", "PolicyDecision", "SemanticValidationResult", "StatePacket"]
