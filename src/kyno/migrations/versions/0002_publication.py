"""publication state on constitutions

Revision ID: 0002
Revises: 0001
"""

import os

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PREFIX = os.environ.get("KYNO_TABLE_PREFIX", "kyno_")


def upgrade() -> None:
    table = f"{PREFIX}constitutions"
    # Existing rows must land private, so the NOT NULL flag needs a server-side
    # default; SQLite also refuses a NOT NULL ADD COLUMN without one.
    with op.batch_alter_table(table) as batch:
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("history_public", sa.Boolean, nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    table = f"{PREFIX}constitutions"
    with op.batch_alter_table(table) as batch:
        batch.drop_column("history_public")
        batch.drop_column("published_at")
