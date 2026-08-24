# SPDX-License-Identifier: Elastic-2.0
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    false,
)


def build_metadata(prefix: str = "kyno_") -> tuple[MetaData, Table, Table]:
    metadata = MetaData()
    constitutions = Table(
        f"{prefix}constitutions",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", String(255), nullable=False, unique=True),
        Column("current_version", Integer, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        # Private until someone publishes: a null stamp is the default state,
        # and history stays off even then until it is opted into separately.
        Column("published_at", DateTime(timezone=True), nullable=True),
        Column("history_public", Boolean, nullable=False, default=False, server_default=false()),
    )
    versions = Table(
        f"{prefix}constitution_versions",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("constitution_id", Integer, ForeignKey(f"{prefix}constitutions.id"), nullable=False),
        Column("version", Integer, nullable=False),
        Column("mission", Text, nullable=False),
        # Nullable: every version written before declarations existed has none.
        Column("declaration", Text, nullable=True),
        Column("principles", Text, nullable=False),  # JSON-encoded list (portable)
        Column("change_note", Text, nullable=False),
        Column("changed_mission", Boolean, nullable=False),
        Column("changed_principles", Boolean, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("created_by", String(255), nullable=True),
        UniqueConstraint("constitution_id", "version", name=f"{prefix}uq_constitution_version"),
    )
    return metadata, constitutions, versions
