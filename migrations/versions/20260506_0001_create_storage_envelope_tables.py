"""create storage envelope tables

Revision ID: 20260506_0001
Revises:
Create Date: 2026-05-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260506_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("record_id", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_type", "record_id", name="uq_records_object_type_record_id"),
    )
    op.create_table(
        "stage_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stage_key", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stage_key"),
    )
    op.create_table(
        "work_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("work_item_id", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_item_id"),
    )
    op.create_table(
        "operator_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("work_item_id", sa.String(), nullable=False),
        sa.Column("action_event_id", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "worker_queue_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("queue_item_id", sa.String(), nullable=False),
        sa.Column("queue_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.String(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("queue_item_id"),
    )
    op.create_table(
        "worker_queue_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("queue_item_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("worker_queue_events")
    op.drop_table("worker_queue_items")
    op.drop_table("operator_actions")
    op.drop_table("work_items")
    op.drop_table("stage_states")
    op.drop_table("records")
