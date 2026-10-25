"""The AI resume rewrite on the shared LLM client and on the LLM worker, without a network."""
import pytest

from job_hunter.config import settings
from job_hunter.llm import FakeLlm, LlmError
from job_hunter.preparation import ai_tailoring
from job_hunter.preparation.ai_tailoring import AiUnavailable, WorkerRewriter, rewrite_content
from job_hunter.preparation.tailor_llm import SYSTEM, LlmRewriter, job_payload

JOB = {"title": "Data Engineer", "skills": ["Python"], "description": "Build pipelines. " * 400, "company": "Acme", "id": "x"}
CONTENT = {"sections": [{"id": "s", "title": "Experience", "entries": [{"id": "e", "bullets": ["Built APIs in Python for 3 teams"]}]}]}


def test_the_prompt_sends_only_what_the_rewrite_needs():
    sent = job_payload(JOB)
    assert set(sent) == {"title", "skills", "description"} and len(sent["description"]) == 4000


def test_the_model_is_asked_with_her_prompt_plus_the_shape_rules():
    model = FakeLlm(lambda system, user: {"entries": [["Delivered Python APIs for 3 teams"]]})
    assert LlmRewriter(model).rewrite([["Built APIs in Python for 3 teams"]], JOB) == [["Delivered Python APIs for 3 teams"]]
    system, _ = model.calls[0]
    assert system.startswith(SYSTEM) and "same number of bullet strings" in system


def test_a_reply_without_entries_is_unavailable():
    with pytest.raises(AiUnavailable):
        LlmRewriter(FakeLlm(lambda system, user: {"rows": []})).rewrite([["a"]], JOB)


def test_a_reply_with_the_wrong_kind_of_entries_is_refused_by_the_fact_check():
    model = FakeLlm(lambda system, user: {"entries": 5})
    with pytest.raises(AiUnavailable):
        rewrite_content(CONTENT, JOB, LlmRewriter(model))


def test_a_model_error_is_unavailable():
    def down(system, user):
        raise LlmError("down")
    with pytest.raises(AiUnavailable):
        LlmRewriter(FakeLlm(down)).rewrite([["a"]], JOB)


def test_the_whole_rewrite_keeps_only_reworded_bullets_that_add_no_new_facts():
    model = FakeLlm(lambda system, user: {"entries": [["Built APIs in Python using Kubernetes"]]})
    result, changed = rewrite_content(CONTENT, JOB, LlmRewriter(model))
    assert changed == 0 and result["sections"][0]["entries"][0]["bullets"] == ["Built APIs in Python for 3 teams"]



def test_entries_without_bullets_are_not_sent_and_come_back_empty_in_place():
    model = FakeLlm(lambda system, user: {"entries": [["A1 reworded", "A2 reworded"], ["C1 reworded"]]})
    result = LlmRewriter(model).rewrite([["A1", "A2"], [], ["C1"]], JOB)
    assert result == [["A1 reworded", "A2 reworded"], [], ["C1 reworded"]]
    assert '"entries": [["A1", "A2"], ["C1"]]' in model.calls[0][1]


@pytest.mark.parametrize("wrong", [
    [["A1 reworded", "A2 reworded"]],                                   # an entry dropped (B2: 6 sent, 5 back)
    [["A1 reworded"], ["A2 reworded"], ["C1 reworded"]],                # an entry added / bullets split
    [["A1 reworded", "A2 reworded", "C1 reworded"], []],                # bullets merged
])
def test_a_reply_of_the_wrong_shape_is_asked_for_again_with_the_reason(wrong):
    model = FakeLlm([{"entries": wrong}, {"entries": [["A1 reworded", "A2 reworded"], ["C1 reworded"]]}])
    assert LlmRewriter(model).rewrite([["A1", "A2"], ["C1"]], JOB) == [["A1 reworded", "A2 reworded"], ["C1 reworded"]]
    assert len(model.calls) == 2 and "previous reply was rejected" in model.calls[1][1]


def test_a_wrong_shape_twice_is_unavailable():
    model = FakeLlm([{"entries": [["only one"]]}])
    with pytest.raises(AiUnavailable):
        LlmRewriter(model).rewrite([["A1"], ["B1"]], JOB)
    assert len(model.calls) == 2


def test_nothing_to_reword_does_not_call_the_model():
    model = FakeLlm([{"entries": []}])
    assert LlmRewriter(model).rewrite([[], []], JOB) == [[], []] and model.calls == []

class StubS3:
    pass


@pytest.fixture
def worker_answer(monkeypatch):
    """Replace the S3 round trip: ``ask`` returns what the test sets."""
    seen = {}

    def ask(s3, bucket, task, payload, *, wait_seconds):
        seen.update(bucket=bucket, task=task, payload=payload, wait=wait_seconds)
        if isinstance(seen.get("answer"), Exception):
            raise seen["answer"]
        return seen.get("answer")

    monkeypatch.setattr(ai_tailoring.llm_transport, "ask", ask)
    monkeypatch.setattr(ai_tailoring.storage, "s3", lambda: StubS3())
    return seen


def test_the_worker_rewriter_sends_a_tailor_request_and_returns_the_entries(worker_answer):
    worker_answer["answer"] = {"entries": [["Delivered Python APIs for 3 teams"]]}
    assert WorkerRewriter("docs").rewrite([["Built APIs in Python for 3 teams"]], JOB) == [["Delivered Python APIs for 3 teams"]]
    assert worker_answer["task"] == "tailor" and worker_answer["bucket"] == "docs"
    assert set(worker_answer["payload"]["job"]) == {"title", "skills", "description"}
    assert worker_answer["wait"] == ai_tailoring.WORKER_WAIT_SECONDS == 25


@pytest.mark.parametrize("answer", [None, {"error": "MODEL_UNAVAILABLE"}, ["not", "a", "dict"], RuntimeError("s3 down")])
def test_the_worker_rewriter_falls_back_when_the_worker_is_slow_or_failing(worker_answer, answer):
    worker_answer["answer"] = answer
    with pytest.raises(AiUnavailable):
        WorkerRewriter("docs").rewrite([["a"]], JOB)


def test_the_worker_route_is_used_in_aws_and_the_model_route_locally(monkeypatch):
    monkeypatch.setattr(settings, "document_bucket", "docs")
    monkeypatch.setattr(settings, "model_backend", "heuristic")
    monkeypatch.setattr(settings, "llm_worker", "s3")
    assert isinstance(ai_tailoring.build_model(), WorkerRewriter)
    monkeypatch.setattr(settings, "llm_worker", "inline")
    assert ai_tailoring.build_model() is None
    monkeypatch.setattr(settings, "model_backend", "hosted")
    monkeypatch.setattr(settings, "llm_base_url", "https://gateway.test/v1")
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_model", "m")
    assert isinstance(ai_tailoring.build_model(), LlmRewriter)
