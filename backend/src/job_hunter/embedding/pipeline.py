"""The job and profile embedding functions teammates call.

Each function takes typed, nullable inputs and does the whole job:

  build the versioned text  ->  save the match features  ->  skip if nothing changed
  ->  call the embedder  ->  hand the embedding row to storage

They never raise for expected problems. The outcome carries a status instead:
``ready`` (vector stored), ``unchanged`` (skipped), ``pending`` (embedder unavailable, retry
later), ``failed`` (unusable response or an internal error) or ``no_content`` (nothing to embed).
Reasons are short and never contain the input text. Match features are saved on every run, even
when the embedding is skipped or fails, because they describe the job or profile, not the vector.

The caller supplies the embedder and the store, so the same functions work in tests, in a
backfill command, inside a request (the caller's database session lives in the store) or
behind an API later. Nothing here touches the database, the ranking or the live app.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .client import DIMENSIONS, Embedder, EmbedderUnavailable, InvalidEmbeddingResponse
from .features import Classifier, extract_job_features, extract_profile_features
from .job_text import JOB_TEXT_VERSION, JobTextInput, build_job_text
from .profile_text import PROFILE_TEXT_VERSION, ProfileTextInput, build_profile_text
from .stores import (
    STATUS_FAILED,
    STATUS_NO_CONTENT,
    STATUS_PENDING,
    STATUS_READY,
    EmbeddingRecord,
    EmbeddingStore,
    StoredEmbeddingState,
)

log = logging.getLogger("job_hunter.embedding")

STATUS_UNCHANGED = "unchanged"
MAX_BATCH_SIZE = 64   # the embedder service accepts at most 64 texts per request


@dataclass(frozen=True)
class JobEmbedRequest:
    job_id: str
    job: JobTextInput
    stated_seniority: Sequence[str] | None = None     # only if the source states a level


@dataclass(frozen=True)
class ProfileEmbedRequest:
    profile_version_id: str
    snapshot: Mapping[str, Any]                       # the confirmed profile snapshot
    target_roles: Sequence[str] | None = None         # from preferences
    seniority_preference: str | Sequence[str] | None = None


@dataclass(frozen=True)
class EmbeddingOutcome:
    key: str
    status: str            # ready | unchanged | pending | failed | no_content
    reason: str | None
    text_version: str
    input_hash: str | None
    model: str | None


@dataclass(frozen=True)
class _Prepared:
    key: str
    version: str                       # always known, even when the text could not be built
    text: str | None
    input_hash: str | None
    features: dict[str, Any]
    error_status: str | None = None
    error_reason: str | None = None


def _hash(version: str, text: str) -> str:
    return hashlib.sha256(f"{version}\n{text}".encode("utf-8")).hexdigest()


def _plain(features: Any) -> dict[str, Any]:
    """Dataclass -> JSON-friendly dict (tuples become lists)."""
    return {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(features).items()}


def _failed_prep(key: str, version: str, features: dict[str, Any], exc: Exception) -> _Prepared:
    return _Prepared(key, version, None, None, features, STATUS_FAILED, f"preparation error: {type(exc).__name__}")


def _prepare_job(request: JobEmbedRequest, classify: Classifier | None,
                 text_version: str = JOB_TEXT_VERSION) -> _Prepared:
    key = request.job_id
    try:
        features = _plain(extract_job_features(request.job.title, request.stated_seniority, classify))
    except Exception as exc:
        return _failed_prep(key, text_version, {}, exc)
    try:
        built = build_job_text(request.job, version=text_version)
    except ValueError as exc:
        return _Prepared(key, text_version, None, None, features, STATUS_NO_CONTENT, str(exc))
    except Exception as exc:
        return _failed_prep(key, text_version, features, exc)
    return _Prepared(key, built.version, built.text, _hash(built.version, built.text), features)


def _prepare_profile(request: ProfileEmbedRequest, classify: Classifier | None) -> _Prepared:
    key = request.profile_version_id
    try:
        features = _plain(extract_profile_features(request.target_roles, request.seniority_preference, classify))
    except Exception as exc:
        return _failed_prep(key, PROFILE_TEXT_VERSION, {}, exc)
    try:
        built = build_profile_text(ProfileTextInput(snapshot=request.snapshot, target_roles=request.target_roles))
    except ValueError as exc:
        return _Prepared(key, PROFILE_TEXT_VERSION, None, None, features, STATUS_NO_CONTENT, str(exc))
    except Exception as exc:
        return _failed_prep(key, PROFILE_TEXT_VERSION, features, exc)
    return _Prepared(key, built.version, built.text, _hash(built.version, built.text), features)


def _is_current(state: StoredEmbeddingState | None, item: _Prepared, expected_model: str | None) -> bool:
    return (
        state is not None
        and state.status == STATUS_READY
        and state.text_version == item.version
        and state.input_hash == item.input_hash
        and (expected_model is None or state.model == expected_model)
    )


def _outcome(item: _Prepared, status: str, reason: str | None, model: str | None = None) -> EmbeddingOutcome:
    return EmbeddingOutcome(item.key, status, reason, item.version, item.input_hash, model)


def _store_without_vector(store: EmbeddingStore, item: _Prepared, status: str, reason: str) -> EmbeddingOutcome:
    record = EmbeddingRecord(status=status, model=None, dimensions=None, text_version=item.version,
                             input_hash=item.input_hash, vector=None, reason=reason)
    try:
        store.save(item.key, record)
    except Exception as exc:
        return _outcome(item, STATUS_FAILED, f"storage error: {type(exc).__name__}")
    return _outcome(item, status, reason)


def _run(prepared: list[_Prepared], embedder: Embedder, store: EmbeddingStore, *,
         batch_size: int, force: bool, expected_model: str | None) -> list[EmbeddingOutcome]:
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    outcomes: dict[int, EmbeddingOutcome] = {}
    to_embed: list[int] = []

    for index, item in enumerate(prepared):
        try:
            if item.features:
                store.save_features(item.key, item.features)    # features never depend on the vector
        except Exception as exc:
            outcomes[index] = _outcome(item, STATUS_FAILED, f"storage error: {type(exc).__name__}")
            continue
        if item.error_status:
            outcomes[index] = _store_without_vector(store, item, item.error_status, item.error_reason or "")
            continue
        try:
            state = store.get_state(item.key, item.version)
            if not force and _is_current(state, item, expected_model):
                outcomes[index] = _outcome(item, STATUS_UNCHANGED, None, state.model if state else None)
                continue
        except Exception as exc:
            outcomes[index] = _outcome(item, STATUS_FAILED, f"storage error: {type(exc).__name__}")
            continue
        to_embed.append(index)

    for start in range(0, len(to_embed), batch_size):
        chunk = to_embed[start:start + batch_size]
        error: tuple[str, str] | None = None
        result = None
        try:
            result = embedder.embed([prepared[i].text for i in chunk])  # type: ignore[misc]
        except EmbedderUnavailable:
            error = (STATUS_PENDING, "embedding service unavailable")
        except InvalidEmbeddingResponse:
            error = (STATUS_FAILED, "embedding service returned an unusable response")
        except Exception as exc:
            error = (STATUS_FAILED, f"unexpected embedder error: {type(exc).__name__}")
        else:
            if len(result.embeddings) != len(chunk):
                error = (STATUS_FAILED, "embedding count differs from request count")
        if error:
            for i in chunk:
                outcomes[i] = _store_without_vector(store, prepared[i], error[0], error[1])
            continue
        for i, vector in zip(chunk, result.embeddings):
            item = prepared[i]
            record = EmbeddingRecord(status=STATUS_READY, model=result.model, dimensions=len(vector) or DIMENSIONS,
                                     text_version=item.version, input_hash=item.input_hash, vector=tuple(vector))
            try:
                store.save(item.key, record)
            except Exception as exc:
                outcomes[i] = _outcome(item, STATUS_FAILED, f"storage error: {type(exc).__name__}")
            else:
                outcomes[i] = _outcome(item, STATUS_READY, None, result.model)

    ordered = [outcomes[i] for i in range(len(prepared))]
    counts: dict[str, int] = {}
    for outcome in ordered:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    log.info("embedding run: items=%d %s", len(ordered), " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return ordered


def embed_jobs(requests: Sequence[JobEmbedRequest], *, embedder: Embedder, store: EmbeddingStore,
               expected_model: str | None = None, classify: Classifier | None = None, force: bool = False,
               batch_size: int = 32, text_version: str = JOB_TEXT_VERSION) -> list[EmbeddingOutcome]:
    """Embed many jobs, one embedder call per batch. Outcomes are in request order.

    ``text_version`` picks the job text format (default ``job-v2``, the whole description); other
    versions are for experiments and are stored as separate rows, so formats can be compared."""
    prepared = [_prepare_job(r, classify, text_version) for r in requests]
    return _run(prepared, embedder, store, batch_size=batch_size, force=force, expected_model=expected_model)


def embed_job(request: JobEmbedRequest, *, embedder: Embedder, store: EmbeddingStore,
              expected_model: str | None = None, classify: Classifier | None = None,
              force: bool = False, text_version: str = JOB_TEXT_VERSION) -> EmbeddingOutcome:
    """The job embedding service: one job in, one outcome out. Never raises for expected problems."""
    return embed_jobs([request], embedder=embedder, store=store, expected_model=expected_model,
                      classify=classify, force=force, batch_size=1, text_version=text_version)[0]


def embed_profiles(requests: Sequence[ProfileEmbedRequest], *, embedder: Embedder, store: EmbeddingStore,
                   expected_model: str | None = None, classify: Classifier | None = None, force: bool = False,
                   batch_size: int = 32) -> list[EmbeddingOutcome]:
    """Embed several profile versions. The caller owns the per-user database context."""
    prepared = [_prepare_profile(r, classify) for r in requests]
    return _run(prepared, embedder, store, batch_size=batch_size, force=force, expected_model=expected_model)


def embed_profile(request: ProfileEmbedRequest, *, embedder: Embedder, store: EmbeddingStore,
                  expected_model: str | None = None, classify: Classifier | None = None,
                  force: bool = False) -> EmbeddingOutcome:
    """The profile embedding service: one profile version in, one outcome out."""
    return embed_profiles([request], embedder=embedder, store=store, expected_model=expected_model,
                          classify=classify, force=force, batch_size=1)[0]
