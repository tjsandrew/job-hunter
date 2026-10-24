"""Result checking, the S3 hand-off and the worker, without a database or a network."""
import io
import json

import pytest

from job_hunter import fit_transport, fit_worker
from job_hunter.llm import FakeLlm, LlmError
from job_hunter.preparation.fit import grounding
from job_hunter.preparation.fit.verify import verify_result

from test_fit_analysis import JOB, SNAPSHOT, respond

EVIDENCE = grounding.evidence_from_snapshot(SNAPSHOT)


class NoSuchKey(Exception):
    pass


class FakeS3:
    """Just enough of boto3's S3 client: put_object, get_object and the NoSuchKey exception."""
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.exceptions = type("Exceptions", (), {"NoSuchKey": NoSuchKey})

    def put_object(self, Bucket, Key, Body, **_):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise NoSuchKey(Key)
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


def worker_result():
    request = fit_transport.build_request("a1", JOB, EVIDENCE, None)
    return fit_transport.run_request(FakeLlm(respond), request)


def test_a_worker_result_passes_the_check_unchanged():
    raw = worker_result()
    checked = verify_result(raw, EVIDENCE)
    assert checked["coverage"] == raw["coverage"] and checked["verdicts"] == raw["verdicts"]
    assert checked["suggestions"] == raw["suggestions"]


def test_a_tampered_result_cannot_smuggle_in_evidence_numbers_or_a_percentage():
    raw = worker_result()
    raw["coverage"] = {"percent": 7}                               # ignored: recomputed from the verdicts
    raw["verdicts"][2] = {"verdict": "met", "evidence": ["b999", "skill:Python"], "note": "Used 99 tools."}
    raw["suggestions"].append({"kind": "emphasise", "requirement": 0, "bullet_id": "b1", "text": "Raised revenue by 700%."})
    checked = verify_result(raw, EVIDENCE)
    assert checked["verdicts"][2]["evidence"] == ["skill:Python"] and checked["verdicts"][2]["note"] == ""
    assert checked["coverage"]["percent"] == 100   # recomputed: two of the two judged must-haves now cite real evidence
    assert all("700" not in s["text"] for s in checked["suggestions"])


def test_an_unanswered_requirement_stays_unanswered_after_the_check():
    raw = worker_result()
    raw["verdicts"][1] = {"verdict": "needs_judgement", "evidence": [], "note": "", "answered": False}
    assert verify_result(raw, EVIDENCE)["verdicts"][1]["answered"] is False


@pytest.mark.parametrize("bad", [None, [], {}, {"requirements": [{"text": "Python experience"}], "verdicts": []}, {"error": "x"}])
def test_unusable_results_are_rejected(bad):
    with pytest.raises(ValueError):
        verify_result(bad, EVIDENCE)


def test_the_worker_writes_a_result_next_to_the_request():
    s3 = FakeS3()
    request = fit_transport.build_request("a1", JOB, EVIDENCE, None)
    fit_transport.put_request(s3, "bucket", request)
    assert fit_worker.process(s3, "bucket", fit_transport.request_key("a1"), client=FakeLlm(respond)) == "ok"
    assert fit_transport.get_result(s3, "bucket", "a1")["coverage"]["percent"] == 50
    assert fit_transport.get_result(s3, "bucket", "never") is None


def test_the_worker_reports_a_model_failure_instead_of_leaving_the_user_waiting():
    def down(system, user):
        raise LlmError("model unavailable")
    s3 = FakeS3()
    fit_transport.put_request(s3, "bucket", fit_transport.build_request("a2", JOB, EVIDENCE, None))
    assert fit_worker.process(s3, "bucket", fit_transport.request_key("a2"), client=FakeLlm(down)) == "MODEL_UNAVAILABLE"
    assert fit_transport.get_result(s3, "bucket", "a2") == {"error": "MODEL_UNAVAILABLE"}


def test_a_posting_without_requirements_is_reported_as_such():
    s3 = FakeS3()
    fit_transport.put_request(s3, "bucket", fit_transport.build_request("a4", JOB, EVIDENCE, None))
    empty = FakeLlm(lambda system, user: {"requirements": []})
    assert fit_worker.process(s3, "bucket", fit_transport.request_key("a4"), client=empty) == "NO_REQUIREMENTS"
    assert fit_transport.get_result(s3, "bucket", "a4") == {"error": "NO_REQUIREMENTS"}


def test_the_worker_ignores_a_request_whose_key_does_not_match_its_id():
    s3 = FakeS3()
    s3.objects[("bucket", "fit-requests/other.json")] = json.dumps(fit_transport.build_request("a3", JOB, EVIDENCE, None)).encode()
    assert fit_worker.process(s3, "bucket", "fit-requests/other.json", client=FakeLlm(respond)) == "BAD_REQUEST"
    assert ("bucket", fit_transport.result_key("a3")) not in s3.objects


def test_the_handler_only_reads_fit_requests_from_the_documents_bucket(monkeypatch):
    seen = []
    monkeypatch.setenv("DOCUMENT_BUCKET", "docs")
    monkeypatch.setattr(fit_worker, "process", lambda s3, bucket, key, client=None: seen.append((bucket, key)) or "ok")
    monkeypatch.setitem(__import__("sys").modules, "boto3", type("B", (), {"client": staticmethod(lambda *a, **k: object())}))
    event = {"Records": [{"s3": {"bucket": {"name": "docs"}, "object": {"key": "fit-requests/x.json"}}},
                         {"s3": {"bucket": {"name": "docs"}, "object": {"key": "uploads/x.pdf"}}},
                         {"s3": {"bucket": {"name": "elsewhere"}, "object": {"key": "fit-requests/y.json"}}}]}
    assert fit_worker.handler(event)["processed"] == 1 and seen == [("docs", "fit-requests/x.json")]
