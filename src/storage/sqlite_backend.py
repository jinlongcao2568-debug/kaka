from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from typing import Any


class SQLiteStorageBackend:
    def __init__(self, storage_path: Path) -> None:
        self.storage_path = self.effective_storage_path(storage_path)
        self._lock = RLock()
        self._connection = self._connect()
        self._initialize()

    @staticmethod
    def effective_storage_path(storage_path: Path) -> Path:
        if storage_path.suffix.lower() == ".json":
            return storage_path.with_suffix(".sqlite")
        return storage_path

    def clear(self, *, remove_storage: bool = True) -> None:
        with self._lock:
            if remove_storage:
                self._connection.close()
                self._remove_storage_files()
                self._connection = self._connect()
                self._initialize()
                return
            self._connection.execute("DELETE FROM operator_actions")
            self._connection.execute("DELETE FROM worker_queue_events")
            self._connection.execute("DELETE FROM worker_queue_items")
            self._connection.execute("DELETE FROM work_items")
            self._connection.execute("DELETE FROM stage_states")
            self._connection.execute("DELETE FROM records")
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def upsert_record(self, entry: Any) -> Any:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO records (object_type, record_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(object_type, record_id)
                DO UPDATE SET payload = excluded.payload
                """,
                (entry.object_type, entry.record_id, self._to_json(entry)),
            )
            self._connection.commit()
            return entry

    def get_record(self, object_type: str, record_id: str) -> Any | None:
        row = self._fetchone(
            "SELECT payload FROM records WHERE object_type = ? AND record_id = ?",
            (object_type, record_id),
        )
        if row is None:
            return None
        return self._record_from_json(str(row["payload"]))

    def list_records(self, object_type: str) -> list[Any]:
        rows = self._fetchall(
            "SELECT payload FROM records WHERE object_type = ? ORDER BY rowid",
            (object_type,),
        )
        return [self._record_from_json(str(row["payload"])) for row in rows]

    def upsert_stage_state(self, key: str, entry: Any) -> Any:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO stage_states (stage_key, payload)
                VALUES (?, ?)
                ON CONFLICT(stage_key)
                DO UPDATE SET payload = excluded.payload
                """,
                (key, self._to_json(entry)),
            )
            self._connection.commit()
            return entry

    def get_stage_state(self, key: str) -> Any | None:
        row = self._fetchone(
            "SELECT payload FROM stage_states WHERE stage_key = ?",
            (key,),
        )
        if row is None:
            return None
        return self._stage_state_from_json(str(row["payload"]))

    def list_stage_states(self) -> list[Any]:
        rows = self._fetchall("SELECT payload FROM stage_states ORDER BY rowid", ())
        return [self._stage_state_from_json(str(row["payload"])) for row in rows]

    def upsert_work_item(self, entry: Any) -> Any:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO work_items (work_item_id, payload)
                VALUES (?, ?)
                ON CONFLICT(work_item_id)
                DO UPDATE SET payload = excluded.payload
                """,
                (entry.work_item_id, self._to_json(entry)),
            )
            self._connection.commit()
            return entry

    def get_work_item(self, work_item_id: str) -> Any | None:
        row = self._fetchone(
            "SELECT payload FROM work_items WHERE work_item_id = ?",
            (work_item_id,),
        )
        if row is None:
            return None
        return self._work_item_from_json(str(row["payload"]))

    def list_work_items(self) -> list[Any]:
        rows = self._fetchall("SELECT payload FROM work_items ORDER BY rowid", ())
        return [self._work_item_from_json(str(row["payload"])) for row in rows]

    def append_operator_action(self, entry: Any) -> Any:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO operator_actions (work_item_id, action_event_id, payload)
                VALUES (?, ?, ?)
                """,
                (entry.work_item_id, entry.action_event_id, self._to_json(entry)),
            )
            self._connection.commit()
            return entry

    def list_operator_actions(self, work_item_id: str) -> list[Any]:
        rows = self._fetchall(
            "SELECT payload FROM operator_actions WHERE work_item_id = ? ORDER BY id",
            (work_item_id,),
        )
        return [self._operator_action_from_json(str(row["payload"])) for row in rows]

    def upsert_worker_queue_item(self, entry: Any) -> Any:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO worker_queue_items (queue_item_id, queue_name, status, priority, next_run_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(queue_item_id)
                DO UPDATE SET
                    queue_name = excluded.queue_name,
                    status = excluded.status,
                    priority = excluded.priority,
                    next_run_at = excluded.next_run_at,
                    payload = excluded.payload
                """,
                (
                    entry.queue_item_id,
                    entry.queue_name,
                    entry.status,
                    entry.priority,
                    entry.next_run_at,
                    self._to_json(entry),
                ),
            )
            self._connection.commit()
            return entry

    def get_worker_queue_item(self, queue_item_id: str) -> Any | None:
        row = self._fetchone(
            "SELECT payload FROM worker_queue_items WHERE queue_item_id = ?",
            (queue_item_id,),
        )
        if row is None:
            return None
        return self._worker_queue_item_from_json(str(row["payload"]))

    def list_worker_queue_items(self) -> list[Any]:
        rows = self._fetchall(
            """
            SELECT payload FROM worker_queue_items
            ORDER BY priority DESC, next_run_at IS NULL, next_run_at, rowid
            """,
            (),
        )
        return [self._worker_queue_item_from_json(str(row["payload"])) for row in rows]

    def append_worker_queue_event(self, entry: Any) -> Any:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO worker_queue_events (queue_item_id, event_id, event_type, payload)
                VALUES (?, ?, ?, ?)
                """,
                (entry.queue_item_id, entry.event_id, entry.event_type, self._to_json(entry)),
            )
            self._connection.commit()
            return entry

    def list_worker_queue_events(self, queue_item_id: str) -> list[Any]:
        rows = self._fetchall(
            "SELECT payload FROM worker_queue_events WHERE queue_item_id = ? ORDER BY id",
            (queue_item_id,),
        )
        return [self._worker_queue_event_from_json(str(row["payload"])) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.storage_path,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=OFF")
        return connection

    def _initialize(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    object_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (object_type, record_id)
                );
                CREATE TABLE IF NOT EXISTS stage_states (
                    stage_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS work_items (
                    work_item_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operator_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_item_id TEXT NOT NULL,
                    action_event_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS worker_queue_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_item_id TEXT NOT NULL UNIQUE,
                    queue_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    next_run_at TEXT,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS worker_queue_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_item_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )
            self._connection.commit()

    def _remove_storage_files(self) -> None:
        for path in (
            self.storage_path,
            self.storage_path.with_name(f"{self.storage_path.name}-wal"),
            self.storage_path.with_name(f"{self.storage_path.name}-shm"),
        ):
            path.unlink(missing_ok=True)

    def _fetchone(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
        with self._lock:
            cursor = self._connection.execute(sql, params)
            return cursor.fetchone()

    def _fetchall(self, sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self._connection.execute(sql, params)
            return list(cursor.fetchall())

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


__all__ = ["SQLiteStorageBackend"]
