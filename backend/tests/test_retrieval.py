import json

import pytest

from job_hunter.embedding.retrieval import (
    ProfileQuery,
    RetrievalCandidate,
    cosine,
    eligible_jobs,
    is_eligible,
    retrieve,
)
from job_hunter.recommendations import rank_jobs


def vec(*head):
    return tuple(list(head) + [0.0] * (8 - len(head)))


QUERY = ProfileQuery(vector=vec(1.0), role_families=("engineering",), seniority_levels=("entry",))


def cand(job_id, vector, family="engineering", levels=()):
    return RetrievalCandidate(job_id=job_id, vector=vector, role_family=family, seniority_levels=levels)


def test_cosine_basics():
    assert cosine(vec(1), vec(1)) == pytest.approx(1.0)
    assert cosine(vec(1), vec(0, 1)) == pytest.approx(0.0)
    assert cosine(vec(0), vec(1)) == 0.0                       # zero vector never raises
    assert cosine(vec(3, 4), vec(6, 8)) == pytest.approx(1.0)  # scale does not matter
    with pytest.raises(ValueError):
        cosine((1.0, 0.0), (1.0,))


def test_results_are_ranked_by_similarity_with_stable_ties():
    result = retrieve(QUERY, [cand("b", vec(0.6, 0.8)), cand("a", vec(1.0)), cand("d", vec(0.6, 0.8)), cand("c", vec(0.0, 1.0))])
    assert [r.job_id for r in result.ranked] == ["a", "b", "d", "c"]          # ties broken by id
    assert [r.rank for r in result.ranked] == [1, 2, 3, 4]
    assert result.considered == 4 and result.blocked == ()


def test_checks_run_before_ranking_so_the_limit_is_filled_with_valid_jobs():
    candidates = [
        cand("recruiter", vec(1.0), family="people"),                       # nearest, wrong occupation
        cand("principal", vec(0.99, 0.1), levels=("lead",)),                # near, wrong level
        cand("good1", vec(0.8, 0.6)),
        cand("good2", vec(0.6, 0.8)),
        cand("good3", vec(0.0, 1.0)),
    ]
    result = retrieve(QUERY, candidates, limit=3)
    assert [r.job_id for r in result.ranked] == ["good1", "good2", "good3"]   # still a full page of 3
    assert [b.job_id for b in result.blocked] == ["recruiter", "principal"]    # highest similarity first
    assert result.blocked[0].similarity > result.ranked[0].similarity           # blocked even though nearest
    assert "people" in result.blocked[0].reasons[0] and "level" in result.blocked[1].reasons[0]


def test_without_checks_nothing_is_blocked_but_verdicts_are_still_reported():
    result = retrieve(QUERY, [cand("recruiter", vec(1.0), family="people"), cand("good", vec(0.6, 0.8))], apply_checks=False)
    assert [r.job_id for r in result.ranked] == ["recruiter", "good"] and result.blocked == ()
    assert result.ranked[0].role == "different"


def test_unknown_and_unspecified_never_block_and_are_explained():
    result = retrieve(QUERY, [cand("x", vec(1.0), family=None), cand("y", vec(0.9, 0.1), family="other"),
                              cand("z", vec(0.8, 0.2), levels=())])
    assert len(result.ranked) == 3 and result.blocked == ()
    by_id = {r.job_id: r for r in result.ranked}
    assert by_id["x"].role == "unknown" and not any("role" in r.lower() for r in by_id["x"].reasons)   # a caveat is not a reason
    assert by_id["z"].seniority == "all_levels" and not any("level" in r.lower() for r in by_id["z"].reasons)
    no_seniority = retrieve(ProfileQuery(vector=vec(1.0), role_families=("engineering",)), [cand("p", vec(1.0), levels=("lead",))])
    assert no_seniority.ranked[0].seniority == "unknown" and not any("level" in r.lower() for r in no_seniority.ranked[0].reasons)


def test_adjacent_role_and_level_are_kept_and_labelled():
    result = retrieve(QUERY, [cand("d", vec(1.0), family="data", levels=("mid",))])
    assert result.ranked[0].role == "adjacent" and result.ranked[0].seniority == "adjacent"


def test_limit_none_returns_everything_and_empty_input_is_fine():
    assert len(retrieve(QUERY, [cand(str(i), vec(1.0, i)) for i in range(25)], limit=None).ranked) == 25
    empty = retrieve(QUERY, [])
    assert empty.ranked == () and empty.blocked == () and empty.considered == 0


def test_dimension_mismatch_is_a_clear_error():
    with pytest.raises(ValueError):
        retrieve(QUERY, [RetrievalCandidate(job_id="a", vector=(1.0, 0.0))])


# ---- eligibility must equal the existing ranker's -----------------------------------------------

JOBS = [
    {"id": "1", "title": "Backend Engineer", "status": "open", "location": "Singapore", "work_mode": "hybrid"},
    {"id": "2", "title": "Data Analyst", "status": "closed", "location": "Singapore", "work_mode": "remote"},
    {"id": "3", "title": "Support Engineer", "status": "open", "location": "London", "work_mode": "onsite"},
    {"id": "4", "title": "Platform Engineer", "status": "open", "location": None, "work_mode": None},
    {"id": "5", "title": "Frontend Engineer", "status": "open", "location": "Singapore (Remote)", "work_mode": "remote"},
    {"id": "6", "title": "Accountant", "status": "OPEN", "location": "singapore", "work_mode": "onsite"},
]


@pytest.mark.parametrize("preferences", [
    {}, {"locations": ["Singapore"]}, {"locations": ["London"], "work_modes": ["onsite"]},
    {"work_modes": ["remote"]}, {"locations": ["Singapore"], "work_modes": ["hybrid", "remote"]},
    {"locations": ["Mars"]},
])
def test_eligibility_matches_the_existing_rankers_filter_exactly(preferences):
    profile = {"headline": "Engineer", "skills": ["Python"], "target_roles": ["Engineer"]}
    expected = {item["job"]["id"] for item in rank_jobs(JOBS, profile, preferences)}
    assert {job["id"] for job in eligible_jobs(JOBS, preferences)} == expected


def test_exclusions_remove_reviewed_jobs():
    assert {j["id"] for j in eligible_jobs(JOBS, {}, exclude_job_ids=["1", "4"])} == {"3", "5", "6"}
    assert is_eligible(JOBS[0], None) is True and is_eligible(JOBS[1], None) is False
