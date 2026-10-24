"""The percentage shown to the user: how many of the posting's must-have requirements the profile evidences.

It is computed here from the model's verdicts, never asked of the model. It is not a hiring probability.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


MIN_JUDGED = 2         # with fewer judged requirements a percentage would mislead
MAX_UNANSWERED = 0.25  # if more than this share of must-haves got no answer from the model, show no percentage


def coverage(requirements: Sequence[Mapping[str, Any]], verdicts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pairs = list(zip(requirements, verdicts))
    musts = [(r, v) for r, v in pairs if r.get("importance") != "nice"]
    scored = [(r, v) for r, v in (musts or pairs) if v["verdict"] != "needs_judgement"]
    met = sum(v["verdict"] == "met" for _, v in scored)
    partly = sum(v["verdict"] == "partly" for _, v in scored)
    basis = musts or pairs
    unanswered_basis = sum(v.get("answered") is False for _, v in basis)
    trustworthy = len(scored) >= MIN_JUDGED and (not basis or unanswered_basis / len(basis) <= MAX_UNANSWERED)
    percent = round(100 * (met + 0.5 * partly) / len(scored)) if trustworthy else None
    return {"percent": percent, "met": met, "partly": partly, "considered": len(scored),
            "needs_judgement": sum(v["verdict"] == "needs_judgement" for _, v in (musts or pairs)),
            "unanswered": sum(v.get("answered") is False for _, v in pairs),
            "basis": "must-have requirements" if musts else "all requirements"}
