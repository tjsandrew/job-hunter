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


def test_lever_normalization_preserves_section_headers_bullets_and_closing_text():
    job = _normalise(
        source="lever",
        board="sample-site",
        fetched_at="2026-10-05T00:00:00Z",
        raw={
            "id": "abc-2",
            "text": "Data Analyst",
            "hostedUrl": "https://jobs.lever.co/sample-site/abc-2",
            "descriptionPlain": "Join our analytics team.\nYou will work with stakeholders.",
            "lists": [
                {
                    "text": "Responsibilities",
                    "content": "<ul><li>Build SQL dashboards</li><li>Review data quality</li></ul>",
                },
                {
                    "text": "Requirements",
                    "content": "<p>Strong SQL skills</p><p>Experience with reporting</p>",
                },
            ],
            "additionalPlain": "We welcome applicants from varied backgrounds.",
        },
    )
    assert job is not None
    description = job["description"]
    assert description.startswith("Join our analytics team.\nYou will work with stakeholders.")
    assert "Responsibilities\n• Build SQL dashboards\n• Review data quality" in description
    assert "Requirements\nStrong SQL skills\nExperience with reporting" in description
    assert description.endswith("We welcome applicants from varied backgrounds.")


def test_html_cleaner_keeps_readable_paragraph_and_list_breaks():
    job = _normalise(
        source="lever",
        board="sample-site",
        fetched_at="2026-10-05T00:00:00Z",
        raw={
            "id": "abc-3",
            "text": "Engineer",
            "hostedUrl": "https://jobs.lever.co/sample-site/abc-3",
            "description": "<h2>About the role</h2><p>Build systems.</p><ul><li>Python</li><li>SQL</li></ul>",
        },
    )
    assert job is not None
    assert job["description"] == "About the role\nBuild systems.\n• Python\n• SQL"


def test_lever_plain_text_bullets_are_joined_to_their_item_text():
    job = _normalise(
        source="lever",
        board="sample-site",
        fetched_at="2026-10-05T00:00:00Z",
        raw={
            "id": "abc-4",
            "text": "Accountant",
            "hostedUrl": "https://jobs.lever.co/sample-site/abc-4",
            "descriptionPlain": "What You’ll Do\n•\nManage accounts\n•\nReview reconciliations",
        },
    )
    assert job is not None
    assert job["description"] == "What You’ll Do\n• Manage accounts\n• Review reconciliations"


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


def _mcf_job(uuid: str, **overrides):
    job = {
        "uuid": uuid,
        "title": f"Data Analyst {uuid}",
        "description": "<p>Responsibilities</p><ul><li>Build dashboards</li><li>Write SQL</li></ul>",
        "postedCompany": {"name": "ABEAM CONSULTING (SINGAPORE) PTE. LTD."},
        "salary": {"minimum": 4000, "maximum": 6000, "type": {"salaryType": "Monthly"}},
        "positionLevels": [{"position": "Senior Executive"}],
        "skills": [{"skill": "SQL"}, {"skill": "Power BI"}, {"skill": "SQL"}],
        "address": {"districts": [{"location": "Raffles Place"}, {"location": "Raffles Place"}]},
        "metadata": {
            "jobDetailsUrl": f"https://www.mycareersfuture.gov.sg/job/{uuid}",
            "newPostingDate": "2026-10-14",
            "expiryDate": "2026-11-13",
        },
    }
    job.update(overrides)
    return job


def test_mycareersfuture_normalization_maps_salary_skills_and_stated_seniority():
    job = _normalise(source="mycareersfuture", board="sg", fetched_at="2026-10-23T00:00:00Z",
                     raw=_mcf_job("abc"))
    assert job is not None
    assert job["dedup_key"] == "mycareersfuture:sg:abc"
    assert job["employer"] == "ABEAM CONSULTING (SINGAPORE) PTE. LTD."
    assert job["location"] == "Raffles Place, Singapore"
    assert job["description"] == "Responsibilities\n• Build dashboards\n• Write SQL"
    assert (job["salary_min"], job["salary_max"]) == (4000, 6000)
    assert (job["salary_currency"], job["salary_period"]) == ("SGD", "Monthly")
    assert job["posted_at"] == "2026-10-14T00:00:00Z"
    assert job["expires_at"] == "2026-11-13T00:00:00Z"
    assert job["skills"] == ["SQL", "Power BI"]
    assert job["stated_seniority"] == ["senior"]


def test_mycareersfuture_plain_executive_grade_is_left_to_the_title():
    job = _normalise(source="mycareersfuture", board="sg", fetched_at="2026-10-23T00:00:00Z",
                     raw=_mcf_job("abc", positionLevels=[{"position": "Executive"}], salary=None, address=None))
    assert job is not None
    assert job["stated_seniority"] is None
    assert job["salary_currency"] is None
    assert job["location"] == "Singapore"


def test_mycareersfuture_pages_by_keyword_and_dedupes_across_searches(monkeypatch):
    calls = []
    def fake_fetch(url, timeout, provider):
        calls.append(url)
        query = parse_qs(urlparse(url).query)
        page = int(query["page"][0])
        start = page * 2 if query["search"] == ["data analyst"] else 2   # second search overlaps the first
        return {"total": 4, "results": [_mcf_job(str(i)) for i in range(start, start + 2)]}
    monkeypatch.setattr(discovery, "_fetch_json", fake_fetch)
    monkeypatch.setattr(discovery.time, "sleep", lambda seconds: None)
    report = discover_report(DiscoveryConfig(
        mycareersfuture_searches=["data analyst", "data engineer"], page_size=2, max_pages_per_board=2,
        singapore_only=True,
    ))
    assert [j["external_id"] for j in report.jobs] == ["0", "1", "2", "3"]
    assert [parse_qs(urlparse(url).query)["page"][0] for url in calls[:2]] == ["0", "1"]
    assert all(url.startswith(discovery.MYCAREERSFUTURE_API) for url in calls)
    assert not report.truncated_boards and not report.failures


def test_mycareersfuture_caps_records_and_reports_truncation(monkeypatch):
    monkeypatch.setattr(discovery, "_fetch_json", lambda *a: {
        "total": 50, "results": [_mcf_job(str(i)) for i in range(3)],
    })
    monkeypatch.setattr(discovery.time, "sleep", lambda seconds: None)
    report = discover_report(DiscoveryConfig(
        mycareersfuture_searches=["analyst"], page_size=3, max_records_per_board=2,
    ))
    assert len(report.jobs) == 2
    assert report.truncated_boards == ["mycareersfuture:analyst"]


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
    {"mycareersfuture_delay_seconds": -1},
    {"mycareersfuture_delay_seconds": 11},
])
def test_config_rejects_unbounded_values(kwargs):
    with pytest.raises(ValueError):
        DiscoveryConfig(**kwargs)
