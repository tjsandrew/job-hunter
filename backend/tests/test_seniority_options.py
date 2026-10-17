import pytest
from pydantic import ValidationError

from job_hunter.api.main import PreferencesWrite, seniority_options
from job_hunter.seniority import SENIORITY_LADDER


def test_options_match_classifier_ladder():
    assert [item["value"] for item in seniority_options()["items"]] == list(SENIORITY_LADDER)


def test_options_keep_the_six_dropdown_words():
    assert [(item["value"], item["label"]) for item in seniority_options()["items"]] == [
        ("intern", "Intern"), ("junior", "Junior / Entry-level"), ("mid", "Mid-level"),
        ("senior", "Senior"), ("lead", "Lead"), ("executive", "Executive")]


@pytest.mark.parametrize("value,expected", [("junior", "junior"), ("Junior", "junior"), ("entry", "junior"),
                                             ("Mid-level", "mid"), ("Lead", "lead"), ("Executive", "executive"),
                                             ("", None)])
def test_preference_seniority_is_canonical(value, expected):
    assert PreferencesWrite(expected_revision=0, seniority=value).seniority == expected


def test_unsupported_preference_seniority_rejected():
    with pytest.raises(ValidationError):
        PreferencesWrite(expected_revision=0, seniority="novice")
