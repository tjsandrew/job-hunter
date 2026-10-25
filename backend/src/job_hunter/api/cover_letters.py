"""Routes that create cover letters (design brief 14).

A cover letter is a ``Document`` of kind ``cover_letter``: it is edited, reviewed, exported and attached to an application with the
same endpoints as a resume. This module only does what is different: creating one, either blank, written by the model from the
confirmed profile and the job description, or improved from a letter the person already has.

The model call is a single short task, so it is waited for inside the request, the way the AI resume rewrite is (25 s: the API
Lambda stops at 29 s). Where it runs depends on ``LLM_WORKER``: the LLM worker Lambda through S3 (AWS) or this process (local).
An answer that is slow, broken or empty creates nothing and costs nothing. A slot is spent only for a usable AI letter, and it is
the same slot per job and month that fit analysis and AI tailoring share.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_hunter import llm_transport
from job_hunter.adapters import storage
from job_hunter.api import fit_analysis
from job_hunter.config import settings
from job_hunter.domain.models import Document, Job, now_utc
from job_hunter.llm import build_client
from job_hunter.llm.tasks import run_task
from job_hunter.preparation import allowance, cover_letter
from job_hunter.preparation.fit import grounding
from job_hunter.profile_bank import services as bank_services

log = logging.getLogger(__name__)
WORKER_WAIT_SECONDS = 25
MIN_DESCRIPTION = 40
MIN_SOURCE_LETTER = 40
MAX_SOURCE_LETTER = 8000
DEFAULT_LAYOUT = {"font_size": 11, "margin": 22, "font_family": "auto", "line_spacing": 1.3, "page_size": "A4"}


class AiLetterFailed(Exception):
    """The model could not give a usable letter. Nothing is created or charged."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class LetterWrite(BaseModel):
    mode: Literal["blank", "write", "improve"] = "write"
    tone: Literal["formal", "friendly", "concise"] = "formal"
    points: str | None = Field(default=None, max_length=600)
    source_document_id: UUID | None = None
    source_text: str | None = Field(default=None, max_length=MAX_SOURCE_LETTER)
    title: str | None = Field(default=None, max_length=240)


def available() -> bool:
    """Whether a letter can be written by AI with the current settings (a blank letter never needs the model)."""
    return settings.model_backend == "fake" or fit_analysis.available()


def fake_answer(payload: dict[str, Any]) -> dict[str, Any]:
    """``MODEL_BACKEND=fake``: a plain letter built from the evidence, for trying the screens without a model."""
    job = payload.get("job") or {}
    evidence = payload.get("evidence") or {}
    keys = [key for key in evidence if ":" not in key][:2]    # the summary and profile bullets, not skills, roles or projects
    middle = " ".join(evidence[key] for key in keys) or (payload.get("letter") or "My background fits this role.")
    return {"paragraphs": [f"I am writing to apply for the {job.get('title') or 'open'} role at {job.get('company') or 'your company'}.",
                           middle, "I would welcome the chance to discuss how I can contribute. Thank you for your time."],
            "claims": [{"text": evidence[key][:80], "evidence": [key]} for key in keys]}


def ask_model(payload: dict[str, Any]) -> dict[str, Any]:
    """The model's raw answer for a ``cover_letter`` task, or ``AiLetterFailed``."""
    if settings.model_backend == "fake":
        return fake_answer(payload)
    if settings.llm_worker == "s3":
        try:
            answer = llm_transport.ask(storage.s3(), settings.document_bucket, "cover_letter", payload, wait_seconds=WORKER_WAIT_SECONDS)
        except Exception:
            log.exception("cover letter request could not be sent or read")
            raise AiLetterFailed("AI_UNAVAILABLE")
        if answer is None:
            raise AiLetterFailed("AI_TIMEOUT")
    else:
        client = build_client(settings)
        if client is None:
            raise AiLetterFailed("AI_NOT_CONFIGURED")
        answer, _ = run_task(client, llm_transport.build_request("cover_letter", uuid4(), payload))
    if not isinstance(answer, dict) or answer.get("error"):
        raise AiLetterFailed("AI_UNAVAILABLE")
    return answer


def today_text(now: datetime | None = None) -> str:
    local = (now or now_utc()).astimezone(allowance.SINGAPORE)
    return f"{local.day} {local:%B %Y}"


def letter_content(basics: dict[str, Any], job: Job, paragraphs: list[str]) -> dict[str, Any]:
    name = str(basics.get("name") or "").strip()
    company = (job.company or "").strip()
    return {"name": name, "email": str(basics.get("email") or ""), "phone": str(basics.get("phone") or ""),
            "location": str(basics.get("location") or ""), "date": today_text(),
            "recipient": f"Hiring Team\n{company}" if company else "Hiring Team", "greeting": "Dear Hiring Team,",
            "paragraphs": paragraphs, "closing": "Yours sincerely,", "signature": name}


def build_router(db_dependency, current_user, doc_out):
    router = APIRouter(prefix="/v1")

    @router.post("/jobs/{job_id}/cover-letter", status_code=201)
    def create(job_id: UUID, body: LetterWrite, db: Session = Depends(db_dependency, scope="function")):
        user = current_user(db)
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Resource not found"})
        basics = bank_services.read_basics(db)["draft"]
        title = (body.title or f"Cover letter — {job.title}")[:240]
        notes: list[dict[str, str]] = []
        ai = {"status": "off", "reason": None}
        paragraphs = [""]
        own: dict[str, Any] = {}
        if body.mode != "blank":
            paragraphs, notes = _write_with_ai(db, user, job, body, basics)
            ai = {"status": "applied", "reason": None}
        elif (body.source_text or "").strip():
            own = cover_letter.parse_own_letter(body.source_text)      # a letter the person already has, put in the editor as it is
            paragraphs = own.pop("paragraphs")
        content = {**letter_content(basics, job, paragraphs), **own}
        item = Document(user_id=user.id, title=title, kind="cover_letter", template="classic",
                        content=content, layout=dict(DEFAULT_LAYOUT), revision=1, job_id=job.id)
        db.add(item)
        db.flush()
        if body.mode != "blank":
            allowance.spend(db, user.id, job.id)
        return {"document": doc_out(item), "notes": notes, "ai": ai}

    def _write_with_ai(db: Session, user, job: Job, body: LetterWrite, basics: dict[str, Any]):
        if not available():
            raise HTTPException(503, detail={"code": "AI_NOT_CONFIGURED", "message": "No AI model is configured"})
        letter_text = ""
        if body.mode == "improve":
            if body.source_document_id is not None:
                source = db.scalar(select(Document).where(Document.id == body.source_document_id, Document.user_id == user.id,
                                                          Document.kind == "cover_letter"))
                if source is None:
                    raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Resource not found"})
                letter_text = "\n\n".join(source.content.get("paragraphs") or [])
            else:
                letter_text = (body.source_text or "").strip()
            if len(letter_text.strip()) < MIN_SOURCE_LETTER:
                raise HTTPException(422, detail={"code": "LETTER_TOO_SHORT", "message": "Pick or paste a letter with at least a few sentences"})
        elif len((job.description or "").strip()) < MIN_DESCRIPTION:
            raise HTTPException(422, detail={"code": "JOB_TOO_SHORT", "message": "This listing has too little detail to write a letter from"})
        snapshot = bank_services.get_confirmed_snapshot(db)
        evidence = grounding.evidence_from_snapshot(snapshot[2]) if snapshot else {}
        if body.mode == "write" and not evidence:
            raise HTTPException(409, detail={"code": "PROFILE_NOT_CONFIRMED", "message": "Confirm your profile before writing a letter from it"})
        if not allowance.can_spend(db, user.id, job.id, user.plan):
            raise HTTPException(402, detail={"code": "AI_LIMIT_REACHED",
                                             "message": f"You have used all {allowance.limit_for(user.plan)} AI uses for this month"})
        payload = {"mode": body.mode, "tone": body.tone, "points": body.points,
                   "job": {"title": job.title, "company": job.company, "description": job.description},
                   "evidence": evidence, "letter": letter_text}
        try:
            answer = ask_model(payload)
            known = " ".join([*evidence.values(), job.title or "", job.company or "", job.description or "", body.points or "",
                              letter_text, str(basics.get("name") or "")])
            return cover_letter.check_letter(answer, evidence=evidence, known_text=known)
        except (AiLetterFailed, cover_letter.LetterUnusable) as exc:
            code = exc.code if isinstance(exc, AiLetterFailed) else "AI_UNAVAILABLE"
            raise HTTPException(503, detail={"code": code, "message": "The AI could not write the letter. Nothing was used; you can write it yourself."})

    return router
