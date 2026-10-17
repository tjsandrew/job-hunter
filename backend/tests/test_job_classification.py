from job_hunter.job_classification import classify_job
from job_hunter.role_family import CLASSIFIER_VERSION
from job_hunter.seniority import SENIORITY_STATED, SENIORITY_VERSION


def test_classify_job_returns_database_values_from_title():
    values = classify_job("Senior Backend Engineer")
    assert values == {
        "category": "engineering",
        "category_source": CLASSIFIER_VERSION,
        "category_evidence": "engineer",
        "seniority": ["senior"],
        "seniority_source": SENIORITY_VERSION,
        "seniority_evidence": "Senior",
    }


def test_source_stated_seniority_overrides_title():
    values = classify_job("Senior Backend Engineer", stated_seniority="Junior")
    assert values["seniority"] == ["junior"]
    assert values["seniority_source"] == SENIORITY_STATED
    assert values["seniority_evidence"] == "Junior"
