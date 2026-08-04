"""work order state machine columns and value checks

Revision ID: 1878cb7a8324
Revises: b441c3a9b232
Create Date: 2026-08-04 14:40:00.350467

The two CHECK constraints were written by hand: Alembic's autogenerate does not
compare CHECK constraints, so it detected the three new columns and nothing else.
They pin the value domain — which statuses and priorities may exist at all — so
that a seed script or a manual UPDATE cannot introduce a value the application
has never heard of. Which transitions are legal is not expressible here, because
it depends on the current row and the caller; that stays in the application.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1878cb7a8324"
down_revision: str | Sequence[str] | None = "b441c3a9b232"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("NEW", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
PRIORITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("work_orders", sa.Column("assignee_id", sa.Uuid(), nullable=True))
    op.add_column("work_orders", sa.Column("resolution", sa.String(), nullable=True))
    op.add_column("work_orders", sa.Column("cancellation_reason", sa.String(), nullable=True))
    op.create_check_constraint("ck_work_orders_status", "work_orders", _in_list("status", STATUSES))
    op.create_check_constraint(
        "ck_work_orders_priority", "work_orders", _in_list("priority", PRIORITIES)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_work_orders_priority", "work_orders", type_="check")
    op.drop_constraint("ck_work_orders_status", "work_orders", type_="check")
    op.drop_column("work_orders", "cancellation_reason")
    op.drop_column("work_orders", "resolution")
    op.drop_column("work_orders", "assignee_id")
