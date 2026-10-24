"""Cross-source de-duplication of job postings (docs/design/04-JOB-INGESTION.md, "Canonicalisation and deduplication").

The same posting can come from several sources (an employer's own Greenhouse/Lever board, MyCareersFuture, Adzuna). Every
source keeps its OWN row in ``jobs`` (so re-importing a source stays idempotent and nothing that points at a job id is
orphaned); this module links the rows that are the same posting:

* ``match_key``        normalised employer + title + location, computed for every row at import;
* ``canonical_job_id`` NULL on the row everyone sees, otherwise the id of the canonical row it duplicates;
* ``also_seen_on``     on the canonical row, the other sources that list the same posting.

Two rows from DIFFERENT sources are the same posting only on exact evidence: the same listing URL, or the same ``match_key`` AND
a description that is nearly the same text. Similar titles alone never merge, and two rows of one source never merge.
The canonical row is chosen by authority (employer ATS, then government portal, then aggregator), then the earlier posting
date, then the id, so the result does not depend on the order the sources were polled in.

All functions here are pure: they read attributes of the row objects they are given and set the three link fields.
"""
from __future__ import annotations

from datetime import datetime
import re
import unicodedata
from typing import Any, Iterable, Sequence

# Lower is more authoritative. The employer's own board first, then the government portal, then aggregators.
AUTHORITY = {"greenhouse": 0, "lever": 0, "smartrecruiters": 0, "mycareersfuture": 1, "adzuna": 2}
UNKNOWN_AUTHORITY = 3
SIMILARITY_THRESHOLD = 0.6      # token-set Jaccard of the two descriptions; tuned on tests/fixtures/dedup_pairs.json
MIN_DESCRIPTION_TOKENS = 12     # a shorter text cannot prove two postings are the same
TRUNCATION_TOKENS = 40          # from this many words, a cut-off copy of a description still identifies it
TRUNCATION_DISCOUNT = 0.85
MAX_KEY = 480

_LEGAL_WORDS = {"pte", "ltd", "limited", "inc", "incorporated", "llc", "llp", "plc", "corp", "corporation", "co", "company",
                "sdn", "bhd", "gmbh", "ag", "singapore", "sg", "the"}
_WORD = re.compile(r"[a-z0-9]+")


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").casefold()


def _tokens(text: Any) -> list[str]:
    return _WORD.findall(_ascii(str(text or "")))


def normalise_company(name: Any) -> str:
    """'Stripe Singapore Pte. Ltd.' and 'Stripe' give the same key part; a name made only of legal words keeps them."""
    words = _tokens(name)
    kept = [word for word in words if word not in _LEGAL_WORDS]
    return " ".join(kept or words)


def normalise_title(title: Any) -> str:
    """Word order and level words are kept, so 'Senior Data Engineer' and 'Data Engineer' stay different postings."""
    return " ".join(_tokens(title))


def normalise_location(location: Any) -> str:
    words = _tokens(location)
    if "singapore" in words:      # 'Tanjong Pagar, Singapore' (MyCareersFuture) and 'Singapore' are the same place here
        return "singapore"
    return " ".join(words)


def match_key(company: Any, title: Any, location: Any) -> str | None:
    """None when the employer or title is unknown: such a posting is never linked to another."""
    company_part, title_part = normalise_company(company), normalise_title(title)
    if not company_part or not title_part:
        return None
    return f"{company_part}|{title_part}|{normalise_location(location)}"[:MAX_KEY]


def description_tokens(description: Any) -> frozenset[str]:
    return frozenset(_tokens(description))


def description_similarity(left: Any, right: Any) -> float:
    """How alike two descriptions are, from 0 to 1; 0 when either is too short to prove anything.

    Jaccard similarity of the word sets. An aggregator often keeps only the first part of a description, so when the shorter text
    still has a substantial number of words, the share of its words found in the longer one counts too (discounted)."""
    a, b = description_tokens(left), description_tokens(right)
    shortest = min(len(a), len(b))
    if shortest < MIN_DESCRIPTION_TOKENS:
        return 0.0
    overlap = len(a & b)
    score = overlap / len(a | b)
    if shortest >= TRUNCATION_TOKENS:
        score = max(score, TRUNCATION_DISCOUNT * overlap / shortest)
    return score


def authority(source: Any) -> int:
    return AUTHORITY.get(str(source or "").casefold(), UNKNOWN_AUTHORITY)


def same_posting(left: Any, right: Any, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """Whether two rows of DIFFERENT sources are the same posting."""
    if left.source == right.source:
        return False
    url = (getattr(left, "source_url", None) or "").strip()
    if url and url == (getattr(right, "source_url", None) or "").strip():
        return True
    key = getattr(left, "match_key", None)
    if not key or key != getattr(right, "match_key", None):
        return False
    return description_similarity(left.description, right.description) >= threshold


def _preference(row: Any) -> tuple:
    posted = getattr(row, "posted_at", None)
    stamp = posted.timestamp() if isinstance(posted, datetime) else 0.0
    return (authority(row.source), 0 if posted else 1, stamp, str(row.id))


def clusters(rows: Sequence[Any], threshold: float = SIMILARITY_THRESHOLD) -> list[list[Any]]:
    """Groups of rows that are the same posting (connected through ``same_posting``), singletons included."""
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if same_posting(rows[i], rows[j], threshold):
                parent[find(i)] = find(j)
    groups: dict[int, list[Any]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(find(index), []).append(row)
    return list(groups.values())


def _seen(row: Any) -> dict[str, Any]:
    return {"job_id": str(row.id), "source": row.source, "source_board": getattr(row, "source_board", None),
            "source_url": getattr(row, "source_url", None)}


def relink(rows: Iterable[Any], threshold: float = SIMILARITY_THRESHOLD) -> int:
    """Recompute the links of rows that share a ``match_key``; returns how many rows changed.

    Every row's links are rebuilt from the whole group, so the outcome never depends on which row was imported last."""
    rows = list(rows)
    changed = 0
    for group in clusters(rows, threshold):
        ordered = sorted(group, key=_preference)
        canonical = ordered[0]
        wanted = {id(canonical): (None, [_seen(row) for row in ordered[1:]])}
        for row in ordered[1:]:
            wanted[id(row)] = (canonical.id, [])
        for row in group:
            link, seen = wanted[id(row)]
            if getattr(row, "canonical_job_id", None) != link or (getattr(row, "also_seen_on", None) or []) != seen:
                row.canonical_job_id, row.also_seen_on = link, seen
                changed += 1
    return changed


def relink_all(rows: Iterable[Any], threshold: float = SIMILARITY_THRESHOLD) -> dict[str, int]:
    """Backfill for rows that were imported before de-duplication existed (``import_jobs --relink``)."""
    groups: dict[str, list[Any]] = {}
    counts = {"jobs": 0, "keyed": 0, "linked": 0, "changed": 0}
    for row in rows:
        counts["jobs"] += 1
        key = match_key(row.company, row.title, row.location)
        if getattr(row, "match_key", None) != key:
            row.match_key = key
        if key:
            counts["keyed"] += 1
            groups.setdefault(key, []).append(row)
        elif getattr(row, "canonical_job_id", None) is not None or getattr(row, "also_seen_on", None):
            row.canonical_job_id, row.also_seen_on = None, []
    for group in groups.values():
        counts["changed"] += relink(group, threshold)
    counts["linked"] = sum(1 for group in groups.values() for row in group if getattr(row, "canonical_job_id", None) is not None)
    return counts
