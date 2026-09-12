"""Persist the runtime direction responses recorded by Core."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kyno_deliveries",
        sa.Column("sequence", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("delivery_id", sa.String(36), nullable=False, unique=True),
        sa.Column("recorded_at", sa.String(40), nullable=False),
        sa.Column(
            "constitution_id", sa.Integer, sa.ForeignKey("kyno_constitutions.id"), nullable=True
        ),
        sa.Column("requested_constitution", sa.String(255), nullable=False),
        sa.Column("served_version", sa.Integer, nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("known_version", sa.Integer, nullable=True),
        sa.Column("detail_level", sa.String(16), nullable=True),
        sa.Column("selection", sa.Text, nullable=False),
        sa.Column("direction", sa.Text().with_variant(LONGTEXT(), "mysql"), nullable=False),
        sa.Column("requester", sa.Text, nullable=False),
        sa.Column("session_id", sa.String(255), nullable=True),
        sa.Column("metadata", sa.Text, nullable=False),
    )
    op.create_index("kyno_ix_delivery_session", "kyno_deliveries", ["session_id", "sequence"])
    op.create_index(
        "kyno_ix_delivery_constitution", "kyno_deliveries", ["requested_constitution", "sequence"]
    )
    op.create_index("kyno_ix_delivery_time", "kyno_deliveries", ["recorded_at"])


def downgrade() -> None:
    op.drop_table("kyno_deliveries")
