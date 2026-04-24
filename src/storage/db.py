from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import mkstemp
from threading import RLock
from time import sleep
from typing import Any, Dict, List

from shared.settings import Settings
from shared.utils import utc_now_iso


_JSON_FILE_STORAGE_BACKEND = "json-file"
_SQLITE_STORAGE_BACKEND = "sqlite"
_SUPPORTED_STORAGE_BACKENDS = frozenset({_JSON_FILE_STORAGE_BACKEND, _SQLITE_STORAGE_BACKEND})


@dataclass(frozen=True)
class PersistedRecord:
    object_type: str
    record_id: str
    stage_scope: int
    project_id: str | None
    object_refs: Dict[str, str]
    decision_states: Dict[str, str]
    trace_refs: Dict[str, str]
    audit_refs: Dict[str, str]
    governed_state: Dict[str, Any]
    writeback_state: Dict[str, Any]
    payload: Dict[str, Any]
    persisted_at: str

    def as_payload(self) -> Dict[str, Any]:
        return dict(self.payload)


@dataclass(frozen=True)
class PersistedStageState:
    stage_scope: int
    project_id: str
    surface_id: str
    root_object_type: str
    root_record_id: str
    inputs: Dict[str, Any]
    persisted_at: str
    typed_object_refs: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PersistedWorkItem:
    work_item_id: str
    work_item_key: str
    stage_scope: int
    project_id: str
    surface_id: str
    primary_object_type: str
    primary_record_id: str
    assignment_profile_id: str
    assignment_lifecycle_state: str
    object_refs: Dict[str, str]
    surface_operational_state: str
    current_operational_state: str
    assigned_owner_role: str
    assigned_owner: str
    reviewer_role: str
    reviewer: str
    assignment_resolved_from: str
    assignment_simplified_boundary: List[str]
    pending_actions: List[str]
    pending_button_flows: List[Dict[str, str]]
    last_action_id: str | None
    last_action_state: str | None
    last_action_at: str | None
    trace_refs: Dict[str, str]
    audit_refs: Dict[str, str]
    decision_states: Dict[str, str]
    governed_context: Dict[str, Any]
    created_at: str
    updated_at: str

    def as_payload(self) -> Dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "work_item_key": self.work_item_key,
            "stage_scope": self.stage_scope,
            "project_id": self.project_id,
            "surface_id": self.surface_id,
            "primary_object_type": self.primary_object_type,
            "primary_record_id": self.primary_record_id,
            "assignment_profile_id": self.assignment_profile_id,
            "assignment_lifecycle_state": self.assignment_lifecycle_state,
            "object_refs": dict(self.object_refs),
            "surface_operational_state": self.surface_operational_state,
            "current_operational_state": self.current_operational_state,
            "assigned_owner_role": self.assigned_owner_role,
            "assigned_owner": self.assigned_owner,
            "reviewer_role": self.reviewer_role,
            "reviewer": self.reviewer,
            "assignment_resolved_from": self.assignment_resolved_from,
            "assignment_simplified_boundary": list(self.assignment_simplified_boundary),
            "pending_actions": list(self.pending_actions),
            "pending_button_flows": list(self.pending_button_flows),
            "last_action_id": self.last_action_id,
            "last_action_state": self.last_action_state,
            "last_action_at": self.last_action_at,
            "trace_refs": dict(self.trace_refs),
            "audit_refs": dict(self.audit_refs),
            "decision_states": dict(self.decision_states),
            "governed_context": dict(self.governed_context),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class PersistedOperatorAction:
    action_event_id: str
    work_item_id: str
    stage_scope: int
    action_id: str
    button_flow_id: str | None
    action_state: str
    resulting_assignment_lifecycle_state: str | None
    requested_by_role: str
    requested_by: str
    assigned_owner_role: str
    assigned_owner: str
    reviewer_role: str
    reviewer: str
    reason: str
    object_refs: Dict[str, str]
    trace_refs: Dict[str, str]
    audit_refs: Dict[str, str]
    requested_at: str
    completed_at: str | None

    def as_payload(self) -> Dict[str, Any]:
        return {
            "action_event_id": self.action_event_id,
            "work_item_id": self.work_item_id,
            "stage_scope": self.stage_scope,
            "action_id": self.action_id,
            "button_flow_id": self.button_flow_id,
            "action_state": self.action_state,
            "resulting_assignment_lifecycle_state": self.resulting_assignment_lifecycle_state,
            "requested_by_role": self.requested_by_role,
            "requested_by": self.requested_by,
            "assigned_owner_role": self.assigned_owner_role,
            "assigned_owner": self.assigned_owner,
            "reviewer_role": self.reviewer_role,
            "reviewer": self.reviewer,
            "reason": self.reason,
            "object_refs": dict(self.object_refs),
            "trace_refs": dict(self.trace_refs),
            "audit_refs": dict(self.audit_refs),
            "requested_at": self.requested_at,
            "completed_at": self.completed_at,
        }


class DatabaseSession:
    _default: "DatabaseSession | None" = None

    def __init__(self, *, storage_path: Path | None = None, settings: Settings | None = None) -> None:
        self._lock = RLock()
        self._closed = False
        self._settings = settings or self.default_settings()
        self._storage_backend = self._resolve_storage_backend(self._settings)
        self._storage_path = self._resolve_effective_storage_path(
            storage_path or self.default_storage_path(settings=self._settings),
            self._storage_backend,
        )
        self._backend = self._build_backend(self._storage_backend, self._storage_path)
        self._tables: Dict[str, Dict[str, PersistedRecord]] = {}
        self._stage_states: Dict[str, PersistedStageState] = {}
        self._work_items: Dict[str, PersistedWorkItem] = {}
        self._operator_actions: Dict[str, List[PersistedOperatorAction]] = {}
        if self._backend is None:
            self._load()

    @classmethod
    def default(cls, *, reload_from_disk: bool = False, settings: Settings | None = None) -> "DatabaseSession":
        resolved_settings = cls.default_settings(settings=settings)
        resolved_backend = cls._resolve_storage_backend(resolved_settings)
        resolved_storage_path = cls.default_storage_path(settings=resolved_settings)
        if (
            cls._default is None
            or cls._default._closed
            or reload_from_disk
            or cls._default.storage_backend != resolved_backend
            or cls._default.storage_path != resolved_storage_path
        ):
            if cls._default is not None:
                cls._default.close()
            cls._default = cls(settings=resolved_settings)
        return cls._default

    @classmethod
    def default_settings(cls, *, settings: Settings | None = None) -> Settings:
        return settings or Settings.from_env()

    @classmethod
    def default_storage_path(cls, *, settings: Settings | None = None) -> Path:
        resolved_settings = cls.default_settings(settings=settings)
        resolved_backend = cls._resolve_storage_backend(resolved_settings)
        return cls._resolve_effective_storage_path(
            resolved_settings.resolved_storage_path(),
            resolved_backend,
        )

    @classmethod
    def _resolve_storage_backend(cls, settings: Settings) -> str:
        backend = (settings.storage_backend or "").strip().lower()
        if backend not in _SUPPORTED_STORAGE_BACKENDS:
            configured_backend = settings.storage_backend
            raise ValueError(
                "unsupported storage backend "
                f"{configured_backend!r}; supported storage backends: {sorted(_SUPPORTED_STORAGE_BACKENDS)}"
            )
        return backend

    @classmethod
    def _resolve_effective_storage_path(cls, storage_path: Path, backend: str) -> Path:
        if backend == _SQLITE_STORAGE_BACKEND:
            from storage.sqlite_backend import SQLiteStorageBackend

            return SQLiteStorageBackend.effective_storage_path(storage_path)
        return storage_path

    def _build_backend(self, backend: str, storage_path: Path) -> Any | None:
        if backend == _SQLITE_STORAGE_BACKEND:
            from storage.sqlite_backend import SQLiteStorageBackend

            return SQLiteStorageBackend(storage_path)
        return None

    @property
    def storage_backend(self) -> str:
        return self._storage_backend

    @property
    def storage_path(self) -> Path:
        return self._storage_path

    def clear(self, *, remove_storage: bool = True) -> None:
        with self._lock:
            if self._backend is not None:
                self._backend.clear(remove_storage=remove_storage)
                return
            self._tables.clear()
            self._stage_states.clear()
            self._work_items.clear()
            self._operator_actions.clear()
            if remove_storage and self._storage_path.exists():
                self._storage_path.unlink(missing_ok=True)
            elif not remove_storage:
                self._flush()

    def close(self) -> None:
        with self._lock:
            if self._backend is not None:
                self._backend.close()
            self._closed = True

    def upsert_record(self, entry: PersistedRecord) -> PersistedRecord:
        with self._lock:
            if self._backend is not None:
                return self._backend.upsert_record(entry)
            self._tables.setdefault(entry.object_type, {})[entry.record_id] = entry
            self._flush()
            return entry

    def get_record(self, object_type: str, record_id: str) -> PersistedRecord | None:
        with self._lock:
            if self._backend is not None:
                return self._backend.get_record(object_type, record_id)
            return self._tables.get(object_type, {}).get(record_id)

    def list_records(self, object_type: str) -> list[PersistedRecord]:
        with self._lock:
            if self._backend is not None:
                return self._backend.list_records(object_type)
            return list(self._tables.get(object_type, {}).values())

    def find_records(self, object_type: str, **criteria: str) -> list[PersistedRecord]:
        rows = self.list_records(object_type)
        matched: list[PersistedRecord] = []
        for row in rows:
            if all(self._match_value(row, key, value) for key, value in criteria.items()):
                matched.append(row)
        return matched

    def upsert_stage_state(self, entry: PersistedStageState) -> PersistedStageState:
        with self._lock:
            stage_key = self._stage_key(entry.stage_scope, entry.surface_id, entry.root_record_id)
            if self._backend is not None:
                return self._backend.upsert_stage_state(stage_key, entry)
            self._stage_states[stage_key] = entry
            self._flush()
            return entry

    def get_stage_state(self, stage_scope: int, surface_id: str, root_record_id: str) -> PersistedStageState | None:
        with self._lock:
            stage_key = self._stage_key(stage_scope, surface_id, root_record_id)
            if self._backend is not None:
                return self._backend.get_stage_state(stage_key)
            return self._stage_states.get(stage_key)

    def list_stage_states(
        self,
        *,
        stage_scope: int | None = None,
        surface_id: str | None = None,
    ) -> list[PersistedStageState]:
        with self._lock:
            rows = (
                self._backend.list_stage_states()
                if self._backend is not None
                else list(self._stage_states.values())
            )
        if stage_scope is not None:
            rows = [row for row in rows if row.stage_scope == stage_scope]
        if surface_id is not None:
            rows = [row for row in rows if row.surface_id == surface_id]
        return rows

    def find_stage_states(
        self,
        *,
        stage_scope: int | None = None,
        surface_id: str | None = None,
        **criteria: str,
    ) -> list[PersistedStageState]:
        rows = self.list_stage_states(stage_scope=stage_scope, surface_id=surface_id)
        matched: list[PersistedStageState] = []
        for row in rows:
            if all(self._match_stage_state_value(row, key, value) for key, value in criteria.items()):
                matched.append(row)
        return matched

    def upsert_work_item(self, entry: PersistedWorkItem) -> PersistedWorkItem:
        with self._lock:
            if self._backend is not None:
                return self._backend.upsert_work_item(entry)
            self._work_items[entry.work_item_id] = entry
            self._flush()
            return entry

    def find_work_item(
        self,
        *,
        stage_scope: int,
        surface_id: str,
        primary_object_type: str,
        primary_record_id: str,
    ) -> PersistedWorkItem | None:
        with self._lock:
            rows = (
                self._backend.list_work_items()
                if self._backend is not None
                else list(self._work_items.values())
            )
            for item in rows:
                if (
                    item.stage_scope == stage_scope
                    and item.surface_id == surface_id
                    and item.primary_object_type == primary_object_type
                    and item.primary_record_id == primary_record_id
                ):
                    return item
        return None

    def list_work_items(self, stage_scope: int | None = None) -> list[PersistedWorkItem]:
        with self._lock:
            rows = (
                self._backend.list_work_items()
                if self._backend is not None
                else list(self._work_items.values())
            )
        if stage_scope is None:
            return rows
        return [row for row in rows if row.stage_scope == stage_scope]

    def append_operator_action(self, entry: PersistedOperatorAction) -> PersistedOperatorAction:
        with self._lock:
            if self._backend is not None:
                return self._backend.append_operator_action(entry)
            self._operator_actions.setdefault(entry.work_item_id, []).append(entry)
            self._flush()
            return entry

    def list_operator_actions(self, work_item_id: str) -> list[PersistedOperatorAction]:
        with self._lock:
            if self._backend is not None:
                return self._backend.list_operator_actions(work_item_id)
            return list(self._operator_actions.get(work_item_id, []))

    def _stage_key(self, stage_scope: int, surface_id: str, root_record_id: str) -> str:
        return f"{stage_scope}:{surface_id}:{root_record_id}"

    def _load(self) -> None:
        if not self._storage_path.exists():
            return
        raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
        self._tables = {
            object_type: {
                record_id: PersistedRecord(**payload)
                for record_id, payload in rows.items()
            }
            for object_type, rows in raw.get("tables", {}).items()
        }
        self._stage_states = {
            key: PersistedStageState(**payload)
            for key, payload in raw.get("stage_states", {}).items()
        }
        self._work_items = {
            work_item_id: PersistedWorkItem(**payload)
            for work_item_id, payload in raw.get("work_items", {}).items()
        }
        self._operator_actions = {
            work_item_id: [PersistedOperatorAction(**entry) for entry in rows]
            for work_item_id, rows in raw.get("operator_actions", {}).items()
        }

    def _flush(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "storage_version": 1,
            "tables": {
                object_type: {
                    record_id: asdict(record)
                    for record_id, record in rows.items()
                }
                for object_type, rows in self._tables.items()
            },
            "stage_states": {
                key: asdict(entry)
                for key, entry in self._stage_states.items()
            },
            "work_items": {
                work_item_id: asdict(entry)
                for work_item_id, entry in self._work_items.items()
            },
            "operator_actions": {
                work_item_id: [asdict(entry) for entry in rows]
                for work_item_id, rows in self._operator_actions.items()
            },
        }
        fd, temp_name = mkstemp(
            prefix=f"{self._storage_path.stem}-",
            suffix=".tmp",
            dir=str(self._storage_path.parent),
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception:
            os.close(fd)
            raise
        try:
            self._replace_with_retry(temp_path, self._storage_path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def _replace_with_retry(self, temp_path: Path, target_path: Path, *, retries: int = 8) -> None:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                os.replace(temp_path, target_path)
                return
            except PermissionError as exc:
                last_error = exc
            except OSError as exc:
                last_error = exc
            sleep(0.025 * (attempt + 1))
        if last_error is not None:
            raise last_error

    def _match_value(self, row: PersistedRecord, key: str, expected: str) -> bool:
        if key == "project_id":
            return row.project_id == expected
        if row.payload.get(key) == expected:
            return True
        if row.object_refs.get(key) == expected:
            return True
        if row.decision_states.get(key) == expected:
            return True
        if row.trace_refs.get(key) == expected:
            return True
        if row.audit_refs.get(key) == expected:
            return True
        return False

    def _match_stage_state_value(self, row: PersistedStageState, key: str, expected: str) -> bool:
        if key == "project_id":
            return row.project_id == expected
        if key == "root_record_id":
            return row.root_record_id == expected
        if row.inputs.get(key) == expected:
            return True
        if row.typed_object_refs.get(key) == expected:
            return True
        return False


def build_persisted_at() -> str:
    return utc_now_iso()


__all__ = [
    "DatabaseSession",
    "PersistedOperatorAction",
    "PersistedRecord",
    "PersistedStageState",
    "PersistedWorkItem",
    "build_persisted_at",
]
