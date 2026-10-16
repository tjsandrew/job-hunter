"""Where embedding results are kept, behind a small interface.

The embedding functions never talk to a database directly. They read the previous state
and hand back one record per item; the real database implementation (a later step, once
the extra columns are agreed) plugs in behind ``EmbeddingStore``. ``InMemoryEmbeddingStore``
is the implementation used by tests and by offline experiments.

The key is whatever identifies the row: a job id, or a profile version id.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping, Protocol

STATUS_READY = "ready"            # vector computed and stored
STATUS_PENDING = "pending"        # embedder unavailable; retry later (no usable vector)
STATUS_FAILED = "failed"          # unusable response or an internal error (no usable vector)
STATUS_NO_CONTENT = "no_content"  # nothing embeddable (blank title, empty profile)


@dataclass(frozen=True)
class StoredEmbeddingState:
    """What is already stored for a key; enough to decide whether work can be skipped."""

    status: str | None
    model: str | None
    text_version: str | None
    input_hash: str | None


@dataclass(frozen=True)
class EmbeddingRecord:
    """The full result handed to storage for one key."""

    status: str
    model: str | None
    dimensions: int | None
    text_version: str | None
    input_hash: str | None
    vector: tuple[float, ...] | None   # None unless status is "ready"
    features: Mapping[str, object]     # match features kept outside the vector
    reason: str | None = None          # short, text-free explanation for non-ready statuses


class EmbeddingStore(Protocol):
    def get_state(self, key: str) -> StoredEmbeddingState | None: ...

    def save(self, key: str, record: EmbeddingRecord) -> None:
        """Store a full record (replacing any previous vector)."""
        ...

    def save_features(self, key: str, features: Mapping[str, object]) -> None:
        """Refresh only the match features, leaving the vector and its metadata alone."""
        ...


@dataclass
class InMemoryEmbeddingStore:
    """Dictionary-backed store for tests and offline runs."""

    records: dict[str, EmbeddingRecord] = field(default_factory=dict)

    def get_state(self, key: str) -> StoredEmbeddingState | None:
        record = self.records.get(key)
        if record is None:
            return None
        return StoredEmbeddingState(record.status, record.model, record.text_version, record.input_hash)

    def save(self, key: str, record: EmbeddingRecord) -> None:
        self.records[key] = record

    def save_features(self, key: str, features: Mapping[str, object]) -> None:
        if key in self.records:
            self.records[key] = replace(self.records[key], features=dict(features))
