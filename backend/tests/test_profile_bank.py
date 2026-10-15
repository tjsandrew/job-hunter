"""Pure bank contracts: no HTTP, database or model calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_hunter.demo import LEGACY_PROFILE as PROFILE, PROFILE as BASICS, PROFILE_ITEMS
from job_hunter.profile_bank.dates import normalize_date, normalize_dates
from job_hunter.profile_bank.migration import migrate_legacy_profile, restore_legacy_profile
from job_hunter.profile_bank.schema import Bullet, ITEM_MODELS, validate_item_data
from job_hunter.profile_bank.skills import infer_skill_category
from job_hunter.profile_bank.snapshots import assemble_profile_snapshot, profile_embedding_text

FIXTURES = Path(__file__).parent / "fixtures"
USER = "11111111-1111-1111-1111-111111111111"


@pytest.mark.parametrize("value,expected", [("2023", "2023"), ("2023-07", "2023-07"), ("July 2023", "2023-07"), ("Jul 2023", "2023-07"), ("07/2023", "2023-07"), ("2023-13", None), ("0000", None), ("last summer", None)])
def test_normalize_date(value, expected):
    assert normalize_date(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("2023–Present", {"start": "2023", "end": None, "current": True}),
    ("Jul 2022 – Jun 2023", {"start": "2022-07", "end": "2023-06", "current": False}),
    ("2018-2022", {"start": "2018", "end": "2022", "current": False}),
    (None, {"start": None, "end": None, "current": False}),
])
def test_normalize_range(value, expected):
    assert normalize_dates(value) == expected


def test_unknown_dates_preserve_source():
    assert normalize_dates("During university")["dates_text"] == "During university"
    assert normalize_dates("summer 2021 – autumn 2022")["dates_text"] == "summer 2021 – autumn 2022"


@pytest.mark.parametrize("kind,data", [
    ("experience", {"title": "Engineer"}), ("education", {"qualification": "BSc"}),
    ("project", {"name": "Pipeline"}), ("skill", {"name": "Python"}),
    ("certification", {"name": "Certificate"}), ("award", {"title": "Award"}),
    ("volunteering", {"title": "Mentor"}), ("custom", {"title": "Fun facts"}),
])
def test_all_kind_models(kind, data):
    result = validate_item_data(kind, data)
    assert result["bullets"] == []
    assert kind in ITEM_MODELS


@pytest.mark.parametrize("data", [
    {"text": ""}, {"text": "   "}, {"text": "x" * 4001},
    {"text": "Main", "alternatives": [{"id": f"v_{i}", "text": "Other"} for i in range(5)]},
    {"id": "b_1", "text": "Main", "alternatives": [{"id": "b_1", "text": "Other"}]},
    {"text": "Main", "alternatives": [{"id": "v_1", "text": "Other"}, {"id": "v_1", "text": "Another"}]},
])
def test_point_limits(data):
    with pytest.raises(ValidationError):
        Bullet.model_validate(data)


def test_boundaries_and_provenance():
    bullet = Bullet.model_validate({"text": "x" * 4000, "alternatives": [{"id": f"v_{i}", "text": "Other"} for i in range(4)], "tags": ["backend"], "skills": ["Python"], "provenance": {"origin": "import", "import_id": "import-1", "evidence": {"source_sha256": "a" * 64, "page": 1, "text": "Original"}}})
    assert len(bullet.alternatives) == 4
    assert bullet.provenance.evidence.text == "Original"
    validate_item_data("project", {"name": "Project", "bullets": [{"id": f"b_{i}", "text": "Point"} for i in range(30)]})
    with pytest.raises(ValidationError):
        validate_item_data("project", {"name": "Project", "bullets": [{"text": "Point"} for _ in range(31)]})
    with pytest.raises(ValidationError):
        validate_item_data("project", {"name": "Project", "bullets": [{"id": "same", "text": "Point"}] * 2})


@pytest.mark.parametrize("dates", [{"start": "2023-99"}, {"current": True, "end": "2024"}, {"start": "2025", "end": "2024"}])
def test_invalid_structured_dates(dates):
    with pytest.raises(ValidationError):
        validate_item_data("experience", {"title": "Engineer", **dates})


def test_migration_is_stable_and_preserves_legacy_shape():
    draft = deepcopy(PROFILE)
    draft["experience"][0]["bullets"] = ["Built APIs", "Led a team"]
    draft["education"][0]["dates"] = "During university"
    basics, items = migrate_legacy_profile(draft, USER)
    assert not any(key in basics for key in ("skills", "experience", "education", "projects"))
    assert (basics, items) == migrate_legacy_profile(draft, USER)
    assert len({item["id"] for item in items}) == len(items)
    assert len({point["id"] for item in items for point in item["data"]["bullets"]}) == 2
    assert next(item for item in items if item["kind"] == "education")["data"]["dates_text"] == "During university"
    assert restore_legacy_profile(basics, items) == draft
    assert draft["experience"][0]["bullets"] == ["Built APIs", "Led a team"]


def test_snapshot_fixture_empty():
    assert assemble_profile_snapshot({}, [], 0) == json.loads((FIXTURES / "profile_snapshot_empty.json").read_text())


def test_snapshot_fixture_demo():
    assert assemble_profile_snapshot(BASICS, PROFILE_ITEMS, 1) == json.loads((FIXTURES / "profile_snapshot_demo.json").read_text())


def test_snapshot_fixture_versions():
    basics = {"headline": "Backend Engineer", "summary": "Builds reliable services"}
    items = [{"id": "22222222-2222-2222-2222-222222222222", "kind": "experience", "position": 0, "data": {"title": "Engineer", "organisation": "Fictional Labs", "start": "2023-07", "end": None, "current": True, "skills": ["Python"], "bullets": [{"id": "b_backend", "text": "Built reliable APIs", "tags": ["backend"], "skills": ["Python"], "alternatives": [{"id": "v_impact", "text": "Helped teams release safely", "tags": ["leadership"]}], "provenance": {"origin": "user"}}]}}]
    snapshot = assemble_profile_snapshot(basics, items, 2)
    assert snapshot == json.loads((FIXTURES / "profile_snapshot_versions.json").read_text())
    assert "alternatives" not in snapshot["bullets"][0]
    assert "provenance" not in snapshot["bullets"][0]
    assert "Helped teams" not in profile_embedding_text(snapshot)


def test_snapshot_archived_and_order():
    items = [{"id": str(i), "kind": "skill", "position": position, "data": {"name": name}, "archived_at": archived} for i, position, name, archived in [(1, 5, "SQL", None), (2, 1, "Python", None), (3, 0, "Archived", "2026-10-14")]]
    assert assemble_profile_snapshot({}, items, 3)["skills"] == ["Python", "SQL"]


@pytest.mark.parametrize("name, expected", [("Python", "language"), ("  sql ", "language"), ("FastAPI", "framework"),
                                            ("scikit-learn", "framework"), ("PostgreSQL", "tool"), ("Docker", "tool"),
                                            ("Mentoring", "soft"), ("Data modelling", "domain"), ("", "domain")])
def test_infer_skill_category(name, expected):
    assert infer_skill_category(name) == expected


def test_legacy_skills_get_inferred_categories_unless_given():
    _, items = migrate_legacy_profile({"skills": ["Python", "Docker", {"name": "Go", "category": "tool"}]}, "u")
    assert [item["data"]["category"] for item in items] == ["language", "tool", "tool"]


def test_embedding_excludes_contacts_even_when_repeated_in_summary():
    snapshot = {"name": "Jordan Example", "display_name": "Jordan Example", "email": "jordan@example.invalid", "phone": "+65 6123 4567", "location": "Fictional City", "links": [{"url": "https://example.invalid/portfolio"}], "headline": "Backend Engineer", "summary": "Jordan Example builds Python APIs in Fictional City. jordan@example.invalid +65 6123 4567 https://example.invalid/portfolio", "skills": ["Python"], "experience": [{"role": "Engineer", "company": "Jordan Example", "location": "Fictional City", "skills": ["SQL"]}], "bullets": [{"text": "Built backend APIs", "alternatives": [{"text": "Excluded version"}], "provenance": {"evidence": {"text": "Excluded evidence"}}}]}
    text = profile_embedding_text(snapshot)
    for excluded in ("Jordan Example", "jordan@example.invalid", "+65 6123 4567", "Fictional City", "https://example.invalid/portfolio", "Excluded version", "Excluded evidence"):
        assert excluded not in text
    for included in ("Backend Engineer", "Python", "SQL", "Built backend APIs"):
        assert included in text
    assert profile_embedding_text(snapshot) == text
