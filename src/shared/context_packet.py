from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from shared.contracts_runtime import ContractRecord


@dataclass(frozen=True)
class ContextPacket:
    capability_mode: str
    stage: int
    project_id: str
    records: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    inputs: Mapping[str, Any] = field(default_factory=dict)
    flags: Mapping[str, Any] = field(default_factory=dict)
    now: str | None = None
    release_level: str | None = None
    approval_state: str | None = None
    environment_tier: str | None = None
    capability_mode_overrides: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_records(
        cls,
        capability_mode: str,
        stage: int,
        project_id: str,
        records: Mapping[str, ContractRecord | Mapping[str, Any]],
        inputs: Mapping[str, Any] | None = None,
    ) -> "ContextPacket":
        normalized_records: dict[str, Mapping[str, Any]] = {}
        for key, record in records.items():
            normalized_records[key] = record.data if isinstance(record, ContractRecord) else dict(record)
        inputs_map = dict(inputs or {})
        return cls(
            capability_mode=capability_mode,
            stage=stage,
            project_id=project_id,
            records=normalized_records,
            inputs=inputs_map,
            flags=dict(inputs_map.get("flags", {})),
            now=inputs_map.get("now"),
            release_level=inputs_map.get("release_level") or inputs_map.get("minimum_release_level"),
            approval_state=inputs_map.get("approval_state"),
            environment_tier=inputs_map.get("environment_tier", "internal_pilot"),
            capability_mode_overrides=dict(inputs_map.get("capability_mode_overrides") or {}),
        )

    def record(self, object_type: str) -> Mapping[str, Any]:
        return self.records.get(object_type, {})

    def input(self, field_name: str, default: Any = None) -> Any:
        return self.inputs.get(field_name, default)

    def override_mode(self, capability_family: str) -> str | None:
        return self.capability_mode_overrides.get(capability_family)


__all__ = ["ContextPacket"]
