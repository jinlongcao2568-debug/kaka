# Stage: stage1_tasking
# Consumes formal objects: task_execution_context, project_identity_strategy, clock_strategy_profile
# Dependent handoff: H-01-STAGE1-TO-STAGE2
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from __future__ import annotations

from typing import Any

from shared.contracts_runtime import ContractStore
from shared.utils import build_id, utc_now_iso
from stage1_tasking.contract_runtime import build_stage1_handoff, build_stage1_inputs
from stage1_tasking.extractors import Stage1Extraction, extract_stage1
from stage1_tasking.models import (
    Stage1ExecutionWindow,
    Stage1PauseState,
    Stage1RetryState,
    Stage1SchedulerTask,
    Stage2HandoffIntent,
)
from storage.repositories.stage1_scheduler_repo import Stage1SchedulerRepository


H01_CONSUMER_MUST_NOT_RECOMPUTE = [
    "source_registry_id",
    "route_policy_id",
    "default_route",
    "fallback_route",
    "clock_resolution_rule_id",
    "clock_precedence_rule_id",
]
STAGE1_SCHEDULER_QUEUE_NAME = "stage1_scheduler_queue"
STAGE2_HANDOFF_INTENT_STATE = "INTENT_ONLY_NO_FETCH"
_BLOCKED_SOURCE_TOKENS = ("PRIVATE", "GRAY", "LOGIN", "CAPTCHA", "ANTI_BOT")
_BLOCKED_LIVE_FLAGS = (
    "live_execution_enabled",
    "external_fetch_enabled",
    "real_external_fetch_enabled",
    "stage2_fetch_enabled",
    "crawler_enabled",
    "provider_call_enabled",
    "real_provider_call_enabled",
    "private_source_enabled",
    "gray_source_enabled",
    "login_bypass_enabled",
    "captcha_bypass_enabled",
    "anti_bot_bypass_enabled",
)


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "live"}
    return bool(value)


def _coerce_window_start(extracted: Stage1Extraction, now: str) -> str:
    return extracted.current_action_start_at_optional or now


def _coerce_window_due(extracted: Stage1Extraction) -> str:
    return extracted.current_action_deadline_at_optional or extracted.time_range_until


def _conflict_state(extracted: Stage1Extraction) -> str:
    if extracted.baseline_collection_state == "BLOCKED":
        return "BLOCKED"
    if extracted.mismatch_reasons or extracted.requires_manual_review:
        return "REVIEW_REQUIRED"
    return "CONSISTENT"


class Stage1Scheduler:
    def __init__(
        self,
        *,
        settings: Any | None = None,
        store: ContractStore | None = None,
        repository: Stage1SchedulerRepository | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or ContractStore.default(settings)
        self.repository = repository or Stage1SchedulerRepository()

    def next_window(self, context: Any) -> Stage1ExecutionWindow:
        payload = self._payload_from_context(context)
        now = str(payload.get("now") or utc_now_iso())
        extracted = extract_stage1(payload, self.store, now=now)
        return self._build_window(payload=payload, extracted=extracted, now=now)

    def create_task(self, context: Any) -> Stage1SchedulerTask:
        payload = self._payload_from_context(context)
        self._assert_internal_scheduler_boundary(payload)
        now = str(payload.get("now") or utc_now_iso())
        extracted = extract_stage1(payload, self.store, now=now)
        window = self._build_window(payload=payload, extracted=extracted, now=now)
        handoff_payload = build_stage1_handoff(
            payload,
            project_id=str(payload["project_id"]),
            context_id=build_id("CTX", str(payload["task_id"])),
            extracted=extracted,
            requires_manual_review=extracted.requires_manual_review,
        )
        stage1_inputs = build_stage1_inputs(payload, extracted=extracted)
        queue_item_id = str(payload.get("queue_item_id") or build_id("S1Q", str(payload["task_id"])))
        audit_refs = {
            "scheduling_audit_id": build_id("S1AUD", str(payload["task_id"])),
            "handoff_id": "H-01-STAGE1-TO-STAGE2",
            "source_registry_id": extracted.source_registry_id,
            "route_policy_id": extracted.route_policy_id,
            "clock_resolution_rule_id": extracted.clock_resolution_rule_id,
            "clock_precedence_rule_id": extracted.clock_precedence_rule_id,
        }
        conflict_reasons = [
            *extracted.mismatch_reasons,
            *extracted.fallback_reasons,
        ]
        task = Stage1SchedulerTask(
            task_id=str(payload["task_id"]),
            project_id=str(payload["project_id"]),
            source_family=extracted.source_family,
            route_policy_id=extracted.route_policy_id,
            source_registry_id=extracted.source_registry_id,
            default_route=extracted.default_route,
            fallback_route=extracted.fallback_route,
            clock={
                "clock_resolution_rule_id": extracted.clock_resolution_rule_id,
                "clock_precedence_rule_id": extracted.clock_precedence_rule_id,
                "time_range_from": extracted.time_range_from,
                "time_range_until": extracted.time_range_until,
            },
            window=window,
            queue_item_id=queue_item_id,
            status="queued",
            retry_state=Stage1RetryState(
                attempt_count=0,
                max_attempts=int(payload.get("max_attempts", 3)),
            ),
            pause_state=Stage1PauseState(is_paused=False),
            audit_refs=audit_refs,
            stage2_handoff_intent=Stage2HandoffIntent(
                handoff_id="H-01-STAGE1-TO-STAGE2",
                consumer_stage="stage2_ingestion",
                intent_state=STAGE2_HANDOFF_INTENT_STATE,
                fetch_enabled=False,
                crawler_enabled=False,
                real_external_fetch_enabled=False,
                handoff_payload=handoff_payload,
                consumer_must_not_recompute_fields=list(H01_CONSUMER_MUST_NOT_RECOMPUTE),
            ),
            requires_manual_review=extracted.requires_manual_review,
            conflict_state=_conflict_state(extracted),
            conflict_reasons=conflict_reasons,
            created_at=now,
            updated_at=now,
        )
        return self.repository.enqueue_task(
            task,
            queue_name=STAGE1_SCHEDULER_QUEUE_NAME,
            queue_payload={
                "scheduler_task": task.as_payload(),
                "stage1_inputs": stage1_inputs,
                "stage2_handoff_intent": task.stage2_handoff_intent.as_payload(),
                "external_fetch_enabled": False,
                "real_external_fetch_enabled": False,
                "crawler_enabled": False,
            },
            priority=int(payload.get("priority", 0)),
            max_attempts=task.retry_state.max_attempts,
            next_run_at=window.window_start_at,
            now=now,
        )

    def readback(self, queue_item_id: str) -> dict[str, Any]:
        return self.repository.readback(queue_item_id)

    def replay(self, queue_item_id: str) -> dict[str, Any]:
        return self.repository.replay(queue_item_id)

    def lease(
        self,
        queue_item_id: str,
        *,
        worker_id: str,
        lease_id: str,
        lease_seconds: int = 60,
        now: str | None = None,
    ) -> Stage1SchedulerTask:
        return self.repository.lease(
            queue_item_id,
            worker_id=worker_id,
            lease_id=lease_id,
            lease_seconds=lease_seconds,
            now=now,
        )

    def retry(
        self,
        queue_item_id: str,
        *,
        worker_id: str,
        lease_id: str,
        error: str,
        retry_delay_seconds: int = 0,
        now: str | None = None,
    ) -> Stage1SchedulerTask:
        return self.repository.retry(
            queue_item_id,
            worker_id=worker_id,
            lease_id=lease_id,
            error=error,
            retry_delay_seconds=retry_delay_seconds,
            now=now,
        )

    def pause(
        self,
        queue_item_id: str,
        *,
        paused_by: str,
        reason: str,
        now: str | None = None,
    ) -> Stage1SchedulerTask:
        return self.repository.pause(queue_item_id, paused_by=paused_by, reason=reason, now=now)

    def resume(
        self,
        queue_item_id: str,
        *,
        next_run_at: str | None = None,
        now: str | None = None,
    ) -> Stage1SchedulerTask:
        return self.repository.resume(queue_item_id, next_run_at=next_run_at, now=now)

    def dead_letter(
        self,
        queue_item_id: str,
        *,
        reason: str,
        now: str | None = None,
    ) -> Stage1SchedulerTask:
        return self.repository.dead_letter(queue_item_id, reason=reason, now=now)

    def _build_window(
        self,
        *,
        payload: dict[str, Any],
        extracted: Stage1Extraction,
        now: str,
    ) -> Stage1ExecutionWindow:
        task_id = str(payload["task_id"])
        return Stage1ExecutionWindow(
            window_id=build_id("S1WIN", task_id),
            time_range_from=extracted.time_range_from,
            time_range_until=extracted.time_range_until,
            window_start_at=_coerce_window_start(extracted, now),
            window_due_at=_coerce_window_due(extracted),
            window_priority_policy=extracted.window_priority_policy,
            window_priority=extracted.window_priority,
            clock_resolution_rule_id=extracted.clock_resolution_rule_id,
            clock_precedence_rule_id=extracted.clock_precedence_rule_id,
            status="scheduled",
            authority_refs={
                "source_registry_id": extracted.source_registry_id,
                "route_policy_id": extracted.route_policy_id,
                "default_route": extracted.default_route,
                "fallback_route": extracted.fallback_route,
            },
        )

    def _payload_from_context(self, context: Any) -> dict[str, Any]:
        if hasattr(context, "inputs") and isinstance(context.inputs, dict):
            payload = dict(context.inputs)
        elif isinstance(context, dict):
            payload = dict(context)
        else:
            raise TypeError("stage1 scheduler context must be a mapping or StageBundle-like object with inputs")
        required = ["task_id", "project_id", "region_code"]
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValueError(f"stage1 scheduler missing required inputs: {', '.join(missing)}")
        return payload

    def _assert_internal_scheduler_boundary(self, payload: dict[str, Any]) -> None:
        requested_live_flags = [flag for flag in _BLOCKED_LIVE_FLAGS if _truthy(payload.get(flag))]
        if requested_live_flags:
            raise ValueError(
                "stage1 scheduler is internal intent/readback only; blocked live/fetch flags: "
                + ", ".join(requested_live_flags)
            )
        source_markers = " ".join(
            str(payload.get(field, ""))
            for field in ("source_mode", "source_family", "source_registry_id", "source_url")
        ).upper()
        blocked_markers = [token for token in _BLOCKED_SOURCE_TOKENS if token in source_markers]
        if blocked_markers:
            raise ValueError(
                "stage1 scheduler only accepts public/source-blueprint governed sources; blocked markers: "
                + ", ".join(blocked_markers)
            )


__all__ = [
    "H01_CONSUMER_MUST_NOT_RECOMPUTE",
    "STAGE1_SCHEDULER_QUEUE_NAME",
    "STAGE2_HANDOFF_INTENT_STATE",
    "Stage1Scheduler",
]
