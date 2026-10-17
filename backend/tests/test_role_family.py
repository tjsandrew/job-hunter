import pytest

from job_hunter.role_family import classify_role_family


@pytest.mark.parametrize("title,family", [
    # the occupation beats a domain word elsewhere in the title (the old ingestion classifier got these wrong)
    ("Technical Recruiter, Backend Engineering", "people"),
    ("Recruiter, Data Analytics", "people"),
    ("Recruiter, Technical Support", "people"),
    ("Principal Recruiter", "people"),
    ("SDC Business Recruiter (Fixed Term Contract)", "people"),
    ("Internal Auditor - APAC Regulatory & Financial Operations", "finance"),
    ("Product Counsel (Money Movement Legal - APAC)", "legal"),
    # the head of the title beats the team, product or region after it
    ("Account Executive, Product - Local Payment Methods", "sales"),
    ("Data Analyst, Recruiting Operations", "data"),
    ("Engineering Manager, Recruiting Platform", "engineering"),
    # unchanged from the old ingestion classifier
    ("Junior Backend Engineer", "engineering"),
    ("Senior Data Scientist", "data"),
    ("Customer Success Account Manager", "customer_success"),
    ("Product Manager, Global Self-Serve Product", "product"),
    ("Accountant", "finance"),
    ("Fraud Strategist", "other"),
    ("Entry-Level Business Insights Associate", "other"),
    ("", "other"),
    (None, "other"),
])
def test_role_family(title, family):
    assert classify_role_family(title)[0] == family


def test_evidence_is_the_matched_phrase():
    assert classify_role_family("Technical Recruiter, Backend Engineering") == ("people", "recruiter")
    assert classify_role_family("Fraud Strategist") == ("other", None)


def test_the_old_import_path_still_works():
    from job_hunter.embedding import role_family as old

    assert old.classify_role_family is classify_role_family
    assert old.CLASSIFIER_VERSION == "role-family-v1"
