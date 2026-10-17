import pytest

from job_hunter.seniority import (
    EVIDENCE_MAX,
    SENIORITY_LADDER,
    SENIORITY_STATED,
    SENIORITY_VERSION,
    classify_seniority,
    levels_from_text,
    normalise_levels,
)


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


def test_ladder():
    assert SENIORITY_LADDER == ("intern", "entry", "mid", "senior", "lead")


def test_levels_come_from_the_title_with_the_matched_phrase_as_evidence():
    assert classify_seniority("Senior Backend Engineer") == (["senior"], SENIORITY_VERSION, "Senior")
    assert classify_seniority("Senior/Staff Engineer") == (["senior", "lead"], SENIORITY_VERSION, "Senior, Staff Engineer")
    assert classify_seniority("Graduate Programme") == (["entry"], SENIORITY_VERSION, "Graduate")


def test_a_title_naming_no_level_is_classified_as_open_to_all_levels():
    # [] (not None): the classifier ran and found nothing, which is different from "never classified"
    assert classify_seniority("Backend Engineer") == ([], SENIORITY_VERSION, None)
    assert classify_seniority("") == ([], SENIORITY_VERSION, None)
    assert classify_seniority(None) == ([], SENIORITY_VERSION, None)


def test_a_level_the_source_states_beats_the_title():
    levels, source, evidence = classify_seniority("Senior Engineer", stated=["Junior ", "bogus"])
    assert (levels, source) == (["entry"], SENIORITY_STATED) and "Junior" in evidence
    assert classify_seniority("Senior Engineer", stated=["entry"])[:2] == (["entry"], SENIORITY_STATED)
    # a stated value that means nothing falls back to the title
    assert classify_seniority("Senior Engineer", stated=["bogus"]) == (["senior"], SENIORITY_VERSION, "Senior")
    assert classify_seniority("Senior Engineer", stated=[]) == (["senior"], SENIORITY_VERSION, "Senior")
    assert classify_seniority("Senior Engineer", stated="Junior") == (["entry"], SENIORITY_STATED, "Junior")


def test_evidence_fits_the_column():
    levels, _, evidence = classify_seniority("Senior Engineer", stated=["Junior " + "x" * 300])
    assert levels == ["entry"] and len(evidence) == EVIDENCE_MAX


def test_executive_is_a_stated_level_only_never_a_title_keyword():
    # a user picking "Executive" in preferences means the top of the ladder ...
    assert normalise_levels(["Executive"]) == ("lead",)
    assert classify_seniority("Head of Data", stated=["Executive"])[:2] == (["lead"], SENIORITY_STATED)
    # ... but "Account Executive" is a sales job, not an executive-level one
    assert levels_from_text("Account Executive") == ()
    assert classify_seniority("Account Executive")[0] == []


def test_normalise_levels_accepts_ladder_names_and_plain_wording_in_ladder_order():
    assert normalise_levels(["Senior", "intern", " Junior "]) == ("intern", "entry", "senior")
    assert normalise_levels(["nonsense", None]) == ()
    assert normalise_levels(None) == ()
