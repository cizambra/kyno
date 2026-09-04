"""the token that authenticated each remote write

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

PREFIX = "kyno_"


def upgrade() -> None:
    # Nullable: local and stdio writes carry no bearer token, and every
    # version written before this column existed records nothing.
    with op.batch_alter_table(f"{PREFIX}constitution_versions") as batch:
        batch.add_column(sa.Column("token_id", sa.Integer, nullable=True))
        batch.create_foreign_key(
            f"{PREFIX}fk_versions_token_id", f"{PREFIX}tokens", ["token_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table(f"{PREFIX}constitution_versions") as batch:
        batch.drop_column("token_id")
