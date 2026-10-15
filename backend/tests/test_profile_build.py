"""Pure tests for building resumes from the profile bank (no database)."""
from copy import deepcopy

import pytest

from job_hunter.api.document_checks import check_bank_fields
from job_hunter.profile_bank.build import (
    BuildError,
    blank_document_parts,
    effective_defaults,
    plan_to_document,
    suggest_plan,
)
from job_hunter.profile_bank.dates import DATE_FORMATS, PRESENT_LABELS, format_date, format_date_range

BASICS = {"name": "Alex Tan", "email": "alex@example.invalid", "phone": "+65 5550 0100",
          "location": "Singapore", "summary": "Backend engineer who likes data."}


def item(item_id, kind, data, revision=1, tags=None):
    return {"id": item_id, "kind": kind, "data": data, "tags": tags or [], "revision": revision,
            "position": 0, "archived_at": None}


def point(point_id, text, tags=(), skills=(), alternatives=()):
    return {"id": point_id, "text": text, "tags": list(tags), "skills": list(skills),
            "alternatives": [dict(version) for version in alternatives]}


def make_bank():
    items = [
        item("00000000-0000-4000-8000-0000000000a1", "experience", {
            "title": "Data & Backend Engineer", "organisation": "Harbour Metrics", "location": "Singapore",
            "start": "2023-07", "end": None, "current": True, "skills": ["Python", "PostgreSQL"],
            "bullets": [
                point("b_api", "Built FastAPI services and PostgreSQL data models.", ["backend"],
                      ["PostgreSQL"], alternatives=[{
                          "id": "v_docker", "tags": [], "skills": [],
                          "text": "Shipped Python APIs on PostgreSQL with Docker based releases."}]),
                point("b_sql", "Designed incremental SQL pipelines with quality checks.", ["data"], []),
                point("b_team", "Introduced testing and Docker workflows for the team.", ["leadership"], []),
                point("b_lunch", "Organised weekly team lunches.", [], []),
            ]}, revision=4),
        item("00000000-0000-4000-8000-0000000000a2", "experience", {
            "title": "Backend Developer", "organisation": "Old Co", "start": "2021", "end": "2022",
            "current": False, "skills": ["Python"],
            "bullets": [point("b_old", "Maintained Python batch jobs.", [], ["Python"])]}),
        item("00000000-0000-4000-8000-0000000000a3", "experience", {
            "title": "Retail Associate", "organisation": "Shop", "start": "2019", "end": "2020",
            "bullets": [point("b_shop", "Served customers at the till.")]}),
        item("00000000-0000-4000-8000-0000000000a4", "project", {"name": "Job pipeline", "skills": ["Python", "PostgreSQL"],
                                       "bullets": [point("b_proj", "Loaded postings into PostgreSQL.", [], ["PostgreSQL"])]}),
        item("00000000-0000-4000-8000-0000000000a5", "project", {"name": "Pottery blog", "bullets": [point("b_pot", "Wrote about clay.")]}),
        item("00000000-0000-4000-8000-0000000000a6", "education", {"qualification": "BSc Computer Science", "institution": "NUS",
                                  "start": "2018-08", "end": "2022-05", "grade": "Honours",
                                  "bullets": [point("b_edu", "Databases focus.")]}),
        item("00000000-0000-4000-8000-0000000000b1", "skill", {"name": "Python", "category": "language"}),
        item("00000000-0000-4000-8000-0000000000b2", "skill", {"name": "SQL", "category": "language"}),
        item("00000000-0000-4000-8000-0000000000b3", "skill", {"name": "PostgreSQL", "category": "tool"}),
        item("00000000-0000-4000-8000-0000000000b4", "skill", {"name": "Docker", "category": "tool"}),
        item("00000000-0000-4000-8000-0000000000b5", "skill", {"name": "Excel", "category": "tool"}),
        item("00000000-0000-4000-8000-0000000000c1", "custom", {"title": "Community interests", "heading": "Volunteer",
                                    "bullets": [point("b_c", "Organise coding meetups.")]}),
    ]
    return {"basics": BASICS, "items": items}


JOB = {"id": "11111111-1111-4111-8111-111111111111", "title": "Senior Backend Engineer",
       "company": "Meridian Labs", "category": "backend",
       "description": "Build APIs and data services with a collaborative team.",
       "skills": ["Python", "PostgreSQL", "Docker", "Kubernetes"]}


def picks_for(suggestion, kind, item_id):
    section = next(section for section in suggestion["plan"]["sections"] if section["kind"] == kind)
    return next(row for row in section["items"] if row["item_id"] == item_id)["picks"]


# --- suggest_plan -----------------------------------------------------------

def test_suggestion_orders_experience_newest_first_and_leaves_out_unmatched_items():
    suggestion = suggest_plan(JOB, make_bank())
    experience = next(section for section in suggestion["plan"]["sections"] if section["kind"] == "experience")
    assert [row["item_id"] for row in experience["items"]] == ["00000000-0000-4000-8000-0000000000a1", "00000000-0000-4000-8000-0000000000a2"]
    projects = next(section for section in suggestion["plan"]["sections"] if section["kind"] == "projects")
    assert [row["item_id"] for row in projects["items"]] == ["00000000-0000-4000-8000-0000000000a4"]
    assert suggestion["strategy"] == "keyword-v1"


def test_points_are_capped_best_first_and_unrelated_points_are_left_out():
    bank = make_bank()
    four = [pick["bullet_id"] for pick in picks_for(suggest_plan(JOB, bank, points_per_item=4), "experience", "00000000-0000-4000-8000-0000000000a1")]
    assert four[0] == "b_api"
    assert "b_lunch" not in four and len(four) <= 4
    one = suggest_plan(JOB, bank, points_per_item=1)
    assert all(len(row["picks"]) <= 1 for section in one["plan"]["sections"] if section["kind"] != "skills"
               for row in section["items"])
    two = picks_for(suggest_plan(JOB, bank, points_per_item=2), "experience", "00000000-0000-4000-8000-0000000000a1")
    assert len(two) == 2


def test_a_better_matching_version_is_chosen_and_explained():
    suggestion = suggest_plan(JOB, make_bank())
    first = picks_for(suggestion, "experience", "00000000-0000-4000-8000-0000000000a1")[0]
    assert first == {"bullet_id": "b_api", "alternative_id": "v_docker"}
    reasons = suggestion["reasons"]["00000000-0000-4000-8000-0000000000a1:b_api"]
    assert any(reason.startswith("matches") and "Docker" in reason and "PostgreSQL" in reason for reason in reasons)
    assert "tagged backend" in reasons
    assert any("version" in reason for reason in reasons)


def test_main_wording_is_kept_when_no_version_scores_higher():
    bank = make_bank()
    bank["items"][0]["data"]["bullets"][0]["alternatives"][0]["text"] = "Wrote some code."
    first = picks_for(suggest_plan(JOB, bank), "experience", "00000000-0000-4000-8000-0000000000a1")[0]
    assert first == {"bullet_id": "b_api"}


def test_item_reasons_are_concrete():
    reasons = suggest_plan(JOB, make_bank())["reasons"]
    assert reasons["00000000-0000-4000-8000-0000000000a1"][0] == "matches Python, PostgreSQL"
    assert reasons["00000000-0000-4000-8000-0000000000a2"][0] == "matches Python"
    assert reasons["00000000-0000-4000-8000-0000000000a4"][0].startswith("matches")
    assert reasons["00000000-0000-4000-8000-0000000000a6"] == ["education is included by default"]
    assert reasons["00000000-0000-4000-8000-0000000000b1"] == ["listed in the job requirements"]
    assert "00000000-0000-4000-8000-0000000000b5" not in reasons


def test_coverage_lists_job_skills_found_and_missing_in_the_bank():
    coverage = suggest_plan(JOB, make_bank())["coverage"]
    assert coverage == {"covered": ["Python", "PostgreSQL", "Docker"], "missing": ["Kubernetes"]}


def test_coverage_counts_skills_listed_on_items_and_points():
    bank = make_bank()
    bank["items"] = [row for row in bank["items"] if row["kind"] != "skill"]
    assert "Python" in suggest_plan(JOB, bank)["coverage"]["covered"]  # from item.skills
    bank["items"][0]["data"]["bullets"][0]["skills"] = ["Kubernetes"]
    assert "Kubernetes" in suggest_plan(JOB, bank)["coverage"]["covered"]  # from a point


def test_skills_section_lists_matching_skills_first():
    suggestion = suggest_plan(JOB, make_bank())
    skills = next(section for section in suggestion["plan"]["sections"] if section["kind"] == "skills")
    assert skills["skill_ids"][:3] == ["00000000-0000-4000-8000-0000000000b1", "00000000-0000-4000-8000-0000000000b3", "00000000-0000-4000-8000-0000000000b4"]
    assert skills["skill_ids"][-1] == "00000000-0000-4000-8000-0000000000b5" or skills["skill_ids"][-1] == "00000000-0000-4000-8000-0000000000b2"
    assert set(skills["skill_ids"]) == {"00000000-0000-4000-8000-0000000000b1", "00000000-0000-4000-8000-0000000000b2", "00000000-0000-4000-8000-0000000000b3", "00000000-0000-4000-8000-0000000000b4", "00000000-0000-4000-8000-0000000000b5"}


def test_skill_aliases_match_like_recommendations_do():
    bank = make_bank()
    job = {**JOB, "skills": ["Postgres", "Amazon Web Services"]}
    suggestion = suggest_plan(job, bank)
    assert suggestion["coverage"] == {"covered": ["Postgres"], "missing": ["Amazon Web Services"]}
    assert suggestion["reasons"]["00000000-0000-4000-8000-0000000000a1"][0].startswith("matches")


def test_job_with_no_match_still_suggests_most_recent_roles():
    job = {"id": JOB["id"], "title": "Pastry Chef", "company": "Bakery", "skills": ["Baking"],
           "description": "Bake bread."}
    suggestion = suggest_plan(job, make_bank())
    experience = next(section for section in suggestion["plan"]["sections"] if section["kind"] == "experience")
    assert [row["item_id"] for row in experience["items"]] == ["00000000-0000-4000-8000-0000000000a1", "00000000-0000-4000-8000-0000000000a2"]
    assert "most recent" in suggestion["reasons"]["00000000-0000-4000-8000-0000000000a1"][0]
    assert suggestion["coverage"] == {"covered": [], "missing": ["Baking"]}


def test_plan_shape_title_template_and_section_order_from_defaults():
    defaults = {"template": "modern", "sections": [{"kind": "skills"}, {"kind": "experience"}]}
    suggestion = suggest_plan(JOB, make_bank(), template="modern", defaults=defaults)
    plan = suggestion["plan"]
    assert plan["title"] == "Senior Backend Engineer – Meridian Labs"
    assert plan["template"] == "modern" and plan["job_id"] == JOB["id"]
    assert plan["summary"] == {"mode": "profile"}
    assert [section["kind"] for section in plan["sections"]] == ["skills", "experience", "education", "projects"]
    no_summary = suggest_plan(JOB, make_bank(), include_profile_summary=False)["plan"]["summary"]
    assert no_summary == {"mode": "custom", "text": ""}


def test_suggestion_is_deterministic_and_leaves_the_bank_untouched():
    bank = make_bank()
    before = deepcopy(bank)
    assert suggest_plan(JOB, bank) == suggest_plan(JOB, bank)
    assert bank == before


def test_empty_bank_gives_an_empty_plan_and_all_skills_missing():
    suggestion = suggest_plan(JOB, {"basics": {}, "items": []})
    assert suggestion["plan"]["sections"] == []
    assert suggestion["coverage"]["covered"] == [] and len(suggestion["coverage"]["missing"]) == 4


def test_unknown_strategy_is_rejected():
    with pytest.raises(BuildError) as error:
        suggest_plan(JOB, make_bank(), strategy="embedding-v1")
    assert error.value.status == 422


# --- plan_to_document -------------------------------------------------------

def basic_plan():
    return {"title": "Backend Engineer – Meridian", "template": "classic", "job_id": JOB["id"],
            "summary": {"mode": "profile"}, "sections": [
                {"kind": "experience", "items": [{"item_id": "00000000-0000-4000-8000-0000000000a1", "picks": [
                    {"bullet_id": "b_api", "alternative_id": "v_docker"}, {"bullet_id": "b_sql"}]}]},
                {"kind": "education", "items": [{"item_id": "00000000-0000-4000-8000-0000000000a6", "picks": []}]},
                {"kind": "skills", "skill_ids": ["00000000-0000-4000-8000-0000000000b2", "00000000-0000-4000-8000-0000000000b3", "00000000-0000-4000-8000-0000000000b1"]}]}


def test_document_entries_carry_source_dates_and_bullet_sources():
    document = plan_to_document(basic_plan(), make_bank(), BASICS, {})
    content = document["content"]
    experience = content["sections"][0]
    assert experience["kind"] == "experience" and experience["title"] == "Experience"
    entry = experience["entries"][0]
    assert entry["heading"] == "Data & Backend Engineer"
    assert entry["subheading"] == "Harbour Metrics · Singapore"
    assert entry["source"] == {"item_id": "00000000-0000-4000-8000-0000000000a1", "item_revision": 4}
    assert entry["date_range"] == {"start": "2023-07", "end": None, "current": True}
    assert entry["dates"] == "Jul 2023 – Present"
    # The chosen version's wording is copied, and the profile text at that moment is remembered.
    assert entry["bullets"] == ["Shipped Python APIs on PostgreSQL with Docker based releases.",
                                "Designed incremental SQL pipelines with quality checks."]
    assert entry["bullet_sources"] == [
        {"bullet_id": "b_api", "alternative_id": "v_docker", "base_text": entry["bullets"][0]},
        {"bullet_id": "b_sql", "base_text": entry["bullets"][1]}]
    assert len(entry["bullet_sources"]) == len(entry["bullets"])
    assert document["title"] == "Backend Engineer – Meridian" and document["job_id"] == JOB["id"]


def test_contact_and_summary_come_from_profile_basics():
    content = plan_to_document(basic_plan(), make_bank(), BASICS, {})["content"]
    assert (content["name"], content["email"], content["phone"], content["location"]) == (
        "Alex Tan", "alex@example.invalid", "+65 5550 0100", "Singapore")
    assert content["summary"] == BASICS["summary"]
    plan = {**basic_plan(), "summary": {"mode": "custom", "text": "Tailored summary."}}
    assert plan_to_document(plan, make_bank(), BASICS, {})["content"]["summary"] == "Tailored summary."


def test_skills_become_grouped_lines_by_category():
    skills = plan_to_document(basic_plan(), make_bank(), BASICS, {})["content"]["sections"][2]
    assert skills["kind"] == "skills" and skills["title"] == "Skills"
    assert [(entry["heading"], entry["bullets"]) for entry in skills["entries"]] == [
        ("Languages", ["SQL, Python"]), ("Tools", ["PostgreSQL"])]
    assert all("source" not in entry for entry in skills["entries"])


def test_education_and_custom_entries():
    plan = {**basic_plan(), "sections": [
        {"kind": "education", "items": [{"item_id": "00000000-0000-4000-8000-0000000000a6", "picks": [{"bullet_id": "b_edu"}]}]},
        {"kind": "custom", "items": [{"item_id": "00000000-0000-4000-8000-0000000000c1", "picks": [{"bullet_id": "b_c"}]}]},
        {"kind": "projects", "items": [{"item_id": "00000000-0000-4000-8000-0000000000a4", "picks": []}]}]}
    sections = plan_to_document(plan, make_bank(), BASICS, {})["content"]["sections"]
    education = sections[0]["entries"][0]
    assert education["heading"] == "BSc Computer Science" and education["subheading"] == "NUS · Honours"
    assert education["dates"] == "Aug 2018 – May 2022"
    assert education["date_range"] == {"start": "2018-08", "end": "2022-05", "current": False}
    custom = sections[1]["entries"][0]
    assert (custom["heading"], custom["subheading"]) == ("Community interests", "Volunteer")
    assert "date_range" not in custom and custom["dates"] == ""
    assert sections[1]["title"] == "Additional information"
    assert sections[2]["kind"] == "projects" and sections[2]["entries"][0]["heading"] == "Job pipeline"


def test_defaults_set_layout_titles_and_header_fields():
    defaults = {"template": "modern",
                "layout": {"date_format": "07/2023", "present_label": "Now", "accent_color": "teal"},
                "sections": [{"kind": "skills", "title": "Technical skills"},
                             {"kind": "experience", "title": "Work history"}],
                "header_fields": ["email"]}
    plan = {**basic_plan(), "template": None}
    document = plan_to_document(plan, make_bank(), BASICS, defaults)
    assert document["template"] == "modern"
    assert document["layout"]["accent_color"] == "teal" and document["layout"]["font_size"] == 11
    assert document["layout"]["heading_style"] == "rule"  # missing keys fall back to built-in defaults
    sections = document["content"]["sections"]
    assert [section["title"] for section in sections] == ["Work history", "Education", "Technical skills"]
    assert sections[0]["entries"][0]["dates"] == "07/2023 – Now"
    content = document["content"]
    assert content["email"] == "alex@example.invalid" and content["phone"] == "" and content["location"] == ""
    explicit = plan_to_document(basic_plan(), make_bank(), BASICS, defaults)
    assert explicit["template"] == "classic"  # the plan's own choice wins


def test_no_defaults_use_the_built_in_layout():
    layout = plan_to_document(basic_plan(), make_bank(), BASICS, {})["layout"]
    assert layout["date_format"] == "Jul 2023" and layout["present_label"] == "Present"
    assert layout["font_size"] == 11 and layout["margin"] == 18


def test_built_documents_pass_the_server_checks():
    document = plan_to_document(basic_plan(), make_bank(), BASICS, {})
    check_bank_fields(document["content"], document["layout"])


def test_suggested_plan_builds_a_document():
    suggestion = suggest_plan(JOB, make_bank())
    document = plan_to_document(suggestion["plan"], make_bank(), BASICS, {})
    assert [section["kind"] for section in document["content"]["sections"]] == [
        "experience", "education", "projects", "skills"]


@pytest.mark.parametrize("plan_change, status, code", [
    ({"sections": [{"kind": "experience", "items": [{"item_id": "missing", "picks": []}]}]}, 404, "NOT_FOUND"),
    ({"sections": [{"kind": "experience", "items": [{"item_id": "00000000-0000-4000-8000-0000000000a1", "picks": [{"bullet_id": "nope"}]}]}]}, 404, "NOT_FOUND"),
    ({"sections": [{"kind": "experience", "items": [{"item_id": "00000000-0000-4000-8000-0000000000a1", "picks": [
        {"bullet_id": "b_api", "alternative_id": "nope"}]}]}]}, 404, "NOT_FOUND"),
    ({"sections": [{"kind": "experience", "items": [{"item_id": "00000000-0000-4000-8000-0000000000a6", "picks": []}]}]}, 422, "INVALID_PLAN"),
    ({"sections": [{"kind": "experience", "items": [{"item_id": "00000000-0000-4000-8000-0000000000a1", "picks": [
        {"bullet_id": "b_api"}, {"bullet_id": "b_api", "alternative_id": "v_docker"}]}]}]}, 422, "INVALID_PLAN"),
    ({"sections": [{"kind": "skills", "skill_ids": ["missing"]}]}, 404, "NOT_FOUND"),
    ({"sections": [{"kind": "skills", "skill_ids": ["00000000-0000-4000-8000-0000000000a1"]}]}, 422, "INVALID_PLAN"),
])
def test_bad_plans_are_rejected_without_a_partial_document(plan_change, status, code):
    with pytest.raises(BuildError) as error:
        plan_to_document({**basic_plan(), **plan_change}, make_bank(), BASICS, {})
    assert (error.value.status, error.value.code) == (status, code)


def test_archived_items_are_missing_from_the_bank_and_so_rejected():
    bank = make_bank()
    bank["items"] = [row for row in bank["items"] if row["id"] != "00000000-0000-4000-8000-0000000000a1"]
    with pytest.raises(BuildError) as error:
        plan_to_document(basic_plan(), bank, BASICS, {})
    assert error.value.status == 404


def test_building_does_not_change_the_bank():
    bank = make_bank()
    before = deepcopy(bank)
    plan_to_document(basic_plan(), bank, BASICS, {})
    assert bank == before


# --- dates ------------------------------------------------------------------

@pytest.mark.parametrize("date_format, expected", [
    ("Jul 2023", "Jul 2023"), ("July 2023", "July 2023"), ("07/2023", "07/2023"), ("2023", "2023")])
def test_every_date_format(date_format, expected):
    assert format_date("2023-07", date_format) == expected
    assert format_date("2023", date_format) == "2023"  # no month to show


@pytest.mark.parametrize("present_label", PRESENT_LABELS)
@pytest.mark.parametrize("date_format", DATE_FORMATS)
def test_current_range_uses_the_present_label(date_format, present_label):
    text = format_date_range({"start": "2023-07", "end": None, "current": True}, date_format, present_label)
    assert text == f"{format_date('2023-07', date_format)} – {present_label}"


def test_ranges_with_end_unknown_or_missing():
    assert format_date_range({"start": "2022-01", "end": "2023-06", "current": False}, "July 2023") == "January 2022 – June 2023"
    assert format_date_range({"start": "2022", "end": None, "current": False}) == "2022"  # end unknown
    assert format_date_range({"start": None, "end": None, "current": False}) == ""
    assert format_date_range(None) == ""
    assert format_date("not a date") == ""


# --- blank resumes and defaults --------------------------------------------

def test_blank_resume_gets_basics_and_default_sections():
    stored = {"template": "modern", "layout": {"date_format": "2023"},
              "sections": [{"kind": "experience", "title": "Work"},
                           {"kind": "custom", "title": "Fun facts", "hidden": True},
                           {"kind": "award"}],
              "header_fields": ["email", "location"]}
    template, content, layout = blank_document_parts(None, {"name": "", "sections": []}, None, BASICS, stored)
    assert template == "modern"
    assert layout == {"font_size": 11, "margin": 18, "date_format": "2023"}
    assert (content["name"], content["email"], content["location"]) == ("Alex Tan", "alex@example.invalid", "Singapore")
    assert "phone" not in content or content["phone"] == ""
    assert content["summary"] == BASICS["summary"]
    assert [(s["title"], s["kind"], s.get("hidden", False)) for s in content["sections"]] == [
        ("Work", "experience", False), ("Fun facts", "custom", True), ("Awards", "awards", False)]
    assert all(section["entries"] == [] and section["id"] for section in content["sections"])


def test_blank_resume_keeps_what_the_client_sent():
    sections = [{"id": "s1", "title": "Mine", "entries": []}]
    template, content, layout = blank_document_parts(
        "classic", {"name": "Typed Name", "summary": "Typed", "sections": sections}, {"font_size": 12},
        BASICS, {"template": "modern", "layout": {"font_size": 10, "accent_color": "navy"}})
    assert template == "classic" and layout == {"font_size": 12, "margin": 18, "accent_color": "navy"}
    assert content["name"] == "Typed Name" and content["summary"] == "Typed"
    assert content["email"] == "alex@example.invalid"


def test_without_saved_defaults_a_blank_resume_only_gains_profile_details():
    template, content, layout = blank_document_parts(None, {"sections": []}, None, BASICS, {})
    assert (template, layout) == ("classic", {"font_size": 11, "margin": 18})
    assert content["sections"] == [] and content["name"] == "Alex Tan"


def test_resume_with_entries_is_a_copy_and_is_left_alone():
    original = {"name": "", "sections": [{"id": "s", "title": "T", "entries": [{"id": "e", "bullets": []}]}]}
    template, content, layout = blank_document_parts(None, original, None, BASICS,
                                                    {"template": "modern", "layout": {"font_size": 9}})
    assert content == original and template == "classic" and layout == {"font_size": 11, "margin": 18}


def test_invalid_stored_defaults_are_ignored():
    assert effective_defaults({"layout": {"heading_style": "nonsense"}})["layout"]["heading_style"] == "rule"
    template, _content, layout = blank_document_parts(None, {"sections": []}, None, {}, {"template": "nonsense"})
    assert template == "classic" and layout == {"font_size": 11, "margin": 18}


def test_both_spellings_of_newline_are_accepted_in_defaults():
    for spelling in ("newline", "new line"):
        assert effective_defaults({"layout": {"contact_separator": spelling}})["layout"]["contact_separator"] == spelling


# --- certifications, awards and volunteering --------------------------------

CERT_ID = "00000000-0000-4000-8000-0000000000d1"
AWARD_ID = "00000000-0000-4000-8000-0000000000d2"
VOLUNTEER_ID = "00000000-0000-4000-8000-0000000000d3"
OTHER_CERT_ID = "00000000-0000-4000-8000-0000000000d4"


def bank_with_extras():
    bank = make_bank()
    bank["items"] += [
        item(CERT_ID, "certification", {"name": "Docker Certified Associate", "issuer": "Example Academy",
                                        "start": "2022-03", "bullets": []}),
        item(OTHER_CERT_ID, "certification", {"name": "Pottery Level 2", "issuer": "Clay Guild", "bullets": []}),
        item(AWARD_ID, "award", {"title": "Hackathon winner", "awarder": "City Council", "start": "2021", "bullets": []}),
        item(VOLUNTEER_ID, "volunteering", {"title": "Mentor", "organisation": "Code Club", "location": "Singapore",
                                            "start": "2020-01", "end": "2021-12",
                                            "bullets": [point("b_vol", "Taught Python to teenagers.")]}),
    ]
    return bank


def extras_plan():
    return {**basic_plan(), "sections": [
        {"kind": "certifications", "items": [{"item_id": CERT_ID, "picks": []}]},
        {"kind": "awards", "items": [{"item_id": AWARD_ID, "picks": []}]},
        {"kind": "volunteering", "items": [{"item_id": VOLUNTEER_ID, "picks": [{"bullet_id": "b_vol"}]}]}]}


def test_new_section_kinds_map_item_fields_to_entries():
    document = plan_to_document(extras_plan(), bank_with_extras(), BASICS, {})
    sections = document["content"]["sections"]
    assert [(s["kind"], s["title"]) for s in sections] == [
        ("certifications", "Certifications"), ("awards", "Awards"), ("volunteering", "Volunteering")]
    certification, award, volunteering = (s["entries"][0] for s in sections)
    assert (certification["heading"], certification["subheading"], certification["dates"]) == (
        "Docker Certified Associate", "Example Academy", "Mar 2022")
    assert certification["source"] == {"item_id": CERT_ID, "item_revision": 1} and certification["bullets"] == []
    assert (award["heading"], award["subheading"], award["dates"]) == ("Hackathon winner", "City Council", "2021")
    assert (volunteering["heading"], volunteering["subheading"]) == ("Mentor", "Code Club")
    assert volunteering["dates"] == "Jan 2020 – Dec 2021"
    assert volunteering["bullets"] == ["Taught Python to teenagers."]
    assert volunteering["bullet_sources"] == [{"bullet_id": "b_vol", "base_text": "Taught Python to teenagers."}]
    check_bank_fields(document["content"], document["layout"])


def test_new_section_kinds_reject_items_of_another_kind():
    plan = {**basic_plan(), "sections": [{"kind": "awards", "items": [{"item_id": CERT_ID, "picks": []}]}]}
    with pytest.raises(BuildError) as error:
        plan_to_document(plan, bank_with_extras(), BASICS, {})
    assert (error.value.status, error.value.code) == (422, "INVALID_PLAN")


def test_default_sections_for_the_new_kinds_set_titles():
    defaults = {"sections": [{"kind": "certification", "title": "Licences"}, {"kind": "award"}, {"kind": "volunteering"}]}
    sections = plan_to_document(extras_plan(), bank_with_extras(), BASICS, defaults)["content"]["sections"]
    assert [s["title"] for s in sections] == ["Licences", "Awards", "Volunteering"]


def test_suggestion_includes_matching_certifications_only():
    suggestion = suggest_plan(JOB, bank_with_extras())
    section = next(s for s in suggestion["plan"]["sections"] if s["kind"] == "certifications")
    assert [row["item_id"] for row in section["items"]] == [CERT_ID]
    assert suggestion["reasons"][CERT_ID]
    kinds = [s["kind"] for s in suggestion["plan"]["sections"]]
    assert kinds[-1] == "certifications" and "awards" not in kinds and "volunteering" not in kinds
    assert plan_to_document(suggestion["plan"], bank_with_extras(), BASICS, {})["content"]["sections"][-1]["kind"] == "certifications"


def test_suggestion_without_a_matching_certification_has_no_section():
    assert "certifications" not in [s["kind"] for s in suggest_plan(JOB, make_bank())["plan"]["sections"]]


def test_document_checks_accept_the_new_kinds_and_reject_unknown_ones():
    for kind in ("certifications", "awards", "volunteering"):
        check_bank_fields({"sections": [{"id": "s", "title": "T", "kind": kind, "entries": []}]}, {})
    with pytest.raises(Exception) as error:
        check_bank_fields({"sections": [{"id": "s", "title": "T", "kind": "hobbies", "entries": []}]}, {})
    assert getattr(error.value, "status_code", None) == 422
