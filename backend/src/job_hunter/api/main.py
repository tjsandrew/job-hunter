from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_hunter.config import settings
from job_hunter.recommendations import rank_jobs, RANKING_VERSION
from job_hunter.embedding import for_you as semantic, profile_sync, settings as embedding_settings
from job_hunter.embedding.retrieval import FUSION_VERSION
from job_hunter.adapters.database import get_db
from job_hunter.domain.identity import DEV_USERS
from job_hunter.domain.models import (User, Profile, Preference, Job, JobReview, Application,
                                      ProfileVersion, Document, DocumentExport, Upload, AiTailorUse, now_utc)
from job_hunter.domain.models import Base, listed_jobs
from job_hunter.adapters.database import engine
from job_hunter.preparation.rendering import pdf_bytes
from job_hunter.preparation import ai_tailoring, allowance
from job_hunter.preparation.tailoring import tailor
from job_hunter.profile_bank import services as bank_services
from job_hunter.profile_bank.services import BankError
from job_hunter.api.profile_bank import build_router
from job_hunter.api.document_checks import check_bank_fields
from job_hunter.api.resume_build import build_router as build_resume_router
from job_hunter.api import cover_letters, fit_analysis
from job_hunter.preparation.cover_letter import plain_text as letter_plain_text
from job_hunter.profile_bank.build import blank_document_parts
from job_hunter.profile_bank.importing import ImportFailure
from job_hunter.profile_bank.importing.docx import CONTENT_TYPES, declared_file_problem, detect_resume_file, extract_docx
from job_hunter.seniority import SENIORITY_LADDER, SENIORITY_OPTIONS, normalise_levels
from job_hunter.adapters import storage
from job_hunter.adapters.auth import CloudIdentity, cloud_identity

app = FastAPI(title="Job Hunter API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",")],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "REQUEST_FAILED", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": {
        "code": detail.get("code", "REQUEST_FAILED"), "message": detail.get("message", "Request failed"),
        "request_id": request.headers.get("x-request-id", str(uuid4())),
        "details": {k: v for k, v in detail.items() if k not in {"code", "message"}},
    }})

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": {"code": "INVALID_REQUEST",
        "message": "Request validation failed", "request_id": request.headers.get("x-request-id", str(uuid4())),
        "details": {"errors": exc.errors()}}})

@app.on_event("startup")
def optional_schema_init():
    if settings.auto_create_schema:
        Base.metadata.create_all(engine)

def identity(request: Request, x_dev_user: str | None = Header(default=None)) -> str | CloudIdentity:
    if settings.auth_mode == "cognito":
        return cloud_identity(request)
    if settings.auth_mode != "local" or settings.app_env not in {"local", "test"}:
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Identity provider is not configured"})
    chosen = x_dev_user or settings.dev_default_user
    if chosen not in DEV_USERS:
        raise HTTPException(401, detail={"code": "INVALID_DEV_IDENTITY", "message": "Use alice or casey in local mode"})
    return chosen

def db_for(user_key = Depends(identity)):
    try:
        yield from get_db(user_key)
    except ValueError as exc:
        raise HTTPException(503, detail={"code": "IDENTITY_NOT_SEEDED", "message": str(exc)}) from exc

def current_user(db: Session) -> User:
    return db.info["current_user"]

def not_found():
    raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Resource not found"})

def doc_out(doc: Document) -> dict:
    return {"id": str(doc.id), "title": doc.title, "kind": doc.kind, "revision": doc.revision,
            "template": doc.template, "content": doc.content, "layout": doc.layout,
            "reviewed_revision": doc.reviewed_revision,
            "job_id": str(doc.job_id) if doc.job_id else None,
            "updated_at": (doc.updated_at or now_utc()).isoformat()}

class ProfileWrite(BaseModel):
    draft: dict[str, Any]
    expected_revision: int

class ConfirmWrite(BaseModel):
    expected_bank_revision: int = Field(ge=0)

class PreferencesFilter(BaseModel):
    """Job preferences as a filter: saved as the profile default, or sent with one Discover request."""
    roles: list[str] = Field(default=[], max_length=20)
    locations: list[str] = Field(default=[], max_length=20)
    work_modes: list[str] = Field(default=[], max_length=3)
    seniority: str | None = None
    salary_min: float | None = Field(default=None, ge=0)
    salary_currency: str | None = "SGD"
    salary_period: str | None = "year"

    @field_validator("roles", "locations", "work_modes")
    @classmethod
    def tidy_labels(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value and value.strip()]
        if any(len(value) > 100 for value in cleaned):
            raise ValueError("each value must be at most 100 characters")
        return cleaned

    @field_validator("seniority")
    @classmethod
    def validate_seniority(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = normalise_levels(value)
        if len(normalized) == 1 and (value.strip().casefold() in SENIORITY_LADDER or
                                     value.strip().casefold() in {"entry", "mid-level"}):
            return normalized[0]
        raise ValueError("seniority must be one of the supported levels")

class PreferencesWrite(PreferencesFilter):
    expected_revision: int

def discover_filters(filters: Literal["saved", "none", "custom"] = Query("saved"),
                     role: list[str] = Query([]), location: list[str] = Query([]),
                     work_mode: list[str] = Query([]), seniority: str | None = Query(None, max_length=40),
                     salary_min: float | None = Query(None, ge=0),
                     salary_currency: str | None = Query(None, max_length=8),
                     salary_period: str | None = Query(None, max_length=10)) -> dict | None:
    """Which preferences a Discover request ranks with. None means the user's saved preferences.

    ``custom`` filters apply to this one request and are never saved; ``none`` ranks with no preferences at all."""
    if filters == "saved":
        return None
    if filters == "none":
        return {}
    try:
        return PreferencesFilter(roles=role, locations=location, work_modes=work_mode, seniority=seniority,
                                 salary_min=salary_min, salary_currency=salary_currency or "SGD",
                                 salary_period=salary_period or "year").model_dump()
    except ValidationError as exc:
        raise HTTPException(422, detail={"code": "INVALID_FILTERS", "message": "These filters are not valid",
                                         "errors": [error["msg"] for error in exc.errors()]}) from exc

POSTED_WITHIN_DAYS = (3, 7, 14, 30, 365)   # Discover's "Posted" choices; a year is the widest ("Past year")

def posted_after(posted_within: int = Query(365, description="Only jobs posted in the last N days: 3, 7, 14, 30 or 365")) -> datetime:
    """Discover's "Posted" filter, for this request only. Without it a list covers the past year."""
    if posted_within not in POSTED_WITHIN_DAYS:
        raise HTTPException(422, detail={"code": "INVALID_FILTERS", "message": "These filters are not valid",
                                         "errors": [f"posted_within must be one of {', '.join(map(str, POSTED_WITHIN_DAYS))}"]})
    return now_utc() - timedelta(days=posted_within)

def effective_preferences(db: Session, chosen: dict | None) -> dict:
    if chosen is not None:
        return chosen
    saved = db.get(Preference, current_user(db).id)
    return saved.data if saved else {}

class ReviewWrite(BaseModel):
    decision: str

class ApplicationWrite(BaseModel):
    status: str | None = None
    notes: str | None = None
    applied_at: datetime | None = None
    expected_revision: int | None = None
    resume_document_id: UUID | None = None
    expected_resume_revision: int | None = Field(default=None, ge=1)
    resume_export_id: UUID | None = None
    cover_letter_text: str | None = Field(default=None, max_length=20000)
    cover_letter_document_id: UUID | None = None
    expected_cover_letter_revision: int | None = Field(default=None, ge=1)

class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    template: str = "classic"
    job_id: UUID | None = None
    content: dict[str, Any]
    layout: dict[str, Any] = Field(default_factory=lambda: {"font_size": 11, "margin": 18})

class DocumentPatch(BaseModel):
    title: str | None = None
    template: str | None = None
    content: dict[str, Any] | None = None
    layout: dict[str, Any] | None = None
    expected_revision: int

class DocumentReview(BaseModel):
    expected_revision: int

class DuplicateWrite(BaseModel):
    title: str | None = None
    job_id: UUID | None = None

class TailorWrite(BaseModel):
    job_id: UUID
    title: str | None = None
    mode: Literal["rules", "ai"] = "rules"

class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)

WRITTEN_KINDS = ("resume", "cover_letter")          # documents the user edits, reviews, exports and attaches
ARCHIVED_AS = {"resume": "archived", "cover_letter": "archived_letter"}
RESTORED_AS = {archived: kind for kind, archived in ARCHIVED_AS.items()}

LETTER_TEXT_FIELDS = {"name": 5000, "email": 5000, "phone": 5000, "location": 5000, "date": 200, "recipient": 1000,
                      "greeting": 300, "closing": 300, "signature": 300}

def validate_letter_content(content: dict) -> None:
    """A cover letter's own fields: contact, date, recipient, greeting, paragraphs, closing and signature."""
    for field, limit in LETTER_TEXT_FIELDS.items():
        value = content.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": f"{field} must be text up to {limit} characters"})
    paragraphs = content.get("paragraphs", [])
    if not isinstance(paragraphs, list) or len(paragraphs) > 12:
        raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": "A letter has up to 12 paragraphs"})
    if any(not isinstance(item, str) or len(item) > 4000 for item in paragraphs):
        raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": "Paragraphs must be text up to 4000 characters"})

def validate_document(template: str, content: dict, layout: dict, db: Session | None = None,
                      existing_content: dict | None = None, kind: str = "resume") -> None:
    """Check a resume's (or, with ``kind="cover_letter"``, a letter's) shape and limits.

    With ``db``, entry sources must point to the caller's own profile items; IDs
    already in ``existing_content`` (the stored resume being edited) are not checked again.
    """
    if not isinstance(content, dict) or not isinstance(layout, dict):
        raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": "Content and layout must be objects"})
    for field in ("name", "email", "phone", "location", "summary"):
        if field in content and content[field] is not None and not isinstance(content[field], str):
            raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": f"{field} must be text"})
        if isinstance(content.get(field), str) and len(content[field]) > 5000:
            raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": f"{field} is too long"})
    if not isinstance(content.get("sections", []), list):
        raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": "sections must be a list"})
    if template not in {"classic", "modern"}:
        raise HTTPException(422, detail={"code": "INVALID_TEMPLATE", "message": "Template must be classic or modern"})
    fs = layout.get("font_size", 11)
    margin = layout.get("margin", 18)
    spacing = layout.get("line_spacing", 1.25)
    family = layout.get("font_family", "auto")
    numeric_ok = lambda value: (isinstance(value, (int, float)) and not isinstance(value, bool)
                                and (not isinstance(value, float) or math.isfinite(value)))
    if not numeric_ok(fs) or not 8 <= fs <= 16 or not numeric_ok(margin) or not 10 <= margin <= 35:
        raise HTTPException(422, detail={"code": "INVALID_LAYOUT", "message": "font_size must be 8–16 and margin 10–35 mm"})
    if not numeric_ok(spacing) or not 1 <= spacing <= 1.8:
        raise HTTPException(422, detail={"code": "INVALID_LAYOUT", "message": "line_spacing must be between 1.0 and 1.8"})
    if not isinstance(family, str) or family not in {"auto", "serif", "sans", "mono", "latex"}:
        raise HTTPException(422, detail={"code": "INVALID_LAYOUT", "message": "font_family must be auto, serif, sans, mono, or latex"})
    page_size = layout.get("page_size", "A4")
    if not isinstance(page_size, str) or page_size not in {"A4", "letter"}:
        raise HTTPException(422, detail={"code": "INVALID_LAYOUT", "message": "page_size must be A4 or letter"})
    if kind == "cover_letter":
        validate_letter_content(content)
        return
    if len(content.get("sections", [])) > 30:
        raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": "Too many resume sections"})
    for section in content.get("sections", []):
        if not isinstance(section, dict) or not isinstance(section.get("entries", []), list) or not isinstance(section.get("title", ""), str):
            raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": "Sections must contain entry lists"})
        if len(section.get("entries", [])) > 100:
            raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": "Too many entries"})
        for entry in section.get("entries", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("bullets", []), list):
                raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": "Entries must contain bullet lists"})
            if any(not isinstance(b, str) or len(b) > 4000 for b in entry.get("bullets", [])):
                raise HTTPException(422, detail={"code": "INVALID_CONTENT", "message": "Bullets must be text up to 4000 characters"})
    check_bank_fields(content, layout, db, existing_content)

def inspect_pdf(data: bytes) -> dict[str, Any]:
    """Extract bounded text without trying to infer structured profile facts."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            return {"status": "unsupported", "error_code": "ENCRYPTED_PDF", "page_count": None, "text": None}
        page_count = len(reader.pages)
        if page_count > 20:
            return {"status": "unsupported", "error_code": "PAGE_LIMIT_EXCEEDED", "page_count": page_count, "text": None}
        pages = [page.extract_text() or "" for page in reader.pages]
        extracted = "\n\n".join(text.strip() for text in pages if text.strip()).strip()
        if not extracted:
            return {"status": "ocr_required", "error_code": "OCR_REQUIRED", "page_count": page_count, "text": None}
        return {"status": "ready_for_review", "error_code": None, "page_count": page_count,
                "text": extracted[:120000]}
    except Exception:
        return {"status": "unsupported", "error_code": "INVALID_OR_CORRUPT_PDF", "page_count": None, "text": None}

def inspect_docx(data: bytes) -> dict[str, Any]:
    """Bounded text of a safe .docx, for the same review-only step as PDFs (Word files have no page count)."""
    try:
        extracted = extract_docx(data)
    except ImportFailure as exc:
        return {"status": "unsupported", "error_code": exc.code, "page_count": None, "text": None}
    except Exception:
        return {"status": "unsupported", "error_code": "INVALID_OR_CORRUPT_DOCX", "page_count": None, "text": None}
    return {"status": "ready_for_review", "error_code": None, "page_count": None, "text": extracted.text[:120000]}

@app.get("/v1/health")
def health():
    return {"status": "ok"}

def ai_uses(db: Session, user_id: UUID) -> int:
    return allowance.uses(db, user_id)

@app.get("/v1/me")
def me(db: Session = Depends(db_for, scope="function")):
    user = current_user(db)
    used = ai_uses(db, user.id)
    limit = allowance.limit_for(user.plan)
    available = ai_tailoring.build_model() is not None
    return {"user_id": str(user.id), "display_name": user.display_name, "plan": user.plan,
            "allowance": {"limit": limit, "used": used, "remaining": max(limit - used, 0),
                          "period": allowance.month_label(), "enabled": available},
            "ai_available": available, "fit_available": fit_analysis.available(), "letter_available": cover_letters.available(),
            "ai_status": "AI tailoring is ready" if available else "No AI model is configured"}

@app.exception_handler(BankError)
async def bank_error_handler(request: Request, exc: BankError):
    return await http_error_handler(request, HTTPException(exc.status, detail={
        "code": exc.code, "message": exc.message}))

@app.get("/v1/profile")
def profile(db: Session = Depends(db_for, scope="function")):
    return bank_services.read_basics(db)

@app.put("/v1/profile")
def update_profile(body: ProfileWrite, db: Session = Depends(db_for, scope="function")):
    return bank_services.update_basics(db, body.draft, body.expected_revision)

@app.post("/v1/profile/confirm")
def confirm_profile(body: ConfirmWrite, db: Session = Depends(db_for, scope="function")):
    result = bank_services.confirm_bank(db, body.expected_bank_revision)
    profile_sync.embed_after_save(db, current_user(db).id)   # best effort: a failed embed never fails the confirm
    return result

app.include_router(build_router(db_for))
app.include_router(fit_analysis.build_router(db_for, current_user))
app.include_router(cover_letters.build_router(db_for, current_user, doc_out))

@app.get("/v1/preferences")
def get_preferences(db: Session = Depends(db_for, scope="function")):
    item = db.get(Preference, current_user(db).id)
    data = dict(item.data) if item else {}
    seniority = data.get("seniority")
    if isinstance(seniority, str):
        normalized = normalise_levels(seniority)
        if len(normalized) == 1:
            data["seniority"] = normalized[0]
    return {**data, "revision": item.revision if item else 0}

@app.get("/v1/preferences/seniority-options")
def seniority_options():
    return {"items": SENIORITY_OPTIONS}

@app.put("/v1/preferences")
def update_preferences(body: PreferencesWrite, db: Session = Depends(db_for, scope="function")):
    item = db.scalar(select(Preference).where(Preference.user_id == current_user(db).id).with_for_update())
    if item is None:
        if body.expected_revision != 0: raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Preferences changed"})
        item = Preference(user_id=current_user(db).id, revision=1, data=body.model_dump(exclude={"expected_revision"})); db.add(item)
    else:
        if item.revision != body.expected_revision: raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Preferences changed"})
        item.data = body.model_dump(exclude={"expected_revision"}); item.revision += 1
    profile_sync.embed_after_save(db, current_user(db).id)   # best effort; no-op without a confirmed profile
    return {**item.data, "revision": item.revision}

@app.get("/v1/recommendations")
def recommendations(db: Session = Depends(db_for, scope="function"), limit: int = Query(20, ge=1, le=100),
                     offset: int = Query(0, ge=0, le=1000000),
                     q: str | None = Query(None, max_length=200),
                     chosen: dict | None = Depends(discover_filters), since: datetime = Depends(posted_after)):
    return keyword_recommendations(db, limit, offset, q, effective_preferences(db, chosen), since)

def keyword_recommendations(db: Session, limit: int, offset: int, q: str | None, prefs: dict,
                            since: datetime | None = None) -> dict:
    jobs = db.scalars(select(Job).where(listed_jobs(posted_after=since))).all()
    skipped = skipped_job_ids(db)
    candidates = [job_out(job) for job in jobs if str(job.id) not in skipped]
    ranked = rank_jobs(candidates, bank_services.build_profile_snapshot(db), prefs)
    query = q.strip().casefold() if q else ""
    if query:
        ranked = [row for row in ranked if query in " ".join(str(row["job"].get(field) or "")
                  for field in ("title", "company", "description", "location", "category", "skills")).casefold()]
    items = []
    for row in ranked[offset:offset + limit]:
        reasons = ([row["reason"]] if row["mode"] == "cold_start" else
                   [evidence["text"] for evidence in row["evidence"]] or [row["reason"]])
        items.append({**row, "reasons": reasons, "review": None})
    return {"items": items, "total": len(ranked),
            "next_offset": offset + limit if offset + limit < len(ranked) else None,
            "degraded_mode": True, "ranking_version": RANKING_VERSION,
            "ranking_status": "Keyword text similarity and skill matching (the For you list uses semantic matching)"}

@app.get("/v1/recommendations/for-you")
def recommendations_for_you(db: Session = Depends(db_for, scope="function"), limit: int = Query(20, ge=1, le=100),
                            offset: int = Query(0, ge=0, le=1000000),
                            q: str | None = Query(None, max_length=200),
                            chosen: dict | None = Depends(discover_filters), since: datetime = Depends(posted_after)):
    """Semantic recommendations (eligibility, role/seniority checks, then similarity), behind FOR_YOU_ENABLED.

    Falls back to the keyword ranker, and says so in ``ranking_mode`` / ``fallback_reason``, whenever the
    profile has no confirmed version or no vector. The existing /v1/recommendations is unchanged.
    Discover filters (``filters=custom|none``) replace the saved preferences for this request only; the profile's
    vector still comes from what was saved."""
    if not embedding_settings.for_you_enabled():
        raise HTTPException(404, detail={"code": "FOR_YOU_DISABLED", "message": "Semantic recommendations are not enabled"})
    prefs = effective_preferences(db, chosen)
    skipped = sorted(skipped_job_ids(db))
    confirmed = bank_services.get_confirmed_snapshot(db)
    result, reason = semantic.semantic_for_you(db, confirmed, prefs, skipped, posted_after=since)
    if result is None:
        base = keyword_recommendations(db, limit, offset, q, prefs, since)
        code = "profile_embedding_pending" if reason == semantic.NO_VECTOR else "no_profile"   # the page offers "Check again" only for the first
        return {**base, "ranking_mode": "keyword_fallback", "fallback_reason": reason, "fallback_code": code}
    ordered, fused = result.ranked, False
    if embedding_settings.for_you_fusion_enabled():
        try:   # merge the keyword ranking in; if it cannot be computed, keep the semantic order rather than fail the page
            open_jobs = db.scalars(select(Job).where(listed_jobs(posted_after=since))).all()
            keyword_ranked = rank_jobs([job_out(job) for job in open_jobs if str(job.id) not in set(skipped)],
                                       bank_services.build_profile_snapshot(db), prefs)
            ordered, fused = semantic.fuse_with_keyword(result.ranked, keyword_ranked), True
        except Exception:
            logging.getLogger(__name__).exception("For you: keyword fusion failed; serving the semantic order")
    ranked = semantic.matching(db, ordered, q, job_out)
    total = len(ranked)
    return {"items": semantic.page_items(db, ranked, offset, limit, job_out, snapshot=confirmed[2],
                                         preferences=prefs), "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
            "degraded_mode": False, "ranking_mode": "semantic", "ranking_fusion": FUSION_VERSION if fused else None,
            "ranking_version": semantic.FUSED_RANKING_VERSION if fused else semantic.RANKING_VERSION,
            "fallback_reason": None, "fallback_code": None, "blocked_by_checks": len(result.blocked),
            "ranking_status": semantic.FUSED_STATUS if fused else semantic.SEMANTIC_STATUS}

def skipped_job_ids(db: Session) -> set[str]:
    """Jobs this user saved or passed on, plus the canonical row of any of them that has since become a duplicate.

    Discover lists show only canonical rows, so a posting the user already reviewed under another source stays hidden."""
    reviewed = [r.job_id for r in db.scalars(select(JobReview)).all() if r.decision in {"saved", "dismissed"}]
    hidden = {str(job_id) for job_id in reviewed}
    if reviewed:
        hidden.update(str(job_id) for job_id in db.scalars(
            select(Job.canonical_job_id).where(Job.id.in_(reviewed), Job.canonical_job_id.is_not(None))))
    return hidden

def job_out(job: Job) -> dict:
    return {"id": str(job.id), "title": job.title, "company": job.company,
            "employer": job.company, "location": job.location, "work_mode": job.work_mode,
            "description": job.description, "url": job.source_url or job.url,
            "source_url": job.source_url or job.url, "source": job.source,
            "source_board": job.source_board,
            "posted_at": job.posted_at.isoformat() if job.posted_at else None,
            "fetched_at": job.fetched_at.isoformat() if job.fetched_at else None,
            "category": job.category, "category_source": job.category_source,
            "category_evidence": job.category_evidence,
            "skills": job.skills, "status": job.status, "salary_min": job.salary_min,
            "salary_max": job.salary_max, "salary_currency": job.salary_currency,
            "salary_period": job.salary_period,
            # The other sources that list the same posting (cross-source de-duplication); empty when there are none.
            "also_seen_on": job.also_seen_on or []}

@app.get("/v1/jobs/reviewed")   # declared before /v1/jobs/{job_id} so "reviewed" is not read as a job id
def reviewed_jobs(decision: str = Query(pattern="^(saved|dismissed)$"), limit: int = Query(20, ge=1, le=100),
                  offset: int = Query(0, ge=0, le=1000000), q: str | None = Query(None, max_length=200),
                  db: Session = Depends(db_for, scope="function")):
    """The jobs this user saved or passed on, newest decision first, in the same item shape as the Discover lists."""
    rows = db.execute(select(JobReview, Job).join(Job, Job.id == JobReview.job_id)
                      .where(JobReview.user_id == current_user(db).id, JobReview.decision == decision)
                      .order_by(JobReview.updated_at.desc())).all()
    items = [{"job": job_out(job), "score": None, "reasons": [], "review": review.decision} for review, job in rows]
    query = q.strip().casefold() if q else ""
    if query:
        items = [row for row in items if query in " ".join(str(row["job"].get(field) or "")
                 for field in ("title", "company", "description", "location", "category", "skills")).casefold()]
    return {"items": items[offset:offset + limit], "total": len(items),
            "next_offset": offset + limit if offset + limit < len(items) else None}

@app.get("/v1/jobs/{job_id}")
def get_job(job_id: UUID, db: Session = Depends(db_for, scope="function")):
    job = db.get(Job, job_id)
    if job is None: not_found()
    return job_out(job)

@app.put("/v1/jobs/{job_id}/review")
def review_job(job_id: UUID, body: ReviewWrite, db: Session = Depends(db_for, scope="function")):
    if body.decision not in {"saved", "dismissed", "none"}: raise HTTPException(422, detail={"code": "INVALID_DECISION", "message": "decision must be saved, dismissed, or none"})
    if db.get(Job, job_id) is None: not_found()
    user_id = current_user(db).id
    item = db.scalar(select(JobReview).where(JobReview.user_id == user_id, JobReview.job_id == job_id))
    if body.decision == "none":
        if item: db.delete(item)
    elif item:
        item.decision = body.decision
    else:
        db.add(JobReview(user_id=user_id, job_id=job_id, decision=body.decision))
    application = db.scalar(select(Application).where(Application.user_id == user_id, Application.job_id == job_id).with_for_update())
    if body.decision == "saved":
        if application is None:
            db.add(Application(user_id=user_id, job_id=job_id, status="saved", notes="", revision=1))
    elif application is not None and is_untouched_save(application):
        db.delete(application)
    return {"job_id": str(job_id), "decision": None if body.decision == "none" else body.decision}

def is_untouched_save(application: Application) -> bool:
    """A tracker row that only exists because the job was saved: nothing the user wrote or attached would be lost."""
    return (application.status == "saved" and not (application.notes or "").strip() and application.applied_at is None
            and application.resume_export_id is None and not application.cover_letter_text
            and application.cover_letter_export_id is None and application.packet_updated_at is None)

@app.get("/v1/applications")
def list_applications(db: Session = Depends(db_for, scope="function")):
    user_id = current_user(db).id
    rows = db.scalars(select(Application).where(Application.user_id == user_id)
                      .order_by(Application.updated_at.desc())).all()
    # Two queries for the whole list, not one or two per application.
    jobs = {job.id: job for job in db.scalars(select(Job).where(Job.id.in_({x.job_id for x in rows})))} if rows else {}
    export_ids = {export_id for x in rows for export_id in (x.resume_export_id, x.cover_letter_export_id) if export_id}
    exports = ({export.id: export for export in db.scalars(select(DocumentExport).where(
        DocumentExport.id.in_(export_ids), DocumentExport.user_id == user_id))} if export_ids else {})
    return {"items": [application_out(x, db, jobs=jobs, exports=exports) for x in rows]}

def application_out(item: Application, db: Session, *, jobs: dict | None = None, exports: dict | None = None) -> dict:
    """``jobs`` and ``exports`` are optional id-keyed lookups loaded once for a whole list; alone, it queries per row."""
    def packet_for(export_id: UUID | None, title: str | None) -> dict | None:
        if not export_id:
            return None
        if exports is not None:
            export = exports.get(export_id)
        else:
            export = db.scalar(select(DocumentExport).where(
                DocumentExport.id == export_id,
                DocumentExport.user_id == current_user(db).id,
            ))
        if not export:
            return None
        return {"export_id": str(export.id), "document_id": str(export.document_id),
                "title": title, "revision": export.revision,
                "download_url": f"/v1/exports/{export.id}"}
    packet = packet_for(item.resume_export_id, item.resume_title)
    letter_packet = packet_for(item.cover_letter_export_id, item.cover_letter_title)
    job = jobs.get(item.job_id) if jobs is not None else db.get(Job, item.job_id)
    return {"id": str(item.id), "job_id": str(item.job_id), "status": item.status,
            "notes": item.notes, "applied_at": item.applied_at.isoformat() if item.applied_at else None,
            "revision": item.revision, "job": job_out(job) if job else None,
            "resume_export_id": str(item.resume_export_id) if item.resume_export_id else None,
            "resume_packet": packet, "cover_letter_packet": letter_packet, "cover_letter_text": item.cover_letter_text,
            "packet_updated_at": item.packet_updated_at.isoformat() if item.packet_updated_at else None}

def create_reviewed_export(document: Document, user_id: UUID, db: Session) -> DocumentExport:
    export_id = uuid4()
    path = storage.write(storage.reference("exports", user_id, export_id, "pdf"), pdf_bytes(document), "application/pdf")
    export = DocumentExport(id=export_id, user_id=user_id, document_id=document.id,
                            revision=document.revision, file_path=str(path))
    db.add(export)
    db.flush()
    return export

@app.put("/v1/applications/{job_id}")
def put_application(job_id: UUID, body: ApplicationWrite, db: Session = Depends(db_for, scope="function")):
    if body.status is not None and body.status not in {"saved", "preparing", "applied", "interviewing", "offer", "rejected", "withdrawn"}:
        raise HTTPException(422, detail={"code": "INVALID_STATUS", "message": "Unsupported application status"})
    if db.get(Job, job_id) is None: not_found()
    user_id = current_user(db).id
    fields = body.model_fields_set
    if "resume_document_id" in fields and "resume_export_id" in fields:
        raise HTTPException(422, detail={"code": "AMBIGUOUS_RESUME", "message": "Provide a document ID or an export ID, not both"})
    if "resume_document_id" in fields and body.resume_document_id is not None and body.expected_resume_revision is None:
        raise HTTPException(422, detail={"code": "REVISION_REQUIRED", "message": "expected_resume_revision is required when selecting a resume"})
    item = db.scalar(select(Application).where(Application.user_id == user_id,
                        Application.job_id == job_id).with_for_update())
    if item is None:
        if body.expected_revision not in (None, 0): raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Application changed"})
        item = Application(user_id=user_id, job_id=job_id,
            status=body.status or "saved", notes=body.notes or "", applied_at=body.applied_at, revision=1)
        db.add(item)
    else:
        if body.expected_revision != item.revision: raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Application changed"})
        if "status" in fields and body.status is not None: item.status = body.status
        if "notes" in fields and body.notes is not None: item.notes = body.notes
        if "applied_at" in fields: item.applied_at = body.applied_at
        item.revision += 1

    if "resume_document_id" in fields:
        if body.resume_document_id is None:
            item.resume_export_id = None; item.resume_title = None
        else:
            document = db.scalar(select(Document).where(
                Document.id == body.resume_document_id, Document.user_id == user_id).with_for_update())
            if document is None: not_found()
            if document.kind != "resume":
                raise HTTPException(422, detail={"code": "NOT_A_RESUME", "message": "Select a resume document"})
            if document.revision != body.expected_resume_revision:
                raise HTTPException(409, detail={"code": "RESUME_REVISION_CONFLICT", "message": "Resume changed; review the latest version before attaching it"})
            if document.reviewed_revision != document.revision:
                raise HTTPException(409, detail={"code": "REVIEW_REQUIRED", "message": "Review the current resume revision before attaching it"})
            old_export = db.scalar(select(DocumentExport).where(
                DocumentExport.id == item.resume_export_id, DocumentExport.user_id == user_id)) if item.resume_export_id else None
            if old_export and old_export.document_id == document.id and old_export.revision == document.revision:
                export = old_export
            else:
                export = create_reviewed_export(document, user_id, db)
            item.resume_export_id = export.id
            item.resume_title = document.title
    elif "resume_export_id" in fields:
        if body.resume_export_id is None:
            item.resume_export_id = None; item.resume_title = None
        else:
            export = db.scalar(select(DocumentExport).where(
                DocumentExport.id == body.resume_export_id, DocumentExport.user_id == user_id))
            if export is None: not_found()
            document = db.scalar(select(Document).where(
                Document.id == export.document_id, Document.user_id == user_id))
            if document is None: not_found()
            item.resume_export_id = export.id
            item.resume_title = document.title

    if "cover_letter_document_id" in fields:
        if body.cover_letter_document_id is None:
            item.cover_letter_export_id = None; item.cover_letter_title = None
        else:
            if body.expected_cover_letter_revision is None:
                raise HTTPException(422, detail={"code": "REVISION_REQUIRED", "message": "expected_cover_letter_revision is required when selecting a letter"})
            letter = db.scalar(select(Document).where(
                Document.id == body.cover_letter_document_id, Document.user_id == user_id).with_for_update())
            if letter is None: not_found()
            if letter.kind != "cover_letter":
                raise HTTPException(422, detail={"code": "NOT_A_COVER_LETTER", "message": "Select a cover letter document"})
            if letter.revision != body.expected_cover_letter_revision:
                raise HTTPException(409, detail={"code": "LETTER_REVISION_CONFLICT", "message": "Letter changed; review the latest version before attaching it"})
            if letter.reviewed_revision != letter.revision:
                raise HTTPException(409, detail={"code": "REVIEW_REQUIRED", "message": "Review the current letter revision before attaching it"})
            old_letter_export = db.scalar(select(DocumentExport).where(
                DocumentExport.id == item.cover_letter_export_id, DocumentExport.user_id == user_id)) if item.cover_letter_export_id else None
            if old_letter_export and old_letter_export.document_id == letter.id and old_letter_export.revision == letter.revision:
                letter_export = old_letter_export
            else:
                letter_export = create_reviewed_export(letter, user_id, db)
            item.cover_letter_export_id = letter_export.id
            item.cover_letter_title = letter.title

    if "cover_letter_text" in fields:
        item.cover_letter_text = body.cover_letter_text
    if fields & {"resume_document_id", "resume_export_id", "cover_letter_text", "cover_letter_document_id"}:
        item.packet_updated_at = now_utc()
    db.flush()
    return application_out(item, db)

app.include_router(build_resume_router(db_for, validate_document=validate_document, doc_out=doc_out))

@app.get("/v1/documents")
def list_documents(kind: str | None = None, db: Session = Depends(db_for, scope="function")):
    stmt = select(Document).where(Document.user_id == current_user(db).id)
    # Without a kind, archived (deleted) documents stay out of the list; ask for kind=archived to see them.
    stmt = stmt.where(Document.kind == kind) if kind else stmt.where(Document.kind.notin_(tuple(RESTORED_AS)))
    return {"items": [doc_out(x) for x in db.scalars(stmt.order_by(Document.updated_at.desc())).all()]}

@app.post("/v1/documents", status_code=201)
def create_document(body: DocumentCreate, db: Session = Depends(db_for, scope="function")):
    # A new, empty resume starts from the user's resume defaults and profile basics.
    template, content, layout = blank_document_parts(
        body.template if "template" in body.model_fields_set else None, body.content,
        body.layout if "layout" in body.model_fields_set else None,
        bank_services.read_basics(db)["draft"], bank_services.get_settings(db)["resume_defaults"])
    validate_document(template, content, layout, db)
    if body.job_id is not None and db.get(Job, body.job_id) is None: not_found()
    item = Document(user_id=current_user(db).id, title=body.title, template=template,
                    content=content, layout=layout, revision=1, job_id=body.job_id)
    db.add(item); db.flush()
    return doc_out(item)

@app.get("/v1/documents/{document_id}")
def get_document(document_id: UUID, db: Session = Depends(db_for, scope="function")):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id))
    if item is None: not_found()
    return doc_out(item)

@app.patch("/v1/documents/{document_id}")
def patch_document(document_id: UUID, body: DocumentPatch, db: Session = Depends(db_for, scope="function")):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id, Document.kind.in_(WRITTEN_KINDS)).with_for_update())
    if item is None: not_found()
    if item.revision != body.expected_revision: raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Document changed"})
    changes = body.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    template = changes.get("template", item.template); content = changes.get("content", item.content); layout = changes.get("layout", item.layout)
    validate_document(template, content, layout, db, item.content, kind=item.kind)
    for key, value in changes.items(): setattr(item, key, value)
    item.revision += 1; item.reviewed_revision = None; item.updated_at = now_utc()
    return doc_out(item)

@app.delete("/v1/documents/{document_id}", status_code=204)
def archive_document(document_id: UUID, db: Session = Depends(db_for, scope="function")):
    """Archive a resume or cover letter: it leaves the library but its exports and application snapshots keep working."""
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id,
                                            Document.kind.in_(tuple(ARCHIVED_AS) + tuple(RESTORED_AS))).with_for_update())
    if item is None: not_found()
    if item.kind in ARCHIVED_AS: item.kind = ARCHIVED_AS[item.kind]
    return Response(status_code=204)

@app.post("/v1/documents/{document_id}/restore")
def restore_document(document_id: UUID, db: Session = Depends(db_for, scope="function")):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id,
                                            Document.kind.in_(tuple(ARCHIVED_AS) + tuple(RESTORED_AS))).with_for_update())
    if item is None: not_found()
    if item.kind in RESTORED_AS: item.kind = RESTORED_AS[item.kind]
    return doc_out(item)

@app.post("/v1/documents/{document_id}/duplicate", status_code=201)
def duplicate_document(document_id: UUID, body: DuplicateWrite, db: Session = Depends(db_for, scope="function")):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id, Document.kind.in_(WRITTEN_KINDS)))
    if item is None: not_found()
    if body.job_id and db.get(Job, body.job_id) is None: not_found()
    copy = Document(user_id=item.user_id, title=body.title or f"{item.title} copy", kind=item.kind,
                    template=item.template, content=item.content, layout=item.layout, revision=1, job_id=body.job_id)
    db.add(copy); db.flush()
    return doc_out(copy)

@app.post("/v1/documents/{document_id}/tailor", status_code=201)
def tailor_document(document_id: UUID, body: TailorWrite, db: Session = Depends(db_for, scope="function")):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id, Document.kind == "resume"))
    job = db.get(Job, body.job_id)
    if item is None or job is None: not_found()
    content, keywords = tailor(item.content, job_out(job))
    ai = {"status": "off", "changed": 0, "reason": None}
    if body.mode == "ai":
        model = ai_tailoring.build_model()
        if model is None:
            raise HTTPException(503, detail={"code": "AI_NOT_CONFIGURED", "message": "No AI model is configured"})
        user = current_user(db)
        user_id = user.id
        if not allowance.can_spend(db, user_id, job.id, user.plan):
            raise HTTPException(402, detail={"code": "AI_LIMIT_REACHED", "message": f"You have used all {allowance.limit_for(user.plan)} AI uses for this month"})
        try:
            content, changed = ai_tailoring.rewrite_content(content, job_out(job), model)
            ai = {"status": "applied" if changed else "unchanged", "changed": changed, "reason": None}
            if changed:
                allowance.spend(db, user_id, job.id)
        except ai_tailoring.AiUnavailable as exc:
            ai = {"status": "fallback", "changed": 0, "reason": str(exc)}
    copy = Document(user_id=item.user_id, title=(body.title or f"{item.title} — {job.title}")[:240], kind=item.kind,
                    template=item.template, content=content, layout=item.layout, revision=1, job_id=job.id)
    db.add(copy); db.flush()
    return {"document": doc_out(copy), **keywords, "ai": ai}

@app.post("/v1/documents/{document_id}/review")
def review_document(document_id: UUID, body: DocumentReview, db: Session = Depends(db_for, scope="function")):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id, Document.kind.in_(WRITTEN_KINDS)).with_for_update())
    if item is None: not_found()
    if body.expected_revision != item.revision: raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Document changed"})
    item.reviewed_revision = item.revision
    return doc_out(item)

def owned_document(document_id: UUID, db: Session) -> Document:
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id))
    if item is None: not_found()
    return item

@app.get("/v1/documents/{document_id}/preview.pdf")
def preview_document(document_id: UUID, db: Session = Depends(db_for, scope="function")):
    return Response(pdf_bytes(owned_document(document_id, db)), media_type="application/pdf",
                    headers={"Content-Disposition": "inline; filename=resume-preview.pdf"})

@app.post("/v1/documents/{document_id}/exports", status_code=201)
def export_document(document_id: UUID, db: Session = Depends(db_for, scope="function")):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id, Document.kind.in_(WRITTEN_KINDS)).with_for_update())
    if item is None: not_found()
    if item.reviewed_revision != item.revision:
        raise HTTPException(409, detail={"code": "REVIEW_REQUIRED", "message": "Review the current revision before export"})
    export = create_reviewed_export(item, current_user(db).id, db)
    export_id = export.id
    return {"export_id": str(export_id), "revision": item.revision, "download_url": f"/v1/exports/{export_id}"}

@app.get("/v1/exports/{export_id}")
def download_export(export_id: UUID, db: Session = Depends(db_for, scope="function")):
    item = db.scalar(select(DocumentExport).where(DocumentExport.id == export_id, DocumentExport.user_id == current_user(db).id))
    if item is None: not_found()
    source = db.get(Document, item.document_id) if getattr(item, "document_id", None) else None
    filename = f"{'cover-letter' if source is not None and source.kind in ('cover_letter', 'archived_letter') else 'resume'}-r{item.revision}.pdf"
    if item.file_path.startswith("s3://"):
        return JSONResponse({"url": storage.download_url(item.file_path, filename, "application/pdf")}, headers={"Cache-Control": "no-store"})
    try:
        data = storage.read(item.file_path)
    except FileNotFoundError:
        not_found()
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@app.post("/v1/uploads", status_code=201)
def upload_resume(body: UploadCreate, db: Session = Depends(db_for, scope="function")):
    declared = declared_file_problem(body.filename, body.content_type)
    if isinstance(declared, tuple):
        raise HTTPException(422, detail={"code": declared[0], "message": declared[1]})
    upload_id = uuid4()
    path = storage.reference("uploads", current_user(db).id, upload_id, declared)
    upload = Upload(id=upload_id, user_id=current_user(db).id, filename=Path(body.filename).name,
                    content_type=body.content_type, declared_size=body.size_bytes,
                    file_path=str(path)); db.add(upload); db.flush()
    if settings.storage_backend == "s3":
        return {"upload_id": str(upload_id), "upload_url": storage.upload_url(path, body.content_type, body.size_bytes),
                "finalize_url": f"/v1/uploads/{upload_id}/finalize", "fields": {}, "expires_at": None}
    return {"upload_id": str(upload_id), "upload_url": f"/v1/uploads/{upload_id}/content", "fields": {}, "expires_at": None}

@app.put("/v1/uploads/{upload_id}/content")
async def save_upload_content(upload_id: UUID, request: Request, db: Session = Depends(db_for, scope="function")):
    if settings.storage_backend != "local":
        raise HTTPException(400, detail="Use the direct upload URL and finalize endpoint")
    item = db.scalar(select(Upload).where(Upload.id == upload_id, Upload.user_id == current_user(db).id).with_for_update())
    if item is None: not_found()
    if item.sha256 is not None:
        raise HTTPException(409, detail={"code": "UPLOAD_IMMUTABLE", "message": "This upload has already been captured"})
    parts = []
    total_size = 0
    async for chunk in request.stream():
        total_size += len(chunk)
        if total_size > min(item.declared_size, 10 * 1024 * 1024):
            raise HTTPException(413, detail={"code": "UPLOAD_TOO_LARGE", "message": "File exceeds its declared size or the 10 MiB limit"})
        parts.append(chunk)
    data = b"".join(parts)
    if total_size != item.declared_size:
        raise HTTPException(422, detail={"code": "SIZE_MISMATCH", "message": "Uploaded byte count does not match the declared size"})
    return process_upload(item, data)


@app.post("/v1/uploads/{upload_id}/finalize")
def finalize_upload(upload_id: UUID, db: Session = Depends(db_for, scope="function")):
    if settings.storage_backend != "s3":
        raise HTTPException(400, detail="Direct upload finalization is not enabled")
    item = db.scalar(select(Upload).where(Upload.id == upload_id, Upload.user_id == current_user(db).id).with_for_update())
    if item is None:
        not_found()
    if item.sha256 is not None:
        raise HTTPException(409, detail={"code": "UPLOAD_IMMUTABLE", "message": "This upload has already been captured"})
    try:
        frozen, data = storage.capture(item.file_path, item.declared_size)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(422, detail={"code": "INVALID_UPLOAD", "message": str(exc)}) from exc
    result = process_upload(item, data, persist=False)
    item.file_path = frozen
    return result


def process_upload(item: Upload, data: bytes, persist: bool = True):
    try:
        kind = detect_resume_file(data)
    except ImportFailure as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": str(exc)})
    # The bytes decide the type, so a renamed file is stored (and later served) as what it really is.
    item.content_type = CONTENT_TYPES[kind]
    if persist:
        item.file_path = storage.write(str(Path(item.file_path).with_suffix(f".{kind}")), data, item.content_type)
    item.sha256 = hashlib.sha256(data).hexdigest()
    parsed = inspect_pdf(data) if kind == "pdf" else inspect_docx(data)
    item.status = parsed["status"]
    item.page_count = parsed["page_count"]
    item.extracted_text = parsed["text"]
    item.error_code = parsed["error_code"]
    return {"upload_id": str(item.id), "status": item.status, "page_count": item.page_count,
            "error_code": item.error_code,
            "message": "Extracted text is a review candidate only; verify it and enter profile facts manually.",
            "ai_available": False}

@app.get("/v1/uploads/{upload_id}")
def get_upload(upload_id: UUID, db: Session = Depends(db_for, scope="function")):
    item = db.scalar(select(Upload).where(Upload.id == upload_id, Upload.user_id == current_user(db).id))
    if item is None: not_found()
    return {"upload_id": str(item.id), "filename": item.filename, "status": item.status,
            "page_count": item.page_count, "extracted_text": item.extracted_text,
            "error_code": item.error_code, "sha256": item.sha256}
