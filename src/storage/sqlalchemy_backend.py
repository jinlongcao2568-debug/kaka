from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import unquote, urlsplit

from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.engine import Engine

from storage.sqlalchemy_schema import (
    metadata,
    operator_actions,
    records,
    stage_states,
    work_items,
    worker_queue_events,
    worker_queue_items,
)


class SQLAlchemyStorageBackend:
    def __init__(self, database_url: str, *, storage_backend: str) -> None:
        self.database_url = database_url
        self.storage_backend = storage_backend
        self.database_dialect = self._database_dialect(database_url)
        self.storage_path = self.effective_storage_path(database_url)
        if self.storage_path is not None:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._engine = self._connect()
        self._initialize()

    @staticmethod
    def effective_storage_path(database_url: str) -> Path | None:
        parsed = urlsplit(database_url)
        if parsed.scheme != "sqlite":
            return None
        if parsed.path in ("", "/:memory:"):
            return None
        return Path(unquote(parsed.path.lstrip("/")))

    @staticmethod
    def _database_dialect(database_url: str) -> str:
        return urlsplit(database_url).scheme.strip().lower().split("+", 1)[0]

    def clear(self, *, remove_storage: bool = True) -> None:
        with self._lock:
            if remove_storage and self.storage_path is not None:
                self._engine.dispose()
                self.storage_path.unlink(missing_ok=True)
                self._engine = self._connect()
                self._initialize()
                return

            with self._engine.begin() as connection:
                connection.execute(delete(operator_actions))
                connection.execute(delete(worker_queue_events))
                connection.execute(delete(worker_queue_items))
                connection.execute(delete(work_items))
                connection.execute(delete(stage_states))
                connection.execute(delete(records))

    def close(self) -> None:
        with self._lock:
            self._engine.dispose()

    def upsert_record(self, entry: Any) -> Any:
        with self._lock:
            self._upsert(
                table=records,
                match_columns={
                    "object_type": entry.object_type,
                    "record_id": entry.record_id,
                },
                values={
                    "object_type": entry.object_type,
                    "record_id": entry.record_id,
                    "payload": self._to_json(entry),
                },
            )
            return entry

    def get_record(self, object_type: str, record_id: str) -> Any | None:
        payload = self._fetch_payload(
            select(records.c.payload).where(
                records.c.object_type == object_type,
                records.c.record_id == record_id,
            )
        )
        if payload is None:
            return None
        return self._record_from_json(payload)

    def list_records(self, object_type: str) -> list[Any]:
        rows = self._fetch_payloads(
            select(records.c.payload)
            .where(records.c.object_type == object_type)
            .order_by(records.c.id)
        )
        return [self._record_from_json(payload) for payload in rows]

    def upsert_stage_state(self, key: str, entry: Any) -> Any:
        with self._lock:
            self._upsert(
                table=stage_states,
                match_columns={"stage_key": key},
                values={"stage_key": key, "payload": self._to_json(entry)},
            )
            return entry

    def get_stage_state(self, key: str) -> Any | None:
        payload = self._fetch_payload(
            select(stage_states.c.payload).where(stage_states.c.stage_key == key)
        )
        if payload is None:
            return None
        return self._stage_state_from_json(payload)

    def list_stage_states(self) -> list[Any]:
        rows = self._fetch_payloads(select(stage_states.c.payload).order_by(stage_states.c.id))
        return [self._stage_state_from_json(payload) for payload in rows]

    def upsert_work_item(self, entry: Any) -> Any:
        with self._lock:
            self._upsert(
                table=work_items,
                match_columns={"work_item_id": entry.work_item_id},
                values={"work_item_id": entry.work_item_id, "payload": self._to_json(entry)},
            )
            return entry

    def get_work_item(self, work_item_id: str) -> Any | None:
        payload = self._fetch_payload(
            select(work_items.c.payload).where(work_items.c.work_item_id == work_item_id)
        )
        if payload is None:
            return None
        return self._work_item_from_json(payload)

    def list_work_items(self) -> list[Any]:
        rows = self._fetch_payloads(select(work_items.c.payload).order_by(work_items.c.id))
        return [self._work_item_from_json(payload) for payload in rows]

    def append_operator_action(self, entry: Any) -> Any:
        with self._lock:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(operator_actions).values(
                        work_item_id=entry.work_item_id,
                        action_event_id=entry.action_event_id,
                        payload=self._to_json(entry),
                    )
                )
            return entry

    def list_operator_actions(self, work_item_id: str) -> list[Any]:
        rows = self._fetch_payloads(
            select(operator_actions.c.payload)
            .where(operator_actions.c.work_item_id == work_item_id)
            .order_by(operator_actions.c.id)
        )
        return [self._operator_action_from_json(payload) for payload in rows]

    def clear_operator_actions(self, work_item_id: str) -> int:
        with self._lock:
            with self._engine.begin() as connection:
                result = connection.execute(
                    delete(operator_actions).where(operator_actions.c.work_item_id == work_item_id)
                )
            return int(result.rowcount or 0)

    def upsert_worker_queue_item(self, entry: Any) -> Any:
        with self._lock:
            self._upsert(
                table=worker_queue_items,
                match_columns={"queue_item_id": entry.queue_item_id},
                values={
                    "queue_item_id": entry.queue_item_id,
                    "queue_name": entry.queue_name,
                    "status": entry.status,
                    "priority": entry.priority,
                    "next_run_at": entry.next_run_at,
                    "payload": self._to_json(entry),
                },
            )
            return entry

    def get_worker_queue_item(self, queue_item_id: str) -> Any | None:
        payload = self._fetch_payload(
            select(worker_queue_items.c.payload).where(
                worker_queue_items.c.queue_item_id == queue_item_id
            )
        )
        if payload is None:
            return None
        return self._worker_queue_item_from_json(payload)

    def list_worker_queue_items(self) -> list[Any]:
        rows = self._fetch_payloads(
            select(worker_queue_items.c.payload).order_by(
                worker_queue_items.c.priority.desc(),
                worker_queue_items.c.next_run_at,
                worker_queue_items.c.id,
            )
        )
        return [self._worker_queue_item_from_json(payload) for payload in rows]

    def append_worker_queue_event(self, entry: Any) -> Any:
        with self._lock:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(worker_queue_events).values(
                        queue_item_id=entry.queue_item_id,
                        event_id=entry.event_id,
                        event_type=entry.event_type,
                        payload=self._to_json(entry),
                    )
                )
            return entry

    def list_worker_queue_events(self, queue_item_id: str) -> list[Any]:
        rows = self._fetch_payloads(
            select(worker_queue_events.c.payload)
            .where(worker_queue_events.c.queue_item_id == queue_item_id)
            .order_by(worker_queue_events.c.id)
        )
        return [self._worker_queue_event_from_json(payload) for payload in rows]

    def _connect(self) -> Engine:
        try:
            connect_args: dict[str, Any] = {}
            if self.database_url.startswith("sqlite:"):
                connect_args["check_same_thread"] = False
            return create_engine(self.database_url, future=True, connect_args=connect_args)
        except Exception as exc:
            raise RuntimeError(
                f"storage backend {self.storage_backend!r} failed to configure SQLAlchemy engine; "
                "check KAKA_STORAGE_DATABASE_URL; no_silent_fallback"
            ) from exc

    def _initialize(self) -> None:
        try:
            if self.database_dialect == "sqlite":
                metadata.create_all(self._engine)
                return
            with self._engine.begin():
                return
        except Exception as exc:
            raise RuntimeError(
                f"storage backend {self.storage_backend!r} failed to initialize SQLAlchemy storage seam; "
                "check backend config and database connectivity; no_silent_fallback"
            ) from exc

    def _upsert(self, *, table: Any, match_columns: dict[str, Any], values: dict[str, Any]) -> None:
        predicates = [getattr(table.c, name) == value for name, value in match_columns.items()]
        update_values = {
            key: value
            for key, value in values.items()
            if key not in match_columns
        }
        with self._engine.begin() as connection:
            result = connection.execute(update(table).where(*predicates).values(**update_values))
            if result.rowcount == 0:
                connection.execute(insert(table).values(**values))

    def _fetch_payload(self, statement: Any) -> str | None:
        with self._lock:
            with self._engine.begin() as connection:
                row = connection.execute(statement).first()
        if row is None:
            return None
        return str(row[0])

    def _fetch_payloads(self, statement: Any) -> list[str]:
        with self._lock:
            with self._engine.begin() as connection:
                rows = connection.execute(statement).fetchall()
        return [str(row[0]) for row in rows]

    def _to_json(self, entry: Any) -> str:
        return json.dumps(asdict(entry), ensure_ascii=False, sort_keys=True)

    def _record_from_json(self, payload: str) -> Any:
        from storage.db import PersistedRecord

        return PersistedRecord(**json.loads(payload))

    def _stage_state_from_json(self, payload: str) -> Any:
        from storage.db import PersistedStageState

        return PersistedStageState(**json.loads(payload))

    def _work_item_from_json(self, payload: str) -> Any:
        from storage.db import PersistedWorkItem

        return PersistedWorkItem(**json.loads(payload))

    def _operator_action_from_json(self, payload: str) -> Any:
        from storage.db import PersistedOperatorAction

        return PersistedOperatorAction(**json.loads(payload))

    def _worker_queue_item_from_json(self, payload: str) -> Any:
        from storage.db import PersistedWorkerQueueItem

        return PersistedWorkerQueueItem(**json.loads(payload))

    def _worker_queue_event_from_json(self, payload: str) -> Any:
        from storage.db import PersistedWorkerQueueEvent

        return PersistedWorkerQueueEvent(**json.loads(payload))


__all__ = ["SQLAlchemyStorageBackend"]
