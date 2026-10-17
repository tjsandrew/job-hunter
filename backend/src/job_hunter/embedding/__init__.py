"""Embedding support: the client for the standalone embedder service, the versioned text
builders, the match features and checks, and the job and profile embedding functions.

Typical use from ingestion or profile-save code::

    from job_hunter.embedding import (HttpEmbedder, InMemoryEmbeddingStore, JobEmbedRequest,
                                      JobTextInput, embed_job)

    outcome = embed_job(JobEmbedRequest(job_id=str(job.id), job=JobTextInput.from_job(job)),
                        embedder=HttpEmbedder("http://embedder:8100"), store=my_store)
    # outcome.status is "ready", "unchanged", "pending", "failed" or "no_content"; nothing is raised
"""

from .client import Embedder, EmbeddingResult, EmbedderUnavailable, InvalidEmbeddingResponse, HttpEmbedder
from .features import (
    check_role_family,
    check_seniority,
    extract_job_features,
    extract_profile_features,
)
from .job_text import JOB_TEXT_VERSION, JobTextInput, build_job_text
from .pipeline import (
    STATUS_UNCHANGED,
    EmbeddingOutcome,
    JobEmbedRequest,
    ProfileEmbedRequest,
    embed_job,
    embed_jobs,
    embed_profile,
    embed_profiles,
)
from .profile_text import PROFILE_TEXT_VERSION, ProfileTextInput, build_profile_text
from .stores import (
    STATUS_FAILED,
    STATUS_NO_CONTENT,
    STATUS_PENDING,
    STATUS_READY,
    EmbeddingRecord,
    EmbeddingStore,
    InMemoryEmbeddingStore,
    StoredEmbeddingState,
)

__all__ = [
    "Embedder", "EmbeddingResult", "EmbedderUnavailable", "InvalidEmbeddingResponse", "HttpEmbedder",
    "check_role_family", "check_seniority", "extract_job_features", "extract_profile_features",
    "JOB_TEXT_VERSION", "JobTextInput", "build_job_text",
    "PROFILE_TEXT_VERSION", "ProfileTextInput", "build_profile_text",
    "STATUS_UNCHANGED", "EmbeddingOutcome", "JobEmbedRequest", "ProfileEmbedRequest",
    "embed_job", "embed_jobs", "embed_profile", "embed_profiles",
    "STATUS_FAILED", "STATUS_NO_CONTENT", "STATUS_PENDING", "STATUS_READY",
    "EmbeddingRecord", "EmbeddingStore", "InMemoryEmbeddingStore", "StoredEmbeddingState",
]
