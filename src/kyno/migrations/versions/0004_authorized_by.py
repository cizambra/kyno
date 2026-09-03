"""who authorized each version's write

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

PREFIX = "kyno_"


def upgrade() -> None:
    # Nullable: every version written before the questions existed, and
    # every local or direct write, records nothing.
    with op.batch_alter_table(f"{PREFIX}constitution_versions") as batch:
        batch.add_column(sa.Column("authorized_by", sa.String(32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(f"{PREFIX}constitution_versions") as batch:
        batch.drop_column("authorized_by")
