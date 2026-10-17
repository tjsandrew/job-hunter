from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from job_hunter.import_jobs import (
    classify_title,
    import_report,
    load_snapshot,
    save_snapshot,
    upsert_records,
)
from job_hunter.ingestion.discovery import DiscoveryReport


FIELDS = (
    "source", "external_id", "dedup_key", "title", "company", "location", "work_mode",
    "description", "url", "status", "salary_min", "salary_max", "salary_currency",
    "salary_period", "posted_at", "expires_at", "source_board", "source_url", "fetched_at",
    "category", "category_source", "category_evidence", "updated_at",
)


class FakeJob:
    __mapper__ = SimpleNamespace(attrs={name: None for name in FIELDS})

    def __init__(self, **kwargs):
        for name in FIELDS:
            setattr(self, name, kwargs.get(name))
        self.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)


class MemoryRepository:
    def __init__(self):
        self.jobs = {}
        self.added = []

    def find(self, source, source_board, external_id):
        return self.jobs.get((source, source_board, external_id))

    def add(self, job):
        self.added.append(job)
        self.jobs[(job.source, job.source_board, job.external_id)] = job


def record(**overrides):
    result = {
        "source": "greenhouse",
        "source_board": "sample-board",
        "external_id": "100",
        "source_url": "https://example.test/jobs/100",
        "title": "Data Engineer",
        "employer": "Example Co",
        "location": "Singapore",
        "work_mode": None,
        "description": "Build data systems",
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "posted_at": "2026-09-10T00:00:00Z",
        "expires_at": None,
        "fetched_at": "2026-10-05T00:00:00Z",
        "dedup_key": "greenhouse:sample-board:100",
    }
    result.update(overrides)
    return result


def test_new_record_keeps_source_and_fetch_provenance_and_explicit_unknowns():
    repo = MemoryRepository()
    stats = upsert_records(repo, [record()], job_model=FakeJob)
    job = repo.jobs[("greenhouse", "sample-board", "100")]
    assert (stats.new, stats.updated, stats.unchanged, stats.errors) == (1, 0, 0, 0)
    assert job.company == "Example Co"
    assert job.location == "Singapore"
    assert job.work_mode is None
    assert job.description == "Build data systems"
    assert job.salary_min is None and job.salary_currency is None
    assert job.source_board == "sample-board"
    assert job.source_url == record()["source_url"]
    assert job.fetched_at == datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert job.posted_at == datetime(2026, 9, 10, tzinfo=timezone.utc)


def test_repeat_record_is_idempotent_but_refreshes_fetched_at():
    repo = MemoryRepository()
    first = record()
    upsert_records(repo, [first], job_model=FakeJob)
    existing = repo.jobs[("greenhouse", "sample-board", "100")]
    old_updated_at = existing.updated_at

    second = record(fetched_at="2026-10-06T00:00:00Z")
    stats = upsert_records(repo, [second], job_model=FakeJob)
    assert (stats.new, stats.updated, stats.unchanged) == (0, 0, 1)
    assert len(repo.added) == 1
    assert existing.fetched_at == datetime(2026, 10, 6, tzinfo=timezone.utc)
    assert existing.updated_at == old_updated_at


def test_changed_listing_updates_once_without_changing_identity():
    repo = MemoryRepository()
    upsert_records(repo, [record()], job_model=FakeJob)
    existing = repo.jobs[("greenhouse", "sample-board", "100")]
    stats = upsert_records(repo, [record(description="Revised details", salary_min=90000)], job_model=FakeJob)
    assert (stats.new, stats.updated, stats.unchanged) == (0, 1, 0)
    assert existing.description == "Revised details"
    assert existing.salary_min == 90000
    assert existing.dedup_key == "greenhouse:sample-board:100"


def test_source_board_scopes_same_external_id():
    repo = MemoryRepository()
    stats = upsert_records(repo, [
        record(),
        record(source_board="sample-board-2", dedup_key="greenhouse:sample-board-2:100"),
    ], job_model=FakeJob)
    assert stats.new == 2
    assert len(repo.jobs) == 2


def test_missing_location_and_work_mode_remain_null():
    repo = MemoryRepository()
    stats = upsert_records(repo, [record(location=None, work_mode=None)], job_model=FakeJob)
    job = repo.jobs[("greenhouse", "sample-board", "100")]
    assert stats.new == 1
    assert job.location is None
    assert job.work_mode is None


def test_missing_employer_and_description_remain_null():
    repo = MemoryRepository()
    upsert_records(repo, [record(employer=None, description=None)], job_model=FakeJob)
    job = repo.jobs[("greenhouse", "sample-board", "100")]
    assert job.company is None
    assert job.description is None


def test_invalid_record_is_counted_and_valid_record_keeps_progress():
    repo = MemoryRepository()
    stats = upsert_records(repo, [record(title=" "), record(external_id="101")], job_model=FakeJob)
    assert stats.errors == 1
    assert stats.new == 1
    assert stats.record_errors[0]["external_id"] == "100"


def test_location_filter_and_discovery_failures_are_reported():
    repo = MemoryRepository()
    report = DiscoveryReport(
        jobs=[record(), record(external_id="101", location="Remote")],
        failures=[{"source": "lever", "board": "bad", "kind": "rate_limited", "error": "429"}],
        truncated_boards=["greenhouse:sample-board"],
    )
    stats = import_report(repo, report, location="singapore", job_model=FakeJob)
    assert stats.new == 1
    assert stats.errors == 1
    assert stats.source_failures[0]["kind"] == "rate_limited"
    assert stats.truncated_boards == ["greenhouse:sample-board"]
    assert len(repo.jobs) == 1


def test_overlong_source_fields_are_rejected_without_truncation():
    repo = MemoryRepository()
    stats = upsert_records(repo, [record(title="X" * 241)], job_model=FakeJob)
    assert stats.errors == 1
    assert not repo.jobs


@pytest.mark.parametrize("title,expected,evidence", [
    ("Senior Data Engineer", "data", "data engineer"),
    ("Product Designer", "design", "designer"),
    ("Account Executive, APAC", "sales", "account executive"),
    ("Senior Software Engineer", "engineering", "engineer"),
    ("Graduate Programme", "other", None),
    # the occupation beats a domain word elsewhere in the title
    ("Technical Recruiter, Backend Engineering", "people", "recruiter"),
    ("Recruiter, Data Analytics", "people", "recruiter"),
    ("Internal Auditor - APAC Regulatory & Financial Operations", "finance", "auditor"),
])
def test_deterministic_title_category_is_labelled_and_has_evidence(title, expected, evidence):
    assert classify_title(title) == (expected, "role-family-v1", evidence)


def test_ingestion_category_and_the_recommenders_role_family_always_agree():
    from job_hunter.embedding.features import extract_job_features

    titles = ["Senior Data Engineer", "Product Designer", "Account Executive, Product - Local Payment Methods",
              "Technical Recruiter, Backend Engineering", "Recruiter, Data Analytics", "Fraud Strategist",
              "Database Administrator", "Customer Success Account Manager", "Product Counsel (APAC)", ""]
    for title in titles:
        category = classify_title(title)[0]
        family = extract_job_features(title).role_family
        assert family == (None if category == "other" else category), title


def test_imported_category_is_marked_as_inferred():
    repo = MemoryRepository()
    upsert_records(repo, [record(title="Senior Data Engineer")], job_model=FakeJob)
    job = repo.jobs[("greenhouse", "sample-board", "100")]
    assert job.category == "data"
    assert job.category_source == "role-family-v1"
    assert job.category_evidence == "data engineer"


def test_reimport_refreshes_a_category_written_by_the_old_classifier():
    repo = MemoryRepository()
    upsert_records(repo, [record(title="Recruiter, Data Analytics")], job_model=FakeJob)
    job = repo.jobs[("greenhouse", "sample-board", "100")]
    # a row ingested before the shared classifier: wrong family and the old source label
    job.category, job.category_source, job.category_evidence = "data", "title_keyword_v1", "analytics"
    stats = upsert_records(repo, [record(title="Recruiter, Data Analytics")], job_model=FakeJob)
    assert (stats.updated, stats.unchanged) == (1, 0)
    assert (job.category, job.category_source, job.category_evidence) == ("people", "role-family-v1", "recruiter")
    # and the next import has nothing left to change
    assert upsert_records(repo, [record(title="Recruiter, Data Analytics")], job_model=FakeJob).unchanged == 1


class BrokenModel(FakeJob):
    __mapper__ = SimpleNamespace(attrs={name: None for name in FIELDS if name != "fetched_at"})


def test_schema_missing_provenance_fails_clearly():
    repo = MemoryRepository()
    with pytest.raises(RuntimeError, match="fetched_at"):
        upsert_records(repo, [record()], job_model=BrokenModel)


def test_snapshot_round_trip_preserves_records_and_partial_state(tmp_path):
    original = DiscoveryReport(
        jobs=[record()],
        failures=[{"source": "lever", "board": "bad", "kind": "rate_limited", "error": "429"}],
        truncated_boards=["greenhouse:board"],
    )
    path = tmp_path / "cache" / "snapshot.json"
    save_snapshot(path, original)
    loaded = load_snapshot(path)
    assert loaded.jobs == original.jobs
    assert loaded.failures == original.failures
    assert loaded.truncated_boards == original.truncated_boards


def test_snapshot_rejects_unknown_format(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"snapshot_version": 2, "jobs": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        load_snapshot(path)
