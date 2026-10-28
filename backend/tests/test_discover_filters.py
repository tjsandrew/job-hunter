"""Discover's per-request filters: which preferences a job list ranks with (no database needed)."""
import pytest
from fastapi import HTTPException

from job_hunter.api.main import PreferencesWrite, discover_filters


def build(**values):
    params = dict(filters="saved", role=[], location=[], work_mode=[], seniority=None,
                  salary_min=None, salary_currency=None, salary_period=None)
    params.update(values)
    return discover_filters(**params)


def test_saved_uses_the_profile_defaults():
    assert build() is None


def test_none_ranks_without_preferences():
    assert build(filters="none") == {}


def test_custom_builds_preferences_for_this_request_only():
    assert build(filters="custom", role=[" Data engineer ", ""], location=["Singapore"], work_mode=["remote"],
                 seniority="Mid-level", salary_min=4000, salary_period="month") == {
        "roles": ["Data engineer"], "locations": ["Singapore"], "work_modes": ["remote"], "seniority": "mid",
        "salary_min": 4000.0, "salary_currency": "SGD", "salary_period": "month"}


def test_custom_ignores_values_sent_without_choosing_custom():
    assert build(filters="saved", role=["Ignored"]) is None


@pytest.mark.parametrize("values", [{"seniority": "novice"}, {"role": ["x" * 101]},
                                    {"work_mode": ["remote", "hybrid", "onsite", "remote"]}])
def test_invalid_custom_filters_are_rejected(values):
    with pytest.raises(HTTPException) as raised:
        build(filters="custom", **values)
    assert raised.value.status_code == 422
    assert raised.value.detail["code"] == "INVALID_FILTERS"


def test_saving_preferences_keeps_the_same_rules():
    saved = PreferencesWrite(expected_revision=0, roles=[" Backend engineer "], seniority="Senior")
    assert saved.roles == ["Backend engineer"] and saved.seniority == "senior"
