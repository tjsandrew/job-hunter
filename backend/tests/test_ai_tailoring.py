import pytest

from job_hunter.config import settings
from job_hunter.preparation import ai_tailoring
from job_hunter.llm import OllamaClient
from job_hunter.preparation.ai_tailoring import AiUnavailable, FakeRewriter, build_model, rewrite_content
from job_hunter.preparation.tailor_llm import LlmRewriter

JOB = {"title": "Data Engineer", "skills": ["Python"], "description": "Build pipelines."}


class Stub:
    def __init__(self, result):
        self.result = result

    def rewrite(self, entries, job):
        return self.result


def content(*bullets):
    return {"sections": [{"id": "s", "title": "Experience", "entries": [{"id": "e", "bullets": list(bullets)}]}]}


def bullets_of(result):
    return result["sections"][0]["entries"][0]["bullets"]


def test_reworded_bullet_is_kept():
    result, changed = rewrite_content(content("Built APIs in Python for 3 teams"), JOB, Stub([["Delivered Python APIs for 3 teams"]]))
    assert bullets_of(result) == ["Delivered Python APIs for 3 teams"] and changed == 1


@pytest.mark.parametrize("invented", ["Built APIs in Python for 30 teams", "Built APIs in Python using Kubernetes"])
def test_bullet_with_new_number_or_name_is_dropped(invented):
    result, changed = rewrite_content(content("Built APIs in Python for 3 teams"), JOB, Stub([[invented]]))
    assert bullets_of(result) == ["Built APIs in Python for 3 teams"] and changed == 0


def test_wrong_shape_is_unavailable():
    with pytest.raises(AiUnavailable):
        rewrite_content(content("a"), JOB, Stub([]))


def test_wrong_bullet_count_keeps_that_entry():
    result, changed = rewrite_content(content("a", "b"), JOB, Stub([["only one"]]))
    assert bullets_of(result) == ["a", "b"] and changed == 0


def test_input_is_not_modified():
    source = content("Built things")
    rewrite_content(source, JOB, Stub([["Made things"]]))
    assert bullets_of(source) == ["Built things"]


def test_fake_backend_changes_nothing():
    result, changed = rewrite_content(content("a"), JOB, FakeRewriter())
    assert bullets_of(result) == ["a"] and changed == 0


@pytest.mark.parametrize("backend,expected", [("heuristic", type(None)), ("bedrock", type(None)), ("fake", FakeRewriter), ("ollama", LlmRewriter)])
def test_backend_follows_existing_model_setting(monkeypatch, backend, expected):
    monkeypatch.setattr(settings, "model_backend", backend)
    monkeypatch.setattr(settings, "llm_worker", "inline")
    assert isinstance(build_model(), expected)


def test_unreachable_ollama_is_unavailable():
    with pytest.raises(AiUnavailable):
        LlmRewriter(OllamaClient("http://127.0.0.1:1", "m", timeout=2)).rewrite([["a"]], JOB)


def test_limit_is_five():
    assert ai_tailoring.LIMIT == 5


def test_resume_without_bullets_never_calls_the_model():
    class Explode:
        def rewrite(self, entries, job):
            raise AssertionError("model was called")
    for empty in ({"sections": []}, content()):
        result, changed = rewrite_content(empty, JOB, Explode())
        assert result == empty and changed == 0
