"""Result checking, the S3 hand-off, the task registry and the LLM worker, without a database or a network."""
import io
import itertools
import json

import pytest

from job_hunter import llm_transport, llm_worker
from job_hunter.llm import FakeLlm, LlmError
from job_hunter.llm.tasks import TASKS, run_task
from job_hunter.preparation.fit import grounding
from job_hunter.preparation.fit.verify import verify_result

from test_fit_analysis import JOB, SNAPSHOT, respond

EVIDENCE = grounding.evidence_from_snapshot(SNAPSHOT)
TAILOR_INPUT = {"entries": [["Built APIs in Python for 3 teams"]], "job": {"title": "Data Engineer", "skills": ["Python"], "description": "Build pipelines."}}


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


class WorkingS3(FakeS3):
    """Like S3 with the worker attached: writing a request file runs the worker at once."""
    def __init__(self, client):
        super().__init__()
        self.client = client

    def put_object(self, Bucket, Key, Body, **kw):
        super().put_object(Bucket, Key, Body, **kw)
        if Key.startswith(llm_transport.REQUEST_PREFIX):
            llm_worker.process(self, Bucket, Key, client=self.client)


def fit_request(request_id):
    return llm_transport.build_request("fit", request_id, {"job": JOB, "evidence": EVIDENCE, "requirements": None})


def tailor_request(request_id):
    return llm_transport.build_request("tailor", request_id, TAILOR_INPUT)


def worker_result():
    body, outcome = run_task(FakeLlm(respond), fit_request("a1"))
    assert outcome == "ok"
    return body


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


def test_the_registry_has_the_fit_and_tailor_tasks():
    assert set(TASKS) == {"fit", "tailor"}


def test_an_unknown_task_is_refused_by_name():
    assert run_task(FakeLlm(respond), {"request_id": "x", "task": "translate", "input": {}}) == ({"error": "UNKNOWN_TASK"}, "UNKNOWN_TASK")
    assert run_task(FakeLlm(respond), {"request_id": "x", "input": {}})[1] == "UNKNOWN_TASK"


def test_a_task_that_crashes_reports_a_generic_failure():
    assert run_task(FakeLlm(respond), {"request_id": "x", "task": "fit"}) == ({"error": "ANALYSIS_FAILED"}, "ANALYSIS_FAILED")


class DeniedS3(FakeS3):
    """S3 as the API role sees it: it may read objects but not list the bucket, so a missing key is AccessDenied, not NoSuchKey."""
    def __init__(self, code="AccessDenied"):
        super().__init__()
        self.code = code

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            error = Exception("An error occurred (%s) when calling the GetObject operation" % self.code)
            error.response = {"Error": {"Code": self.code}}
            raise error
        return super().get_object(Bucket, Key)


def test_a_result_that_is_not_there_yet_is_not_an_error_even_when_s3_says_access_denied():
    s3 = DeniedS3()
    assert llm_transport.get_result(s3, "bucket", "early") is None                 # the first poll, before the worker has written
    s3.objects[("bucket", llm_transport.result_key("early"))] = b'{"error": "NO_REQUIREMENTS"}'
    assert llm_transport.get_result(s3, "bucket", "early") == {"error": "NO_REQUIREMENTS"}


@pytest.mark.parametrize("code", ["404", "NotFound", "403"])
def test_other_spellings_of_not_found_also_wait(code):
    assert llm_transport.get_result(DeniedS3(code), "bucket", "x") is None


def test_a_real_storage_failure_is_still_raised():
    with pytest.raises(Exception, match="InternalError"):
        llm_transport.get_result(DeniedS3("InternalError"), "bucket", "x")


def test_ask_waits_for_a_result_that_s3_reports_as_access_denied_until_it_exists():
    s3, clock, ticks = DeniedS3(), iter(range(100)), []

    def sleep(seconds):
        ticks.append(seconds)
        if len(ticks) == 3:                      # the worker finishes during the third wait
            s3.objects[("bucket", llm_transport.result_key(sent["id"]))] = b'{"entries": []}'

    sent = {}
    original = s3.put_object

    def put_object(Bucket, Key, Body, **kw):
        original(Bucket, Key, Body, **kw)
        sent["id"] = Key.removeprefix(llm_transport.REQUEST_PREFIX).removesuffix(".json")
    s3.put_object = put_object
    result = llm_transport.ask(s3, "bucket", "tailor", {"x": 1}, wait_seconds=20, sleep=sleep, clock=lambda: next(clock))
    assert result == {"entries": []} and len(ticks) == 3


def test_the_worker_writes_a_result_next_to_the_request():
    s3 = FakeS3()
    llm_transport.put_request(s3, "bucket", fit_request("a1"))
    assert llm_worker.process(s3, "bucket", llm_transport.request_key("a1"), client=FakeLlm(respond)) == "ok"
    assert llm_transport.get_result(s3, "bucket", "a1")["coverage"]["percent"] == 50
    assert llm_transport.get_result(s3, "bucket", "never") is None


def test_the_worker_reports_a_model_failure_instead_of_leaving_the_user_waiting():
    def down(system, user):
        raise LlmError("model unavailable")
    s3 = FakeS3()
    llm_transport.put_request(s3, "bucket", fit_request("a2"))
    assert llm_worker.process(s3, "bucket", llm_transport.request_key("a2"), client=FakeLlm(down)) == "MODEL_UNAVAILABLE"
    assert llm_transport.get_result(s3, "bucket", "a2") == {"error": "MODEL_UNAVAILABLE"}


def test_a_worker_without_a_model_key_reports_it_instead_of_crashing(monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    s3 = FakeS3()
    llm_transport.put_request(s3, "bucket", fit_request("a5"))
    assert llm_worker.process(s3, "bucket", llm_transport.request_key("a5")) == "MODEL_UNAVAILABLE"
    assert llm_transport.get_result(s3, "bucket", "a5") == {"error": "MODEL_UNAVAILABLE"}


def test_a_posting_without_requirements_is_reported_as_such():
    s3 = FakeS3()
    llm_transport.put_request(s3, "bucket", fit_request("a4"))
    empty = FakeLlm(lambda system, user: {"requirements": []})
    assert llm_worker.process(s3, "bucket", llm_transport.request_key("a4"), client=empty) == "NO_REQUIREMENTS"
    assert llm_transport.get_result(s3, "bucket", "a4") == {"error": "NO_REQUIREMENTS"}


def test_the_worker_ignores_a_request_whose_key_does_not_match_its_id():
    s3 = FakeS3()
    s3.objects[("bucket", "llm-requests/other.json")] = json.dumps(fit_request("a3")).encode()
    assert llm_worker.process(s3, "bucket", "llm-requests/other.json", client=FakeLlm(respond)) == "BAD_REQUEST"
    assert ("bucket", llm_transport.result_key("a3")) not in s3.objects


def test_the_handler_only_reads_llm_requests_from_the_documents_bucket(monkeypatch):
    seen = []
    monkeypatch.setenv("DOCUMENT_BUCKET", "docs")
    monkeypatch.setattr(llm_worker, "process", lambda s3, bucket, key, client=None: seen.append((bucket, key)) or "ok")
    monkeypatch.setitem(__import__("sys").modules, "boto3", type("B", (), {"client": staticmethod(lambda *a, **k: object())}))
    event = {"Records": [{"s3": {"bucket": {"name": "docs"}, "object": {"key": "llm-requests/x.json"}}},
                         {"s3": {"bucket": {"name": "docs"}, "object": {"key": "uploads/x.pdf"}}},
                         {"s3": {"bucket": {"name": "docs"}, "object": {"key": "llm-results/x.json"}}},
                         {"s3": {"bucket": {"name": "elsewhere"}, "object": {"key": "llm-requests/y.json"}}}]}
    assert llm_worker.handler(event)["processed"] == 1 and seen == [("docs", "llm-requests/x.json")]


def test_the_tailor_task_returns_the_models_rewrite():
    model = FakeLlm(lambda system, user: {"entries": [["Delivered Python APIs for 3 teams"]]})
    s3 = FakeS3()
    llm_transport.put_request(s3, "bucket", tailor_request("t1"))
    assert llm_worker.process(s3, "bucket", llm_transport.request_key("t1"), client=model) == "ok"
    assert llm_transport.get_result(s3, "bucket", "t1") == {"entries": [["Delivered Python APIs for 3 teams"]]}
    system, user = model.calls[0]
    assert "exactly the same number of bullet strings" in system and "Build pipelines." in user


def test_a_tailor_reply_without_entries_is_reported_not_crashed():
    s3 = FakeS3()
    llm_transport.put_request(s3, "bucket", tailor_request("t2"))
    outcome = llm_worker.process(s3, "bucket", llm_transport.request_key("t2"), client=FakeLlm(lambda system, user: {"rows": []}))
    assert outcome == "MODEL_UNAVAILABLE" and llm_transport.get_result(s3, "bucket", "t2") == {"error": "MODEL_UNAVAILABLE"}


def test_ask_returns_the_answer_of_a_worker_that_replies_at_once():
    model = FakeLlm(lambda system, user: {"entries": [["Reworded"]]})
    s3 = WorkingS3(model)
    answer = llm_transport.ask(s3, "bucket", "tailor", TAILOR_INPUT, wait_seconds=5, sleep=lambda _: None)
    assert answer == {"entries": [["Reworded"]]}
    assert [key for _, key in s3.objects if key.startswith("llm-requests/")]    # the request file was written


def test_ask_gives_up_when_the_worker_does_not_answer():
    ticks, pauses = itertools.count(), []
    s3 = FakeS3()
    answer = llm_transport.ask(s3, "bucket", "tailor", TAILOR_INPUT, wait_seconds=3, interval=1,
                               sleep=pauses.append, clock=lambda: next(ticks))
    assert answer is None and pauses == [1, 1, 1]


def test_ask_passes_on_a_worker_error():
    def down(system, user):
        raise LlmError("model unavailable")
    answer = llm_transport.ask(WorkingS3(FakeLlm(down)), "bucket", "tailor", TAILOR_INPUT, wait_seconds=5, sleep=lambda _: None)
    assert answer == {"error": "MODEL_UNAVAILABLE"}
