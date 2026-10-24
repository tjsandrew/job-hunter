"""Judge each requirement against the profile's evidence, then suggest improvements."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from job_hunter.llm import LlmClient, LlmError, complete_validated
from job_hunter.preparation.fit import grounding, prompts

GROUP_SIZE = 5       # small groups keep a small model's JSON short and accurate
MAX_SUGGESTIONS = 5


def _rows(data: dict, key: str) -> list:
    rows = data[key]
    if not isinstance(rows, list):
        raise ValueError(f"{key} must be a list")
    return rows


def _answers(client: LlmClient, group: Sequence[Mapping[str, Any]], evidence: Mapping[str, str]) -> dict[int, dict]:
    """Rows keyed by position in ``group``. Small models restart ids, quote them, or skip rows, so be forgiving."""
    rows = complete_validated(client, prompts.JUDGE_SYSTEM, prompts.judge_user(group, evidence),
                              lambda data: _rows(data, "verdicts"), max_tokens=700)
    by_id: dict[int, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(group) and index not in by_id:
            by_id[index] = row
    if not by_id and len(rows) == len(group) and all(isinstance(row, dict) for row in rows):
        by_id = dict(enumerate(rows))     # no usable ids, but one answer per requirement: take them in order
    return by_id


def judge(client: LlmClient, requirements: Sequence[Mapping[str, Any]], evidence: Mapping[str, str]) -> list[dict[str, Any]]:
    verdicts: list[dict[str, Any]] = []
    for start in range(0, len(requirements), GROUP_SIZE):
        group = requirements[start:start + GROUP_SIZE]
        answers = _answers(client, group, evidence)
        missing = [i for i in range(len(group)) if i not in answers]
        if missing:                       # ask once more, only about the requirements that got no answer
            try:
                again = _answers(client, [group[i] for i in missing], evidence)
            except LlmError:
                again = {}
            for position, index in enumerate(missing):
                if position in again:
                    answers[index] = again[position]
        verdicts.extend(grounding.check_verdict(answers.get(i), requirement, evidence) for i, requirement in enumerate(group))
    return verdicts


def suggest(client: LlmClient, requirements: Sequence[Mapping[str, Any]], verdicts: Sequence[Mapping[str, Any]],
            evidence: Mapping[str, str]) -> list[dict[str, Any]]:
    """Suggestions are a bonus: if the model fails here the analysis is still returned without them."""
    if all(v["verdict"] == "met" for v in verdicts):
        return []
    try:
        rows = complete_validated(client, prompts.SUGGEST_SYSTEM, prompts.suggest_user(requirements, verdicts, evidence),
                                  lambda data: _rows(data, "suggestions"), max_tokens=700)
    except LlmError:
        return []
    texts = [r["text"] for r in requirements]
    checked = (grounding.check_suggestion(row, len(requirements), evidence, texts) for row in rows)
    return [s for s in checked if s][:MAX_SUGGESTIONS]
