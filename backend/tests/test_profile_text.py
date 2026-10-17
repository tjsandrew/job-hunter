import pytest

from job_hunter.embedding.profile_text import (
    MAX_TEXT_CHARS,
    PROFILE_TEXT_VERSION,
    ProfileTextInput,
    build_profile_text,
)


def snapshot(**overrides):
    base = {
        "name": "Alice Tan",
        "email": "alice.tan@example.com",
        "phone": "+65 9123 4567",
        "links": ["https://linkedin.com/in/alicetan"],
        "location": "Singapore",
        "headline": "Junior backend engineer",
        "summary": "Builds REST APIs and data services. Reach me at alice.tan@example.com.",
        "skills": ["Python", "SQL"],
        "experience": [
            {"role": "Backend Intern", "company": "Acme", "skills": ["Docker", "python"]},
            {"role": "Data Assistant", "company": "Beta", "skills": []},
        ],
        "projects": [{"name": "Job tracker", "skills": ["FastAPI"]}],
        "education": [{"degree": "BSc Computer Science", "school": "NUS"}],
        "bullets": [
            {"id": "1", "item_id": "a", "text": "Built an API serving 10k requests a day"},
            {"id": "2", "item_id": "a", "text": "Wrote SQL reports for the finance team"},
        ],
    }
    base.update(overrides)
    return base


def build(snap=None, roles=None):
    return build_profile_text(ProfileTextInput(snapshot=snap if snap is not None else snapshot(), target_roles=roles))


def test_labelled_layout_and_order():
    result = build(roles=["Backend Engineer", "Data Engineer"])
    assert result.version == PROFILE_TEXT_VERSION == "profile-v2"
    assert result.included == ("Target role", "Summary", "Demonstrated skills", "Roles", "Projects", "Highlights")
    lines = result.text.splitlines()
    assert lines[0] == "Target role: Backend Engineer; Data Engineer"
    assert lines[1].startswith("Summary: Junior backend engineer. Builds REST APIs and data services.")
    assert "Demonstrated skills: Python, SQL, Docker, FastAPI" in result.text
    assert "Roles: Backend Intern; Data Assistant" in result.text
    assert "Projects: Job tracker" in result.text
    assert "Highlights: Built an API serving 10k requests a day. Wrote SQL reports for the finance team." in result.text


def test_contact_details_are_removed_everywhere():
    snap = snapshot(summary="Alice Tan builds APIs in Singapore. Email alice.tan@example.com or call +65 9123 4567.",
                    bullets=[{"id": "1", "item_id": "a", "text": "Presented at https://linkedin.com/in/alicetan to Alice Tan's team"}])
    text = build(snap).text
    for leaked in ("alice.tan@example.com", "9123 4567", "linkedin.com", "Alice Tan"):
        assert leaked.lower() not in text.lower()


def test_education_is_not_included():
    text = build().text
    assert "Computer Science" not in text and "NUS" not in text


def test_skills_are_deduplicated_across_sections_case_insensitively():
    skills_line = next(l for l in build().text.splitlines() if l.startswith("Demonstrated skills"))
    assert skills_line.lower().count("python") == 1


def test_target_role_is_optional_and_changes_the_text():
    without = build()
    assert "Target role" not in without.text
    with_role = build(roles=["Backend Engineer"])
    assert with_role.text != without.text and with_role.text.startswith("Target role: Backend Engineer")


def test_target_roles_from_preferences_accept_lists_and_delimited_strings():
    snap = snapshot()
    from_list = ProfileTextInput.from_preferences(snap, {"target_roles": ["Backend Engineer", " backend engineer ", ""]})
    assert list(from_list.target_roles) == ["Backend Engineer"]
    from_text = ProfileTextInput.from_preferences(snap, {"roles": "Data Analyst; Data Engineer, Analyst"})
    assert list(from_text.target_roles) == ["Data Analyst", "Data Engineer", "Analyst"]
    for prefs in (None, {}, {"target_roles": None}):
        assert ProfileTextInput.from_preferences(snap, prefs).target_roles is None


def test_missing_pieces_are_simply_left_out():
    result = build(snapshot(summary=None, headline=None, projects=[], experience=[], bullets=[], skills=["Go"]))
    assert result.included == ("Demonstrated skills",)
    assert result.text == "Demonstrated skills: Go"


def test_headline_and_summary_that_match_are_not_repeated():
    result = build(snapshot(headline="Backend engineer", summary="backend engineer"))
    assert result.text.splitlines()[0].count("ackend engineer") == 1


def test_legacy_per_entry_bullets_are_used_when_no_flat_list_exists():
    snap = snapshot(bullets=None, experience=[{"role": "Intern", "skills": [],
                                                "bullets": ["Cleaned CSV data", {"text": "Automated a report"}]}])
    del snap["bullets"]
    assert "Highlights: Cleaned CSV data. Automated a report." in build(snap).text


def test_empty_profile_is_rejected_with_a_clear_message():
    with pytest.raises(ValueError, match="no confirmed content"):
        build({"name": "Alice Tan", "email": "alice@example.com"})
    with pytest.raises(ValueError):
        build({})


def test_deterministic_and_capped():
    assert build(roles=["Backend Engineer"]) == build(roles=["Backend Engineer"])
    big = snapshot(bullets=[{"id": str(i), "item_id": "a", "text": f"Delivered project number {i} on schedule"} for i in range(2500)])
    result = build(big)
    assert result.truncated is True and len(result.text) <= MAX_TEXT_CHARS
