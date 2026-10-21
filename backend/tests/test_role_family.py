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
    # Added 2026-10-20 after the 457-listing run left 23% as "other": common titles from the wider employer set
    ("Senior Tax Manager", "finance"),
    ("Senior Metals Trader", "finance"),
    ("Portfolio Manager", "finance"),
    # Added 2026-10-20: "financial" is not a substring of "finance"; a Financial Analyst profile had no role check
    ("Financial Analyst", "finance"),
    ("FP&A Analyst", "finance"),
    ("Senior Financial Planning Manager", "finance"),
    ("Financial Reporting Analyst", "finance"),
    ("Financial Crime Compliance Analyst", "legal"),
    ("Account Executive, Financial Institutions", "sales"),
    ("Data Scientist, Financial Services", "data"),
    ("People Solutions Partner", "people"),
    ("Head of Total Rewards, Global", "people"),
    ("Product Director, VIP Products", "product"),
    ("Head of Product, Insurance", "product"),
    ("Key Account Director", "sales"),
    ("Head of Commercial, ShopBack Pay", "sales"),
    ("Regional CRM Manager", "marketing"),
    ("Manager, Public Affairs", "marketing"),
    ("Network Architect", "engineering"),
    ("Database Administrator", "engineering"),
    ("Specialist Solutions Architect, Payments", "customer_success"),
    ("Implementation Consultant (SEA/GCN)", "customer_success"),
    ("Enterprise Support Specialist", "customer_success"),
    ("Procurement Executive", "operations"),
    ("Merchant Onboarding Manager", "operations"),
    ("Senior CDD Risk Analyst", "legal"),
    ("Controls & Governance Manager - OKX SG", "legal"),
    ("Tech Governance - Security Compliance & Governance Engineer", "engineering"),
    ("Product Builder Intern (Product Engineering)", "engineering"),
    # the old behaviour must survive the additions
    ("Technical Support Engineer", "engineering"),
    ("Trading Systems Engineer", "engineering"),
    ("Syntax Engineer", "engineering"),
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


# ---- engineering sub-roles (added 2026-10-20) ----------------------------------------------------------------------
from job_hunter.role_family import classify_engineering_subrole  # noqa: E402


@pytest.mark.parametrize("title,subrole", [
    ("Senior Software Engineer, Backend", "backend"),
    ("Engineer, Backend (Payments)", "backend"),
    ("Technical Support Engineer, Metronome", "support"),
    ("Staff/Senior Staff Frontend Engineer - Growth", "frontend"),
    ("Full Stack Engineer", "fullstack"),
    ("iOS Developer", "mobile"),
    ("Software Engineer (Android)", "mobile"),
    ("DevOps Engineer", "infra"),
    ("Quality Assurance Engineer", "qa"),
    ("Application Security Engineer", "security"),
    # a title that names no sub-role has none (unknown, never blocks)
    ("Software Engineer", None),
    ("Senior Staff Engineer, Payment", None),
    ("Audio Engineer", None),
    ("", None),
])
def test_engineering_subrole(title, subrole):
    assert classify_engineering_subrole(title) == subrole
