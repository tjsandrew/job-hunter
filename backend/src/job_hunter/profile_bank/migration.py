"""Deterministic, lossless transform for the legacy profile JSON."""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from .dates import normalize_dates
from .skills import infer_skill_category

LEGACY_KINDS = {"skills": "skill", "experience": "experience", "education": "education", "projects": "project"}


def migrate_legacy_profile(draft: dict, user_id) -> tuple[dict, list[dict]]:
    basics = deepcopy(draft)
    items = []
    for field, kind in LEGACY_KINDS.items():
        for position, source in enumerate(basics.pop(field, []) or []):
            source = deepcopy(source)
            item_id = str(uuid5(NAMESPACE_URL, f"job-hunter/profile-bank/{user_id}/{kind}/{position}"))
            row = source if isinstance(source, dict) else {"name": str(source)}
            data = {"legacy_fields": row, "bullets": []}
            for index, point in enumerate(row.get("bullets", []) or []):
                bullet = deepcopy(point) if isinstance(point, dict) else {"text": str(point)}
                bullet.setdefault("id", "b_" + uuid5(NAMESPACE_URL, f"{item_id}/bullet/{index}").hex)
                bullet.setdefault("tags", [])
                bullet.setdefault("skills", [])
                bullet.setdefault("alternatives", [])
                data["bullets"].append(bullet)
            if kind == "skill":
                data.update(name=row.get("name", ""), category=row.get("category") or infer_skill_category(row.get("name", "")), level=row.get("level", ""))
            else:
                data.update(normalize_dates(row.get("dates")))
                for key in ("start", "end", "current", "dates_text"):
                    if key in row:
                        data[key] = deepcopy(row[key])
                if kind == "experience":
                    data.update(title=row.get("title", row.get("role", "")), organisation=row.get("organisation", row.get("company", "")), skills=row.get("skills", []), summary=row.get("summary", ""))
                elif kind == "education":
                    data.update(qualification=row.get("qualification", row.get("degree", "")), institution=row.get("institution", row.get("school", "")), grade=row.get("grade", ""))
                else:
                    data.update(name=row.get("name", ""), role=row.get("role", ""), url=row.get("url", ""), skills=row.get("skills", []), summary=row.get("summary", ""))
            items.append({"id": item_id, "kind": kind, "position": position, "data": data, "tags": row.get("tags", []), "origin": "manual", "revision": 1})
    return basics, items


def restore_legacy_profile(basics: dict, items: list[dict]) -> dict:
    from .snapshots import assemble_profile_snapshot
    result = assemble_profile_snapshot(basics, items, 0)
    result.pop("bank_revision", None)
    result.pop("bullets", None)
    return result
