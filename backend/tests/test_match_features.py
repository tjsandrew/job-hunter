import pytest

from job_hunter.embedding.features import (
    ADJACENT_FAMILIES,
    SENIORITY_LADDER,
    check_role_family,
    check_seniority,
    extract_profile_features,
    job_role_family,
    job_seniority_levels,
    role_hint_from_snapshot,
)
from job_hunter.role_family import classify_role_family
from job_hunter.seniority import classify_seniority


def fake_classify(title):
    """A tiny stand-in classifier with the real one's return shape (family, version, evidence)."""
    t = f" {title.casefold()} "
    for category, words in (("people", ("recruiter",)), ("data", ("data",)), ("engineering", ("engineer", "developer")),
                            ("sales", ("sales", "account executive"))):
        if any(w in t for w in words):
            return category, "title_keyword_v1", words[0]
    return "other", "title_keyword_v1", None


def stored_job(title):
    """The role family and levels the recommender reads for a job that ingestion classified from its title."""
    return job_role_family(classify_role_family(title)[0]), job_seniority_levels(classify_seniority(title)[0])


@pytest.mark.parametrize("category,expected", [
    ("engineering", "engineering"), (" Data ", "data"), ("people", "people"),
    # unknown, empty, "other" or a label the checks do not know all count as unknown, which never blocks
    ("other", None), ("", None), (None, None), ("astronaut", None),
])
def test_job_role_family_is_read_from_the_stored_category(category, expected):
    assert job_role_family(category) == expected


@pytest.mark.parametrize("stored,expected", [
    (None, ()), ([], ()), (["senior"], ("senior",)), (["lead", "senior"], ("senior", "lead")),
    (["bogus", "junior"], ("junior",)), (["Senior"], ("senior",)),
])
def test_job_seniority_levels_are_read_from_the_stored_column(stored, expected):
    assert job_seniority_levels(stored) == expected


def test_profile_features():
    f = extract_profile_features(["Backend Engineer", "backend developer", "Data Analyst"], "Junior", classify=fake_classify)
    assert f.role_families == ("engineering", "data")
    assert f.seniority_levels == ("junior",)
    empty = extract_profile_features(None, None, classify=fake_classify)
    assert empty.role_families == () and empty.seniority_levels == ()
    assert extract_profile_features(["Mystery Role"], ["Senior", "x"], classify=fake_classify).seniority_levels == ("senior",)


def test_seniority_verdicts():
    assert check_seniority(["junior"], ["junior"]).verdict == "match"
    assert check_seniority(["mid"], ["junior"]).verdict == "adjacent"
    assert check_seniority(["senior"], ["junior"]).verdict == "mismatch"
    assert check_seniority(["lead"], ["junior"]).blocks is True
    assert check_seniority(["intern"], ["senior"]).verdict == "mismatch"
    # several job levels: the closest one counts
    assert check_seniority(["junior", "mid"], ["mid"]).verdict == "match"
    assert check_seniority(["senior", "lead"], ["mid"]).verdict == "adjacent"


def test_unspecified_job_counts_as_all_levels_and_is_flagged():
    for job in (None, [], ()):
        result = check_seniority(job, ["junior"])
        assert result.verdict == "all_levels" and result.job_unspecified is True and result.blocks is False
    # unspecified takes precedence even when the profile is also unset
    assert check_seniority(None, None).verdict == "all_levels"


def test_unknown_profile_seniority_never_blocks():
    result = check_seniority(["lead"], None)
    assert result.verdict == "unknown" and result.blocks is False and result.job_unspecified is False


def test_role_family_verdicts():
    assert check_role_family("engineering", ["engineering"]).verdict == "same"
    assert check_role_family("data", ["engineering"]).verdict == "adjacent"
    assert check_role_family("engineering", ["data"]).verdict == "adjacent"
    different = check_role_family("people", ["engineering"])
    assert different.verdict == "different" and different.blocks is True
    # best verdict across several target families
    assert check_role_family("data", ["people", "engineering"]).verdict == "adjacent"
    assert check_role_family("people", ["people", "engineering"]).verdict == "same"


@pytest.mark.parametrize("job,profile", [
    (None, ["engineering"]), ("other", ["engineering"]), ("", ["engineering"]),
    ("engineering", None), ("engineering", []), ("engineering", ["other"]),
])
def test_unknown_role_family_never_blocks(job, profile):
    result = check_role_family(job, profile)
    assert result.verdict == "unknown" and result.blocks is False


def test_adjacency_table_is_symmetric_and_uses_known_families():
    assert all(len(pair) == 2 for pair in ADJACENT_FAMILIES)
    assert SENIORITY_LADDER == ("intern", "junior", "mid", "senior", "lead", "executive")


def test_recruiter_and_seniority_traps_are_caught_without_hurting_good_jobs():
    profile = extract_profile_features(["Backend Engineer"], "Junior")
    family, levels = stored_job("Principal Recruiter")
    assert check_role_family(family, profile.role_families).blocks is True
    assert check_seniority(levels, profile.seniority_levels).blocks is True
    family, levels = stored_job("Senior Backend Engineer")
    assert check_role_family(family, profile.role_families).blocks is False
    assert check_seniority(levels, profile.seniority_levels).blocks is True
    family, levels = stored_job("Backend Engineer, Payments")
    assert check_role_family(family, profile.role_families).verdict == "same"
    assert check_seniority(levels, profile.seniority_levels).verdict == "all_levels"


def test_real_classifier_agrees_on_the_trap_titles():
    jobs = {
        "Principal Recruiter": "people",
        "Technical Recruiter (Fixed Term Contract)": "people",
        "Backend Engineer": "engineering",
        "Senior Data Scientist": "data",
    }
    for title, family in jobs.items():
        assert stored_job(title)[0] == family
    assert extract_profile_features(["Backend Engineer"], "Junior").role_families == ("engineering",)


def test_executive_in_a_preference_is_its_own_level():
    assert extract_profile_features(["Head of Data"], "Executive", classify=fake_classify).seniority_levels == ("executive",)
    assert extract_profile_features(None, ["Executive"], classify=fake_classify).seniority_levels == ("executive",)


def test_lead_and_executive_count_as_the_same_level_in_the_checks():
    for job, profile in ((["lead"], ["executive"]), (["executive"], ["lead"]), (["executive"], ["executive"])):
        assert check_seniority(job, profile).verdict == "match"
    # and executive sits at the top of the ladder like lead does
    assert check_seniority(["executive"], ["senior"]).verdict == "adjacent"
    assert check_seniority(["executive"], ["mid"]).blocks is True
    assert check_seniority(["executive"], ["junior"]).blocks is True
    assert check_seniority(["lead"], ["junior"]).blocks is True


def test_role_hint_from_snapshot():
    assert role_hint_from_snapshot({"headline": " Data & Backend Engineer "}) == ["Data & Backend Engineer"]
    assert role_hint_from_snapshot({"headline": "", "experience": [{"role": "Data Analyst"}]}) == ["Data Analyst"]
    assert role_hint_from_snapshot({"experience": [{"title": "Engineer"}]}) == ["Engineer"]
    assert role_hint_from_snapshot({}) == [] and role_hint_from_snapshot(None) == []


def test_profile_features_carry_engineering_subroles():
    f = extract_profile_features(["Senior Backend Engineer", "Staff Engineer"], "Senior")
    assert f.engineering_subroles == ("backend",) and f.role_families == ("engineering",)
    assert extract_profile_features(["Data Analyst"], "Mid").engineering_subroles == ()
