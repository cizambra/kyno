from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.mysql import DATETIME, LONGTEXT

UTC_DATETIME = DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")


def build_metadata(prefix: str = "kyno_") -> tuple[MetaData, Table, Table, Table]:
    metadata = MetaData()
    constitutions = Table(
        f"{prefix}constitutions",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", String(255), nullable=False, unique=True),
        Column("current_version", Integer, nullable=False),
        Column("created_at", UTC_DATETIME, nullable=False),
        # Private until someone publishes: a null stamp is the default state,
        # and history stays off even then until it is opted into separately.
        Column("published_at", UTC_DATETIME, nullable=True),
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
        Column("created_at", UTC_DATETIME, nullable=False),
        Column("created_by", String(255), nullable=True),
        # Nullable: local and direct writes have no questions to record.
        Column("authorized_by", String(32), nullable=True),
        # The server-verified token that authenticated a remote write.
        # Nullable: local and stdio writes carry no bearer token.
        Column("token_id", Integer, ForeignKey(f"{prefix}tokens.id"), nullable=True),
        UniqueConstraint("constitution_id", "version", name=f"{prefix}uq_constitution_version"),
    )
    tokens = Table(
        f"{prefix}tokens",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        # Not unique: during rotation two live tokens share a name on purpose.
        Column("name", String(255), nullable=False),
        Column("scope", String(16), nullable=False),
        # Unique: the hash is how a request finds its row.
        Column("token_hash", String(64), nullable=False, unique=True),
        Column("created_at", UTC_DATETIME, nullable=False),
        # Null until first use.
        Column("last_used_at", UTC_DATETIME, nullable=True),
        # Null unless minted with --ttl.
        Column("expires_at", UTC_DATETIME, nullable=True),
        # Null until revoked. Rows are never deleted: versions reference
        # token ids, and those must resolve forever.
        Column("revoked_at", UTC_DATETIME, nullable=True),
    )
    build_delivery_record_table(metadata, prefix)
    return metadata, constitutions, versions, tokens


def build_delivery_record_table(metadata: MetaData, prefix: str = "kyno_") -> Table:
    return Table(
        f"{prefix}delivery_records",
        metadata,
        Column("sequence", Integer, primary_key=True, autoincrement=True),
        Column("record_id", String(36), nullable=False, unique=True),
        Column("recorded_at", String(40), nullable=False),
        Column("constitution_id", Integer, ForeignKey(f"{prefix}constitutions.id"), nullable=True),
        Column("requested_constitution", String(255), nullable=False),
        Column("served_version", Integer, nullable=False),
        Column("operation", String(64), nullable=False),
        Column("last_seen_version", Integer, nullable=True),
        Column("detail_level", String(16), nullable=True),
        Column("selection", Text, nullable=False),
        Column("delta", Text().with_variant(LONGTEXT(), "mysql"), nullable=False),
        Column("requester", Text, nullable=False),
        Column("correlation_id", String(255), nullable=True),
        Column("metadata", Text, nullable=False),
        Index(f"{prefix}ix_delivery_record_correlation", "correlation_id", "sequence"),
        Index(f"{prefix}ix_delivery_record_constitution", "requested_constitution", "sequence"),
        Index(f"{prefix}ix_delivery_record_time", "recorded_at"),
    )
