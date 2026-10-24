import logging
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from job_hunter import llm_transport
from job_hunter.adapters import storage
from job_hunter.config import settings
from job_hunter.llm import build_client
from job_hunter.preparation.allowance import LIMIT  # AI uses per user per month; fit analysis shares the same slots
from job_hunter.preparation.tailor_llm import AiUnavailable, LlmRewriter, job_payload

log = logging.getLogger(__name__)
WORKER_WAIT_SECONDS = 25   # the API Lambda stops at 29 s (API Gateway at 30 s), so the answer cannot be awaited longer


class Rewriter(Protocol):
    def rewrite(self, entries: list[list[str]], job: Mapping[str, Any]) -> list[list[str]]: ...


class FakeRewriter:
    def rewrite(self, entries, job):
        return [list(bullets) for bullets in entries]


@dataclass
class WorkerRewriter:
    """AWS: the API Lambda has no internet, so the LLM worker Lambda does the rewrite (task ``tailor``) through S3."""
    bucket: str
    wait_seconds: float = WORKER_WAIT_SECONDS

    def rewrite(self, entries, job):
        try:
            answer = llm_transport.ask(storage.s3(), self.bucket, "tailor", {"entries": entries, "job": job_payload(job)},
                                       wait_seconds=self.wait_seconds)
        except Exception as exc:
            log.exception("tailor request could not be sent or read")
            raise AiUnavailable("The AI model is not available") from exc
        if answer is None:
            raise AiUnavailable("The AI model took too long to answer")
        if not isinstance(answer, dict) or answer.get("error"):
            raise AiUnavailable("The AI model is not available")
        return answer.get("entries")


def build_model() -> Rewriter | None:
    """``fake`` for tests; the LLM worker in AWS; otherwise the configured model (hosted, or local Ollama), if any."""
    if settings.model_backend == "fake":
        return FakeRewriter()
    if settings.llm_worker == "s3":
        return WorkerRewriter(settings.document_bucket)
    client = build_client(settings)
    return LlmRewriter(client) if client is not None else None


def _facts(text: str, skip_first: bool = False) -> set[str]:
    tokens = text.split()[1 if skip_first else 0:]
    return {t.strip(".,;:()!?\"'").lower() for t in tokens if any(c.isdigit() for c in t) or t[:1].isupper()}


def _safe(original: str, rewritten: Any) -> str:
    if not isinstance(rewritten, str) or not rewritten.strip() or len(rewritten) > 4000:
        return original
    return rewritten if _facts(rewritten, True) <= _facts(original) else original


def rewrite_content(content: Mapping[str, Any], job: Mapping[str, Any], model: Rewriter) -> tuple[dict, int]:
    entries = [entry for section in content.get("sections", []) for entry in section.get("entries", [])]
    if not any(entry.get("bullets") for entry in entries):
        return dict(content), 0
    result = model.rewrite([list(entry.get("bullets", [])) for entry in entries], job)
    if not isinstance(result, list) or len(result) != len(entries):
        raise AiUnavailable("The AI model returned an unexpected result")
    changed = 0
    rewritten: dict[int, list[str]] = {}
    for index, entry in enumerate(entries):
        original = entry.get("bullets", [])
        new = result[index]
        if not isinstance(new, list) or len(new) != len(original):
            rewritten[index] = list(original)
            continue
        rewritten[index] = [_safe(old, text) for old, text in zip(original, new)]
        changed += sum(a != b for a, b in zip(original, rewritten[index]))
    position = iter(range(len(entries)))
    sections = [{**section, "entries": [{**entry, "bullets": rewritten[next(position)]} for entry in section.get("entries", [])]}
                for section in content.get("sections", [])]
    return {**content, "sections": sections}, changed
