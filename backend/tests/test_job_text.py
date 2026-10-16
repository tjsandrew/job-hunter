from types import SimpleNamespace

import pytest

from job_hunter.embedding.job_text import (
    JOB_TEXT_VERSION,
    MAX_TEXT_CHARS,
    SECTIONS_TEXT_VERSION,
    TOLERANT_SECTIONS_TEXT_VERSION,
    JobTextInput,
    build_job_text,
    section_stats,
)

STRIPE_LIKE = """About Acme
Acme is a global company that builds financial infrastructure for the internet.
About the team
Our team is friendly and we love lunch.
What you�ll do
� Design and build backend services that process payments at scale
� Work with product managers to ship reliable APIs
Responsibilities
Own the reliability of the services you build and respond to incidents.
Who you are
We�re looking for engineers who enjoy solving hard problems.
Minimum requirements
� 3+ years of experience building production software
� Strong knowledge of Python or Java and SQL
Preferred qualifications
� Experience with distributed systems
Annual base salary range (excluding equity and bonus)
$100,000 - $150,000
#LI-Remote
Equal opportunity
Acme is an equal opportunity employer. Contact careers@acme.example or https://acme.example/jobs.
"""


def text_of(version=SECTIONS_TEXT_VERSION, **kwargs):
    """Most tests below describe the heading-based format, so it is the helper's default (job-v1)."""
    return build_job_text(JobTextInput(**kwargs), version=version)


def test_title_only_gives_just_the_role_line():
    result = text_of(title="  Backend   Engineer ")
    assert result.text == "Role: Backend Engineer"
    assert result.included == ("Role",)
    assert result.version == SECTIONS_TEXT_VERSION == "job-v1"
    assert result.used_sections is False and result.truncated is False
    assert build_job_text(JobTextInput(title="  Backend   Engineer ")).version == JOB_TEXT_VERSION == "job-v2"


@pytest.mark.parametrize("title", ["", "   ", None])
def test_blank_title_is_rejected(title):
    with pytest.raises(ValueError):
        build_job_text(JobTextInput(title=title))


def test_skills_are_deduplicated_cleaned_and_optional():
    result = text_of(title="Engineer", skills=["Python", " python ", "", "SQL", "Python"])
    assert "Stated skills: Python, SQL" in result.text
    assert "Stated skills" in result.included
    for empty in (None, [], ["", "  "]):
        assert "Stated skills" not in text_of(title="Engineer", skills=empty).text


def test_known_sections_are_kept_and_boilerplate_dropped():
    result = text_of(title="Backend Engineer", description=STRIPE_LIKE)
    assert result.used_sections is True
    assert result.included == ("Role", "Work", "Requirements")
    work = result.text.split("Work: ", 1)[1].split("\nRequirements: ", 1)[0]
    requirements = result.text.split("Requirements: ", 1)[1]
    assert "Design and build backend services" in work
    assert "Own the reliability" in work
    assert "3+ years" in requirements and "distributed systems" in requirements
    assert "engineers who enjoy solving hard problems" in requirements
    for dropped in ("global company", "friendly", "$100,000", "equal opportunity", "careers@",
                    "acme.example", "#LI-Remote", "lunch"):
        assert dropped.lower() not in result.text.lower()


def test_garbled_apostrophe_headings_and_bullets_are_handled():
    result = text_of(title="Engineer", description=STRIPE_LIKE)
    assert "�" not in result.text
    assert "Design and build backend services that process payments at scale." in result.text


def test_company_is_never_part_of_the_text():
    job = SimpleNamespace(title="Backend Engineer", description=None, skills=None, company="Acme Corp")
    result = build_job_text(JobTextInput.from_job(job))
    assert "Acme" not in result.text
    record = {"title": "Backend Engineer", "description": "Build APIs.", "skills": ["Go"], "company": "Acme"}
    assert "Acme" not in build_job_text(JobTextInput.from_job(record)).text


def test_description_without_known_sections_falls_back_to_full_text():
    description = "We are hiring a backend developer.\nYou will build APIs   and\n\nmaintain data services."
    result = text_of(title="Developer", description=description)
    assert result.used_sections is False
    assert result.included == ("Role", "Description")
    assert result.text.endswith(
        "Description: We are hiring a backend developer. You will build APIs and. maintain data services.")


def test_tiny_extraction_falls_back_to_full_text():
    description = "Responsibilities\nBuild things.\nAbout us\nWe are a company with a long story to tell about ourselves."
    result = text_of(title="Developer", description=description)
    assert result.used_sections is False
    assert "Description:" in result.text and "long story" in result.text


def test_missing_or_blank_description_is_fine():
    for description in (None, "", "   \n  "):
        result = text_of(title="Developer", description=description)
        assert result.included == ("Role",)


def test_output_is_deterministic():
    first = text_of(title="Backend Engineer", description=STRIPE_LIKE, skills=["Python"])
    second = text_of(title="Backend Engineer", description=STRIPE_LIKE, skills=["Python"])
    assert first == second


def test_very_long_text_is_capped_and_flagged():
    long_requirements = "Requirements\n" + "\n".join(f"Skill number {i} is needed for this role" for i in range(2000))
    result = text_of(title="Engineer", description="Responsibilities\nBuild.\n" + long_requirements)
    assert result.truncated is True
    assert len(result.text) <= MAX_TEXT_CHARS


def test_about_the_role_is_kept_but_other_about_sections_are_not():
    description = ("About the role\nYou will lead the design of our data platform for many teams across the company.\n"
                   "About Acme\nAcme was founded in 2010 by people who care about quality.\n"
                   "Requirements\nDeep experience with SQL and Python in production environments.")
    result = text_of(title="Data Engineer", description=description)
    assert "lead the design of our data platform" in result.text
    assert "founded in 2010" not in result.text


# ---- job-v2 (the default: whole description) and job-v3 (tolerant headings) ------------------------
def v2(**kwargs):
    return build_job_text(JobTextInput(**kwargs))


def test_default_format_keeps_the_whole_description_and_nothing_is_dropped_by_headings():
    result = v2(title="Backend Engineer", description=STRIPE_LIKE, skills=["Python"])
    assert result.version == "job-v2" and result.used_sections is False
    assert result.included == ("Role", "Stated skills", "Description")
    text = result.text
    for kept in ("global company", "Design and build backend services", "3+ years", "distributed systems", "friendly"):
        assert kept in text                      # boilerplate stays too: that is the trade-off of the default
    for cleaned in ("careers@", "https://", "�"):
        assert cleaned not in text               # but links, emails and replacement characters are still cleaned


def test_default_format_with_no_description_is_just_the_role_and_skills():
    assert v2(title="Developer").text == "Role: Developer"
    assert v2(title="Developer", description="  ", skills=["Go"]).text == "Role: Developer\nStated skills: Go"


def test_default_format_is_capped_and_deterministic():
    description = "\n".join(f"Line number {i} describes some of the work." for i in range(3000))
    first, second = v2(title="Engineer", description=description), v2(title="Engineer", description=description)
    assert first == second and first.truncated is True and len(first.text) <= MAX_TEXT_CHARS


def test_unknown_version_is_rejected():
    with pytest.raises(ValueError):
        build_job_text(JobTextInput(title="x"), version="job-v9")


RUN_TOGETHER = """AboutStripe
Stripe is a financial infrastructure platform for businesses with a very long company story.
Aboutthe team
The Payments team owns critical payment flows and likes to talk about itself at length here.
Whatyou'll do
Build and operate the services that move money for millions of businesses around the world.
Whoyou are
You have strong experience with Python, SQL and distributed systems in production settings.
"""


def test_tolerant_headings_find_sections_even_when_spaces_are_missing():
    strict = build_job_text(JobTextInput(title="Engineer", description=RUN_TOGETHER), version=SECTIONS_TEXT_VERSION)
    tolerant = build_job_text(JobTextInput(title="Engineer", description=RUN_TOGETHER),
                              version=TOLERANT_SECTIONS_TEXT_VERSION)
    assert strict.used_sections is False                       # none of the run-together headings match
    assert tolerant.used_sections is True and tolerant.included == ("Role", "Work", "Requirements")
    assert "move money" in tolerant.text and "distributed systems" in tolerant.text
    assert "company story" not in tolerant.text and "talk about itself" not in tolerant.text


def test_tolerant_format_falls_back_to_the_whole_description_unless_both_parts_are_found():
    only_work = ("About the team\nWe are a friendly team with a long history of building things together.\n"
                 "What you'll do\n" + "Build and run reliable services for our customers every day. " * 4)
    strict = build_job_text(JobTextInput(title="Engineer", description=only_work), version=SECTIONS_TEXT_VERSION)
    tolerant = build_job_text(JobTextInput(title="Engineer", description=only_work),
                              version=TOLERANT_SECTIONS_TEXT_VERSION)
    assert strict.used_sections is True and "friendly team" not in strict.text      # job-v1 silently drops the intro
    assert tolerant.used_sections is False and "friendly team" in tolerant.text    # job-v3 keeps everything


def test_section_stats_reports_what_heading_detection_found():
    good = section_stats(STRIPE_LIKE)
    assert good.used_sections is True and good.fallback_reason is None and 0 < good.kept_share < 1
    none_found = section_stats("We are hiring a backend developer.\nYou will build APIs and maintain services.")
    assert none_found.used_sections is False and none_found.fallback_reason == "no recognisable heading"
    assert section_stats(None).fallback_reason == "no description"
    missing = section_stats(RUN_TOGETHER.replace("Whoyou are", "Something else"), tolerant=True)
    assert missing.used_sections is False and missing.fallback_reason == "requirements section missing"
