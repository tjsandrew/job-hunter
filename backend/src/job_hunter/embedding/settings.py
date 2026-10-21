"""Environment switches for the embedding features (kept out of the shared ``config.py`` on purpose)."""

import os

DEFAULT_EMBEDDER_URL = "http://embedder:8100"


def embedder_url() -> str:
    return os.getenv("EMBEDDER_URL") or DEFAULT_EMBEDDER_URL


def _on(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def for_you_enabled() -> bool:
    """The semantic "for you" endpoint is off unless FOR_YOU_ENABLED is 1/true/yes/on."""
    return _on("FOR_YOU_ENABLED")


DEFAULT_EMBEDDER_MODEL = "jinaai/jina-embeddings-v2-small-en"


def embed_mode() -> str:
    """How a profile save triggers embedding: ``queue`` (write an S3 flag after the commit; the AWS embed
    worker does the rest), ``sync`` (embed in the request through the HTTP embedder; local Compose) or ``off``.

    EMBED_ON_SAVE=queue selects the queue; 1/true/yes/on selects sync; anything else is off."""
    raw = (os.getenv("EMBED_ON_SAVE") or "").strip().lower()
    if raw == "queue":
        return "queue"
    return "sync" if raw in {"1", "true", "yes", "on"} else "off"


def embed_on_save_enabled() -> bool:
    """The synchronous embed after confirm / preferences save is off unless EMBED_ON_SAVE is 1/true/yes/on."""
    return embed_mode() == "sync"


def embedder_model_name() -> str:
    """Model id the embed worker expects stored vectors to carry (the in-process backend uses the same variable)."""
    return os.getenv("EMBEDDER_MODEL_NAME") or DEFAULT_EMBEDDER_MODEL


def for_you_fusion_enabled() -> bool:
    """For you merges the keyword ranking into the semantic one unless FOR_YOU_FUSION is 0/false/no/off (on by default)."""
    return (os.getenv("FOR_YOU_FUSION") or "").strip().lower() not in {"0", "false", "no", "off"}
