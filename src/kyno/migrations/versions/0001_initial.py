# SPDX-License-Identifier: Elastic-2.0
"""initial coherence schema

Revision ID: 0001
Revises:
"""

import os

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

PREFIX = os.environ.get("KYNO_TABLE_PREFIX", "kyno_")


def upgrade() -> None:
    op.create_table(
        f"{PREFIX}constitutions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("current_version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        f"{PREFIX}constitution_versions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "constitution_id",
            sa.Integer,
            sa.ForeignKey(f"{PREFIX}constitutions.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("mission", sa.Text, nullable=False),
        sa.Column("principles", sa.Text, nullable=False),
        sa.Column("change_note", sa.Text, nullable=False),
        sa.Column("changed_mission", sa.Boolean, nullable=False),
        sa.Column("changed_principles", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.UniqueConstraint("constitution_id", "version", name=f"{PREFIX}uq_constitution_version"),
    )


def downgrade() -> None:
    op.drop_table(f"{PREFIX}constitution_versions")
    op.drop_table(f"{PREFIX}constitutions")
