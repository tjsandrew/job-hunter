from __future__ import annotations

from job_hunter.recommendations import rank_jobs


JOBS = [
    {
        "id": "sql-analyst",
        "title": "SQL Analyst",
        "location": "Singapore",
        "work_mode": "hybrid",
        "skills": ["SQL", "Excel", "Tableau"],
        "description": "Build SQL reports and dashboards for business analytics.",
        "posted_at": "2026-09-20T00:00:00Z",
    },
    {
        "id": "ml-engineer",
        "title": "Machine Learning Engineer",
        "location": "Singapore",
        "work_mode": "onsite",
        "skills": ["Python", "PyTorch", "NoSQL"],
        "description": "Train machine learning models with Python and PyTorch.",
        "posted_at": "2026-09-25T00:00:00Z",
    },
]


def by_id(results):
    return [result["job"]["id"] for result in results]


def test_sql_analyst_profile_ranks_sql_analyst_ahead_of_ml_engineer():
    profile = {
        "skills": ["SQL", "Excel", "Tableau"],
        "summary": "SQL reporting and business analysis",
    }
    preferences = {"target_roles": ["SQL Analyst"], "locations": ["Singapore"]}
    results = rank_jobs(JOBS, profile, preferences)
    assert by_id(results) == ["sql-analyst", "ml-engineer"]
    assert "SQL" in results[0]["matched_skills"]
    assert results[0]["score"] > results[1]["score"]
    assert results[0]["score_label"] == "relevance score (not probability)"


def test_ml_engineer_profile_ranks_ml_engineer_ahead_of_sql_analyst():
    profile = {
        "skills": ["Python", "machine learning", "PyTorch"],
        "experience": [{"title": "Machine Learning Engineer", "skills": ["Python", "PyTorch"]}],
        "summary": "Train machine learning models",
    }
    preferences = {"roles": ["Machine Learning Engineer"], "locations": ["SG"]}
    results = rank_jobs(JOBS, profile, preferences)
    assert by_id(results) == ["ml-engineer", "sql-analyst"]
    assert results[0]["matched_skills"] == ["Python", "machine learning", "PyTorch"]
    assert any(item["kind"] == "location_eligibility" for item in results[0]["evidence"])


def test_sql_and_nosql_are_distinct_exact_skills():
    jobs = [
        {"id": "a", "title": "Database Developer", "skills": ["SQL"], "location": "Singapore"},
        {"id": "b", "title": "Database Developer", "skills": ["NoSQL"], "location": "Singapore"},
    ]
    results = rank_jobs(jobs, {"skills": ["SQL"]}, {})
    assert results[0]["job"]["id"] == "a"
    assert results[0]["matched_skills"] == ["SQL"]
    assert results[1]["matched_skills"] == []


def test_selected_location_is_a_hard_filter_and_unknown_does_not_pass():
    jobs = [
        {"id": "sg", "title": "Analyst", "location": "Singapore"},
        {"id": "remote", "title": "Analyst", "location": "Remote"},
        {"id": "unknown", "title": "Analyst", "location": None},
        {"id": "ny", "title": "Analyst", "location": "New York"},
    ]
    results = rank_jobs(jobs, {"skills": ["SQL"]}, {"locations": ["Singapore"]})
    assert by_id(results) == ["sg"]
    assert results[0]["evidence"][-1]["kind"] == "location_eligibility"


def test_selected_work_mode_is_a_hard_filter_and_unknown_does_not_pass():
    jobs = [
        {"id": "remote", "title": "Analyst", "location": "Singapore", "work_mode": "remote"},
        {"id": "onsite", "title": "Analyst", "location": "Singapore", "work_mode": "onsite"},
        {"id": "unknown", "title": "Analyst", "location": "Singapore", "work_mode": None},
    ]
    assert by_id(rank_jobs(jobs, {}, {"work_modes": ["remote"]})) == ["remote"]


def test_empty_profile_returns_stable_cold_start_without_fake_score():
    jobs = [
        {"id": "older", "title": "Analyst", "posted_at": "2026-01-01T00:00:00Z"},
        {"id": "newer", "title": "Engineer", "posted_at": "2026-02-01T00:00:00Z"},
    ]
    results = rank_jobs(jobs, {}, {})
    assert by_id(results) == ["newer", "older"]
    assert all(item["mode"] == "cold_start" for item in results)
    assert all(item["score"] == 0 for item in results)
    assert "Add skills" in results[0]["reason"]


def test_profile_contact_name_and_protected_fields_are_ignored():
    profile = {
        "name": "NoSQL Alice",
        "email": "nosql@example.com",
        "phone": "555-0100",
        "gender": "SQL",
        "ethnicity": "SQL",
    }
    results = rank_jobs(JOBS, profile, {})
    assert all(item["mode"] == "cold_start" for item in results)
    assert all(item["score"] == 0 for item in results)
    assert all(not item["matched_skills"] for item in results)


def test_closed_jobs_are_excluded_and_ties_are_stable():
    jobs = [
        {"id": "z", "title": "Data Analyst", "skills": ["SQL"], "status": "open"},
        {"id": "a", "title": "Data Analyst", "skills": ["SQL"], "status": "open"},
        {"id": "closed", "title": "Data Analyst", "skills": ["SQL"], "status": "closed"},
    ]
    results = rank_jobs(jobs, {"skills": ["SQL"]}, {})
    assert by_id(results) == ["a", "z"]
    assert [item["rank"] for item in results] == [1, 2]


def test_reasons_include_exact_evidence_and_scores_are_deterministic():
    profile = {"skills": ["SQL"], "summary": "reporting"}
    first = rank_jobs(JOBS, profile, {"locations": ["Singapore"]})
    second = rank_jobs(JOBS, profile, {"locations": ["Singapore"]})
    assert [(row["job"]["id"], row["score"], row["evidence"]) for row in first] == [
        (row["job"]["id"], row["score"], row["evidence"]) for row in second
    ]
    assert any(evidence.get("matched_text") == "SQL" for evidence in first[0]["evidence"])
    assert 0 <= first[0]["score"] <= 1
