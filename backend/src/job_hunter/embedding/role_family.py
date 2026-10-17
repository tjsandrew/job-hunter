"""Compatibility alias: the role-family classifier now lives in ``job_hunter.role_family`` so ingestion
and the recommender share one implementation. Import from there in new code."""

from job_hunter.role_family import (  # noqa: F401
    CATEGORY_RULES,
    CLASSIFIER_VERSION,
    OCCUPATION_RULES,
    classify_role_family,
)
