from __future__ import annotations

from typing import Any, Mapping

from runtime.entrypoint_registry import RuntimeEntrypointRegistry


def _slug(value: str) -> str:
    return str(value).replace("_", "-").replace(" ", "-")


class WorkQueueDispatcher:
    def __init__(
        self,
        *,
        created_at: str,
        entrypoint_registry: RuntimeEntrypointRegistry | None = None,
    ) -> None:
        self.created_at = created_at
        self.entrypoint_registry = entrypoint_registry or RuntimeEntrypointRegistry.default()
        self._tasks: list[dict[str, Any]] = []

    def enqueue_next_action(
        self,
        *,
        run_id: str,
        project_id: str,
        current_stage_id: str,
        next_action: Mapping[str, Any],
        input_refs: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        entrypoint_id = str(next_action.get("entrypoint_id") or "")
        action_type = str(next_action.get("action_type") or "")
        task_suffix = str(next_action.get("dispatch_task_id_suffix") or entrypoint_id or action_type or "operator-review")
        blocking_reasons: list[str] = [str(reason) for reason in next_action.get("blocking_reasons", []) if reason]
        if not entrypoint_id:
            dispatch_state = "WAITING_FOR_REVIEW"
        else:
            try:
                self.entrypoint_registry.require_registered_entrypoint(entrypoint_id)
                dispatch_state = "READY_FOR_INTERNAL_DISPATCH"
            except ValueError as exc:
                dispatch_state = "BLOCKED_UNREGISTERED_ENTRYPOINT"
                blocking_reasons.append(str(exc))
        task = {
            "dispatch_task_id": f"DISPATCH-{run_id}-{_slug(task_suffix)}",
            "run_id": run_id,
            "project_id": project_id,
            "current_stage_id": current_stage_id,
            "action_type": action_type,
            "entrypoint_id": entrypoint_id,
            "reason": str(next_action.get("reason") or ""),
            "review_family": str(next_action.get("review_family") or ""),
            "review_state": str(next_action.get("review_state") or ""),
            "source_metric": str(next_action.get("source_metric") or ""),
            "metric_count": int(next_action.get("metric_count") or 0),
            "operator_next_action": str(next_action.get("operator_next_action") or ""),
            "stability_metric_counts": dict(next_action.get("stability_metric_counts") or {})
            if isinstance(next_action.get("stability_metric_counts"), Mapping)
            else {},
            "dispatch_state": dispatch_state,
            "execution_mode": "INTERNAL_ONLY",
            "input_refs": list(input_refs),
            "blocking_reasons": blocking_reasons,
            "external_customer_action_enabled": False,
            "created_at": self.created_at,
        }
        self._tasks.append(task)
        return task

    def pending_tasks(self) -> list[dict[str, Any]]:
        return list(self._tasks)
