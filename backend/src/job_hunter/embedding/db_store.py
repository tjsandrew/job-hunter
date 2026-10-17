"""Database-backed ``EmbeddingStore`` implementations (tables from migration 0012).

The caller owns the SQLAlchemy ``Session`` and its transaction: nothing here opens a connection or
commits. That keeps the per-user row-level security intact (the caller's session already has
``app.user_id`` set) and lets the embedding functions run inside or after a request.

Every write runs inside a SAVEPOINT, so one failing row (for example an unknown id) cannot poison the
rest of a batch: the embedding functions catch the error, report ``failed`` for that item and carry on.

This module imports SQLAlchemy and pgvector, so it is not re-exported from ``job_hunter.embedding``;
import it explicitly.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .db_tables import job_embeddings, profile_embeddings, profile_versions
from .stores import EmbeddingRecord, StoredEmbeddingState


def _uuid(key: str) -> UUID:
    try:
        return UUID(str(key))
    except ValueError as exc:
        raise ValueError("key must be a UUID") from exc


def _values(record: EmbeddingRecord) -> dict[str, Any]:
    return {
        "text_version": record.text_version,
        "model": record.model,
        "dimensions": record.dimensions,
        "input_hash": record.input_hash,
        "status": record.status,
        "reason": record.reason,
        "embedding": list(record.vector) if record.vector is not None else None,
    }


def _update_set(statement) -> dict[str, Any]:
    excluded = statement.excluded
    return {
        "model": excluded.model,
        "dimensions": excluded.dimensions,
        "input_hash": excluded.input_hash,
        "status": excluded.status,
        "reason": excluded.reason,
        "embedding": excluded.embedding,
        "updated_at": func.now(),
    }


class _Store:
    def __init__(self, session: Session):
        self.session = session

    def _state(self, table, owner_column: str, key: str, text_version: str) -> StoredEmbeddingState | None:
        row = self.session.execute(
            select(table.c.status, table.c.model, table.c.text_version, table.c.input_hash)
            .where(table.c[owner_column] == _uuid(key), table.c.text_version == text_version)
        ).first()
        return StoredEmbeddingState(*row) if row else None


class DbJobEmbeddingStore(_Store):
    """Job embeddings (shared data)."""

    def get_state(self, key: str, text_version: str) -> StoredEmbeddingState | None:
        return self._state(job_embeddings, "job_id", key, text_version)

    def save(self, key: str, record: EmbeddingRecord) -> None:
        statement = pg_insert(job_embeddings).values(job_id=_uuid(key), **_values(record))
        statement = statement.on_conflict_do_update(index_elements=["job_id", "text_version"],
                                                    set_=_update_set(statement))
        with self.session.begin_nested():
            self.session.execute(statement)


class DbProfileEmbeddingStore(_Store):
    """Profile-version embeddings. A profile's match features are read live from its preferences."""

    def get_state(self, key: str, text_version: str) -> StoredEmbeddingState | None:
        return self._state(profile_embeddings, "profile_version_id", key, text_version)

    def save(self, key: str, record: EmbeddingRecord) -> None:
        version_id = _uuid(key)
        with self.session.begin_nested():
            # The owner comes from the profile version itself (visible only to its own user under
            # row-level security), so a caller can never write an embedding for someone else's profile.
            owner = self.session.execute(
                select(profile_versions.c.user_id).where(profile_versions.c.id == version_id)).scalar_one_or_none()
            if owner is None:
                raise LookupError("profile version not found for the current user")
            statement = pg_insert(profile_embeddings).values(user_id=owner, profile_version_id=version_id,
                                                             **_values(record))
            statement = statement.on_conflict_do_update(index_elements=["profile_version_id", "text_version"],
                                                        set_=_update_set(statement))
            self.session.execute(statement)
