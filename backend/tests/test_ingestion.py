from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from job_hunter.ingestion import discovery
from job_hunter.ingestion.discovery import (
    DiscoveryConfig,
    ProviderHTTPError,
    ProviderRequestError,
    _normalise,
    discover_report,
)


def test_greenhouse_normalization_keeps_absent_values_null_and_html_clean():
    job = _normalise(
        source="greenhouse",
        board="sample-co",
        fetched_at="2026-10-05T00:00:00Z",
        raw={
            "id": 42,
            "title": "Data Engineer",
            "absolute_url": "https://boards.greenhouse.io/sample-co/jobs/42",
            "location": {"name": "Singapore"},
            "content": "&amp;lt;p&amp;gt;Build &amp;amp; ship&amp;lt;/p&amp;gt;",
            "first_published": "2026-10-01T10:00:00+08:00",
        },
    )
    assert job is not None
    assert job["description"] == "Build & ship"
    assert job["posted_at"] == "2026-10-01T02:00:00Z"
    assert job["fetched_at"] == "2026-10-05T00:00:00Z"
    assert job["dedup_key"] == "greenhouse:sample-co:42"
    assert job["salary_min"] is job["salary_max"] is None
    assert job["salary_currency"] is job["salary_period"] is None
    assert job["expires_at"] is None


def test_lever_normalization_maps_salary_and_millisecond_timestamp():
    job = _normalise(
        source="lever",
        board="sample-site",
        fetched_at="2026-10-05T00:00:00Z",
        raw={
            "id": "abc-1",
            "text": "Product Analyst",
            "hostedUrl": "https://jobs.lever.co/sample-site/abc-1",
            "categories": {"location": "Singapore", "allLocations": ["Singapore", "Remote"]},
            "workplaceType": "hybrid",
            "createdAt": 1790812800000,
            "salaryRange": {"min": 80000, "max": 100000, "currency": "SGD", "interval": "year"},
            "descriptionPlain": "Analyze product usage",
        },
    )
    assert job is not None
    assert job["location"] == "Singapore, Remote"
    assert job["work_mode"] == "hybrid"
    assert job["salary_min"] == 80000
    assert job["salary_max"] == 100000
    assert job["salary_currency"] == "SGD"
    assert job["salary_period"] == "year"
    assert job["posted_at"] == "2026-10-01T00:00:00Z"
    assert job["expires_at"] is None


def test_smartrecruiters_normalization_maps_public_posting_fields():
    job = _normalise(
        source="smartrecruiters",
        board="Grab",
        fetched_at="2026-10-05T00:00:00Z",
        raw={
            "id": "posting-1",
            "name": "Senior Software Engineer",
            "applyUrl": "https://jobs.smartrecruiters.com/Grab/posting-1",
            "releasedDate": "2026-10-01T10:00:00.000Z",
            "company": {"name": "Grab"},
            "location": {"city": "Singapore", "country": "Singapore", "countryCode": "sg"},
        },
    )
    assert job is not None
    assert job["source"] == "smartrecruiters"
    assert job["employer"] == "Grab"
    assert job["location"] == "Singapore"
    assert job["source_url"].endswith("posting-1")
    assert job["posted_at"] == "2026-10-01T10:00:00Z"
    assert job["salary_min"] is None
    assert job["description"] is None


def test_smartrecruiters_uses_singapore_country_filter_and_excludes_other_locations(monkeypatch):
    calls = []
    monkeypatch.setattr(discovery, "_fetch_json", lambda url, *a: (
        calls.append(url) or {
            "offset": 0,
            "limit": 2,
            "totalFound": 2,
            "content": [
                {"id": "sg", "name": "Singapore role", "applyUrl": "https://x/sg",
                 "location": {"city": "Singapore", "countryCode": "sg"}},
                {"id": "remote", "name": "Remote role", "applyUrl": "https://x/r",
                 "location": {"city": "Remote", "remote": True, "countryCode": "us"}},
            ],
        }
    ))
    report = discover_report(DiscoveryConfig(smartrecruiters_boards=["Grab"], page_size=2))
    assert len(report.jobs) == 1
    assert report.jobs[0]["external_id"] == "sg"
    assert "country=sg" in calls[0]
    assert "offset=0" in calls[0]


def test_greenhouse_reads_single_documented_full_board_page_and_caps_records(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_json", lambda *a: {"jobs": [
        {"id": i, "title": f"Role {i}", "absolute_url": f"https://example.test/{i}", "location": {"name": "Singapore"}}
        for i in range(4)
    ]})
    report = discover_report(DiscoveryConfig(greenhouse_boards=["board"], max_records_per_board=2))
    assert len(report.jobs) == 2
    assert report.truncated_boards == ["greenhouse:board"]
    assert not report.failures


def test_greenhouse_singapore_filter_uses_location(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_json", lambda *a: {"jobs": [
        {"id": 1, "title": "SG", "absolute_url": "https://x/1", "location": {"name": "Singapore"}},
        {"id": 2, "title": "Remote", "absolute_url": "https://x/2", "location": {"name": "Remote"}},
    ]})
    report = discover_report(DiscoveryConfig(greenhouse_boards=["board"], singapore_only=True))
    assert [job["title"] for job in report.jobs] == ["SG"]


def test_lever_pagination_and_request_budget(monkeypatch):
    calls = []
    def fake_fetch(url, timeout, provider):
        calls.append(url)
        query = parse_qs(urlparse(url).query)
        skip = int(query["skip"][0])
        return [
            {"id": str(i), "text": f"Role {i}", "hostedUrl": f"https://jobs.lever.co/x/{i}"}
            for i in range(skip, skip + 2)
        ]
    monkeypatch.setattr(discovery, "_fetch_json", fake_fetch)
    report = discover_report(DiscoveryConfig(lever_boards=["site"], page_size=2, max_pages_per_board=2))
    assert [j["external_id"] for j in report.jobs] == ["0", "1", "2", "3"]
    assert [parse_qs(urlparse(url).query)["skip"][0] for url in calls] == ["0", "2"]
    assert report.truncated_boards == ["lever:site"]


def test_rate_limit_and_partial_source_failure_are_reported(monkeypatch):
    monkeypatch.setattr(discovery, "_discover_greenhouse", lambda *a: (_ for _ in ()).throw(ProviderHTTPError("greenhouse", 429, "url")))
    monkeypatch.setattr(discovery, "_discover_lever", lambda *a: ([{"title": "ok"}], False))
    report = discover_report(DiscoveryConfig(greenhouse_boards=["bad"], lever_boards=["good"]))
    assert report.jobs == [{"title": "ok"}]
    assert report.failures[0]["kind"] == "rate_limited"


def test_http_error_classification():
    assert ProviderHTTPError("x", 429, "u").kind == "rate_limited"
    assert ProviderHTTPError("x", 503, "u").kind == "server_error"
    assert ProviderHTTPError("x", 404, "u").kind == "http_error"
    assert ProviderRequestError("x", "timeout", "t").kind == "timeout"


@pytest.mark.parametrize("kwargs", [
    {"timeout_seconds": 0},
    {"timeout_seconds": 61},
    {"page_size": 101},
    {"max_pages_per_board": 11},
    {"max_records_per_board": 1001},
])
def test_config_rejects_unbounded_values(kwargs):
    with pytest.raises(ValueError):
        DiscoveryConfig(**kwargs)
