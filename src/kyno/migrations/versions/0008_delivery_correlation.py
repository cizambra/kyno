"""Name application-defined delivery grouping independently of sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("kyno_delivery_records") as batch:
        batch.drop_index("kyno_ix_delivery_record_session")
        batch.alter_column(
            "session_id",
            new_column_name="correlation_id",
            existing_type=sa.String(255),
            existing_nullable=True,
        )
    op.create_index(
        "kyno_ix_delivery_record_correlation",
        "kyno_delivery_records",
        ["correlation_id", "sequence"],
    )


def downgrade() -> None:
    with op.batch_alter_table("kyno_delivery_records") as batch:
        batch.drop_index("kyno_ix_delivery_record_correlation")
        batch.alter_column(
            "correlation_id",
            new_column_name="session_id",
            existing_type=sa.String(255),
            existing_nullable=True,
        )
    op.create_index(
        "kyno_ix_delivery_record_session", "kyno_delivery_records", ["session_id", "sequence"]
    )
