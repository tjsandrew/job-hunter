"""Where embedding results are kept, behind a small interface.

The embedding functions never talk to a database directly. They read the previous state and
hand back records; the real database implementation (a later step, once the table layout is
agreed) plugs in behind ``EmbeddingStore``. ``InMemoryEmbeddingStore`` is the implementation
used by tests and by offline experiments.

The layout mirrors a separate-tables design:

* **Embedding rows** are keyed by ``(key, text_version)``: one row per entity per text format,
  holding the vector and its metadata. Re-embedding with a new model overwrites the row for that
  text version; a new text version creates a new row, so formats can be compared side by side.
* **Match features** (seniority, role family) are keyed by ``key`` only. They describe the job or
  profile, not a particular vector, so they are saved independently and refreshed on every run.

The key is whatever identifies the entity: a job id, or a profile version id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

STATUS_READY = "ready"            # vector computed and stored
STATUS_PENDING = "pending"        # embedder unavailable; retry later (no usable vector)
STATUS_FAILED = "failed"          # unusable response or an internal error (no usable vector)
STATUS_NO_CONTENT = "no_content"  # nothing embeddable (blank title, empty profile)


@dataclass(frozen=True)
class StoredEmbeddingState:
    """What is already stored for one (key, text_version); enough to decide whether to skip work."""

    status: str | None
    model: str | None
    text_version: str | None
    input_hash: str | None


@dataclass(frozen=True)
class EmbeddingRecord:
    """One embedding row: the vector (when there is a usable one) and its metadata."""

    status: str
    model: str | None
    dimensions: int | None
    text_version: str
    input_hash: str | None
    vector: tuple[float, ...] | None   # None unless status is "ready"
    reason: str | None = None          # short, text-free explanation for non-ready statuses


class EmbeddingStore(Protocol):
    def get_state(self, key: str, text_version: str) -> StoredEmbeddingState | None: ...

    def save(self, key: str, record: EmbeddingRecord) -> None:
        """Insert or replace the embedding row for (key, record.text_version)."""
        ...

    def save_features(self, key: str, features: Mapping[str, object]) -> None:
        """Insert or replace the match features for key, independent of any embedding row."""
        ...


@dataclass
class InMemoryEmbeddingStore:
    """Dictionary-backed store for tests and offline runs."""

    records: dict[tuple[str, str], EmbeddingRecord] = field(default_factory=dict)
    features: dict[str, Mapping[str, object]] = field(default_factory=dict)

    def get_state(self, key: str, text_version: str) -> StoredEmbeddingState | None:
        record = self.records.get((key, text_version))
        if record is None:
            return None
        return StoredEmbeddingState(record.status, record.model, record.text_version, record.input_hash)

    def save(self, key: str, record: EmbeddingRecord) -> None:
        self.records[(key, record.text_version)] = record

    def save_features(self, key: str, features: Mapping[str, object]) -> None:
        self.features[key] = dict(features)
