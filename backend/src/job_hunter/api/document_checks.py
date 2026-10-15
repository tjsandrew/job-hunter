"""Server checks for the profile-bank fields a resume may carry.

All of these fields are optional, so documents written before the profile bank
existed keep validating. ``validate_document`` calls ``check_bank_fields``.
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_hunter.domain.models import ProfileItem
from job_hunter.profile_bank.build import LAYOUT_CHOICES, SECTION_KINDS
from job_hunter.profile_bank.dates import is_profile_date

MAX_ID_LENGTH = 200
MAX_POINT_LENGTH = 4000


def _invalid(message: str, code: str = "INVALID_CONTENT"):
    raise HTTPException(422, detail={"code": code, "message": message})


def _optional_id(value, label: str) -> None:
    if value is not None and (not isinstance(value, str) or not value or len(value) > MAX_ID_LENGTH):
        _invalid(f"{label} must be text or null")


def check_layout_choices(layout: dict) -> None:
    for key, allowed in LAYOUT_CHOICES.items():
        if key in layout and (not isinstance(layout[key], str) or layout[key] not in allowed):
            _invalid(f"{key} must be one of: {', '.join(allowed)}", "INVALID_LAYOUT")


def _check_source(source) -> UUID:
    if not isinstance(source, dict):
        _invalid("source must be an object")
    try:
        item_id = UUID(str(source.get("item_id")))
    except ValueError:
        _invalid("source.item_id must be an item ID")
    revision = source.get("item_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        _invalid("source.item_revision must be a whole number")
    _optional_id(source.get("angle_id"), "source.angle_id")
    return item_id


def _check_date_range(date_range) -> None:
    if not isinstance(date_range, dict):
        _invalid("date_range must be an object")
    for key in ("start", "end"):
        value = date_range.get(key)
        if value is not None and (not isinstance(value, str) or not is_profile_date(value)):
            _invalid(f"date_range.{key} must be YYYY, YYYY-MM or null")
    if not isinstance(date_range.get("current", False), bool):
        _invalid("date_range.current must be true or false")


def _check_bullet_sources(entry: dict) -> None:
    sources = entry["bullet_sources"]
    if not isinstance(sources, list) or len(sources) != len(entry.get("bullets", [])):
        _invalid("bullet_sources must be a list with one item per bullet")
    for source in sources:
        if source is None:
            continue
        if not isinstance(source, dict):
            _invalid("Each bullet source must be an object or null")
        if not isinstance(source.get("bullet_id"), str) or not source["bullet_id"] or len(source["bullet_id"]) > MAX_ID_LENGTH:
            _invalid("bullet_sources[].bullet_id must be text")
        _optional_id(source.get("alternative_id"), "bullet_sources[].alternative_id")
        base_text = source.get("base_text")
        if not isinstance(base_text, str) or len(base_text) > MAX_POINT_LENGTH:
            _invalid("bullet_sources[].base_text must be text up to 4000 characters")


def _entry_source_ids(content: dict) -> set[UUID]:
    """Check the shape of every bank field and return the item IDs the entries point to."""
    item_ids: set[UUID] = set()
    for section in content.get("sections", []):
        if "kind" in section and (not isinstance(section["kind"], str) or section["kind"] not in SECTION_KINDS):
            _invalid(f"Section kind must be one of: {', '.join(SECTION_KINDS)}")
        if "hidden" in section and not isinstance(section["hidden"], bool):
            _invalid("Section hidden must be true or false")
        for entry in section.get("entries", []):
            if entry.get("source") is not None:
                item_ids.add(_check_source(entry["source"]))
            if entry.get("date_range") is not None:
                _check_date_range(entry["date_range"])
            if entry.get("bullet_sources") is not None:
                _check_bullet_sources(entry)
    return item_ids


def _stored_source_ids(content) -> set[UUID]:
    """Item IDs already stored in a resume; reads without validating."""
    found: set[UUID] = set()
    sections = content.get("sections") if isinstance(content, dict) else None
    for section in sections if isinstance(sections, list) else []:
        entries = section.get("entries") if isinstance(section, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            source = entry.get("source") if isinstance(entry, dict) else None
            if isinstance(source, dict):
                try:
                    found.add(UUID(str(source.get("item_id"))))
                except ValueError:
                    pass
    return found


def check_bank_fields(content: dict, layout: dict, db: Session | None = None,
                      existing_content: dict | None = None) -> None:
    """Validate section kinds, point sources, date ranges and layout choices.

    With ``db``, each ``source.item_id`` must be one of the caller's own items
    (archived ones count; a foreign ID is hidden by row-level security and so
    reads as missing). IDs already in ``existing_content`` are not looked up again, so
    a resume whose profile item was deleted can still be edited.
    """
    check_layout_choices(layout)
    item_ids = _entry_source_ids(content)
    if db is None or not item_ids:
        return
    if existing_content:
        item_ids -= _stored_source_ids(existing_content)
    if not item_ids:
        return
    owned = set(db.scalars(select(ProfileItem.id).where(
        ProfileItem.id.in_(item_ids), ProfileItem.user_id == db.info["current_user"].id)))
    if item_ids - owned:
        _invalid("An entry points to a profile item that does not exist", "INVALID_SOURCE")
