import pytest
from pydantic import ValidationError

from job_hunter.api.main import PreferencesWrite, seniority_options
from job_hunter.seniority import SENIORITY_LADDER


def test_options_match_classifier_ladder():
    assert [item["value"] for item in seniority_options()["items"]] == list(SENIORITY_LADDER)


@pytest.mark.parametrize("value,expected", [("entry", "entry"), ("Junior", "entry"),
                                             ("Mid-level", "mid"), ("Executive", "lead"), ("", None)])
def test_preference_seniority_is_canonical(value, expected):
    assert PreferencesWrite(expected_revision=0, seniority=value).seniority == expected


def test_unsupported_preference_seniority_rejected():
    with pytest.raises(ValidationError):
        PreferencesWrite(expected_revision=0, seniority="novice")
