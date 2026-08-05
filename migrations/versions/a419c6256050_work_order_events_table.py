"""work_order_events table

Revision ID: a419c6256050
Revises: 1878cb7a8324
Append-only audit rows. Unlike the previous migration, autogenerate did render
the CHECK constraints here: it emits them as part of create_table for a new
table, while it still does not *compare* constraints on an existing one.

Create Date: 2026-08-05 21:57:08.038616

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a419c6256050"
down_revision: str | Sequence[str] | None = "1878cb7a8324"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "work_order_events",
        sa.Column("work_order_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("old_status", sa.String(), nullable=True),
        sa.Column("new_status", sa.String(), nullable=False),
        sa.Column("work_order_version", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('CREATE', 'ASSIGN', 'REASSIGN', 'START', 'COMPLETE', 'CANCEL')",
            name="ck_work_order_events_event_type",
        ),
        sa.CheckConstraint(
            "new_status IN ('NEW', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')",
            name="ck_work_order_events_new_status",
        ),
        sa.CheckConstraint(
            "old_status IS NULL OR old_status IN "
            "('NEW', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')",
            name="ck_work_order_events_old_status",
        ),
        sa.CheckConstraint("source IN ('API')", name="ck_work_order_events_source"),
        sa.ForeignKeyConstraint(
            ["work_order_id"],
            ["work_orders.id"],
            name="fk_work_order_events_work_order_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_work_order_events_work_order_id"),
        "work_order_events",
        ["work_order_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_work_order_events_work_order_id"), table_name="work_order_events")
    op.drop_table("work_order_events")
