from datetime import datetime, timezone
import hashlib
import json
import math
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_hunter.config import settings
from job_hunter.recommendations import rank_jobs, RANKING_VERSION
from job_hunter.adapters.database import get_db
from job_hunter.domain.identity import DEV_USERS
from job_hunter.domain.models import (User, Profile, Preference, Job, JobReview, Application,
                                      ProfileVersion, Document, DocumentExport, Upload, now_utc)
from job_hunter.domain.models import Base
from job_hunter.adapters.database import engine
from job_hunter.preparation.rendering import pdf_bytes

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

def identity(x_dev_user: str | None = Header(default=None)) -> str:
    if settings.auth_mode != "local" or settings.app_env not in {"local", "test"}:
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Identity provider is not configured"})
    chosen = x_dev_user or settings.dev_default_user
    if chosen not in DEV_USERS:
        raise HTTPException(401, detail={"code": "INVALID_DEV_IDENTITY", "message": "Use alice or bob in local mode"})
    return chosen

def db_for(user_key: str = Depends(identity)):
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
    expected_revision: int

class PreferencesWrite(BaseModel):
    roles: list[str] = []
    locations: list[str] = []
    work_modes: list[str] = []
    seniority: str | None = None
    salary_min: float | None = None
    salary_currency: str | None = "SGD"
    salary_period: str | None = "year"
    expected_revision: int

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

class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)

def validate_document(template: str, content: dict, layout: dict) -> None:
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
    if not isinstance(family, str) or family not in {"auto", "serif", "sans", "mono"}:
        raise HTTPException(422, detail={"code": "INVALID_LAYOUT", "message": "font_family must be auto, serif, sans, or mono"})
    page_size = layout.get("page_size", "A4")
    if not isinstance(page_size, str) or page_size not in {"A4", "letter"}:
        raise HTTPException(422, detail={"code": "INVALID_LAYOUT", "message": "page_size must be A4 or letter"})
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

@app.get("/v1/health")
def health():
    return {"status": "ok"}

@app.get("/v1/me")
def me(db: Session = Depends(db_for)):
    user = current_user(db)
    limit = 50 if user.plan == "premium" else 5
    period = datetime.now(ZoneInfo("Asia/Singapore")).strftime("%Y-%m")
    return {"user_id": str(user.id), "display_name": user.display_name, "plan": user.plan,
            "allowance": {"limit": limit, "used": None, "remaining": None, "period": period, "enabled": False},
            "ai_available": False, "ai_status": "AI generation is not configured in this local POC"}

@app.get("/v1/profile")
def profile(db: Session = Depends(db_for)):
    user = current_user(db); item = db.get(Profile, user.id)
    if item is None: return {"draft": {}, "revision": 0, "confirmed_revision": None}
    return {"draft": item.draft, "revision": item.revision, "confirmed_revision": item.confirmed_revision}

@app.put("/v1/profile")
def update_profile(body: ProfileWrite, db: Session = Depends(db_for)):
    user = current_user(db); item = db.scalar(select(Profile).where(Profile.user_id == user.id).with_for_update())
    if item is None:
        if body.expected_revision != 0: raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Profile changed"})
        item = Profile(user_id=user.id, revision=1, draft=body.draft); db.add(item)
    else:
        if item.revision != body.expected_revision: raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Profile changed"})
        item.draft = body.draft; item.revision += 1; item.updated_at = now_utc()
    return {"draft": item.draft, "revision": item.revision, "confirmed_revision": item.confirmed_revision}

@app.post("/v1/profile/confirm")
def confirm_profile(body: ConfirmWrite, db: Session = Depends(db_for)):
    item = db.scalar(select(Profile).where(Profile.user_id == current_user(db).id).with_for_update())
    if item is None or item.revision != body.expected_revision:
        raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Profile changed"})
    data = item.draft
    content_hash = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    version = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == item.user_id,
                                ProfileVersion.revision == item.revision))
    if version is None:
        version = ProfileVersion(user_id=item.user_id, revision=item.revision, data=data, content_hash=content_hash)
        db.add(version)
    item.confirmed_revision = item.revision
    return {"confirmed": True, "revision": item.revision, "profile_version_id": str(version.id),
            "embedding_status": "unavailable"}

@app.get("/v1/preferences")
def get_preferences(db: Session = Depends(db_for)):
    item = db.get(Preference, current_user(db).id)
    return {**(item.data if item else {}), "revision": item.revision if item else 0}

@app.put("/v1/preferences")
def update_preferences(body: PreferencesWrite, db: Session = Depends(db_for)):
    item = db.scalar(select(Preference).where(Preference.user_id == current_user(db).id).with_for_update())
    if item is None:
        if body.expected_revision != 0: raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Preferences changed"})
        item = Preference(user_id=current_user(db).id, revision=1, data=body.model_dump(exclude={"expected_revision"})); db.add(item)
    else:
        if item.revision != body.expected_revision: raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Preferences changed"})
        item.data = body.model_dump(exclude={"expected_revision"}); item.revision += 1
    return {**item.data, "revision": item.revision}

@app.get("/v1/recommendations")
def recommendations(db: Session = Depends(db_for), limit: int = Query(20, ge=1, le=100),
                     offset: int = Query(0, ge=0, le=1000000),
                     q: str | None = Query(None, max_length=200)):
    jobs = db.scalars(select(Job).where(Job.status == "open")).all()
    reviews = {r.job_id: r.decision for r in db.scalars(select(JobReview)).all()}
    prefs = db.get(Preference, current_user(db).id)
    profile = db.get(Profile, current_user(db).id)
    candidates = [job_out(job) for job in jobs if reviews.get(job.id) not in {"saved", "dismissed"}]
    ranked = rank_jobs(candidates, profile.draft if profile else {}, prefs.data if prefs else {})
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
            "ranking_status": "Local text similarity and skill matching; semantic embeddings are not enabled"}

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
            "salary_period": job.salary_period}

@app.get("/v1/jobs/{job_id}")
def get_job(job_id: UUID, db: Session = Depends(db_for)):
    job = db.get(Job, job_id)
    if job is None: not_found()
    return job_out(job)

@app.put("/v1/jobs/{job_id}/review")
def review_job(job_id: UUID, body: ReviewWrite, db: Session = Depends(db_for)):
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
    if body.decision == "saved" and db.scalar(select(Application).where(Application.user_id == user_id, Application.job_id == job_id)) is None:
        db.add(Application(user_id=user_id, job_id=job_id, status="saved", notes="", revision=1))
    return {"job_id": str(job_id), "decision": None if body.decision == "none" else body.decision}

@app.get("/v1/applications")
def list_applications(db: Session = Depends(db_for)):
    rows = db.scalars(select(Application).where(Application.user_id == current_user(db).id)
                      .order_by(Application.updated_at.desc())).all()
    return {"items": [application_out(x, db) for x in rows]}

def application_out(item: Application, db: Session) -> dict:
    packet = None
    if item.resume_export_id:
        export = db.scalar(select(DocumentExport).where(
            DocumentExport.id == item.resume_export_id,
            DocumentExport.user_id == current_user(db).id,
        ))
        if export:
            packet = {"export_id": str(export.id), "document_id": str(export.document_id),
                      "title": item.resume_title, "revision": export.revision,
                      "download_url": f"/v1/exports/{export.id}"}
    job = db.get(Job, item.job_id)
    return {"id": str(item.id), "job_id": str(item.job_id), "status": item.status,
            "notes": item.notes, "applied_at": item.applied_at.isoformat() if item.applied_at else None,
            "revision": item.revision, "job": job_out(job) if job else None,
            "resume_export_id": str(item.resume_export_id) if item.resume_export_id else None,
            "resume_packet": packet, "cover_letter_text": item.cover_letter_text,
            "packet_updated_at": item.packet_updated_at.isoformat() if item.packet_updated_at else None}

def create_reviewed_export(document: Document, user_id: UUID, db: Session) -> DocumentExport:
    export_id = uuid4()
    directory = Path(settings.pdf_storage_dir).resolve(); directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{user_id}-{export_id}.pdf"
    path.write_bytes(pdf_bytes(document))
    export = DocumentExport(id=export_id, user_id=user_id, document_id=document.id,
                            revision=document.revision, file_path=str(path))
    db.add(export)
    db.flush()
    return export

@app.put("/v1/applications/{job_id}")
def put_application(job_id: UUID, body: ApplicationWrite, db: Session = Depends(db_for)):
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

    if "cover_letter_text" in fields:
        item.cover_letter_text = body.cover_letter_text
    if fields & {"resume_document_id", "resume_export_id", "cover_letter_text"}:
        item.packet_updated_at = now_utc()
    db.flush()
    return application_out(item, db)

@app.get("/v1/documents")
def list_documents(kind: str | None = None, db: Session = Depends(db_for)):
    stmt = select(Document).where(Document.user_id == current_user(db).id)
    if kind: stmt = stmt.where(Document.kind == kind)
    return {"items": [doc_out(x) for x in db.scalars(stmt.order_by(Document.updated_at.desc())).all()]}

@app.post("/v1/documents", status_code=201)
def create_document(body: DocumentCreate, db: Session = Depends(db_for)):
    validate_document(body.template, body.content, body.layout)
    if body.job_id is not None and db.get(Job, body.job_id) is None: not_found()
    item = Document(user_id=current_user(db).id, title=body.title, template=body.template,
                    content=body.content, layout=body.layout, revision=1, job_id=body.job_id)
    db.add(item); db.flush()
    return doc_out(item)

@app.get("/v1/documents/{document_id}")
def get_document(document_id: UUID, db: Session = Depends(db_for)):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id).with_for_update())
    if item is None: not_found()
    return doc_out(item)

@app.patch("/v1/documents/{document_id}")
def patch_document(document_id: UUID, body: DocumentPatch, db: Session = Depends(db_for)):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id).with_for_update())
    if item is None: not_found()
    if item.revision != body.expected_revision: raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Document changed"})
    changes = body.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    template = changes.get("template", item.template); content = changes.get("content", item.content); layout = changes.get("layout", item.layout)
    validate_document(template, content, layout)
    for key, value in changes.items(): setattr(item, key, value)
    item.revision += 1; item.reviewed_revision = None; item.updated_at = now_utc()
    return doc_out(item)

@app.post("/v1/documents/{document_id}/duplicate", status_code=201)
def duplicate_document(document_id: UUID, body: DuplicateWrite, db: Session = Depends(db_for)):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id))
    if item is None: not_found()
    if body.job_id and db.get(Job, body.job_id) is None: not_found()
    copy = Document(user_id=item.user_id, title=body.title or f"{item.title} copy", kind=item.kind,
                    template=item.template, content=item.content, layout=item.layout, revision=1, job_id=body.job_id)
    db.add(copy); db.flush()
    return doc_out(copy)

@app.post("/v1/documents/{document_id}/review")
def review_document(document_id: UUID, body: DocumentReview, db: Session = Depends(db_for)):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id).with_for_update())
    if item is None: not_found()
    if body.expected_revision != item.revision: raise HTTPException(409, detail={"code": "REVISION_CONFLICT", "message": "Document changed"})
    item.reviewed_revision = item.revision
    return doc_out(item)

def owned_document(document_id: UUID, db: Session) -> Document:
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id))
    if item is None: not_found()
    return item

@app.get("/v1/documents/{document_id}/preview.pdf")
def preview_document(document_id: UUID, db: Session = Depends(db_for)):
    return Response(pdf_bytes(owned_document(document_id, db)), media_type="application/pdf",
                    headers={"Content-Disposition": "inline; filename=resume-preview.pdf"})

@app.post("/v1/documents/{document_id}/exports", status_code=201)
def export_document(document_id: UUID, db: Session = Depends(db_for)):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == current_user(db).id).with_for_update())
    if item is None: not_found()
    if item.reviewed_revision != item.revision:
        raise HTTPException(409, detail={"code": "REVIEW_REQUIRED", "message": "Review the current revision before export"})
    export_id = uuid4()
    directory = Path(settings.pdf_storage_dir).resolve(); directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{current_user(db).id}-{export_id}.pdf"
    path.write_bytes(pdf_bytes(item))
    db.add(DocumentExport(id=export_id, user_id=current_user(db).id, document_id=item.id,
                          revision=item.revision, file_path=str(path)))
    db.flush()
    return {"export_id": str(export_id), "revision": item.revision, "download_url": f"/v1/exports/{export_id}"}

@app.get("/v1/exports/{export_id}")
def download_export(export_id: UUID, db: Session = Depends(db_for)):
    item = db.scalar(select(DocumentExport).where(DocumentExport.id == export_id, DocumentExport.user_id == current_user(db).id))
    if item is None: not_found()
    path = Path(item.file_path)
    if not path.is_file(): not_found()
    return Response(path.read_bytes(), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="resume-r{item.revision}.pdf"'})

@app.post("/v1/uploads", status_code=201)
def upload_resume(body: UploadCreate, db: Session = Depends(db_for)):
    if body.content_type != "application/pdf" or not body.filename.lower().endswith(".pdf"):
        raise HTTPException(422, detail={"code": "UNSUPPORTED_FILE", "message": "Upload a PDF resume"})
    upload_id = uuid4(); directory = Path(settings.pdf_storage_dir).resolve().parent / "uploads"; directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{current_user(db).id}-{upload_id}.pdf"
    upload = Upload(id=upload_id, user_id=current_user(db).id, filename=Path(body.filename).name,
                    content_type=body.content_type, declared_size=body.size_bytes,
                    file_path=str(path)); db.add(upload); db.flush()
    return {"upload_id": str(upload_id), "upload_url": f"/v1/uploads/{upload_id}/content", "fields": {}, "expires_at": None}

@app.put("/v1/uploads/{upload_id}/content")
async def save_upload_content(upload_id: UUID, request: Request, db: Session = Depends(db_for)):
    item = db.scalar(select(Upload).where(Upload.id == upload_id, Upload.user_id == current_user(db).id).with_for_update())
    if item is None: not_found()
    if item.sha256 is not None:
        raise HTTPException(409, detail={"code": "UPLOAD_IMMUTABLE", "message": "This upload has already been captured"})
    parts = []
    total_size = 0
    async for chunk in request.stream():
        total_size += len(chunk)
        if total_size > min(item.declared_size, 10 * 1024 * 1024):
            raise HTTPException(413, detail={"code": "UPLOAD_TOO_LARGE", "message": "PDF exceeds its declared size or the 10 MiB limit"})
        parts.append(chunk)
    data = b"".join(parts)
    if total_size != item.declared_size:
        raise HTTPException(422, detail={"code": "SIZE_MISMATCH", "message": "Uploaded byte count does not match the declared size"})
    if not data.startswith(b"%PDF-"):
        raise HTTPException(422, detail={"code": "INVALID_PDF", "message": "PDF must be valid and at most 10 MiB"})
    Path(item.file_path).write_bytes(data)
    item.sha256 = hashlib.sha256(data).hexdigest()
    parsed = inspect_pdf(data)
    item.status = parsed["status"]
    item.page_count = parsed["page_count"]
    item.extracted_text = parsed["text"]
    item.error_code = parsed["error_code"]
    return {"upload_id": str(item.id), "status": item.status, "page_count": item.page_count,
            "error_code": item.error_code,
            "message": "Extracted text is a review candidate only; verify it and enter profile facts manually.",
            "ai_available": False}

@app.get("/v1/uploads/{upload_id}")
def get_upload(upload_id: UUID, db: Session = Depends(db_for)):
    item = db.scalar(select(Upload).where(Upload.id == upload_id, Upload.user_id == current_user(db).id))
    if item is None: not_found()
    return {"upload_id": str(item.id), "filename": item.filename, "status": item.status,
            "page_count": item.page_count, "extracted_text": item.extracted_text,
            "error_code": item.error_code, "sha256": item.sha256}
