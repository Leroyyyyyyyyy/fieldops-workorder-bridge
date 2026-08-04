"""work_orders table

Revision ID: b441c3a9b232
Revises: b4b3b0b765f8
Create Date: 2026-07-30 11:24:02.304908

`asset_id` is indexed because PostgreSQL does not index foreign keys
automatically and every work order lookup goes through its asset. `status` is
deliberately left unindexed: it is the column the query and index evidence work
will use to show a plan difference before and after adding an index.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b441c3a9b232"
down_revision: str | Sequence[str] | None = "b4b3b0b765f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "work_orders",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default=sa.text("'NEW'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name="fk_work_orders_asset_id_assets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_work_orders_asset_id"), "work_orders", ["asset_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_work_orders_asset_id"), table_name="work_orders")
    op.drop_table("work_orders")
