from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, String, Text, UniqueConstraint, and_, or_, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    auth_subject: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    draft: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    bank_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    profile_epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    confirmed_revision: Mapped[int | None] = mapped_column(Integer)
    basics_provenance: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class ProfileVersion(Base):
    __tablename__ = "profile_versions"
    __table_args__ = (UniqueConstraint("user_id", "revision", name="uq_profile_version_user_revision"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(512))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    embedding_dims: Mapped[int | None] = mapped_column(Integer)
    embedding_text_version: Mapped[str | None] = mapped_column(Text)
    embedding_status: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Preference(Base):
    __tablename__ = "preferences"
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "source_board", "external_id", name="uq_job_source_board_external"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    work_mode: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="synthetic", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    skills: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255))
    dedup_key: Mapped[str | None] = mapped_column(String(500), unique=True)
    source_board: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    category: Mapped[str | None] = mapped_column(String(40))
    category_source: Mapped[str | None] = mapped_column(String(40))
    category_evidence: Mapped[str | None] = mapped_column(String(120))
    # Seniority levels named by the job (ladder: intern, junior, mid, senior, lead, executive); [] = names no level (open to
    # all levels), NULL = not classified yet. Set at ingestion by job_hunter.seniority, like category.
    seniority: Mapped[list | None] = mapped_column(JSON)
    seniority_source: Mapped[str | None] = mapped_column(String(40))
    seniority_evidence: Mapped[str | None] = mapped_column(String(120))
    salary_min: Mapped[float | None]
    salary_max: Mapped[float | None]
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(30))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(512))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    # Cross-source de-duplication (job_hunter/ingestion/dedup.py). Each source keeps its own row; rows that are the same posting are
    # linked. canonical_job_id is NULL on the row users see and the canonical row's id on its duplicates; also_seen_on lists, on
    # the canonical row, the other sources of the same posting; match_key is normalised employer + title + location.
    canonical_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    match_key: Mapped[str | None] = mapped_column(String(500), index=True)
    also_seen_on: Mapped[list | None] = mapped_column(JSON)


def listed_jobs(now: datetime | None = None, posted_after: datetime | None = None, include_closed: bool = False):
    """The jobs Discover shows: open, not past their closing date, and not a duplicate of another source's row.

    A pull closes expired and long-unseen jobs (import_jobs.close_unseen), but pulls are occasional, so the closing date is also
    checked here: a listing disappears on the day it expires, not at the next pull. ``posted_after`` is Discover's "Posted"
    filter; a job whose source gave no posting date always passes it. ``include_closed`` is Discover's "Include expired
    listings" switch: closed and expired jobs are listed too (duplicates never are)."""
    clause = Job.canonical_job_id.is_(None)
    if not include_closed:
        clause = and_(clause, Job.status == "open", or_(Job.expires_at.is_(None), Job.expires_at > (now or now_utc())))
    if posted_after is not None:
        clause = and_(clause, or_(Job.posted_at.is_(None), Job.posted_at >= posted_after))
    return clause


class JobReview(Base):
    __tablename__ = "job_reviews"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_job_review_user_job"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_application_user_job"),
        ForeignKeyConstraint(["resume_export_id", "user_id"], ["document_exports.id", "document_exports.user_id"],
                             name="fk_application_resume_export_owner"),
        ForeignKeyConstraint(["cover_letter_export_id", "user_id"], ["document_exports.id", "document_exports.user_id"],
                             name="fk_application_letter_export_owner"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="saved", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resume_export_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    resume_title: Mapped[str | None] = mapped_column(String(240))
    cover_letter_text: Mapped[str | None] = mapped_column(Text)
    cover_letter_export_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    cover_letter_title: Mapped[str | None] = mapped_column(String(240))
    packet_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("id", "user_id", name="uq_document_id_user"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default="resume", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    template: Mapped[str] = mapped_column(String(30), default="classic", nullable=False)
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    layout: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    reviewed_revision: Mapped[int | None] = mapped_column(Integer)
    job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("jobs.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class DocumentExport(Base):
    __tablename__ = "document_exports"
    __table_args__ = (UniqueConstraint("id", "user_id", name="uq_document_export_id_user"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AiTailorUse(Base):
    __tablename__ = "ai_tailor_uses"
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class JobRequirements(Base):
    """The requirements read from a posting by the language model; shared by every user and reused while the posting is unchanged."""
    __tablename__ = "job_requirements"
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    requirements: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class FitAnalysis(Base):
    """A user's latest fit analysis of one job. ``result`` is set once the app has checked the model's answer."""
    __tablename__ = "fit_analyses"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_fit_analysis_user_job"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    profile_revision: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Upload(Base):
    __tablename__ = "uploads"
    __table_args__ = (UniqueConstraint("id", "user_id", name="uq_upload_id_user"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    declared_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="uploaded", nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ProfileItem(Base):
    __tablename__ = "profile_items"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_profile_item_id_user"),
        CheckConstraint("kind IN ('experience','education','project','skill','certification','award','volunteering','custom')", name="ck_profile_item_kind"),
        CheckConstraint("origin IN ('manual','import')", name="ck_profile_item_origin"),
        ForeignKeyConstraint(["parent_id", "user_id"], ["profile_items.id", "profile_items.user_id"], name="fk_profile_item_parent_owner"),
        Index("ix_profile_items_user_kind", "user_id", "kind", "position"),
        Index("uq_profile_skill_name", "user_id", text("lower(data->>'name')"), unique=True,
              postgresql_where=text("kind = 'skill' AND archived_at IS NULL")),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}", nullable=False)
    origin: Mapped[str] = mapped_column(Text, default="manual", server_default="manual", nullable=False)
    import_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    parent_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, server_default=text("now()"), onupdate=now_utc)


class ProfileImport(Base):
    __tablename__ = "profile_imports"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_profile_import_id_user"),
        CheckConstraint("source_type IN ('upload','document','json_resume','text')", name="ck_profile_import_source"),
        CheckConstraint("status IN ('pending','ready','failed','applied','discarded')", name="ck_profile_import_status"),
        ForeignKeyConstraint(["upload_id", "user_id"], ["uploads.id", "uploads.user_id"], name="fk_profile_import_upload_owner"),
        ForeignKeyConstraint(["document_id", "user_id"], ["documents.id", "documents.user_id"], name="fk_profile_import_document_owner"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    upload_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    document_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    input_ref: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_payload: Mapped[dict | list | str | None] = mapped_column(JSONB)
    task_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    profile_epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending", nullable=False)
    parser: Mapped[str | None] = mapped_column(Text)
    candidates: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, server_default=text("now()"))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_result: Mapped[dict | None] = mapped_column(JSONB)


class UserSettings(Base):
    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("id", "user_id", name="uq_user_settings_id_user"),)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), default=uuid4, nullable=False)
    resume_defaults: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
