"""Job title -> role family: the one classifier for ingestion and for the recommender.

Ingestion calls it (``classify_title`` in ``import_jobs.py``) to fill ``jobs.category``; the embedding
pipeline calls it to save a job's role family in ``job_match_features``. Both therefore always agree, and the
keyword tables below are the single place to tune. It uses twelve families (the eleven keyword families plus
"other"), and two ordering rules found by the evaluation runs:

* **The occupation comes first.** Taking the first family in a fixed order whose keyword appears anywhere in
  the title filed "Technical Recruiter, Backend Engineering" and "Recruiter, Data Analytics" as engineering
  and data (the recruiting keyword sits later in the list). The words that name an occupation outright
  (recruiter, auditor, counsel, ...) are therefore checked first.
* **The head of the title counts before the tail.** Text after a comma, dash, pipe or bracket is usually a
  team, product or region ("Account Executive, Product - Local Payment Methods"), so the head segment is
  classified first and the whole title is only a fallback.

Titles that match nothing are "other", which the match checks treat as unknown (never blocks). The result is
a title-only inference, not a value supplied by the job source.
"""

from __future__ import annotations

import re

CLASSIFIER_VERSION = "role-family-v1"

# Checked first, on the head segment and then on the whole title: words that name the occupation itself.
OCCUPATION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("people", ("recruiter", "recruiting", "recruitment", "sourcer", "talent acquisition", "human resources",
                "people operations", "hr business partner")),
    ("legal", ("paralegal", "counsel", "attorney", "solicitor")),
    ("finance", ("accountant", "auditor", "controller", "treasury")),
)

# The keyword families, checked in this order (the first phrase found wins).
CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("data", ("data scientist", "data engineer", "data analyst", "analytics", "machine learning", " ml ",
              "artificial intelligence", "business intelligence")),
    ("design", ("designer", "design", " ux", "ux ", "user experience", "visual design")),
    ("product", ("product manager", "product owner", "product lead", "product management")),
    ("sales", ("sales", "account executive", "business development", "partnerships")),
    ("customer_success", ("customer success", "client success", "customer support", "customer service",
                          "account manager")),
    ("engineering", ("engineer", "developer", "software", "infrastructure", "platform", "devops", "sre",
                     "quality assurance", " qa ", "cybersecurity")),
    ("operations", ("operations", "strategy", "program manager", "project manager", "supply chain", "logistics")),
    ("marketing", ("marketing", "communications", "public relations", "content", "brand")),
    ("finance", ("finance", "accounting", "accountant", "treasury", "audit")),
    ("people", ("human resources", "people operations", "recruiter", "recruiting", "talent acquisition")),
    ("legal", ("legal", "compliance", "privacy counsel")),
)

# The head of a title ends at the first comma, semicolon, pipe, slash-free dash or bracket.
_HEAD_END = re.compile(r"\s[-–—]\s|[,;|(\[]")


def _head(title: str) -> str:
    return _HEAD_END.split(title, maxsplit=1)[0].strip()


def _first_match(text: str, rules: tuple[tuple[str, tuple[str, ...]], ...]) -> "tuple[str, str] | None":
    padded = f" {text.casefold()} "
    for family, phrases in rules:
        for phrase in phrases:
            if phrase in padded:
                return family, phrase.strip()
    return None


def classify_role_family(title: str | None) -> "tuple[str, str | None]":
    """Return ``(family, matched phrase)``; the family is ``"other"`` when nothing matches."""
    if not title or not title.strip():
        return "other", None
    head = _head(title)
    for text in (head, title):
        for rules in (OCCUPATION_RULES, CATEGORY_RULES):
            hit = _first_match(text, rules)
            if hit:
                return hit
    return "other", None
