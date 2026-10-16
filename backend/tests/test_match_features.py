import pytest

from job_hunter.embedding.features import (
    ADJACENT_FAMILIES,
    SENIORITY_LADDER,
    SOURCE_INFERRED_FROM_TITLE,
    SOURCE_STATED,
    SOURCE_UNSPECIFIED,
    check_role_family,
    check_seniority,
    extract_job_features,
    extract_profile_features,
    levels_from_text,
)


def fake_classify(title):
    """Stand-in for import_jobs.classify_title (which needs SQLAlchemy); same return shape."""
    t = f" {title.casefold()} "
    for category, words in (("people", ("recruiter",)), ("data", ("data",)), ("engineering", ("engineer", "developer")),
                            ("sales", ("sales", "account executive"))):
        if any(w in t for w in words):
            return category, "title_keyword_v1", words[0]
    return "other", "title_keyword_v1", None


@pytest.mark.parametrize("title,expected", [
    ("Senior Backend Engineer", ("senior",)),
    ("Software Engineer, Intern", ("intern",)),
    ("Internal Auditor", ()),
    ("Staff Accountant", ()),
    ("Staff Software Engineer", ("lead",)),
    ("Lead Generation Specialist", ()),
    ("Team Lead, Payments", ("lead",)),
    ("Principal Recruiter", ("lead",)),
    ("Senior/Staff Engineer", ("senior", "lead")),
    ("Junior Developer", ("entry",)),
    ("Software Engineer, New Grad", ("entry",)),
    ("Global Trainee Program 2027", ("entry",)),
    ("Operations Manager", ()),
    ("Product Manager, Payments", ()),
    ("Engineering Manager, Payments", ("lead",)),
    ("Manager, Engineering", ("lead",)),
    ("Senior Engineering Manager", ("senior", "lead")),
    ("Associate Software Engineer", ()),
    ("(Senior) Finance Associate - 6 Month Maternity Cover", ("senior",)),
    ("Head of Data", ("lead",)),
    ("VP, Sales", ("lead",)),
    ("Mid-level Data Analyst", ("mid",)),
    ("Backend Engineer", ()),
    ("", ()),
    (None, ()),
])
def test_levels_from_title(title, expected):
    assert levels_from_text(title) == expected


def test_job_features_stated_beats_inferred_and_unspecified_is_flagged():
    # plain wording is understood and unknown words are ignored; a stated value beats the title
    stated = extract_job_features("Senior Engineer", stated_seniority=["Junior ", "bogus"], classify=fake_classify)
    assert (stated.seniority_levels, stated.seniority_source) == (("entry",), SOURCE_STATED)
    stated = extract_job_features("Senior Engineer", stated_seniority=["entry"], classify=fake_classify)
    assert (stated.seniority_levels, stated.seniority_source) == (("entry",), SOURCE_STATED)
    # a stated value that means nothing falls back to the title
    fallback = extract_job_features("Senior Engineer", stated_seniority=["bogus"], classify=fake_classify)
    assert (fallback.seniority_levels, fallback.seniority_source) == (("senior",), SOURCE_INFERRED_FROM_TITLE)
    inferred = extract_job_features("Senior Engineer", classify=fake_classify)
    assert (inferred.seniority_levels, inferred.seniority_source) == (("senior",), SOURCE_INFERRED_FROM_TITLE)
    unspecified = extract_job_features("Backend Engineer", classify=fake_classify)
    assert (unspecified.seniority_levels, unspecified.seniority_source) == ((), SOURCE_UNSPECIFIED)


def test_job_role_family_uses_the_title_classifier_first_then_the_stored_category():
    assert extract_job_features("Backend Engineer", category="engineering", classify=fake_classify).role_family == "engineering"
    # the title classifier wins over a stored category that disagrees
    assert extract_job_features("Backend Engineer", category="people", classify=fake_classify).role_family == "engineering"
    # when the title says nothing, the stored category is the fallback
    assert extract_job_features("Fraud Strategist", category="operations", classify=fake_classify).role_family == "operations"
    assert extract_job_features("Fraud Strategist", category="other", classify=fake_classify).role_family is None
    assert extract_job_features("Data Analyst", category=None, classify=fake_classify).role_family == "data"
    assert extract_job_features("Fraud Strategist", category=None, classify=fake_classify).role_family is None


def test_profile_features():
    f = extract_profile_features(["Backend Engineer", "backend developer", "Data Analyst"], "Junior", classify=fake_classify)
    assert f.role_families == ("engineering", "data")
    assert f.seniority_levels == ("entry",)
    empty = extract_profile_features(None, None, classify=fake_classify)
    assert empty.role_families == () and empty.seniority_levels == ()
    assert extract_profile_features(["Mystery Role"], ["Senior", "x"], classify=fake_classify).seniority_levels == ("senior",)


def test_seniority_verdicts():
    assert check_seniority(["entry"], ["entry"]).verdict == "match"
    assert check_seniority(["mid"], ["entry"]).verdict == "adjacent"
    assert check_seniority(["senior"], ["entry"]).verdict == "mismatch"
    assert check_seniority(["lead"], ["entry"]).blocks is True
    assert check_seniority(["intern"], ["senior"]).verdict == "mismatch"
    # several job levels: the closest one counts
    assert check_seniority(["entry", "mid"], ["mid"]).verdict == "match"
    assert check_seniority(["senior", "lead"], ["mid"]).verdict == "adjacent"


def test_unspecified_job_counts_as_all_levels_and_is_flagged():
    for job in (None, [], ()):
        result = check_seniority(job, ["entry"])
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
    assert SENIORITY_LADDER == ("intern", "entry", "mid", "senior", "lead")


def test_recruiter_and_seniority_traps_are_caught_without_hurting_good_jobs():
    profile = extract_profile_features(["Backend Engineer"], "Junior", classify=fake_classify)
    trap = extract_job_features("Principal Recruiter", category="people", classify=fake_classify)
    assert check_role_family(trap.role_family, profile.role_families).blocks is True
    assert check_seniority(trap.seniority_levels, profile.seniority_levels).blocks is True
    senior = extract_job_features("Senior Backend Engineer", category="engineering", classify=fake_classify)
    assert check_role_family(senior.role_family, profile.role_families).blocks is False
    assert check_seniority(senior.seniority_levels, profile.seniority_levels).blocks is True
    good = extract_job_features("Backend Engineer, Payments", category="engineering", classify=fake_classify)
    assert check_role_family(good.role_family, profile.role_families).verdict == "same"
    assert check_seniority(good.seniority_levels, profile.seniority_levels).verdict == "all_levels"


def test_real_classifier_agrees_on_the_trap_titles():
    jobs = {
        "Principal Recruiter": "people",
        "Technical Recruiter (Fixed Term Contract)": "people",
        "Backend Engineer": "engineering",
        "Senior Data Scientist": "data",
    }
    for title, family in jobs.items():
        assert extract_job_features(title).role_family == family
    profile = extract_profile_features(["Backend Engineer"], "Junior")
    assert profile.role_families == ("engineering",)


def test_executive_is_a_stated_level_only_never_a_title_keyword():
    # a user picking "Executive" in preferences means the top of the ladder ...
    assert extract_profile_features(["Head of Data"], "Executive", classify=fake_classify).seniority_levels == ("lead",)
    assert extract_profile_features(None, ["Executive"], classify=fake_classify).seniority_levels == ("lead",)
    # ... but "Account Executive" is a sales job, not an executive-level one
    assert levels_from_text("Account Executive") == ()
    assert extract_job_features("Account Executive", classify=fake_classify).seniority_levels == ()


def test_role_hint_from_snapshot():
    from job_hunter.embedding.features import role_hint_from_snapshot

    assert role_hint_from_snapshot({"headline": " Data & Backend Engineer "}) == ["Data & Backend Engineer"]
    assert role_hint_from_snapshot({"headline": "", "experience": [{"role": "Data Analyst"}]}) == ["Data Analyst"]
    assert role_hint_from_snapshot({"experience": [{"title": "Engineer"}]}) == ["Engineer"]
    assert role_hint_from_snapshot({}) == [] and role_hint_from_snapshot(None) == []
