from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, UniqueConstraint


metadata = MetaData()

records = Table(
    "records",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("object_type", String, nullable=False),
    Column("record_id", String, nullable=False),
    Column("payload", Text, nullable=False),
    UniqueConstraint("object_type", "record_id", name="uq_records_object_type_record_id"),
)

stage_states = Table(
    "stage_states",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("stage_key", String, nullable=False, unique=True),
    Column("payload", Text, nullable=False),
)

work_items = Table(
    "work_items",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("work_item_id", String, nullable=False, unique=True),
    Column("payload", Text, nullable=False),
)

operator_actions = Table(
    "operator_actions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("work_item_id", String, nullable=False),
    Column("action_event_id", String, nullable=False),
    Column("payload", Text, nullable=False),
)

worker_queue_items = Table(
    "worker_queue_items",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("queue_item_id", String, nullable=False, unique=True),
    Column("queue_name", String, nullable=False),
    Column("status", String, nullable=False),
    Column("priority", Integer, nullable=False),
    Column("next_run_at", String, nullable=True),
    Column("payload", Text, nullable=False),
)

worker_queue_events = Table(
    "worker_queue_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("queue_item_id", String, nullable=False),
    Column("event_id", String, nullable=False),
    Column("event_type", String, nullable=False),
    Column("payload", Text, nullable=False),
)

ENVELOPE_TABLES = {
    "records": records,
    "stage_states": stage_states,
    "work_items": work_items,
    "operator_actions": operator_actions,
    "worker_queue_items": worker_queue_items,
    "worker_queue_events": worker_queue_events,
}


__all__ = [
    "ENVELOPE_TABLES",
    "metadata",
    "operator_actions",
    "records",
    "stage_states",
    "worker_queue_events",
    "worker_queue_items",
    "work_items",
]
