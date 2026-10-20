import pytest

from job_hunter.seniority import (
    CHECK_LADDER,
    EVIDENCE_MAX,
    SENIORITY_LADDER,
    SENIORITY_STATED,
    SENIORITY_VERSION,
    check_rank,
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
    ("Junior Developer", ("junior",)),
    ("Software Engineer, New Grad", ("junior",)),
    ("Global Trainee Program 2027", ("junior",)),
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
    assert SENIORITY_LADDER == ("intern", "junior", "mid", "senior", "lead", "executive")
    # the match checks compare lead and executive as one step (until a larger labelled set says otherwise)
    assert CHECK_LADDER == ("intern", "junior", "mid", "senior", "lead")
    assert check_rank("executive") == check_rank("lead") == 4
    assert [check_rank(level) for level in ("intern", "junior", "mid", "senior")] == [0, 1, 2, 3]


def test_levels_come_from_the_title_with_the_matched_phrase_as_evidence():
    assert classify_seniority("Senior Backend Engineer") == (["senior"], SENIORITY_VERSION, "Senior")
    assert classify_seniority("Senior/Staff Engineer") == (["senior", "lead"], SENIORITY_VERSION, "Senior, Staff Engineer")
    assert classify_seniority("Graduate Programme") == (["junior"], SENIORITY_VERSION, "Graduate")


def test_a_title_naming_no_level_is_classified_as_open_to_all_levels():
    # [] (not None): the classifier ran and found nothing, which is different from "never classified"
    assert classify_seniority("Backend Engineer") == ([], SENIORITY_VERSION, None)
    assert classify_seniority("") == ([], SENIORITY_VERSION, None)
    assert classify_seniority(None) == ([], SENIORITY_VERSION, None)


def test_a_level_the_source_states_beats_the_title():
    levels, source, evidence = classify_seniority("Senior Engineer", stated=["Junior ", "bogus"])
    assert (levels, source) == (["junior"], SENIORITY_STATED) and "Junior" in evidence
    assert classify_seniority("Senior Engineer", stated=["junior"])[:2] == (["junior"], SENIORITY_STATED)
    # a stated value that means nothing falls back to the title
    assert classify_seniority("Senior Engineer", stated=["bogus"]) == (["senior"], SENIORITY_VERSION, "Senior")
    assert classify_seniority("Senior Engineer", stated=[]) == (["senior"], SENIORITY_VERSION, "Senior")
    assert classify_seniority("Senior Engineer", stated="Junior") == (["junior"], SENIORITY_STATED, "Junior")


def test_evidence_fits_the_column():
    levels, _, evidence = classify_seniority("Senior Engineer", stated=["Junior " + "x" * 300])
    assert levels == ["junior"] and len(evidence) == EVIDENCE_MAX


def test_executive_is_a_stated_level_only_never_a_title_keyword():
    # a user picking "Executive" in preferences, or a source stating it, is stored as its own level ...
    assert normalise_levels(["Executive"]) == ("executive",)
    assert classify_seniority("Head of Data", stated=["Executive"])[:2] == (["executive"], SENIORITY_STATED)
    # ... while the title rules still return "lead" for director/VP/chief/head-of titles (they cannot tell them apart)
    assert classify_seniority("VP, Sales")[0] == ["lead"]
    # ... but "Account Executive" is a sales job, not an executive-level one
    assert levels_from_text("Account Executive") == ()
    assert classify_seniority("Account Executive")[0] == []


def test_normalise_levels_accepts_ladder_names_and_plain_wording_in_ladder_order():
    assert normalise_levels(["Senior", "intern", " Junior "]) == ("intern", "junior", "senior")


def test_legacy_keys_and_wording_are_converted():
    # "entry" was the key before the contract used the dropdown's own word; "Mid-level" was a stored label
    assert normalise_levels("entry") == ("junior",)
    assert normalise_levels(["Entry", "Mid-level"]) == ("junior", "mid")
    assert classify_seniority("Senior Engineer", stated="entry")[:2] == (["junior"], SENIORITY_STATED)
    assert normalise_levels(["nonsense", None]) == ()
    assert normalise_levels(None) == ()


def test_head_without_of_is_lead_level():
    assert classify_seniority("Head, Merchant Acquisition")[0] == ["lead"]
    assert classify_seniority("Product Head Count Analyst")[0] == []
