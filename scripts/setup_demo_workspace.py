"""Explicitly reset Alice's local demo profile and hide named QA resumes.
Run inside the local API container with this script mounted. Existing unrelated
documents are preserved. Archived QA records/exports remain recoverable in DB.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from job_hunter.config import settings
from job_hunter.domain.identity import DEV_USERS
from job_hunter.domain.models import Document
from job_hunter.demo import PROFILE, CONTENT

assert settings.app_env == "local", "Local demo only"
base = "http://api:8000/v1"
def call(path, body=None, method=None):
    req = Request(base + path, data=None if body is None else json.dumps(body).encode(),
                  headers={"X-Dev-User": "alice", "Content-Type": "application/json"},
                  method=method or ("POST" if body is not None else "GET"))
    with urlopen(req, timeout=30) as response:
        return json.load(response)

old_profile = call("/profile")
docs = call("/documents?kind=resume")["items"]
apps = call("/applications")["items"]
backup = Path("/data/demo-backups")
backup.mkdir(exist_ok=True)
snapshot = backup / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + ".json")
snapshot.write_text(json.dumps({"profile": old_profile, "documents": docs, "applications": apps}, indent=2))
call("/profile", {"draft": PROFILE, "expected_revision": old_profile["revision"]}, "PUT")
target = next(a for a in apps if a["job"]["title"] == "Backend Engineer" and a["job"]["company"] == "Meridian Labs")
title = "Alex Tan — Backend Engineer"
doc = next((d for d in docs if d["title"] == title), None)
if doc is None:
    doc = call("/documents", {"title": title, "template": "modern", "content": CONTENT,
                             "job_id": target["job_id"],
                             "layout": {"font_size": 10, "margin": 15, "font_family": "sans", "line_spacing": 1.15, "page_size": "A4"}})
call("/documents/" + doc["id"] + "/review", {"expected_revision": doc["revision"]})
call("/applications/" + target["job_id"], {
    "expected_revision": target["revision"], "status": "applied",
    "applied_at": "2026-10-05T01:00:00Z",
    "notes": "Fictional demonstration application. Nothing was submitted to an employer.",
    "resume_document_id": doc["id"], "expected_resume_revision": doc["revision"],
    "cover_letter_text": "Dear Meridian Labs hiring team,\n\nI am applying for the Backend Engineer role. My experience combines Python API development, PostgreSQL data modelling and dependable analytics pipelines. At Harbour Metrics, I built FastAPI services, added ownership checks and migrations, and established unit and integration testing.\n\nMy portfolio includes a containerized model-serving API and a job-discovery pipeline with repeatable imports. I would bring a practical approach to reliable data services and clear collaboration with product and analytics teams.\n\nThank you for considering my application.\n\nAlex Tan\n\nFictional demonstration letter; not submitted."
}, "PUT")
prefixes = ("Synthetic integration test resume", "Demo — SQL analyst (fictional)", "Demo — ML engineer (fictional)")
names = {"RLS context test", "Tenant isolation test", "Synthetic preparation context test"}
engine = create_engine(settings.database_url)
with Session(engine) as db, db.begin():
    db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(DEV_USERS["alice"][0])})
    archived = []
    for d in db.scalars(select(Document).where(Document.user_id == DEV_USERS["alice"][0], Document.kind == "resume")):
        if d.title in names or d.title.startswith(prefixes):
            d.kind = "archived_test"
            archived.append(d.title)
print(json.dumps({"archived_test_resumes": len(archived), "resume": title, "application": "Backend Engineer", "backup": str(snapshot)}))
