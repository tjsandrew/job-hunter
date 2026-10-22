from job_hunter.preparation.tailoring import tailor

JOB = {"title": "Data Engineer", "skills": ["Python", "SQL", "Airflow"], "description": "Build SQL pipelines in Python."}


def content(*bullets, sources=None):
    entry = {"id": "e1", "heading": "Engineer", "subheading": "Acme", "dates": "", "bullets": list(bullets)}
    if sources:
        entry["bullet_sources"] = sources
    return {"summary": "", "sections": [{"id": "s1", "title": "Experience", "entries": [entry]}]}


def test_relevant_bullets_move_first_and_ties_keep_order():
    result, _ = tailor(content("Ran team lunches", "Wrote SQL pipelines in Python", "Organised events"), JOB)
    assert result["sections"][0]["entries"][0]["bullets"] == ["Wrote SQL pipelines in Python", "Ran team lunches", "Organised events"]


def test_bullet_sources_follow_their_bullets_and_input_is_unchanged():
    original = content("Ran lunches", "Used SQL", sources=[{"id": "a"}, {"id": "b"}])
    result, _ = tailor(original, JOB)
    entry = result["sections"][0]["entries"][0]
    assert entry["bullets"] == ["Used SQL", "Ran lunches"] and entry["bullet_sources"] == [{"id": "b"}, {"id": "a"}]
    assert original["sections"][0]["entries"][0]["bullets"] == ["Ran lunches", "Used SQL"]


def test_matched_and_missing_skills_use_aliases():
    _, keywords = tailor(content("Built postgres dashboards", "Wrote python and structured query language"), JOB)
    assert keywords == {"matched": ["Python", "SQL"], "missing": ["Airflow"]}


def test_job_without_keywords_changes_nothing():
    source = content("b", "a")
    result, keywords = tailor(source, {"title": "", "description": None, "skills": []})
    assert result == source and keywords == {"matched": [], "missing": []}


def test_ordering_uses_skill_aliases():
    result, _ = tailor(content("Git", "Postgres"), {"title": "", "skills": ["PostgreSQL"]})
    assert result["sections"][0]["entries"][0]["bullets"] == ["Postgres", "Git"]
