"""Environment switches for the embedding features (kept out of the shared ``config.py`` on purpose)."""

import os

DEFAULT_EMBEDDER_URL = "http://embedder:8100"


def embedder_url() -> str:
    return os.getenv("EMBEDDER_URL") or DEFAULT_EMBEDDER_URL


def for_you_enabled() -> bool:
    """The semantic "for you" endpoint is off unless FOR_YOU_ENABLED is 1/true/yes/on."""
    return (os.getenv("FOR_YOU_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}
