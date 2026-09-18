"""Preserve microseconds in MySQL timestamps."""

from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TIMESTAMP_COLUMNS = (
    ("kyno_constitutions", "created_at", False),
    ("kyno_constitutions", "published_at", True),
    ("kyno_constitution_versions", "created_at", False),
    ("kyno_tokens", "created_at", False),
    ("kyno_tokens", "last_used_at", True),
    ("kyno_tokens", "expires_at", True),
    ("kyno_tokens", "revoked_at", True),
)


def _set_precision(precision: int) -> None:
    if op.get_bind().dialect.name != "mysql":
        return
    for table, column, nullable in TIMESTAMP_COLUMNS:
        op.alter_column(table, column, type_=DATETIME(fsp=precision), existing_nullable=nullable)


def upgrade() -> None:
    _set_precision(6)


def downgrade() -> None:
    _set_precision(0)
