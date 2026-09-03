"""the tokens the server accepts

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

PREFIX = "kyno_"


def upgrade() -> None:
    op.create_table(
        f"{PREFIX}tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        # Not unique: during rotation two live tokens share a name on purpose.
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        # Unique: the hash is how a request finds its row.
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Null until first use.
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        # Null unless minted with --ttl.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # Null until revoked. Rows are never deleted: versions reference
        # token ids, and those must resolve forever.
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table(f"{PREFIX}tokens")
