"""Job title -> role family: the one classifier for ingestion and for the recommender.

Ingestion calls it (``classify_title`` in ``import_jobs.py``) to fill ``jobs.category``;
the recommender reads that column rather than classifying jobs a second time. The keyword tables below are
the single place to tune. It uses twelve families (the eleven keyword families plus
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
                "people operations", "hr business partner", "people partner", "total rewards",
                "people solutions", "people scientist", "talent partner")),
    ("legal", ("paralegal", "counsel", "attorney", "solicitor")),
    ("finance", ("accountant", "auditor", "controller", "treasury")),
)

# The keyword families, checked in this order (the first phrase found wins).
CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("data", ("data scientist", "data engineer", "data analyst", "analytics", "machine learning", " ml ",
              "artificial intelligence", "business intelligence")),
    ("design", ("designer", "design", " ux", "ux ", "user experience", "visual design")),
    ("product", ("product manager", "product owner", "product lead", "product management", "product director",
                 "head of product", "product strategist", "product specialist")),
    ("sales", ("sales", "account executive", "business development", "partnerships", "key account",
               "relationship manager", "merchant acquisition", "merchant growth", "partner development",
               "partner acquisition", "commercial", "wholesale", "deal desk")),
    ("customer_success", ("customer success", "client success", "customer support", "customer service",
                          "account manager", "account management", "support specialist", "support manager",
                          "support lead", "it support", "concierge", "solutions architect",
                          "implementation consultant", "engagement manager", "professional services")),
    ("engineering", ("engineer", "developer", "software", "infrastructure", "platform", "devops", "sre",
                     "quality assurance", " qa ", "cybersecurity", "architect", "database administrator")),
    ("operations", ("operations", "strategy", "program manager", "project manager", "supply chain", "logistics",
                    "procurement", "office admin", "executive assistant", "business assistant", "enablement",
                    "onboarding", "coordinator", "pmo", "flight supply", "process manager", "operation associate")),
    ("marketing", ("marketing", "communications", "public relations", "content", "brand", " crm ",
                   "public affairs", "social media", "creative strategist", "ad creative")),
    ("finance", ("finance", "accounting", "accountant", "treasury", "audit", " tax ", "trader", " trading ",
                 "portfolio manager", "investment research", "pricing",
                 # "financial" is not a substring of "finance", so "Financial Analyst" fell through to "other" and a
                 # finance profile had no role check at all. Specific phrases only: "Financial Crime" stays legal.
                 "financial analyst", "financial planning", "financial reporting", "financial manager", "fp&a", "fp & a")),
    ("people", ("human resources", "people operations", "recruiter", "recruiting", "talent acquisition", " hr ")),
    ("legal", ("legal", "compliance", "privacy counsel", "risk analyst", "risk manager", "risk director",
               "cdd", " kyc", " aml", "governance manager", "governance specialist", "risk programs")),
)

# Every label the classifier can return; anything else read from the database is treated as unknown.
ROLE_FAMILIES: frozenset[str] = frozenset(
    family for family, _ in (*OCCUPATION_RULES, *CATEGORY_RULES)) | {"other"}


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


# ---- Engineering sub-roles ----------------------------------------------------------------------------------------------
# "engineering" is one family, so a backend profile saw support, frontend and QA engineers as the same kind of role. The
# sub-role is read from the title only, and only a title that names one counts: "Software Engineer" has none (unknown, never
# blocks). Checked on the head of the title first, like the family.
SUBROLE_VERSION = "engineering-subrole-v1"
ENGINEERING_SUBROLE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("support", ("technical support", "support engineer", "support specialist", "customer engineer")),
    ("fullstack", ("full stack", "full-stack", "fullstack")),
    ("frontend", ("frontend", "front-end", "front end", "ui engineer", "web developer")),
    ("mobile", (" ios", "android", "mobile")),
    ("backend", ("backend", "back-end", "back end")),
    ("infra", ("devops", " sre", "site reliability", "infrastructure", "platform engineer", "cloud engineer")),
    ("security", ("security engineer", "cybersecurity", "application security", "appsec")),
    ("qa", ("quality assurance", " qa ", "sdet", "test engineer", "test automation")),
)

# Pairs that are close enough to be a plausible move rather than a different job. Everything else, when both sides name a
# sub-role, is a clear mismatch.
ADJACENT_SUBROLES: frozenset[frozenset[str]] = frozenset(frozenset(pair) for pair in (
    ("fullstack", "backend"), ("fullstack", "frontend"), ("fullstack", "mobile"), ("fullstack", "infra"),
    ("backend", "infra"), ("frontend", "mobile"), ("infra", "security"), ("qa", "fullstack"),
))


def classify_engineering_subrole(title: str | None) -> "str | None":
    """The engineering sub-role a title names (backend, frontend, fullstack, mobile, infra, security, qa, support), or None."""
    if not title or not title.strip():
        return None
    for text in (_head(title), title):
        hit = _first_match(text, ENGINEERING_SUBROLE_RULES)
        if hit:
            return hit[0]
    return None
