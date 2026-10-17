"""Embed one user's confirmed profile version, for the backfill and for the save/confirm hooks.

``embed_user_profile`` assumes the session already has the row-level-security user set (a request session does;
the backfill sets it per user). It never commits. ``embed_after_save`` is the hook the API calls after a profile
is confirmed or preferences are saved: it is off unless ``EMBED_ON_SAVE`` is set, it never raises, and it runs
inside a savepoint, so a failed embed (embedder down, bad response, a database error) can never fail or
poison the save that triggered it.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_hunter.domain.models import Preference, Profile, ProfileVersion

from . import settings as embedding_settings
from .client import HttpEmbedder
from .db_store import DbProfileEmbeddingStore
from .pipeline import EmbeddingOutcome, ProfileEmbedRequest, embed_profile
from .profile_text import ProfileTextInput

NO_CONFIRMED_PROFILE = "no_confirmed_profile"
HOOK_TIMEOUT_SECONDS = 5.0
log = logging.getLogger(__name__)


def embed_user_profile(session: Session, user_id: Any, embedder, *, force: bool = False) -> "EmbeddingOutcome | None":
    """Embed the user's confirmed profile version; ``None`` when there is no confirmed version."""
    profile = session.get(Profile, user_id)
    if profile is None or profile.confirmed_revision is None:
        return None
    version = session.scalar(select(ProfileVersion).where(
        ProfileVersion.user_id == user_id, ProfileVersion.revision == profile.confirmed_revision))
    if version is None:
        return None
    preferences = session.get(Preference, user_id)
    data = preferences.data if preferences else {}
    return embed_profile(
        ProfileEmbedRequest(profile_version_id=str(version.id), snapshot=version.data,
                            target_roles=ProfileTextInput.from_preferences({}, data).target_roles),
        embedder=embedder, store=DbProfileEmbeddingStore(session), force=force)


def embed_after_save(session: Session, user_id: Any, *, embedder=None) -> str:
    """Best-effort embed after a confirm or a preferences save. Returns a short status, never raises."""
    if not embedding_settings.embed_on_save_enabled():
        return "disabled"
    try:
        with session.begin_nested():
            outcome = embed_user_profile(
                session, user_id, embedder or HttpEmbedder(embedding_settings.embedder_url(),
                                                           timeout_seconds=HOOK_TIMEOUT_SECONDS))
        return outcome.status if outcome is not None else NO_CONFIRMED_PROFILE
    except Exception:   # a failed embed must never fail the save that triggered it
        log.exception("Profile embedding after save failed; the save itself is unaffected")
        return "error"
