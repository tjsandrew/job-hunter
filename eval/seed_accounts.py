"""Create the staging evaluation accounts and give each a fictional, confirmed profile.

Accounts use example.com addresses (a reserved domain: nobody receives mail) and invitation emails are
suppressed. Passwords are generated here and stored only in ~/.job-hunter-eval/accounts.json (mode 600).
Each account gets one persona: profile basics, a profile bank (experience, education, project, skills),
a confirmation (which queues the profile embedding) and job preferences. Seeding is skipped for an
account whose bank already has items, so the script is safe to rerun.

Run from the repository root with the evaluation virtualenv (boto3) and an operator SSO session:
    AWS_PROFILE=<sso profile> python eval/seed_accounts.py
Delete the accounts after the project: see eval/README.md.
"""
from __future__ import annotations

import json
import os
import secrets
import string
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))
import cognito_tokens as ct  # noqa: E402
from job_hunter.profile_bank.skills import infer_skill_category  # noqa: E402

USER_POOL_ID = os.environ.get("EVAL_USER_POOL_ID", "ap-southeast-1_rqE5iKEpf")
FICTIONAL = "(fictional)"


def _bullets(*texts: str) -> list[dict]:
    return [{"id": f"b_{uuid4().hex[:10]}", "text": text, "tags": []} for text in texts]


def _persona(name, headline, summary, jobs, degree, project, skills, roles, seniority):
    items = [{"kind": "experience", "data": {"title": title, "organisation": f"{org} {FICTIONAL}", "start": start,
                                             "end": end, "current": end is None, "bullets": _bullets(*bullets)}}
             for title, org, start, end, bullets in jobs]
    items.append({"kind": "education", "data": {"qualification": degree, "institution": f"Example University {FICTIONAL}",
                                                "start": "2016", "end": "2020", "current": False, "bullets": []}})
    items.append({"kind": "project", "data": {"name": project[0], "bullets": _bullets(project[1])}})
    items += [{"kind": "skill", "data": {"name": skill, "category": infer_skill_category(skill)}} for skill in skills]
    profile = {"name": name, "display_name": name, "email": f"{name.lower().replace(' ', '.')}@example.invalid",
               "phone": "", "location": "Singapore", "headline": headline, "summary": summary}
    preferences = {"roles": roles, "locations": ["Singapore"], "work_modes": [],  # most sources state no work mode, and unstated modes are filtered out
                   "seniority": seniority, "salary_min": None, "salary_currency": "SGD", "salary_period": "year"}
    return {"profile": profile, "items": items, "preferences": preferences}


PERSONAS = [
    _persona("Mei Lin Tan", "Data Engineer", "Data engineer with three years building batch and streaming pipelines on AWS.",
             [("Data Engineer", "Harbourline Analytics", "2022", None, [
                 "Built Airflow pipelines loading 40 million rows a day into a PostgreSQL warehouse.",
                 "Moved nightly ETL jobs to AWS Glue and Lambda, cutting run time by half."]),
              ("Data Analyst", "Lion City Retail", "2020", "2022", [
                 "Wrote SQL models and Tableau dashboards for weekly sales reporting."])],
             "BSc in Computer Science", ("Event pipeline", "Kafka to S3 pipeline with schema checks and replay."),
             ["Python", "SQL", "Airflow", "AWS", "PostgreSQL", "Spark", "dbt", "Docker"], ["Data Engineer"], "junior"),
    _persona("Arjun Nair", "Backend Software Engineer", "Backend engineer focused on Python and Go services and APIs.",
             [("Software Engineer", "Kampong Payments", "2021", None, [
                 "Designed REST and gRPC services in Go handling 2,000 requests a second.",
                 "Introduced contract tests and cut production incidents by a third."]),
              ("Junior Developer", "Marina Web Studio", "2019", "2021", [
                 "Built Django features and maintained CI pipelines."])],
             "BEng in Computer Engineering", ("Rate limiter", "Open-source token-bucket rate limiter for Go services."),
             ["Go", "Python", "Django", "PostgreSQL", "Kubernetes", "Docker", "gRPC", "Redis"], ["Software Engineer", "Backend Engineer"], "mid"),
    _persona("Siti Rahman", "Data Analyst", "Analyst who turns operational data into dashboards and experiments.",
             [("Data Analyst", "Orchard Health Group", "2021", None, [
                 "Built Power BI dashboards used by 120 clinic managers.",
                 "Ran A/B test analysis for appointment reminders, raising attendance by 6 percent."])],
             "BSc in Statistics", ("Churn study", "Logistic-regression churn model in Python with a written report."),
             ["SQL", "Excel", "Power BI", "Python", "pandas", "Statistics", "Tableau"], ["Data Analyst", "Business Analyst"], "junior"),
    _persona("Daniel Wong", "Frontend Developer", "Frontend developer building accessible React and TypeScript apps.",
             [("Frontend Developer", "Tanjong Travel", "2020", None, [
                 "Rebuilt the booking flow in React and TypeScript, improving conversion by 9 percent.",
                 "Set up Playwright tests and an accessibility checklist for every release."])],
             "Diploma in Information Technology", ("Design system", "Component library with Storybook and visual tests."),
             ["JavaScript", "TypeScript", "React", "CSS", "HTML", "Playwright", "Figma"], ["Frontend Developer", "Software Engineer"], "mid"),
    _persona("Priya Menon", "Cloud and DevOps Engineer", "DevOps engineer running Kubernetes and Terraform on AWS.",
             [("DevOps Engineer", "Straits Logistics", "2019", None, [
                 "Managed 30 AWS accounts with Terraform and GitHub Actions.",
                 "Moved services to EKS with autoscaling, cutting compute cost by 25 percent."]),
              ("System Administrator", "Bugis IT Services", "2017", "2019", [
                 "Automated Linux server patching with Ansible."])],
             "BEng in Electrical Engineering", ("Cost dashboard", "Cost Explorer dashboard with budget alerts per team."),
             ["AWS", "Terraform", "Kubernetes", "Docker", "Linux", "Python", "CI/CD", "Ansible"], ["DevOps Engineer", "Cloud Engineer"], "senior"),
    _persona("Hafiz Ismail", "Business Analyst", "Business analyst bridging operations teams and software delivery.",
             [("Business Analyst", "Raffles Insurance", "2021", None, [
                 "Wrote requirements and user stories for a claims portal used by 5,000 agents.",
                 "Mapped claim processes and removed two manual hand-offs."])],
             "BBA in Business Analytics", ("Process map", "End-to-end claims process map with improvement proposals."),
             ["Requirements analysis", "SQL", "Excel", "Jira", "Process mapping", "Stakeholder management"], ["Business Analyst", "Product Analyst"], "junior"),
]


def _password() -> str:
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits, "!@#%^*-_=+"]
    chars = [secrets.choice(pool) for pool in pools] + [secrets.choice("".join(pools)) for _ in range(20)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def ensure_accounts(count: int) -> dict[str, dict]:
    import boto3

    store = ct.ACCOUNTS_FILE
    store.parent.mkdir(mode=0o700, exist_ok=True)
    accounts = json.loads(store.read_text()) if store.exists() else {}
    cognito = boto3.client("cognito-idp", region_name="ap-southeast-1")
    for number in range(1, count + 1):
        email = f"jh-eval-{number:02d}@example.com"
        if email in accounts:
            continue
        password = _password()
        cognito.admin_create_user(UserPoolId=USER_POOL_ID, Username=email, MessageAction="SUPPRESS",
                                  UserAttributes=[{"Name": "email", "Value": email},
                                                  {"Name": "email_verified", "Value": "true"}])
        cognito.admin_set_user_password(UserPoolId=USER_POOL_ID, Username=email, Password=password, Permanent=True)
        accounts[email] = {"password": password}
        store.write_text(json.dumps(accounts, indent=2))
        os.chmod(store, 0o600)
        print(f"created {email}")
    return accounts


def _call(token: str, path: str, body=None, method: str | None = None) -> dict:
    request = Request(ct.API_BASE + path, method=method or ("POST" if body is not None else "GET"),
                      data=None if body is None else json.dumps(body).encode(),
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def seed(email: str, password: str, persona: dict) -> str:
    token = ct.login(email, password)["access_token"]
    if _call(token, "/profile/bank")["items"]:
        return "already seeded"
    profile = _call(token, "/profile")
    _call(token, "/profile", {"draft": persona["profile"], "expected_revision": profile["revision"]}, "PUT")
    for item in persona["items"]:
        _call(token, "/profile/items", item)
    bank = _call(token, "/profile/bank")
    _call(token, "/profile/confirm", {"expected_bank_revision": bank["bank_revision"]})
    preferences = _call(token, "/preferences")
    _call(token, "/preferences", {**persona["preferences"], "expected_revision": preferences["revision"]}, "PUT")
    return f"seeded as {persona['profile']['headline']} ({len(persona['items'])} bank items)"


if __name__ == "__main__":
    accounts = ensure_accounts(len(PERSONAS))
    for (email, account), persona in zip(sorted(accounts.items()), PERSONAS):
        print(f"{email}: {seed(email, account['password'], persona)}")
