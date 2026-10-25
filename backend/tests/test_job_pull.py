from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from job_hunter import discovery_worker, import_jobs, import_worker, job_pull
from job_hunter.ingestion.discovery import DiscoveryConfig, DiscoveryReport

from tests.test_import_jobs import FakeJob, MemoryRepository, record


class FakeS3:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body, **_):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


def jobs(count, source="greenhouse", board="b"):
    return [record(source=source, source_board=board, external_id=str(i), dedup_key=f"{source}:{board}:{i}",
                   source_url=f"https://example.test/{source}/{board}/{i}", title=f"Data Engineer {i}")
            for i in range(count)]


# --- shared rules -------------------------------------------------------------------------------------------

def test_clamp_max_new_falls_back_and_bounds():
    assert job_pull.clamp_max_new(None) == job_pull.DEFAULT_MAX_NEW
    assert job_pull.clamp_max_new("abc") == job_pull.DEFAULT_MAX_NEW
    assert job_pull.clamp_max_new("0") == 1
    assert job_pull.clamp_max_new(10_000) == job_pull.MAX_NEW_LIMIT
    assert job_pull.clamp_max_new("7") == 7


def test_import_key_only_accepts_a_uuid():
    assert job_pull.import_key("12345678-1234-5678-1234-567812345678") == "imports/12345678-1234-5678-1234-567812345678.json"
    with pytest.raises(ValueError):
        job_pull.import_key("../../uploads/x")


def test_interleave_mixes_boards_and_keeps_each_boards_order():
    mixed = job_pull.interleave(jobs(3, "greenhouse", "a") + jobs(2, "lever", "z"))
    assert [(item["source"], item["external_id"]) for item in mixed] == [
        ("greenhouse", "0"), ("lever", "0"), ("greenhouse", "1"), ("lever", "1"), ("greenhouse", "2")]


def test_interleave_rotates_between_keyword_searches_that_share_a_board():
    # All MyCareersFuture results have board "sg"; without discovered_by one search filled every batch.
    data = [{**job, "discovered_by": "mycareersfuture:data engineer"} for job in jobs(3, "mycareersfuture", "sg")]
    frontend = [{**job, "external_id": f"f{job['external_id']}", "discovered_by": "mycareersfuture:frontend developer"}
                for job in jobs(2, "mycareersfuture", "sg")]
    mixed = job_pull.interleave(data + frontend)
    assert [item["external_id"] for item in mixed] == ["0", "f0", "1", "f1", "2"]


def test_interleave_falls_back_to_board_for_older_snapshots():
    mixed = job_pull.interleave(jobs(2, "mycareersfuture", "sg") + jobs(1, "lever", "z"))
    assert [(item["source"], item["external_id"]) for item in mixed] == [
        ("mycareersfuture", "0"), ("lever", "0"), ("mycareersfuture", "1")]


# --- the cap on new jobs ---------------------------------------------------------------------------------------

def test_max_new_inserts_only_that_many_and_defers_the_rest():
    repo = MemoryRepository()
    stats = import_jobs.upsert_records(repo, jobs(5), job_model=FakeJob, max_new=2)
    assert (stats.new, stats.deferred, stats.errors) == (2, 3, 0)
    assert len(repo.added) == 2


def test_the_next_run_adds_the_next_batch_and_old_rows_do_not_count():
    repo = MemoryRepository()
    import_jobs.upsert_records(repo, jobs(5), job_model=FakeJob, max_new=2)
    stats = import_jobs.upsert_records(repo, jobs(5), job_model=FakeJob, max_new=2)
    assert (stats.new, stats.unchanged, stats.deferred) == (2, 2, 1)
    assert len(repo.added) == 4


def test_existing_rows_are_still_updated_when_the_cap_is_reached():
    repo = MemoryRepository()
    import_jobs.upsert_records(repo, jobs(1), job_model=FakeJob)
    changed = [record(source_board="b", external_id="0", dedup_key="greenhouse:b:0", description="Revised details",
                      source_url="https://example.test/greenhouse/b/0")]
    stats = import_jobs.upsert_records(repo, changed + jobs(3)[1:], job_model=FakeJob, max_new=1)
    assert (stats.updated, stats.new, stats.deferred) == (1, 1, 1)


def test_no_cap_keeps_the_command_line_behaviour():
    stats = import_jobs.upsert_records(MemoryRepository(), jobs(4), job_model=FakeJob)
    assert (stats.new, stats.deferred) == (4, 0)


def test_snapshot_payload_round_trips_without_a_file():
    report = DiscoveryReport(jobs=jobs(2), failures=[{"source": "lever"}], truncated_boards=["greenhouse:b"])
    back = import_jobs.report_from_payload(json.loads(json.dumps(import_jobs.snapshot_payload(report))))
    assert back.jobs == report.jobs and back.failures == report.failures and back.truncated_boards == ["greenhouse:b"]
    with pytest.raises(ValueError):
        import_jobs.report_from_payload({"snapshot_version": 2, "jobs": []})


# --- discovery worker (outside the VPC) -------------------------------------------------------------------------

class FakeLambda:
    def __init__(self, reply=None, error=None):
        self.calls = []
        self.reply, self.error = reply or {"new": 3}, error

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        body = json.dumps(self.reply).encode()
        result = {"Payload": io.BytesIO(body)}
        if self.error:
            result["FunctionError"] = "Unhandled"
        return result


def test_the_pull_stores_a_snapshot_and_invokes_the_import_step(monkeypatch):
    monkeypatch.setattr(discovery_worker, "discover_report", lambda config: DiscoveryReport(jobs=jobs(3)))
    s3, lam = FakeS3(), FakeLambda({"new": 3})
    result = discovery_worker.pull(s3, lam, bucket="docs", import_function="imp", max_new=10, config=DiscoveryConfig())
    ((bucket, key), body), = s3.objects.items()
    assert bucket == "docs" and key.startswith("imports/") and key.endswith(".json")
    assert len(json.loads(body)["jobs"]) == 3
    call, = lam.calls
    assert call["FunctionName"] == "imp" and call["InvocationType"] == "RequestResponse"
    assert json.loads(call["Payload"]) == {"bucket": "docs", "key": key, "max_new": 10}
    assert result["fetched"] == 3 and result["import"] == {"new": 3} and result["snapshot"] == key


def test_a_pull_that_finds_nothing_does_not_wake_the_database(monkeypatch):
    monkeypatch.setattr(discovery_worker, "discover_report",
                        lambda config: DiscoveryReport(failures=[{"source": "lever", "error": "timeout"}]))
    s3, lam = FakeS3(), FakeLambda()
    result = discovery_worker.pull(s3, lam, bucket="docs", import_function="imp", max_new=10, config=DiscoveryConfig())
    assert result["fetched"] == 0 and result["import"] is None and result["failures"]
    assert not s3.objects and not lam.calls


def test_a_failed_import_step_fails_the_pull(monkeypatch):
    monkeypatch.setattr(discovery_worker, "discover_report", lambda config: DiscoveryReport(jobs=jobs(1)))
    with pytest.raises(RuntimeError, match="import step failed"):
        discovery_worker.pull(FakeS3(), FakeLambda({"errorMessage": "boom"}, error=True), bucket="docs",
                              import_function="imp", max_new=10, config=DiscoveryConfig())


def test_the_config_reads_boards_and_searches_from_the_environment(monkeypatch):
    monkeypatch.setenv("GREENHOUSE_BOARDS", "stripe, cloudflare ,")
    monkeypatch.setenv("LEVER_BOARDS", "lalamove")
    monkeypatch.setenv("MYCAREERSFUTURE_SEARCHES", "data analyst,software engineer")
    monkeypatch.delenv("SMARTRECRUITERS_BOARDS", raising=False)
    config = discovery_worker.build_config()
    assert list(config.greenhouse_boards) == ["stripe", "cloudflare"]
    assert list(config.lever_boards) == ["lalamove"]
    assert list(config.mycareersfuture_searches) == ["data analyst", "software engineer"]
    assert config.singapore_only and not config.smartrecruiters_boards


def test_the_handler_takes_the_batch_size_from_the_event_or_the_environment(monkeypatch):
    seen = []
    monkeypatch.setenv("DOCUMENT_BUCKET", "docs")
    monkeypatch.setenv("IMPORT_FUNCTION", "imp")
    monkeypatch.setenv("DISCOVERY_MAX_NEW", "4")
    monkeypatch.setattr(discovery_worker, "pull", lambda s3, lam, **kw: seen.append(kw["max_new"]) or {"fetched": 0})
    monkeypatch.setitem(__import__("sys").modules, "boto3", SimpleNamespace(client=lambda *a, **k: object()))
    discovery_worker.handler({"max_new": 6})
    discovery_worker.handler({"version": "0", "source": "aws.events"})      # an EventBridge schedule event
    discovery_worker.handler({"max_new": "junk"})
    assert seen == [6, 4, 10]


# --- import worker (inside the VPC) -----------------------------------------------------------------------------

def put_snapshot(s3, items, key="imports/12345678-1234-5678-1234-567812345678.json", bucket="docs"):
    s3.put_object(bucket, key, json.dumps(import_jobs.snapshot_payload(DiscoveryReport(jobs=items))).encode())
    return bucket, key


def test_the_import_step_reads_only_snapshots_from_imports(monkeypatch):
    monkeypatch.setenv("DOCUMENT_BUCKET", "docs")
    s3 = FakeS3()
    bucket, key = put_snapshot(s3, jobs(2))
    assert len(import_worker.read_report(s3, bucket, key).jobs) == 2
    for bad_bucket, bad_key in [("other", key), ("docs", "uploads/x.json"), ("docs", "imports/x.pdf"),
                                ("docs", "imports/../uploads/x.json")]:
        with pytest.raises(ValueError):
            import_worker.read_report(s3, bad_bucket, bad_key)


def test_the_import_step_refuses_an_oversized_snapshot(monkeypatch):
    monkeypatch.setenv("DOCUMENT_BUCKET", "docs")
    monkeypatch.setattr(import_worker, "MAX_SNAPSHOT_BYTES", 10)
    s3 = FakeS3()
    bucket, key = put_snapshot(s3, jobs(2))
    with pytest.raises(ValueError, match="too large"):
        import_worker.read_report(s3, bucket, key)


def test_load_mixes_sources_and_respects_the_cap(monkeypatch):
    repo = MemoryRepository()
    monkeypatch.setattr(import_jobs, "SQLAlchemyJobRepository", lambda session: repo)
    monkeypatch.setattr(import_jobs, "_load_job_model", lambda: FakeJob)
    report = DiscoveryReport(jobs=jobs(5, "greenhouse", "a") + jobs(5, "lever", "z"))
    stats = import_worker.load(object(), report, 4)
    assert stats.new == 4 and stats.deferred == 6
    assert sorted(job.source for job in repo.added) == ["greenhouse", "greenhouse", "lever", "lever"]


class FakeSession:
    def __init__(self, engine):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def begin(self):
        return self


def test_the_flag_is_written_after_the_commit_and_only_when_jobs_were_added(monkeypatch):
    events = []

    class Session(FakeSession):
        def __exit__(self, *exc):
            events.append("closed")
            return False

        def begin(self):
            outer = self
            class Transaction:
                def __enter__(self_inner):
                    return outer
                def __exit__(self_inner, *exc):
                    events.append("commit")
                    return False
            return Transaction()

    monkeypatch.setenv("DOCUMENT_BUCKET", "docs")
    s3 = FakeS3()
    bucket, key = put_snapshot(s3, jobs(2))
    monkeypatch.setitem(__import__("sys").modules, "boto3", SimpleNamespace(client=lambda *a, **k: s3))
    monkeypatch.setattr(import_worker, "_engine", object())
    monkeypatch.setattr("sqlalchemy.orm.Session", Session)
    new = {"value": 2}
    monkeypatch.setattr(import_worker, "load", lambda session, report, max_new: SimpleNamespace(
        new=new["value"], updated=0, unchanged=0, deferred=0, linked=0, errors=0, record_errors=[]))
    from job_hunter.embedding import flag
    monkeypatch.setattr(flag, "write_flag", lambda: events.append("flag") or True)

    result = import_worker.handler({"bucket": bucket, "key": key, "max_new": 2})
    assert events == ["commit", "closed", "flag"] or events == ["commit", "flag", "closed"]
    assert events.index("commit") < events.index("flag")
    assert result["new"] == 2 and result["embed_flag_written"] is True and result["snapshot_records"] == 2

    events.clear()
    new["value"] = 0
    result = import_worker.handler({"bucket": bucket, "key": key})
    assert "flag" not in events and result["embed_flag_written"] is False


def test_the_import_step_needs_a_named_snapshot():
    with pytest.raises(ValueError):
        import_worker.handler({})
