"""Validated profile-bank facts, independent of HTTP and persistence."""
from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .dates import is_profile_date

ITEM_KINDS = ("experience", "education", "project", "skill", "certification", "award", "volunteering", "custom")
MAX_ITEMS_PER_KIND = 50
MAX_BULLETS = 30
MAX_VERSIONS = 5  # Includes the main wording.
MAX_POINT_LENGTH = 4000


class BankModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(BankModel):
    source_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    page: int | None = Field(default=None, ge=1)
    text: str


class Provenance(BankModel):
    origin: Literal["import", "user"] = "user"
    import_id: str | None = None
    evidence: Evidence | None = None


class Alternative(BankModel):
    id: str = Field(default_factory=lambda: "v_" + uuid4().hex, min_length=1)
    text: str = Field(min_length=1, max_length=MAX_POINT_LENGTH)
    tags: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("point text cannot be blank")
        return value


class Bullet(Alternative):
    id: str = Field(default_factory=lambda: "b_" + uuid4().hex, min_length=1)
    alternatives: list[Alternative] = Field(default_factory=list, max_length=MAX_VERSIONS - 1)

    @model_validator(mode="after")
    def unique_versions(self):
        ids = [version.id for version in self.alternatives]
        if len(ids) != len(set(ids)) or self.id in ids:
            raise ValueError("version IDs must be unique within a point")
        return self


class AnglePick(BankModel):
    bullet_id: str
    alternative_id: str | None = None


class Angle(BankModel):
    id: str
    name: str
    title: str | None = None
    summary: str = ""
    picks: list[AnglePick] = Field(default_factory=list)


class ItemData(BankModel):
    bullets: list[Bullet] = Field(default_factory=list, max_length=MAX_BULLETS)
    tags: list[str] = Field(default_factory=list)
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    # Preserves the previous dict keys exactly during the one-off migration.
    legacy_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_bullets(self):
        ids = [bullet.id for bullet in self.bullets]
        if len(ids) != len(set(ids)):
            raise ValueError("point IDs must be unique within an item")
        return self


class DatedData(ItemData):
    start: str | None = None
    end: str | None = None
    current: bool = False
    dates_text: str | None = None

    @field_validator("start", "end")
    @classmethod
    def valid_date(cls, value):
        if value is not None and not is_profile_date(value):
            raise ValueError("dates must be YYYY or YYYY-MM")
        return value

    @model_validator(mode="after")
    def coherent_dates(self):
        if self.current and self.end is not None:
            raise ValueError("a current item cannot have an end date")
        if self.start and self.end:
            # Year-only values describe an interval, rather than January 1.
            if self.start[:4] > self.end[:4] or (
                len(self.start) == len(self.end) == 7 and self.start > self.end
            ):
                raise ValueError("end date cannot precede start date")
        return self


class ExperienceData(DatedData):
    title: str = Field(min_length=1)
    organisation: str = ""
    location: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    angles: list[Angle] = Field(default_factory=list)


class EducationData(DatedData):
    qualification: str = Field(min_length=1)
    institution: str = ""
    grade: str = ""


class ProjectData(DatedData):
    name: str = Field(min_length=1)
    role: str = ""
    url: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    angles: list[Angle] = Field(default_factory=list)


class SkillData(ItemData):
    name: str = Field(min_length=1)
    category: Literal["language", "framework", "tool", "domain", "soft"] = "tool"
    level: str = ""


class CertificationData(DatedData):
    name: str = Field(min_length=1)
    issuer: str = ""
    url: str = ""


class AwardData(DatedData):
    title: str = Field(min_length=1)
    awarder: str = ""
    summary: str = ""


class VolunteeringData(ExperienceData):
    pass


class CustomData(DatedData):
    title: str = Field(min_length=1)
    heading: str = ""
    summary: str = ""


ITEM_MODELS = dict(zip(ITEM_KINDS, (ExperienceData, EducationData, ProjectData, SkillData, CertificationData, AwardData, VolunteeringData, CustomData)))


def validate_item_data(kind: str, data: dict) -> dict:
    if kind not in ITEM_MODELS:
        raise ValueError("unknown profile item kind")
    return ITEM_MODELS[kind].model_validate(data).model_dump(mode="json", exclude_none=True)
