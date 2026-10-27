"""Routes for the job fit analysis (design brief 12).

The model is slow (30-40 s), so ``POST`` only records the request and starts the work; the web app polls ``GET``.
Where the work runs depends on ``LLM_WORKER`` (see ``job_hunter.llm_transport``): in this process after the response
(local), or in the LLM worker Lambda through S3 (AWS), as task ``fit``. Either way the stored result passes ``verify_result`` first.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from job_hunter import llm_transport
from job_hunter.adapters import storage
from job_hunter.config import settings
from job_hunter.domain.models import FitAnalysis, Job, JobRequirements, Profile, ProfileVersion, now_utc
from job_hunter.llm import build_client
from job_hunter.llm.tasks import run_task
from job_hunter.preparation import allowance
from job_hunter.preparation.fit import grounding, prompts
from job_hunter.preparation.fit.requirements import MIN_DESCRIPTION, input_hash, normalise
from job_hunter.preparation.fit.verify import verify_result

PENDING_TIMEOUT = timedelta(minutes=5)   # a request with no answer after this long is reported as failed
log = logging.getLogger(__name__)


def available() -> bool:
    """Whether fit analysis can run at all with the current settings."""
    if settings.llm_worker == "s3":
        return bool(settings.document_bucket)
    return build_client(settings) is not None


def _out(db: Session, item: FitAnalysis) -> dict:
    profile = db.get(Profile, item.user_id)
    return {"id": str(item.id), "job_id": str(item.job_id), "status": item.status, "error_code": item.error_code,
            "profile_revision": item.profile_revision, "result": item.result,
            "stale": bool(profile and profile.confirmed_revision and item.profile_revision
                          and profile.confirmed_revision > item.profile_revision),
            "created_at": item.created_at.isoformat(), "completed_at": item.completed_at.isoformat() if item.completed_at else None}


def _fail(item: FitAnalysis, code: str) -> None:
    item.status, item.error_code, item.result, item.completed_at = "failed", code, None, now_utc()


def _evidence(db: Session, user_id: UUID, revision: int) -> dict[str, str] | None:
    version = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == user_id, ProfileVersion.revision == revision))
    return grounding.evidence_from_snapshot(version.data) if version else None


def store_outcome(db: Session, item: FitAnalysis, raw: dict | None) -> None:
    """Check a model or worker answer and store it on the analysis; spends the month's slot only when it is usable."""
    if not isinstance(raw, dict) or raw.get("error"):
        return _fail(item, str(raw.get("error"))[:60] if isinstance(raw, dict) else "NO_RESULT")
    evidence = _evidence(db, item.user_id, item.profile_revision or 0)
    job = db.get(Job, item.job_id)
    if evidence is None or job is None:
        return _fail(item, "INPUT_GONE")
    try:
        result = verify_result(raw, evidence)
    except ValueError:
        log.warning("fit analysis %s returned an unusable result", item.id)
        return _fail(item, "INVALID_RESULT")
    item.status, item.error_code, item.result, item.completed_at = "ready", None, result, now_utc()
    cached = db.get(JobRequirements, job.id)
    fingerprint = input_hash({"title": job.title, "description": job.description})
    if cached is None:
        db.add(JobRequirements(job_id=job.id, input_hash=fingerprint, prompt_version=prompts.PROMPT_VERSION,
                               model=result["model"], requirements=result["requirements"]))
    elif cached.input_hash != fingerprint:
        cached.input_hash, cached.prompt_version, cached.model = fingerprint, prompts.PROMPT_VERSION, result["model"]
        cached.requirements, cached.created_at = result["requirements"], now_utc()
    allowance.spend(db, item.user_id, item.job_id)


def _cached_requirements(db: Session, job: Job) -> list | None:
    cached = db.get(JobRequirements, job.id)
    if cached is None or cached.input_hash != input_hash({"title": job.title, "description": job.description}):
        return None
    try:
        return normalise(cached.requirements)
    except ValueError:
        return None


def run_inline(analysis_id: UUID, user_id: UUID, request: dict, client=None) -> None:
    """Background task (local development): call the model, then store the checked answer under the user's own scope."""
    from job_hunter.adapters.database import SessionLocal
    raw, _ = run_task(client or build_client(settings), request)
    with SessionLocal() as db, db.begin():
        db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
        item = db.get(FitAnalysis, analysis_id)
        if item is not None and item.status == "pending":
            store_outcome(db, item, raw)


def build_router(db_dependency, current_user):
    router = APIRouter(prefix="/v1")

    def owned(db: Session, analysis_id: UUID) -> FitAnalysis:
        item = db.scalar(select(FitAnalysis).where(FitAnalysis.id == analysis_id, FitAnalysis.user_id == current_user(db).id))
        if item is None:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Resource not found"})
        return item

    def refresh(db: Session, item: FitAnalysis) -> None:
        """Pick up the worker's answer, or give up on a request that has had too long."""
        if item.status != "pending":
            return
        if settings.llm_worker == "s3":
            try:
                raw = llm_transport.get_result(storage.s3(), settings.document_bucket, item.id)
            except Exception:
                log.exception("fit result %s unreadable", item.id)
                raw = {"error": "INVALID_RESULT"}
            if raw is not None:
                return store_outcome(db, item, raw)
        if now_utc() - item.created_at > PENDING_TIMEOUT:
            _fail(item, "TIMEOUT")

    @router.post("/jobs/{job_id}/fit-analysis", status_code=202)
    def start(job_id: UUID, background: BackgroundTasks, db: Session = Depends(db_dependency, scope="function")):
        user = current_user(db)
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Resource not found"})
        if len((job.description or "").strip()) < MIN_DESCRIPTION:
            raise HTTPException(422, detail={"code": "JOB_TOO_SHORT", "message": "This listing has too little detail to find requirements in"})
        if not available():
            raise HTTPException(503, detail={"code": "AI_NOT_CONFIGURED", "message": "No AI model is configured"})
        profile = db.get(Profile, user.id)
        if profile is None or profile.confirmed_revision is None:
            raise HTTPException(409, detail={"code": "PROFILE_NOT_CONFIRMED", "message": "Confirm your profile before analysing a job"})
        evidence = _evidence(db, user.id, profile.confirmed_revision)
        if not evidence:
            raise HTTPException(409, detail={"code": "PROFILE_NOT_CONFIRMED", "message": "Confirm your profile before analysing a job"})
        item = db.scalar(select(FitAnalysis).where(FitAnalysis.user_id == user.id, FitAnalysis.job_id == job.id).with_for_update())
        if item is not None and item.status == "pending":
            refresh(db, item)
            if item.status == "pending":
                return _out(db, item)            # already running: do not start (or charge) it twice
        running = db.scalar(select(func.count()).select_from(FitAnalysis).where(
            FitAnalysis.user_id == user.id, FitAnalysis.status == "pending", FitAnalysis.job_id != job.id,
            FitAnalysis.created_at >= allowance.month_start())) or 0
        if not allowance.can_spend(db, user.id, job.id, user.plan, reserved=running):
            raise HTTPException(402, detail={"code": "AI_LIMIT_REACHED",
                                             "message": f"You have used all {allowance.limit_for(user.plan)} AI uses for this month"})
        if item is None:
            item = FitAnalysis(user_id=user.id, job_id=job.id)
            db.add(item)
        item.status, item.result, item.error_code = "pending", None, None
        item.profile_revision, item.created_at, item.completed_at = profile.confirmed_revision, now_utc(), None
        if item.id is None:
            item.id = uuid4()
        db.flush()
        request = llm_transport.build_request("fit", item.id, {"job": {"title": job.title, "description": job.description},
                                                               "evidence": evidence, "requirements": _cached_requirements(db, job)})
        if settings.llm_worker == "s3":
            try:
                llm_transport.put_request(storage.s3(), settings.document_bucket, request)
            except Exception:
                log.exception("fit request %s not written", item.id)
                raise HTTPException(503, detail={"code": "AI_UNAVAILABLE", "message": "The analysis could not be started"})
        else:
            background.add_task(run_inline, item.id, user.id, request)
        return _out(db, item)

    @router.get("/fit-analyses/{analysis_id}")
    def read(analysis_id: UUID, db: Session = Depends(db_dependency, scope="function")):
        item = owned(db, analysis_id)
        refresh(db, item)
        return _out(db, item)

    @router.get("/fit-analyses")
    def finished(db: Session = Depends(db_dependency, scope="function")):
        """One small row per job this user has a finished analysis for, so job lists can mark the jobs already checked.

        ``running`` lists the jobs whose analysis is still going. Each one is refreshed first, so the tracker can poll this
        list and see an answer arrive without opening every job."""
        user = current_user(db)
        profile = db.get(Profile, user.id)
        confirmed = profile.confirmed_revision if profile else None
        rows = db.scalars(select(FitAnalysis).where(FitAnalysis.user_id == user.id, FitAnalysis.status.in_(("ready", "pending")))
                          .order_by(FitAnalysis.completed_at.desc())).all()
        for row in rows:
            refresh(db, row)
        return {"items": [{"job_id": str(row.job_id),
                           "percent": ((row.result or {}).get("coverage") or {}).get("percent"),
                           "stale": bool(confirmed and row.profile_revision and confirmed > row.profile_revision)}
                          for row in rows if row.status == "ready"],
                "running": [str(row.job_id) for row in rows if row.status == "pending"]}

    @router.get("/jobs/{job_id}/fit-analysis")
    def latest(job_id: UUID, db: Session = Depends(db_dependency, scope="function")):
        item = db.scalar(select(FitAnalysis).where(FitAnalysis.user_id == current_user(db).id, FitAnalysis.job_id == job_id))
        if item is None:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Resource not found"})
        refresh(db, item)
        return _out(db, item)

    return router
