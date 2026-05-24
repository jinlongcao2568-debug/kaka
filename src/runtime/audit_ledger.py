from __future__ import annotations

from typing import Any, Mapping


class AuditReplayLedger:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def record(
        self,
        *,
        event_type: str,
        run_id: str,
        created_at: str,
        stage_id: str = "",
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": f"AUDIT-{len(self._events) + 1:04d}",
            "event_type": event_type,
            "run_id": run_id,
            "stage_id": stage_id,
            "details": dict(details or {}),
            "created_at": created_at,
        }
        self._events.append(event)
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "ledger_kind": "audit_replay_ledger_v1",
            "events": list(self._events),
        }
