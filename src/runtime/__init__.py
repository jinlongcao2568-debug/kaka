from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORT_MODULES = {
    "AuditReplayLedger": "runtime.audit_ledger",
    "RunController": "runtime.run_controller",
    "StageStateMachine": "runtime.stage_state_machine",
    "TransitionGuard": "runtime.transition_guard",
    "WorkQueueDispatcher": "runtime.dispatcher",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORT_MODULES})

__all__ = [
    "AuditReplayLedger",
    "RunController",
    "StageStateMachine",
    "TransitionGuard",
    "WorkQueueDispatcher",
]
