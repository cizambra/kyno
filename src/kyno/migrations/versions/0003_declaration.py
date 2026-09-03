"""long-form declaration on constitution versions

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

PREFIX = "kyno_"


def upgrade() -> None:
    # Nullable, so versions written before declarations existed keep serving. They have no
    # declaration, which is read the same as an empty one.
    with op.batch_alter_table(f"{PREFIX}constitution_versions") as batch:
        batch.add_column(sa.Column("declaration", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(f"{PREFIX}constitution_versions") as batch:
        batch.drop_column("declaration")
