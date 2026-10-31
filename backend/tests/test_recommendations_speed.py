"""The ranking speed-ups must not change a single result: skill matching equals the plain regex, and the document cache
never serves a stale or unbounded entry. (``rank_jobs`` itself is covered by test_recommendations.py.)"""
import re

import pytest

from job_hunter import recommendations as rec


def _reference_hits(profile_skills, job):
    """The original, un-optimised skill matching: whole-word, case-insensitive regex per spelling, title then description."""
    explicit = {rec._canonical_skill(s): s for s in rec._job_skills(job)}
    hits = []
    for skill in profile_skills:
        canonical = rec._canonical_skill(skill)
        if canonical in explicit:
            hits.append((skill, "job.skills", explicit[canonical]))
            continue
        found = None
        for field in ("title", "description"):
            text = job.get(field)
            if not (isinstance(text, str) and text):
                continue
            for alias in rec._SKILL_ALIASES.get(canonical, (skill,)):
                match = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text, re.IGNORECASE)
                if match:
                    found = (skill, field, match.group(0))
                    break
            if found:
                break
        if found:
            hits.append(found)
    return hits


SKILLS = ["Python", "SQL", "NoSQL", "C++", "C#", "Node.js", ".NET", "CI/CD", "Go", "R", "machine learning", "NLP",
          "Power BI", "Kubernetes", "Spark", "Excel"]
TEXTS = [
    "We use Python3 and sql-server; NoSQL too.", "C++, C# and .NET required", "Machine-learning and MACHINE LEARNING",
    "natural language processing (NLP)", "powerbi and Power BI", "Go-lang, R&D, node.js, CI/CD pipelines",
    "sqlalchemy is not sql but SQL is", "Café développeur: Python et SQL", "Kubernetes with a Kelvin sign",
    "Übung: Spark, apache spark, SPARK3", "ms excel / Microsoft Excel", "", "pysql nosqlx",
    # non-ASCII text: curly quotes and bullets, and the four characters that match an ASCII letter case-insensitively
    "“Python” • SQL – Excel", "\u212aubernetes and \u017fpark", "MACH\u0130NE LEARN\u0130NG, mach\u0131ne learn\u0131ng",
    "\u017fql\u0130te is not SQL; PYTHON\u0307", "naïve \u212a8s — NLP ✓",
]


@pytest.mark.parametrize("description", TEXTS)
@pytest.mark.parametrize("title", ["Python Developer", "Data Éngineer", ""])
def test_skill_matching_equals_the_plain_regex(title, description):
    job = {"title": title, "description": description, "skills": ["Spark"]}
    got = [(h["skill"], h["source"], h["matched_text"]) for h in rec._find_skill_evidence(SKILLS, job)]
    assert got == _reference_hits(SKILLS, job)


def test_document_counts_match_a_fresh_tokenisation_and_follow_text_changes():
    rec._document_cache.clear()
    first = rec._document_counts("Python and SQL engineer")
    assert first == rec.Counter(rec._tokenize("Python and SQL engineer"))
    assert rec._document_counts("Python and SQL engineer") is first          # served from the cache
    edited = rec._document_counts("Python and Rust engineer")                # a changed description is a different key
    assert edited == rec.Counter(rec._tokenize("Python and Rust engineer")) and "sql" not in edited


def test_document_cache_is_bounded(monkeypatch):
    rec._document_cache.clear()
    monkeypatch.setattr(rec, "_DOCUMENT_CACHE_SIZE", 5)
    for i in range(20):
        rec._document_counts(f"job number {i} python")
    assert len(rec._document_cache) == 5


def test_ranking_is_the_same_cold_and_cached():
    jobs = [{"id": str(i), "title": t, "description": d, "skills": [], "status": "open", "location": "Singapore"}
            for i, (t, d) in enumerate([("Data Engineer", "Python SQL Spark pipelines"), ("Backend Developer", "Python APIs and PostgreSQL"),
                                        ("Designer", "Figma and user research")])]
    profile = {"skills": ["Python", "SQL"], "summary": "data engineer"}
    rec._document_cache.clear()
    cold = rec.rank_jobs(jobs, profile, {})
    cached = rec.rank_jobs(jobs, profile, {})
    assert cold == cached and [r["job"]["id"] for r in cold][0] == "0"


def test_no_profile_text_skips_tokenising_the_pool():
    rec._document_cache.clear()
    rec.rank_jobs([{"id": "1", "title": "Engineer", "description": "Python", "status": "open"}], {}, {})
    assert len(rec._document_cache) == 0                                      # cold start: nothing to compare against
