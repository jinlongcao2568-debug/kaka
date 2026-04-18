# Stage: shared
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, handoff/stage_handoff_catalog.json

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from shared.contracts_runtime import ContractStore, StageBundle


def not_implemented(message: str) -> None:
    raise NotImplementedError(message)


def normalize_payload(payload: Any) -> Any:
    if is_dataclass(payload):
        return asdict(payload)
    if isinstance(payload, Mapping):
        return dict(payload)
    return payload


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def build_id(prefix: str, project_id: str, suffix: Optional[str] = None) -> str:
    base = f"{prefix}-{project_id}"
    return f"{base}-{suffix}" if suffix else base


def ensure_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def get_flag(flags: Mapping[str, Any], name: str, default: bool = False) -> bool:
    if not flags:
        return default
    return bool(flags.get(name, default))


def ensure_enum(store: ContractStore, enum_name: str, value: Optional[str], fallback: str = "") -> str:
    try:
        allowed = store.get_enum_values(enum_name)
    except KeyError:
        return value or fallback
    if value in allowed:
        return value
    if allowed:
        return allowed[0]
    return value or fallback


def ensure_enum_or_fallback(
    store: ContractStore, enum_name: str, value: Optional[str], fallback: str = ""
) -> str:
    try:
        allowed = store.get_enum_values(enum_name)
    except KeyError:
        return value or fallback
    if value in allowed:
        return value
    if fallback in allowed:
        return fallback
    return value or fallback


def apply_rule(store: ContractStore, trace: list[str], rule_code: str) -> None:
    store.get_rule(rule_code)
    trace.append(rule_code)


def resolve_bundle(payload: Any, fallback: Optional[StageBundle] = None) -> StageBundle:
    if isinstance(payload, StageBundle):
        return payload
    if isinstance(payload, Mapping):
        for key in ("bundle", "stage", "stage_bundle", "stage1", "stage2", "stage3", "stage4", "stage5", "stage6", "stage7", "stage8"):
            candidate = payload.get(key)
            if isinstance(candidate, StageBundle):
                return candidate
    if fallback is not None:
        return fallback
    raise TypeError("payload must include a StageBundle")


__all__ = [
    "apply_rule",
    "build_id",
    "ensure_enum",
    "ensure_enum_or_fallback",
    "ensure_list",
    "get_flag",
    "normalize_payload",
    "resolve_bundle",
    "utc_now_iso",
]
