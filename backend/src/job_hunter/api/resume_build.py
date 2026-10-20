"""Thin routes for building a resume from the profile bank.

The logic lives in ``job_hunter.profile_bank.build`` as pure functions; these
routes load the caller's data, call them and save the result.
"""
from typing import Annotated, Literal, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.orm import Session

from job_hunter.domain.models import Document, Job
from job_hunter.profile_bank import services
from job_hunter.profile_bank.build import (
    BuildError,
    STRATEGY_KEYWORD_V1,
    effective_defaults,
    plan_to_document,
    suggest_plan,
)
from job_hunter.profile_bank.schema import BankModel


class PointPick(BankModel):
    bullet_id: str = Field(min_length=1, max_length=200)
    alternative_id: str | None = Field(default=None, max_length=200)


class PlanItem(BankModel):
    item_id: UUID
    angle_id: str | None = Field(default=None, max_length=200)  # Reserved for angles; not used yet.
    picks: list[PointPick] = Field(default_factory=list, max_length=30)


class ItemsSection(BankModel):
    kind: Literal["experience", "education", "projects", "custom", "certifications", "awards", "volunteering"]
    items: list[PlanItem] = Field(default_factory=list, max_length=50)


class SkillsSection(BankModel):
    kind: Literal["skills"]
    skill_ids: list[UUID] = Field(default_factory=list, max_length=50)


class SummaryPlan(BankModel):
    mode: Literal["profile", "custom"] = "profile"
    text: str | None = Field(default=None, max_length=5000)


class BuildPlan(BankModel):
    title: str = Field(min_length=1, max_length=240)
    template: Literal["classic", "modern"] | None = None  # None: the user's default template
    job_id: UUID | None = None
    summary: SummaryPlan = Field(default_factory=SummaryPlan)
    sections: list[Annotated[Union[ItemsSection, SkillsSection], Field(discriminator="kind")]] = Field(
        default_factory=list, max_length=30)


class SuggestRequest(BankModel):
    job_id: UUID
    points_per_item: int | None = Field(default=None, ge=1, le=30)


def _job_for_ranking(job: Job) -> dict:
    return {"id": str(job.id), "title": job.title, "company": job.company, "category": job.category,
            "description": job.description, "skills": job.skills}


def _raise(error: BuildError):
    raise HTTPException(error.status, detail={"code": error.code, "message": error.message})


def build_router(db_dependency, *, validate_document, doc_out):
    router = APIRouter(prefix="/v1")

    @router.post("/documents/from-bank", status_code=201)
    def create_from_bank(body: BuildPlan, db: Session = Depends(db_dependency, scope="function")):
        if body.job_id is not None and db.get(Job, body.job_id) is None:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Resource not found"})
        bank = services.get_bank(db)
        stored_defaults = services.get_settings(db)["resume_defaults"]
        try:
            built = plan_to_document(body.model_dump(mode="json"), bank, bank["basics"], stored_defaults)
        except BuildError as error:
            _raise(error)
        validate_document(built["template"], built["content"], built["layout"], db)
        document = Document(user_id=db.info["current_user"].id, title=built["title"],
                            template=built["template"], content=built["content"],
                            layout=built["layout"], revision=1, job_id=body.job_id)
        db.add(document)
        db.flush()
        return doc_out(document)

    @router.post("/resume-builds/suggest")
    def suggest(body: SuggestRequest, db: Session = Depends(db_dependency, scope="function")):
        job = db.get(Job, body.job_id)
        if job is None:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Resource not found"})
        stored_defaults = services.get_settings(db)["resume_defaults"]
        chosen = effective_defaults(stored_defaults)
        try:
            return suggest_plan(
                _job_for_ranking(job), services.get_bank(db), STRATEGY_KEYWORD_V1,
                body.points_per_item or chosen["build"]["points_per_item"],
                template=chosen["template"], defaults=chosen,
                include_profile_summary=chosen["build"]["include_profile_summary"])
        except BuildError as error:
            _raise(error)

    return router
