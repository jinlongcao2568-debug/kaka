from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any
from urllib.parse import unquote, urlsplit

from sqlalchemy import create_engine, delete, event, inspect, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from runtime.operational_observability import (
    get_operational_event_sink,
    record_operational_event_safely,
)

from storage.sqlalchemy_schema import (
    ENVELOPE_TABLES,
    metadata,
    operator_actions,
    records,
    stage_states,
    work_items,
    worker_queue_events,
    worker_queue_items,
)


REQUIRED_STORAGE_SCHEMA_REVISION = "20260717_0002"


class SQLAlchemyStorageBackend:
    def __init__(self, database_url: str, *, storage_backend: str) -> None:
        self.database_url = database_url
        self.storage_backend = storage_backend
        self.database_dialect = self._database_dialect(database_url)
        self.storage_path = self.effective_storage_path(database_url)
        if self.storage_path is not None:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._schema_revision: str | None = None
        started = perf_counter()
        try:
            self._engine = self._connect()
            self._install_observability_hooks()
            self._initialize()
        except Exception as exc:
            self._record_database_event(
                operation="storage_initialize",
                outcome="error",
                severity="ERROR",
                duration_ms=(perf_counter() - started) * 1000,
                error_category=type(exc).__name__,
            )
            raise
        self._record_database_event(
            operation="storage_initialize",
            outcome="success",
            severity="INFO",
            duration_ms=(perf_counter() - started) * 1000,
        )

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

    @property
    def schema_revision(self) -> str | None:
        return self._schema_revision

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

    def commit_worker_queue_transition(
        self,
        *,
        item: Any,
        event: Any,
        expected_item: Any | None,
    ) -> bool:
        """Atomically persist a queue state change and its audit event."""
        values = {
            "queue_item_id": item.queue_item_id,
            "queue_name": item.queue_name,
            "status": item.status,
            "priority": item.priority,
            "next_run_at": item.next_run_at,
            "payload": self._to_json(item),
        }
        with self._lock:
            with self._engine.begin() as connection:
                existing_event = connection.execute(
                    select(worker_queue_events.c.id).where(
                        worker_queue_events.c.queue_item_id == event.queue_item_id,
                        worker_queue_events.c.event_id == event.event_id,
                    )
                ).first()
                if existing_event is not None:
                    return False
                if expected_item is None:
                    existing = connection.execute(
                        select(worker_queue_items.c.id).where(
                            worker_queue_items.c.queue_item_id == item.queue_item_id
                        )
                    ).first()
                    if existing is not None:
                        return False
                    connection.execute(insert(worker_queue_items).values(**values))
                else:
                    result = connection.execute(
                        update(worker_queue_items)
                        .where(
                            worker_queue_items.c.queue_item_id == item.queue_item_id,
                            worker_queue_items.c.status == expected_item.status,
                            worker_queue_items.c.payload == self._to_json(expected_item),
                        )
                        .values(**{key: value for key, value in values.items() if key != "queue_item_id"})
                    )
                    if int(result.rowcount or 0) != 1:
                        return False
                connection.execute(
                    insert(worker_queue_events).values(
                        queue_item_id=event.queue_item_id,
                        event_id=event.event_id,
                        event_type=event.event_type,
                        payload=self._to_json(event),
                    )
                )
        return True

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
            engine_options: dict[str, Any] = {
                "future": True,
                "connect_args": connect_args,
            }
            if self.database_dialect == "postgresql":
                engine_options.update(
                    pool_pre_ping=True,
                    pool_recycle=300,
                )
            return create_engine(self.database_url, **engine_options)
        except Exception as exc:
            raise RuntimeError(
                f"storage backend {self.storage_backend!r} failed to configure SQLAlchemy engine; "
                "check database URL/password-file connection config; no_silent_fallback"
            ) from exc

    def _install_observability_hooks(self) -> None:
        @event.listens_for(self._engine, "before_cursor_execute")
        def _before_cursor_execute(
            conn: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            del conn, cursor, parameters
            context._kaka_observability_started = perf_counter()
            context._kaka_observability_statement_type = _database_statement_type(statement)
            context._kaka_observability_executemany = bool(executemany)

        @event.listens_for(self._engine, "after_cursor_execute")
        def _after_cursor_execute(
            conn: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            del conn, cursor, statement, parameters, executemany
            started = getattr(context, "_kaka_observability_started", perf_counter())
            self._record_database_event(
                operation="sql_statement",
                outcome="success",
                severity="INFO",
                duration_ms=(perf_counter() - started) * 1000,
                attributes={
                    "statement_type": getattr(
                        context, "_kaka_observability_statement_type", "OTHER"
                    ),
                    "executemany": bool(
                        getattr(context, "_kaka_observability_executemany", False)
                    ),
                },
            )

        @event.listens_for(self._engine, "handle_error")
        def _handle_error(exception_context: Any) -> None:
            context = getattr(exception_context, "execution_context", None)
            started = getattr(context, "_kaka_observability_started", perf_counter())
            original_exception = getattr(exception_context, "original_exception", None)
            self._record_database_event(
                operation="sql_statement",
                outcome="error",
                severity="ERROR",
                duration_ms=(perf_counter() - started) * 1000,
                error_category=type(original_exception).__name__,
                attributes={
                    "statement_type": getattr(
                        context, "_kaka_observability_statement_type", "OTHER"
                    ),
                    "executemany": bool(
                        getattr(context, "_kaka_observability_executemany", False)
                    ),
                },
            )

    def _record_database_event(
        self,
        *,
        operation: str,
        outcome: str,
        severity: str,
        duration_ms: float,
        error_category: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        record_operational_event_safely(
            get_operational_event_sink("storage"),
            component="database",
            operation=operation,
            outcome=outcome,
            severity=severity,
            duration_ms=duration_ms,
            error_category=error_category,
            attributes={
                "storage_backend": self.storage_backend,
                "database_dialect": self.database_dialect,
                **(attributes or {}),
            },
        )

    def _initialize(self) -> None:
        try:
            if self.database_dialect == "sqlite":
                metadata.create_all(self._engine)
                return
            self._schema_revision = self.validate_required_schema(
                self._engine,
                storage_backend=self.storage_backend,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"storage backend {self.storage_backend!r} failed to initialize SQLAlchemy storage seam; "
                "check backend config and database connectivity; no_silent_fallback"
            ) from exc

    @staticmethod
    def required_table_names() -> tuple[str, ...]:
        return tuple(sorted(ENVELOPE_TABLES))

    @classmethod
    def missing_required_tables(cls, engine: Engine) -> list[str]:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        return [table_name for table_name in cls.required_table_names() if table_name not in existing_tables]

    @classmethod
    def validate_required_schema(cls, engine: Engine, *, storage_backend: str) -> str:
        missing_tables = cls.missing_required_tables(engine)
        if missing_tables:
            missing = ", ".join(missing_tables)
            raise RuntimeError(
                f"storage backend {storage_backend!r} is missing required storage tables: {missing}; "
                "run scripts\\run-storage-migrations.ps1 with KAKA_STORAGE_DATABASE_URL before bootstrapping "
                "a PostgreSQL/SQLAlchemy storage session; no_silent_fallback"
            )
        inspector = inspect(engine)
        if "alembic_version" not in set(inspector.get_table_names()):
            raise RuntimeError(
                f"storage backend {storage_backend!r} has no alembic_version table; "
                "run storage migrations before bootstrapping; no_silent_fallback"
            )
        with engine.begin() as connection:
            schema_revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        if schema_revision != REQUIRED_STORAGE_SCHEMA_REVISION:
            raise RuntimeError(
                f"storage backend {storage_backend!r} schema revision is "
                f"{schema_revision!r}, required {REQUIRED_STORAGE_SCHEMA_REVISION!r}; "
                "run storage migrations to head before bootstrapping; no_silent_fallback"
            )
        return str(schema_revision)

    def _upsert(self, *, table: Any, match_columns: dict[str, Any], values: dict[str, Any]) -> None:
        update_values = {
            key: value
            for key, value in values.items()
            if key not in match_columns
        }
        if self.database_dialect in {"postgresql", "sqlite"}:
            insert_factory = postgresql_insert if self.database_dialect == "postgresql" else sqlite_insert
            statement = insert_factory(table).values(**values).on_conflict_do_update(
                index_elements=list(match_columns.keys()),
                set_=update_values,
            )
            with self._engine.begin() as connection:
                connection.execute(statement)
            return

        predicates = [getattr(table.c, name) == value for name, value in match_columns.items()]
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


def _database_statement_type(statement: str) -> str:
    first_token = str(statement or "").lstrip().split(None, 1)[0].upper().rstrip(";")
    if first_token in {
        "ALTER",
        "CREATE",
        "DELETE",
        "DROP",
        "INSERT",
        "PRAGMA",
        "SELECT",
        "UPDATE",
        "WITH",
    }:
        return first_token
    return "OTHER"


__all__ = ["REQUIRED_STORAGE_SCHEMA_REVISION", "SQLAlchemyStorageBackend"]
