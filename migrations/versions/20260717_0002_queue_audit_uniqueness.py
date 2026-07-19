"""enforce queue and operator audit event uniqueness

Revision ID: 20260717_0002
Revises: 20260506_0001
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260717_0002"
down_revision = "20260506_0001"
branch_labels = None
depends_on = None


def _reject_legacy_duplicates() -> None:
    checks = (
        (
            "operator_actions",
            "work_item_id",
            "action_event_id",
        ),
        (
            "worker_queue_events",
            "queue_item_id",
            "event_id",
        ),
    )
    connection = op.get_bind()
    for table_name, parent_field, event_field in checks:
        duplicate = connection.execute(
            text(
                f"SELECT {parent_field}, {event_field}, COUNT(*) AS duplicate_count "
                f"FROM {table_name} "
                f"GROUP BY {parent_field}, {event_field} "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).first()
        if duplicate is not None:
            raise RuntimeError(
                f"cannot add audit uniqueness to {table_name}: legacy duplicate "
                f"{parent_field}={duplicate[0]!r}, {event_field}={duplicate[1]!r}, "
                f"count={duplicate[2]}; preserve and reconcile audit history before retrying"
            )


def upgrade() -> None:
    _reject_legacy_duplicates()
    with op.batch_alter_table("operator_actions") as batch_op:
        batch_op.create_unique_constraint(
            "uq_operator_actions_work_item_event",
            ["work_item_id", "action_event_id"],
        )
    with op.batch_alter_table("worker_queue_events") as batch_op:
        batch_op.create_unique_constraint(
            "uq_worker_queue_events_item_event",
            ["queue_item_id", "event_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("worker_queue_events") as batch_op:
        batch_op.drop_constraint("uq_worker_queue_events_item_event", type_="unique")
    with op.batch_alter_table("operator_actions") as batch_op:
        batch_op.drop_constraint("uq_operator_actions_work_item_event", type_="unique")
