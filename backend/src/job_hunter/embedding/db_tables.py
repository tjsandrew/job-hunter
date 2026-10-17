"""SQLAlchemy Core definitions for the embedding tables (created by migration 0012).

These use their *own* ``MetaData``, deliberately separate from ``domain.models.Base``. The first
migration builds the schema with ``Base.metadata.create_all``, so adding these tables to ``Base`` would
make a fresh database create them there and then clash with migration 0012. Foreign keys are declared
in the migration only; the Core tables here are used for queries, never for creating the schema.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID

metadata = MetaData()


def _embedding_columns() -> list[Column]:
    return [
        Column("id", PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
        Column("text_version", String(40), nullable=False),
        Column("model", Text),
        Column("dimensions", Integer),
        Column("input_hash", String(64)),
        Column("status", String(20), nullable=False),
        Column("reason", Text),
        Column("embedding", Vector(512)),
        Column("created_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
        Column("updated_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    ]


job_embeddings = Table("job_embeddings", metadata, Column("job_id", PGUUID(as_uuid=True), nullable=False),
                       *_embedding_columns())

profile_embeddings = Table("profile_embeddings", metadata,
                           Column("user_id", PGUUID(as_uuid=True), nullable=False),
                           Column("profile_version_id", PGUUID(as_uuid=True), nullable=False),
                           *_embedding_columns())

# Read-only reference used to find the owner of a profile version (the table itself belongs to the app).
profile_versions = Table("profile_versions", metadata,
                         Column("id", PGUUID(as_uuid=True), primary_key=True),
                         Column("user_id", PGUUID(as_uuid=True), nullable=False))
