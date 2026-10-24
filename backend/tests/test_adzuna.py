from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from job_hunter.ingestion import discovery
from job_hunter.ingestion.discovery import DiscoveryConfig, ProviderHTTPError, _normalise, discover_report

APP_ID, APP_KEY = "id-12345", "key-67890-secret"


def adzuna_job(identifier, **overrides):
    raw = {"id": identifier, "title": "Data Engineer", "company": {"display_name": "Acme Pte Ltd"},
           "location": {"display_name": "Singapore", "area": ["Singapore"]},
           "description": "Build and run data pipelines for the platform team...",
           "redirect_url": f"https://www.adzuna.sg/land/ad/{identifier}?se=abc",
           "created": "2026-10-20T08:30:00Z", "salary_min": 90000.0, "salary_max": 120000.0, "salary_is_predicted": "0"}
    raw.update(overrides)
    return raw


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", APP_ID)
    monkeypatch.setenv("ADZUNA_APP_KEY", APP_KEY)
    monkeypatch.setattr(discovery.time, "sleep", lambda seconds: None)


def test_normalisation_keeps_what_the_posting_says():
    job = _normalise(source="adzuna", board="sg", raw=adzuna_job("42"), fetched_at="2026-10-24T00:00:00Z")
    assert job["dedup_key"] == "adzuna:sg:42" and job["source"] == "adzuna" and job["source_board"] == "sg"
    assert job["employer"] == "Acme Pte Ltd" and job["location"] == "Singapore" and job["title"] == "Data Engineer"
    assert job["source_url"].startswith("https://www.adzuna.sg/land/ad/42")
    assert job["posted_at"] == "2026-10-20T08:30:00Z"
    assert (job["salary_min"], job["salary_max"], job["salary_currency"], job["salary_period"]) == (90000.0, 120000.0, "SGD", "year")


def test_a_salary_estimated_by_adzuna_is_not_stored():
    job = _normalise(source="adzuna", board="sg", raw=adzuna_job("43", salary_is_predicted="1"), fetched_at="2026-10-24T00:00:00Z")
    assert job["salary_min"] is None and job["salary_max"] is None and job["salary_currency"] is None and job["salary_period"] is None


def test_a_result_without_an_id_title_or_link_is_skipped():
    for broken in ({"id": None}, {"title": ""}, {"redirect_url": None}):
        assert _normalise(source="adzuna", board="sg", raw=adzuna_job("44", **broken), fetched_at="2026-10-24T00:00:00Z") is None


def test_pages_start_at_one_and_stop_when_the_results_run_out(monkeypatch):
    calls = []

    def fake_fetch(url, timeout, provider):
        calls.append(url)
        page = int(urlparse(url).path.rsplit("/", 1)[1])
        return {"count": 3, "results": [adzuna_job(str(i)) for i in range((page - 1) * 2, min(page * 2, 3))]}
    monkeypatch.setattr(discovery, "_fetch_json", fake_fetch)
    report = discover_report(DiscoveryConfig(adzuna_searches=["data engineer"], page_size=2, max_pages_per_board=5, singapore_only=True))
    assert [job["external_id"] for job in report.jobs] == ["0", "1", "2"]
    assert [urlparse(url).path.rsplit("/", 1)[1] for url in calls] == ["1", "2"]
    query = parse_qs(urlparse(calls[0]).query)
    assert query["what"] == ["data engineer"] and query["results_per_page"] == ["2"] and query["app_id"] == [APP_ID]
    assert calls[0].startswith(discovery.ADZUNA_API + "/1?")
    assert not report.failures and not report.truncated_boards


def test_a_page_size_above_the_adzuna_limit_is_lowered(monkeypatch):
    seen = []
    monkeypatch.setattr(discovery, "_fetch_json", lambda url, timeout, provider: seen.append(url) or {"count": 0, "results": []})
    discover_report(DiscoveryConfig(adzuna_searches=["analyst"], page_size=100))
    assert parse_qs(urlparse(seen[0]).query)["results_per_page"] == [str(discovery.ADZUNA_MAX_PER_PAGE)]


def test_caps_records_and_reports_truncation(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_json", lambda *a: {"count": 500, "results": [adzuna_job(str(i)) for i in range(3)]})
    report = discover_report(DiscoveryConfig(adzuna_searches=["analyst"], page_size=3, max_records_per_board=2))
    assert len(report.jobs) == 2 and report.truncated_boards == ["adzuna:analyst"]


def test_only_singapore_results_are_kept_when_asked(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_json", lambda *a: {"count": 2, "results": [
        adzuna_job("1"), adzuna_job("2", location={"display_name": "London"})]})
    report = discover_report(DiscoveryConfig(adzuna_searches=["analyst"], singapore_only=True))
    assert [job["external_id"] for job in report.jobs] == ["1"]


def test_without_keys_the_search_fails_cleanly_and_other_sources_still_run(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_KEY")
    monkeypatch.setattr(discovery, "_discover_lever", lambda *a: ([{"title": "ok", "dedup_key": "lever:x:1"}], False))
    report = discover_report(DiscoveryConfig(adzuna_searches=["analyst"], lever_boards=["x"]))
    assert [job["title"] for job in report.jobs] == ["ok"]
    assert report.failures[0]["kind"] == "missing_credentials" and report.failures[0]["source"] == "adzuna"


def test_a_rejected_request_never_puts_the_keys_in_the_failure_report(monkeypatch):
    def refuse(url, timeout, provider):
        raise ProviderHTTPError(provider, 401, url)
    monkeypatch.setattr(discovery, "_fetch_json", refuse)
    report = discover_report(DiscoveryConfig(adzuna_searches=["analyst"]))
    text = repr(report.failures)
    assert report.failures[0]["kind"] == "http_error" and APP_ID not in text and APP_KEY not in text
    assert APP_ID not in repr(DiscoveryConfig(adzuna_searches=["analyst"]))      # the configuration never holds the keys


def test_the_delay_between_pages_is_bounded():
    with pytest.raises(ValueError):
        DiscoveryConfig(adzuna_delay_seconds=11)
