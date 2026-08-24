"""long-form declaration on constitution versions

Revision ID: 0003
Revises: 0002
"""

import os

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

PREFIX = os.environ.get("KYNO_TABLE_PREFIX", "kyno_")


def upgrade() -> None:
    # Nullable, so every version written before declarations existed keeps
    # serving -- with none, which reads the same as an empty one.
    with op.batch_alter_table(f"{PREFIX}constitution_versions") as batch:
        batch.add_column(sa.Column("declaration", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(f"{PREFIX}constitution_versions") as batch:
        batch.drop_column("declaration")
