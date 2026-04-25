# Stage: stage1_tasking
# Consumes formal objects: task_execution_context, project_identity_strategy, clock_strategy_profile
# Dependent handoff: H-01-STAGE1-TO-STAGE2
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class TaskExecutionContext:
    task_id: str


@dataclass(frozen=True)
class ProjectIdentityStrategy:
    strategy_id: str


@dataclass(frozen=True)
class ClockStrategyProfile:
    clock_profile_id: str


@dataclass(frozen=True)
class Stage1ExecutionWindow:
    window_id: str
    time_range_from: str
    time_range_until: str
    window_start_at: str
    window_due_at: str
    window_priority_policy: str
    window_priority: str
    clock_resolution_rule_id: str
    clock_precedence_rule_id: str
    status: str
    authority_refs: dict[str, str] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Stage1RetryState:
    attempt_count: int
    max_attempts: int
    next_retry_at: str | None = None
    last_error: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Stage1PauseState:
    is_paused: bool
    paused_at: str | None = None
    paused_by: str | None = None
    reason: str | None = None
    resumed_at: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Stage2HandoffIntent:
    handoff_id: str
    consumer_stage: str
    intent_state: str
    fetch_enabled: bool
    crawler_enabled: bool
    real_external_fetch_enabled: bool
    handoff_payload: dict[str, Any]
    consumer_must_not_recompute_fields: list[str]

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Stage1SchedulerTask:
    task_id: str
    project_id: str
    source_family: str
    route_policy_id: str
    source_registry_id: str
    default_route: str
    fallback_route: str
    clock: dict[str, Any]
    window: Stage1ExecutionWindow
    queue_item_id: str
    status: str
    retry_state: Stage1RetryState
    pause_state: Stage1PauseState
    audit_refs: dict[str, str]
    stage2_handoff_intent: Stage2HandoffIntent
    requires_manual_review: bool
    conflict_state: str
    conflict_reasons: list[str]
    created_at: str
    updated_at: str

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["window"] = self.window.as_payload()
        payload["retry_state"] = self.retry_state.as_payload()
        payload["pause_state"] = self.pause_state.as_payload()
        payload["stage2_handoff_intent"] = self.stage2_handoff_intent.as_payload()
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Stage1SchedulerTask":
        window = Stage1ExecutionWindow(**dict(payload["window"]))
        retry_state = Stage1RetryState(**dict(payload["retry_state"]))
        pause_state = Stage1PauseState(**dict(payload["pause_state"]))
        handoff_intent = Stage2HandoffIntent(**dict(payload["stage2_handoff_intent"]))
        return cls(
            task_id=str(payload["task_id"]),
            project_id=str(payload["project_id"]),
            source_family=str(payload["source_family"]),
            route_policy_id=str(payload["route_policy_id"]),
            source_registry_id=str(payload["source_registry_id"]),
            default_route=str(payload["default_route"]),
            fallback_route=str(payload["fallback_route"]),
            clock=dict(payload["clock"]),
            window=window,
            queue_item_id=str(payload["queue_item_id"]),
            status=str(payload["status"]),
            retry_state=retry_state,
            pause_state=pause_state,
            audit_refs={key: str(value) for key, value in dict(payload["audit_refs"]).items()},
            stage2_handoff_intent=handoff_intent,
            requires_manual_review=bool(payload["requires_manual_review"]),
            conflict_state=str(payload["conflict_state"]),
            conflict_reasons=[str(value) for value in payload.get("conflict_reasons", [])],
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
        )


__all__ = [
    "ClockStrategyProfile",
    "ProjectIdentityStrategy",
    "Stage1ExecutionWindow",
    "Stage1PauseState",
    "Stage1RetryState",
    "Stage1SchedulerTask",
    "Stage2HandoffIntent",
    "TaskExecutionContext",
]
